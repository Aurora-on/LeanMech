# E 阶段 certified proof search 改造基线备注

日期：2026-05-11
范围：只读复查当前 E 阶段与最新 minimal skeleton artifacts，不修改核心 prover 逻辑。

## 1. 当前 E 阶段入口函数

当前 E 阶段实现位于 `src/mech_pipeline/modules/E_prover.py`。

入口函数：

```python
ModuleE.run(
    grounding: GroundingResult,
    selected_candidate: StatementCandidate | None,
    run_dir: Path,
    mechlib_context: str = "(none)",
) -> tuple[list[ProofAttemptResult], ProofCheckResult]
```

调用位置：`src/mech_pipeline/orchestrator.py`。Orchestrator 在 D 阶段语义排序后：

1. 用 `semantic.selected_candidate_id` 从当前轮 `candidates` 中找到 `selected_candidate`。
2. 若 `semantic.semantic_pass = false`，直接生成 `proof_skipped_due_to_semantic_fail`。
3. 若通过语义检查，调用 `module_e.run(...)`。

当前调用只传入：

- `grounding`
- `selected_candidate`
- `run_dir`
- `mechlib_context`

没有把 `evidence_bindings`、`controlled_sketch`、`proof_obligations` 作为独立参数传给 E。

## 2. 当前 E 阶段输入字段

E 阶段实际读取的输入如下。

### 2.1 从 `GroundingResult` 读取

- `grounding.sample_id`
- `grounding.problem_ir`

`problem_ir` 会先经过 `sanitize_problem_ir_for_llm`，再序列化为 `problem_ir_json` 传给 LLM prompt。

### 2.2 从 `selected_candidate` 读取

当前 E 阶段实际使用：

- `selected_candidate.candidate_id`
- `selected_candidate.lean_header`
- `selected_candidate.theorem_decl`

其中：

- `theorem_decl` 传给 proof planning / proof generation / proof repair prompt。
- `lean_header` 与 `theorem_decl`、`proof_body` 一起传给 `LeanRunner.verify_proof`。
- `candidate_id` 用于 Lean 临时文件与日志命名，以及最终 `ProofCheckResult.selected_candidate_id`。

当前 E 阶段没有读取以下 minimal skeleton 字段：

- `selected_candidate.proof_obligations`
- `selected_candidate.evidence_bindings`
- `selected_candidate.controlled_sketch`
- `selected_candidate.controlled_sketch_steps_used`
- `selected_candidate.verified_decls`
- `selected_candidate.selected_laws`
- `selected_candidate.target_spec`
- `selected_candidate.hypothesis_provenance`
- `selected_candidate.model_predicate_bindings`
- `selected_candidate.explicit_model_gaps`

这些字段已经存在于 `TheoremSkeletonCandidate` 类型和 artifacts 中，但当前 E 阶段未消费。

### 2.3 从 `mechlib_context` 读取

E 阶段只接收一个字符串型 `mechlib_context`，并把它传给 LLM prompt。

注意：最新 run 的配置中：

```json
"knowledge": {
  "inject_modules": ["B"]
}
```

因此 orchestrator 中：

```python
e_context = mechlib_context if "E" in inject_set else "(none)"
```

在最新 run 中 E 实际收到的是 `"(none)"`，不是完整 MechLib retrieval context。

## 3. 当前 E 阶段控制流

当前 E 阶段仍然是 legacy full-proof generation 风格：

```text
LLM proof plan
  -> LLM full proof body
  -> Lean verify whole proof
  -> LLM repair whole proof
```

具体流程：

1. 调用 `E_plan_proof` prompt，让 LLM 输出 JSON proof plan：
   - `plan`
   - `theorems_to_apply`
   - `givens_to_use`
   - `intermediate_claims`
   - `algebraic_cleanup_only`

2. 调用 `E_generate_proof` prompt，让 LLM 输出完整 Lean proof body：
   - `proof_body`
   - `strategy`
   - `plan`
   - `used_facts`

