from mech_pipeline.modules.solution_renderer import audit_rendered_solution
from mech_pipeline.types import SolutionFormula, SolutionStep, SolutionTrace


def _trace(status="fully_mechlib_verified"):
    formula = SolutionFormula("ans", "mu_s.val = F_start.val / W.val", "μ_s = F_start / W", verified=True)
    step = SolutionStep(
        step_id="sk1",
        kind="law_application",
        title="应用物理定律",
        formal_formula="F_start.val = mu_s.val * W.val",
        display_formula="F_start = μ_s W",
        verified_decl="MechLib.Friction.staticFrictionMax",
        verified=status == "fully_mechlib_verified",
    )
    return SolutionTrace(
        sample_id="s1",
        candidate_id="c1",
        proof_status=status,
        target_formal=formula.formal_formula,
        target_display=formula.display_formula,
        steps=[step],
        final_answers=[formula],
    )


def test_fully_verified_solution_with_final_answer_passes():
    natural = "应用物理定律得到 F_start = μ_s W。最终答案 μ_s = F_start / W。上述物理定律应用和代数推导均已由 Lean 验证。"
    audit = audit_rendered_solution(solution_trace=_trace(), natural_solution=natural, llm_payload={})
    assert audit.audit_pass is True


def test_gap_assisted_without_gap_disclosure_fails():
    natural = "最终答案 μ_s = F_start / W。"
    audit = audit_rendered_solution(solution_trace=_trace("gap_assisted_success"), natural_solution=natural, llm_payload={})
    assert audit.audit_pass is False
    assert "gap_or_partial_not_disclosed" in audit.failure_tags


def test_legacy_no_audit_overclaim_fails():
    natural = "最终答案 μ_s = F_start / W。上述物理定律应用和代数推导均已由 Lean 验证。"
    audit = audit_rendered_solution(solution_trace=_trace("legacy_verified_no_audit"), natural_solution=natural, llm_payload={})
    assert audit.audit_pass is False
    assert "legacy_no_audit_not_disclosed" in audit.failure_tags or "legacy_no_audit_overclaimed" in audit.failure_tags


def test_trace_external_formula_warns_or_fails():
    natural = "最终答案 μ_s = F_start / W。额外公式 x = y。上述物理定律应用和代数推导均已由 Lean 验证。"
    audit = audit_rendered_solution(solution_trace=_trace(), natural_solution=natural, llm_payload={})
    assert audit.audit_pass is False
    assert audit.unsupported_formula_count >= 1


def test_proof_failed_cannot_claim_lean_verified():
    natural = "最终答案 μ_s = F_start / W。上述结论已由 Lean 验证。"
    audit = audit_rendered_solution(solution_trace=_trace("proof_failed"), natural_solution=natural, llm_payload={})
    assert audit.audit_pass is False
    assert "failed_proof_overclaimed" in audit.failure_tags


def test_multi_final_answer_requires_each_formula():
    trace = _trace("proof_failed")
    trace.final_answers.append(
        SolutionFormula(
            "ans2",
            "T.val = (m1.val * m2.val * g.val) / (m1.val + m2.val)",
            "T = m₁ m₂ g / (m₁ + m₂)",
            verified=False,
        )
    )
    natural = "最终答案 a = m₂ g / (m₁ + m₂)。当前形式化证明未通过，因此以下只展示已构造的建模和计划步骤，不作为最终 verified solution。"

    audit = audit_rendered_solution(solution_trace=trace, natural_solution=natural, llm_payload={})

    assert audit.audit_pass is False
    assert "final_answer_missing" in audit.failure_tags
