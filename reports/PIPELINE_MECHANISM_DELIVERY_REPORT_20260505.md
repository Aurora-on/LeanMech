# LeanMech 当前 Pipeline 运行机制交付报告（2026-05-05）

## 1. 总览

当前 LeanMech pipeline 的主入口仍然是：

```bash
mech-baseline run --config <config.yaml>
```

或者等价地：

```bash
python -m mech_pipeline.cli run --config <config.yaml>
```

主流程由 `src/mech_pipeline/cli.py` 负责初始化，由 `src/mech_pipeline/orchestrator.py` 负责逐样本编排。当前代码支持两种 B 阶段生成模式：

- `legacy_candidate`：旧路径，B 直接生成若干 Lean theorem candidate。
- `minimal_skeleton`：新路径，A 之后先生成 ModelIR、EvidenceBinding、ControlledSketch、SketchAudit，再让 B 生成最小 theorem skeleton。

默认配置保持 legacy 行为。只有显式设置：

```yaml
statement:
  generation_mode: minimal_skeleton
```

才启用新前半段。

## 2. 全局执行顺序

### 2.1 CLI 初始化

CLI 做以下事情：

1. 读取 YAML 配置并合并默认值。
2. 应用命令行覆盖项：
   - `--limit`
   - `--tag`
   - `--sample-concurrency`
3. 校验配置值，例如 dataset 类型、Lean backend 路由策略、generation mode、并发上限等。
4. 创建本次 run 目录：
   - `runs/<timestamp>_<tag>/`
5. 指定最新输出目录：
   - `outputs/latest/`
6. 初始化 stage row 容器，当前登记的 JSONL 文件包括：
   - `problem_ir.jsonl`
   - `model_ir.jsonl`
   - `structured_mechlib_context.jsonl`
   - `evidence_bindings.jsonl`
   - `controlled_sketch.jsonl`
   - `sketch_audit.jsonl`
   - `mechlib_retrieval.jsonl`
   - `statement_candidates.jsonl`
   - `theorem_skeleton_candidates.jsonl`
   - `compile_checks.jsonl`
   - `semantic_rank.jsonl`
   - `proof_attempts.jsonl`
   - `proof_checks.jsonl`
   - `sample_summary.jsonl`
7. 如果 `knowledge.enabled=true`，创建 `MechLibRetriever`。
8. 按 dataset 配置加载样本：
   - `local_archive`
   - `phyx`
   - `lean4phys`
9. 如果 Lean 预检开启，则运行 preflight。
10. 调用 `execute_samples(...)` 进入 orchestrator。

### 2.2 并发模型

样本级并发在 orchestrator 中执行。`runtime.sample_concurrency` 或命令行 `--sample-concurrency` 控制并发数，配置校验限制最大值为 10。

每个样本由 `process_sample(...)` 独立处理。最终 orchestrator 会按原始样本顺序汇总各样本产生的 stage rows、compile rows、semantic rows、proof rows 和 summary。

### 2.3 每个样本的高层流程

legacy 模式：

```text
sample
  -> A: ProblemIR
  -> MechLib string retrieval context
  -> B: StatementCandidate
  -> C: Lean statement check
  -> D: Semantic rank
  -> optional B revision loop
  -> E: existing proof stage
```

minimal skeleton 模式：

```text
sample
  -> A: ProblemIR
  -> MechLib string retrieval context
  -> StructuredMechLibContext
  -> A2: ModelIR
  -> SchemaPlanner
  -> EvidenceBinder
  -> ControlledSketch
  -> SketchAudit
  -> B: TheoremSkeletonCandidate
  -> C: Lean statement check
  -> D: Semantic rank
  -> optional B revision loop
  -> E: existing proof stage
```

本报告重点解释 D 之前的内容。

## 3. A 阶段：ProblemIR 生成

A 阶段由 `ModuleA` 执行，输入是 `CanonicalSample`。

输入字段主要包括：

- `sample_id`
- `problem_text`
- `options`
- `image_b64` / `image_path`
- `image_description`
- metadata

A 阶段会先对题面文本做泄漏清理，然后渲染 `prompts/A_extract_ir.txt`。如果样本带图且模型支持视觉输入，则走 multimodal 请求；否则走纯文本请求。

模型必须返回 JSON，解析为 ProblemIR payload。解析成功后，A 阶段会做一次物理 law 归一化。例如如果题面明显是运动学问题，但模型误把 law 标成 NewtonSecondLaw，代码会根据 force/mass/acceleration 等关键结构进行修正。

A 阶段输出 `GroundingResult`：

- `sample_id`
- `model_id`
- `problem_ir`
- `parse_ok`
- `raw_response`
- `error`
- vision retry marker

落盘文件：

- `problem_ir.jsonl`

