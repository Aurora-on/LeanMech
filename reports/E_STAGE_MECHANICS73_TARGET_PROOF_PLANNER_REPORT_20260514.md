# Mechanics73 E 阶段 Blocked Obligation 与 Target Proof Planner 报告

- 运行目录：`/Users/weizhixin/AI4Mechanics/LeanMech/runs/20260514_222459_mechanics73-target-planner-havefix-no-declcheck-20260514`
- latest 镜像：`/Users/weizhixin/AI4Mechanics/LeanMech/outputs/latest`
- 样本：`lean4phys-university_mechanics_Mechanics_73_University`
- 运行命令：`.venv/bin/python -m mech_pipeline.cli run --config tmp/minimal_mechanics73_single_no_declcheck_20260514.yaml --tag mechanics73-target-planner-havefix-no-declcheck-20260514 --sample-concurrency 1`
- 数据来源：`sample_summary.jsonl`、`proof_search_trace.jsonl`、`proof_strategy_prompts.jsonl`、`proof_action_checks.jsonl`、`proof_dependency_audit.jsonl`、`proof_attempts.jsonl`、`proof_checks.jsonl`、`metrics.json`
- 复测前提：本次小规模复测使用 `knowledge.lean_check_decls=false` 跳过较慢的 evidence declaration `#check`，但 E 阶段 proof action probe、最终 proof replay 规则和 dependency audit 仍按 Lean 检查结果执行。

## 1. 本轮修改总览

本轮修改目标是把 preflight 失败的 proof obligations 从“继续交给 LLM 反复尝试”改为“明确阻断，并切换到从可用 facts 证明 target 的模式”。这不是把系统退回 legacy full proof，而是让 LLM 负责局部代数 fact plan，Lean 继续检查每个动作。

| 改动方向 | 实现结果 |
| --- | --- |
| blocked obligations | deterministic preflight 失败后，obligation 进入 `blocked_obligations`，不再留在 `remaining_obligations` |
| search mode | 当 required obligations 被阻断后，E search 切换为 `target_proof_from_available_facts` |
| prompt 收缩 | target mode 下清空 `allowed_decls`、`required_decls` 和 active obligations，只保留 local facts、accepted prefix、blocked diagnostics、target |
| target proof planner | LLM 可返回 `fact_plan` + `close`；E 阶段逐条转为 Lean `have` / closing tactic 并 probe |
| search state | queued node 支持 `planned_actions`，同一 LLM fact plan 的后续动作不再重复调用 LLM |
| dependency audit | 只统计最终 Lean proof body 中实际出现的 declaration；obligation 覆盖要求 produced fact 和 required declaration 都真实出现在通过的 proof body 中 |

### 1.1 修改文件

| 文件 | 主要修改 |
| --- | --- |
| `src/mech_pipeline/types.py` | `ProofSearchNode` 增加 `planned_actions`；`ProofSearchTrace` 增加 `search_mode` 和 `blocked_obligations` |
| `src/mech_pipeline/modules/e_search_controller.py` | blocked obligation 状态、target search mode、fact-plan action queue、target mode prompt context、side-condition 后继续 LLM search |
| `src/mech_pipeline/modules/e_strategy_controller.py` | 按 `search_mode` 构造 compact payload；target mode 不暴露 allowed declarations 和 remaining obligations |
| `prompts/E_strategy_controller.md` | 增加 target mode 指令：blocked obligations 仅作诊断，不再尝试 blocked declarations；优先输出短 fact plan |
| `src/mech_pipeline/modules/e_dependency_audit.py` | verified declaration 使用和 obligation 覆盖改为 Lean identifier 精确匹配，避免 substring 误判 |
| `tests/test_e_search_controller_basic.py` | 增加 blocked obligations、target mode、fact plan sequencing、full-have tactic 解析等回归测试 |
| `tests/test_e_strategy_prompt_compact.py` | 验证 target mode prompt 收缩 |
| `tests/test_e_dependency_audit.py` | 验证无 required declaration 时不误覆盖 obligation |

## 2. 最后一次运行总览

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
| search_mode | target_proof_from_available_facts |
| nodes_expanded | 5 |
| llm_calls | 1 |
| probe_checks | 6 |
| physical_assumption_augmented | True |
| latest mirror check | `outputs/latest` 与本次 run 的 `sample_summary.jsonl`、`proof_search_trace.jsonl` 一致 |

本次最终没有完成 proof，但失败形态已经从旧问题“无效 extractor 被当作 progress 并污染搜索树”变为可诊断的 target-mode 局部 proof action 失败。无效 `MechLib.Compat.PHYSlib.SI.newton_second_law mi*_law` 没有产生 fact，也没有进入最终依赖审计。

## 3. E 阶段状态流

### 3.1 Preflight 输入 obligations

| obligation_id | kind | from_hypothesis | must_use | formal_claim | produced_fact_name |
| --- | --- | --- | --- | --- | --- |
| sk1 | law_to_equation | `mi1_law` | `MechLib.Compat.PHYSlib.SI.newton_second_law` | `Fnet1 = m1 * a` | `h_glider_newton` |
| sk2 | law_to_equation | `mi2_law` | `MechLib.Compat.PHYSlib.SI.newton_second_law` | `Fnet2 = m2 * a` | `h_weight_newton` |

