# pipeline1

面向力学题自动形式化的基线流水线。项目把自然语言题目送入 LLM，生成结构化 `Problem IR`、Lean 定理候选、Lean 编译检查、语义筛选和证明尝试，并把整次运行归档为可复盘的 stage 日志。

当前主流程是：

`输入样本 -> A Grounding -> B Statement Generation -> C Lean Compile Check -> D Semantic Rank -> E Proof Search/Repair -> F Metrics & Report`

在当前代码中，`B/C/D` 已支持一轮失败后闭环重试：

`B -> C -> D -> feedback -> B(revise) -> C -> D -> E`

只有最终轮会进入 `E` 和最终指标统计；第 0 轮保留用于日志和诊断。

## 1. 项目目标

这个仓库当前解决的是一个可跑通、可复盘的 baseline 问题，而不是训练框架或通用 agent 平台：

- 从题面中抽取物理量、目标量和物理规律。
- 生成多个 Lean theorem 候选，并用真实 Lean 环境筛掉无法编译的候选。
- 用规则 + LLM 做语义筛选，并在失败时把错误反馈回送给 B 阶段重生候选。
- 对最终候选做 proof generation / repair，并输出结构化运行记录。

## 2. 运行机制

### 2.1 总体控制流

CLI 入口是：

```powershell
mech-baseline run --config <config>.yaml
```

实际执行链路在 [src/mech_pipeline/cli.py](/f:/AI4Mechanics/coding/pipeline1/src/mech_pipeline/cli.py)：

1. 读取并校验 YAML 配置。
2. 建立 `runs/<timestamp>_<tag>/` 和 `outputs/latest/`。
3. 构建数据集 adapter。
4. `--dry-run` 时只创建目录和基础汇总，不执行 A-F。
5. 非 dry-run 时构建 model client、LeanRunner、MechLibRetriever 和各阶段模块。
6. 若 `lean.enabled=true` 且 `preflight_enabled=true`，先对 `PhysLean` / `MechLib` 做 `lake env lean` 预检。
7. 对每个样本执行 A 阶段、知识检索、B/C/D 主流程。
8. 若满足闭环条件，则把上一轮 C/D 反馈打包后回送给 B 再跑一轮。
9. 仅对最终轮 `semantic_pass=true` 的样本执行 E 阶段。
10. F 阶段汇总 `metrics.json`、`analysis.md`、`sample_summary.jsonl` 和运行级 README。

### 2.2 A-F 各阶段

#### A. Grounding

文件：[src/mech_pipeline/modules/A_grounding.py](/f:/AI4Mechanics/coding/pipeline1/src/mech_pipeline/modules/A_grounding.py)

职责：

- 读取题面文本、选项、图像或图像描述。
- 调用模型抽取 `Problem IR`。
- 规范化 `physical_laws`、`known_quantities`、`unknown_target` 等字段。
- 做基础防泄漏清理，避免把基准答案直接喂回后续 prompt。

#### B. Statement Generation

文件：[src/mech_pipeline/modules/B_statement_gen.py](/f:/AI4Mechanics/coding/pipeline1/src/mech_pipeline/modules/B_statement_gen.py)

职责：

- 为每个样本生成 4 个 Lean theorem 候选。
- 可注入 MechLib 检索上下文，帮助模型对齐命名、导入和风格。
- 对高风险输出做本地正规化和修补，例如数值字面量规范化、部分幻觉 API 修复、风险符号拦截。
- round 0 使用 [prompts/B_generate_statements.txt](/f:/AI4Mechanics/coding/pipeline1/prompts/B_generate_statements.txt)。
- revision round 使用 [prompts/B_revise_statements.txt](/f:/AI4Mechanics/coding/pipeline1/prompts/B_revise_statements.txt)。

#### C. Lean Compile Check

文件：[src/mech_pipeline/modules/C_compile_check.py](/f:/AI4Mechanics/coding/pipeline1/src/mech_pipeline/modules/C_compile_check.py)

职责：

- 对每个候选调用 LeanRunner。
- 按 import 和路由策略选择 `physlean` 或 `mechlib` backend。
- 输出编译是否通过、错误类型、后端、fallback 使用情况和日志路径。

