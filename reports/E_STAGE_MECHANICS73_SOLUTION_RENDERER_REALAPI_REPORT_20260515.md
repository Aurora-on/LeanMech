# Mechanics73 E 阶段真实 API 交互报告

- run dir: `runs/20260515_194416_mechanics73-solution-renderer-realapi-20260515-v2`
- latest mirror: `outputs/latest`
- sample: `lean4phys-university_mechanics_Mechanics_73_University`
- B stage: `minimal_skeleton`
- E stage: `llm_guided_search`
- legacy fallback: disabled
- data sources:
  - `proof_strategy_prompts.jsonl`
  - `proof_action_checks.jsonl`
  - `proof_search_trace.jsonl`
  - `proof_attempts.jsonl`
  - `proof_checks.jsonl`
  - `proof_dependency_audit.jsonl`
  - `solution_trace.jsonl`
  - `natural_solution.jsonl`
  - `solution_render_audit.jsonl`

重要限制：本次 E 阶段产物没有保存完整 raw LLM JSON response。下面的“LLM 回答”来自已经解析并写入 `proof_action_checks.jsonl` 的 action proposals；`proof_strategy_prompts.jsonl` 保存的是 compact proof state、prompt excerpt 和关键字段，而不是完整 prompt 全文。

## 1. 总览

| 字段 | 值 |
| --- | --- |
| grounding_ok | True |
| statement_generation_ok | True |
| compile_ok | True |
| semantic_ok | True |
| proof_ok | False |
| end_to_end_ok | False |
| final_error_type | proof_search_failure |
| sub_error_type | target_proof_failed_after_blocked_obligations |
| search_status | failed |
| failure_reason | target_proof_failed_after_blocked_obligations |
| search_elapsed_s | 36.608 |
| nodes_expanded | 5 |
| llm_calls | 1 |
| probe_checks | 4 |
| physical_assumption_augmented | True |
| dependency classification | proof_failed |
| fully_mechlib_verified | False |

### 1.1 Dependency Audit

| 字段 | 值 |
| --- | --- |
| proof_success | False |
| used_verified_decls |  |
| required_verified_decls | `MechLib.Compat.PHYSlib.SI.newton_second_law` |
| missing_required_decls | `MechLib.Compat.PHYSlib.SI.newton_second_law` |
| covered_obligations |  |
| missing_obligations | `sk1`, `sk2` |
| gap_assisted | True |
| algebra_only | False |
| schema_metadata_in_proof_body | False |

本次 proof 没有使用 required verified declaration，两个 proof obligations 都因 `from_hypothesis_missing` 被 preflight 阻塞，因此最终不能标为 verified。

## 2. LLM 调用前的确定性动作

E 阶段在调用 LLM 前先做了两个确定性动作。

### 2.1 augment_physical_positive_hypotheses_1

| 字段 | 值 |
| --- | --- |
| source | deterministic |
| strategy | augment_physical_positive_hypotheses |
| accepted | True |
| status | progress |
| error_type |  |
| error_message | added 2 typed physical positivity assumption(s) |
| expected_effect | missing_side_condition: denominator `m1.val + m2.val` requires positivity facts for `m1.val`, `m2.val` |

新增物理正性假设：

```text
h_m1_pos : 0 < m1.val
h_m2_pos : 0 < m2.val
```

Lean check:

```text
compile_pass: true
syntax_ok: true
elaboration_ok: true
backend_used: mechlib
```

### 2.2 side_condition_1

| 字段 | 值 |
| --- | --- |
| source | deterministic |
| strategy | prove_side_condition |
| accepted | True |
| status | progress |
| error_type | unsolved_goals |
| error_message | unsolved goals |
| uses_facts | `h_m1_pos`, `h_m2_pos` |
| new_local_facts | `hden_m1_val___m2_val` |

Action:

```lean
have hden_m1_val___m2_val : m1.val + m2.val ≠ 0 := by
  nlinarith [h_m1_pos, h_m2_pos]
```

Lean check result:

```text
该局部 have 被接受，并产生新事实：
hden_m1_val___m2_val : m1.val + m2.val ≠ 0

整体 theorem target 尚未关闭，因此 probe 返回 progress / unsolved_goals。
```

