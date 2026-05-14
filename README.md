# LeanMech

LeanMech 是一个面向力学题自动形式化的分阶段流水线。它从自然语言题面和可选图像出发，构造结构化中间表示，生成 Lean theorem candidate 或 typed minimal skeleton，在真实 Lean 环境中做 statement elaboration check，再进入语义排序、证明尝试和运行归档。

当前仓库的目标不是训练框架，也不是通用 agent 平台，而是一个可运行、可回放、可诊断的研究型基线。

## 项目目标

- 从题面中抽取结构化物理语义。
- 使用 MechLib corpus 做检索、建模提示和 evidence binding。
- 明确区分 schema metadata 与 verified declaration。
- 生成 legacy theorem candidate 或 minimal theorem skeleton。
- 在真实 Lean 中检查 theorem statement 是否可 elaboration。
- 将每次运行完整写入 `runs/<run>/`，并同步轻量镜像到 `outputs/latest/`。
- 保持旧 CLI 和旧配置兼容。

## CLI 兼容性

主入口保持不变：

```bash
mech-baseline run --config <config>.yaml
```

等价模块调用：

```bash
PYTHONPATH=src python -m mech_pipeline.cli run --config <config>.yaml
```

常用参数：

```bash
mech-baseline run \
  --config configs/smoke_minimal_skeleton.yaml \
  --limit 1 \
  --tag local-smoke \
  --sample-concurrency 1
```

旧配置仍可加载。statement 生成模式由以下开关控制：

```yaml
statement:
  generation_mode: legacy_candidate | minimal_skeleton
```

## 两种 Pipeline 模式

### Legacy Candidate 模式

`generation_mode: legacy_candidate` 保留旧流程：

```text
sample
  -> A ProblemIR
  -> MechLib retrieval context
  -> B theorem candidates
  -> C Lean statement elaboration check
  -> D semantic rank
  -> E proof generation/check
  -> F report and metrics
```

该模式下，B 仍让模型直接生成 Lean theorem declaration。C/D/E 的消费方式保持旧逻辑。

### Minimal Skeleton 模式

`generation_mode: minimal_skeleton` 在 B 之前加入受控前半段：

```text
sample
  -> A ProblemIR
  -> Structured MechLib Context
  -> A2 ModelIR + CanonicalTarget + FunctionFormulaIR
  -> SchemaPlanner
  -> EvidenceBinder
  -> ControlledSketch
  -> SketchAudit
  -> B typed deterministic theorem skeleton assembler
  -> C Lean statement elaboration check
  -> D semantic rank
  -> E existing proof stage
```

新增阶段只在 minimal skeleton 模式启用。E 阶段目前不重构。

当前交接状态见 [docs/handoff_minimal_pipeline_token_optimization_20260513.md](/Users/weizhixin/AI4Mechanics/LeanMech/docs/handoff_minimal_pipeline_token_optimization_20260513.md)。该文档记录了最近一次 token 优化、12 题真实评测中止原因、新 E proof search 长尾问题，以及后续建议。

## 核心数据结构

### ProblemIR

A 阶段输出 `GroundingResult.problem_ir`。常见字段包括：

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
- `symbol_table`

### ModelIR

A2 阶段输出 `ModelIR`，负责把题面理解整理成可审计的建模表示，包括：

- problem facts / givens
- coordinate conventions
- local definitions
- model instances
- interface instantiations，例如 net force、component relation、constraint equation
- quantity annotations
- canonical target
- forbidden_as_assumption

在 minimal skeleton 模式中，A2 是物理量类型判断的权威来源。B 不再根据变量名字符匹配来猜 `Mass`、`Force`、`Acceleration` 等类型。

### QuantityTypeAnnotation

每个物理量可以带有：

- `symbol`
- `semantic_role`
- `unit_or_dimension`
- `lean_type`
- `confidence`
- `evidence_text`
- `reasoning_note`
- `status`

支持的 SI 类型由 `src/mech_pipeline/quantity_types.py` 维护。若 A2 输出 MechLib.SI 不支持的类型，B 不能伪造该类型，只能保守降级并记录 unsupported 信息。

### CanonicalTarget 与 FunctionFormulaIR

`CanonicalTarget` 是 minimal B 唯一允许读取的 target 来源。它包括：

- `target_kind`
- `target_variables`
- `lean_formula`
- `secondary_formulas`
- `function_formula_ir`
- `requires_closed_form`
- `parse_ok`
- `error`

`FunctionFormulaIR` 用来把函数型目标的语义结构交给 A2/LLM 判断，而不是让 B 猜。A2 负责区分目标到底是：

