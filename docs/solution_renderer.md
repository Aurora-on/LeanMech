# SolutionRenderer

`SolutionRenderer` 是 E 阶段之后的单模块可读解题流程出口。它不改变 theorem skeleton 生成、proof search、legacy proof fallback 或 Lean replay 逻辑，只把已经形成的结构化求解结果转成中文自然语言说明，并写入可审计 artifact。

## 为什么不直接翻译 Lean proof

Lean proof 是验证脚本，不等同于教学式力学解题过程。逐行翻译 proof body 容易把 `rw`、`linarith`、局部 fact 名称误写成物理推理，也可能把 proof 中只用于代数闭合的辅助关系说成新的物理定律。因此 `SolutionRenderer` 不依赖完整 Lean proof 逐行翻译，只使用结构化 trace 中已经整理过的步骤、公式和验证状态。

## ControlledSketch 的角色

`ControlledSketch` 可以作为叙述骨架，因为它记录了计划中的 `law_to_equation` / `constraint_to_equation` 和至多一个 `algebra_obligation`。但它不是最终 verified fact 来源：

- `proof_steps` 只说明“计划如何讲”。
- `blocked_law_steps`、`gap_steps`、`gap_schema_only` 不能写成已验证物理规律。
- sketch 中的公式只有被 E 阶段 proof trace、proof check 或 dependency audit 覆盖时，才可在自然语言中标为已验证。

核心原则：

```text
ControlledSketch 决定怎么讲；
ProofSearchTrace / ProofCheck / DependencyAudit 决定能不能讲；
LLM 负责讲得通顺，不负责重新求解。
```

## 验证状态来源

`SolutionRenderer` 优先消费：

- `ProofDependencyAudit.classification`
- `ProofDependencyAudit.covered_obligations`
- `ProofSearchTrace.accepted_actions`
- `ProofCheckResult.proof_success`
- `ProofAttemptResult.proof_mode`

如果 trace/audit 为空，模块会保守退回 `ProofAttemptResult` 和 `ProofCheckResult`。legacy proof 成功但没有 dependency audit 时，状态为 `legacy_verified_no_audit`，不能标记为 `fully_mechlib_verified`。

## LLM 的角色

LLM 只用于中文表达：

- 不重新解题。
- 不新增公式。
- 不新增物理定律。
- 不修改最终答案。
- 不隐藏 gap、partial、legacy/no-audit 或 proof_failed 状态。
- 输入只包含 compact `SolutionTrace`，不包含完整 Lean proof、完整 MechLib context、完整 theorem corpus 或完整 raw response。

默认配置 `solution_renderer.natural_language_enabled=false`，因此无 LLM 时也会生成 deterministic fallback。

## SolutionTrace

`SolutionTrace` 是自然语言渲染的唯一事实源，包含：

- `sample_id`
- `candidate_id`
- `proof_status`
- `target_formal`
- `target_display`
- `steps`
- `final_answers`
- `warnings`
- `source_status`

每个 `SolutionStep` 记录 step kind、标题、公式、来源 artifact、关联 obligation、verified declaration、proof action 和验证状态。每个 `SolutionFormula` 保留 `formal_formula`，并由代码生成 `display_formula`。

## Natural Solution

`natural_solution.jsonl` 保存每个样本的可读解题流程摘要，包括：

- `render_success`
- `proof_status`
- `natural_solution`
- `render_audit_pass`
- `error`

自然语言解题流程应包含题意与符号说明、建模与物理定律应用、联立方程/代数求解、最终答案和形式化验证说明。

## RenderAudit

`SolutionRenderAudit` 检查：

- final answer coverage
- verified law step coverage
- unsupported formula detection
- gap / partial disclosure
- legacy no-audit disclosure
- proof failed disclosure
- target match

若 audit fail 且启用 LLM，模块最多修订一次；修订仍只能基于同一个 `SolutionTrace`。

## 输出文件

E 阶段后新增：

- `solution_trace.jsonl`
- `natural_solution.jsonl`
- `solution_render_audit.jsonl`

这些文件会写入 `runs/<run>/`，并通过 archive writer 同步到 `outputs/latest/`。

## proof_status 分类

- `fully_mechlib_verified`：dependency audit 确认 required verified declarations 和 obligations 覆盖。
- `partial_mechlib_verified`：部分 MechLib 覆盖，仍有缺口。
- `gap_assisted_success`：proof 成功但依赖 gap law。
- `algebra_only_success`：主要证明代数目标，缺少必要 MechLib verified declaration 覆盖。
- `legacy_verified_no_audit`：legacy proof 通过，但缺少 dependency audit。
- `proof_failed`：Lean proof 未通过。
- `proof_skipped_due_to_semantic_fail`：语义阶段失败，proof 被跳过。
- `not_checked`：缺少足够 proof/check 信息。
