# Mechanics73 E 阶段 LLM Obligation Fallback 复测报告

- 运行目录：`/Users/weizhixin/AI4Mechanics/LeanMech/runs/20260514_201233_mechanics73-llm-obligation-fallback-20260514`
- latest 镜像：`/Users/weizhixin/AI4Mechanics/LeanMech/outputs/latest`
- 样本：`lean4phys-university_mechanics_Mechanics_73_University`
- 运行命令：`.venv/bin/python -m mech_pipeline.cli run --config tmp/minimal_mechanics73_single_20260514.yaml --tag mechanics73-llm-obligation-fallback-20260514`
- 数据来源：`sample_summary.jsonl`、`proof_search_trace.jsonl`、`proof_action_checks.jsonl`、`proof_strategy_prompts.jsonl`、`proof_dependency_audit.jsonl`

## 1. 本轮机制修改

本轮把 `exact must_use from_hypothesis` 从“固定成功路径”降级为 deterministic preflight：

1. 先尝试 deterministic extractor preflight。
2. 如果 Lean 返回 type/API/symbol 错误，该 action 标记为 invalid，不产生 fact，不覆盖 obligation。
3. search 不再立即以 `missing_proof_friendly_extractor` 终止，而是进入 LLM local-action synthesis fallback。
4. fallback prompt 打开 `decl_candidate_mode=true`，把 required declarations 和其他 allowed verified declaration candidates 一并提供给 LLM。
5. LLM 仍只能提出局部 action；每个 action 仍必须经过 ActionGuard、Lean probe 和最终 replay。

## 2. 运行总览

| 字段 | 值 |
| --- | --- |
| compile_ok | True |
| semantic_ok | True |
| proof_ok | False |
| final_error_type | proof_search_failure |
| sub_error_type | proof_action_synthesis_failed_after_preflight |
| search_status | failed |
| failure_reason | proof_action_synthesis_failed_after_preflight |
| search_elapsed_s | 61.236 |
| nodes_expanded | 6 |
| llm_calls | 4 |
| probe_checks | 7 |
| proof_strategy_prompts rows | 4 |
| proof_action_checks rows | 8 |
| dependency classification | proof_failed |

`outputs/latest/sample_summary.jsonl` 与本次 run 的 `sample_summary.jsonl` 一致；`outputs/latest/proof_search_trace.jsonl` 与本次 run 的 `proof_search_trace.jsonl` 一致。

## 3. Preflight 结果

两个 deterministic exact extractor preflight 均被 Lean 判定为 invalid。

| action_id | tactic | status | error_type |
| --- | --- | --- | --- |
| sk1_1 | `exact MechLib.Compat.PHYSlib.SI.newton_second_law mi1_law` | invalid | type_mismatch |
| sk2_1 | `exact MechLib.Compat.PHYSlib.SI.newton_second_law mi2_law` | invalid | type_mismatch |

核心 Lean 报错仍是：

```text
mi1_law has type
  Dynamics.NewtonLaw.NewtonSecondLaw m1 a Fnet1
but is expected to have type
  Compat.PHYSlib.SI.Mass
```

这说明 `MechLib.Compat.PHYSlib.SI.newton_second_law` 仍然不是当前 `NewtonSecondLaw ...` predicate hypothesis 的 proof-friendly extractor。

## 4. LLM Fallback 行为

本次进入了 4 次 LLM strategy call，且所有 prompt 都带有：

| 字段 | 值 |
| --- | --- |
| decl_candidate_mode | True |
| remaining sk1 error | missing_proof_friendly_extractor |
| remaining sk2 error | missing_proof_friendly_extractor |
| remaining sk_mi3 error | from_hypothesis_missing |

prompt 中的 allowed declarations 包括：

