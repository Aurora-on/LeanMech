# pipeline1

面向力学题自动形式化与 Lean 校验的基线流水线。

当前代码把自然语言题目送入 `A -> B -> C -> D -> E -> F` 流程，输出结构化 `Problem IR`、Lean 定理候选、编译与语义验证结果、证明尝试日志，以及可直接打开的 Lean 导出工作区。项目重点是“可跑通、可回放、可诊断”，而不是训练框架或通用 agent 平台。

## 1. 项目定位

本项目当前解决的是一个可验证的 baseline 问题：

- 从题面中抽取物理对象、已知量、未知目标、约束与物理规律。
- 生成 Lean theorem 候选，并在真实 Lean 环境中做编译检查。
- 用规则和 LLM 联合做语义筛选，必要时把反馈回送给 B 阶段重生候选。
- 对最终候选做 Lean 证明生成与修复。
- 将整次运行归档为可复盘的日志、报告和 Lean 文件。

## 2. 当前主流程

主入口：

```powershell
mech-baseline run --config <config>.yaml
```

等价调用：

```powershell
$env:PYTHONPATH = "src"
python -m mech_pipeline.cli run --config <config>.yaml
```

当前主流程如下：

```text
输入样本
  -> A Grounding
  -> MechLib 检索
  -> B Statement Generation
  -> C Lean Compile Check
  -> D Semantic Rank
  -> E Proof Search / Repair
  -> F Metrics / Analysis / Export
```

其中真正的控制逻辑在 [src/mech_pipeline/cli.py](src/mech_pipeline/cli.py)：

1. 读取并校验 YAML 配置。
2. 构建 `runs/<timestamp>_<tag>/`。
3. 加载数据源。
4. 构建模型客户端、LeanRunner、MechLibRetriever 和 A-F 各模块。
5. 可选执行 Lean preflight。
6. 逐题或并发执行样本流程。
7. 聚合阶段日志、指标、分析报告和 Lean 导出文件。
8. 将整次 run 复制到 `outputs/latest/`。

## 3. 各模块职责

### A. Grounding

文件：[src/mech_pipeline/modules/A_grounding.py](src/mech_pipeline/modules/A_grounding.py)

职责：

- 从题面抽取 `Problem IR`。
- 规范化 `known_quantities`、`unknown_target`、`physical_laws`、`constraints` 等字段。
- 图文题优先尝试 vision；失败时退回纯文本抽取。

### B. Statement Generation

文件：[src/mech_pipeline/modules/B_statement_gen.py](src/mech_pipeline/modules/B_statement_gen.py)

职责：

- 根据 `Problem IR` 和可选的 MechLib 上下文生成 Lean theorem 候选。
- round 0 使用 [prompts/B_generate_statements.txt](prompts/B_generate_statements.txt)。
- revision round 使用 [prompts/B_revise_statements.txt](prompts/B_revise_statements.txt)。
- 做本地规范化，例如小数字面量规范化、合法标识符修复、希腊字母标识符转 ASCII。

当前行为有两个关键点：

- 目标仍然是生成 4 个候选，但最终只保留“可用候选”。
- **已经不再生成伪造的 fallback theorem**，也不再用克隆候选去硬补满 4 个位置。

也就是说，B 阶段现在宁可返回较少的真实候选，也不会再制造 `fallback_goal` 这一类无研究价值的占位命题。

### C. Lean Compile Check

文件：[src/mech_pipeline/modules/C_compile_check.py](src/mech_pipeline/modules/C_compile_check.py)

职责：

- 逐个候选调用 LeanRunner 编译。
- 记录 `compile_pass`、`syntax_ok`、`elaboration_ok`、`backend_used`、`route_reason` 等结果。
- 不引入额外 LLM 评审，只基于 Lean 输出提取更细的错误信息。

当前会额外保存：

- `stderr_excerpt`
- `error_line`
- `error_message`
- `error_snippet`
- `sub_error_type`
- `failure_summary`

首批规则化细标签包括：

- `symbol_hallucination`
- `wrong_api_shape`
- `namespace_or_import_issue`
- `type_mismatch`
- `invalid_decl_shape`
- `timeout_or_tooling_block`

### D. Semantic Rank

文件：[src/mech_pipeline/modules/D_semantic_rank.py](src/mech_pipeline/modules/D_semantic_rank.py)  
Prompt：[prompts/D_semantic_rank.txt](prompts/D_semantic_rank.txt)

职责：

- 只对编译通过的候选做语义排序。
- 联合规则分数、LLM 语义判断和 proofability bias 选出最终候选。
- 输出可回流给 B 的细粒度语义反馈。