3. 调用 `LeanRunner.verify_proof(...)`，把完整 theorem 与完整 proof body 拼成临时 Lean 文件：

   ```lean
   <header>

   <theorem_decl_without_body> := by
     <proof_body>
   ```

4. 若 Lean `strict_pass = true`，proof success。

5. 若失败，调用 `E_repair_proof` prompt，把 previous proof 与 previous Lean error 交给 LLM，要求生成一个新的完整 proof body。

当前没有“proof state -> tactic action -> Lean step check -> next proof state”的交互式循环。

## 4. 当前 E 阶段输出字段

### 4.1 `proof_attempts.jsonl`

类型：`ProofAttemptResult`

字段：

- `sample_id`
- `attempt_index`
- `proof_body`
- `parse_ok`
- `raw_response`
- `compile_pass`
- `strict_pass`
- `error_type`
- `stderr_digest`
- `log_path`
- `plan`
- `backend_used`
- `route_reason`
- `route_fallback_used`
- `sub_error_type`
- `failure_tags`
- `failure_summary`
- `failure_details`
- `proof_body_excerpt`
- `stderr_excerpt`
- `proof_plan`
- `theorems_to_apply`
- `givens_to_use`
- `intermediate_claims`
- `plan_grounding_ok`

当前 `proof_attempts.jsonl` 没有直接记录：

- `candidate_id`
- `round_index`
- `proof_obligations`
- `evidence_bindings`
- `controlled_sketch_steps_used`
- `validated_local_actions`
- `proof_trace`

因此若后续要做 certified proof search，建议为 E 新增独立 trace artifacts，而不是继续把所有信息塞进 `proof_body`。

### 4.2 `proof_checks.jsonl`

类型：`ProofCheckResult`

字段：

- `sample_id`
- `proof_success`
- `attempts_used`
- `selected_candidate_id`
- `error_type`
- `final_log_path`
- `backend_used`
- `round_index`
- `sub_error_type`
- `failure_tags`
- `failure_summary`
- `failure_details`

`proof_checks.jsonl` 记录的是最终 proof 检查结果，不包含逐步 tactic trace。

## 5. 最新 minimal skeleton metadata 是否已经进入 E

结论：metadata 已进入 B/D artifacts 和 `selected_candidate` 对象，但没有被当前 E 阶段消费。

最新 run：`outputs/latest`，tag 为 `minimal-routed-101-realapi-20260511`。

关键 artifact 计数：

| artifact | 行数 | 说明 |
| --- | ---: | --- |
| `statement_candidates.jsonl` | 162 | minimal skeleton candidates，含 `proof_obligations` 等字段 |
| `theorem_skeleton_candidates.jsonl` | 162 | 与 statement candidates 同步 |
| `controlled_sketch.jsonl` | 162 | 含 `proof_steps` / `algebra_obligation` |
| `evidence_bindings.jsonl` | 2360 | MechLib verified declaration bindings |
| `semantic_rank.jsonl` | 162 | D 阶段语义排序 |
| `proof_attempts.jsonl` | 59 | E 阶段 LLM proof attempts |
| `proof_checks.jsonl` | 96 | E 阶段最终 proof check rows |

候选中 minimal skeleton metadata 情况：

- 162 个 statement candidates 中，96 个含有 `proof_obligations`。
- `proof_obligations` 总数为 156。
- 37 个 semantic-pass selected candidates 中，27 个含有 `proof_obligations`，总 obligation 数为 51。

典型 `proof_obligations` 记录包含：

```json
{
  "step_id": "sk_mi1",
  "kind": "law_to_equation",
  "formal_claim": "v_avg = delta_x / delta_t",
  "verified_decl": "MechLib.Kinematics.PointMotion.displacement_forms_equiv_course_form",
  "binding_status": "ok",
  "proof_fact_allowed": true,
  "produces": "h_mi1"
}
```

这些字段存在于 `TheoremSkeletonCandidate`，但当前 `ModuleE.run` 没有读取。