剩余目标：

```lean
⊢ a.val = m2.val * g.val / (m1.val + m2.val) ∧
  T.val = m1.val * m2.val * g.val / (m1.val + m2.val)
```

## 3. LLM 收到的信息

本次 E 阶段只有一次 LLM strategy call。

| 字段 | 值 |
| --- | --- |
| llm_call_index | 1 |
| node_id | node_2_2 |
| depth | 2 |
| prompt_chars | 6252 |
| search_mode | target_proof_from_available_facts |
| failed_action_count | 0 |
| decl_candidate_mode | False |

### 3.1 Target

```lean
a.val = (m2.val * g.val) / (m1.val + m2.val) ∧
  T.val = (m1.val * m2.val * g.val) / (m1.val + m2.val)
```

### 3.2 Active Goals

```text
unsolved goals
m1 m2 : Mass
T Fnet1 Fnet2 : Force
g a : Acceleration
h_mi1_net_force_balance : Fnet1.val = T.val
h_mi1_newton_second_law : Fnet1.val = m1.val * a.val
h_mi2_net_force_balance : Fnet2.val = m2.val * g.val - T.val
h_mi2_newton_second_law : Fnet2.val = m2.val * a.val
h_m1_pos : 0 < m1.val
h_m2_pos : 0 < m2.val
hden_m1_val___m2_val : m1.val + m2.val ≠ 0
⊢ a.val = m2.val * g.val / (m1.val + m2.val) ∧
  T.val = m1.val * m2.val * g.val / (m1.val + m2.val)
```

### 3.3 Proof Prefix

```lean
have hden_m1_val___m2_val : m1.val + m2.val ≠ 0 := by
  nlinarith [h_m1_pos, h_m2_pos]
```

### 3.4 Local Facts

```text
h_mi1_net_force_balance : Fnet1.val = T.val
h_mi1_newton_second_law : Fnet1.val = m1.val * a.val
h_mi2_net_force_balance : Fnet2.val = m2.val * g.val - T.val
h_mi2_newton_second_law : Fnet2.val = m2.val * a.val
h_m1_pos : 0 < m1.val
h_m2_pos : 0 < m2.val
hden_m1_val___m2_val : m1.val + m2.val ≠ 0
```

### 3.5 Remaining / Blocked Obligations

`remaining_obligations` 为空，因为两个 required obligations 已被 preflight 标记为 blocked。blocked obligations 只作为诊断上下文，不是 LLM 可继续尝试使用的 active tasks。

| obligation_id | kind | must_use | formal_claim | produced_fact_name | replay_status | reason |
| --- | --- | --- | --- | --- | --- | --- |
| sk1 | constraint_to_equation | `MechLib.Compat.PHYSlib.SI.newton_second_law` | `T = m1 * a` | h_glider_force | blocked | from_hypothesis_missing |
| sk2 | constraint_to_equation | `MechLib.Compat.PHYSlib.SI.newton_second_law` | `m2 * g - T = m2 * a` | h_weight_force | blocked | from_hypothesis_missing |

### 3.6 Allowed Declarations

```text
allowed_decls: []
```

这意味着 LLM 不能引入或调用新的 MechLib declarations，只能基于已有 local facts 和已接受 proof prefix 做 target proof。

### 3.7 Prompt Excerpt

```text
You are a Lean proof strategy controller.

Your task is to propose the next proof action, not a complete proof.

Use the compact proof state's `search_mode` field.

When `search_mode` is `target_proof_from_available_facts`:
- the required proof obligations are either already handled or blocked by preflight;
- blocked obligations are diagnostic context, not active tasks;
- do not try to use blocked declarations or any unlisted declaration;
- prove the theorem target from available local facts and accepted proof-prefix facts;
- prefer a short target-proof fact plan with algebraic `have` facts plus a final closing tactic.

Do not:
- introduce new assumptions,
- modify the theorem statement,
- use sorry/admit/axiom,
- use declarations outside whitelist,
- use schema/problem metadata as proof facts.
- do not use constructor or split goals in the linear prefix search; close conjunctions with exact ⟨..., ...⟩ only when all components are already available.
- if extractor preflight blocked an obligation, do not keep trying that extractor shape.

Return JSON only.
```