如果 A 阶段失败，样本会提前结束，summary 中记录 grounding failure，不再进入 B/C/D。

## 4. MechLib 检索上下文

### 4.1 legacy string context

如果满足：

```text
retriever exists
grounding.parse_ok
statement.with_mechlib_context=true
```

orchestrator 会调用：

```python
MechLibRetriever.build_domain_context(...)
```

它会返回一个 domain pack，其中包含：

- `context_text`
- `summary_items`
- `verified_decl_items`
- `schema_items`
- `alias_items`
- `source_items`
- `law_matched_items`
- `proof_style_examples`
- 各类 count
- `gap_schema_only`

`context_text` 是旧 B/D/E 可注入的字符串上下文。是否注入某个阶段由：

```yaml
knowledge:
  inject_modules: ["B", "D", "E"]
```

控制。当前常见配置只注入 B。

落盘文件：

- `mechlib_retrieval.jsonl`

这个文件保留旧字段，同时也记录 v2 corpus 的 verified/schema/alias items，便于审计。

### 4.2 structured context

structured context 只在 minimal skeleton 模式启用。

结构是 `StructuredMechLibContext`，分三层：

1. `modeling_context`
   - `matched_topics`
   - `concepts`
   - `law_schemas`
   - `problem_schemas`
   - `aliases`
2. `proof_context`
   - `verified_decls`
   - `required_imports`
   - `proof_hints`
   - `proof_style_examples`
3. `forbidden_as_proof_fact`
   - schema
   - problem schema
   - concept
   - alignment
   - residual
   - interface
   - example-only material

这里最重要的原则是：schema、concept、problem schema、alignment 只能用于建模和规划，不能当作 proof fact。只有符合条件的 verified declaration 才能进入 `proof_context.verified_decls`。

落盘文件：

- `structured_mechlib_context.jsonl`

## 5. minimal skeleton 前半段

下面几节只在 `statement.generation_mode=minimal_skeleton` 时运行。

## 5.1 A2：ModelIR Builder

A2 阶段由 `ModuleA2ModelIR` 执行。

输入：

- `sample_id`
- `problem_text`
- A 阶段生成的 `problem_ir`
- `structured_mechlib_context`
- optional image description

输出：

- `ModelIR`

ModelIR 的职责不是生成 Lean theorem，而是建立建模层解释。它包括：

- `objects`
- `variables`
- `givens`
- `coordinate_system`
- `reference_frame`
- `local_definitions`
- `model_instances`
- `target`
- `forbidden_as_assumption`
- `source_problem_ir_hash`
- `raw_response`
- `parse_ok`
- `error`

其中最关键的是：

- `givens`：题面事实，带 `HypothesisProvenance`。
- `model_instances`：物理模型实例，例如某个一维牛顿第二定律实例、运动学约束、能量平衡等。
- `target`：最终要证明或表达的目标。
- `forbidden_as_assumption`：不能作为 theorem hypothesis 的内容，至少应覆盖 final target、candidate answer、derived law equations、algebra elimination results。

A2 会拒绝包含 Lean theorem 或 proof artifact 的输出，也要求：

- 至少有一个 `model_instance`。
- `forbidden_as_assumption` 覆盖 target。

通过后，`SchemaPlanner` 会根据 structured MechLib context 中的 law/problem schemas 给 `model_instance.planning_schema_id` 补 planning schema。注意：SchemaPlanner 只填 planning schema，不填 verified declaration。

落盘文件：

- `model_ir.jsonl`

## 5.2 EvidenceBinder

EvidenceBinder 的输入是：

- `ModelIR`
- `StructuredMechLibContext`
- problem text
- ProblemIR

它只从 `proof_context.verified_decls` 中选择候选 declaration。它不会把 law schema、problem schema、concept 或 alignment ID 写进 `verified_decl`。

绑定逻辑大致是：

1. 读取每个 `model_instance` 的 kind、natural language、expected claim、planning schema。
2. 从 structured context 的 proof declarations 中选择 proof-eligible rows。
3. 根据 schema alignment、alias、law/topic/name、token overlap 等打分。
4. 给每个 model instance 返回 top-k bindings。
5. 如果配置允许 Lean declaration check，使用 Lean runner 对 declaration 做可调用性检查。

每条输出是 `EvidenceBinding`：

- `binding_id`
- `model_instance_id`
- `planning_schema`
- `verified_decl`
- `decl_statement`
- `decl_status`
- `trust_level`
- `callable_by_llm`
- `required_imports`
- `lean_check_pass`
- `proof_fact_allowed`
- `binding_status`
- `expected_claim`
- `notes`

如果没有找到合格 verified declaration，则输出：

```text
binding_status = gap_schema_only
verified_decl = null
proof_fact_allowed = false
```