当前 D 阶段已经支持区分“表面形式不同但语义等价”和“真正 target drift”。  
`target_relation` 目前使用以下分类：

- `exact`
- `equivalent`
- `special_case`
- `weaker`
- `drift`

其中：

- `exact` / `equivalent` 可以进入通过路径。
- `special_case` / `weaker` / `drift` 会被当作真正的目标偏移或不足。

LLM 输出会被结构化保存，重点字段包括：

- `failure_summary`
- `failure_tags`
- `mismatch_fields`
- `missing_or_incorrect_translations`
- `suggested_fix_direction`
- `sub_error_type`

这部分是当前闭环质量提升的核心。

### E. Proof Search / Repair

文件：[src/mech_pipeline/modules/E_prover.py](src/mech_pipeline/modules/E_prover.py)  
Prompts：

- [prompts/E_generate_proof.txt](prompts/E_generate_proof.txt)
- [prompts/E_repair_proof.txt](prompts/E_repair_proof.txt)

职责：

- 对 D 最终选中的 theorem 生成 Lean proof body。
- 若失败，则依据 Lean 报错做 proof repair。
- 用 LeanRunner 做真实 proof verify。

当前行为已经与早期版本不同：

- **已经停用无意义的 deterministic bare tactic fallback**。
- 不再自动追加 `rfl`、`simp`、`aesop`、`linarith`、`ring` 之类的裸 tactic 尝试。
- 如果模型没有给出可用 proof body，也不会再伪造 `trivial` 证明。

同时：

- E 只会在最终轮 `semantic_pass = true` 时运行。
- 如果最终轮语义失败，proof 会被记为 `proof_skipped_due_to_semantic_fail`。

E 阶段目前也会落盘更细的规则化错误信息，但**不会回流到 B**。

### F. Metrics / Analysis / Export

文件：[src/mech_pipeline/modules/F_report.py](src/mech_pipeline/modules/F_report.py)

职责：

- 汇总最终轮结果。
- 计算阶段成功率、错误分布和闭环使用率。
- 生成：
  - `metrics.json`
  - `analysis.md`
  - run 级 `README.md`
  - Lean 导出工作区

## 4. B/C/D 闭环机制

当前闭环只作用于 `B -> C -> D`，最多一轮 revision。

控制逻辑：

```text
Round 0: B -> C -> D
若失败:
  反馈打包 -> B(revise) -> C -> D
Round 1 作为最终轮
```

只在以下情况触发 revision：

- `C` 阶段没有任何候选编译通过  
  `retry_reason = "no_compile_pass"`
- `C` 阶段有候选编译通过，但 `D.semantic_pass = false`  
  `retry_reason = "semantic_fail"`

当前反馈包包含：

- 轮次摘要
  - `retry_reason`
  - `compile_pass_count`
  - `semantic_pass`
  - `selected_candidate_id`
- C 阶段详细编译错误
  - `error_type`
  - `sub_error_type`
  - `failure_summary`
  - `stderr_excerpt`
  - `error_line`
  - `error_message`
  - `error_snippet`
- D 阶段详细语义反馈
  - `semantic_score`
  - `target_relation`
  - `failure_tags`
  - `mismatch_fields`
  - `missing_or_incorrect_translations`
  - `suggested_fix_direction`
  - `hard_gate_reasons`

注意：

- 闭环只回送结构化摘要，不会把完整长日志直接塞回 prompt。
- 最终 `metrics.json` 只按最终轮统计，不会把 round 0 的失败重复计入指标。

## 5. 并发与实时进度

当前已经支持题目级并发执行。

配置项：

```yaml
runtime:
  sample_concurrency: 4
```

也可以用 CLI 覆盖：

```powershell
python -m mech_pipeline.cli run --config <config>.yaml --sample-concurrency 4
```

实现方式：

- 并发粒度是“题目”，不是候选或 proof attempt。
- 单题内部仍保持 `A -> B -> C -> D -> E` 顺序。
- 主线程按输入顺序汇总最终结果。
- 并发上限当前限制为 **10**。

运行时会输出题目级进度：

```text
progress: 0/40 completed, sample_concurrency=10
progress: 7/40 completed, sample=<sample_id>
progress: 40/40 completed
```

并发模式下采用真实完成顺序刷新，不会因为前面某一题较慢而卡住后续进度显示。

如果你在 IDE 输出面板里看不到实时刷新，优先使用：

```powershell
python -u -m mech_pipeline.cli run --config <config>.yaml --sample-concurrency 4
```

仓库还提供了 VS Code 启动配置：

- [.vscode/launch.json](.vscode/launch.json)
- [.vscode/tasks.json](.vscode/tasks.json)

