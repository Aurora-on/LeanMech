from __future__ import annotations

from mech_pipeline.eval.metrics import build_metrics
from mech_pipeline.types import SampleRunSummary


def _summary(sample_id: str) -> SampleRunSummary:
    return SampleRunSummary(
        sample_id=sample_id,
        grounding_ok=True,
        statement_generation_ok=True,
        compile_ok=True,
        semantic_ok=True,
        proof_ok=True,
        end_to_end_ok=True,
        final_error_type=None,
    )


def test_llm_guided_search_metrics_from_stage_rows() -> None:
    stage_rows = {
        "proof_attempts.jsonl": [
            {
                "sample_id": "s1",
                "attempt_index": 1,
                "proof_mode": "llm_guided_search",
                "strict_pass": True,
            },
            {
                "sample_id": "s2",
                "attempt_index": 1,
                "proof_mode": "llm_guided_search",
                "strict_pass": True,
            },
        ],
        "proof_search_trace.jsonl": [
            {"sample_id": "s1", "candidate_id": "c1", "search_status": "success", "llm_calls": 2},
            {"sample_id": "s2", "candidate_id": "c2", "search_status": "failed", "llm_calls": 4},
        ],
        "proof_action_checks.jsonl": [
            {"sample_id": "s1", "source": "llm", "accepted": True, "status": "progress"},
            {"sample_id": "s1", "source": "llm", "accepted": False, "status": "invalid"},
            {
                "sample_id": "s2",
                "source": "deterministic",
                "accepted": False,
                "status": "invalid",
                "strategy": "missing_side_condition",
                "error_type": "missing_side_condition",
            },
        ],
        "proof_dependency_audit.jsonl": [
            {
                "sample_id": "s1",
                "classification": "fully_mechlib_verified",
                "used_verified_decls": ["decl1"],
                "required_verified_decls": ["decl1"],
                "covered_obligations": ["obl1"],
                "missing_obligations": [],
            },
            {
                "sample_id": "s2",
                "classification": "partial_mechlib_verified",
                "used_verified_decls": ["decl2"],
                "required_verified_decls": ["decl2", "decl3"],
                "covered_obligations": ["obl2"],
                "missing_obligations": ["obl3"],
            },
        ],
    }

    metrics = build_metrics(
        summaries=[_summary("s1"), _summary("s2")],
        statement_rows=[],
        grounding_rows=[],
        compile_rows=[],
        semantic_rows=[],
        proof_rows=[],
        proof_attempt_rows=stage_rows["proof_attempts.jsonl"],
        stage_rows=stage_rows,
    )

    assert metrics["llm_guided_search_enabled_rate"] == 1.0
    assert metrics["obligation_replay_success_rate"] == 0.666667
    assert metrics["proof_obligation_coverage_rate"] == 0.666667
    assert metrics["verified_decl_use_rate"] == 1.0
    assert metrics["fully_mechlib_verified_proof_rate"] == 0.5
    assert metrics["partial_mechlib_verified_proof_rate"] == 0.5
    assert metrics["llm_strategy_success_rate"] == 0.5
    assert metrics["valid_llm_action_rate"] == 0.5
    assert metrics["invalid_llm_action_rate"] == 0.5
    assert metrics["missing_side_condition_rate"] == 0.333333
    assert metrics["physical_assumption_augmentation_rate"] == 0.0
    assert metrics["augmented_theorem_compile_success_rate"] == 0.0
    assert metrics["average_llm_calls_per_proof"] == 3.0
    assert metrics["average_lean_action_checks_per_proof"] == 1.5


def test_llm_guided_search_metrics_count_classifications() -> None:
    stage_rows = {
        "proof_attempts.jsonl": [
            {"sample_id": "s1", "proof_mode": "llm_guided_search"},
            {"sample_id": "s2", "proof_mode": "llm_guided_search"},
        ],
        "proof_dependency_audit.jsonl": [
            {
                "sample_id": "s1",
                "classification": "gap_assisted_success",
                "used_verified_decls": ["decl1"],
                "required_verified_decls": ["decl1"],
                "covered_obligations": ["obl1"],
                "missing_obligations": [],
            },
            {
                "sample_id": "s2",
                "classification": "algebra_only_success",
                "used_verified_decls": [],
                "required_verified_decls": ["decl2"],
                "covered_obligations": [],
                "missing_obligations": ["obl2"],
            },
        ],
    }

    metrics = build_metrics(
        summaries=[_summary("s1"), _summary("s2")],
        statement_rows=[],
        grounding_rows=[],
        compile_rows=[],
        semantic_rows=[],
        proof_rows=[],
        proof_attempt_rows=stage_rows["proof_attempts.jsonl"],
        stage_rows=stage_rows,
    )

    assert metrics["gap_assisted_success_rate"] == 0.5
    assert metrics["algebra_only_success_rate"] == 0.5
    assert metrics["verified_decl_use_rate"] == 0.5


def test_llm_guided_search_metrics_count_physical_assumption_augmentation() -> None:
    stage_rows = {
        "proof_attempts.jsonl": [
            {"sample_id": "s1", "proof_mode": "llm_guided_search"},
        ],
        "proof_search_trace.jsonl": [
            {
                "sample_id": "s1",
                "candidate_id": "c1",
                "search_status": "failed",
                "llm_calls": 1,
                "physical_assumption_augmented": True,
            },
        ],
        "proof_action_checks.jsonl": [
            {
                "sample_id": "s1",
                "source": "deterministic",
                "accepted": True,
                "status": "context_augmented",
                "strategy": "augment_physical_positive_hypotheses",
                "compile_pass": True,
            }
        ],
        "proof_dependency_audit.jsonl": [
            {
                "sample_id": "s1",
                "classification": "proof_failed",
                "used_verified_decls": [],
                "required_verified_decls": [],
                "covered_obligations": [],
                "missing_obligations": [],
                "physical_assumption_augmented": True,
            },
        ],
    }

    metrics = build_metrics(
        summaries=[_summary("s1")],
        statement_rows=[],
        grounding_rows=[],
        compile_rows=[],
        semantic_rows=[],
        proof_rows=[],
        proof_attempt_rows=stage_rows["proof_attempts.jsonl"],
        stage_rows=stage_rows,
    )

    assert metrics["physical_assumption_augmentation_rate"] == 1.0
    assert metrics["augmented_theorem_compile_success_rate"] == 1.0
