__TASK_F_SOLUTION_RENDERER__
你正在把一个结构化解题轨迹渲染成中文力学解题流程。

硬性约束：
1. 不要重新解题。
2. 不要新增公式。
3. 不要新增物理定律。
4. 不要修改最终答案。
5. 不要隐藏 gap、partial、legacy/no-audit 或 proof_failed 状态。
6. 只使用 SolutionTrace 中的步骤、公式和验证状态。
7. 不要输入、依赖或复述完整 Lean proof、完整 MechLib context、完整 theorem corpus、完整 raw_response。

风格要求：
1. 写成教材式中文解题过程：先设符号和正方向，再分对象受力分析并编号方程，最后联立消元。
2. 不要写“目标公式：”“轨迹中给出”“按轨迹中的目标结果可得”“结构化 artifact”等内部流水线措辞。
3. 不要用项目符号罗列 artifact；自然段和独立公式行优先。
4. 如果 SolutionTrace 没有某个中间公式，不要补写该公式。

输出内容必须包含：
1. 题意与符号说明
2. 建模与物理定律应用
3. 联立方程/代数求解
4. 最终答案
5. 形式化验证说明

验证状态说明规则：
- proof_status=fully_mechlib_verified 时，可以写“上述物理定律应用和代数推导均已由 Lean 验证。”
- proof_status=legacy_verified_no_audit 时，必须写“本题 Lean proof 已通过，但当前缺少 dependency audit，不能确认所有物理步骤均由 MechLib verified declaration 覆盖。”
- proof_status=gap_assisted_success 时，必须写“其中部分建模关系依赖 gap law，不能计为 fully MechLib verified。”
- proof_status=proof_failed 时，必须写“当前形式化证明未通过，因此以下只展示已构造的建模和计划步骤，不作为最终 verified solution。”
- 其他 partial/algebra_only/not_checked/skipped 状态也必须明确披露，不能写成 fully MechLib verified。

返回 JSON，不要输出 JSON 以外的文字：
{
  "natural_solution": "...",
  "used_step_ids": ["..."],
  "mentioned_formulas": ["..."],
  "verification_note": "..."
}

SolutionTrace:
{{solution_trace_json}}
