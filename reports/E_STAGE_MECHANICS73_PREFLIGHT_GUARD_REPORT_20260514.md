# Mechanics73 E 阶段 Preflight Guard 修改与运行报告

- 运行目录：`/Users/weizhixin/AI4Mechanics/LeanMech/runs/20260514_193629_mechanics73-p2-search-guards-20260514`
- latest 镜像：`/Users/weizhixin/AI4Mechanics/LeanMech/outputs/latest`
- 样本：`lean4phys-university_mechanics_Mechanics_73_University`
- 运行命令：`.venv/bin/python -m mech_pipeline.cli run --config tmp/minimal_mechanics73_single_20260514.yaml --tag mechanics73-p2-search-guards-20260514`
- 数据来源：`sample_summary.jsonl`、`proof_search_trace.jsonl`、`proof_action_checks.jsonl`、`proof_strategy_prompts.jsonl`、`proof_dependency_audit.jsonl`、`proof_attempts.jsonl`、`proof_checks.jsonl`、`theorem_skeleton_candidates.jsonl`
- 重要观测限制：本次 E 阶段在 deterministic extractor preflight 失败后停止，未进入 LLM-guided loop，因此没有 LLM prompt 或 raw response 可整理。

## 1. 修改结果总览

本轮修改围绕 P0/P1/P2 做了三类收紧。

| 优先级 | 改动 | 结果 |
| --- | --- | --- |
| P0 | probe classifier 收紧：stderr 中出现非 `unsolved goals` 的 `error:` 时直接 `invalid` | `Application type mismatch` 不再被误标为 `progress` |
| P0 | 无效 action 不再产生 `new_local_facts` / `covered_obligations` | 错误的 `h_glider_nsl`、`h_weight_nsl` 不会污染后续搜索 |
| P0/P1 | deterministic extractor preflight 只先尝试 `exact must_use from_hypothesis`；类型/API/符号错误直接 `missing_proof_friendly_extractor` | Mechanics73 本次 `llm_calls=0`，没有继续 12 次 LLM 循环 |
| P1 | dependency audit 只从最终 replay proof body 统计 required declaration 使用 | 无效 prefix 中出现的 `MechLib.Compat.PHYSlib.SI.newton_second_law` 没有计入 `used_verified_decls` |
| P2 | 线性 prefix search 中禁止 LLM 早期 `constructor` / `split_conjunction` | 防止 branch 子目标状态未建模时错误扩展 |
| P2 | prompt 增加 active goal、本地 fact 命题摘要，并按 remaining obligations 收缩 allowed declarations | 减少无关 declaration 噪声；本次运行未进入 LLM prompt，靠单元测试覆盖 |
| P2 | 增加 repeated failed action shape 检测 | 同一 prefix 下只换 `have` 名的失败动作不再重复 probe |

### 1.1 改动文件

| 文件 | 主要内容 |
| --- | --- |
| `src/mech_pipeline/adapters/lean_runner.py` | probe stderr 分类：混合 `Application type mismatch` + `unsolved goals` 归为 invalid/type_mismatch |
| `src/mech_pipeline/modules/e_obligation_replayer.py` | extractor preflight 失败映射为 `missing_proof_friendly_extractor`，并停止后续 deterministic 替代模板 |
| `src/mech_pipeline/modules/e_search_controller.py` | invalid action 不更新 search state；preflight fail 后跳过 LLM；constructor 禁用、action shape 去重、active goal/local fact type prompt |
| `src/mech_pipeline/modules/e_proof_context.py` | pending obligation 的 produced fact 不再进入初始 `allowed_local_facts` |
| `src/mech_pipeline/modules/e_strategy_controller.py`、`prompts/E_strategy_controller.md` | prompt 去掉 `split_conjunction`，增加 active goal，收缩 allowed decls |
| `src/mech_pipeline/modules/e_side_conditions.py` | side-condition denominator 去重辅助 |
| `src/mech_pipeline/types.py` | `ProofSearchNode` 增加 local fact claim/type 与 side-condition denominator 状态 |
| `docs/e_llm_guided_certified_prover.md` | 同步记录 classifier、preflight、prompt 和 loop detection 行为 |
| `tests/test_e_*.py` | 增加 classifier、preflight、invalid fact、constructor ban、repeated shape、prompt 收缩等回归测试 |