#### D. Semantic Rank

文件：[src/mech_pipeline/modules/D_semantic_rank.py](/f:/AI4Mechanics/coding/pipeline1/src/mech_pipeline/modules/D_semantic_rank.py)

职责：

- 仅对编译通过的候选做语义排序。
- 综合规则分数、LLM 分数和 proofability bias。
- 拒绝 trivial goal、law drift、target mismatch、known quantity mismatch 等候选。
- 产出最终选中候选和完整 ranking。

#### E. Proof Search / Repair

文件：[src/mech_pipeline/modules/E_prover.py](/f:/AI4Mechanics/coding/pipeline1/src/mech_pipeline/modules/E_prover.py)

职责：

- 对 D 最终选中的 theorem 生成 Lean proof body。
- 若失败，基于 Lean 报错做 repair。
- LLM 尝试失败后，追加 deterministic fallback tactic。
- 当前只有最终轮 `semantic_pass=true` 的样本会进入 E。
- 若最终轮 `semantic_pass=false`，会直接记为 `proof_skipped_due_to_semantic_fail`。

#### F. Metrics & Report

文件：[src/mech_pipeline/modules/F_report.py](/f:/AI4Mechanics/coding/pipeline1/src/mech_pipeline/modules/F_report.py)

职责：

- 汇总最终轮样本结果。
- 计算阶段成功率、MechLib 采用率、错误分布和闭环使用率。
- 生成运行级分析文本和运行 README。

### 2.3 B/C/D 闭环机制

这是当前项目最重要的增量机制，控制逻辑在 [src/mech_pipeline/cli.py](/f:/AI4Mechanics/coding/pipeline1/src/mech_pipeline/cli.py)。

第 0 轮固定执行：

`B -> C -> D`

触发 revision 的条件只有两个：

- `C` 全部编译失败，`retry_reason = "no_compile_pass"`
- `C` 有通过项，但 `D.semantic_pass = false`，`retry_reason = "semantic_fail"`

触发后执行：

1. 把上一轮的 compile 结果和 semantic ranking 组装成结构化 feedback。
2. 把 feedback、上一轮候选和原始 `Problem IR` 一起送给 B 的 revise prompt。
3. 重新生成完整 4 个候选，再跑一轮 `C -> D`。
4. 第 1 轮作为最终轮；不会继续第 2 次 revision。

反馈包内容包括：

- 轮次摘要：`retry_reason`、`compile_pass_count`、`semantic_pass`、`selected_candidate_id`
- 候选级反馈：`candidate_id`、`theorem_decl`、`plan`
- 编译反馈：`compile_pass`、`error_type`、`stderr_digest`、`backend_used`、`route_reason`、`route_fallback_used`
- 对已进入 D 的候选补充：`semantic_score`、`semantic_pass`、`semantic_reason`、`back_translation_text`、`hard_gate_reasons`、`semantic_rank_score`

日志和统计规则：

- `statement_candidates.jsonl`、`compile_checks.jsonl`、`semantic_rank.jsonl`、`proof_checks.jsonl` 会写入所有轮次。
- 每条记录都带 `round_index`。
- `sample_summary.jsonl` 会带 `final_round_index` 和 `feedback_loop_used`。
- `metrics.json` 只按最终轮统计，不把第 0 轮失败重复计入成功率。

## 3. 数据源

### `lean4phys`

文件：[src/mech_pipeline/adapters/lean4phys.py](/f:/AI4Mechanics/coding/pipeline1/src/mech_pipeline/adapters/lean4phys.py)

用途：

- 从 Lean4Phys 风格 JSON benchmark 加载题目。
- 当前最常用的数据源。
- 仓库自带一个最小 fixture：[fixtures/bench_mechanics73.json](/f:/AI4Mechanics/coding/pipeline1/fixtures/bench_mechanics73.json)。

### `local_archive`

文件：[src/mech_pipeline/adapters/local_archive.py](/f:/AI4Mechanics/coding/pipeline1/src/mech_pipeline/adapters/local_archive.py)

用途：

- 从本地归档目录读取文本题或图文题。
- `text_only` 和 `image_text` 两种模式。
- 当前图文模式默认只支持单图样本。

