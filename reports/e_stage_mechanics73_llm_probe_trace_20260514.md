# Mechanics73 E 阶段 LLM / Probe Check 追踪报告

- 运行目录：`/Users/weizhixin/AI4Mechanics/LeanMech/runs/20260514_164428_mechanics73-sidecondition-dedupe-20260514`
- 样本：`lean4phys-university_mechanics_Mechanics_73_University`
- 数据来源：`proof_strategy_prompts.jsonl`、`proof_action_checks.jsonl`、`proof_search_trace.jsonl`、`proof_dependency_audit.jsonl`、`sample_summary.jsonl`
- 重要观测限制：本次产物没有保存 LLM 原始 raw JSON response；下面的“LLM 输出”是从已解析并进入 `proof_action_checks` 的 `ProofActionProposal` 还原出来的。

## 1. 总览

| 字段 | 值 |
| --- | --- |
| compile_ok | True |
| semantic_ok | True |
| proof_ok | False |
| final_error_type | proof_search_failure |
| sub_error_type | max_llm_calls_exhausted |
| search_status | failed |
| failure_reason | max_llm_calls_exhausted |
| search_elapsed_s | 378.738 |
| nodes_expanded | 17 |
| llm_calls | 12 |
| probe_checks | 21 |
| physical_assumption_augmented | True |
| fully_mechlib_verified | False |
| classification | proof_failed |

### 1.1 Action 分布

| 类别 | 计数 |
| --- | --- |
| deterministic | 4 |
| llm | 21 |

| accepted | 计数 |
| --- | --- |
| False | 7 |
| True | 18 |

| strategy | 计数 |
| --- | --- |
| algebra_solve | 2 |
| augment_physical_positive_hypotheses | 1 |
| close_goal | 7 |
| derive_model_equation | 2 |
| deterministic_exact_extractor | 2 |
| introduce_intermediate_have | 4 |
| prove_side_condition | 1 |
| quantity_value_projection | 3 |
| rewrite_forward | 1 |
| split_conjunction | 2 |

| error_type | 计数 |
| --- | --- |
| None | 1 |
| action_guard_failed | 3 |
| no_meaningful_progress | 2 |
| symbol_hallucination | 1 |
| type_mismatch | 1 |
| unsolved_goals | 17 |

### 1.2 Dependency Audit

| 字段 | 值 |
| --- | --- |
| used_verified_decls |  |
| required_verified_decls | MechLib.Compat.PHYSlib.SI.newton_second_law, MechLib.Kinematics.Verified.Kinematics.linear_constraint_velocity |
| missing_required_decls | MechLib.Compat.PHYSlib.SI.newton_second_law, MechLib.Kinematics.Verified.Kinematics.linear_constraint_velocity |
| covered_obligations |  |
| missing_obligations | sk1, sk2, sk_mi3 |
| gap_assisted | True |
| algebra_only | False |
| schema_metadata_in_proof_body | False |

### 1.3 自动补充的物理正性假设

| name | variable | type | expression | reason |
| --- | --- | --- | --- | --- |
| h_m1_pos | m1 | Mass | 0 < m1.val | missing_side_condition: denominator m1.val + m2.val requires positivity facts for m1.val, m2.val |
| h_m2_pos | m2 | Mass | 0 < m2.val | missing_side_condition: denominator m1.val + m2.val requires positivity facts for m1.val, m2.val |

## 2. LLM 调用前的确定性动作

| file_order | action_id | strategy | accepted | status | error_type | new facts | new claims | probe_checks_used |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | sk1_1 | deterministic_exact_extractor | True | progress | unsolved_goals |  |  |  |
| 2 | sk2_1 | deterministic_exact_extractor | True | progress | unsolved_goals |  |  |  |
| 3 | augment_physical_positive_hypotheses_1 | augment_physical_positive_hypotheses | True | progress |  |  |  |  |
| 4 | side_condition_1 | prove_side_condition | True | progress | unsolved_goals | hden_m1_val___m2_val | m1.val + m2.val ≠ 0 | 3 |

### 2.1 sk1_1 `deterministic_exact_extractor`

```lean
have h_glider_nsl : T = m1 * a := by
  exact MechLib.Compat.PHYSlib.SI.newton_second_law mi1_law
```

| accepted | status | error_type | error_message | uses_facts | uses_decls | side_condition_denominator |
| --- | --- | --- | --- | --- | --- | --- |
| True | progress | unsolved_goals | Application type mismatch: The argument | mi1_law | MechLib.Compat.PHYSlib.SI.newton_second_law |  |

<details><summary>Lean stderr / goals excerpt</summary>

```text
/private/var/folders/vj/48782l41209gm2tv8w9s9gq40000gn/T/pipeline_proof_probe_ya8_2bo2.lean:24:54: error: Application type mismatch: The argument
  mi1_law
has type
  Dynamics.NewtonLaw.NewtonSecondLaw m1 a Fnet1
of sort `Prop` but is expected to have type
  Compat.PHYSlib.SI.Mass
of sort `Type` in the application
  Compat.PHYSlib.SI.newton_second_law mi1_law
/private/var/folders/vj/48782l41209gm2tv8w9s9gq40000gn/T/pipeline_proof_probe_ya8_2bo2.lean:22:59: error: unsolved goals
m1 m2 : Mass
T Fnet1 Fnet2 : Force
g a : Acceleration
h_net_force_mi1 : Fnet1.val = T.val
h_newton2_mi1 : Fnet1.val = m1.val * a.val
h_net_force_mi2 : Fnet2.val = m2.val * g.val - T.val
h_newton2_mi2 : Fnet2.val = m2.val * a.val
mi1_law : Dynamics.NewtonLaw.NewtonSecondLaw m1 a Fnet1
mi2_law : Dynamics.NewtonLaw....
```
```text
unsolved goals
m1 m2 : Mass
T Fnet1 Fnet2 : Force
g a : Acceleration
h_net_force_mi1 : Fnet1.val = T.val
h_newton2_mi1 : Fnet1.val = m1.val * a.val
h_net_force_mi2 : Fnet2.val = m2.val * g.val - T.val
h_newton2_mi2 : Fnet2.val = m2.val * a.val
mi1_law : Dynamics.NewtonLaw.NewtonSecondLaw m1 a Fnet1
mi2_law : Dynamics.NewtonLaw.NewtonSecondLaw m2 a Fnet2
h_glider_nsl : T = m1 * a
⊢ a.val = m2.val * g.val / (m1.val + m2.val) ∧ T.val = m1.val * m2.val * g.val / (m1.val + m2.val)
```
</details>

### 2.2 sk2_1 `deterministic_exact_extractor`

```lean
have h_weight_nsl : m2 * g - T = m2 * a := by
  exact MechLib.Compat.PHYSlib.SI.newton_second_law mi2_law
```

| accepted | status | error_type | error_message | uses_facts | uses_decls | side_condition_denominator |
| --- | --- | --- | --- | --- | --- | --- |
| True | progress | unsolved_goals | Application type mismatch: The argument | mi2_law | MechLib.Compat.PHYSlib.SI.newton_second_law |  |

<details><summary>Lean stderr / goals excerpt</summary>

```text
/private/var/folders/vj/48782l41209gm2tv8w9s9gq40000gn/T/pipeline_proof_probe_dpw8spgo.lean:24:54: error: Application type mismatch: The argument
  mi1_law
has type
  Dynamics.NewtonLaw.NewtonSecondLaw m1 a Fnet1
of sort `Prop` but is expected to have type
  Compat.PHYSlib.SI.Mass
of sort `Type` in the application
  Compat.PHYSlib.SI.newton_second_law mi1_law
/private/var/folders/vj/48782l41209gm2tv8w9s9gq40000gn/T/pipeline_proof_probe_dpw8spgo.lean:26:54: error: Application type mismatch: The argument
  mi2_law
has type
  Dynamics.NewtonLaw.NewtonSecondLaw m2 a Fnet2
of sort `Prop` but is expected to have type
  Compat.PHYSlib.SI.Mass
of sort `Type` in the application
  Compat.PHYSlib.SI.newton_second_law mi2_law
/private/var/folders/vj/48782l41209gm2tv8w9s9gq40000gn/T/pipeline_proof_p...
```
```text
unsolved goals
m1 m2 : Mass
T Fnet1 Fnet2 : Force
g a : Acceleration
h_net_force_mi1 : Fnet1.val = T.val
h_newton2_mi1 : Fnet1.val = m1.val * a.val
h_net_force_mi2 : Fnet2.val = m2.val * g.val - T.val
h_newton2_mi2 : Fnet2.val = m2.val * a.val
mi1_law : Dynamics.NewtonLaw.NewtonSecondLaw m1 a Fnet1
mi2_law : Dynamics.NewtonLaw.NewtonSecondLaw m2 a Fnet2
h_glider_nsl : T = m1 * a
h_weight_nsl : m2 * g - T = m2 * a
⊢ a.val = m2.val * g.val / (m1.val + m2.val) ∧ T.val = m1.val * m2.val * g.val / (m1.val + m2.val)
```
</details>

### 2.3 augment_physical_positive_hypotheses_1 `augment_physical_positive_hypotheses`


Added assumptions:
```json
[
  {
    "name": "h_m1_pos",
    "variable": "m1",
    "lean_type": "Mass",
    "expression": "0 < m1.val",
    "source": "e_physical_assumption_augmentation",
    "reason": "missing_side_condition: denominator m1.val + m2.val requires positivity facts for m1.val, m2.val"
  },
  {
    "name": "h_m2_pos",
    "variable": "m2",
    "lean_type": "Mass",
    "expression": "0 < m2.val",
    "source": "e_physical_assumption_augmentation",
    "reason": "missing_side_condition: denominator m1.val + m2.val requires positivity facts for m1.val, m2.val"
  }
]
```

| accepted | status | error_type | error_message | uses_facts | uses_decls | side_condition_denominator |
| --- | --- | --- | --- | --- | --- | --- |
| True | progress |  | added 2 typed physical positivity assumption(s) |  |  |  |

### 2.4 side_condition_1 `prove_side_condition`

```lean
have hden_m1_val___m2_val : m1.val + m2.val ≠ 0 := by
  nlinarith [h_m1_pos, h_m2_pos]
```

| accepted | status | error_type | error_message | uses_facts | uses_decls | side_condition_denominator |
| --- | --- | --- | --- | --- | --- | --- |
| True | progress | unsolved_goals | Application type mismatch: The argument | h_m1_pos, h_m2_pos |  | m1.val + m2.val |

<details><summary>Lean stderr / goals excerpt</summary>

```text
/private/var/folders/vj/48782l41209gm2tv8w9s9gq40000gn/T/pipeline_proof_probe_9zqdqlyq.lean:23:54: error: Application type mismatch: The argument
  mi1_law
has type
  Dynamics.NewtonLaw.NewtonSecondLaw m1 a Fnet1
of sort `Prop` but is expected to have type
  Compat.PHYSlib.SI.Mass
of sort `Type` in the application
  Compat.PHYSlib.SI.newton_second_law mi1_law
/private/var/folders/vj/48782l41209gm2tv8w9s9gq40000gn/T/pipeline_proof_probe_9zqdqlyq.lean:25:54: error: Application type mismatch: The argument
  mi2_law
has type
  Dynamics.NewtonLaw.NewtonSecondLaw m2 a Fnet2
of sort `Prop` but is expected to have type
  Compat.PHYSlib.SI.Mass
of sort `Type` in the application
  Compat.PHYSlib.SI.newton_second_law mi2_law
/private/var/folders/vj/48782l41209gm2tv8w9s9gq40000gn/T/pipeline_proof_p...
```
```text
unsolved goals
m1 m2 : Mass
T Fnet1 Fnet2 : Force
g a : Acceleration
h_net_force_mi1 : Fnet1.val = T.val
h_newton2_mi1 : Fnet1.val = m1.val * a.val
h_net_force_mi2 : Fnet2.val = m2.val * g.val - T.val
h_newton2_mi2 : Fnet2.val = m2.val * a.val
mi1_law : Dynamics.NewtonLaw.NewtonSecondLaw m1 a Fnet1
mi2_law : Dynamics.NewtonLaw.NewtonSecondLaw m2 a Fnet2
h_m1_pos : 0 < m1.val
h_m2_pos : 0 < m2.val
h_glider_nsl : T = m1 * a
h_weight_nsl : m2 * g - T = m2 * a
hden_m1_val___m2_val : m1.val + m2.val ≠ 0
⊢ a.val = m2.val * g.val / (m1.val + m2.val) ∧ T.val = m1.val * m2.val * g.val / (m1.val + m2.val)
```
</details>

## 3. 每次 LLM 调用与 Probe Check

### 3.1 LLM call 1: node `node_2_4`, depth 2

#### 传给 LLM 的结构化信息

| 字段 | 值 |
| --- | --- |
| llm_call_index | 1 |
| node_id | node_2_4 |
| depth | 2 |
| prompt_chars | 4289 |
| failed_action_count | 0 |
| local_fact_count | 12 |
| remaining_obligation_count | 1 |
| allowed_decl_count | 9 |
| omitted_context | full_retrieval_context, full_problem_ir, full_structured_mechlib_context, full_theorem_corpus, full_previous_proof_attempts |

Target excerpt:
```lean
a.val = (m2.val * g.val) / (m1.val + m2.val) ∧
  T.val = (m1.val * m2.val * g.val) / (m1.val + m2.val)
```
Proof prefix excerpt:
```lean
have h_glider_nsl : T = m1 * a := by
  exact MechLib.Compat.PHYSlib.SI.newton_second_law mi1_law
have h_weight_nsl : m2 * g - T = m2 * a := by
  exact MechLib.Compat.PHYSlib.SI.newton_second_law mi2_law
have hden_m1_val___m2_val : m1.val + m2.val ≠ 0 := by
  nlinarith [h_m1_pos, h_m2_pos]
```
Local facts:
```text
h_net_force_mi1
h_newton2_mi1
h_net_force_mi2
h_newton2_mi2
mi1_law
mi2_law
h_glider_nsl
h_weight_nsl
h_mi3
h_m1_pos
h_m2_pos
hden_m1_val___m2_val
```
Remaining obligations:
| obligation_id | kind | must_use | produced_fact_name | replay_status | formal_claim |
| --- | --- | --- | --- | --- | --- |
| sk_mi3 | constraint_to_equation | MechLib.Kinematics.Verified.Kinematics.linear_constraint_velocity | h_mi3 | pending | a1 = a2 ∧ T1 = T2 |

Allowed verified declarations:
```text
MechLib.Compat.PHYSlib.SI.newton_second_law
MechLib.Analytical.LagrangeEquation.eulerLagrange_iff_newton_course_form
MechLib.Dynamics.NewtonLaw.newtonSecondLaw_course_form
MechLib.Examples.FinalTheoremDemos.newtonSecondLaw_byDefinition
MechLib.Dynamics.NewtonLaw.newton_second_law_verified
MechLib.Dynamics.SystemDynamics.centerOfMassBalance_eq
MechLib.Kinematics.Verified.Kinematics.linear_constraint_velocity
MechLib.Examples.FinalTheoremDemos.eulerLagrangeNewtonBridge_byResidualAlgebra
MechLib.Examples.FinalTheoremDemos.uniformAccelerationDisplacement_byCalculation
```
<details><summary>Prompt excerpt retained in artifact</summary>

````text
You are a Lean proof strategy controller.

Your task is to propose the next proof action, not a complete proof.

You may use only:
- listed local facts,
- listed proof obligations,
- listed verified declarations,
- listed algebra strategy cards,
- standard tactics: simp, simp_all, rw, have, exact, apply, constructor, field_simp, ring_nf, linarith, nlinarith.

Do not:
- introduce new assumptions,
- modify the theorem statement,
- use sorry/admit/axiom,
- use declarations outside whitelist,
- use schema/problem metadata as proof facts.

