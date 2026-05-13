from __future__ import annotations

from mech_pipeline.eval.metrics import build_metrics, build_minimal_skeleton_stage_summary
from mech_pipeline.types import SampleRunSummary


def _summary(sample_id: str) -> SampleRunSummary:
    return SampleRunSummary(
        sample_id=sample_id,
        grounding_ok=True,
        statement_generation_ok=True,
        compile_ok=False,
        semantic_ok=False,
        proof_ok=False,
        end_to_end_ok=False,
        final_error_type=None,
    )


def test_minimal_skeleton_metrics_from_stage_rows() -> None:
    stage_rows = {
        "model_ir.jsonl": [
            {"sample_id": "s1", "parse_ok": True},
            {"sample_id": "s2", "parse_ok": False},
        ],
        "evidence_bindings.jsonl": [
            {"sample_id": "s1", "binding_status": "ok", "proof_fact_allowed": True},
            {"sample_id": "s2", "binding_status": "gap_schema_only", "proof_fact_allowed": False},
        ],
        "controlled_sketch.jsonl": [
            {"sample_id": "s1", "parse_ok": True},
            {"sample_id": "s2", "parse_ok": True},
        ],
        "sketch_audit.jsonl": [
            {"sample_id": "s1", "audit_pass": True, "schema_used_as_proof_fact": False},
            {"sample_id": "s2", "audit_pass": False, "schema_used_as_proof_fact": True},
        ],
        "theorem_skeleton_candidates.jsonl": [
            {
                "sample_id": "s1",
                "candidate_id": "c1",
                "generation_mode": "minimal_skeleton",
                "parse_ok": True,
                "hypothesis_provenance": [{"role": "explicit_gap_law"}],
                "skeleton_audit": {
                    "audit_pass": True,
                    "raw_law_equation_in_hypotheses": False,
                    "schema_used_as_proof_fact": False,
                },
            },
            {
                "sample_id": "s2",
                "candidate_id": "c2",
                "generation_mode": "minimal_skeleton",
                "parse_ok": True,
                "hypothesis_provenance": [],
                "skeleton_audit": {
                    "audit_pass": False,
                    "raw_law_equation_in_hypotheses": True,
                    "schema_used_as_proof_fact": False,
                },
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
        stage_rows=stage_rows,
    )

    assert metrics["model_ir_success_rate"] == 0.5
    assert metrics["evidence_binding_success_rate"] == 0.5
    assert metrics["verified_binding_rate"] == 0.5
    assert metrics["gap_schema_only_rate"] == 0.5
    assert metrics["sketch_audit_pass_rate"] == 0.5
    assert metrics["skeleton_generation_success_rate"] == 0.5
    assert metrics["derived_equation_hypothesis_violation_rate"] == 0.5
    assert metrics["schema_as_proof_fact_violation_rate"] == 0.5
    assert metrics["explicit_gap_law_rate"] == 0.5

    summary = build_minimal_skeleton_stage_summary(stage_rows)
    assert summary["generation_mode"] == "minimal_skeleton"
    assert summary["model_ir_ok"] == "1/2"
    assert summary["evidence_binding_count"] == 2
    assert summary["verified_binding_count"] == 1
    assert summary["gap_schema_only_count"] == 1
    assert summary["sketch_audit_pass"] == "1/2"
    assert summary["forbidden_hypothesis_count"] == 1
    assert summary["skeleton_candidate_count"] == 2


def test_minimal_skeleton_metrics_are_null_for_legacy_rows() -> None:
    metrics = build_metrics(
        summaries=[_summary("s1")],
        statement_rows=[],
        grounding_rows=[],
        compile_rows=[],
        semantic_rows=[],
        proof_rows=[],
        stage_rows={},
    )

    assert metrics["model_ir_success_rate"] is None
    assert metrics["evidence_binding_success_rate"] is None
    assert metrics["verified_binding_rate"] is None
    assert build_minimal_skeleton_stage_summary({})["generation_mode"] == "legacy_candidate"
