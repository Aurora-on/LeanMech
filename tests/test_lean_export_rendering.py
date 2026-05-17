from mech_pipeline.rendering import _render_problem_lean_file
from mech_pipeline.types import CanonicalSample, SampleRunSummary


def test_verified_lean_export_uses_augmented_theorem_decl_when_present() -> None:
    sample = CanonicalSample(sample_id="s1", source="unit", problem_text="prove x = x", meta={"name": "s1"})
    summary = SampleRunSummary(
        sample_id="s1",
        grounding_ok=True,
        statement_generation_ok=True,
        compile_ok=True,
        semantic_ok=True,
        proof_ok=True,
        end_to_end_ok=True,
        final_error_type=None,
    )
    text = _render_problem_lean_file(
        sample=sample,
        summary=summary,
        candidate_row={
            "candidate_id": "c1",
            "lean_header": "import Mathlib",
            "theorem_decl": "theorem c1 (x : Real) : x = x",
        },
        semantic_row={"selected_candidate_id": "c1"},
        proof_row={"proof_success": True, "attempts_used": 1, "selected_candidate_id": "c1"},
        attempt_row={
            "proof_body": "rfl",
            "proof_search_trace": {
                "augmented_theorem_decl": "theorem c1 (x : Real) (h_x_pos : 0 < x) : x = x"
            },
        },
    )

    assert "theorem c1 (x : Real) (h_x_pos : 0 < x) : x = x := by" in text
    assert "theorem c1 (x : Real) : x = x := by" not in text