### 3.2 Deterministic extractor preflight

两个 deterministic exact extractor 均被 Lean 判定为 invalid/type_mismatch。

```lean
have h_glider_newton : Fnet1 = m1 * a := by
  exact MechLib.Compat.PHYSlib.SI.newton_second_law mi1_law
```

```lean
have h_weight_newton : Fnet2 = m2 * a := by
  exact MechLib.Compat.PHYSlib.SI.newton_second_law mi2_law
```

Lean 报错核心是 `mi*_law` 的类型为 `Dynamics.NewtonLaw.NewtonSecondLaw ...`，但该 declaration 期望的第一个参数是 `Compat.PHYSlib.SI.Mass`。因此它不是当前 model predicate hypothesis 的 proof-friendly extractor。

本轮新状态：

```json
{
  "remaining_obligations": [],
  "blocked_obligations": [
    {
      "obligation_id": "sk1",
      "reason": "missing_proof_friendly_extractor"
    },
    {
      "obligation_id": "sk2",
      "reason": "missing_proof_friendly_extractor"
    }
  ],
  "search_mode": "target_proof_from_available_facts"
}
```

### 3.3 Target mode prompt

本次只发生一次 LLM strategy call。

| 字段 | 值 |
| --- | --- |
| llm_call_index | 1 |
| node_id | node_2_2 |
| depth | 2 |
| prompt_chars | 7909 |
| local_facts_n | 11 |
| remaining_obligations | 0 |
| blocked_obligations | 2 |
| allowed_decls | 0 |
| decl_candidate_mode | False |

prompt 中的 active goal 明确包含当前可用 facts 和 target：

```text
h_mi1_net_force_balance : Fnet1.val = T.val
h_mi1_newton2 : Fnet1.val = m1.val * a.val
h_mi2_net_force_balance : Fnet2.val = m2.val * g.val - T.val
h_mi2_newton2 : Fnet2.val = m2.val * a.val
hden_m1_val___m2_val : m1.val + m2.val ≠ 0
⊢ a.val = m2.val * g.val / (m1.val + m2.val) ∧
  T.val = m1.val * m2.val * g.val / (m1.val + m2.val)
```

这符合本轮目标：prompt 没有继续要求覆盖 `sk1` / `sk2`，也没有暴露 Lagrange、center of mass 或 example demos 等无关 declarations。

## 4. Accepted / Rejected Actions

### 4.1 Accepted actions

| row | source | strategy | status | new facts |
| --- | --- | --- | --- | --- |
| 1 | deterministic | augment_physical_positive_hypotheses | progress | `h_m1_pos`, `h_m2_pos` |
| 2 | deterministic | prove_side_condition | progress | `hden_m1_val___m2_val` |
| 3 | LLM fact plan | target_fact_plan_have | progress | `hT_eq` |
| 4 | LLM fact plan | target_fact_plan_have | progress | `ha_eq` |

Accepted proof prefix:

```lean
have hden_m1_val___m2_val : m1.val + m2.val ≠ 0 := by
  nlinarith [h_m1_pos, h_m2_pos]

have hT_eq : T.val = m1.val * a.val := by
  linarith [h_mi1_net_force_balance, h_mi1_newton2]

have ha_eq : a.val = m2.val * g.val / (m1.val + m2.val) := by
  field_simp [hden_m1_val___m2_val]
  nlinarith [hT_eq, h_mi2_net_force_balance, h_mi2_newton2]
```

### 4.2 Rejected actions

| row | source | strategy | error_type | 说明 |
| --- | --- | --- | --- | --- |
| 1 | deterministic | deterministic_exact_extractor | type_mismatch | `newton_second_law mi1_law` API 不匹配 |
| 2 | deterministic | deterministic_exact_extractor | type_mismatch | `newton_second_law mi2_law` API 不匹配 |
| 3 | LLM fact plan | target_fact_plan_have | tactic_no_goals | LLM 为 `hT_final` 生成的 tactic 在 `rw [hT_eq, ha_eq]` 后目标已关闭，后续 tactic 触发 `No goals to be solved` |

Rejected LLM action:

```lean
have hT_final : T.val = m1.val * m2.val * g.val / (m1.val + m2.val) := by
  rw [hT_eq, ha_eq]
  field_simp [hden_m1_val___m2_val]
  ring_nf
```

Lean 返回：

```text
No goals to be solved
```

该 action 被标记为 invalid，没有进入 proof prefix。搜索没有继续复用这个坏 action，也没有产生 `hT_final`。

## 5. Dependency Audit

| 字段 | 值 |
| --- | --- |
| proof_success | False |
| used_verified_decls |  |
| required_verified_decls | `MechLib.Compat.PHYSlib.SI.newton_second_law` |
| missing_required_decls | `MechLib.Compat.PHYSlib.SI.newton_second_law` |
| covered_obligations |  |
| missing_obligations | sk1, sk2 |
| gap_assisted | True |
| fully_mechlib_verified | False |
| algebra_only | False |
| classification | proof_failed |
| schema_metadata_in_proof_body | False |