## 2. 本次运行总览

| 字段 | 值 |
| --- | --- |
| grounding_ok | True |
| statement_generation_ok | True |
| compile_ok | True |
| semantic_ok | True |
| proof_ok | False |
| final_error_type | proof_search_failure |
| sub_error_type | missing_proof_friendly_extractor |
| search_status | failed |
| failure_reason | missing_proof_friendly_extractor |
| search_elapsed_s | 86.195 |
| nodes_expanded | 0 |
| llm_calls | 0 |
| probe_checks | 2 |
| physical_assumption_augmented | False |
| fully_mechlib_verified | False |
| dependency classification | proof_failed |

`outputs/latest/sample_summary.jsonl` 与本次 run 的 `sample_summary.jsonl` 一致；`outputs/latest/proof_search_trace.jsonl` 与本次 run 的 `proof_search_trace.jsonl` 一致。

### 2.1 文件索引

| 文件 | 行数 | 作用 |
| --- | ---: | --- |
| `sample_summary.jsonl` | 1 | 样本级最终结果 |
| `proof_search_trace.jsonl` | 1 | E search 汇总与 accepted/rejected actions |
| `proof_action_checks.jsonl` | 2 | 两个 deterministic preflight probe 的 Lean 结果 |
| `proof_strategy_prompts.jsonl` | 0 | 未进入 LLM-guided loop |
| `proof_dependency_audit.jsonl` | 1 | required/used declarations 与 obligation 覆盖审计 |
| `proof_attempts.jsonl` | 1 | E attempt 聚合记录 |
| `proof_checks.jsonl` | 1 | proof check 汇总 |

## 3. E 阶段输入结构

### 3.1 theorem skeleton

```lean
theorem lean4phys_university_mechanics_Mechanics_73_University_c1_explicit_gap_allowed
  (m1 m2 : Mass)
  (T Fnet1 Fnet2 : Force)
  (g a a1 a2 : Acceleration)
  (equal_acceleration_magnitude : a1.val = a2.val)
  (common_acceleration_symbol : a1.val = a.val ∧ a2.val = a.val)
  (h_mi1_net_force_balance : Fnet1.val = T.val)
  (h_mi1_newton_second_law : Fnet1.val = m1.val * a1.val)
  (h_mi2_net_force_balance : Fnet2.val = m2.val * g.val - T.val)
  (h_mi2_newton_second_law : Fnet2.val = m2.val * a2.val)
  (h_mi3_constraint_acceleration : a1.val = a2.val)
  (h_mi3_common_symbol_glider : a1.val = a.val)
  (h_mi3_common_symbol_weight : a2.val = a.val)
  (h_mii1 : Fnet1.val = T.val)
  (h_mii2 : Fnet2.val = m2.val * g.val - T.val)
  (h_mii3 : a1.val = a.val)
  (h_mii4 : a2.val = a.val)
  (mi1_law : MechLib.Dynamics.NewtonLaw.NewtonSecondLaw m1 a1 T)
  (mi2_law : MechLib.Dynamics.NewtonLaw.NewtonSecondLaw m2 a2 T)
  : a.val = (m2.val * g.val) / (m1.val + m2.val) ∧
  T.val = (m1.val * m2.val * g.val) / (m1.val + m2.val)
```

注意：当前 theorem hypotheses 中已经有 value-level 方程 `h_mi1_newton_second_law`、`h_mi2_newton_second_law`。这不是本轮修改的目标，但它仍是后续要继续清理的建模/最小 skeleton 问题。

### 3.2 proof obligations

