# E 阶段 LLM-Guided Certified Prover

本文说明 LeanMech 当前 E 阶段从“LLM 一次性生成完整 Lean proof”转向 “LLM-guided certified proof search” 的设计。

## 1. 为什么不再使用 full-proof LLM generation

早期 E 阶段的基本形式是：

```text
theorem statement
  -> LLM proof plan
  -> LLM full proof body
  -> Lean verify
  -> LLM repair
```

这个模式实现简单，但有几个问题：

1. **证明不可控**：LLM 容易跳过物理定律应用步骤，直接写代数 tactic，导致 proof 虽然可能通过，却没有体现 MechLib 的 verified declaration。
2. **难以审计依赖**：完整 proof body 是一次性生成的，系统很难判断每个 proof obligation 是否被覆盖，也难以区分 MechLib theorem、schema metadata 和普通代数事实。
3. **失败反馈粗糙**：Lean 报错通常只对应整段 proof，不能稳定定位是哪一个局部动作失败。
4. **不适合 minimal skeleton**：D 阶段之前已经生成了 `proof_obligations`、`EvidenceBinding` 和 verified extractor declaration，E 阶段应优先消费这些结构化信息，而不是让 LLM 重新猜证明。

因此新的 E 阶段把 LLM 从“完整证明作者”降级为“证明策略控制器”。LLM 仍深度参与，但每个动作都必须由 Lean 检查。

## 2. 为什么不直接接入 Lean Copilot

Lean Copilot 的 tactic suggestion、premise selection 和 proof search 思路与本项目方向相近，但 LeanMech 当前没有直接依赖它，原因是：

1. **本项目需要 MechLib EvidenceBinding**：证明阶段必须显式使用 D/B 前已经绑定好的 verified extractor declaration。
2. **本项目需要 proof obligation audit**：每个 `law_to_equation` / `constraint_to_equation` obligation 都要能追踪是否被覆盖。
3. **schema 不能进入 proof whitelist**：MechLib 中 concept schema、law schema、problem schema 只能用于建模、检索和规划，不能作为 proof fact。
4. **输出需要 pipeline 级诊断**：LeanMech 要落盘 `proof_search_trace.jsonl`、`proof_action_checks.jsonl`、`proof_dependency_audit.jsonl` 和 metrics，供后续实验报告与 failure routing 使用。

因此当前实现是一个 MechCopilot-style prover：参考 LLM-guided tactic search 的思想，但使用 LeanMech 自己的 proof context、action guard、dependency audit 和输出格式。

## 3. LLM 在新 E 阶段中的角色

LLM 不再直接输出完整 proof。它的角色包括：

- **strategy controller**：根据当前 target、local facts、remaining obligations 和 allowed declarations 选择下一步策略。
- **local tactic proposer**：提出一个小的 tactic block，例如一个 `have`、一次 `rw`、一次 `field_simp` + `nlinarith`。
- **subgoal proposer**：在允许时提出局部可验证中间事实。
- **failure diagnosis**：读取上一轮 Lean error excerpt 和 failed action summary，调整下一步策略。

LLM 输入必须是 compact proof state。允许字段包括：

- `target`
- `active_goals`
- `proof_prefix_summary`
- `local_facts`
- `remaining_obligations`
- `required_decls`
- `allowed_decls`
- `decl_candidate_mode`
- `available_strategy_cards`
- `available_algebra_strategy_cards`
- `last_error`
- `failed_actions`

禁止传入：

- 完整 `retrieval_context`
- 完整 `ProblemIR`
- 完整 `StructuredMechLibContext`
- 完整 previous proof attempts
- 完整 theorem corpus
- 长篇自然语言解题过程

prompt 会做长度控制，目标是保持在 8000 字符以内。

当前 prompt 中的 `local_facts` 优先使用 `name : proposition/type` 形式；对 LLM 新增且已被 Lean 接受的 `have`，后续节点会记录该 fact 的命题。正常情况下 `allowed_decls` 会优先收缩到当前 remaining obligations 的 `must_use`，避免把无关 example theorem 作为策略噪声传给 LLM；如果 deterministic extractor preflight 已经证明 `must_use from_hypothesis` 的固定调用形态不成立，prompt 会打开 `decl_candidate_mode`，把 required decl 和其他 allowed verified decl candidates 一并给 LLM，用于局部 proof action synthesis。

## 4. Lean 的角色

Lean 是唯一的证明裁判。新的 E 阶段中，Lean 负责：

1. **validate each action**：每个 LLM 或 deterministic 生成的 local tactic block 都通过 `probe_proof_prefix` 检查。
2. **区分 action 状态**：
   - `closed`：当前 proof prefix 已关闭目标；
   - `progress`：当前 prefix 没有 elaboration error，但仍有未解决 goals；
   - `invalid`：语法、类型、引用或 tactic 失败。
3. **final replay**：即使 probe 返回 `closed`，最终 proof body 仍必须通过 `verify_proof` replay，才算 proof success。

系统禁止使用 `sorry`、`admit`、`axiom` 和 `set_option` 等不受控 escape hatch。

## 5. MechLib 的角色

