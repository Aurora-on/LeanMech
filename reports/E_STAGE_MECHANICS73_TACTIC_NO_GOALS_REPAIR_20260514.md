# Mechanics73 E 阶段 tactic_no_goals Repair 修改与复测报告

- 运行目录：`/Users/weizhixin/AI4Mechanics/LeanMech/runs/20260514_232245_mechanics73-no-goals-repair-20260514`
- latest 镜像：`/Users/weizhixin/AI4Mechanics/LeanMech/outputs/latest`
- 样本：`lean4phys-university_mechanics_Mechanics_73_University`
- 运行命令：`.venv/bin/python -m mech_pipeline.cli run --config tmp/minimal_mechanics73_single_no_declcheck_20260514.yaml --tag mechanics73-no-goals-repair-20260514 --sample-concurrency 1`
- 数据来源：`sample_summary.jsonl`、`proof_search_trace.jsonl`、`proof_strategy_prompts.jsonl`、`proof_action_checks.jsonl`、`proof_dependency_audit.jsonl`、`proof_checks.jsonl`、`metrics.json`
- 复测前提：本次仍使用 `knowledge.lean_check_decls=false` 的 Mechanics73 小规模配置，以避免前置 evidence declaration `#check` 成为主要耗时；E 阶段 Lean probe、final replay 和 dependency audit 未跳过。

## 1. 修改目的

上一次 Mechanics73 run 中，LLM fact plan 已经推出 `ha_eq`，但当前 plan item：

```lean
have hT_final : T.val = m1.val * m2.val * g.val / (m1.val + m2.val) := by
  rw [hT_eq, ha_eq]
  field_simp [hden_m1_val___m2_val]
  ring_nf
```

被 Lean 判定为：

```text
No goals to be solved
```

旧行为会把整个 action 标为 invalid，然后丢掉该 fact-plan node。这样会丢失已经成功的 prefix 和 local facts，只因为当前 claim 的 tactic body 多写了尾部 tactic。

本轮修改目标：

1. 对 `have h : claim := by ...` 形态的 `tactic_no_goals` 做局部 repair。
2. repair 只截短当前 `have` 的 tactic body，不改变 theorem、claim、local facts 或前序 prefix。
3. fact plan item 失败后，优先修当前 claim；repair 成功后继续执行原 fact plan 剩余动作。

## 2. 机制改动

### 2.1 tactic_no_goals repair

新增处理逻辑位于 `src/mech_pipeline/modules/e_search_controller.py`。

当原 action：

```lean
have h : claim := by
  tactic1
  tactic2
  tactic3
```

返回 `tactic_no_goals` 或 stderr/message 中包含 `No goals to be solved` 时，E search 会生成 deterministic repair candidates：

```lean
have h : claim := by
  tactic1
  tactic2
```

然后：

```lean
have h : claim := by
  tactic1
```

repair 顺序是删除最少尾部 tactic 优先。每个 repair candidate 仍经过 action guard、Lean probe 和最终 replay 链路；没有任何 repair 会被直接信任。

### 2.2 保留当前 node

repair 使用当前 node 的：

- `proof_prefix`
- `local_facts`
- `local_fact_claims`
- `local_fact_types`
- `remaining_obligations`
- `planned_actions`

因此已接受的前序 facts 不会被丢掉。repair action 成功后，child node 会继续携带原 action 对应的 `plan_remainders`，也就是继续执行同一个 fact plan 的后续 close/action。

### 2.3 Trace 标记

原失败 action 会保留在 `rejected_actions`，并增加：

| 字段 | 含义 |
| --- | --- |
| `repair_attempted` | 是否触发 repair |
| `repair_action_ids` | 尝试过的 repair action id |
| `repair_strategy` | 当前为 `drop_trailing_tactics_on_no_goals` |
| `repair_accepted_action_id` | 若 repair 成功，记录被接受的 repair action |

repair action 自身若 accepted，会进入 `accepted_actions`，并带有：

| 字段 | 含义 |
| --- | --- |
| `repair_of` | 原始失败 action id |
| `repair_kind` | repair 类型 |
| `repair_prefix_len` | 保留 tactic 行数 |
| `repair_original_tactic_count` | 原始 tactic 行数 |
| `repair_dropped_tactics` | 被删除的尾部 tactic |

## 3. 回归测试

新增测试：

```text
test_search_controller_repairs_fact_plan_tactic_no_goals_without_dropping_prefix
```

测试场景：

1. LLM 返回一个两步 fact plan：先证明 `h_one`，再证明 `h_final`。
2. `h_final` 的原 tactic body 为三行，模拟 Lean 返回 `tactic_no_goals`。
3. 第一次 repair 保留两行仍失败。
4. 第二次 repair 只保留第一行，通过 Lean probe。
5. E search 继续执行原 fact plan 的 close action。
6. 最终 trace 成功，并且 final proof body 同时保留 `h_one` 和 repaired `h_final`。

目标测试：

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

50 passed in 0.62s
```

全量测试：

```text
.venv/bin/python -m pytest -q