这些配置会强制使用 `integratedTerminal` 与无缓冲输出。

## 6. Lean / MechLib / Mathlib 适配

### LeanRunner

文件：[src/mech_pipeline/adapters/lean_runner.py](src/mech_pipeline/adapters/lean_runner.py)

当前支持：

- `physlean` / `mechlib` 两类 backend
- `auto_by_import` / `force_physlean` / `force_mechlib`
- route fallback
- preflight 检查

preflight 现在按配置中的 `root_dir` 解析相对路径，不再错误地基于当前工作目录拼接。

### 导出 Lean 工作区

每次 run 完成后都会生成：

- `runs/<run>/lean_exports/`
- `outputs/latest/lean_exports/`

其中包含：

- `lean-toolchain`
- `lakefile.toml`
- `lake-manifest.json`（若本地 package cache 可用）
- `RunArtifacts.lean`
- `README.md`
- `index.json`
- `problems/*.lean`

设计目的：

- 每道题单独导出为一份 `.lean` 文件。
- 直接把 `lean_exports/` 当成 Lean workspace 打开。
- 避免单独打开 `runs/.../*.lean` 时出现 `import MechLib` 无法解析的问题。

当前导出逻辑会显式加入：

- 本地 `MechLib`
- 如 PhysLean `.lake/packages/mathlib` 存在，则显式加入 `mathlib`

根项目本身的 [lakefile.toml](lakefile.toml) 也已显式声明本地 `mathlib` 路径依赖。

## 7. 数据源

支持三类数据源：

- `lean4phys`
- `local_archive`
- `phyx`

### lean4phys

文件：[src/mech_pipeline/adapters/lean4phys.py](src/mech_pipeline/adapters/lean4phys.py)

默认配置使用本地 `LeanPhysBench_v0.json`。  
在当前这台机器上，`mechanics` 子集是最常用的评测对象。

### local_archive

文件：[src/mech_pipeline/adapters/local_archive.py](src/mech_pipeline/adapters/local_archive.py)

支持：

- `text_only`
- `image_text`

当前 `image_text` 默认仍按 MVP 路径工作，样本图像处理能力是保守实现。

### phyx

文件：[src/mech_pipeline/adapters/phyx.py](src/mech_pipeline/adapters/phyx.py)

支持从多个 parquet URL 顺序尝试加载。

## 8. 关键配置项

配置定义在 [src/mech_pipeline/config.py](src/mech_pipeline/config.py)。

主要字段：

```yaml
dataset:
  source: lean4phys
  limit: 10
  sample_policy: index_head
  seed: 42

model:
  provider: openai_compatible
  model_id: gpt-5.4
  base_url: null
  api_key_env: OPENAI_API_KEY

lean:
  enabled: true
  preflight_enabled: true
  physlean_dir: F:/AI4Mechanics/PhysLean-master
  mechlib_dir: F:/AI4Mechanics/coding/MechLib
  route_policy: auto_by_import
  default_backend: mechlib
  route_fallback: true

knowledge:
  enabled: true
  scope: mechanics_si
  top_k: 6
  inject_modules: [B]

statement:
  library_target: mechlib
  with_mechlib_context: true
  feedback_loop_enabled: true
  max_revision_rounds: 1

semantic:
  pass_threshold: 0.7

proof:
  max_attempts: 2

runtime:
  sample_concurrency: 1
```

当前校验规则中最重要的几项：

- `runtime.sample_concurrency` 必须在 `1..10`
- `statement.max_revision_rounds >= 0`
- `semantic.pass_threshold` 必须在 `[0, 1]`
- 多个路径字段会做乱码嫌疑检测
- YAML 按 `utf-8-sig` 读取

## 9. 快速开始

### 9.1 安装

```powershell
pip install -e .[dev]
```

### 9.2 dry-run

```powershell
$env:PYTHONPATH = "src"
python -m mech_pipeline.cli run --config configs/default_mechanics73_openai.yaml --dry-run --limit 1 --tag dryrun-check
```

作用：

- 验证 CLI、配置加载和输出目录创建。
- 不调用模型。
- 不执行 Lean 编译和证明。

### 9.3 单题或小样本真实运行

仓库中保留了几组可复用配置：

- [configs/default_mechanics73_openai.yaml](configs/default_mechanics73_openai.yaml)
- [configs/mechanics73_plus3_openai_gpt54.yaml](configs/mechanics73_plus3_openai_gpt54.yaml)
- [configs/mechanics73_plus3_proxy_gpt54.yaml](configs/mechanics73_plus3_proxy_gpt54.yaml)
- [configs/full_run_openai_proxy_lean.yaml](configs/full_run_openai_proxy_lean.yaml)

