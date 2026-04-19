# pipeline1

`pipeline1` 是一个面向力学题自动形式化的基线系统。它将自然语言题目送入分阶段流水线，生成 Lean theorem 候选，在真实 Lean 环境中完成编译、语义筛选与证明验证，并将整次运行归档为可复查的结果目录。

当前仓库的重点不是训练框架，也不是通用 agent 平台，而是一个可运行、可回放、可诊断的研究型基线。

## 1. 项目目标

本项目当前解决的问题是：

- 从题面中抽取结构化物理语义，包括已知量、目标量、约束和物理规律。
- 生成 Lean theorem 候选，并在真实 Lean 环境中检查其可编译性。
- 对编译通过的候选做语义筛选，必要时将反馈回送到命题生成阶段。
- 为最终候选生成 Lean proof，并在 Lean 中验证。
- 将整次运行保存为日志、指标、分析报告和可直接打开的 Lean 工作区。

## 2. 主流程概览

主流程入口是：

```powershell
mech-baseline run --config <config>.yaml
```

等价的模块调用是：

```powershell
$env:PYTHONPATH = "src"
python -m mech_pipeline.cli run --config <config>.yaml
```

当前主流程为：

```text
输入样本
  -> A 结构化理解
  -> MechLib 检索
  -> B 候选命题生成
  -> C Lean 编译检查
  -> D 语义排序与筛选
  -> E 证明生成与修复
  -> F 指标汇总与结果导出
```

其中：

- A 负责把题面转成结构化 `Problem IR`
- B 负责生成 Lean theorem 候选
- C 负责在真实 Lean 中编译候选
- D 负责从可编译候选中选择语义最合适的 theorem
- E 负责构造并验证 proof
- F 负责生成 `metrics.json`、`analysis.md`、`README.md` 和 Lean 导出工作区

## 3. 模块间通信

这一节只说明当前主流程里各模块之间实际传递的核心数据，而不是 prompt 文案。

### 3.1 输入样本

主流程统一使用 `CanonicalSample` 作为样本载体，核心字段包括：

- `sample_id`
- `source`
- `problem_text`
- `options`
- `gold_answer`
- `image_b64` / `image_path` / `image_description`
- `category` / `subfield` / `reasoning_type`
- `skip_reason`
- `meta`

其中主流程真正依赖的核心输入通常是：

- `sample_id`
- `problem_text`
- 可选图像信息

### 3.2 A 阶段输出：Problem IR

A 阶段输出 `GroundingResult`，其中最重要的部分是 `problem_ir`。当前 `Problem IR` 的标准字段包括：

- `objects`
- `known_quantities`
- `unknown_target`
- `units`
- `constraints`
- `relations`
- `physical_laws`
- `assumptions`
- `diagram_information`
- `goal_statement`
- `coordinate_system`
- `reference_frame`
- `simplifications`
- `symbol_table`

除此以外，A 阶段结果还包含：

- `parse_ok`
- `raw_response`
- `error`
- `vision_fallback`

后续模块对 A 的依赖关系是：

- B 使用 `problem_ir` 生成 theorem 候选
- MechLib 检索使用 `problem_text + problem_ir`
- D 使用 `problem_ir` 评估 theorem 是否与题意一致
- E 使用 `problem_ir` 辅助 proof planning 和 proof generation

### 3.3 MechLib 检索输出

当 `knowledge.enabled = true` 且 `statement.with_mechlib_context = true` 时，系统会基于 `problem_text + problem_ir` 构造检索上下文。当前落盘到 `mechlib_retrieval.jsonl` 的主要内容包括：

- `enabled`
- `retrieved_count`
- `domain_from_a`
- `selected_tags`
- `summary_items_count`
- `source_items_count`
- `final_context_chars`
- `items`
- `summary_items`
- `import_hints`
- `law_matched_items`
- `proof_style_examples`
- `retrieval_context`

其中真正传给后续模块的是字符串形式的 `retrieval_context`。是否注入某个阶段，由 `knowledge.inject_modules` 控制，目前支持：

- `B`
- `D`
- `E`

### 3.4 B 阶段输出：StatementCandidate

B 阶段每轮输出若干 `StatementCandidate`。每个 candidate 当前包含：

- `candidate_id`
- `lean_header`
- `theorem_decl`
- `assumptions`
- `plan`
- `supporting_facts`
- `fact_sources`
- `library_symbols_used`
- `grounding_explanation`
- `unsupported_claims`
- `parse_ok`
- `raw_response`
- `error`
- `round_index`
- `source_round_index`

