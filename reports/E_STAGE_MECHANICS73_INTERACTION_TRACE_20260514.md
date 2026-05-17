# Mechanics73 E 阶段交互追踪报告

- 运行目录：`/Users/weizhixin/AI4Mechanics/LeanMech/runs/20260514_184211_mechanics73-strict-probe-no-pending-facts-20260514`
- latest 镜像：`/Users/weizhixin/AI4Mechanics/LeanMech/outputs/latest`
- 样本：`lean4phys-university_mechanics_Mechanics_73_University`
- 数据来源：`proof_strategy_prompts.jsonl`、`proof_action_checks.jsonl`、`proof_search_trace.jsonl`、`proof_attempts.jsonl`、`proof_checks.jsonl`、`proof_dependency_audit.jsonl`
- 重要限制：本次产物没有单独保存完整 LLM raw JSON response；下面的“LLM 输出”来自已经解析并写入 `proof_action_checks.jsonl` 的 `ProofActionProposal`。

## 1. 总览

| 字段 | 值 |
| --- | --- |
| compile_ok | True |
| semantic_ok | True |
| proof_ok | False |
| final_error_type | proof_search_failure |
| sub_error_type | search_queue_exhausted |
| search_status | failed |
| failure_reason | search_queue_exhausted |
| search_elapsed_s | 441.188 |
| nodes_expanded | 3 |
| llm_calls | 1 |
| probe_checks | 11 |
| physical_assumption_augmented | True |
| fully_mechlib_verified | False |
| dependency classification | proof_failed |

### 1.1 文件索引

| 文件 | 作用 |
| --- | --- |
| `proof_strategy_prompts.jsonl` | E 阶段发给 LLM 的 compact proof state，包括 target、prefix、local facts、remaining obligations、allowed decls 和 prompt excerpt |
| `proof_action_checks.jsonl` | 每个 deterministic / LLM action 的 tactic block、uses_facts、uses_decls、Lean probe 状态和 stderr excerpt |
| `proof_search_trace.jsonl` | 搜索级汇总：accepted/rejected actions、LLM calls、probe checks、最终 failure reason |
| `proof_attempts.jsonl` | E 阶段 attempt 聚合记录，内嵌 prompts、action checks、search trace 和 dependency audit |
| `proof_checks.jsonl` | 最终 proof check 结果 |
| `proof_dependency_audit.jsonl` | required decl / covered obligation / gap assisted / fully verified 分类 |
| `controlled_sketch.jsonl` | proof obligations 来源 |
| `theorem_skeleton_candidates.jsonl` | E 阶段使用的 theorem skeleton |
| `evidence_bindings.jsonl` | MechLib declaration binding 来源 |

注意：`proof_action_checks.jsonl` 是从 trace 中的 accepted actions + rejected actions 展开得到，不保证严格按实际执行时间排序。

## 2. 传给 LLM 的信息

本次只有一次 LLM strategy call。

| 字段 | 值 |
| --- | --- |
| llm_call_index | 1 |
| node_id | node_2_3 |
| depth | 2 |
| prompt_chars | 4689 |
| failed_action_count | 7 |

### 2.1 Target

```lean
a.val = (m2.val * g.val) / (m1.val + m2.val) ∧
  T.val = (m1.val * m2.val * g.val) / (m1.val + m2.val)
```

### 2.2 Proof Prefix Summary

```lean
have h_glider_newton : T = m1 * a1 := by
  simpa [MechLib.Compat.PHYSlib.SI.newton_second_law] using mi1_law
have hden_m1_val___m2_val : m1.val + m2.val ≠ 0 := by
  nlinarith [h_m1_pos, h_m2_pos]
```

### 2.3 Local Facts

```text
h_global_sign_convention_m1
h_global_sign_convention_m2
h_mi1_net_force_balance
h_mi1_newton_second_law
h_mi2_net_force_balance
h_mi2_newton_second_law
h_mi3_constraint_acceleration
h_mi3_expected_claim
same_acceleration_magnitude
mi1_law
mi2_law
h_glider_newton
h_m1_pos
h_m2_pos
hden_m1_val___m2_val
```

### 2.4 Remaining Obligations