这就是当前 pipeline 对 MechLib 缺口的显式表达：不伪造 declaration，不把 schema 当 theorem。

落盘文件：

- `evidence_bindings.jsonl`

## 5.3 ControlledSketch

ControlledSketch 由 `ModuleControlledSketch` 执行。

输入：

- problem text
- ProblemIR
- ModelIR
- EvidenceBinding list
- StructuredMechLibContext

输出：

- `ControlledSketch`

ControlledSketch 的每个 step 必须是受控类型之一：

- `law_application`
- `constraint_application`
- `definition_expansion`
- `algebra_elimination`
- `target_rewrite`
- `positivity_or_domain`

对于 law/constraint step，必须带上：

- `source_model_instance`
- `planning_schema`
- `verified_decl` 或 `binding_status=gap_schema_only`
- `expected_claim`
- `proof_fact_allowed`

ControlledSketch 的用途是先描述“后续证明应该走哪些步骤”，但不把 law application 的结果直接塞进 theorem hypotheses。

落盘文件：

- `controlled_sketch.jsonl`

## 5.4 SketchAudit

SketchAudit 由 `SketchAuditor` 执行。它审计 ModelIR、ControlledSketch、EvidenceBinding 和 hypothesis provenance。

主要 hard gates：

- final target 不能出现在 hypotheses。
- candidate answer 不能出现在 hypotheses。
- law application result 不能作为普通 problem fact hypothesis。
- algebra elimination result 不能进入 hypotheses。
- schema/problem/concept/alignment/interface/residual/example metadata 不能作为 proof fact。
- 每个 hypothesis 必须有 provenance。
- proof-eligible step 必须使用 EvidenceBinder 白名单中的 verified declaration。
- `gap_schema_only` 不能被标成 proof fact。

输出是 `SketchAuditResult`：

- `audit_pass`
- `failure_tags`
- `failure_summary`
- `target_leakage`
- `candidate_answer_leakage`
- `raw_law_equation_in_hypotheses`
- `algebra_result_in_hypotheses`
- `schema_used_as_proof_fact`
- `unbound_verified_decl`
- `missing_provenance`
- `details`

落盘文件：

- `sketch_audit.jsonl`

## 6. B 阶段：生成 theorem candidate 或 minimal skeleton

B 阶段由 `ModuleB` 执行。它是 D 之前最关键的生成阶段。

## 6.1 legacy_candidate 路径

legacy 模式下，B 输入：

- `GroundingResult`
- string form MechLib context
- revision feedback
- previous candidates

B 渲染 legacy prompt：

- 第一轮使用 `B_generate_statements.txt`
- revision round 使用 `B_revise_statements.txt`

模型输出 JSON candidates。每个 candidate 会转成 `StatementCandidate`。

`StatementCandidate` 的核心字段：

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
- `verified_decl_refs`
- `schema_refs`
- `alias_refs`
- `grounding_status`
- `gap_schema_only`
- `parse_ok`
- `raw_response`
- `error`
- `round_index`
- `source_round_index`

B 会规范化 theorem declaration 和 header，并补充 MechLib grounding metadata。legacy 路径仍然允许生成多个 theorem candidate，后续由 C 检查、D 排序。

落盘文件：

- `statement_candidates.jsonl`

## 6.2 minimal_skeleton 路径

minimal 模式下，B 输入显著增加：

- ProblemIR
- ModelIR
- ControlledSketch
- EvidenceBinding list
- StructuredMechLibContext
- SketchAuditResult
- revision feedback
- previous candidates

B 输出 `TheoremSkeletonCandidate`。它继承 `StatementCandidate` 的旧字段，并增加：

- `generation_mode`
- `hypothesis_provenance`
- `model_ir_digest`
- `evidence_bindings`
- `controlled_sketch`
- `proof_obligations`
- `controlled_sketch_steps_used`
- `selected_laws`
- `verified_decls`
- `gap_laws`
- `fully_mechlib_verified`
- `skeleton_audit`

minimal B 的核心规则：

1. verified declarations 只能来自 EvidenceBinder 白名单。
2. proof obligations 以 ControlledSketch steps 为权威来源。
3. law application expected claim 保留在 `proof_obligations`。
4. 普通 theorem hypotheses 只允许题面事实、坐标约定、局部定义、模型实例、显式 gap law。
5. target、candidate answer、law application equation、algebra elimination result 不应成为普通 hypotheses。
6. 若没有 verified declaration，则记录 `gap_laws` 和 `gap_schema_only`，不假装绑定成功。
7. skeleton audit 失败时，该 candidate 不会交给 C/D。

minimal 模式会同时写：

- `statement_candidates.jsonl`
- `theorem_skeleton_candidates.jsonl`

## 7. C 阶段：Lean statement check