后续使用方式如下：

- C 对每个 candidate 做真实 Lean 编译检查
- D 只在 compile 结果基础上评估这些 candidate
- E 只会接收 D 选中的最终 candidate

### 3.5 C 阶段输出：CompileCheckResult

C 阶段对每个 candidate 输出一个 `CompileCheckResult`。关键字段包括：

- `candidate_id`
- `compile_pass`
- `syntax_ok`
- `elaboration_ok`
- `error_type`
- `sub_error_type`
- `failure_tags`
- `failure_summary`
- `failure_details`
- `stderr_digest`
- `stderr_excerpt`
- `error_line`
- `error_message`
- `error_snippet`
- `log_path`
- `backend_used`
- `route_reason`
- `route_fallback_used`
- `round_index`

后续使用方式如下：

- D 只会在这些 compile result 基础上处理“可编译候选”
- 反馈闭环也会把 compile 失败信息回送给 B

### 3.6 D 阶段输出：SemanticRankResult

D 阶段输出一个 `SemanticRankResult`。核心字段包括：

- `selected_candidate_id`
- `selected_theorem_decl`
- `semantic_pass`
- `ranking`
- `selected_backend`
- `selected_route_reason`
- `selected_route_fallback_used`
- `error`
- `sub_error_type`
- `failure_tags`
- `failure_summary`
- `failure_details`
- `round_index`
- `retry_triggered`
- `retry_reason`
- `retry_feedback_summary`

其中 `ranking` 是一个列表，每个候选的条目通常包含：

- `candidate_id`
- `semantic_score`
- `semantic_pass`
- `target_relation`
- `failure_summary`
- `failure_tags`
- `mismatch_fields`
- `missing_or_incorrect_translations`
- `suggested_fix_direction`
- `sub_error_type`
- 与库依据有关的字段，例如 `library_grounding_score`

后续使用方式如下：

- 若 `semantic_pass = true`，E 阶段接收 `selected_candidate_id` 对应的 theorem
- 若 `semantic_pass = false`，系统可能触发 B/C/D feedback revision

### 3.7 E 阶段输入与输出

E 阶段的输入不是全部候选，而是：

- `problem_ir`
- D 最终选中的 `StatementCandidate`
- 可选 `mechlib_context`

当前 E 分成 proof planning 和 proof generation 两层。落盘的 attempt 结果 `ProofAttemptResult` 关键字段包括：

- `attempt_index`
- `proof_body`
- `parse_ok`
- `raw_response`
- `compile_pass`
- `strict_pass`
- `error_type`
- `sub_error_type`
- `failure_tags`
- `failure_summary`
- `failure_details`
- `stderr_digest`
- `stderr_excerpt`
- `log_path`
- `plan`
- `proof_plan`
- `theorems_to_apply`
- `givens_to_use`
- `intermediate_claims`
- `plan_grounding_ok`
- `backend_used`
- `route_reason`
- `route_fallback_used`

E 的最终汇总结果是 `ProofCheckResult`，关键字段包括：

- `proof_success`
- `attempts_used`
- `selected_candidate_id`
- `error_type`
- `sub_error_type`
- `failure_tags`
- `failure_summary`
- `failure_details`
- `final_log_path`
- `backend_used`

### 3.8 样本级最终汇总

每个样本最终都会产生一个 `SampleRunSummary`，这是最适合做样本级分析的对象。关键字段包括：

- `grounding_ok`
- `statement_generation_ok`
- `compile_ok`
- `semantic_ok`
- `proof_ok`
- `end_to_end_ok`
- `final_error_type`
- `final_round_index`
- `feedback_loop_used`
- `sub_error_type`
- `failure_summary`
- `failure_details`

## 4. 反馈闭环传递什么内容

当前反馈闭环只作用于 `B -> C -> D`，由 `rendering.build_revision_feedback(...)` 组装。它不是把整份日志原样塞回 prompt，而是传回一个结构化摘要。

反馈消息顶层字段包括：

- `retry_reason`
- `compile_pass_count`
- `semantic_pass`
- `selected_candidate_id`
- `candidates`

其中 `retry_reason` 当前主要有两类：

- `no_compile_pass`
- `semantic_fail`

`candidates` 列表中，每个候选会携带以下信息的摘要：