本次 audit 符合保守标准：无效 prefix 中出现过的 declaration 不计入 `used_verified_decls`；只靠 theorem hypotheses 进行的代数推进也不覆盖 law obligations。

## 6. Metrics 摘要

| 指标 | 值 |
| --- | ---: |
| proof_success_rate | 0.0 |
| end_to_end_verified_solve_rate | 0.0 |
| obligation_replay_success_rate | 0.0 |
| proof_obligation_coverage_rate | 0.0 |
| verified_decl_use_rate | 0.0 |
| fully_mechlib_verified_proof_rate | 0.0 |
| gap_assisted_success_rate | 0.0 |
| algebra_only_success_rate | 0.0 |
| valid_llm_action_rate | 0.666667 |
| invalid_llm_action_rate | 0.333333 |
| average_llm_calls_per_proof | 1.0 |
| average_lean_action_checks_per_proof | 7.0 |

## 7. 测试结果

本轮完成后的目标测试：

```text
.venv/bin/python -m pytest \
  tests/test_e_dependency_audit.py \
  tests/test_e_search_controller_basic.py \
  tests/test_e_strategy_prompt_compact.py \
  tests/test_e_strategy_controller_prompt.py \
  tests/test_e_obligation_replayer.py \
  tests/test_e_certified_replay.py \
  tests/test_e_metrics_llm_guided_search.py \
  tests/test_e_proof_search_types.py -q

49 passed in 0.24s
```

本轮完成后的全量测试：

```text
.venv/bin/python -m pytest -q

285 passed in 62.51s (0:01:02)
```

格式检查：

```text
git diff --check -- <modified E-stage files>
```

无输出，表示没有 whitespace error。

## 8. 对照运行

在 `runs/20260514_220733_mechanics73-target-planner-indentfix-no-declcheck-20260514` 中，target proof planner 曾生成可通过 Lean replay 的代数 proof：

```lean
have hden_m1_val___m2_val : m1.val + m2.val ≠ 0 := by
  nlinarith [h_m1_pos, h_m2_pos]
have hT_eq : T.val = m1.val * a.val := by
  linarith [h_mi1_net_force, h_mi1_newton2]
have ha_eq : a.val = m2.val * g.val / (m1.val + m2.val) := by
  field_simp [hden_m1_val___m2_val] at *; nlinarith [h_mi2_net_force, h_mi2_newton2, hT_eq]
have hT_final : T.val = m1.val * m2.val * g.val / (m1.val + m2.val) := by
  field_simp [hden_m1_val___m2_val] at *; nlinarith [hT_eq, ha_eq]
exact ⟨ha_eq, hT_final⟩
```

这个对照说明 target proof planner 路径可以完成 algebraic target proof。但该 proof 未使用 required verified declaration，因此即使 replay 成功，也只能是 gap-assisted / algebra-only 级别，不能标记为 fully MechLib verified。最后一次运行失败后，audit 修复也保证不会再把缺少 required declaration 的代数 fact 误计为 covered obligation。

## 9. 当前结论与限制

本轮核心目标已完成：preflight 失败的 obligations 不再继续喂给 LLM；target mode prompt 已经收缩；LLM fact plan 会被拆成局部 Lean actions 并逐步检查；dependency audit 只统计最终通过 proof body 中的真实 declaration 使用。

最后一次 Mechanics73 未成功关闭 proof，直接原因是 LLM fact plan 的第三个 `have` tactic 触发 `tactic_no_goals`。这是局部 tactic 生成问题，不再是 search state 被无效 extractor 污染的问题。

仍然存在的限制：

1. 当前 `proof_obligations` 仍将 `MechLib.Compat.PHYSlib.SI.newton_second_law` 绑定为 `NewtonSecondLaw ...` predicate 的 extractor，但该 declaration 实际不是 extractor。
2. theorem skeleton 中仍有 value-level 方程 hypotheses，例如 `h_mi1_newton2`、`h_mi2_newton2`。target mode 可以用它们完成代数证明，但不能因此覆盖 MechLib law obligation。
3. target proof planner 目前只做一次 fact-plan expansion；当某个 plan item 因 `tactic_no_goals` 等局部 tactic 形态失败时，还没有对同一 claim 做 tactic repair。

下一步建议：

1. 在 target mode 下加入局部 tactic repair：当 `have claim := by ...` 返回 `tactic_no_goals` 时，允许对同一 claim 重试更短 tactic，例如只保留已关闭目标前的 tactic 或改用 `simpa [hT_eq, ha_eq]` / `nlinarith`。
2. 在 proof obligation synthesis 中区分 `must_use`、`extractor_decl`、`extractor_call_shape` 和 `verified_law_reference`，避免把非 extractor declaration 绑定成 mandatory proof action。
3. 后续清理 minimal theorem skeleton，避免物理定律应用结果提前作为 theorem hypotheses 进入 E 阶段。