```text
MechLib.Compat.PHYSlib.SI.newton_second_law
MechLib.Kinematics.Verified.Kinematics.linear_constraint_velocity
MechLib.Analytical.LagrangeEquation.eulerLagrange_iff_newton_course_form
MechLib.Dynamics.NewtonLaw.newtonSecondLaw_course_form
MechLib.Dynamics.NewtonLaw.newton_second_law_verified
MechLib.Dynamics.SystemDynamics.centerOfMassBalance_eq
MechLib.Examples.FinalTheoremDemos.newtonSecondLaw_byDefinition
MechLib.Examples.FinalTheoremDemos.eulerLagrangeNewtonBridge_byResidualAlgebra
MechLib.Examples.FinalTheoremDemos.uniformAccelerationDisplacement_byCalculation
```

### 4.1 Accepted LLM actions

| action_id | strategy | accepted | status | new fact | uses_decls |
| --- | --- | --- | --- | --- | --- |
| llm_1_1 | introduce_intermediate_have | True | progress | hTma |  |
| llm_2_1 | derive_model_equation | True | progress | h_mi2_eq |  |
| llm_3_1 | algebra_solve | True | progress | ha |  |

LLM 生成的主要动作：

```lean
have hTma : T.val = m1.val * a.val := by
  linarith [h_mi1_net_force, h_mi1_newton2]
```

```lean
have h_mi2_eq : m2.val * g.val - T.val = m2.val * a.val := by
  linarith [h_mi2_net_force, h_mi2_newton2]
```

```lean
have ha : a.val = m2.val * g.val / (m1.val + m2.val) := by
  field_simp [hden_m1_val___m2_val]
  nlinarith [hTma, h_mi2_eq]
```

这些动作都通过 Lean probe，但它们没有使用 MechLib verified declarations，也没有覆盖 `sk1` / `sk2` / `sk_mi3`。

### 4.2 Rejected LLM action

```lean
have hTfinal : T.val = m1.val * m2.val * g.val / (m1.val + m2.val) := by
  rw [hTma, ha]
  field_simp [hden_m1_val___m2_val]
  ring_nf
```

Lean 返回：

```text
error: No goals to be solved
```

该 action 被标记为 invalid，没有进入 proof prefix。

## 5. Dependency Audit

| 字段 | 值 |
| --- | --- |
| proof_success | False |
| used_verified_decls |  |
| required_verified_decls | `MechLib.Compat.PHYSlib.SI.newton_second_law`, `MechLib.Kinematics.Verified.Kinematics.linear_constraint_velocity` |
| missing_required_decls | `MechLib.Compat.PHYSlib.SI.newton_second_law`, `MechLib.Kinematics.Verified.Kinematics.linear_constraint_velocity` |
| covered_obligations |  |
| missing_obligations | sk1, sk2, sk_mi3 |
| fully_mechlib_verified | False |
| classification | proof_failed |

audit 行为符合预期：即使 LLM 通过已有 value-level hypotheses 推进了代数，它没有使用 required verified declaration，也没有覆盖 proof obligations，因此没有被标记为 fully verified。

## 6. 结论

本轮目标已经达成：E 阶段不再把 proof obligation 固定为 `exact must_use from_hypothesis`，preflight 失败后会进入 LLM-guided local-action synthesis，并且每个动作仍由 Lean 认证。

但复测也说明下一层问题仍然存在：

1. 当前 theorem skeleton 仍把 law application 的 value-level 结果放进 hypotheses，例如 `h_mi1_newton2`、`h_mi2_newton2`。
2. LLM fallback 会自然优先使用这些已有 hypotheses 做代数，而不是解决 required MechLib obligation。
3. 当前 `proof_obligations` 仍没有 proof-friendly extractor；`MechLib.Compat.PHYSlib.SI.newton_second_law` 作为 required decl 仍无法从 `mi1_law` / `mi2_law` 直接推出 formal claim。

下一步建议：

1. 在 proof obligation synthesis 阶段区分 `required_decl`、`allowed_decl_candidates`、`extractor_decl` 和 `extractor_call_shape`。
2. 对 law/constraint obligations，在 obligation 未覆盖前，优先要求 LLM action 使用 verified declaration；纯 algebra action 可以接受为局部 progress，但不得覆盖 law obligation。
3. 继续清理 theorem skeleton，避免把 `h_mi1_newton2`、`h_mi2_newton2` 这类物理定律应用结果提前放入 hypotheses。