- theorem 本体信息
  - `candidate_id`
  - `theorem_decl`
  - `plan`
  - `supporting_facts`
  - `fact_sources`
  - `library_symbols_used`
  - `grounding_explanation`
  - `unsupported_claims`
- C 阶段反馈
  - `compile_pass`
  - `error_type`
  - `sub_error_type`
  - `failure_tags`
  - `failure_summary`
  - `stderr_digest`
  - `stderr_excerpt`
  - `backend_used`
  - `route_reason`
  - `route_fallback_used`
  - `error_line`
  - `error_message`
  - `error_snippet`
- D 阶段反馈
  - `semantic_score`
  - `semantic_pass`
  - `semantic_sub_error_type`
  - `semantic_failure_tags`
  - `semantic_failure_summary`
  - `back_translation_text`
  - `mismatch_fields`
  - `missing_or_incorrect_translations`
  - `suggested_fix_direction`
  - `hard_gate_reasons`
  - `semantic_rank_score`
  - `library_grounding_score`
  - `grounded_library_symbols`
  - `grounding_gap_summary`
  - `direct_translation`

这意味着当前 revision 不是一句模糊的“请重试”，而是把每个 candidate 在 C/D 两个阶段暴露出的核心问题结构化回送给 B。

## 5. 当前主流程特性

### 5.1 反馈闭环

当前主流程支持 `B -> C -> D` 的反馈闭环：

- 当某一轮没有任何候选编译通过时，系统会将编译反馈打包后回送给 B。
- 当某一轮有候选编译通过但语义筛选失败时，系统会将语义反馈回送给 B。
- 反馈轮数由 `statement.max_revision_rounds` 控制。

默认情况下，最终指标只按最终轮次统计，不重复累计前面轮次的失败。

### 5.2 真实 Lean 验证

项目不会只停留在“模型生成一段看起来像 Lean 的字符串”。主流程会调用真实 Lean 环境：

- 编译阶段由 `C` 调用 `LeanRunner`
- 证明阶段由 `E` 调用 `LeanRunner`
- 支持 `PhysLean` 与 `MechLib` 两类后端

### 5.3 诊断能力

当前已经实现了较细粒度的失败诊断：

- 编译前坏声明快速拦截
- 语法/类型/命名空间类错误细分
- timeout 类型细分
- 语义漂移、目标错误、给定条件缺失等语义失败标签
- proof 失败的结构化记录

### 5.4 结果归档

每次运行都会落盘到：

- `runs/<timestamp>_<tag>/`

并同步生成一个轻量镜像：

- `outputs/latest/`

其中 `runs/...` 保留完整档案，`outputs/latest/` 只保留最近一次运行的轻量结果。

## 6. 仓库结构

下面是当前最重要的目录与文件。

```text
pipeline1/
├─ configs/                  常用 YAML 配置模板
├─ fixtures/                 小规模实验夹具与固定样本集
├─ outputs/
│  └─ latest/                最近一次运行的轻量镜像
├─ prompts/                  A/B/D/E/Z 阶段提示词
├─ reports/                  实验报告、中期报告与分析文档
├─ runs/                     每次正式运行的完整落盘结果
├─ rubbish/                  已归档的历史调试/实验产物
├─ src/mech_pipeline/
│  ├─ adapters/              数据源与 Lean 运行适配层
│  ├─ archive/               结果写出与 latest 镜像
│  ├─ eval/                  指标与错误分类
│  ├─ knowledge/             MechLib 检索与上下文构造
│  ├─ model/                 模型客户端
│  ├─ modules/               A/B/C/D/E/F/Z 各阶段实现
│  ├─ cli.py                 主流程入口
│  ├─ orchestrator.py        样本级执行编排
│  ├─ rendering.py           README 与 Lean 导出渲染
│  ├─ config.py              配置结构与校验
│  ├─ types.py               核心类型定义
│  └─ utils.py               通用工具与题面清洗
├─ tests/                    pytest 测试
├─ tmp/                      临时日志、临时配置与 pytest 基目录
├─ lakefile.toml             Lean 导出工作区依赖声明
├─ lean-toolchain            Lean 工具链版本
├─ pyproject.toml            Python 包定义与命令行入口
└─ README.md
```

## 7. 关键源码文件

如果你要快速建立上下文，优先看这些文件：

- [cli.py](f:/AI4Mechanics/coding/pipeline1/src/mech_pipeline/cli.py)
  主流程入口，负责组装模块、读取配置、调度样本执行。