| obligation_id | kind | source_model_instance | must_use | formal_claim | produced_fact_name |
| --- | --- | --- | --- | --- | --- |
| sk1 | law_to_equation | mi1 | `MechLib.Compat.PHYSlib.SI.newton_second_law` | `Fnet1 = m1 * a1` | h_glider_nsl |
| sk2 | law_to_equation | mi2 | `MechLib.Compat.PHYSlib.SI.newton_second_law` | `Fnet2 = m2 * a2` | h_weight_nsl |
| sk_mi3 | constraint_to_equation | mi3 | `MechLib.Kinematics.Verified.Kinematics.linear_constraint_velocity` | `a1 = a2 and a1 = a and a2 = a` | h_mi3 |

关键问题仍然是 `must_use` 绑定：`MechLib.Compat.PHYSlib.SI.newton_second_law` 的声明形态是

```lean
theorem newton_second_law (m : Mass) (a : Acceleration) : F_of m a = m * a
```

它不是从

```lean
mi1_law : MechLib.Dynamics.NewtonLaw.NewtonSecondLaw m1 a1 T
```

推出 `Fnet1 = m1 * a1` 的 extractor theorem。因此它不应该被当作当前 model predicate hypothesis 的 `must_use` extractor。

## 4. Deterministic Preflight 结果

本次 E 阶段只执行了两个 deterministic exact extractor preflight。两者都被 Lean 判定为 invalid，且没有 accepted action。

| row | action_id | strategy | accepted | status | error_type | uses_facts | uses_decls |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | sk1_1 | deterministic_exact_extractor | False | invalid | type_mismatch | mi1_law | `MechLib.Compat.PHYSlib.SI.newton_second_law` |
| 2 | sk2_1 | deterministic_exact_extractor | False | invalid | type_mismatch | mi2_law | `MechLib.Compat.PHYSlib.SI.newton_second_law` |

### 4.1 sk1_1

```lean
have h_glider_nsl : Fnet1 = m1 * a1 := by
  exact MechLib.Compat.PHYSlib.SI.newton_second_law mi1_law
```

Lean stderr excerpt:

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

本轮修复后的分类结果：

| 字段 | 值 |
| --- | --- |
| accepted | False |
| status | invalid |
| error_type | type_mismatch |
| new_local_facts | 未产生 |
| covered_obligations | 未覆盖 |

### 4.2 sk2_1

```lean
have h_weight_nsl : Fnet2 = m2 * a2 := by
  exact MechLib.Compat.PHYSlib.SI.newton_second_law mi2_law
```

Lean stderr excerpt:

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

本轮修复后的分类结果：

| 字段 | 值 |
| --- | --- |
| accepted | False |
| status | invalid |
| error_type | type_mismatch |
| new_local_facts | 未产生 |
| covered_obligations | 未覆盖 |

## 5. LLM 调用情况

本次没有 LLM strategy call。

| 字段 | 值 |
| --- | --- |
| proof_strategy_prompts rows | 0 |
| trace.llm_calls | 0 |
| trace.nodes_expanded | 0 |
| trace.failure_reason | missing_proof_friendly_extractor |

这正是本轮 P0/P1 的目标行为：当 deterministic extractor preflight 已经证明 `must_use` 与 `from_hypothesis` API 不匹配时，不再把错误 prefix 交给 LLM，也不再让 LLM 围绕不存在的 `h_glider_nsl` / `h_weight_nsl` 继续生成后续 tactic。

## 6. Dependency Audit

| 字段 | 值 |
| --- | --- |
| proof_success | False |
| used_verified_decls |  |
| required_verified_decls | `MechLib.Compat.PHYSlib.SI.newton_second_law`, `MechLib.Kinematics.Verified.Kinematics.linear_constraint_velocity` |
| missing_required_decls | `MechLib.Compat.PHYSlib.SI.newton_second_law`, `MechLib.Kinematics.Verified.Kinematics.linear_constraint_velocity` |
| covered_obligations |  |
| missing_obligations | sk1, sk2, sk_mi3 |
| schema_metadata_in_proof_body | False |
| algebra_only | False |
| gap_assisted | True |
| fully_mechlib_verified | False |
| classification | proof_failed |

