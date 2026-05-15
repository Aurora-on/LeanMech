import json

from mech_pipeline.types import (
    SolutionFormula,
    SolutionRenderAudit,
    SolutionRenderResult,
    SolutionStep,
    SolutionTrace,
)


def test_solution_renderer_types_json_roundtrip():
    formula = SolutionFormula("f1", "a.val = g.val", display_formula="a = g", verified=True)
    step = SolutionStep(
        step_id="s1",
        kind="law_application",
        title="应用物理定律",
        output_formulas=[formula],
        verified=True,
    )
    trace = SolutionTrace(
        sample_id="sample_1",
        candidate_id="cand_1",
        proof_status="fully_mechlib_verified",
        target_formal="a.val = g.val",
        target_display="a = g",
        steps=[step],
        final_answers=[formula],
    )
    audit = SolutionRenderAudit(
        sample_id="sample_1",
        candidate_id="cand_1",
        render_success=True,
        audit_pass=True,
        formula_coverage_pass=True,
        law_step_coverage_pass=True,
        target_match_pass=True,
    )
    result = SolutionRenderResult(
        sample_id="sample_1",
        candidate_id="cand_1",
        render_success=True,
        proof_status="fully_mechlib_verified",
        solution_trace=trace,
        natural_solution="a = g",
        render_audit=audit,
    )

    payload = json.loads(json.dumps(result.to_dict(), ensure_ascii=False))
    assert payload["solution_trace"]["steps"][0]["output_formulas"][0]["display_formula"] == "a = g"
    assert payload["render_audit"]["audit_pass"] is True