C 阶段由 `ModuleC` 执行，内部调用 `LeanRunner.compile_statement(...)`。

重要点：

1. C 不要求 B 输出完整 proof。
2. C 会先抽取 declaration-only 形态。
3. C 会预检查 theorem declaration，拒绝明显带 proof body 或 tactic residue 的 candidate。
4. C 在临时 Lean 文件中补内部证明占位块，只用于 statement elaboration check。
5. 这个临时占位不会写回 B 输出，也不会让 proof success 变成 true。
6. C 会根据 header 和 route policy 选择 backend：
   - MechLib
   - PhysLean
   - 或根据配置做 backend 路由
7. 结果写入 `CompileCheckResult`。

`CompileCheckResult` 包括：

- `compile_pass`
- `syntax_ok`
- `elaboration_ok`
- `error_type`
- `stderr_digest`
- `log_path`
- `backend_used`
- `route_reason`
- backend secondary-route marker
- `stderr_excerpt`
- `error_line`
- `error_message`
- `sub_error_type`
- `failure_tags`
- `failure_summary`
- `failure_details`

落盘文件：

- `compile_checks.jsonl`
- 具体 Lean 日志在 `runs/<run>/lean_compile/`

在 minimal 模式中，只有：

```text
candidate.parse_ok == true
candidate.skeleton_audit.audit_pass == true
```

的 skeleton candidate 才会进入 C。

## 8. D 阶段入口边界

D 阶段由 `ModuleD` 执行。本报告重点是 D 之前，因此这里只说明 D 的输入边界。

D 只对 compile-passed candidates 做 semantic ranking。如果没有任何 compile-passed candidate，D 直接返回 semantic fail，并记录 no compile-passed candidates 的原因。

D 输入：

- ProblemIR
- compile-passed candidates
- compile check results
- problem text
- 可选 MechLib context

D 会综合：

- target match
- known quantity coverage
- law match
- unit consistency
- assumption consistency
- trivial goal penalty
- backend bias
- proofability bias
- library grounding score
- verified declaration refs
- gap schema status

最后返回 `SemanticRankResult`，并写入：

- `semantic_rank.jsonl`

如果开启 feedback loop，并且当前 round 没有 compile pass 或 semantic fail，orchestrator 会把 compile/D 反馈整理成 revision feedback，再让 B 进行下一轮生成。当前默认最多一轮 revision。

## 9. 归档与报告

run 结束后，CLI 调用 F/reporting：

1. 根据 summaries 和 stage rows 生成 `metrics.json`。
2. 生成 `analysis.md`。
3. 生成 run `README.md`。
4. 生成 Lean export files。
5. 调用 archive writer 写入 `runs/<run>/`。
6. 清空并重建 `outputs/latest/` 轻量镜像。

因此同一批 stage rows 会出现在：

- `runs/<run>/`
- `outputs/latest/`

## 10. 当前 101 题运行的说明

2026-05-05 已尝试全量 101 题运行：

```bash
.venv/bin/python -m mech_pipeline.cli run \
  --config configs/mechanics101_proxy_gpt54_20260409.yaml \
  --sample-concurrency 5 \
  --tag mechanics101-full-try-20260505
```

该配置使用 legacy candidate 模式，不启用 minimal skeleton。因此：

- `model_ir.jsonl` 为空。
- `evidence_bindings.jsonl` 为空。
- `controlled_sketch.jsonl` 为空。
- `sketch_audit.jsonl` 为空。
- minimal skeleton metrics 为 null。

这不是新前半段失败，而是配置没有启用新模式。

本次 run 成功完成 101 个样本，主要结果：

- end-to-end verified solve：27 / 101
- grounding success rate：0.970297
- statement generation success rate：0.940594
- Lean compile success rate：0.936842
- semantic consistency pass rate：0.47191
- proof success rate：0.27551

失败主要集中在 semantic drift，其次是 proof search failure 和 elaboration failure。

## 11. 机制设计上的关键保证

当前 pipeline 在 D 之前有几条关键边界：

1. 旧 CLI 不变，旧配置默认仍走 legacy candidate。
2. minimal skeleton 必须显式打开。
3. schema metadata 只能用于建模和规划，不能作为 proof fact。
4. verified declaration 只能来自 EvidenceBinder 白名单。
5. gap 会显式记录为 `gap_schema_only`，不会伪装成 verified theorem。
6. B minimal skeleton 不负责生成完整证明。
7. C 只做 statement elaboration check。
8. D 只消费 compile-passed candidates；minimal 模式下还要求 skeleton audit pass。

这套边界的目的，是把“题目建模”“MechLib 证据绑定”“受控解题草图”“Lean statement 形状检查”和“语义排序”分开审计，避免把未验证的 schema、推导式或最终答案混入 theorem hypotheses。