Omitted context:

```text
full_retrieval_context
full_problem_ir
full_structured_mechlib_context
full_theorem_corpus
full_previous_proof_attempts
```

## 4. LLM 回答与 Lean 检查

本次 LLM 产生了 3 个 fact-plan actions。前两个被 Lean probe 接受为局部进展；第三个未通过。

### 4.1 llm_plan_1_1

| 字段 | 值 |
| --- | --- |
| source | llm |
| strategy | target_fact_plan_have |
| accepted | True |
| status | progress |
| error_type | unsolved_goals |
| error_message | unsolved goals |
| uses_facts | `h_mi1_net_force_balance`, `h_mi1_newton_second_law` |
| uses_decls |  |
| new_local_facts | `hTma` |
| new_local_fact_claims | `T.val = m1.val * a.val` |
| probe_checks_used | 2 |

LLM proposal:

```lean
have hTma : T.val = m1.val * a.val := by
  linarith [h_mi1_net_force_balance, h_mi1_newton_second_law]
```

Lean check result:

```text
该局部 have 被接受，产生：
hTma : T.val = m1.val * a.val

整体目标未关闭，因此 status=progress, error_type=unsolved_goals。
```

剩余目标摘录：

```lean
hTma : T.val = m1.val * a.val
⊢ a.val = m2.val * g.val / (m1.val + m2.val) ∧
  T.val = m1.val * m2.val * g.val / (m1.val + m2.val)
```

### 4.2 llm_plan_1_2

| 字段 | 值 |
| --- | --- |
| source | llm |
| strategy | target_fact_plan_have |
| accepted | True |
| status | progress |
| error_type | unsolved_goals |
| error_message | unsolved goals |
| uses_facts | `h_mi2_net_force_balance`, `h_mi2_newton_second_law`, `hTma`, `hden_m1_val___m2_val` |
| uses_decls |  |
| new_local_facts | `ha` |
| new_local_fact_claims | `a.val = m2.val * g.val / (m1.val + m2.val)` |
| probe_checks_used | 3 |

LLM proposal:

```lean
have ha : a.val = m2.val * g.val / (m1.val + m2.val) := by
  field_simp [hden_m1_val___m2_val] at *
  nlinarith [h_mi2_net_force_balance, h_mi2_newton_second_law, hTma]
```

实际写入的 tactic block 是单行版本：

```lean
have ha : a.val = m2.val * g.val / (m1.val + m2.val) := by
  field_simp [hden_m1_val___m2_val] at *; nlinarith [h_mi2_net_force_balance, h_mi2_newton_second_law, hTma]
```

Lean check result:

```text
该局部 have 被接受，产生：
ha : a.val = m2.val * g.val / (m1.val + m2.val)

整体目标仍未关闭，因此 status=progress, error_type=unsolved_goals。
```

剩余目标摘录：

```lean
hTma : T.val = m1.val * a.val
ha : a.val = m2.val * g.val / (m1.val + m2.val)
⊢ a.val = m2.val * g.val / (m1.val + m2.val) ∧
  T.val = m1.val * m2.val * g.val / (m1.val + m2.val)
```

### 4.3 llm_plan_1_3

| 字段 | 值 |
| --- | --- |
| source | llm |
| strategy | target_fact_plan_have |
| accepted | False |
| status | invalid |
| error_type | type_mismatch |
| error_message | linarith failed to find a contradiction |
| uses_facts | `hTma`, `ha` |
| uses_decls |  |
| proposed_local_facts | `hTfinal` |
| proposed_local_fact_claims | `T.val = m1.val * m2.val * g.val / (m1.val + m2.val)` |
| probe_checks_used | 4 |

LLM proposal:

```lean
have hTfinal : T.val = m1.val * m2.val * g.val / (m1.val + m2.val) := by
  nlinarith [hTma, ha]
```

Lean check result:

```text
rejected
error_type: type_mismatch
error_message: linarith failed to find a contradiction
```

Lean stderr excerpt:

