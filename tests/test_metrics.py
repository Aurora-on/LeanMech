from __future__ import annotations

from mech_pipeline.eval.metrics import build_metrics
from mech_pipeline.types import CompileCheckResult, GroundingResult, SampleRunSummary, SemanticRankResult


def test_lean_compile_success_rate_is_sample_level_on_final_round() -> None:
    summaries = [
        SampleRunSummary(
            sample_id="s1",
            grounding_ok=True,
            statement_generation_ok=True,
            compile_ok=True,
            semantic_ok=False,
            proof_ok=False,
            end_to_end_ok=False,
            final_error_type="semantic_drift",
            final_round_index=1,
        ),
        SampleRunSummary(
            sample_id="s2",
            grounding_ok=True,
            statement_generation_ok=True,
            compile_ok=False,
            semantic_ok=False,
            proof_ok=False,
            end_to_end_ok=False,
            final_error_type="elaboration_failure",
            final_round_index=0,
        ),
    ]
    grounding_rows = [
        GroundingResult(sample_id="s1", model_id="m", problem_ir={}, parse_ok=True, raw_response="", error=None),
        GroundingResult(sample_id="s2", model_id="m", problem_ir={}, parse_ok=True, raw_response="", error=None),
    ]
    compile_rows = [
        CompileCheckResult(
            sample_id="s1",
            candidate_id="c1",
            compile_pass=False,
            syntax_ok=False,
            elaboration_ok=False,
            error_type="elaboration_failure",
            stderr_digest="bad",
            log_path=None,
            round_index=1,
        ),
        CompileCheckResult(
            sample_id="s1",
            candidate_id="c2",
            compile_pass=True,
            syntax_ok=True,
            elaboration_ok=True,
            error_type=None,
            stderr_digest="",
            log_path=None,
            round_index=1,
        ),
        CompileCheckResult(
            sample_id="s1",
            candidate_id="stale",
            compile_pass=False,
            syntax_ok=False,
            elaboration_ok=False,
            error_type="elaboration_failure",
            stderr_digest="stale",
            log_path=None,
            round_index=0,
        ),
        CompileCheckResult(
            sample_id="s2",
            candidate_id="c1",
            compile_pass=False,
            syntax_ok=False,
            elaboration_ok=False,
            error_type="elaboration_failure",
            stderr_digest="bad",
            log_path=None,
            round_index=0,
        ),
        CompileCheckResult(
            sample_id="s2",
            candidate_id="c2",
            compile_pass=False,
            syntax_ok=False,
            elaboration_ok=False,
            error_type="elaboration_failure",
            stderr_digest="bad",
            log_path=None,
            round_index=0,
        ),
    ]

    metrics = build_metrics(
        summaries=summaries,
        statement_rows=[],
        grounding_rows=grounding_rows,
        compile_rows=compile_rows,
        semantic_rows=[],
        proof_rows=[],
    )

    assert metrics["lean_compile_success_rate"] == 0.5


def test_compile_and_semantic_rates_use_total_sample_denominator() -> None:
    summaries = [
        SampleRunSummary(
            sample_id="s1",
            grounding_ok=True,
            statement_generation_ok=True,
            compile_ok=True,
            semantic_ok=True,
            proof_ok=False,
            end_to_end_ok=False,
            final_error_type=None,
            final_round_index=0,
        ),
        SampleRunSummary(
            sample_id="s2",
            grounding_ok=True,
            statement_generation_ok=True,
            compile_ok=False,
            semantic_ok=False,
            proof_ok=False,
            end_to_end_ok=False,
            final_error_type="elaboration_failure",
            final_round_index=0,
        ),
        SampleRunSummary(
            sample_id="s3",
            grounding_ok=True,
            statement_generation_ok=False,
            compile_ok=False,
            semantic_ok=False,
            proof_ok=False,
            end_to_end_ok=False,
            final_error_type="statement_generation_failure",
            final_round_index=0,
        ),
    ]
    grounding_rows = [
        GroundingResult(sample_id=f"s{i}", model_id="m", problem_ir={}, parse_ok=True, raw_response="", error=None)
        for i in range(1, 4)
    ]
    compile_rows = [
        CompileCheckResult(
            sample_id="s1",
            candidate_id="c1",
            compile_pass=True,
            syntax_ok=True,
            elaboration_ok=True,
            error_type=None,
            stderr_digest="",
            log_path=None,
            round_index=0,
        )
    ]
    semantic_rows = [
        SemanticRankResult(
            sample_id="s1",
            selected_candidate_id="c1",
            selected_theorem_decl="theorem c : True",
            semantic_pass=True,
            ranking=[{"candidate_id": "c1", "semantic_pass": True}],
            round_index=0,
        )
    ]

    metrics = build_metrics(
        summaries=summaries,
        statement_rows=[],
        grounding_rows=grounding_rows,
        compile_rows=compile_rows,
        semantic_rows=semantic_rows,
        proof_rows=[],
    )

    assert metrics["lean_compile_success_rate"] == 0.333333
    assert metrics["semantic_consistency_pass_rate"] == 0.333333