286 passed in 265.20s (0:04:25)
```

格式检查：

```text
git diff --check -- src/mech_pipeline/modules/e_search_controller.py tests/test_e_search_controller_basic.py
```

无输出，表示没有 whitespace error。

## 4. Mechanics73 最后一次 E 流程

### 4.1 总览

| 字段 | 值 |
| --- | --- |
| proof_ok | True |
| end_to_end_ok | True |
| search_status | success |
| search_mode | target_proof_from_available_facts |
| failure_reason |  |
| llm_calls | 1 |
| nodes_expanded | 6 |
| probe_checks | 7 |
| latest mirror check | `outputs/latest` 与本 run 的 `sample_summary.jsonl`、`proof_search_trace.jsonl` 一致 |

本次真实 API run 没有触发 `tactic_no_goals` repair，因为 LLM 生成的 `hT_final` tactic 是：

```lean
field_simp [hden_m1_val___m2_val] at *; nlinarith [hT_eq, ha_final]
```

该 action 直接通过 Lean probe。repair 机制由上述单元测试覆盖。

### 4.2 Blocked obligations

preflight 仍然把两个 law obligations 标记为 blocked：

| obligation_id | must_use | reason |
| --- | --- | --- |
| sk1 | `MechLib.Compat.PHYSlib.SI.newton_second_law` | `missing_proof_friendly_extractor` |
| sk2 | `MechLib.Examples.FinalTheoremDemos.newtonSecondLaw_byDefinition` | `missing_proof_friendly_extractor` |

因此 E 阶段进入：

```text
target_proof_from_available_facts
```

### 4.3 Accepted actions

| row | source | strategy | new facts |
| --- | --- | --- | --- |
| 1 | deterministic | augment_physical_positive_hypotheses | `h_m1_pos`, `h_m2_pos` |
| 2 | deterministic | prove_side_condition | `hden_m1_val___m2_val` |
| 3 | LLM fact plan | target_fact_plan_have | `hT_eq` |
| 4 | LLM fact plan | target_fact_plan_have | `ha_final` |
| 5 | LLM fact plan | target_fact_plan_have | `hT_final` |
| 6 | LLM fact plan | target_fact_plan_close |  |

Final proof body：

```lean
have hden_m1_val___m2_val : m1.val + m2.val ≠ 0 := by
  nlinarith [h_m1_pos, h_m2_pos]
have hT_eq : T.val = m1.val * a.val := by
  linarith [h_net_force_mi1, h_newton2_mi1]
have ha_final : a.val = (m2.val * g.val) / (m1.val + m2.val) := by
  field_simp [hden_m1_val___m2_val] at *; nlinarith [hT_eq, h_net_force_mi2, h_newton2_mi2]
have hT_final : T.val = (m1.val * m2.val * g.val) / (m1.val + m2.val) := by
  field_simp [hden_m1_val___m2_val] at *; nlinarith [hT_eq, ha_final]
exact ⟨ha_final, hT_final⟩
```

### 4.4 Rejected actions

本次 rejected actions 只有两个 deterministic preflight failures：

| action_id | strategy | error_type |
| --- | --- | --- |
| sk1_1 | deterministic_exact_extractor | type_mismatch |
| sk2_1 | deterministic_exact_extractor | type_mismatch |

没有 LLM action 被拒绝。

## 5. Dependency Audit

| 字段 | 值 |
| --- | --- |
| proof_success | True |
| used_verified_decls |  |
| required_verified_decls | `MechLib.Compat.PHYSlib.SI.newton_second_law`, `MechLib.Examples.FinalTheoremDemos.newtonSecondLaw_byDefinition` |
| missing_required_decls | `MechLib.Compat.PHYSlib.SI.newton_second_law`, `MechLib.Examples.FinalTheoremDemos.newtonSecondLaw_byDefinition` |
| covered_obligations |  |
| missing_obligations | sk1, sk2 |
| fully_mechlib_verified | False |
| gap_assisted | True |
| algebra_only | True |
| classification | gap_assisted_success |

该分类符合预期：最终 Lean replay 成功，但 proof body 没有使用 required verified declarations，也没有覆盖 law obligations，因此不能标记为 fully MechLib verified。

## 6. Metrics 摘要

| 指标 | 值 |
| --- | ---: |
| proof_success_rate | 1.0 |
| end_to_end_verified_solve_rate | 1.0 |
| fully_mechlib_verified_proof_rate | 0.0 |
| gap_assisted_success_rate | 1.0 |
| algebra_only_success_rate | 0.0 |
| valid_llm_action_rate | 1.0 |
| invalid_llm_action_rate | 0.0 |
| average_llm_calls_per_proof | 1.0 |
| average_lean_action_checks_per_proof | 8.0 |

注意：`metrics.json` 中 `algebra_only_success_rate=0.0`，但 dependency audit row 标记 `algebra_only=true` 且 `classification=gap_assisted_success`。这说明当前 aggregate metric 对 `algebra_only_success_rate` 的统计口径可能仍需要单独审查。

## 7. 当前结论

本轮修复完成了两个目标：

1. `tactic_no_goals` 不再直接导致 fact-plan node 丢失；系统会局部截短当前 `have` 的 tactic body，并用 Lean probe 验证 repair。
2. repair 成功后会保留已接受 prefix、local facts 和 plan remainder，继续执行后续 fact-plan action。

最后一次 Mechanics73 run 通过了最终 Lean replay，但仍是 `gap_assisted_success`。根本原因没有改变：当前 proof obligations 仍绑定到不能从 `mi*_law` predicate hypothesis 直接推出方程的 declarations，E 阶段只能从 theorem hypotheses 中已有的 value-level equations 完成代数 target proof。

下一步建议：

1. 为 `tactic_no_goals` repair 增加真实 trace 统计字段，例如 `repair_attempt_rate`、`repair_success_rate`。
2. 审查 `algebra_only_success_rate` 的 aggregate 计算，确保与 per-sample dependency audit 分类一致。
3. 继续修 proof obligation synthesis，区分 `verified_law_reference` 与真正可调用的 `extractor_decl` / `extractor_call_shape`。