- `scalar_relation`
- `pointwise_relation`
- `evaluation_relation`
- `ode_relation`
- `component_relation`
- `property`

B 优先消费 `function_formula_ir`。如果该结构不合法，B 会阻塞 skeleton，并通过 failure routing 把问题归因到 A2，而不是继续用正则猜函数语义。

示例：

```json
{
  "formula_id": "target_formula_1",
  "formula_kind": "pointwise_relation",
  "bound_variables": [{"name": "t", "lean_type": "Time"}],
  "domain_conditions": ["0 <= t", "t <= t_final"],
  "lhs": "v_x t",
  "relation": "=",
  "rhs": "2 * k * t",
  "lean_formula": "forall t, 0 <= t ∧ t <= t_final -> v_x t = 2 * k * t",
  "parse_ok": true
}
```

### StructuredMechLibContext

结构化 MechLib 上下文把建模信息和 proof-eligible declaration 分开：

- `modeling_context`
  - concepts
  - law schemas
  - problem schemas
  - aliases
- `proof_context`
  - verified declarations
  - required imports
  - proof hints
  - proof style examples
- `forbidden_as_proof_fact`

law schema、problem schema、concept、alignment、example、interface metadata 都只能作为建模/检索信息，不能当作 proof fact。

### EvidenceBinding

`EvidenceBinder` 将 `ModelInstance` 绑定到 MechLib declaration。一个 binding 只有在满足 verified、callable、Lean check 等条件时，才可以作为 proof-eligible declaration。

若找不到 verified declaration，必须记录 gap：

- `binding_status = gap_schema_only`
- `proof_fact_allowed = false`
- `verified_decl = null`

pipeline 不能伪造 MechLib theorem 或 model predicate 名称。

### ControlledSketch

当前 ControlledSketch 是 minimal proof-obligation sketch，不是自然语言完整解题过程：

- `proof_steps` 只允许 `law_to_equation` / `constraint_to_equation`。
- `algebra_obligation` 至多一个，用于最终代数目标。
- `blocked_law_steps` 存放 gap 或未绑定 declaration 的 law instance。
- canonical v2 路径中，`gap_steps` 不复用 proof step 类型。

### TheoremSkeletonCandidate

Minimal B 输出 `TheoremSkeletonCandidate`，它兼容并扩展 `StatementCandidate`。旧字段保留：

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

新增字段包括：

- `generation_mode`
- `hypothesis_provenance`
- `model_ir_digest`
- `evidence_bindings`
- `controlled_sketch`
- `proof_obligations`
- `selected_laws`
- `verified_decls`
- `gap_laws`
- `skeleton_audit`
- `typed_binders`
- `model_predicate_bindings`
- `excluded_hypotheses`
- `generation_blocked_reason`

## Minimal B 生成规则

minimal mode 下，B 不再信任 LLM 直接生成的 `theorem_decl`。LLM 只选择 givens、model instances、variant 和说明性 metadata。最终 Lean theorem skeleton 由 deterministic assembler 生成。

header 顺序固定：

```lean
import Mathlib
import MechLib

open MechLib
open MechLib.SI
```

核心规则：

- typed binders 来自 `ModelIR.quantity_annotations`、verified declaration signature 或显式 introduced variable。
- theorem target 优先在 `.val` 层做 Real algebra。
- 允许重要的 audited modeling equation，例如 `Fnet.val = T.val`、`Fnet.val = m.val * a.val`。
- 删除或拒绝无信息约束，例如 `a.val = a.val`、`T.val = T.val`。
- 不把自然语言条件翻译成伪 Lean predicate，例如 `massless_string`、`frictionless_track`。
- 只有 EvidenceBinder/registry 确认存在的 MechLib declaration 才可生成 MechLib model binder。
- explicit modeling gap 只能记为 gap，不能计为 verified MechLib use。

B 不输出 proof body。C 阶段可以在临时 statement-check 文件里使用内部 placeholder，但 B 不输出 `:= by`、`sorry`、`admit`。

## SketchAudit Gate

SketchAudit 审计的是 sketch 和未来 skeleton 的候选数据结构，不是 Lean proof。

hard gate 包括：

- schema/problem/concept metadata 被当作 proof fact
- proof step 标记 proof-eligible 但缺少 verified declaration
- gap binding 出现在 `proof_steps`
- final target 或 candidate answer 进入普通 hypothesis
- algebra result 进入普通 hypothesis
- provenance 缺失
- fabricated 或未注册 MechLib reference
- 非 Lean-like formal claim