### `phyx`

文件：[src/mech_pipeline/adapters/phyx.py](/f:/AI4Mechanics/coding/pipeline1/src/mech_pipeline/adapters/phyx.py)

用途：

- 从 parquet URL 拉取 PhyX mechanics 数据。
- 支持多个 URL 顺序 fallback。

## 4. 模型与外部依赖

### Python

要求：

- Python `>=3.10`
- `openai`
- `pandas`
- `pydantic`
- `pyarrow`
- `PyYAML`

安装：

```powershell
pip install -e .[dev]
```

如果暂时不想安装包，也可以直接用源码路径运行：

```powershell
$env:PYTHONPATH = "src"
python -m mech_pipeline.cli run --config <config>.yaml --dry-run --limit 1
```

### 模型 provider

当前只支持两类 provider：

- `mock`
- `openai_compatible`

`openai_compatible` 通过 OpenAI Python SDK 调兼容接口，关键字段是：

- `model.model_id`
- `model.base_url`
- `model.api_key` 或 `model.api_key_env`

如果你走官方 OpenAI：

```yaml
model:
  provider: openai_compatible
  model_id: gpt-5.4
  base_url: null
  api_key_env: OPENAI_API_KEY
```

如果你走兼容代理：

```yaml
model:
  provider: openai_compatible
  model_id: gpt-5.4
  base_url: "https://api.openai-proxy.org/v1"
  api_key_env: OPENAI_PROXY_KEY
```

不要把 API key 直接写进仓库文件。

### Lean / PhysLean / MechLib

若要执行真实编译与证明校验，还需要：

- 可用的 Lean4 / Lake
- 本地 `PhysLean` 仓库
- 本地 `MechLib` 仓库

配置中的很多样例路径仍然是作者机器上的绝对路径，例如：

- `F:/AI4Mechanics/PhysLean-master`
- `F:/AI4Mechanics/coding/MechLib`
- `F:/AI4Mechanics/数据集/归档`

换机器时必须先改这些路径。

## 5. 快速开始

### 5.1 先跑 dry-run

最稳妥的第一步是先确认 CLI、配置加载和输出目录没问题：

```powershell
$env:PYTHONPATH = "src"
python -m mech_pipeline.cli run --config configs/default_mechanics73_openai.yaml --dry-run --limit 1 --tag dryrun-check
```

特点：

- 会创建 `runs/` 和 `outputs/latest/`
- 不调用模型
- 不执行 Lean 编译和证明

### 5.2 跑 Mechanics73 fixture

仓库内置的最小样本配置是：

[configs/default_mechanics73_openai.yaml](/f:/AI4Mechanics/coding/pipeline1/configs/default_mechanics73_openai.yaml)

运行前请先检查：

- `dataset.lean4phys.bench_path`
- `lean.physlean_dir`
- `lean.mechlib_dir`
- `knowledge.summary_corpus_path`

示例：

```powershell
$env:PYTHONPATH = "src"
$env:OPENAI_PROXY_KEY = "<your-key>"
python -m mech_pipeline.cli run --config configs/default_mechanics73_openai.yaml --limit 1 --tag mechanics73-real
```

### 5.3 跑自定义 4 题 benchmark

仓库里现在保留了一组可复用的 4 题样本：

- bench: [fixtures/bench_mechanics73_plus3_seed20260330.json](/f:/AI4Mechanics/coding/pipeline1/fixtures/bench_mechanics73_plus3_seed20260330.json)
- 代理配置: [configs/mechanics73_plus3_proxy_gpt54.yaml](/f:/AI4Mechanics/coding/pipeline1/configs/mechanics73_plus3_proxy_gpt54.yaml)
- 官方 OpenAI 配置: [configs/mechanics73_plus3_openai_gpt54.yaml](/f:/AI4Mechanics/coding/pipeline1/configs/mechanics73_plus3_openai_gpt54.yaml)

这组 bench 固定包含 `Mechanics73`，并附带 3 道按固定 seed 选出的 mechanics 题，适合做小规模真实 API 回归。

示例：