```text
error: linarith failed to find a contradiction
case h1.h
m1 m2 : Mass
T Fnet1 Fnet2 : Force
g a : Acceleration
h_mi1_net_force_balance : Fnet1.val = T.val
h_mi1_newton_second_law : Fnet1.val = m1.val * a.val
h_mi2_net_force_balance : Fnet2.val = m2.val * g.val - T.val
h_mi2_newton_second_law : Fnet2.val = m2.val * a.val
h_m1_pos : 0 < m1.val
h_m2_pos : 0 < m2.val
hden_m1_val___m2_val : m1.val + m2.val ≠ 0
hTma : T.val = m1.val * a.val
ha : a.val = m2.val * g.val / (m1.val + m2.val)
a✝ : T.val < m1.val * m2.val * g.val / (m1.val + m2.val)
⊢ False
failed
```

Probe full proof body at failure:

```lean
have hden_m1_val___m2_val : m1.val + m2.val ≠ 0 := by
  nlinarith [h_m1_pos, h_m2_pos]
have hTma : T.val = m1.val * a.val := by
  linarith [h_mi1_net_force_balance, h_mi1_newton_second_law]
have ha : a.val = m2.val * g.val / (m1.val + m2.val) := by
  field_simp [hden_m1_val___m2_val] at *; nlinarith [h_mi2_net_force_balance, h_mi2_newton_second_law, hTma]
have hTfinal : T.val = m1.val * m2.val * g.val / (m1.val + m2.val) := by
  nlinarith [hTma, ha]
```

## 5. Action Check 汇总

| order | action_id | source | strategy | accepted | status | error_type | new fact |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | augment_physical_positive_hypotheses_1 | deterministic | augment_physical_positive_hypotheses | True | progress |  | `h_m1_pos`, `h_m2_pos` |
| 2 | side_condition_1 | deterministic | prove_side_condition | True | progress | unsolved_goals | `hden_m1_val___m2_val` |
| 3 | llm_plan_1_1 | llm | target_fact_plan_have | True | progress | unsolved_goals | `hTma` |
| 4 | llm_plan_1_2 | llm | target_fact_plan_have | True | progress | unsolved_goals | `ha` |
| 5 | llm_plan_1_3 | llm | target_fact_plan_have | False | invalid | type_mismatch |  |

## 6. 失败原因

本次失败有两层：

1. `sk1` / `sk2` 两个 proof obligations 被 preflight 标记为 `from_hypothesis_missing`，因此 required verified declaration `MechLib.Compat.PHYSlib.SI.newton_second_law` 没有被实际使用，dependency audit 不能覆盖 obligations。
2. 在 target proof fallback 中，LLM 成功构造了 `hTma` 和 `ha`，但第三步 `hTfinal` 只用 `nlinarith [hTma, ha]` 不足以证明张力闭式，Lean probe 拒绝该 action。

因此最终分类保持为：

```text
classification: proof_failed
fully_mechlib_verified: false
gap_assisted: true
```

## 7. SolutionRenderer 输出

虽然 E proof 未通过，SolutionRenderer 仍生成了自然语言 partial solution，并且通过 render audit。该解题流程明确披露：

```text
当前形式化证明未通过，因此以下只展示已构造的建模和计划步骤，不作为最终 verified solution。
```

`solution_trace.jsonl` 中最终答案包含两项，均标记为未验证：

```text
a = (m2 * g) / (m1 + m2)
T = (m1 * m2 * g) / (m1 + m2)
```

`solution_render_audit.jsonl`:

| 字段 | 值 |
| --- | --- |
| audit_pass | True |
| formula_coverage_pass | True |
| law_step_coverage_pass | True |
| unsupported_formula_count | 0 |
| proof_status_disclosure_pass | True |
| target_match_pass | True |

## 8. 后续建议

- E 阶段需要在 blocked obligation 处保留更强的 `from_hypothesis` 绑定，避免只剩 value-level gap hypotheses 后 required decl 无法 replay。
- `hTfinal` 的局部证明需要更强的分母非零处理或 `field_simp`/`ring_nf` 组合，而不是单独依赖 `nlinarith [hTma, ha]`。
- 报告层面建议后续保存 raw LLM response，当前只能从 parsed action proposals 还原 LLM 回答。