| obligation_id | kind | from_hypothesis | must_use | formal_claim | produced_fact_name |
| --- | --- | --- | --- | --- | --- |
| sk2 | law_to_equation | mi2_law | MechLib.Compat.PHYSlib.SI.newton_second_law | `m2 * g - T = m2 * a2` | h_weight_newton |
| sk_mi3 | constraint_to_equation |  | MechLib.Kinematics.Verified.Kinematics.linear_constraint_velocity | `a1 = a ∧ a2 = a` | h_mi3 |

### 2.5 Allowed Declarations

```text
MechLib.Compat.PHYSlib.SI.newton_second_law
MechLib.Analytical.LagrangeEquation.eulerLagrange_iff_newton_course_form
MechLib.Dynamics.NewtonLaw.newtonSecondLaw_course_form
MechLib.Dynamics.NewtonLaw.newton_second_law_verified
MechLib.Dynamics.SystemDynamics.centerOfMassBalance_eq
MechLib.Examples.FinalTheoremDemos.newtonSecondLaw_byDefinition
MechLib.Kinematics.Verified.Kinematics.linear_constraint_velocity
MechLib.Examples.FinalTheoremDemos.eulerLagrangeNewtonBridge_byResidualAlgebra
MechLib.Examples.FinalTheoremDemos.uniformAccelerationDisplacement_byCalculation
```

## 3. LLM 输出

本次 LLM 返回两个 proposals，均未通过 Lean probe。

### 3.1 llm_1_1

| 字段 | 值 |
| --- | --- |
| strategy | derive_law_equation |
| accepted | False |
| status | invalid |
| error_type | type_mismatch |
| error_message | Type mismatch: After simplification, term |
| uses_facts | mi2_law |
| uses_decls | MechLib.Compat.PHYSlib.SI.newton_second_law |

```lean
have h_weight_newton : m2 * g - T = m2 * a2 := by
  simpa [MechLib.Compat.PHYSlib.SI.newton_second_law] using mi2_law
```

Lean stderr excerpt:

```text
error: Type mismatch: After simplification, term
  mi2_law
 has type
  Dynamics.NewtonLaw.NewtonSecondLaw m2 a2 T
but is expected to have type
  m2 * g - T = m2 * a2
```

### 3.2 llm_1_2

| 字段 | 值 |
| --- | --- |
| strategy | derive_model_equation |
| accepted | False |
| status | invalid |
| error_type | type_mismatch |
| error_message | Type mismatch: After simplification, term |
| uses_facts | same_acceleration_magnitude |
| uses_decls |  |

```lean
have h_mi3 : a1 = a ∧ a2 = a := by
  simpa using same_acceleration_magnitude
```

Lean stderr excerpt:

```text
error: Type mismatch: After simplification, term
  same_acceleration_magnitude
 has type
  a1.val = a.val ∧ a2.val = a.val
but is expected to have type
  a1 = a ∧ a2 = a
```

## 4. Lean Check 结果汇总

| row | source | action_id | strategy | accepted | status | error_type |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | deterministic | sk1_4 | deterministic_simpa_decl_using_hypothesis | True | progress | unsolved_goals |
| 2 | deterministic | augment_physical_positive_hypotheses_1 | augment_physical_positive_hypotheses | True | progress |  |
| 3 | deterministic | side_condition_1 | prove_side_condition | True | progress | unsolved_goals |
| 4 | deterministic | sk1_1 | deterministic_exact_extractor | False | invalid | type_mismatch |
| 5 | deterministic | sk1_2 | deterministic_simpa_using_extractor | False | invalid | type_mismatch |
| 6 | deterministic | sk1_3 | deterministic_infer_extractor_claim | False | invalid | type_mismatch |
| 7 | deterministic | sk2_1 | deterministic_exact_extractor | False | invalid | type_mismatch |
| 8 | deterministic | sk2_2 | deterministic_simpa_using_extractor | False | invalid | type_mismatch |
| 9 | deterministic | sk2_3 | deterministic_infer_extractor_claim | False | invalid | type_mismatch |
| 10 | deterministic | sk2_4 | deterministic_simpa_decl_using_hypothesis | False | invalid | type_mismatch |
| 11 | llm | llm_1_1 | derive_law_equation | False | invalid | type_mismatch |
| 12 | llm | llm_1_2 | derive_model_equation | False | invalid | type_mismatch |