```powershell
$env:PYTHONPATH = "src"
$env:OPENAI_PROXY_KEY = "<your-key>"
python -m mech_pipeline.cli run --config configs/mechanics73_plus3_proxy_gpt54.yaml
```

### 5.4 常用参数

```powershell
mech-baseline run --config <config>.yaml --limit 10
mech-baseline run --config <config>.yaml --tag myrun
mech-baseline run --config <config>.yaml --dry-run
```

含义：

- `--limit` 覆盖配置中的样本数
- `--tag` 覆盖输出标签
- `--dry-run` 只建运行骨架，不执行实际阶段

## 6. 配置说明

配置定义在 [src/mech_pipeline/config.py](/f:/AI4Mechanics/coding/pipeline1/src/mech_pipeline/config.py)。

### `dataset`

- `source`: `local_archive` / `phyx` / `lean4phys`
- `limit`
- `sample_policy`: `index_head` / `seed_random`
- `seed`
- `lean4phys.bench_path`
- `local_archive.root`
- `single_image_only_for_mvp`

### `model`

- `provider`
- `model_id`
- `base_url`
- `api_key` / `api_key_env`
- `supports_vision`
- `timeout_s`
- `max_retries`

### `lean`

- `enabled`
- `physlean_dir`
- `mechlib_dir`
- `timeout_s`
- `preflight_enabled`
- `route_policy`: `auto_by_import` / `force_physlean` / `force_mechlib`
- `default_backend`
- `route_fallback`

### `knowledge`

- `enabled`
- `mechlib_dir`
- `scope`
- `top_k`
- `cache_path`
- `context_source`
- `summary_corpus_path`
- `inject_modules`: 当前支持 `B` / `D` / `E`

### `statement`

- `library_target`
- `with_mechlib_context`
- `feedback_loop_enabled`
- `max_revision_rounds`

### `semantic`

- `pass_threshold`

### `proof`

- `max_attempts`

### `prompts`

- `a_extract_ir`
- `b_generate_statements`
- `b_revise_statements`
- `d_semantic_rank`
- `e_generate_proof`
- `e_repair_proof`

### `output`

- `output.output_dir`
- `output.runs_dir`
- `output.tag`

## 7. MechLib 检索机制

文件：[src/mech_pipeline/knowledge/mechlib.py](/f:/AI4Mechanics/coding/pipeline1/src/mech_pipeline/knowledge/mechlib.py)

当前不是向量数据库，而是轻量混合检索：

- 从 `theorem_corpus.jsonl` 按领域标签读取 summary
- 从本地 MechLib `.lean` 文件抽取 declaration、import hint 和 proof 风格示例

随后把两部分拼成 prompt context，按 `inject_modules` 选择性注入到 B/D/E。

当前可确认的行为：

- 领域标签优先来自 A 阶段抽取的 `physical_laws`
- 若 A 提供不稳定，则退回题面关键词匹配
- D 阶段存在轻微的 MechLib backend bias

## 8. 输出文件

每次运行都会创建：

- `runs/<timestamp>_<tag>/`
- `outputs/latest/`

`outputs/latest/` 会被最新一次运行覆盖，`runs/` 会保留历史结果。

当前主流程会写出这些文件：

- `problem_ir.jsonl`
- `mechlib_retrieval.jsonl`
- `statement_candidates.jsonl`
- `compile_checks.jsonl`
- `semantic_rank.jsonl`
- `proof_attempts.jsonl`
- `proof_checks.jsonl`
- `sample_summary.jsonl`
- `metrics.json`
- `analysis.md`
- `README.md`
- `config.json`
- `manifest.json`

另外还有两个非常实用的目录：

- `lean_compile/`: C 阶段的编译日志
- `lean_proof/`: E 阶段的 proof 验证日志

以及一个中间目录：

- `.pipeline1_tmp/compile/<backend>/`: 编译时实际写出的临时 Lean 文件
- `.pipeline1_tmp/proof/<backend>/`: proof 验证时实际写出的临时 Lean 文件

这两个目录对排查 “候选能过 C 但过不了 E” 很重要。

## 9. 指标说明

指标由 [src/mech_pipeline/eval/metrics.py](/f:/AI4Mechanics/coding/pipeline1/src/mech_pipeline/eval/metrics.py) 生成。