Available strategy cards:
- derive_law_equation
- derive_model_equation
- prove_side_condition
- split_conjunction
- algebra_solve
- rewrite_forward
- rewrite_backward
- simp_normalize
- quantity_value_projection
- introduce_intermediate_have
- close_goal

Return JSON only:

{"proposals":[{"strategy":"derive_model_equation","tactic_block":"have hT : T.val = m1.val * a.val := by\n  linarith [hFnet1, h_mi1]","uses_facts":["hFnet1","h_mi1"],"uses_decls":[],"expected_effect":"derive a local equation from checked facts","priority":0.9}]}

Compact proof state:

```json
{
  "target": "a.val = (m2.val * g.val) / (m1.val + m2.val) ∧\n  T.val = (m1.val * m2.val * g.val) / (m1.val + m2.val)",
  "proof_prefix_summary": "have h_glider_nsl : T = m1 * a := by\n  exact MechLib.Compat.PHYSlib.SI.newton_second_law mi1_law\nhave h_weight_nsl : m2 * g - T = m2 * a := by\n  exact MechLib.Compat.PHYSlib.SI.newton_second_law mi2_law\nhave hden_m1_val___m2_val : m1.val + m2.val ≠ 0 := by\n  nlinarith [h_m1_pos, h_m2_pos]",
  "local_facts": [
    "h_net_force_mi1",...
````
</details>

#### LLM 输出动作（parsed proposals）

| action_id | strategy | priority | uses_facts | uses_decls | expected_effect |
| --- | --- | --- | --- | --- | --- |
| llm_1_1 | split_conjunction | 0.98 |  |  | split the conjunctive target into the two scalar equations for a.val and T.val |
| llm_1_2 | derive_model_equation | 0.88 | h_glider_nsl |  | project the first Newton-law equation to values for later algebraic elimination |
| llm_1_3 | derive_model_equation | 0.87 | h_weight_nsl |  | project the second Newton-law equation to values for later algebraic elimination |

Action `llm_1_1` tactic:
```lean
constructor
```
Action `llm_1_2` tactic:
```lean
have h1 : T.val = m1.val * a.val := by
  simpa using h_glider_nsl
```
Action `llm_1_3` tactic:
```lean
have h2 : m2.val * g.val - T.val = m2.val * a.val := by
  simpa using h_weight_nsl
```

#### Probe/check 结果

| action_id | accepted | status | error_type | error_message | new facts | new claims | probe_checks_used | raw_probe_status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| llm_1_1 | True | progress | unsolved_goals | Application type mismatch: The argument |  |  | 4 |  |
| llm_1_2 | True | progress | unsolved_goals | Application type mismatch: The argument | h1 | T.val = m1.val * a.val | 5 |  |
| llm_1_3 | True | progress | unsolved_goals | Application type mismatch: The argument | h2 | m2.val * g.val - T.val = m2.val * a.val | 6 |  |

<details><summary>llm_1_1 Lean stderr / goals excerpt</summary>

```text
/private/var/folders/vj/48782l41209gm2tv8w9s9gq40000gn/T/pipeline_proof_probe_6x9kvqhy.lean:23:54: error: Application type mismatch: The argument
  mi1_law
has type
  Dynamics.NewtonLaw.NewtonSecondLaw m1 a Fnet1
of sort `Prop` but is expected to have type
  Compat.PHYSlib.SI.Mass
of sort `Type` in the application
  Compat.PHYSlib.SI.newton_second_law mi1_law
/private/var/folders/vj/48782l41209gm2tv8w9s9gq40000gn/T/pipeline_proof_probe_6x9kvqhy.lean:25:54: error: Application type mismatch: The argument
  mi2_law
has type
  Dynamics.NewtonLaw.NewtonSecondLaw m2 a Fnet2
of sort `Prop` but is expected to have type
  Compat.PHYSlib.SI.Mass
of sort `Type` in the application
  Compat.PHYSlib.SI.newton_second_law mi2_law
/private/var/folders/vj/48782l41209gm2tv8w9s9gq40000gn/T/pipeline_proof_p...
```
```text
unsolved goals
case left
m1 m2 : Mass
T Fnet1 Fnet2 : Force
g a : Acceleration
h_net_force_mi1 : Fnet1.val = T.val
h_newton2_mi1 : Fnet1.val = m1.val * a.val
h_net_force_mi2 : Fnet2.val = m2.val * g.val - T.val
h_newton2_mi2 : Fnet2.val = m2.val * a.val
mi1_law : Dynamics.NewtonLaw.NewtonSecondLaw m1 a Fnet1
mi2_law : Dynamics.NewtonLaw.NewtonSecondLaw m2 a Fnet2
h_m1_pos : 0 < m1.val
h_m2_pos : 0 < m2.val
h_glider_nsl : T = m1 * a
h_weight_nsl : m2 * g - T = m2 * a
hden_m1_val___m2_val : m1.val + m2.val ≠ 0
⊢ a.val = m2.val * g.val / (m1.val + m2.val)

case right
m1 m2 : Mass
T Fnet1 Fnet2 : Force
g a : Acceleration
h_net_force_mi1 : Fnet1.val = T.val
h_newton2_mi1 : Fnet1.val = m1.val * a.val
h_net_force_mi2 : Fnet2.val = m2.val * g.val - T.val
h_newton2_mi2 : Fnet2.val = m2.val * a.v...
```
</details>

<details><summary>llm_1_2 Lean stderr / goals excerpt</summary>

```text
/private/var/folders/vj/48782l41209gm2tv8w9s9gq40000gn/T/pipeline_proof_probe_9_yt2flv.lean:23:54: error: Application type mismatch: The argument
  mi1_law
has type
  Dynamics.NewtonLaw.NewtonSecondLaw m1 a Fnet1
of sort `Prop` but is expected to have type
  Compat.PHYSlib.SI.Mass
of sort `Type` in the application
  Compat.PHYSlib.SI.newton_second_law mi1_law
/private/var/folders/vj/48782l41209gm2tv8w9s9gq40000gn/T/pipeline_proof_probe_9_yt2flv.lean:25:54: error: Application type mismatch: The argument
  mi2_law
has type
  Dynamics.NewtonLaw.NewtonSecondLaw m2 a Fnet2
of sort `Prop` but is expected to have type
  Compat.PHYSlib.SI.Mass
of sort `Type` in the application
  Compat.PHYSlib.SI.newton_second_law mi2_law
/private/var/folders/vj/48782l41209gm2tv8w9s9gq40000gn/T/pipeline_proof_p...
```
```text
unsolved goals
m1 m2 : Mass
T Fnet1 Fnet2 : Force
g a : Acceleration
h_net_force_mi1 : Fnet1.val = T.val
h_newton2_mi1 : Fnet1.val = m1.val * a.val
h_net_force_mi2 : Fnet2.val = m2.val * g.val - T.val
h_newton2_mi2 : Fnet2.val = m2.val * a.val
mi1_law : Dynamics.NewtonLaw.NewtonSecondLaw m1 a Fnet1
mi2_law : Dynamics.NewtonLaw.NewtonSecondLaw m2 a Fnet2
h_m1_pos : 0 < m1.val
h_m2_pos : 0 < m2.val
h_glider_nsl : T = m1 * a
h_weight_nsl : m2 * g - T = m2 * a
hden_m1_val___m2_val : m1.val + m2.val ≠ 0
h1 : T.val = m1.val * a.val
⊢ a.val = m2.val * g.val / (m1.val + m2.val) ∧ T.val = m1.val * m2.val * g.val / (m1.val + m2.val)
```
</details>

<details><summary>llm_1_3 Lean stderr / goals excerpt</summary>

```text
/private/var/folders/vj/48782l41209gm2tv8w9s9gq40000gn/T/pipeline_proof_probe_h0rtyr05.lean:23:54: error: Application type mismatch: The argument
  mi1_law
has type
  Dynamics.NewtonLaw.NewtonSecondLaw m1 a Fnet1
of sort `Prop` but is expected to have type
  Compat.PHYSlib.SI.Mass
of sort `Type` in the application
  Compat.PHYSlib.SI.newton_second_law mi1_law
/private/var/folders/vj/48782l41209gm2tv8w9s9gq40000gn/T/pipeline_proof_probe_h0rtyr05.lean:25:54: error: Application type mismatch: The argument
  mi2_law
has type
  Dynamics.NewtonLaw.NewtonSecondLaw m2 a Fnet2
of sort `Prop` but is expected to have type
  Compat.PHYSlib.SI.Mass
of sort `Type` in the application
  Compat.PHYSlib.SI.newton_second_law mi2_law
/private/var/folders/vj/48782l41209gm2tv8w9s9gq40000gn/T/pipeline_proof_p...
```
```text
unsolved goals
m1 m2 : Mass
T Fnet1 Fnet2 : Force
g a : Acceleration
h_net_force_mi1 : Fnet1.val = T.val
h_newton2_mi1 : Fnet1.val = m1.val * a.val
h_net_force_mi2 : Fnet2.val = m2.val * g.val - T.val
h_newton2_mi2 : Fnet2.val = m2.val * a.val
mi1_law : Dynamics.NewtonLaw.NewtonSecondLaw m1 a Fnet1
mi2_law : Dynamics.NewtonLaw.NewtonSecondLaw m2 a Fnet2
h_m1_pos : 0 < m1.val
h_m2_pos : 0 < m2.val
h_glider_nsl : T = m1 * a
h_weight_nsl : m2 * g - T = m2 * a
hden_m1_val___m2_val : m1.val + m2.val ≠ 0
h2 : m2.val * g.val - T.val = m2.val * a.val
⊢ a.val = m2.val * g.val / (m1.val + m2.val) ∧ T.val = m1.val * m2.val * g.val / (m1.val + m2.val)
```
</details>

### 3.2 LLM call 2: node `node_3_5`, depth 3

#### 传给 LLM 的结构化信息

| 字段 | 值 |
| --- | --- |
| llm_call_index | 2 |
| node_id | node_3_5 |
| depth | 3 |
| prompt_chars | 4302 |
| failed_action_count | 0 |
| local_fact_count | 12 |
| remaining_obligation_count | 1 |
| allowed_decl_count | 9 |
| omitted_context | full_retrieval_context, full_problem_ir, full_structured_mechlib_context, full_theorem_corpus, full_previous_proof_attempts |

Target excerpt:
```lean
a.val = (m2.val * g.val) / (m1.val + m2.val) ∧
  T.val = (m1.val * m2.val * g.val) / (m1.val + m2.val)
```
Proof prefix excerpt:
```lean
have h_glider_nsl : T = m1 * a := by
  exact MechLib.Compat.PHYSlib.SI.newton_second_law mi1_law
have h_weight_nsl : m2 * g - T = m2 * a := by
  exact MechLib.Compat.PHYSlib.SI.newton_second_law mi2_law
have hden_m1_val___m2_val : m1.val + m2.val ≠ 0 := by
  nlinarith [h_m1_pos, h_m2_pos]