## 6. 当前 E 是否读取 proof_obligations

结论：否。

当前 E 阶段没有：

- 遍历 `selected_candidate.proof_obligations`
- 按 obligation 生成局部 `have`
- 强制使用 obligation 中的 `verified_decl`
- 校验 `proof_fact_allowed`
- 区分 verified declaration 与 schema/problem/concept metadata
- 建立 local action trace
- 保存 Lean-validated step sequence

当前唯一接近 grounding 的逻辑是 `_plan_grounding_ok(...)`：

1. 检查 LLM plan 中的 `theorems_to_apply` 名称是否出现在 `mechlib_context` 字符串中。
2. 若问题明显包含 physics law 关键词而 LLM 标记为 `algebraic_cleanup_only`，则判为 false。

这不是 proof obligation consumption，也不是 verified extractor invocation。

## 7. 当前 E 如何使用 candidate / theorem_decl / problem_ir / mechlib_context

### candidate

当前 E 只把 `selected_candidate` 当成一个完整 theorem skeleton 容器使用：

- 取 `theorem_decl`
- 取 `lean_header`
- 取 `candidate_id`

它不关心 candidate 是 legacy candidate 还是 `minimal_skeleton` candidate。

### theorem_decl

`theorem_decl` 是当前 E 的核心输入。LLM planning、generation、repair 都围绕整段 theorem statement 展开。

LeanRunner 会用 `_declaration_only(theorem_decl)` 去掉已有 body，再拼接 LLM 返回的 proof body。

### problem_ir

`problem_ir` 只作为自然语言/结构化上下文传给 LLM，让 LLM理解题目和符号含义。Lean 不直接消费 `problem_ir`。

### mechlib_context

`mechlib_context` 只作为字符串进入 prompt。当前 E 不读取结构化 context，不使用 `RetrievedDecl` list，也不按 `callable_by_llm` whitelist 过滤 facts。

在最新 run 中，配置只向 B 注入知识，E 实际收到 `"(none)"`。

## 8. 当前 proof_attempts/proof_checks 基线结果

最新 run 中：

- `proof_checks.jsonl`: 96 行
- proof success: 17
- skipped due to semantic fail: 59
- proof_search_failure: 20

`proof_attempts.jsonl`：

- 59 行
- `strict_pass = true`: 17
- `compile_pass = true`: 18
- `proof_search_failure`: 41
- `partially_correct_but_unverifiable`: 1

这些 proof attempts 是整段 proof body 级别的检查结果，不是局部 tactic/action 级别结果。

## 9. 对后续 certified proof search 改造的直接含义

阶段 0 结论：

1. 当前 E 仍是 legacy full-proof generation。
2. minimal skeleton metadata 已经生成，并且进入 `StatementCandidate` / artifacts。
3. E 没有消费 `proof_obligations`。
4. E 没有显式调用 MechLib verified extractor declaration。
5. E 没有阻止 schema/problem/concept metadata 被 LLM 当 proof fact 使用；当前依赖 B/D 的 audit 和 statement generation 阶段控制。
6. E 的 Lean 校验粒度是整段 proof body，不是局部 action。
7. 若要实现 MechCopilot-style prover，应新增 E2 certified prover，并保留当前 `ModuleE` 作为 legacy fallback。

建议下一阶段最小改造方向：

- 新增 `ProofAction` / `ProofStateSnapshot` / `CertifiedProofTrace` 数据结构。
- 从 `selected_candidate.proof_obligations` 生成 deterministic first actions，例如 law extractor `have`。
- 新增 LeanRunner 局部 action checker，至少支持“当前 theorem + prefix proof + candidate tactic block”的 replay 检查。
- LLM 只生成候选 tactic block / intermediate `have`，系统逐条 Lean 验证。
- 只有 verified/core 或 verified/derived 且 `proof_fact_allowed = true` 的 declarations 可以进入 proof whitelist。
- 最终仍输出完整 proof，并用现有 `LeanRunner.verify_proof` 做 replay。