核心字段包括：

- `grounding_success_rate`
- `statement_generation_success_rate`
- `lean_compile_success_rate`
- `semantic_consistency_pass_rate`
- `proof_success_rate`
- `end_to_end_verified_solve_rate`
- `mechlib_header_rate`
- `mechlib_compile_pass_rate`
- `selected_mechlib_candidate_rate`
- `feedback_loop_used_rate`
- `error_type_distribution`

注意：

- `lean_compile_success_rate` 的分母是候选数，不是样本数。
- 最终指标只统计每个样本的最终轮。
- `feedback_loop_used_rate` 统计触发过 revision 的样本比例。

## 10. 测试

最简单的回归方式：

```powershell
pytest -q
```

如果只想先看 CLI 和关键阶段：

```powershell
pytest -q tests/test_cli_smoke.py tests/test_statement_normalization.py tests/test_semantic_rank.py
```

当前测试覆盖重点包括：

- 配置加载与校验
- CLI smoke
- LeanRunner 路径解析
- B 阶段正规化与修补
- D 阶段 guardrail / proofability bias
- B/C/D feedback loop 控制流

## 11. 常见问题

### `No module named mech_pipeline`

执行以下任一项：

```powershell
pip install -e .[dev]
```

或：

```powershell
$env:PYTHONPATH = "src"
```

### Lean preflight 失败

通常是以下原因之一：

- `lean.physlean_dir` 路径错误
- `lean.mechlib_dir` 路径错误
- 对应仓库缺少 `lakefile.toml` 或 `lean-toolchain`
- `lake env lean` 在对应仓库目录下无法执行

如果只是想先验证上游阶段，可以临时关闭：

```yaml
lean:
  enabled: false
  preflight_enabled: false
```

### `AuthenticationError` / `invalid_api_key`

请优先检查：

- `model.base_url` 是否和 key 类型匹配
- `model.api_key_env` 指向的环境变量是否存在
- 当前 key 是否有对应模型的访问权限

### Windows 中文乱码

CLI 会尝试切到 UTF-8。若仍然乱码，可先执行：

```powershell
chcp 65001
```

## 12. 当前限制

这些是当前代码层面可确认的限制：

- CLI 只有 `run` 一个子命令。
- provider 只有 `mock` 和 `openai_compatible`。
- 图文数据路径仍主要按 MVP 约束处理。
- B 阶段虽然加入了本地修补和 feedback loop，但仍会出现语义漂移和 fallback 候选。
- E 阶段仍是 baseline 级 proof 策略，对代数消元、分母讨论、ODE/微分几何类题目的稳定性不足。
- 多个样例配置仍包含作者机器的绝对路径，迁移到新机器前必须先改。

## 13. 建议阅读顺序

如果你准备继续开发这个项目，建议按下面顺序读代码：

1. [src/mech_pipeline/cli.py](/f:/AI4Mechanics/coding/pipeline1/src/mech_pipeline/cli.py)
2. [src/mech_pipeline/config.py](/f:/AI4Mechanics/coding/pipeline1/src/mech_pipeline/config.py)
3. [src/mech_pipeline/modules/A_grounding.py](/f:/AI4Mechanics/coding/pipeline1/src/mech_pipeline/modules/A_grounding.py)
4. [src/mech_pipeline/modules/B_statement_gen.py](/f:/AI4Mechanics/coding/pipeline1/src/mech_pipeline/modules/B_statement_gen.py)
5. [src/mech_pipeline/adapters/lean_runner.py](/f:/AI4Mechanics/coding/pipeline1/src/mech_pipeline/adapters/lean_runner.py)
6. [src/mech_pipeline/modules/D_semantic_rank.py](/f:/AI4Mechanics/coding/pipeline1/src/mech_pipeline/modules/D_semantic_rank.py)
7. [src/mech_pipeline/modules/E_prover.py](/f:/AI4Mechanics/coding/pipeline1/src/mech_pipeline/modules/E_prover.py)
8. [src/mech_pipeline/knowledge/mechlib.py](/f:/AI4Mechanics/coding/pipeline1/src/mech_pipeline/knowledge/mechlib.py)