这里有两个重要变化：

1. 虽然 invalid tactic block 中出现了 `MechLib.Compat.PHYSlib.SI.newton_second_law`，但它没有进入最终 replay proof body，因此没有计入 `used_verified_decls`。
2. `sk1` / `sk2` 的 preflight 没通过，所以 `h_glider_nsl` / `h_weight_nsl` 没有被当作 covered obligation。

## 7. 与前两次报告的关键差异

| 现象 | 前两次运行 | 本次运行 |
| --- | --- | --- |
| `Application type mismatch` + `unsolved goals` | 曾被误标为 `accepted=True` / `progress` | 标为 `accepted=False` / `invalid` / `type_mismatch` |
| 错误 extractor action 是否产生 fact | 曾产生 `h_glider_nsl`、`h_weight_nsl` 并污染后续 LLM | 未产生任何 accepted fact |
| LLM 是否围绕坏 prefix 继续搜索 | 曾继续生成投影、constructor、algebra action | `llm_calls=0`，直接停止 |
| failure reason | `search_queue_exhausted` 或 `max_llm_calls_exhausted` | `missing_proof_friendly_extractor` |
| dependency audit | 可能受无效 prefix 文本干扰 | 只统计最终 proof body，`used_verified_decls=[]` |

## 8. 验证结果

| 验证 | 命令 | 结果 |
| --- | --- | --- |
| focused tests | `.venv/bin/python -m pytest tests/test_e_search_controller_basic.py tests/test_e_strategy_prompt_compact.py tests/test_e_strategy_controller_prompt.py tests/test_e_action_guard.py` | 32 passed |
| full tests | `.venv/bin/python -m pytest` | 275 passed |
| Mechanics73 real API | `.venv/bin/python -m mech_pipeline.cli run --config tmp/minimal_mechanics73_single_20260514.yaml --tag mechanics73-p2-search-guards-20260514` | compile/semantic ok, proof failed as `missing_proof_friendly_extractor`, no LLM loop |

## 9. 已知限制与下一步

1. 本轮修复的是 E 阶段 checker/search state 的认证边界，不是 MechLib declaration 本身。当前仍缺少能从 `NewtonSecondLaw m a F` predicate hypothesis 推出 value equation 的 proof-friendly extractor。
2. `proof_obligations` 仍把 `MechLib.Compat.PHYSlib.SI.newton_second_law` 绑定为 `must_use`。E 阶段现在能明确拒绝这个绑定，但更上游的 EvidenceBinding / obligation construction 仍需要避免把非 extractor theorem 选为 `must_use`。
3. P2 的 prompt 改进和 constructor ban 已由单元测试覆盖；Mechanics73 本次因 preflight fail 没有进入 LLM prompt，所以这些策略未在该样本真实 API 中触发。
4. theorem skeleton 里仍存在 value-level law equations 作为 hypotheses 的痕迹，例如 `h_mi1_newton_second_law`、`h_mi2_newton_second_law`。这与“物理定律应用结果应在 E 阶段推出”的目标仍有张力，需要继续从 D/ControlledSketch/EvidenceBinding 链路清理。

## 10. 结论

本次修改达成了 P0 的核心目标：错误 extractor 不再被当作有效 progress，也不会产生 local fact 或污染搜索树。Mechanics73 的 E 阶段现在在两个 Lean-certified preflight failure 后以 `missing_proof_friendly_extractor` 退出，`llm_calls=0`，避免了前两次报告中持续 LLM 循环和 token 浪费的问题。

下一步应集中在 P1 的上游绑定修正：为 `NewtonSecondLaw` predicate 提供或检索真正 proof-friendly 的 extractor declaration；如果 MechLib 当前不存在该 theorem，应明确把 obligation 标为 `missing_proof_friendly_extractor`，而不是把定义型 theorem 当作 extractor。