当前 gate 对 audited component/model interface equation 有意放宽：component relation、net-force definition 等可以与 target variable 重叠，只要它们被明确标记为 modeling interface，并且不计为 verified MechLib declaration。

## Feedback 与 Failure Routing

legacy 模式仍是 B/C/D 反馈闭环。

minimal 模式使用 deterministic failure routing，不再把所有失败统一反馈给 Sketch+B。router 会把错误归因到：

- `A2`：target、quantity type、unit、function formula structure 错误
- `EvidenceBinder`：bad declaration、signature mismatch、Lean check failure
- `Sketch`：proof-obligation 选择错误或 sketch audit fail
- `B`：theorem shape、binder、header、`.val`、skeleton audit 错误
- `C`：Lean tooling/backend 问题
- `D`：compile 后的语义不一致

每次 retry 从责任阶段开始重跑，下游阶段重跑，上游 artifact 尽量复用。全局轮数仍由 `statement.max_revision_rounds` 控制。
默认反馈范围是 `minimal_feedback_scope: routed_stage`。兼容值包括 `sketch_and_b`、`b_only`、`all_downstream` 和 `none`，但新 minimal run 应优先使用 `routed_stage`。

## 运行产物

标准运行写入：

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

minimal skeleton 运行额外写入：

- `structured_mechlib_context.jsonl`
- `model_ir.jsonl`
- `evidence_bindings.jsonl`
- `controlled_sketch.jsonl`
- `sketch_audit.jsonl`
- `theorem_skeleton_candidates.jsonl`
- `failure_routes.jsonl`

完整档案位于：

- `runs/<timestamp>_<tag>/`

最近一次运行的轻量镜像位于：

- `outputs/latest/`

## 指标

核心指标按题统计：

- `grounding_success_rate`
- `statement_generation_success_rate`
- `lean_compile_success_rate`
- `semantic_consistency_pass_rate`
- `proof_success_rate`
- `end_to_end_verified_solve_rate`

minimal skeleton 额外指标：

- `model_ir_success_rate`
- `evidence_binding_success_rate`
- `verified_binding_rate`
- `gap_schema_only_rate`
- `sketch_audit_pass_rate`
- `skeleton_generation_success_rate`
- `derived_equation_hypothesis_violation_rate`
- `schema_as_proof_fact_violation_rate`
- `explicit_gap_law_rate`

`lean_compile_success_rate` 和 `semantic_consistency_pass_rate` 以总题目数为分母，不按 candidate row 数量计算。

## 配置要点

minimal mode 关键配置：

```yaml
statement:
  generation_mode: minimal_skeleton
  allow_explicit_gap_laws: true
  forbid_derived_equation_hypotheses: true
  require_hypothesis_provenance: true
  require_evidence_binding: true
  max_model_ir_candidates: 2
  max_sketch_steps: 12
  minimal_feedback_scope: routed_stage
  b_minimal_llm_enabled: false
  b_minimal_llm_on_retry: true
  compact_minimal_prompts: true

knowledge:
  structured_context_enabled: true
  enriched_corpus_enabled: true
  decl_corpus_path: ../MechLib/corpus/decl_corpus_enriched.jsonl
  law_schema_corpus_path: ../MechLib/corpus/law_schema_corpus.jsonl
  problem_schema_corpus_path: ../MechLib/corpus/problem_schema_corpus.jsonl
  concept_corpus_path: ../MechLib/corpus/concept_corpus.jsonl
  alias_map_path: ../MechLib/corpus/alias_map.jsonl
  evidence_top_k: 8
  lean_check_decls: true
```

常用 smoke 配置：

- `configs/smoke_legacy_candidate.yaml`
- `configs/smoke_minimal_skeleton.yaml`
- `configs/smoke_minimal_skeleton_gap.yaml`

近期固定回归集：

- `tmp/random10_plus_mechanics73_20260509_181342.json`
- `tmp/minimal_random10_plus_mechanics73_20260509_181342.yaml`

该集合包含 `Mechanics73`。比较 minimal mode 改动时，应优先复用这组样本，避免每次重新抽样导致结果不可比。

近期 12 题评测集：

- `fixtures/bench_testset_v1_selected12.json`
- `configs/minimal_testset_v1_selected12.yaml`

该配置使用 `gpt-5.4` 和 minimal skeleton。注意：在 `proof.mode=auto` 且 selected candidate 为 minimal skeleton 时，E 会进入 `llm_guided_search`。默认搜索预算较大，真实并发评测可能长时间停留在 `pipeline_proof_probe_*.lean`。不要为了绕开该问题静默改成 legacy proof；如果只想评估 D 前流程或限预算测试新 E，应显式创建单独配置并在报告中说明。