- [orchestrator.py](f:/AI4Mechanics/coding/pipeline1/src/mech_pipeline/orchestrator.py)
  样本级执行逻辑，包括反馈闭环和阶段串联。
- [config.py](f:/AI4Mechanics/coding/pipeline1/src/mech_pipeline/config.py)
  全部配置结构、默认值和校验规则。
- [lean_runner.py](f:/AI4Mechanics/coding/pipeline1/src/mech_pipeline/adapters/lean_runner.py)
  真实 Lean 编译与证明验证入口。
- [mechlib.py](f:/AI4Mechanics/coding/pipeline1/src/mech_pipeline/knowledge/mechlib.py)
  MechLib 检索与上下文构造。
- [B_statement_gen.py](f:/AI4Mechanics/coding/pipeline1/src/mech_pipeline/modules/B_statement_gen.py)
  theorem 候选生成与 revision。
- [D_semantic_rank.py](f:/AI4Mechanics/coding/pipeline1/src/mech_pipeline/modules/D_semantic_rank.py)
  语义评分、排序和 hard gate。
- [E_prover.py](f:/AI4Mechanics/coding/pipeline1/src/mech_pipeline/modules/E_prover.py)
  proof planning、生成、修复与验证。
- [metrics.py](f:/AI4Mechanics/coding/pipeline1/src/mech_pipeline/eval/metrics.py)
  指标口径定义。

## 8. 配置结构

主配置由以下几部分组成：

- `dataset`
- `model`
- `lean`
- `knowledge`
- `statement`
- `semantic`
- `proof`
- `prompts`
- `output`
- `runtime`

一个最小可运行示例如下：

```yaml
dataset:
  source: lean4phys
  limit: 10
  sample_policy: index_head
  lean4phys:
    bench_path: F:/AI4Mechanics/coding/Lean4PHYS/LeanPhysBench/LeanPhysBench_v0.json
    category: mechanics

model:
  provider: openai_compatible
  model_id: gpt-5.4
  base_url: https://your-proxy.example.com
  api_key_env: OPENAI_PROXY_KEY
  supports_vision: true
  timeout_s: 60
  max_retries: 2

lean:
  enabled: true
  physlean_dir: F:/AI4Mechanics/PhysLean-master
  mechlib_dir: F:/AI4Mechanics/coding/MechLib
  timeout_s: 120
  lean_header: import PhysLean
  route_policy: auto_by_import
  default_backend: mechlib
  route_fallback: true

knowledge:
  enabled: true
  mechlib_dir: F:/AI4Mechanics/coding/MechLib
  scope: mechanics_si
  top_k: 6
  cache_path: tmp/mechlib_index.jsonl
  inject_modules: ["B"]
  summary_corpus_path: F:/AI4Mechanics/coding/MechLib/theorem_corpus.jsonl

statement:
  library_target: mechlib
  with_mechlib_context: true
  feedback_loop_enabled: true
  max_revision_rounds: 1

semantic:
  pass_threshold: 0.7

proof:
  max_attempts: 2

prompts:
  dir: prompts

output:
  output_dir: outputs/latest
  runs_dir: runs
  tag: demo-run

runtime:
  sample_concurrency: 4
```

## 9. 运行方式

### 9.1 主流程

```powershell
$env:PYTHONPATH = "src"
$env:OPENAI_PROXY_KEY = "<your-key>"
python -m mech_pipeline.cli run --config configs/mechanics101_proxy_gpt54_20260409.yaml
```

常用附加参数：

```powershell
python -m mech_pipeline.cli run `
  --config configs/theoretical_mechanics_14_proxy_gpt54_20260407.yaml `
  --limit 14 `
  --tag my-run `
  --sample-concurrency 8
```

### 9.2 无 MechLib 检索消融

```powershell
$env:PYTHONPATH = "src"
python -m mech_pipeline.cli_ablate_no_mechlib run --config <config>.yaml
```

这条入口会关闭 `knowledge.enabled` 和 `statement.with_mechlib_context`，但保留主流程结构。

### 9.3 直接 theorem baseline

```powershell
$env:PYTHONPATH = "src"
python -m mech_pipeline.cli_direct_baseline run --config <config>.yaml
```

这条入口不是主流程。它用于“直接 theorem 生成”基线或相关对照实验。

## 10. 运行产物说明

典型的 `runs/<run>/` 目录包含：

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
- `lean_exports/`

部分运行还会包含：

