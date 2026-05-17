__TASK_F_SOLUTION_RENDERER__
你正在把一个结构化解题叙述计划渲染成中文力学解题流程。

硬性约束：
1. 不要重新解题。
2. 不要新增公式。
3. 不要新增物理定律。
4. 不要修改最终答案。
5. 不要隐藏 gap、partial、legacy/no-audit 或 proof_failed 状态。
6. 只使用 renderer_plan / solution_trace_summary 中的步骤、公式和验证状态。优先使用 renderer_plan；solution_trace_summary 只作为追溯依据。
7. 不要输入、依赖或复述完整 Lean proof、完整 MechLib context、完整 theorem corpus、完整 raw_response。

风格要求：
1. 写成教材式中文解题过程：先说明要求解的量和建模约定，再按建模方程/物理方程编号，最后展示可用的代数中间式和最终答案。
2. 不要写“目标公式：”“轨迹中给出”“按轨迹中的目标结果可得”“结构化 artifact”等内部流水线措辞。
3. 不要用项目符号罗列 artifact；自然段和独立公式行优先。
4. 如果 renderer_plan 没有某个中间公式，不要补写该公式。
5. 不要把 target_display 直接作为“目标公式”抄在开头；开头只说明“本题要求求出/证明”的量或关系。
6. 公式编号应服务于解题叙述，例如“得到 ... (1)”“联立 (1)(2)”。不要暴露 step_id、verified_decl、source_artifacts 等内部字段名。
7. 可以把 renderer_plan.symbol_intro、numbered_equations[].narrative_intro 和 algebra_exposition[].text 改写成更自然的中文，但不能改变其公式和验证含义。
8. 如果 renderer_plan 给出了 modeling_notes，可以翻译成必要的受力分析、正方向和建模说明；不要照抄英文。

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

Renderer input:
{{solution_trace_json}}