### 4.1 Accepted Deterministic Actions

#### sk1_4

```lean
have h_glider_newton : T = m1 * a1 := by
  simpa [MechLib.Compat.PHYSlib.SI.newton_second_law] using mi1_law
```

Lean 接受该 prefix，但目标未关闭，因此 status 为 `progress / unsolved_goals`。

#### augment_physical_positive_hypotheses_1

自动补充两个 typed physical positivity assumptions：

```text
h_m1_pos : 0 < m1.val
h_m2_pos : 0 < m2.val
```

reason：

```text
missing_side_condition: denominator m1.val + m2.val requires positivity facts for m1.val, m2.val
```

#### side_condition_1

```lean
have hden_m1_val___m2_val : m1.val + m2.val ≠ 0 := by
  nlinarith [h_m1_pos, h_m2_pos]
```

Lean 接受该 side condition，但目标未关闭。

### 4.2 Rejected Extractor Attempts

#### sk1 exact extractor

```lean
have h_glider_newton : T = m1 * a1 := by
  exact MechLib.Compat.PHYSlib.SI.newton_second_law mi1_law
```

Lean stderr excerpt：

```text
error: Application type mismatch: The argument
  mi1_law
has type
  Dynamics.NewtonLaw.NewtonSecondLaw m1 a1 T
of sort `Prop` but is expected to have type
  Compat.PHYSlib.SI.Mass
of sort `Type` in the application
  Compat.PHYSlib.SI.newton_second_law mi1_law
```

#### sk2 exact extractor

```lean
have h_weight_newton : m2 * g - T = m2 * a2 := by
  exact MechLib.Compat.PHYSlib.SI.newton_second_law mi2_law
```

Lean stderr excerpt：

```text
error: Application type mismatch: The argument
  mi2_law
has type
  Dynamics.NewtonLaw.NewtonSecondLaw m2 a2 T
of sort `Prop` but is expected to have type
  Compat.PHYSlib.SI.Mass
of sort `Type` in the application
  Compat.PHYSlib.SI.newton_second_law mi2_law
```

## 5. Dependency Audit

| 字段 | 值 |
| --- | --- |
| proof_success | False |
| classification | proof_failed |
| fully_mechlib_verified | False |
| gap_assisted | True |
| algebra_only | False |
| used_verified_decls |  |
| required_verified_decls | MechLib.Compat.PHYSlib.SI.newton_second_law, MechLib.Kinematics.Verified.Kinematics.linear_constraint_velocity |
| missing_required_decls | MechLib.Compat.PHYSlib.SI.newton_second_law, MechLib.Kinematics.Verified.Kinematics.linear_constraint_velocity |
| covered_obligations |  |
| missing_obligations | sk1, sk2, sk_mi3 |
| schema_metadata_in_proof_body | False |

## 6. 关键观察

1. `MechLib.Compat.PHYSlib.SI.newton_second_law mi1_law` 和 `... mi2_law` 不是当前 `NewtonSecondLaw ...` predicate 的直接 extractor 调用形状。
2. `exact must_use from_hypothesis` 对 `sk1` 和 `sk2` 都返回 `type_mismatch`。
3. 本次仍有一个 deterministic `simpa [newton_second_law] using mi1_law` 被 Lean 接受为 `progress`，但 dependency audit 没有把 required declarations 计为已覆盖，最终仍是 `proof_failed`。
4. LLM 只调用一次，两个 proposal 都是 type mismatch，没有产生可接受动作。
5. allowed declarations 中仍包含多个对本题干扰较大的示例 theorem，例如 `eulerLagrangeNewtonBridge_byResidualAlgebra` 和 `uniformAccelerationDisplacement_byCalculation`。

## 7. 结论

本次 E 阶段没有生成最终 proof body，失败原因是 `search_queue_exhausted`。从交互 trace 看，核心问题不是代数求解本身，而是 proof obligation 的 verified declaration / expected claim 形状不匹配：系统仍把 `MechLib.Compat.PHYSlib.SI.newton_second_law` 当作可从 `NewtonSecondLaw ...` hypothesis 直接推出目标方程的 proof-friendly extractor 使用。