- `.pipeline1_tmp/`
- `lean_compile/`
- `lean_proof/`

这些重型调试材料保留在 `runs/...` 中，不默认完整复制到 `outputs/latest/`。

## 11. 指标口径

当前最常看的指标有：

- `grounding_success_rate`
  最终轮次中，成功得到结构化题意表示的题目比例。
- `statement_generation_success_rate`
  最终轮次中，成功生成候选 theorem 的题目比例。
- `lean_compile_success_rate`
  按题统计。最终轮次中，每题只要有至少一个 candidate 编译通过，即视为该题 compile 成功。
- `semantic_consistency_pass_rate`
  最终轮次中，通过语义筛选的题目比例。
- `proof_success_rate`
  最终轮次中，proof 验证通过的题目比例。
- `end_to_end_verified_solve_rate`
  端到端成功率，即题目最终 theorem 与 proof 均通过。

补充说明：

- `lean_compile_success_rate` 当前是按题统计，不是按 candidate 条目统计。
- 大多数主指标只统计最终轮次，不重复计算前面轮次的中间失败。

## 12. Lean / MechLib / Mathlib 关系

当前主流程的 header 策略是“后端最小必需头文件”，而不是默认总加 `import Mathlib`。

常见情况：

- `mechlib` 目标通常使用 `import MechLib`
- `physlean` 目标通常使用 `import PhysLean`

这不代表无法使用 `Mathlib` 内容。`MechLib` 本身依赖 `mathlib`，因此很多常见对象与 tactic 已可通过依赖闭包使用。但主流程不会默认把 `import Mathlib` 作为显式头文件塞进每个输出。

根目录 [lakefile.toml](f:/AI4Mechanics/coding/pipeline1/lakefile.toml) 用于导出工作区，当前显式声明了：

- 本地 `MechLib`
- 本地 `mathlib`

## 13. 测试

运行全部测试：

```powershell
$env:PYTHONPATH = "src"
python -m pytest -q
```

常用分组：

```powershell
python -m pytest -q tests/test_cli_smoke.py tests/test_config.py
python -m pytest -q tests/test_semantic_rank.py tests/test_semantic_guardrails.py
python -m pytest -q tests/test_lean_runner.py tests/test_e_prover.py
```

测试目录见：
- [tests](f:/AI4Mechanics/coding/pipeline1/tests)

## 14. 当前仓库中几个重要的实验入口

常用配置模板位于：
- [configs](f:/AI4Mechanics/coding/pipeline1/configs)

其中最常用的包括：

- `mechanics101_proxy_gpt54_20260409.yaml`
- `theoretical_mechanics_14_proxy_gpt54_20260407.yaml`
- `direct_baseline_mechanics101_gpt54_20260410.yaml`
- `smoke_mock_local_text.yaml`

夹具位于：
- [fixtures](f:/AI4Mechanics/coding/pipeline1/fixtures)

报告位于：
- [reports](f:/AI4Mechanics/coding/pipeline1/reports)

## 15. 当前已知边界

这份 README 只描述当前仓库中的实际结构和当前实现，不承诺以下内容已经完全解决：

- MechLib 检索结果稳定转化为 theorem/proof 中的显式库定理复用
- 所有理论力学题都能稳定通过
- 所有 `Mathlib` 对象都能在最小头文件策略下无额外适配地直接使用

当前系统已经具备：

- 真实 Lean 闭环
- 可复查的运行产物
- 结构化反馈闭环
- 检索与消融实验能力

但仍然是研究型基线，而不是最终产品。

## 16. 建议的阅读顺序

如果你是第一次进入这个仓库，建议按这个顺序建立上下文：

1. 看本 README
2. 看 [config.py](f:/AI4Mechanics/coding/pipeline1/src/mech_pipeline/config.py)
3. 看 [cli.py](f:/AI4Mechanics/coding/pipeline1/src/mech_pipeline/cli.py)
4. 看 [orchestrator.py](f:/AI4Mechanics/coding/pipeline1/src/mech_pipeline/orchestrator.py)
5. 看 [modules](f:/AI4Mechanics/coding/pipeline1/src/mech_pipeline/modules)
6. 看最近一次运行的 [outputs/latest](f:/AI4Mechanics/coding/pipeline1/outputs/latest)
7. 再看 [reports](f:/AI4Mechanics/coding/pipeline1/reports) 中的分析文档

这份顺序足够在新上下文窗口中快速恢复项目全貌。
