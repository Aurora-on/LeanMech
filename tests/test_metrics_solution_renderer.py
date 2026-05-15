from mech_pipeline.eval.metrics import build_metrics
from mech_pipeline.types import SampleRunSummary


def test_solution_renderer_metrics_are_computed_from_stage_rows():
    summaries = [
        SampleRunSummary(
            sample_id="s1",
            grounding_ok=True,
            statement_generation_ok=True,
            compile_ok=True,
            semantic_ok=True,
            proof_ok=True,
            end_to_end_ok=True,
            final_error_type=None,
        ),
        SampleRunSummary(
            sample_id="s2",
            grounding_ok=True,
            statement_generation_ok=True,
            compile_ok=True,
            semantic_ok=True,
            proof_ok=True,
            end_to_end_ok=True,
            final_error_type=None,
        ),
    ]
    metrics = build_metrics(
        summaries=summaries,
        statement_rows=[],
        grounding_rows=[],
        compile_rows=[],
        semantic_rows=[],
        proof_rows=[],
        stage_rows={
            "natural_solution.jsonl": [
                {"sample_id": "s1", "render_success": True, "proof_status": "fully_mechlib_verified", "natural_solution": "ok"},
                {"sample_id": "s2", "render_success": True, "proof_status": "legacy_verified_no_audit", "natural_solution": "ok"},
            ],
            "solution_render_audit.jsonl": [
                {
                    "sample_id": "s1",
                    "audit_pass": True,
                    "formula_coverage_pass": True,
                    "law_step_coverage_pass": True,
                    "gap_disclosure_pass": True,
                    "proof_status_disclosure_pass": True,
                    "unsupported_formula_count": 0,
                    "details": {"proof_status": "fully_mechlib_verified"},
                },
                {
                    "sample_id": "s2",
                    "audit_pass": True,
                    "formula_coverage_pass": True,
                    "law_step_coverage_pass": True,
                    "gap_disclosure_pass": True,
                    "proof_status_disclosure_pass": True,
                    "unsupported_formula_count": 2,
                    "details": {"proof_status": "legacy_verified_no_audit"},
                },
            ],
            "solution_trace.jsonl": [],
        },
    )
    assert metrics["solution_render_success_rate"] == 1.0
    assert metrics["solution_render_audit_pass_rate"] == 1.0
    assert metrics["solution_verified_trace_rate"] == 0.5
    assert metrics["solution_legacy_no_audit_rate"] == 0.5
    assert metrics["solution_unsupported_formula_avg"] == 1.0