constructor
```
Local facts:
```text
h_net_force_mi1
h_newton2_mi1
h_net_force_mi2
h_newton2_mi2
mi1_law
mi2_law
h_glider_nsl
h_weight_nsl
h_mi3
h_m1_pos
h_m2_pos
hden_m1_val___m2_val
```
Remaining obligations:
| obligation_id | kind | must_use | produced_fact_name | replay_status | formal_claim |
| --- | --- | --- | --- | --- | --- |
| sk_mi3 | constraint_to_equation | MechLib.Kinematics.Verified.Kinematics.linear_constraint_velocity | h_mi3 | pending | a1 = a2 ∧ T1 = T2 |

Allowed verified declarations:
```text
MechLib.Compat.PHYSlib.SI.newton_second_law
MechLib.Analytical.LagrangeEquation.eulerLagrange_iff_newton_course_form
MechLib.Dynamics.NewtonLaw.newtonSecondLaw_course_form
MechLib.Examples.FinalTheoremDemos.newtonSecondLaw_byDefinition
MechLib.Dynamics.NewtonLaw.newton_second_law_verified
MechLib.Dynamics.SystemDynamics.centerOfMassBalance_eq
MechLib.Kinematics.Verified.Kinematics.linear_constraint_velocity
MechLib.Examples.FinalTheoremDemos.eulerLagrangeNewtonBridge_byResidualAlgebra
MechLib.Examples.FinalTheoremDemos.uniformAccelerationDisplacement_byCalculation
```
<details><summary>Prompt excerpt retained in artifact</summary>

````text
You are a Lean proof strategy controller.

Your task is to propose the next proof action, not a complete proof.

You may use only:
- listed local facts,
- listed proof obligations,
- listed verified declarations,
- listed algebra strategy cards,
- standard tactics: simp, simp_all, rw, have, exact, apply, constructor, field_simp, ring_nf, linarith, nlinarith.

Do not:
- introduce new assumptions,
- modify the theorem statement,
- use sorry/admit/axiom,
- use declarations outside whitelist,
- use schema/problem metadata as proof facts.

Available strategy cards:
- derive_law_equation
- derive_model_equation
- prove_side_condition
- split_conjunction
- algebra_solve
- rewrite_forward
- rewrite_backward
- simp_normalize
- quantity_value_projection
- introduce_intermediate_have
- close_goal

Return JSON only:

{"proposals":[{"strategy":"derive_model_equation","tactic_block":"have hT : T.val = m1.val * a.val := by\n  linarith [hFnet1, h_mi1]","uses_facts":["hFnet1","h_mi1"],"uses_decls":[],"expected_effect":"derive a local equation from checked facts","priority":0.9}]}

Compact proof state:

```json
{
  "target": "a.val = (m2.val * g.val) / (m1.val + m2.val) ∧\n  T.val = (m1.val * m2.val * g.val) / (m1.val + m2.val)",
  "proof_prefix_summary": "have h_glider_nsl : T = m1 * a := by\n  exact MechLib.Compat.PHYSlib.SI.newton_second_law mi1_law\nhave h_weight_nsl : m2 * g - T = m2 * a := by\n  exact MechLib.Compat.PHYSlib.SI.newton_second_law mi2_law\nhave hden_m1_val___m2_val : m1.val + m2.val ≠ 0 := by\n  nlinarith [h_m1_pos, h_m2_pos]\nconstructor",
  "local_facts": [
    "h_ne...
````
</details>

#### LLM 输出动作（parsed proposals）

| action_id | strategy | priority | uses_facts | uses_decls | expected_effect |
| --- | --- | --- | --- | --- | --- |
| llm_2_1 | quantity_value_projection | 0.95 | h_glider_nsl |  | project the first Newton-law equation to `.val` form for algebraic manipulation of the first conjunct |
| llm_2_2 | quantity_value_projection | 0.93 | h_weight_nsl |  | project the second Newton-law equation to `.val` form so the two scalar equations can be combined |

Action `llm_2_1` tactic:
```lean
have h_glider_nsl_val : T.val = m1.val * a.val := by
  simpa using h_glider_nsl
```
Action `llm_2_2` tactic:
```lean
have h_weight_nsl_val : m2.val * g.val - T.val = m2.val * a.val := by
  simpa using h_weight_nsl
```

#### Probe/check 结果

| action_id | accepted | status | error_type | error_message | new facts | new claims | probe_checks_used | raw_probe_status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| llm_2_1 | True | progress | unsolved_goals | Application type mismatch: The argument | h_glider_nsl_val | T.val = m1.val * a.val | 7 |  |
| llm_2_2 | True | progress | unsolved_goals | Application type mismatch: The argument | h_weight_nsl_val | m2.val * g.val - T.val = m2.val * a.val | 8 |  |

<details><summary>llm_2_1 Lean stderr / goals excerpt</summary>

```text
/private/var/folders/vj/48782l41209gm2tv8w9s9gq40000gn/T/pipeline_proof_probe_e73dawmk.lean:23:54: error: Application type mismatch: The argument
  mi1_law
has type
  Dynamics.NewtonLaw.NewtonSecondLaw m1 a Fnet1
of sort `Prop` but is expected to have type
  Compat.PHYSlib.SI.Mass
of sort `Type` in the application
  Compat.PHYSlib.SI.newton_second_law mi1_law
/private/var/folders/vj/48782l41209gm2tv8w9s9gq40000gn/T/pipeline_proof_probe_e73dawmk.lean:25:54: error: Application type mismatch: The argument
  mi2_law
has type
  Dynamics.NewtonLaw.NewtonSecondLaw m2 a Fnet2
of sort `Prop` but is expected to have type
  Compat.PHYSlib.SI.Mass
of sort `Type` in the application
  Compat.PHYSlib.SI.newton_second_law mi2_law
/private/var/folders/vj/48782l41209gm2tv8w9s9gq40000gn/T/pipeline_proof_p...
```
```text
unsolved goals
case left
m1 m2 : Mass
T Fnet1 Fnet2 : Force
g a : Acceleration
h_net_force_mi1 : Fnet1.val = T.val
h_newton2_mi1 : Fnet1.val = m1.val * a.val
h_net_force_mi2 : Fnet2.val = m2.val * g.val - T.val
h_newton2_mi2 : Fnet2.val = m2.val * a.val
mi1_law : Dynamics.NewtonLaw.NewtonSecondLaw m1 a Fnet1
mi2_law : Dynamics.NewtonLaw.NewtonSecondLaw m2 a Fnet2
h_m1_pos : 0 < m1.val
h_m2_pos : 0 < m2.val
h_glider_nsl : T = m1 * a
h_weight_nsl : m2 * g - T = m2 * a
hden_m1_val___m2_val : m1.val + m2.val ≠ 0
h_glider_nsl_val : T.val = m1.val * a.val
⊢ a.val = m2.val * g.val / (m1.val + m2.val)

case right
m1 m2 : Mass
T Fnet1 Fnet2 : Force
g a : Acceleration
h_net_force_mi1 : Fnet1.val = T.val
h_newton2_mi1 : Fnet1.val = m1.val * a.val
h_net_force_mi2 : Fnet2.val = m2.val * g.val - T.va...
```
</details>

<details><summary>llm_2_2 Lean stderr / goals excerpt</summary>

```text
/private/var/folders/vj/48782l41209gm2tv8w9s9gq40000gn/T/pipeline_proof_probe_p7pmy2n8.lean:23:54: error: Application type mismatch: The argument
  mi1_law
has type
  Dynamics.NewtonLaw.NewtonSecondLaw m1 a Fnet1
of sort `Prop` but is expected to have type
  Compat.PHYSlib.SI.Mass
of sort `Type` in the application
  Compat.PHYSlib.SI.newton_second_law mi1_law
/private/var/folders/vj/48782l41209gm2tv8w9s9gq40000gn/T/pipeline_proof_probe_p7pmy2n8.lean:25:54: error: Application type mismatch: The argument
  mi2_law
has type
  Dynamics.NewtonLaw.NewtonSecondLaw m2 a Fnet2
of sort `Prop` but is expected to have type
  Compat.PHYSlib.SI.Mass
of sort `Type` in the application
  Compat.PHYSlib.SI.newton_second_law mi2_law
/private/var/folders/vj/48782l41209gm2tv8w9s9gq40000gn/T/pipeline_proof_p...
```
```text
unsolved goals
case left
m1 m2 : Mass
T Fnet1 Fnet2 : Force
g a : Acceleration
h_net_force_mi1 : Fnet1.val = T.val
h_newton2_mi1 : Fnet1.val = m1.val * a.val
h_net_force_mi2 : Fnet2.val = m2.val * g.val - T.val
h_newton2_mi2 : Fnet2.val = m2.val * a.val
mi1_law : Dynamics.NewtonLaw.NewtonSecondLaw m1 a Fnet1
mi2_law : Dynamics.NewtonLaw.NewtonSecondLaw m2 a Fnet2
h_m1_pos : 0 < m1.val
h_m2_pos : 0 < m2.val
h_glider_nsl : T = m1 * a
h_weight_nsl : m2 * g - T = m2 * a
hden_m1_val___m2_val : m1.val + m2.val ≠ 0
h_weight_nsl_val : m2.val * g.val - T.val = m2.val * a.val
⊢ a.val = m2.val * g.val / (m1.val + m2.val)

case right
m1 m2 : Mass
T Fnet1 Fnet2 : Force
g a : Acceleration
h_net_force_mi1 : Fnet1.val = T.val
h_newton2_mi1 : Fnet1.val = m1.val * a.val
h_net_force_mi2 : Fnet2.val = m2.v...
```
</details>

### 3.3 LLM call 3: node `node_4_8`, depth 4

#### 传给 LLM 的结构化信息

| 字段 | 值 |
| --- | --- |
| llm_call_index | 3 |
| node_id | node_4_8 |
| depth | 4 |
| prompt_chars | 4408 |
| failed_action_count | 0 |
| local_fact_count | 13 |
| remaining_obligation_count | 1 |
| allowed_decl_count | 9 |
| omitted_context | full_retrieval_context, full_problem_ir, full_structured_mechlib_context, full_theorem_corpus, full_previous_proof_attempts |

Target excerpt:
```lean
a.val = (m2.val * g.val) / (m1.val + m2.val) ∧
  T.val = (m1.val * m2.val * g.val) / (m1.val + m2.val)
```
Proof prefix excerpt:
```lean
have h_glider_nsl : T = m1 * a := by
  exact MechLib.Compat.PHYSlib.SI.newton_second_law mi1_law
have h_weight_nsl : m2 * g - T = m2 * a := by
  exact MechLib.Compat.PHYSlib.SI.newton_second_law mi2_law
have hden_m1_val___m2_val : m1.val + m2.val ≠ 0 := by
  nlinarith [h_m1_pos, h_m2_pos]
constructor
have h_glider_nsl_val : T.val = m1.val * a.val := by
  simpa using h_glider_nsl
```
Local facts:
```text
h_net_force_mi1
h_newton2_mi1
h_net_force_mi2
h_newton2_mi2
mi1_law
mi2_law
h_glider_nsl
h_weight_nsl
h_mi3
h_m1_pos
h_m2_pos
hden_m1_val___m2_val
h_glider_nsl_val
```
Remaining obligations:
| obligation_id | kind | must_use | produced_fact_name | replay_status | formal_claim |
| --- | --- | --- | --- | --- | --- |
| sk_mi3 | constraint_to_equation | MechLib.Kinematics.Verified.Kinematics.linear_constraint_velocity | h_mi3 | pending | a1 = a2 ∧ T1 = T2 |

Allowed verified declarations:
```text
MechLib.Compat.PHYSlib.SI.newton_second_law
MechLib.Analytical.LagrangeEquation.eulerLagrange_iff_newton_course_form
MechLib.Dynamics.NewtonLaw.newtonSecondLaw_course_form
MechLib.Examples.FinalTheoremDemos.newtonSecondLaw_byDefinition
MechLib.Dynamics.NewtonLaw.newton_second_law_verified
MechLib.Dynamics.SystemDynamics.centerOfMassBalance_eq
MechLib.Kinematics.Verified.Kinematics.linear_constraint_velocity
MechLib.Examples.FinalTheoremDemos.eulerLagrangeNewtonBridge_byResidualAlgebra
MechLib.Examples.FinalTheoremDemos.uniformAccelerationDisplacement_byCalculation
```
<details><summary>Prompt excerpt retained in artifact</summary>

````text
You are a Lean proof strategy controller.

Your task is to propose the next proof action, not a complete proof.

You may use only:
- listed local facts,
- listed proof obligations,
- listed verified declarations,
- listed algebra strategy cards,
- standard tactics: simp, simp_all, rw, have, exact, apply, constructor, field_simp, ring_nf, linarith, nlinarith.

Do not:
- introduce new assumptions,
- modify the theorem statement,
- use sorry/admit/axiom,
- use declarations outside whitelist,
- use schema/problem metadata as proof facts.

Available strategy cards:
- derive_law_equation
- derive_model_equation
- prove_side_condition
- split_conjunction
- algebra_solve
- rewrite_forward
- rewrite_backward
- simp_normalize
- quantity_value_projection
- introduce_intermediate_have
- close_goal

Return JSON only:

{"proposals":[{"strategy":"derive_model_equation","tactic_block":"have hT : T.val = m1.val * a.val := by\n  linarith [hFnet1, h_mi1]","uses_facts":["hFnet1","h_mi1"],"uses_decls":[],"expected_effect":"derive a local equation from checked facts","priority":0.9}]}

Compact proof state:

```json
{
  "target": "a.val = (m2.val * g.val) / (m1.val + m2.val) ∧\n  T.val = (m1.val * m2.val * g.val) / (m1.val + m2.val)",
  "proof_prefix_summary": "have h_glider_nsl : T = m1 * a := by\n  exact MechLib.Compat.PHYSlib.SI.newton_second_law mi1_law\nhave h_weight_nsl : m2 * g - T = m2 * a := by\n  exact MechLib.Compat.PHYSlib.SI.newton_second_law mi2_law\nhave hden_m1_val___m2_val : m1.val + m2.val ≠ 0 := by\n  nlinarith [h_m1_pos, h_m2_pos]\nconstructor\nhave h_glider_nsl_val : T.val...
````
</details>

#### LLM 输出动作（parsed proposals）

| action_id | strategy | priority | uses_facts | uses_decls | expected_effect |
| --- | --- | --- | --- | --- | --- |
| llm_3_1 | quantity_value_projection | 0.97 | h_weight_nsl |  | project the second Newton-law equation to `.val` form for algebraic solving of the first conjunct |
| llm_3_2 | rewrite_forward | 0.88 | h_glider_nsl_val, h_weight_nsl_val |  | eliminate T.val from the hanging-mass equation to obtain an equation only in a.val |
| llm_3_3 | algebra_solve | 0.8 | hden_m1_val___m2_val, h_weight_nsl_val, h_glider_nsl_val, h_m1_pos, h_m2_pos |  | solve the first conjunct for a.val after clearing the denominator |

Action `llm_3_1` tactic:
```lean
have h_weight_nsl_val : m2.val * g.val - T.val = m2.val * a.val := by
  simpa using h_weight_nsl
```
Action `llm_3_2` tactic:
```lean
rw [h_glider_nsl_val] at h_weight_nsl_val
```
Action `llm_3_3` tactic:
```lean
field_simp [hden_m1_val___m2_val]
 nlinarith [h_weight_nsl_val, h_glider_nsl_val, h_m1_pos, h_m2_pos]
```

#### Probe/check 结果

| action_id | accepted | status | error_type | error_message | new facts | new claims | probe_checks_used | raw_probe_status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| llm_3_1 | True | progress | unsolved_goals | Application type mismatch: The argument | h_weight_nsl_val | m2.val * g.val - T.val = m2.val * a.val | 9 |  |
| llm_3_2 | False | invalid | action_guard_failed | unknown_or_unproved_local_fact |  |  |  |  |
| llm_3_3 | False | invalid | action_guard_failed | unknown_or_unproved_local_fact |  |  |  |  |

<details><summary>llm_3_1 Lean stderr / goals excerpt</summary>

```text
/private/var/folders/vj/48782l41209gm2tv8w9s9gq40000gn/T/pipeline_proof_probe_1313mqoh.lean:23:54: error: Application type mismatch: The argument
  mi1_law
has type
  Dynamics.NewtonLaw.NewtonSecondLaw m1 a Fnet1
of sort `Prop` but is expected to have type
  Compat.PHYSlib.SI.Mass
of sort `Type` in the application
  Compat.PHYSlib.SI.newton_second_law mi1_law
/private/var/folders/vj/48782l41209gm2tv8w9s9gq40000gn/T/pipeline_proof_probe_1313mqoh.lean:25:54: error: Application type mismatch: The argument
  mi2_law
has type
  Dynamics.NewtonLaw.NewtonSecondLaw m2 a Fnet2
of sort `Prop` but is expected to have type
  Compat.PHYSlib.SI.Mass
of sort `Type` in the application
  Compat.PHYSlib.SI.newton_second_law mi2_law
/private/var/folders/vj/48782l41209gm2tv8w9s9gq40000gn/T/pipeline_proof_p...
```
```text
unsolved goals
case left
m1 m2 : Mass
T Fnet1 Fnet2 : Force
g a : Acceleration
h_net_force_mi1 : Fnet1.val = T.val
h_newton2_mi1 : Fnet1.val = m1.val * a.val
h_net_force_mi2 : Fnet2.val = m2.val * g.val - T.val
h_newton2_mi2 : Fnet2.val = m2.val * a.val
mi1_law : Dynamics.NewtonLaw.NewtonSecondLaw m1 a Fnet1
mi2_law : Dynamics.NewtonLaw.NewtonSecondLaw m2 a Fnet2
h_m1_pos : 0 < m1.val
h_m2_pos : 0 < m2.val
h_glider_nsl : T = m1 * a
h_weight_nsl : m2 * g - T = m2 * a
hden_m1_val___m2_val : m1.val + m2.val ≠ 0
h_glider_nsl_val : T.val = m1.val * a.val
h_weight_nsl_val : m2.val * g.val - T.val = m2.val * a.val
⊢ a.val = m2.val * g.val / (m1.val + m2.val)

case right
m1 m2 : Mass
T Fnet1 Fnet2 : Force
g a : Acceleration
h_net_force_mi1 : Fnet1.val = T.val
h_newton2_mi1 : Fnet1.val = m1.val ...
```
</details>

<details><summary>llm_3_2 Lean stderr / goals excerpt</summary>

```text
unknown_or_unproved_local_fact
```
</details>

<details><summary>llm_3_3 Lean stderr / goals excerpt</summary>

```text
unknown_or_unproved_local_fact
```
</details>

### 3.4 LLM call 4: node `node_5_10`, depth 5

#### 传给 LLM 的结构化信息

| 字段 | 值 |
| --- | --- |
| llm_call_index | 4 |
| node_id | node_5_10 |
| depth | 5 |
| prompt_chars | 5035 |
| failed_action_count | 2 |
| local_fact_count | 14 |
| remaining_obligation_count | 1 |
| allowed_decl_count | 9 |
| omitted_context | full_retrieval_context, full_problem_ir, full_structured_mechlib_context, full_theorem_corpus, full_previous_proof_attempts |

Target excerpt:
```lean
a.val = (m2.val * g.val) / (m1.val + m2.val) ∧
  T.val = (m1.val * m2.val * g.val) / (m1.val + m2.val)
```
Proof prefix excerpt:
```lean
have h_glider_nsl : T = m1 * a := by
  exact MechLib.Compat.PHYSlib.SI.newton_second_law mi1_law
have h_weight_nsl : m2 * g - T = m2 * a := by
  exact MechLib.Compat.PHYSlib.SI.newton_second_law mi2_law
have hden_m1_val___m2_val : m1.val + m2.val ≠ 0 := by
  nlinarith [h_m1_pos, h_m2_pos]
constructor
have h_glider_nsl_val : T.val = m1.val * a.val := by
  simpa using h_glider_nsl
have h_weight_nsl_val : m2.val * g.val - T.val = m2.val * a.val := by
  simpa using h_weight_nsl
```
Local facts:
```text
h_net_force_mi1
h_newton2_mi1
h_net_force_mi2
h_newton2_mi2
mi1_law
mi2_law
h_glider_nsl
h_weight_nsl
h_mi3
h_m1_pos
h_m2_pos
hden_m1_val___m2_val
h_glider_nsl_val
h_weight_nsl_val
```
Remaining obligations:
| obligation_id | kind | must_use | produced_fact_name | replay_status | formal_claim |
| --- | --- | --- | --- | --- | --- |
| sk_mi3 | constraint_to_equation | MechLib.Kinematics.Verified.Kinematics.linear_constraint_velocity | h_mi3 | pending | a1 = a2 ∧ T1 = T2 |

Allowed verified declarations:
```text
MechLib.Compat.PHYSlib.SI.newton_second_law
MechLib.Analytical.LagrangeEquation.eulerLagrange_iff_newton_course_form
MechLib.Dynamics.NewtonLaw.newtonSecondLaw_course_form
MechLib.Examples.FinalTheoremDemos.newtonSecondLaw_byDefinition
MechLib.Dynamics.NewtonLaw.newton_second_law_verified
MechLib.Dynamics.SystemDynamics.centerOfMassBalance_eq
MechLib.Kinematics.Verified.Kinematics.linear_constraint_velocity
MechLib.Examples.FinalTheoremDemos.eulerLagrangeNewtonBridge_byResidualAlgebra
MechLib.Examples.FinalTheoremDemos.uniformAccelerationDisplacement_byCalculation
```
<details><summary>Prompt excerpt retained in artifact</summary>

````text
You are a Lean proof strategy controller.

Your task is to propose the next proof action, not a complete proof.

You may use only:
- listed local facts,
- listed proof obligations,
- listed verified declarations,
- listed algebra strategy cards,
- standard tactics: simp, simp_all, rw, have, exact, apply, constructor, field_simp, ring_nf, linarith, nlinarith.

Do not:
- introduce new assumptions,
- modify the theorem statement,
- use sorry/admit/axiom,
- use declarations outside whitelist,
- use schema/problem metadata as proof facts.

Available strategy cards:
- derive_law_equation
- derive_model_equation
- prove_side_condition
- split_conjunction
- algebra_solve
- rewrite_forward
- rewrite_backward
- simp_normalize
- quantity_value_projection
- introduce_intermediate_have
- close_goal

Return JSON only:

{"proposals":[{"strategy":"derive_model_equation","tactic_block":"have hT : T.val = m1.val * a.val := by\n  linarith [hFnet1, h_mi1]","uses_facts":["hFnet1","h_mi1"],"uses_decls":[],"expected_effect":"derive a local equation from checked facts","priority":0.9}]}

Compact proof state:

```json
{
  "target": "a.val = (m2.val * g.val) / (m1.val + m2.val) ∧\n  T.val = (m1.val * m2.val * g.val) / (m1.val + m2.val)",
  "proof_prefix_summary": "have h_glider_nsl : T = m1 * a := by\n  exact MechLib.Compat.PHYSlib.SI.newton_second_law mi1_law\nhave h_weight_nsl : m2 * g - T = m2 * a := by\n  exact MechLib.Compat.PHYSlib.SI.newton_second_law mi2_law\nhave hden_m1_val___m2_val : m1.val + m2.val ≠ 0 := by\n  nlinarith [h_m1_pos, h_m2_pos]\nconstructor\nhave h_glider_nsl_val : T.val...
````
</details>

#### LLM 输出动作（parsed proposals）

| action_id | strategy | priority | uses_facts | uses_decls | expected_effect |
| --- | --- | --- | --- | --- | --- |
| llm_4_1 | introduce_intermediate_have | 0.98 | h_glider_nsl_val, h_weight_nsl_val |  | combine the two Newton-law value equations to eliminate T.val and obtain the main linear equation for a.val |

Action `llm_4_1` tactic:
```lean
have h_sum_eq : m2.val * g.val = (m1.val + m2.val) * a.val := by
  nlinarith [h_glider_nsl_val, h_weight_nsl_val]
```

#### Probe/check 结果

| action_id | accepted | status | error_type | error_message | new facts | new claims | probe_checks_used | raw_probe_status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| llm_4_1 | True | progress | unsolved_goals | Application type mismatch: The argument | h_sum_eq | m2.val * g.val = (m1.val + m2.val) * a.val | 10 |  |

<details><summary>llm_4_1 Lean stderr / goals excerpt</summary>

```text
/private/var/folders/vj/48782l41209gm2tv8w9s9gq40000gn/T/pipeline_proof_probe_zvevljp7.lean:23:54: error: Application type mismatch: The argument
  mi1_law
has type
  Dynamics.NewtonLaw.NewtonSecondLaw m1 a Fnet1
of sort `Prop` but is expected to have type
  Compat.PHYSlib.SI.Mass
of sort `Type` in the application
  Compat.PHYSlib.SI.newton_second_law mi1_law
/private/var/folders/vj/48782l41209gm2tv8w9s9gq40000gn/T/pipeline_proof_probe_zvevljp7.lean:25:54: error: Application type mismatch: The argument
  mi2_law
has type
  Dynamics.NewtonLaw.NewtonSecondLaw m2 a Fnet2
of sort `Prop` but is expected to have type
  Compat.PHYSlib.SI.Mass
of sort `Type` in the application
  Compat.PHYSlib.SI.newton_second_law mi2_law
/private/var/folders/vj/48782l41209gm2tv8w9s9gq40000gn/T/pipeline_proof_p...
```
```text
unsolved goals
case left
m1 m2 : Mass
T Fnet1 Fnet2 : Force
g a : Acceleration
h_net_force_mi1 : Fnet1.val = T.val
h_newton2_mi1 : Fnet1.val = m1.val * a.val
h_net_force_mi2 : Fnet2.val = m2.val * g.val - T.val
h_newton2_mi2 : Fnet2.val = m2.val * a.val
mi1_law : Dynamics.NewtonLaw.NewtonSecondLaw m1 a Fnet1
mi2_law : Dynamics.NewtonLaw.NewtonSecondLaw m2 a Fnet2
h_m1_pos : 0 < m1.val
h_m2_pos : 0 < m2.val
h_glider_nsl : T = m1 * a
h_weight_nsl : m2 * g - T = m2 * a
hden_m1_val___m2_val : m1.val + m2.val ≠ 0
h_glider_nsl_val : T.val = m1.val * a.val
h_weight_nsl_val : m2.val * g.val - T.val = m2.val * a.val
h_sum_eq : m2.val * g.val = (m1.val + m2.val) * a.val
⊢ a.val = m2.val * g.val / (m1.val + m2.val)

case right
m1 m2 : Mass
T Fnet1 Fnet2 : Force
g a : Acceleration
h_net_force_mi1 :...
```
</details>

### 3.5 LLM call 5: node `node_6_11`, depth 6

#### 传给 LLM 的结构化信息

| 字段 | 值 |
| --- | --- |
| llm_call_index | 5 |
| node_id | node_6_11 |
| depth | 6 |
| prompt_chars | 5167 |
| failed_action_count | 2 |
| local_fact_count | 15 |
| remaining_obligation_count | 1 |
| allowed_decl_count | 9 |
| omitted_context | full_retrieval_context, full_problem_ir, full_structured_mechlib_context, full_theorem_corpus, full_previous_proof_attempts |

Target excerpt:
```lean
a.val = (m2.val * g.val) / (m1.val + m2.val) ∧
  T.val = (m1.val * m2.val * g.val) / (m1.val + m2.val)
```
Proof prefix excerpt:
```lean
have h_glider_nsl : T = m1 * a := by
  exact MechLib.Compat.PHYSlib.SI.newton_second_law mi1_law
have h_weight_nsl : m2 * g - T = m2 * a := by
  exact MechLib.Compat.PHYSlib.SI.newton_second_law mi2_law
have hden_m1_val___m2_val : m1.val + m2.val ≠ 0 := by
  nlinarith [h_m1_pos, h_m2_pos]
constructor
have h_glider_nsl_val : T.val = m1.val * a.val := by
  simpa using h_glider_nsl
have h_weight_nsl_val : m2.val * g.val - T.val = m2.val * a.val := by
  simpa using h_weight_nsl
have h_sum_eq : m2.val * g.val = (m1.val + m2.val) * a.val := by
  nlinarith [h_glider_nsl_val, h_weight_nsl_val]
```
Local facts:
```text
h_net_force_mi1
h_newton2_mi1
h_net_force_mi2
h_newton2_mi2
mi1_law
mi2_law
h_glider_nsl
h_weight_nsl
h_mi3
h_m1_pos
h_m2_pos
hden_m1_val___m2_val
h_glider_nsl_val
h_weight_nsl_val
h_sum_eq
```
Remaining obligations:
| obligation_id | kind | must_use | produced_fact_name | replay_status | formal_claim |
| --- | --- | --- | --- | --- | --- |
| sk_mi3 | constraint_to_equation | MechLib.Kinematics.Verified.Kinematics.linear_constraint_velocity | h_mi3 | pending | a1 = a2 ∧ T1 = T2 |

Allowed verified declarations:
```text
MechLib.Compat.PHYSlib.SI.newton_second_law
MechLib.Analytical.LagrangeEquation.eulerLagrange_iff_newton_course_form
MechLib.Dynamics.NewtonLaw.newtonSecondLaw_course_form
MechLib.Examples.FinalTheoremDemos.newtonSecondLaw_byDefinition
MechLib.Dynamics.NewtonLaw.newton_second_law_verified
MechLib.Dynamics.SystemDynamics.centerOfMassBalance_eq
MechLib.Kinematics.Verified.Kinematics.linear_constraint_velocity
MechLib.Examples.FinalTheoremDemos.eulerLagrangeNewtonBridge_byResidualAlgebra
MechLib.Examples.FinalTheoremDemos.uniformAccelerationDisplacement_byCalculation
```
<details><summary>Prompt excerpt retained in artifact</summary>

````text
You are a Lean proof strategy controller.

Your task is to propose the next proof action, not a complete proof.

You may use only:
- listed local facts,
- listed proof obligations,
- listed verified declarations,
- listed algebra strategy cards,
- standard tactics: simp, simp_all, rw, have, exact, apply, constructor, field_simp, ring_nf, linarith, nlinarith.

Do not:
- introduce new assumptions,
- modify the theorem statement,
- use sorry/admit/axiom,
- use declarations outside whitelist,
- use schema/problem metadata as proof facts.

Available strategy cards:
- derive_law_equation
- derive_model_equation
- prove_side_condition
- split_conjunction
- algebra_solve
- rewrite_forward
- rewrite_backward
- simp_normalize
- quantity_value_projection
- introduce_intermediate_have
- close_goal

Return JSON only:

{"proposals":[{"strategy":"derive_model_equation","tactic_block":"have hT : T.val = m1.val * a.val := by\n  linarith [hFnet1, h_mi1]","uses_facts":["hFnet1","h_mi1"],"uses_decls":[],"expected_effect":"derive a local equation from checked facts","priority":0.9}]}

Compact proof state:

```json
{
  "target": "a.val = (m2.val * g.val) / (m1.val + m2.val) ∧\n  T.val = (m1.val * m2.val * g.val) / (m1.val + m2.val)",
  "proof_prefix_summary": "have h_glider_nsl : T = m1 * a := by\n  exact MechLib.Compat.PHYSlib.SI.newton_second_law mi1_law\nhave h_weight_nsl : m2 * g - T = m2 * a := by\n  exact MechLib.Compat.PHYSlib.SI.newton_second_law mi2_law\nhave hden_m1_val___m2_val : m1.val + m2.val ≠ 0 := by\n  nlinarith [h_m1_pos, h_m2_pos]\nconstructor\nhave h_glider_nsl_val : T.val...
````
</details>

#### LLM 输出动作（parsed proposals）

| action_id | strategy | priority | uses_facts | uses_decls | expected_effect |
| --- | --- | --- | --- | --- | --- |
| llm_5_1 | algebra_solve | 0.95 | hden_m1_val___m2_val, h_sum_eq |  | solve the first conjunct by clearing the denominator in the acceleration formula and using the derived sum equation |
| llm_5_2 | introduce_intermediate_have | 0.9 | hden_m1_val___m2_val, h_sum_eq |  | derive the acceleration formula as a reusable local fact for the remaining tension goal |

Action `llm_5_1` tactic:
```lean
field_simp [hden_m1_val___m2_val]
 nlinarith [h_sum_eq]
```
Action `llm_5_2` tactic:
```lean
have ha_val : a.val = (m2.val * g.val) / (m1.val + m2.val) := by
  field_simp [hden_m1_val___m2_val]
  nlinarith [h_sum_eq]
```

#### Probe/check 结果

| action_id | accepted | status | error_type | error_message | new facts | new claims | probe_checks_used | raw_probe_status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| llm_5_1 | True | progress | unsolved_goals | Application type mismatch: The argument |  |  | 11 |  |
| llm_5_2 | True | progress | unsolved_goals | Application type mismatch: The argument | ha_val | a.val = (m2.val * g.val) / (m1.val + m2.val) | 12 |  |

<details><summary>llm_5_1 Lean stderr / goals excerpt</summary>

```text
/private/var/folders/vj/48782l41209gm2tv8w9s9gq40000gn/T/pipeline_proof_probe_a0z1betd.lean:23:54: error: Application type mismatch: The argument
  mi1_law
has type
  Dynamics.NewtonLaw.NewtonSecondLaw m1 a Fnet1
of sort `Prop` but is expected to have type
  Compat.PHYSlib.SI.Mass
of sort `Type` in the application
  Compat.PHYSlib.SI.newton_second_law mi1_law
/private/var/folders/vj/48782l41209gm2tv8w9s9gq40000gn/T/pipeline_proof_probe_a0z1betd.lean:25:54: error: Application type mismatch: The argument
  mi2_law
has type
  Dynamics.NewtonLaw.NewtonSecondLaw m2 a Fnet2
of sort `Prop` but is expected to have type
  Compat.PHYSlib.SI.Mass
of sort `Type` in the application
  Compat.PHYSlib.SI.newton_second_law mi2_law
/private/var/folders/vj/48782l41209gm2tv8w9s9gq40000gn/T/pipeline_proof_p...
```
```text
unsolved goals
case left
m1 m2 : Mass
T Fnet1 Fnet2 : Force
g a : Acceleration
h_net_force_mi1 : Fnet1.val = T.val
h_newton2_mi1 : Fnet1.val = m1.val * a.val
h_net_force_mi2 : Fnet2.val = m2.val * g.val - T.val
h_newton2_mi2 : Fnet2.val = m2.val * a.val
mi1_law : Dynamics.NewtonLaw.NewtonSecondLaw m1 a Fnet1
mi2_law : Dynamics.NewtonLaw.NewtonSecondLaw m2 a Fnet2
h_m1_pos : 0 < m1.val
h_m2_pos : 0 < m2.val
h_glider_nsl : T = m1 * a
h_weight_nsl : m2 * g - T = m2 * a
hden_m1_val___m2_val : m1.val + m2.val ≠ 0
h_glider_nsl_val : T.val = m1.val * a.val
h_weight_nsl_val : m2.val * g.val - T.val = m2.val * a.val
h_sum_eq : m2.val * g.val = (m1.val + m2.val) * a.val
⊢ a.val * (m1.val + m2.val) = m2.val * g.val

case right
m1 m2 : Mass
T Fnet1 Fnet2 : Force
g a : Acceleration
h_net_force_mi1 :...
```
</details>

<details><summary>llm_5_2 Lean stderr / goals excerpt</summary>

```text
/private/var/folders/vj/48782l41209gm2tv8w9s9gq40000gn/T/pipeline_proof_probe_xumgeuap.lean:23:54: error: Application type mismatch: The argument
  mi1_law
has type
  Dynamics.NewtonLaw.NewtonSecondLaw m1 a Fnet1
of sort `Prop` but is expected to have type
  Compat.PHYSlib.SI.Mass
of sort `Type` in the application
  Compat.PHYSlib.SI.newton_second_law mi1_law
/private/var/folders/vj/48782l41209gm2tv8w9s9gq40000gn/T/pipeline_proof_probe_xumgeuap.lean:25:54: error: Application type mismatch: The argument
  mi2_law
has type
  Dynamics.NewtonLaw.NewtonSecondLaw m2 a Fnet2
of sort `Prop` but is expected to have type
  Compat.PHYSlib.SI.Mass
of sort `Type` in the application
  Compat.PHYSlib.SI.newton_second_law mi2_law
/private/var/folders/vj/48782l41209gm2tv8w9s9gq40000gn/T/pipeline_proof_p...
```
```text
unsolved goals
case left
m1 m2 : Mass
T Fnet1 Fnet2 : Force
g a : Acceleration
h_net_force_mi1 : Fnet1.val = T.val
h_newton2_mi1 : Fnet1.val = m1.val * a.val
h_net_force_mi2 : Fnet2.val = m2.val * g.val - T.val
h_newton2_mi2 : Fnet2.val = m2.val * a.val
mi1_law : Dynamics.NewtonLaw.NewtonSecondLaw m1 a Fnet1
mi2_law : Dynamics.NewtonLaw.NewtonSecondLaw m2 a Fnet2
h_m1_pos : 0 < m1.val
h_m2_pos : 0 < m2.val
h_glider_nsl : T = m1 * a
h_weight_nsl : m2 * g - T = m2 * a
hden_m1_val___m2_val : m1.val + m2.val ≠ 0
h_glider_nsl_val : T.val = m1.val * a.val
h_weight_nsl_val : m2.val * g.val - T.val = m2.val * a.val
h_sum_eq : m2.val * g.val = (m1.val + m2.val) * a.val
ha_val : a.val = m2.val * g.val / (m1.val + m2.val)
⊢ a.val = m2.val * g.val / (m1.val + m2.val)

case right
m1 m2 : Mass
T Fnet...
```
</details>

### 3.6 LLM call 6: node `node_7_12`, depth 7

#### 传给 LLM 的结构化信息

| 字段 | 值 |
| --- | --- |
| llm_call_index | 6 |
| node_id | node_7_12 |
| depth | 7 |
| prompt_chars | 5225 |
| failed_action_count | 2 |
| local_fact_count | 15 |
| remaining_obligation_count | 1 |
| allowed_decl_count | 9 |
| omitted_context | full_retrieval_context, full_problem_ir, full_structured_mechlib_context, full_theorem_corpus, full_previous_proof_attempts |

Target excerpt:
```lean
a.val = (m2.val * g.val) / (m1.val + m2.val) ∧
  T.val = (m1.val * m2.val * g.val) / (m1.val + m2.val)
```
Proof prefix excerpt:
```lean
have h_glider_nsl : T = m1 * a := by
  exact MechLib.Compat.PHYSlib.SI.newton_second_law mi1_law
have h_weight_nsl : m2 * g - T = m2 * a := by
  exact MechLib.Compat.PHYSlib.SI.newton_second_law mi2_law
have hden_m1_val___m2_val : m1.val + m2.val ≠ 0 := by
  nlinarith [h_m1_pos, h_m2_pos]
constructor
have h_glider_nsl_val : T.val = m1.val * a.val := by
  simpa using h_glider_nsl
have h_weight_nsl_val : m2.val * g.val - T.val = m2.val * a.val := by
  simpa using h_weight_nsl
have h_sum_eq : m2.val * g.val = (m1.val + m2.val) * a.val := by
  nlinarith [h_glider_nsl_val, h_weight_nsl_val]
field_simp [hden_m1_val___m2_val]
 nlinarith [h_sum_eq]
```
Local facts:
```text
h_net_force_mi1
h_newton2_mi1
h_net_force_mi2
h_newton2_mi2
mi1_law
mi2_law
h_glider_nsl
h_weight_nsl
h_mi3
h_m1_pos
h_m2_pos
hden_m1_val___m2_val
h_glider_nsl_val
h_weight_nsl_val
h_sum_eq
```
Remaining obligations:
| obligation_id | kind | must_use | produced_fact_name | replay_status | formal_claim |
| --- | --- | --- | --- | --- | --- |
| sk_mi3 | constraint_to_equation | MechLib.Kinematics.Verified.Kinematics.linear_constraint_velocity | h_mi3 | pending | a1 = a2 ∧ T1 = T2 |

Allowed verified declarations:
```text
MechLib.Compat.PHYSlib.SI.newton_second_law
MechLib.Analytical.LagrangeEquation.eulerLagrange_iff_newton_course_form
MechLib.Dynamics.NewtonLaw.newtonSecondLaw_course_form
MechLib.Examples.FinalTheoremDemos.newtonSecondLaw_byDefinition
MechLib.Dynamics.NewtonLaw.newton_second_law_verified
MechLib.Dynamics.SystemDynamics.centerOfMassBalance_eq
MechLib.Kinematics.Verified.Kinematics.linear_constraint_velocity
MechLib.Examples.FinalTheoremDemos.eulerLagrangeNewtonBridge_byResidualAlgebra
MechLib.Examples.FinalTheoremDemos.uniformAccelerationDisplacement_byCalculation
```
<details><summary>Prompt excerpt retained in artifact</summary>

````text
You are a Lean proof strategy controller.

Your task is to propose the next proof action, not a complete proof.

You may use only:
- listed local facts,
- listed proof obligations,
- listed verified declarations,
- listed algebra strategy cards,
- standard tactics: simp, simp_all, rw, have, exact, apply, constructor, field_simp, ring_nf, linarith, nlinarith.

Do not:
- introduce new assumptions,
- modify the theorem statement,
- use sorry/admit/axiom,
- use declarations outside whitelist,
- use schema/problem metadata as proof facts.

Available strategy cards:
- derive_law_equation
- derive_model_equation
- prove_side_condition
- split_conjunction
- algebra_solve
- rewrite_forward
- rewrite_backward
- simp_normalize
- quantity_value_projection
- introduce_intermediate_have
- close_goal

Return JSON only:

{"proposals":[{"strategy":"derive_model_equation","tactic_block":"have hT : T.val = m1.val * a.val := by\n  linarith [hFnet1, h_mi1]","uses_facts":["hFnet1","h_mi1"],"uses_decls":[],"expected_effect":"derive a local equation from checked facts","priority":0.9}]}

Compact proof state:

```json
{
  "target": "a.val = (m2.val * g.val) / (m1.val + m2.val) ∧\n  T.val = (m1.val * m2.val * g.val) / (m1.val + m2.val)",
  "proof_prefix_summary": "have h_glider_nsl : T = m1 * a := by\n  exact MechLib.Compat.PHYSlib.SI.newton_second_law mi1_law\nhave h_weight_nsl : m2 * g - T = m2 * a := by\n  exact MechLib.Compat.PHYSlib.SI.newton_second_law mi2_law\nhave hden_m1_val___m2_val : m1.val + m2.val ≠ 0 := by\n  nlinarith [h_m1_pos, h_m2_pos]\nconstructor\nhave h_glider_nsl_val : T.val...
````
</details>

#### LLM 输出动作（parsed proposals）

| action_id | strategy | priority | uses_facts | uses_decls | expected_effect |
| --- | --- | --- | --- | --- | --- |
| llm_6_1 | close_goal | 0.96 | hden_m1_val___m2_val, h_glider_nsl_val, h_sum_eq |  | solve the second conjunct by deriving the explicit formula for T.val from T.val = m1.val * a.val and the previously derived sum equation |

Action `llm_6_1` tactic:
```lean
have h_T_eq : T.val = (m1.val * m2.val * g.val) / (m1.val + m2.val) := by
  field_simp [hden_m1_val___m2_val]
  nlinarith [h_glider_nsl_val, h_sum_eq]
exact h_T_eq
```

#### Probe/check 结果

| action_id | accepted | status | error_type | error_message | new facts | new claims | probe_checks_used | raw_probe_status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| llm_6_1 | True | progress | unsolved_goals | Application type mismatch: The argument | h_T_eq | T.val = (m1.val * m2.val * g.val) / (m1.val + m2.val) | 13 |  |

<details><summary>llm_6_1 Lean stderr / goals excerpt</summary>

```text
/private/var/folders/vj/48782l41209gm2tv8w9s9gq40000gn/T/pipeline_proof_probe_35urdank.lean:23:54: error: Application type mismatch: The argument
  mi1_law
has type
  Dynamics.NewtonLaw.NewtonSecondLaw m1 a Fnet1
of sort `Prop` but is expected to have type
  Compat.PHYSlib.SI.Mass
of sort `Type` in the application
  Compat.PHYSlib.SI.newton_second_law mi1_law
/private/var/folders/vj/48782l41209gm2tv8w9s9gq40000gn/T/pipeline_proof_probe_35urdank.lean:25:54: error: Application type mismatch: The argument
  mi2_law
has type
  Dynamics.NewtonLaw.NewtonSecondLaw m2 a Fnet2
of sort `Prop` but is expected to have type
  Compat.PHYSlib.SI.Mass
of sort `Type` in the application
  Compat.PHYSlib.SI.newton_second_law mi2_law
/private/var/folders/vj/48782l41209gm2tv8w9s9gq40000gn/T/pipeline_proof_p...
```
```text
unsolved goals
case left
m1 m2 : Mass
T Fnet1 Fnet2 : Force
g a : Acceleration
h_net_force_mi1 : Fnet1.val = T.val
h_newton2_mi1 : Fnet1.val = m1.val * a.val
h_net_force_mi2 : Fnet2.val = m2.val * g.val - T.val
h_newton2_mi2 : Fnet2.val = m2.val * a.val
mi1_law : Dynamics.NewtonLaw.NewtonSecondLaw m1 a Fnet1
mi2_law : Dynamics.NewtonLaw.NewtonSecondLaw m2 a Fnet2
h_m1_pos : 0 < m1.val
h_m2_pos : 0 < m2.val
h_glider_nsl : T = m1 * a
h_weight_nsl : m2 * g - T = m2 * a
hden_m1_val___m2_val : m1.val + m2.val ≠ 0
h_glider_nsl_val : T.val = m1.val * a.val
h_weight_nsl_val : m2.val * g.val - T.val = m2.val * a.val
h_sum_eq : m2.val * g.val = (m1.val + m2.val) * a.val
⊢ a.val * (m1.val + m2.val) = m2.val * g.val

case right
m1 m2 : Mass
T Fnet1 Fnet2 : Force
g a : Acceleration
h_net_force_mi1 :...
```
</details>

### 3.7 LLM call 7: node `node_8_14`, depth 8

#### 传给 LLM 的结构化信息

| 字段 | 值 |
| --- | --- |
| llm_call_index | 7 |
| node_id | node_8_14 |
| depth | 8 |
| prompt_chars | 5407 |
| failed_action_count | 2 |
| local_fact_count | 16 |
| remaining_obligation_count | 1 |
| allowed_decl_count | 9 |
| omitted_context | full_retrieval_context, full_problem_ir, full_structured_mechlib_context, full_theorem_corpus, full_previous_proof_attempts |

Target excerpt:
```lean
a.val = (m2.val * g.val) / (m1.val + m2.val) ∧
  T.val = (m1.val * m2.val * g.val) / (m1.val + m2.val)
```
Proof prefix excerpt:
```lean
have h_glider_nsl : T = m1 * a := by
  exact MechLib.Compat.PHYSlib.SI.newton_second_law mi1_law
have h_weight_nsl : m2 * g - T = m2 * a := by
  exact MechLib.Compat.PHYSlib.SI.newton_second_law mi2_law
have hden_m1_val___m2_val : m1.val + m2.val ≠ 0 := by
  nlinarith [h_m1_pos, h_m2_pos]
constructor
have h_glider_nsl_val : T.val = m1.val * a.val := by
  simpa using h_glider_nsl
have h_weight_nsl_val : m2.val * g.val - T.val = m2.val * a.val := by
  simpa using h_weight_nsl
have h_sum_eq : m2.val * g.val = (m1.val + m2.val) * a.val := by
  nlinarith [h_glider_nsl_val, h_weight_nsl_val]
field_simp [hden_m1_val___m2_val]
 nlinarith [h_sum_eq]
have h_T_eq : T.val = (m1.val * m2.val * g.val) / (m1.val + m2.val) := by
  field_simp [hden_m1_val___m2_val]
  nlinarith [h_glider_nsl_val, h_sum_e...
```
Local facts:
```text
h_net_force_mi1
h_newton2_mi1
h_net_force_mi2
h_newton2_mi2
mi1_law
mi2_law
h_glider_nsl
h_weight_nsl
h_mi3
h_m1_pos
h_m2_pos
hden_m1_val___m2_val
h_glider_nsl_val
h_weight_nsl_val
h_sum_eq
h_T_eq
```
Remaining obligations:
| obligation_id | kind | must_use | produced_fact_name | replay_status | formal_claim |
| --- | --- | --- | --- | --- | --- |
| sk_mi3 | constraint_to_equation | MechLib.Kinematics.Verified.Kinematics.linear_constraint_velocity | h_mi3 | pending | a1 = a2 ∧ T1 = T2 |

Allowed verified declarations:
```text
MechLib.Compat.PHYSlib.SI.newton_second_law
MechLib.Analytical.LagrangeEquation.eulerLagrange_iff_newton_course_form
MechLib.Dynamics.NewtonLaw.newtonSecondLaw_course_form
MechLib.Examples.FinalTheoremDemos.newtonSecondLaw_byDefinition
MechLib.Dynamics.NewtonLaw.newton_second_law_verified
MechLib.Dynamics.SystemDynamics.centerOfMassBalance_eq
MechLib.Kinematics.Verified.Kinematics.linear_constraint_velocity
MechLib.Examples.FinalTheoremDemos.eulerLagrangeNewtonBridge_byResidualAlgebra
MechLib.Examples.FinalTheoremDemos.uniformAccelerationDisplacement_byCalculation
```
<details><summary>Prompt excerpt retained in artifact</summary>

````text
You are a Lean proof strategy controller.

Your task is to propose the next proof action, not a complete proof.

You may use only:
- listed local facts,
- listed proof obligations,
- listed verified declarations,
- listed algebra strategy cards,
- standard tactics: simp, simp_all, rw, have, exact, apply, constructor, field_simp, ring_nf, linarith, nlinarith.

Do not:
- introduce new assumptions,
- modify the theorem statement,
- use sorry/admit/axiom,
- use declarations outside whitelist,
- use schema/problem metadata as proof facts.

Available strategy cards:
- derive_law_equation
- derive_model_equation
- prove_side_condition
- split_conjunction
- algebra_solve
- rewrite_forward
- rewrite_backward
- simp_normalize
- quantity_value_projection
- introduce_intermediate_have
- close_goal

Return JSON only:

{"proposals":[{"strategy":"derive_model_equation","tactic_block":"have hT : T.val = m1.val * a.val := by\n  linarith [hFnet1, h_mi1]","uses_facts":["hFnet1","h_mi1"],"uses_decls":[],"expected_effect":"derive a local equation from checked facts","priority":0.9}]}

Compact proof state:

```json
{
  "target": "a.val = (m2.val * g.val) / (m1.val + m2.val) ∧\n  T.val = (m1.val * m2.val * g.val) / (m1.val + m2.val)",
  "proof_prefix_summary": "have h_glider_nsl : T = m1 * a := by\n  exact MechLib.Compat.PHYSlib.SI.newton_second_law mi1_law\nhave h_weight_nsl : m2 * g - T = m2 * a := by\n  exact MechLib.Compat.PHYSlib.SI.newton_second_law mi2_law\nhave hden_m1_val___m2_val : m1.val + m2.val ≠ 0 := by\n  nlinarith [h_m1_pos, h_m2_pos]\nconstructor\nhave h_glider_nsl_val : T.val...
````
</details>

#### LLM 输出动作（parsed proposals）

| action_id | strategy | priority | uses_facts | uses_decls | expected_effect |
| --- | --- | --- | --- | --- | --- |
| llm_7_1 | close_goal | 0.98 | hden_m1_val___m2_val, h_sum_eq, h_T_eq |  | close the conjunctive target by supplying the acceleration formula and the already-proved tension formula together |
| llm_7_2 | split_conjunction | 0.95 | hden_m1_val___m2_val, h_sum_eq, h_T_eq |  | split the conjunction and solve each component directly from existing facts |

Action `llm_7_1` tactic:
```lean
exact ⟨by
  field_simp [hden_m1_val___m2_val]
  nlinarith [h_sum_eq], h_T_eq⟩
```
Action `llm_7_2` tactic:
```lean
constructor
· field_simp [hden_m1_val___m2_val]
  nlinarith [h_sum_eq]
· exact h_T_eq
```

#### Probe/check 结果

| action_id | accepted | status | error_type | error_message | new facts | new claims | probe_checks_used | raw_probe_status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| llm_7_1 | False | invalid | no_meaningful_progress | Lean accepted the prefix, but it added no fact, covered no obligation, and left goals unchanged |  |  | 14 | progress |
| llm_7_2 | False | invalid | no_meaningful_progress | Lean accepted the prefix, but it added no fact, covered no obligation, and left goals unchanged |  |  | 15 | progress |

<details><summary>llm_7_1 Lean stderr / goals excerpt</summary>

```text
Lean accepted the prefix, but it added no fact, covered no obligation, and left goals unchanged
```
```text
unsolved goals
case left
m1 m2 : Mass
T Fnet1 Fnet2 : Force
g a : Acceleration
h_net_force_mi1 : Fnet1.val = T.val
h_newton2_mi1 : Fnet1.val = m1.val * a.val
h_net_force_mi2 : Fnet2.val = m2.val * g.val - T.val
h_newton2_mi2 : Fnet2.val = m2.val * a.val
mi1_law : Dynamics.NewtonLaw.NewtonSecondLaw m1 a Fnet1
mi2_law : Dynamics.NewtonLaw.NewtonSecondLaw m2 a Fnet2
h_m1_pos : 0 < m1.val
h_m2_pos : 0 < m2.val
h_glider_nsl : T = m1 * a
h_weight_nsl : m2 * g - T = m2 * a
hden_m1_val___m2_val : m1.val + m2.val ≠ 0
h_glider_nsl_val : T.val = m1.val * a.val
h_weight_nsl_val : m2.val * g.val - T.val = m2.val * a.val
h_sum_eq : m2.val * g.val = (m1.val + m2.val) * a.val
⊢ a.val * (m1.val + m2.val) = m2.val * g.val

case right
m1 m2 : Mass
T Fnet1 Fnet2 : Force
g a : Acceleration
h_net_force_mi1 :...
```
</details>

<details><summary>llm_7_2 Lean stderr / goals excerpt</summary>

```text
Lean accepted the prefix, but it added no fact, covered no obligation, and left goals unchanged
```
```text
unsolved goals
case left
m1 m2 : Mass
T Fnet1 Fnet2 : Force
g a : Acceleration
h_net_force_mi1 : Fnet1.val = T.val
h_newton2_mi1 : Fnet1.val = m1.val * a.val
h_net_force_mi2 : Fnet2.val = m2.val * g.val - T.val
h_newton2_mi2 : Fnet2.val = m2.val * a.val
mi1_law : Dynamics.NewtonLaw.NewtonSecondLaw m1 a Fnet1
mi2_law : Dynamics.NewtonLaw.NewtonSecondLaw m2 a Fnet2
h_m1_pos : 0 < m1.val
h_m2_pos : 0 < m2.val
h_glider_nsl : T = m1 * a
h_weight_nsl : m2 * g - T = m2 * a
hden_m1_val___m2_val : m1.val + m2.val ≠ 0
h_glider_nsl_val : T.val = m1.val * a.val
h_weight_nsl_val : m2.val * g.val - T.val = m2.val * a.val
h_sum_eq : m2.val * g.val = (m1.val + m2.val) * a.val
⊢ a.val * (m1.val + m2.val) = m2.val * g.val

case right
m1 m2 : Mass
T Fnet1 Fnet2 : Force
g a : Acceleration
h_net_force_mi1 :...
```
</details>

### 3.8 LLM call 8: node `node_7_13`, depth 7

#### 传给 LLM 的结构化信息

| 字段 | 值 |
| --- | --- |
| llm_call_index | 8 |
| node_id | node_7_13 |
| depth | 7 |
| prompt_chars | 6110 |
| failed_action_count | 4 |
| local_fact_count | 16 |
| remaining_obligation_count | 1 |
| allowed_decl_count | 9 |
| omitted_context | full_retrieval_context, full_problem_ir, full_structured_mechlib_context, full_theorem_corpus, full_previous_proof_attempts |

Target excerpt:
```lean
a.val = (m2.val * g.val) / (m1.val + m2.val) ∧
  T.val = (m1.val * m2.val * g.val) / (m1.val + m2.val)
```
Proof prefix excerpt:
```lean
have h_glider_nsl : T = m1 * a := by
  exact MechLib.Compat.PHYSlib.SI.newton_second_law mi1_law
have h_weight_nsl : m2 * g - T = m2 * a := by
  exact MechLib.Compat.PHYSlib.SI.newton_second_law mi2_law
have hden_m1_val___m2_val : m1.val + m2.val ≠ 0 := by
  nlinarith [h_m1_pos, h_m2_pos]
constructor
have h_glider_nsl_val : T.val = m1.val * a.val := by
  simpa using h_glider_nsl
have h_weight_nsl_val : m2.val * g.val - T.val = m2.val * a.val := by
  simpa using h_weight_nsl
have h_sum_eq : m2.val * g.val = (m1.val + m2.val) * a.val := by
  nlinarith [h_glider_nsl_val, h_weight_nsl_val]
have ha_val : a.val = (m2.val * g.val) / (m1.val + m2.val) := by
  field_simp [hden_m1_val___m2_val]
  nlinarith [h_sum_eq]
```
Local facts:
```text
h_net_force_mi1
h_newton2_mi1
h_net_force_mi2
h_newton2_mi2
mi1_law
mi2_law
h_glider_nsl
h_weight_nsl
h_mi3
h_m1_pos
h_m2_pos
hden_m1_val___m2_val
h_glider_nsl_val
h_weight_nsl_val
h_sum_eq
ha_val
```
Remaining obligations:
| obligation_id | kind | must_use | produced_fact_name | replay_status | formal_claim |
| --- | --- | --- | --- | --- | --- |
| sk_mi3 | constraint_to_equation | MechLib.Kinematics.Verified.Kinematics.linear_constraint_velocity | h_mi3 | pending | a1 = a2 ∧ T1 = T2 |

Allowed verified declarations:
```text
MechLib.Compat.PHYSlib.SI.newton_second_law
MechLib.Analytical.LagrangeEquation.eulerLagrange_iff_newton_course_form
MechLib.Dynamics.NewtonLaw.newtonSecondLaw_course_form
MechLib.Examples.FinalTheoremDemos.newtonSecondLaw_byDefinition
MechLib.Dynamics.NewtonLaw.newton_second_law_verified
MechLib.Dynamics.SystemDynamics.centerOfMassBalance_eq
MechLib.Kinematics.Verified.Kinematics.linear_constraint_velocity
MechLib.Examples.FinalTheoremDemos.eulerLagrangeNewtonBridge_byResidualAlgebra
MechLib.Examples.FinalTheoremDemos.uniformAccelerationDisplacement_byCalculation
```
<details><summary>Prompt excerpt retained in artifact</summary>

````text
You are a Lean proof strategy controller.

Your task is to propose the next proof action, not a complete proof.

You may use only:
- listed local facts,
- listed proof obligations,
- listed verified declarations,
- listed algebra strategy cards,
- standard tactics: simp, simp_all, rw, have, exact, apply, constructor, field_simp, ring_nf, linarith, nlinarith.

Do not:
- introduce new assumptions,
- modify the theorem statement,
- use sorry/admit/axiom,
- use declarations outside whitelist,
- use schema/problem metadata as proof facts.

Available strategy cards:
- derive_law_equation
- derive_model_equation
- prove_side_condition
- split_conjunction
- algebra_solve
- rewrite_forward
- rewrite_backward
- simp_normalize
- quantity_value_projection
- introduce_intermediate_have
- close_goal

Return JSON only:

{"proposals":[{"strategy":"derive_model_equation","tactic_block":"have hT : T.val = m1.val * a.val := by\n  linarith [hFnet1, h_mi1]","uses_facts":["hFnet1","h_mi1"],"uses_decls":[],"expected_effect":"derive a local equation from checked facts","priority":0.9}]}

Compact proof state:

```json
{
  "target": "a.val = (m2.val * g.val) / (m1.val + m2.val) ∧\n  T.val = (m1.val * m2.val * g.val) / (m1.val + m2.val)",
  "proof_prefix_summary": "have h_glider_nsl : T = m1 * a := by\n  exact MechLib.Compat.PHYSlib.SI.newton_second_law mi1_law\nhave h_weight_nsl : m2 * g - T = m2 * a := by\n  exact MechLib.Compat.PHYSlib.SI.newton_second_law mi2_law\nhave hden_m1_val___m2_val : m1.val + m2.val ≠ 0 := by\n  nlinarith [h_m1_pos, h_m2_pos]\nconstructor\nhave h_glider_nsl_val : T.val...
````
</details>

#### LLM 输出动作（parsed proposals）

| action_id | strategy | priority | uses_facts | uses_decls | expected_effect |
| --- | --- | --- | --- | --- | --- |
| llm_8_1 | introduce_intermediate_have | 0.97 | h_glider_nsl_val, ha_val, hden_m1_val___m2_val |  | derive the formula for T.val from T.val = m1.val * a.val and the solved expression for a.val |
| llm_8_2 | close_goal | 0.92 | ha_val |  | close the current first conjunct goal with the already derived acceleration formula |

Action `llm_8_1` tactic:
```lean
have hT_val : T.val = (m1.val * m2.val * g.val) / (m1.val + m2.val) := by
  rw [h_glider_nsl_val, ha_val]
  field_simp [hden_m1_val___m2_val]
  ring_nf
```
Action `llm_8_2` tactic:
```lean
exact ha_val
```

#### Probe/check 结果

| action_id | accepted | status | error_type | error_message | new facts | new claims | probe_checks_used | raw_probe_status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| llm_8_1 | True | progress | unsolved_goals | Application type mismatch: The argument | hT_val | T.val = (m1.val * m2.val * g.val) / (m1.val + m2.val) | 16 |  |
| llm_8_2 | True | progress | unsolved_goals | Application type mismatch: The argument |  |  | 17 |  |

<details><summary>llm_8_1 Lean stderr / goals excerpt</summary>

```text
/private/var/folders/vj/48782l41209gm2tv8w9s9gq40000gn/T/pipeline_proof_probe_wkdvh737.lean:23:54: error: Application type mismatch: The argument
  mi1_law
has type
  Dynamics.NewtonLaw.NewtonSecondLaw m1 a Fnet1
of sort `Prop` but is expected to have type
  Compat.PHYSlib.SI.Mass
of sort `Type` in the application
  Compat.PHYSlib.SI.newton_second_law mi1_law
/private/var/folders/vj/48782l41209gm2tv8w9s9gq40000gn/T/pipeline_proof_probe_wkdvh737.lean:25:54: error: Application type mismatch: The argument
  mi2_law
has type
  Dynamics.NewtonLaw.NewtonSecondLaw m2 a Fnet2
of sort `Prop` but is expected to have type
  Compat.PHYSlib.SI.Mass
of sort `Type` in the application
  Compat.PHYSlib.SI.newton_second_law mi2_law
/private/var/folders/vj/48782l41209gm2tv8w9s9gq40000gn/T/pipeline_proof_p...
```
```text
unsolved goals
case left
m1 m2 : Mass
T Fnet1 Fnet2 : Force
g a : Acceleration
h_net_force_mi1 : Fnet1.val = T.val
h_newton2_mi1 : Fnet1.val = m1.val * a.val
h_net_force_mi2 : Fnet2.val = m2.val * g.val - T.val
h_newton2_mi2 : Fnet2.val = m2.val * a.val
mi1_law : Dynamics.NewtonLaw.NewtonSecondLaw m1 a Fnet1
mi2_law : Dynamics.NewtonLaw.NewtonSecondLaw m2 a Fnet2
h_m1_pos : 0 < m1.val
h_m2_pos : 0 < m2.val
h_glider_nsl : T = m1 * a
h_weight_nsl : m2 * g - T = m2 * a
hden_m1_val___m2_val : m1.val + m2.val ≠ 0
h_glider_nsl_val : T.val = m1.val * a.val
h_weight_nsl_val : m2.val * g.val - T.val = m2.val * a.val
h_sum_eq : m2.val * g.val = (m1.val + m2.val) * a.val
ha_val : a.val = m2.val * g.val / (m1.val + m2.val)
hT_val : T.val = m1.val * m2.val * g.val / (m1.val + m2.val)
⊢ a.val = m2.va...
```
</details>

<details><summary>llm_8_2 Lean stderr / goals excerpt</summary>

```text
/private/var/folders/vj/48782l41209gm2tv8w9s9gq40000gn/T/pipeline_proof_probe_wafeog0w.lean:23:54: error: Application type mismatch: The argument
  mi1_law
has type
  Dynamics.NewtonLaw.NewtonSecondLaw m1 a Fnet1
of sort `Prop` but is expected to have type
  Compat.PHYSlib.SI.Mass
of sort `Type` in the application
  Compat.PHYSlib.SI.newton_second_law mi1_law
/private/var/folders/vj/48782l41209gm2tv8w9s9gq40000gn/T/pipeline_proof_probe_wafeog0w.lean:25:54: error: Application type mismatch: The argument
  mi2_law
has type
  Dynamics.NewtonLaw.NewtonSecondLaw m2 a Fnet2
of sort `Prop` but is expected to have type
  Compat.PHYSlib.SI.Mass
of sort `Type` in the application
  Compat.PHYSlib.SI.newton_second_law mi2_law
/private/var/folders/vj/48782l41209gm2tv8w9s9gq40000gn/T/pipeline_proof_p...
```
```text
unsolved goals
case right
m1 m2 : Mass
T Fnet1 Fnet2 : Force
g a : Acceleration
h_net_force_mi1 : Fnet1.val = T.val
h_newton2_mi1 : Fnet1.val = m1.val * a.val
h_net_force_mi2 : Fnet2.val = m2.val * g.val - T.val
h_newton2_mi2 : Fnet2.val = m2.val * a.val
mi1_law : Dynamics.NewtonLaw.NewtonSecondLaw m1 a Fnet1
mi2_law : Dynamics.NewtonLaw.NewtonSecondLaw m2 a Fnet2
h_m1_pos : 0 < m1.val
h_m2_pos : 0 < m2.val
h_glider_nsl : T = m1 * a
h_weight_nsl : m2 * g - T = m2 * a
hden_m1_val___m2_val : m1.val + m2.val ≠ 0
⊢ T.val = m1.val * m2.val * g.val / (m1.val + m2.val)
```
</details>

### 3.9 LLM call 9: node `node_10_15`, depth 8

#### 传给 LLM 的结构化信息

| 字段 | 值 |
| --- | --- |
| llm_call_index | 9 |
| node_id | node_10_15 |
| depth | 8 |
| prompt_chars | 6280 |
| failed_action_count | 4 |
| local_fact_count | 17 |
| remaining_obligation_count | 1 |
| allowed_decl_count | 9 |
| omitted_context | full_retrieval_context, full_problem_ir, full_structured_mechlib_context, full_theorem_corpus, full_previous_proof_attempts |

Target excerpt:
```lean
a.val = (m2.val * g.val) / (m1.val + m2.val) ∧
  T.val = (m1.val * m2.val * g.val) / (m1.val + m2.val)
```
Proof prefix excerpt:
```lean
have h_glider_nsl : T = m1 * a := by
  exact MechLib.Compat.PHYSlib.SI.newton_second_law mi1_law
have h_weight_nsl : m2 * g - T = m2 * a := by
  exact MechLib.Compat.PHYSlib.SI.newton_second_law mi2_law
have hden_m1_val___m2_val : m1.val + m2.val ≠ 0 := by
  nlinarith [h_m1_pos, h_m2_pos]
constructor
have h_glider_nsl_val : T.val = m1.val * a.val := by
  simpa using h_glider_nsl
have h_weight_nsl_val : m2.val * g.val - T.val = m2.val * a.val := by
  simpa using h_weight_nsl
have h_sum_eq : m2.val * g.val = (m1.val + m2.val) * a.val := by
  nlinarith [h_glider_nsl_val, h_weight_nsl_val]
have ha_val : a.val = (m2.val * g.val) / (m1.val + m2.val) := by
  field_simp [hden_m1_val___m2_val]
  nlinarith [h_sum_eq]
have hT_val : T.val = (m1.val * m2.val * g.val) / (m1.val + m2.val) := by
  rw [...
```
Local facts:
```text
h_net_force_mi1
h_newton2_mi1
h_net_force_mi2
h_newton2_mi2
mi1_law
mi2_law
h_glider_nsl
h_weight_nsl
h_mi3
h_m1_pos
h_m2_pos
hden_m1_val___m2_val
h_glider_nsl_val
h_weight_nsl_val
h_sum_eq
ha_val
hT_val
```
Remaining obligations:
| obligation_id | kind | must_use | produced_fact_name | replay_status | formal_claim |
| --- | --- | --- | --- | --- | --- |
| sk_mi3 | constraint_to_equation | MechLib.Kinematics.Verified.Kinematics.linear_constraint_velocity | h_mi3 | pending | a1 = a2 ∧ T1 = T2 |

Allowed verified declarations:
```text
MechLib.Compat.PHYSlib.SI.newton_second_law
MechLib.Analytical.LagrangeEquation.eulerLagrange_iff_newton_course_form
MechLib.Dynamics.NewtonLaw.newtonSecondLaw_course_form
MechLib.Examples.FinalTheoremDemos.newtonSecondLaw_byDefinition
MechLib.Dynamics.NewtonLaw.newton_second_law_verified
MechLib.Dynamics.SystemDynamics.centerOfMassBalance_eq
MechLib.Kinematics.Verified.Kinematics.linear_constraint_velocity
MechLib.Examples.FinalTheoremDemos.eulerLagrangeNewtonBridge_byResidualAlgebra
MechLib.Examples.FinalTheoremDemos.uniformAccelerationDisplacement_byCalculation
```
<details><summary>Prompt excerpt retained in artifact</summary>

````text
You are a Lean proof strategy controller.

Your task is to propose the next proof action, not a complete proof.

You may use only:
- listed local facts,
- listed proof obligations,
- listed verified declarations,
- listed algebra strategy cards,
- standard tactics: simp, simp_all, rw, have, exact, apply, constructor, field_simp, ring_nf, linarith, nlinarith.

Do not:
- introduce new assumptions,
- modify the theorem statement,
- use sorry/admit/axiom,
- use declarations outside whitelist,
- use schema/problem metadata as proof facts.

Available strategy cards:
- derive_law_equation
- derive_model_equation
- prove_side_condition
- split_conjunction
- algebra_solve
- rewrite_forward
- rewrite_backward
- simp_normalize
- quantity_value_projection
- introduce_intermediate_have
- close_goal

Return JSON only:

{"proposals":[{"strategy":"derive_model_equation","tactic_block":"have hT : T.val = m1.val * a.val := by\n  linarith [hFnet1, h_mi1]","uses_facts":["hFnet1","h_mi1"],"uses_decls":[],"expected_effect":"derive a local equation from checked facts","priority":0.9}]}

Compact proof state:

```json
{
  "target": "a.val = (m2.val * g.val) / (m1.val + m2.val) ∧\n  T.val = (m1.val * m2.val * g.val) / (m1.val + m2.val)",
  "proof_prefix_summary": "have h_glider_nsl : T = m1 * a := by\n  exact MechLib.Compat.PHYSlib.SI.newton_second_law mi1_law\nhave h_weight_nsl : m2 * g - T = m2 * a := by\n  exact MechLib.Compat.PHYSlib.SI.newton_second_law mi2_law\nhave hden_m1_val___m2_val : m1.val + m2.val ≠ 0 := by\n  nlinarith [h_m1_pos, h_m2_pos]\nconstructor\nhave h_glider_nsl_val : T.val...
````
</details>

#### LLM 输出动作（parsed proposals）

| action_id | strategy | priority | uses_facts | uses_decls | expected_effect |
| --- | --- | --- | --- | --- | --- |
| llm_9_1 | close_goal | 0.99 | ha_val, hT_val |  | close the conjunctive target using the two already derived component equalities |

Action `llm_9_1` tactic:
```lean
exact ⟨ha_val, hT_val⟩
```

#### Probe/check 结果

| action_id | accepted | status | error_type | error_message | new facts | new claims | probe_checks_used | raw_probe_status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| llm_9_1 | True | progress | unsolved_goals | Application type mismatch: The argument |  |  | 18 |  |

<details><summary>llm_9_1 Lean stderr / goals excerpt</summary>

```text
/private/var/folders/vj/48782l41209gm2tv8w9s9gq40000gn/T/pipeline_proof_probe_7mo4hleb.lean:23:54: error: Application type mismatch: The argument
  mi1_law
has type
  Dynamics.NewtonLaw.NewtonSecondLaw m1 a Fnet1
of sort `Prop` but is expected to have type
  Compat.PHYSlib.SI.Mass
of sort `Type` in the application
  Compat.PHYSlib.SI.newton_second_law mi1_law
/private/var/folders/vj/48782l41209gm2tv8w9s9gq40000gn/T/pipeline_proof_probe_7mo4hleb.lean:25:54: error: Application type mismatch: The argument
  mi2_law
has type
  Dynamics.NewtonLaw.NewtonSecondLaw m2 a Fnet2
of sort `Prop` but is expected to have type
  Compat.PHYSlib.SI.Mass
of sort `Type` in the application
  Compat.PHYSlib.SI.newton_second_law mi2_law
/private/var/folders/vj/48782l41209gm2tv8w9s9gq40000gn/T/pipeline_proof_p...
```
```text
unsolved goals
case right
m1 m2 : Mass
T Fnet1 Fnet2 : Force
g a : Acceleration
h_net_force_mi1 : Fnet1.val = T.val
h_newton2_mi1 : Fnet1.val = m1.val * a.val
h_net_force_mi2 : Fnet2.val = m2.val * g.val - T.val
h_newton2_mi2 : Fnet2.val = m2.val * a.val
mi1_law : Dynamics.NewtonLaw.NewtonSecondLaw m1 a Fnet1
mi2_law : Dynamics.NewtonLaw.NewtonSecondLaw m2 a Fnet2
h_m1_pos : 0 < m1.val
h_m2_pos : 0 < m2.val
h_glider_nsl : T = m1 * a
h_weight_nsl : m2 * g - T = m2 * a
hden_m1_val___m2_val : m1.val + m2.val ≠ 0
⊢ T.val = m1.val * m2.val * g.val / (m1.val + m2.val)
```
</details>

### 3.10 LLM call 10: node `node_11_17`, depth 9

#### 传给 LLM 的结构化信息

| 字段 | 值 |
| --- | --- |
| llm_call_index | 10 |
| node_id | node_11_17 |
| depth | 9 |
| prompt_chars | 6304 |
| failed_action_count | 4 |
| local_fact_count | 17 |
| remaining_obligation_count | 1 |
| allowed_decl_count | 9 |
| omitted_context | full_retrieval_context, full_problem_ir, full_structured_mechlib_context, full_theorem_corpus, full_previous_proof_attempts |

Target excerpt:
```lean
a.val = (m2.val * g.val) / (m1.val + m2.val) ∧
  T.val = (m1.val * m2.val * g.val) / (m1.val + m2.val)
```
Proof prefix excerpt:
```lean
have h_glider_nsl : T = m1 * a := by
  exact MechLib.Compat.PHYSlib.SI.newton_second_law mi1_law
have h_weight_nsl : m2 * g - T = m2 * a := by
  exact MechLib.Compat.PHYSlib.SI.newton_second_law mi2_law
have hden_m1_val___m2_val : m1.val + m2.val ≠ 0 := by
  nlinarith [h_m1_pos, h_m2_pos]
constructor
have h_glider_nsl_val : T.val = m1.val * a.val := by
  simpa using h_glider_nsl
have h_weight_nsl_val : m2.val * g.val - T.val = m2.val * a.val := by
  simpa using h_weight_nsl
have h_sum_eq : m2.val * g.val = (m1.val + m2.val) * a.val := by
  nlinarith [h_glider_nsl_val, h_weight_nsl_val]
have ha_val : a.val = (m2.val * g.val) / (m1.val + m2.val) := by
  field_simp [hden_m1_val___m2_val]
  nlinarith [h_sum_eq]
have hT_val : T.val = (m1.val * m2.val * g.val) / (m1.val + m2.val) := by
  rw [...
```
Local facts:
```text
h_net_force_mi1
h_newton2_mi1
h_net_force_mi2
h_newton2_mi2
mi1_law
mi2_law
h_glider_nsl
h_weight_nsl
h_mi3
h_m1_pos
h_m2_pos
hden_m1_val___m2_val
h_glider_nsl_val
h_weight_nsl_val
h_sum_eq
ha_val
hT_val
```
Remaining obligations:
| obligation_id | kind | must_use | produced_fact_name | replay_status | formal_claim |
| --- | --- | --- | --- | --- | --- |
| sk_mi3 | constraint_to_equation | MechLib.Kinematics.Verified.Kinematics.linear_constraint_velocity | h_mi3 | pending | a1 = a2 ∧ T1 = T2 |

Allowed verified declarations:
```text
MechLib.Compat.PHYSlib.SI.newton_second_law
MechLib.Analytical.LagrangeEquation.eulerLagrange_iff_newton_course_form
MechLib.Dynamics.NewtonLaw.newtonSecondLaw_course_form
MechLib.Examples.FinalTheoremDemos.newtonSecondLaw_byDefinition
MechLib.Dynamics.NewtonLaw.newton_second_law_verified
MechLib.Dynamics.SystemDynamics.centerOfMassBalance_eq
MechLib.Kinematics.Verified.Kinematics.linear_constraint_velocity
MechLib.Examples.FinalTheoremDemos.eulerLagrangeNewtonBridge_byResidualAlgebra
MechLib.Examples.FinalTheoremDemos.uniformAccelerationDisplacement_byCalculation
```
<details><summary>Prompt excerpt retained in artifact</summary>

````text
You are a Lean proof strategy controller.

Your task is to propose the next proof action, not a complete proof.

You may use only:
- listed local facts,
- listed proof obligations,
- listed verified declarations,
- listed algebra strategy cards,
- standard tactics: simp, simp_all, rw, have, exact, apply, constructor, field_simp, ring_nf, linarith, nlinarith.

Do not:
- introduce new assumptions,
- modify the theorem statement,
- use sorry/admit/axiom,
- use declarations outside whitelist,
- use schema/problem metadata as proof facts.

Available strategy cards:
- derive_law_equation
- derive_model_equation
- prove_side_condition
- split_conjunction
- algebra_solve
- rewrite_forward
- rewrite_backward
- simp_normalize
- quantity_value_projection
- introduce_intermediate_have
- close_goal

Return JSON only:

{"proposals":[{"strategy":"derive_model_equation","tactic_block":"have hT : T.val = m1.val * a.val := by\n  linarith [hFnet1, h_mi1]","uses_facts":["hFnet1","h_mi1"],"uses_decls":[],"expected_effect":"derive a local equation from checked facts","priority":0.9}]}

Compact proof state:

```json
{
  "target": "a.val = (m2.val * g.val) / (m1.val + m2.val) ∧\n  T.val = (m1.val * m2.val * g.val) / (m1.val + m2.val)",
  "proof_prefix_summary": "have h_glider_nsl : T = m1 * a := by\n  exact MechLib.Compat.PHYSlib.SI.newton_second_law mi1_law\nhave h_weight_nsl : m2 * g - T = m2 * a := by\n  exact MechLib.Compat.PHYSlib.SI.newton_second_law mi2_law\nhave hden_m1_val___m2_val : m1.val + m2.val ≠ 0 := by\n  nlinarith [h_m1_pos, h_m2_pos]\nconstructor\nhave h_glider_nsl_val : T.val...
````
</details>

#### LLM 输出动作（parsed proposals）

| action_id | strategy | priority | uses_facts | uses_decls | expected_effect |
| --- | --- | --- | --- | --- | --- |
| llm_10_1 | close_goal | 1.0 | ha_val, hT_val |  | close the conjunctive target using the two already derived component facts |

Action `llm_10_1` tactic:
```lean
exact ⟨ha_val, hT_val⟩
```

#### Probe/check 结果

| action_id | accepted | status | error_type | error_message | new facts | new claims | probe_checks_used | raw_probe_status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| llm_10_1 | False | invalid | type_mismatch | Application type mismatch: The argument |  |  | 19 |  |

<details><summary>llm_10_1 Lean stderr / goals excerpt</summary>

```text
/private/var/folders/vj/48782l41209gm2tv8w9s9gq40000gn/T/pipeline_proof_probe_wbgk1y1j.lean:23:54: error: Application type mismatch: The argument
  mi1_law
has type
  Dynamics.NewtonLaw.NewtonSecondLaw m1 a Fnet1
of sort `Prop` but is expected to have type
  Compat.PHYSlib.SI.Mass
of sort `Type` in the application
  Compat.PHYSlib.SI.newton_second_law mi1_law
/private/var/folders/vj/48782l41209gm2tv8w9s9gq40000gn/T/pipeline_proof_probe_wbgk1y1j.lean:25:54: error: Application type mismatch: The argument
  mi2_law
has type
  Dynamics.NewtonLaw.NewtonSecondLaw m2 a Fnet2
of sort `Prop` but is expected to have type
  Compat.PHYSlib.SI.Mass
of sort `Type` in the application
  Compat.PHYSlib.SI.newton_second_law mi2_law
/private/var/folders/vj/48782l41209gm2tv8w9s9gq40000gn/T/pipeline_proof_p...
```
</details>

### 3.11 LLM call 11: node `node_10_16`, depth 8

#### 传给 LLM 的结构化信息

| 字段 | 值 |
| --- | --- |
| llm_call_index | 11 |
| node_id | node_10_16 |
| depth | 8 |
| prompt_chars | 6682 |
| failed_action_count | 5 |
| local_fact_count | 16 |
| remaining_obligation_count | 1 |
| allowed_decl_count | 9 |
| omitted_context | full_retrieval_context, full_problem_ir, full_structured_mechlib_context, full_theorem_corpus, full_previous_proof_attempts |

Target excerpt:
```lean
a.val = (m2.val * g.val) / (m1.val + m2.val) ∧
  T.val = (m1.val * m2.val * g.val) / (m1.val + m2.val)
```
Proof prefix excerpt:
```lean
have h_glider_nsl : T = m1 * a := by
  exact MechLib.Compat.PHYSlib.SI.newton_second_law mi1_law
have h_weight_nsl : m2 * g - T = m2 * a := by
  exact MechLib.Compat.PHYSlib.SI.newton_second_law mi2_law
have hden_m1_val___m2_val : m1.val + m2.val ≠ 0 := by
  nlinarith [h_m1_pos, h_m2_pos]
constructor
have h_glider_nsl_val : T.val = m1.val * a.val := by
  simpa using h_glider_nsl
have h_weight_nsl_val : m2.val * g.val - T.val = m2.val * a.val := by
  simpa using h_weight_nsl
have h_sum_eq : m2.val * g.val = (m1.val + m2.val) * a.val := by
  nlinarith [h_glider_nsl_val, h_weight_nsl_val]
have ha_val : a.val = (m2.val * g.val) / (m1.val + m2.val) := by
  field_simp [hden_m1_val___m2_val]
  nlinarith [h_sum_eq]
exact ha_val
```
Local facts:
```text
h_net_force_mi1
h_newton2_mi1
h_net_force_mi2
h_newton2_mi2
mi1_law
mi2_law
h_glider_nsl
h_weight_nsl
h_mi3
h_m1_pos
h_m2_pos
hden_m1_val___m2_val
h_glider_nsl_val
h_weight_nsl_val
h_sum_eq
ha_val
```
Remaining obligations:
| obligation_id | kind | must_use | produced_fact_name | replay_status | formal_claim |
| --- | --- | --- | --- | --- | --- |
| sk_mi3 | constraint_to_equation | MechLib.Kinematics.Verified.Kinematics.linear_constraint_velocity | h_mi3 | pending | a1 = a2 ∧ T1 = T2 |

Allowed verified declarations:
```text
MechLib.Compat.PHYSlib.SI.newton_second_law
MechLib.Analytical.LagrangeEquation.eulerLagrange_iff_newton_course_form
MechLib.Dynamics.NewtonLaw.newtonSecondLaw_course_form
MechLib.Examples.FinalTheoremDemos.newtonSecondLaw_byDefinition
MechLib.Dynamics.NewtonLaw.newton_second_law_verified
MechLib.Dynamics.SystemDynamics.centerOfMassBalance_eq
MechLib.Kinematics.Verified.Kinematics.linear_constraint_velocity
MechLib.Examples.FinalTheoremDemos.eulerLagrangeNewtonBridge_byResidualAlgebra
MechLib.Examples.FinalTheoremDemos.uniformAccelerationDisplacement_byCalculation
```
<details><summary>Prompt excerpt retained in artifact</summary>

````text
You are a Lean proof strategy controller.

Your task is to propose the next proof action, not a complete proof.

You may use only:
- listed local facts,
- listed proof obligations,
- listed verified declarations,
- listed algebra strategy cards,
- standard tactics: simp, simp_all, rw, have, exact, apply, constructor, field_simp, ring_nf, linarith, nlinarith.

Do not:
- introduce new assumptions,
- modify the theorem statement,
- use sorry/admit/axiom,
- use declarations outside whitelist,
- use schema/problem metadata as proof facts.

Available strategy cards:
- derive_law_equation
- derive_model_equation
- prove_side_condition
- split_conjunction
- algebra_solve
- rewrite_forward
- rewrite_backward
- simp_normalize
- quantity_value_projection
- introduce_intermediate_have
- close_goal

Return JSON only:

{"proposals":[{"strategy":"derive_model_equation","tactic_block":"have hT : T.val = m1.val * a.val := by\n  linarith [hFnet1, h_mi1]","uses_facts":["hFnet1","h_mi1"],"uses_decls":[],"expected_effect":"derive a local equation from checked facts","priority":0.9}]}

Compact proof state:

```json
{
  "target": "a.val = (m2.val * g.val) / (m1.val + m2.val) ∧\n  T.val = (m1.val * m2.val * g.val) / (m1.val + m2.val)",
  "proof_prefix_summary": "have h_glider_nsl : T = m1 * a := by\n  exact MechLib.Compat.PHYSlib.SI.newton_second_law mi1_law\nhave h_weight_nsl : m2 * g - T = m2 * a := by\n  exact MechLib.Compat.PHYSlib.SI.newton_second_law mi2_law\nhave hden_m1_val___m2_val : m1.val + m2.val ≠ 0 := by\n  nlinarith [h_m1_pos, h_m2_pos]\nconstructor\nhave h_glider_nsl_val : T.val...
````
</details>

#### LLM 输出动作（parsed proposals）

| action_id | strategy | priority | uses_facts | uses_decls | expected_effect |
| --- | --- | --- | --- | --- | --- |
| llm_11_1 | introduce_intermediate_have | 0.97 | h_glider_nsl_val, ha_val, hden_m1_val___m2_val |  | derive the second conjunct by substituting the solved acceleration into T.val = m1.val * a.val and normalizing the division expression |
| llm_11_2 | close_goal | 0.88 | hT_val |  | close the remaining goal once the intermediate equation for T.val is established |

Action `llm_11_1` tactic:
```lean
have hT_val : T.val = (m1.val * m2.val * g.val) / (m1.val + m2.val) := by
  rw [h_glider_nsl_val, ha_val]
  field_simp [hden_m1_val___m2_val]
  ring_nf
```
Action `llm_11_2` tactic:
```lean
exact hT_val
```

#### Probe/check 结果

| action_id | accepted | status | error_type | error_message | new facts | new claims | probe_checks_used | raw_probe_status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| llm_11_1 | True | progress | unsolved_goals | Application type mismatch: The argument | hT_val | T.val = (m1.val * m2.val * g.val) / (m1.val + m2.val) | 20 |  |
| llm_11_2 | False | invalid | action_guard_failed | unknown_or_unproved_local_fact |  |  |  |  |

<details><summary>llm_11_1 Lean stderr / goals excerpt</summary>

```text
/private/var/folders/vj/48782l41209gm2tv8w9s9gq40000gn/T/pipeline_proof_probe_00c1c2yy.lean:23:54: error: Application type mismatch: The argument
  mi1_law
has type
  Dynamics.NewtonLaw.NewtonSecondLaw m1 a Fnet1
of sort `Prop` but is expected to have type
  Compat.PHYSlib.SI.Mass
of sort `Type` in the application
  Compat.PHYSlib.SI.newton_second_law mi1_law
/private/var/folders/vj/48782l41209gm2tv8w9s9gq40000gn/T/pipeline_proof_probe_00c1c2yy.lean:25:54: error: Application type mismatch: The argument
  mi2_law
has type
  Dynamics.NewtonLaw.NewtonSecondLaw m2 a Fnet2
of sort `Prop` but is expected to have type
  Compat.PHYSlib.SI.Mass
of sort `Type` in the application
  Compat.PHYSlib.SI.newton_second_law mi2_law
/private/var/folders/vj/48782l41209gm2tv8w9s9gq40000gn/T/pipeline_proof_p...
```
```text
unsolved goals
case right
m1 m2 : Mass
T Fnet1 Fnet2 : Force
g a : Acceleration
h_net_force_mi1 : Fnet1.val = T.val
h_newton2_mi1 : Fnet1.val = m1.val * a.val
h_net_force_mi2 : Fnet2.val = m2.val * g.val - T.val
h_newton2_mi2 : Fnet2.val = m2.val * a.val
mi1_law : Dynamics.NewtonLaw.NewtonSecondLaw m1 a Fnet1
mi2_law : Dynamics.NewtonLaw.NewtonSecondLaw m2 a Fnet2
h_m1_pos : 0 < m1.val
h_m2_pos : 0 < m2.val
h_glider_nsl : T = m1 * a
h_weight_nsl : m2 * g - T = m2 * a
hden_m1_val___m2_val : m1.val + m2.val ≠ 0
hT_val : T.val = m1.val * m2.val * g.val / (m1.val + m2.val)
⊢ T.val = m1.val * m2.val * g.val / (m1.val + m2.val)
```
</details>

<details><summary>llm_11_2 Lean stderr / goals excerpt</summary>

```text
unknown_or_unproved_local_fact
```
</details>

### 3.12 LLM call 12: node `node_13_18`, depth 9

#### 传给 LLM 的结构化信息

| 字段 | 值 |
| --- | --- |
| llm_call_index | 12 |
| node_id | node_13_18 |
| depth | 9 |
| prompt_chars | 7076 |
| failed_action_count | 6 |
| local_fact_count | 17 |
| remaining_obligation_count | 1 |
| allowed_decl_count | 9 |
| omitted_context | full_retrieval_context, full_problem_ir, full_structured_mechlib_context, full_theorem_corpus, full_previous_proof_attempts |

Target excerpt:
```lean
a.val = (m2.val * g.val) / (m1.val + m2.val) ∧
  T.val = (m1.val * m2.val * g.val) / (m1.val + m2.val)
```
Proof prefix excerpt:
```lean
have h_glider_nsl : T = m1 * a := by
  exact MechLib.Compat.PHYSlib.SI.newton_second_law mi1_law
have h_weight_nsl : m2 * g - T = m2 * a := by
  exact MechLib.Compat.PHYSlib.SI.newton_second_law mi2_law
have hden_m1_val___m2_val : m1.val + m2.val ≠ 0 := by
  nlinarith [h_m1_pos, h_m2_pos]
constructor
have h_glider_nsl_val : T.val = m1.val * a.val := by
  simpa using h_glider_nsl
have h_weight_nsl_val : m2.val * g.val - T.val = m2.val * a.val := by
  simpa using h_weight_nsl
have h_sum_eq : m2.val * g.val = (m1.val + m2.val) * a.val := by
  nlinarith [h_glider_nsl_val, h_weight_nsl_val]
have ha_val : a.val = (m2.val * g.val) / (m1.val + m2.val) := by
  field_simp [hden_m1_val___m2_val]
  nlinarith [h_sum_eq]
exact ha_val
have hT_val : T.val = (m1.val * m2.val * g.val) / (m1.val + m2.val)...
```
Local facts:
```text
h_net_force_mi1
h_newton2_mi1
h_net_force_mi2
h_newton2_mi2
mi1_law
mi2_law
h_glider_nsl
h_weight_nsl
h_mi3
h_m1_pos
h_m2_pos
hden_m1_val___m2_val
h_glider_nsl_val
h_weight_nsl_val
h_sum_eq
ha_val
hT_val
```
Remaining obligations:
| obligation_id | kind | must_use | produced_fact_name | replay_status | formal_claim |
| --- | --- | --- | --- | --- | --- |
| sk_mi3 | constraint_to_equation | MechLib.Kinematics.Verified.Kinematics.linear_constraint_velocity | h_mi3 | pending | a1 = a2 ∧ T1 = T2 |

Allowed verified declarations:
```text
MechLib.Compat.PHYSlib.SI.newton_second_law
MechLib.Analytical.LagrangeEquation.eulerLagrange_iff_newton_course_form
MechLib.Dynamics.NewtonLaw.newtonSecondLaw_course_form
MechLib.Examples.FinalTheoremDemos.newtonSecondLaw_byDefinition
MechLib.Dynamics.NewtonLaw.newton_second_law_verified
MechLib.Dynamics.SystemDynamics.centerOfMassBalance_eq
MechLib.Kinematics.Verified.Kinematics.linear_constraint_velocity
MechLib.Examples.FinalTheoremDemos.eulerLagrangeNewtonBridge_byResidualAlgebra
MechLib.Examples.FinalTheoremDemos.uniformAccelerationDisplacement_byCalculation
```
<details><summary>Prompt excerpt retained in artifact</summary>

````text
You are a Lean proof strategy controller.

Your task is to propose the next proof action, not a complete proof.

You may use only:
- listed local facts,
- listed proof obligations,
- listed verified declarations,
- listed algebra strategy cards,
- standard tactics: simp, simp_all, rw, have, exact, apply, constructor, field_simp, ring_nf, linarith, nlinarith.

Do not:
- introduce new assumptions,
- modify the theorem statement,
- use sorry/admit/axiom,
- use declarations outside whitelist,
- use schema/problem metadata as proof facts.

Available strategy cards:
- derive_law_equation
- derive_model_equation
- prove_side_condition
- split_conjunction
- algebra_solve
- rewrite_forward
- rewrite_backward
- simp_normalize
- quantity_value_projection
- introduce_intermediate_have
- close_goal

Return JSON only:

{"proposals":[{"strategy":"derive_model_equation","tactic_block":"have hT : T.val = m1.val * a.val := by\n  linarith [hFnet1, h_mi1]","uses_facts":["hFnet1","h_mi1"],"uses_decls":[],"expected_effect":"derive a local equation from checked facts","priority":0.9}]}

Compact proof state:

```json
{
  "target": "a.val = (m2.val * g.val) / (m1.val + m2.val) ∧\n  T.val = (m1.val * m2.val * g.val) / (m1.val + m2.val)",
  "proof_prefix_summary": "have h_glider_nsl : T = m1 * a := by\n  exact MechLib.Compat.PHYSlib.SI.newton_second_law mi1_law\nhave h_weight_nsl : m2 * g - T = m2 * a := by\n  exact MechLib.Compat.PHYSlib.SI.newton_second_law mi2_law\nhave hden_m1_val___m2_val : m1.val + m2.val ≠ 0 := by\n  nlinarith [h_m1_pos, h_m2_pos]\nconstructor\nhave h_glider_nsl_val : T.val...
````
</details>

#### LLM 输出动作（parsed proposals）

| action_id | strategy | priority | uses_facts | uses_decls | expected_effect |
| --- | --- | --- | --- | --- | --- |
| llm_12_1 | close_goal | 0.99 | hT_val |  | close the remaining second conjunct goal using the already derived formula for T.val |

Action `llm_12_1` tactic:
```lean
exact hT_val
```

#### Probe/check 结果

| action_id | accepted | status | error_type | error_message | new facts | new claims | probe_checks_used | raw_probe_status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| llm_12_1 | False | invalid | symbol_hallucination | Application type mismatch: The argument |  |  | 21 |  |

<details><summary>llm_12_1 Lean stderr / goals excerpt</summary>

```text
/private/var/folders/vj/48782l41209gm2tv8w9s9gq40000gn/T/pipeline_proof_probe_kvjrbvfe.lean:23:54: error: Application type mismatch: The argument
  mi1_law
has type
  Dynamics.NewtonLaw.NewtonSecondLaw m1 a Fnet1
of sort `Prop` but is expected to have type
  Compat.PHYSlib.SI.Mass
of sort `Type` in the application
  Compat.PHYSlib.SI.newton_second_law mi1_law
/private/var/folders/vj/48782l41209gm2tv8w9s9gq40000gn/T/pipeline_proof_probe_kvjrbvfe.lean:25:54: error: Application type mismatch: The argument
  mi2_law
has type
  Dynamics.NewtonLaw.NewtonSecondLaw m2 a Fnet2
of sort `Prop` but is expected to have type
  Compat.PHYSlib.SI.Mass
of sort `Type` in the application
  Compat.PHYSlib.SI.newton_second_law mi2_law
/private/var/folders/vj/48782l41209gm2tv8w9s9gq40000gn/T/pipeline_proof_p...
```
</details>

## 4. 从报告直接看到的问题

- LLM 原始输出未落盘，当前只能审计解析后的 action proposals；如果需要逐字复盘 prompt-response，需要新增 raw response trace 字段。
- 确定性 `newton_second_law` extractor 生成的动作被标记为 progress，但 stderr 中已经出现 application type mismatch；这是“部分 prefix 继续推进但最终 replay 未成功”的重要诊断点。
- `MechLib.Kinematics.Verified.Kinematics.linear_constraint_velocity` 对应 obligation `sk_mi3` 一直保持 pending，后续 LLM 基本转入代数/拆合取，未真正消费该 required declaration。
- side-condition denominator `m1.val + m2.val` 只出现一次，说明本轮去重确实避免了同一 denominator 的重复循环。
- 后段多次接近目标：`ha_val` 和 `hT_val` 被构造出来，但在不同分支的 proof prefix 中不可同时可见或目标形态不匹配，导致 `exact ⟨ha_val, hT_val⟩` 出现 type mismatch / symbol hallucination / no meaningful progress。