MechLib 在新 E 阶段中不是普通文本上下文，而是 verified proof source。

关键输入包括：

- **verified extractor declarations**：例如从课程层 predicate 抽取 value-level equation 的 theorem。
- **proof obligations**：由 ControlledSketch / EvidenceBinding 提供，说明必须从哪个 hypothesis 使用哪个 verified declaration 得到哪个 formal claim。
- **allowed verified declarations**：proof whitelist。LLM action 只能使用 whitelist 内的 MechLib declaration。

`proof_obligations[*].produced_fact_name` 只是期望产物名，不是已存在 proof fact。只有 deterministic replay 或 LLM action 经 Lean probe 接受后，该 fact 才能进入后续 local facts / prompt。

典型 obligation：

```json
{
  "kind": "law_to_equation",
  "from_hypothesis": "glider_law",
  "must_use": "MechLib.Dynamics.NewtonLaw.NewtonSecondLaw.to_value_equation",
  "formal_claim": "Fnet1.val = m1.val * a.val",
  "produced_fact_name": "h_obl_glider"
}
```

E 阶段会优先 deterministic replay：

```lean
have h_obl_glider : Fnet1.val = m1.val * a.val := by
  exact MechLib.Dynamics.NewtonLaw.NewtonSecondLaw.to_value_equation glider_law
```

这一步不依赖 LLM 猜测。

## 6. 搜索流程

当前搜索控制器的核心流程是：

```text
ProofContext
  -> deterministic obligation replay
  -> deterministic side-condition proposals
  -> compact proof state
  -> LLM strategy proposals
  -> ActionGuard
  -> Lean probe_proof_prefix
  -> accepted/rejected action trace
  -> final verify_proof replay
  -> DependencyAudit
```

ActionGuard 会拒绝：

- `sorry` / `admit` / `axiom`
- 未授权 MechLib theorem
- schema/problem/concept metadata
- 修改 theorem statement 的命令
- 自然语言或明显 placeholder
- 超长 tactic block

线性 prefix search 还会在 Lean probe 前拒绝 `constructor` 和 `split_conjunction`。当前模式不维护分支子目标状态，因此 conjunction 只能在所有分量事实已经可用时用 `exact ⟨..., ...⟩` 一次性关闭；真正的分支式 `constructor` 需要等 branch-aware search 实现后再放开。

搜索控制器还有独立的 watchdog，避免某个样本长期占用 E 阶段：

- `proof.llm_guided_search.probe_timeout_s`：单次 `probe_proof_prefix` 超时，默认 `120` 秒；只作用于局部 probe，最终 `verify_proof` replay 仍使用 Lean runner 的正常验证路径。
- `proof.llm_guided_search.max_probe_checks`：每个 candidate 最多执行的 Lean prefix probe 次数，默认 `80`。
- `proof.llm_guided_search.max_wall_clock_s_per_sample`：单个 search 的墙钟预算，默认 `1800` 秒。
- `proof.llm_guided_search.max_no_progress_nodes`：连续展开但没有产生可审计进展的节点上限，默认 `12`。

“可审计进展”只在 Lean 接受该 prefix 后计入。Lean 输出中只有 `unsolved goals` 这一类目标未闭合信息时才允许标记为 `progress`；只要同时出现其他 `error:`，例如 `Application type mismatch`、`unknown identifier`、`type mismatch`，该 action 必须标记为 `invalid`。通过该认证边界后，进展条件包括：新增 local fact claim、覆盖剩余 obligation、关闭目标，或 Lean 返回的 goals excerpt 相比父节点发生变化。只更换 `have` 名称但命题相同，不再算作有效进展。完全相同的 proof prefix 会直接标记为 `duplicate_probe_prefix`，不再重复调用 Lean。

同一个 proof prefix 下，已经失败的 LLM action shape 会被记录；如果后续只更换 `have` 名称但 tactic 结构相同，系统会返回 `repeated_failed_action_shape`，不再重复消耗 Lean probe 或继续扩展该无效方向。

无效 action 不能改变 search state。`proof_action_checks.jsonl` 中的 `proposed_local_facts` / `proposed_local_fact_claims` 只是候选动作诊断；只有 accepted action 的 `new_local_facts` / `new_local_fact_claims` 才能进入后续节点。无效 action 也不能覆盖 proof obligation。

deterministic obligation replay 把 `exact must_use from_hypothesis` 作为 extractor preflight。若该 preflight 出现 type/API/symbol 级错误，说明当前固定调用形态不成立，该 action 本身会被标记为 invalid，且不会产生 fact；search 随后进入 LLM local-action synthesis fallback。LLM 只能提出局部 `have` / rewrite / algebra action，仍需经过 ActionGuard、Lean probe 和最终 replay。若 fallback 仍失败，search 会报告 `proof_action_synthesis_failed_after_preflight` 或相应 budget/watchdog failure。

确定性 side-condition action 会在 LLM strategy prompt 前执行；当当前节点存在可执行的 deterministic side-condition proposal 时，本节点不会先消耗一次 LLM call。side-condition 使用 denominator expression 做语义去重，例如已经证明过 `m1.val + m2.val ≠ 0` 后，不会再用不同 `have` 名称重复证明同一 denominator。