配套 bench：

- [fixtures/bench_mechanics73.json](fixtures/bench_mechanics73.json)
- [fixtures/bench_mechanics73_plus3_seed20260330.json](fixtures/bench_mechanics73_plus3_seed20260330.json)
- [fixtures/bench_mechanics73_plus3_seed2026033001.json](fixtures/bench_mechanics73_plus3_seed2026033001.json)

示例：

```powershell
$env:PYTHONPATH = "src"
$env:OPENAI_API_KEY = "<your-key>"
python -u -m mech_pipeline.cli run --config configs/mechanics73_plus3_openai_gpt54.yaml --sample-concurrency 4 --tag demo
```

如果你使用兼容代理：

```yaml
model:
  provider: openai_compatible
  model_id: gpt-5.4
  base_url: "https://api.openai-proxy.org/v1"
  api_key_env: OPENAI_PROXY_KEY
```

不要把 API key 直接写进仓库文件。

## 10. 输出文件说明

每次运行都会写入 `runs/<timestamp>_<tag>/`，并复制到 `outputs/latest/`。

阶段日志：

- `problem_ir.jsonl`
- `mechlib_retrieval.jsonl`
- `statement_candidates.jsonl`
- `compile_checks.jsonl`
- `semantic_rank.jsonl`
- `proof_attempts.jsonl`
- `proof_checks.jsonl`
- `sample_summary.jsonl`

聚合结果：

- `metrics.json`
- `analysis.md`
- `README.md`
- `config.json`
- `manifest.json`

Lean 导出：

- `lean_exports/README.md`
- `lean_exports/index.json`
- `lean_exports/problems/*.lean`

当前一些关键字段的含义：

- `sample_summary.jsonl`
  - 每题最终结果
  - `final_round_index`
  - `feedback_loop_used`
  - `final_error_type`
  - `sub_error_type`
  - `failure_summary`
- `semantic_rank.jsonl`
  - 语义排序全量信息
  - `target_relation`
  - `mismatch_fields`
  - `missing_or_incorrect_translations`
  - `suggested_fix_direction`
- `proof_attempts.jsonl`
  - 每次证明尝试的原始响应、Lean 校验结果和规则化错误信息

## 11. 测试

单元和 smoke 测试使用 `pytest`，临时文件统一写到：

- `tmp/pytest/cache`
- `tmp/pytest/basetemp`

运行示例：

```powershell
python -m pytest -q
```

当前仓库已经覆盖的重点包括：

- B 阶段候选规范化与反 trivial 规则
- D 阶段 target equivalence / drift 区分
- E 阶段无意义 fallback 停用
- 并发执行
- 实时 progress 输出
- Lean 导出工作区
- 配置校验

## 12. 当前限制

以下限制仍然存在：

- 很多示例配置仍然带有本机绝对路径，换机器前必须先改：
  - `lean.physlean_dir`
  - `lean.mechlib_dir`
  - `dataset.lean4phys.bench_path`
  - `knowledge.summary_corpus_path`
- `D` 和 `E` 仍然是 baseline 质量，不代表题目语义理解或证明搜索已经足够强。
- `competition` 子集整体仍然明显弱于 `university` 子集。
- 闭环目前只做一轮，且只覆盖 `B/C/D`，不扩展到 `E`。
- `local_archive` 的图文路径仍是保守实现，不是通用多图系统。

## 13. 推荐阅读顺序

如果你要快速理解当前代码，建议按以下顺序读：

1. [src/mech_pipeline/cli.py](src/mech_pipeline/cli.py)
2. [src/mech_pipeline/config.py](src/mech_pipeline/config.py)
3. [src/mech_pipeline/modules/B_statement_gen.py](src/mech_pipeline/modules/B_statement_gen.py)
4. [src/mech_pipeline/modules/D_semantic_rank.py](src/mech_pipeline/modules/D_semantic_rank.py)
5. [src/mech_pipeline/modules/E_prover.py](src/mech_pipeline/modules/E_prover.py)
6. [src/mech_pipeline/adapters/lean_runner.py](src/mech_pipeline/adapters/lean_runner.py)

## 14. 当前版本的关键变化

相较于项目早期版本，当前 README 对应的真实代码状态是：

- B 阶段已删除伪造 fallback theorem。
- D 阶段已经能区分“表面形式不同但语义等价”和“真正 target drift”。
- E 阶段已停用无意义的 bare tactic fallback。
- `B/C/D` 已支持一轮结构化 feedback 闭环。
- 已支持题目级并发和实时进度输出。
- 每次 run 都会导出可直接打开的 Lean 工作区。