## Lean / MechLib / Mathlib

minimal skeleton mode 显式导入 Mathlib 和 MechLib，并保证所有 `import` 在所有 `open` 之前。

Lean 检查由 `LeanRunner` 执行，运行结果依赖本机 Lean 环境：

- `lean.physlean_dir`
- `lean.mechlib_dir`
- `lean.timeout_s`
- `lean.route_policy`
- `lean.default_backend`

如果 `import MechLib` 超时，或 preflight 显示 MechLib unavailable，该 run 的 compile/semantic 指标不能直接和 MechLib 健康时的 run 对比。

## 测试

运行全部测试：

```bash
source .venv/bin/activate
pytest -q
```

常用 focused tests：

```bash
python -m pytest -q tests/test_types_model_ir.py tests/test_config_minimal_skeleton.py
python -m pytest -q tests/test_structured_mechlib_context.py tests/test_evidence_binder.py
python -m pytest -q tests/test_model_ir_builder.py tests/test_schema_planner.py
python -m pytest -q tests/test_controlled_sketch.py tests/test_sketch_audit.py
python -m pytest -q tests/test_b_minimal_skeleton.py tests/test_b_no_derived_hypotheses.py
python -m pytest -q tests/test_d_skeleton_aware_rank.py tests/test_failure_routing_minimal_routed_stage.py
python -m pytest -q tests/test_orchestrator_minimal_routed_retry.py tests/test_failure_routing.py
python -m pytest -q tests/test_metrics_minimal_skeleton.py
```

minimal skeleton smoke：

```bash
python -m mech_pipeline.cli run \
  --config configs/smoke_minimal_skeleton.yaml \
  --limit 1 \
  --tag smoke-d-header-routing \
  --sample-concurrency 1
```

## 仓库结构

```text
LeanMech/
├─ configs/                  YAML 配置与 smoke 配置
├─ docs/                     设计说明与 pipeline 文档
├─ fixtures/                 本地测试夹具
├─ outputs/latest/           最近一次运行轻量镜像
├─ prompts/                  各阶段 prompt
├─ reports/                  实验报告与审计报告
├─ runs/                     完整运行档案
├─ src/mech_pipeline/
│  ├─ adapters/              Lean 与数据源适配器
│  ├─ eval/                  metrics 与 summary
│  ├─ knowledge/             MechLib retrieval 与 evidence binding
│  ├─ model/                 模型客户端
│  ├─ modules/               A/A2/B/C/D/E/F/sketch 模块
│  ├─ cli.py                 主 CLI
│  ├─ config.py              配置 dataclass 与校验
│  ├─ failure_routing.py     minimal mode 失败路由
│  ├─ orchestrator.py        样本级执行编排
│  ├─ quantity_types.py      SI 类型 registry
│  ├─ rendering.py           run README/analysis 渲染
│  ├─ types.py               核心 dataclass
│  └─ utils.py               通用工具
├─ tests/                    pytest 测试
├─ tmp/                      临时配置和回归样本选择
├─ lakefile.toml
├─ lean-toolchain
├─ pyproject.toml
└─ README.md
```

## 建议阅读顺序

1. `README.md`
2. `docs/minimal_skeleton_pipeline.md`
3. `src/mech_pipeline/types.py`
4. `src/mech_pipeline/config.py`
5. `src/mech_pipeline/orchestrator.py`
6. `src/mech_pipeline/modules/A2_model_ir.py`
7. `src/mech_pipeline/modules/sketch_builder.py`
8. `src/mech_pipeline/modules/sketch_audit.py`
9. `src/mech_pipeline/modules/B_statement_gen.py`
10. `src/mech_pipeline/knowledge/evidence_binder.py`
11. `outputs/latest/` 或最近的 `runs/<run>/`

## 当前边界

当前实现不承诺：

- E 阶段 proof search 已解决。
- 所有 `gap_schema_only` 关系都可被证明。
- MechLib 已包含所有需要的 mechanics model predicate。
- schema、concept、alignment、example 可作为 proof fact。
- 复杂 ODE / function target 总能被稳定表达成 Lean 一阶公式。

当前重构方向是让 D 之前的前半段更短、更 typed、更可审计，并诚实暴露 gap。后续 E 阶段应消费 `proof_obligations`、`verified_decls`、`controlled_sketch` 和 `hypothesis_provenance`，而不是从不透明自然语言 hypothesis 中寻找证明依据。