## 7. 输出文件说明

### `proof_search_trace.jsonl`

记录每个 sample/candidate 的搜索轨迹摘要：

- `nodes_expanded`
- `llm_calls`
- `probe_checks`
- `search_elapsed_s`
- `accepted_actions`
- `rejected_actions`
- `final_proof_body`
- `search_status`
- `failure_reason`
- `strategy_prompt_summaries`

### `proof_action_checks.jsonl`

记录每个候选动作的 Lean 检查结果：

- `action_id`
- `strategy`
- `tactic_block`
- `source`: `deterministic` 或 `llm`
- `uses_facts`
- `uses_decls`
- `status`: `closed` / `progress` / `invalid`
- `error_type`
- `stderr_excerpt`
- `goals_excerpt`
- `accepted`
- `cache_hit`
- `probe_checks_used`
- `proposed_local_facts`
- `proposed_local_fact_claims`
- `new_local_facts`
- `new_local_fact_claims`
- `covered_obligations`
- `remaining_obligations_after`
- `side_condition_denominator`

常见 E search watchdog 失败类型包括：

- `max_probe_checks_exhausted`
- `wall_clock_budget_exhausted`
- `max_no_progress_nodes_exhausted`
- `duplicate_probe_prefix`
- `no_meaningful_progress`
- `branching_constructor_disallowed_linear_prefix`
- `repeated_failed_action_shape`
- `proof_action_synthesis_failed_after_preflight`

每个样本完成后，orchestrator 会把该样本的 stage rows 追加写入 run directory 的 JSONL 文件。完整运行结束时仍会由最终 writer 覆盖生成一致的聚合文件；如果运行被某个后续样本卡住或中断，已完成样本的 `proof_attempts.jsonl`、`proof_checks.jsonl` 和 trace/audit rows 仍可用于诊断。

### `proof_strategy_prompts.jsonl`

记录 compact prompt summary，而不是完整 prompt 或长上下文：

- `prompt_chars`
- `target_excerpt`
- `active_goals_excerpt`
- `proof_prefix_excerpt`
- `local_facts`
- `remaining_obligations`
- `allowed_decls`
- `decl_candidate_mode`
- `failed_action_count`
- `prompt_excerpt`
- `omitted_context`

`omitted_context` 会明确标记未保存的长上下文，例如完整 retrieval context、完整 ProblemIR、完整 theorem corpus。

### `proof_dependency_audit.jsonl`

记录最终 proof 是否真正使用了 MechLib verified declarations：

- `used_verified_decls`
- `required_verified_decls`
- `missing_required_decls`
- `covered_obligations`
- `missing_obligations`
- `gap_assisted`
- `fully_mechlib_verified`
- `classification`

分类包括：

- `fully_mechlib_verified`
- `partial_mechlib_verified`
- `gap_assisted_success`
- `algebra_only_success`
- `proof_failed`

## 8. 指标说明

E 阶段新增指标包括：

- `llm_guided_search_enabled_rate`：进入新 search prover 的 proof attempt 比例。
- `obligation_replay_success_rate`：成功 replay 的 obligation / required obligations。
- `proof_obligation_coverage_rate`：最终 proof 覆盖的 obligation / required obligations。
- `verified_decl_use_rate`：使用至少一个 required extractor declaration 的 proof 比例。
- `fully_mechlib_verified_proof_rate`：分类为 `fully_mechlib_verified` 的 proof 比例。
- `partial_mechlib_verified_proof_rate`：分类为 `partial_mechlib_verified` 的 proof 比例。
- `gap_assisted_success_rate`：依赖 explicit gap law 的成功比例。
- `algebra_only_success_rate`：final replay 通过但未使用 required MechLib declaration 的比例。
- `llm_strategy_success_rate`：search trace 成功比例。
- `valid_llm_action_rate`：LLM accepted actions / LLM proposals。
- `invalid_llm_action_rate`：LLM invalid actions / LLM proposals。
- `missing_side_condition_rate`：缺少 side condition 的 action 比例。
- `average_llm_calls_per_proof`：每个 proof 的平均 LLM strategy calls。
- `average_lean_action_checks_per_proof`：每个 proof 的平均 Lean action checks。

这些指标用于区分“Lean proof 通过”和“MechLib 支撑的 verified proof 通过”。后者才是后续 pipeline 证明质量提升的核心指标。

## 9. 当前限制

当前实现仍有几个保守限制：

1. DependencyAudit 主要基于 proof body 文本检查 required declaration 和 produced fact，尚未从 Lean proof term 中抽取真实 used constants。
2. SideConditionAnalyzer 先支持简单分母和正性事实，尚未做 Lean AST 级分析。
3. SearchController 是初版 best-first/beam 风格搜索，不是完整 MCTS。
4. legacy full-proof 模式仍保留作显式对照；自动 legacy fallback 默认关闭。若通过配置显式开启 fallback，fallback proof 也不自动标记为 `fully_mechlib_verified`。

后续改进方向是从 Lean replay 中导出真实依赖、增强 proof state parsing，并把 `missing_side_condition` 回传到前段 failure routing。
