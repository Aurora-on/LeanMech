from __future__ import annotations

from mech_pipeline.failure_routing import build_failure_route, stage_at_or_before
from mech_pipeline.types import CompileCheckResult, SemanticRankResult, SketchAuditResult, StatementCandidate, TheoremSkeletonCandidate


def _candidate(cid: str = "c1", unsupported: list[str] | None = None) -> TheoremSkeletonCandidate:
    return TheoremSkeletonCandidate(
        sample_id="s1",
        candidate_id=cid,
        lean_header="import MechLib",
        theorem_decl="theorem c : True",
        unsupported_claims=unsupported or [],
        parse_ok=True,
    )


def _compile(cid: str = "c1", *, ok: bool = False, error: str = "elaboration_failure", tags: list[str] | None = None) -> CompileCheckResult:
    return CompileCheckResult(
        sample_id="s1",
        candidate_id=cid,
        compile_pass=ok,
        syntax_ok=ok,
        elaboration_ok=ok,
        error_type=None if ok else error,
        stderr_digest="",
        log_path=None,
        sub_error_type=None if ok else error,
        failure_tags=tags or ([] if ok else [error]),
        failure_summary=None if ok else error,
    )


def _semantic(*, ok: bool, ranking: list[dict] | None = None) -> SemanticRankResult:
    return SemanticRankResult(
        sample_id="s1",
        selected_candidate_id="c1" if ranking else None,
        selected_theorem_decl=None,
        semantic_pass=ok,
        ranking=ranking or [],
    )


def test_compile_import_or_type_error_routes_to_b() -> None:
    route = build_failure_route(
        sample_id="s1",
        round_index=0,
        candidates=[_candidate()],
        compile_results=[_compile(error="unknown_identifier", tags=["unknown_identifier"])],
        semantic=_semantic(ok=False),
    )

    assert route is not None
    assert route.start_stage == "B"
    assert "unknown_identifier" in route.route_tags


def test_semantic_target_or_units_mismatch_routes_to_a2() -> None:
    route = build_failure_route(
        sample_id="s1",
        round_index=0,
        candidates=[_candidate()],
        compile_results=[_compile(ok=True)],
        semantic=_semantic(
            ok=False,
            ranking=[
                {
                    "candidate_id": "c1",
                    "semantic_pass": False,
                    "failure_tags": ["wrong_target"],
                    "mismatch_fields": ["unknown_target", "units"],
                }
            ],
        ),
    )

    assert route is not None
    assert route.start_stage == "A2"
    assert "unknown_target" in route.route_tags
    assert "units" in route.route_tags


def test_semantic_law_drift_routes_to_sketch() -> None:
    route = build_failure_route(
        sample_id="s1",
        round_index=0,
        candidates=[_candidate()],
        compile_results=[_compile(ok=True)],
        semantic=_semantic(
            ok=False,
            ranking=[
                {
                    "candidate_id": "c1",
                    "semantic_pass": False,
                    "failure_tags": ["law_drift"],
                    "mismatch_fields": ["physical_laws"],
                }
            ],
        ),
    )

    assert route is not None
    assert route.start_stage == "Sketch"


def test_evidence_binding_failures_route_to_evidence_binder() -> None:
    route = build_failure_route(
        sample_id="s1",
        round_index=0,
        candidates=[_candidate(unsupported=["signature_mismatch:MechLib.BadDecl"])],
        compile_results=[_compile(error="elaboration_failure")],
        semantic=_semantic(ok=False),
    )

    assert route is not None
    assert route.start_stage == "EvidenceBinder"
    assert "signature_mismatch" in route.route_tags


def test_skeleton_audit_failure_routes_to_b() -> None:
    candidate = _candidate()
    candidate.skeleton_audit = SketchAuditResult(
        sample_id="s1",
        audit_pass=False,
        failure_tags=["skeleton_audit:unknown_qualitative_predicate"],
    )

    route = build_failure_route(
        sample_id="s1",
        round_index=0,
        candidates=[candidate],
        compile_results=[_compile(error="compile_not_run", tags=["compile_not_run"])],
        semantic=_semantic(ok=False),
    )

    assert route is not None
    assert route.start_stage == "B"
    assert "skeleton_audit_fail" in route.route_tags


def test_skeleton_raw_law_audit_failure_routes_to_b_with_details() -> None:
    candidate = _candidate()
    candidate.skeleton_audit = SketchAuditResult(
        sample_id="s1",
        audit_pass=False,
        failure_tags=["raw_law_equation_in_hypotheses"],
        details={"bad_binders": [{"name": "h_model", "issues": ["law_application_claim_in_binder"]}]},
    )

    route = build_failure_route(
        sample_id="s1",
        round_index=0,
        candidates=[candidate],
        compile_results=[],
        semantic=_semantic(ok=False),
    )

    assert route is not None
    assert route.start_stage == "B"
    assert "skeleton_raw_law_equation_in_hypotheses" in route.route_tags
    assert route.feedback_payload["candidates"][0]["skeleton_audit_details"]["bad_binders"][0]["name"] == "h_model"


def test_missing_canonical_target_routes_to_a2() -> None:
    route = build_failure_route(
        sample_id="s1",
        round_index=0,
        candidates=[_candidate(unsupported=["generation_blocked:missing_canonical_target"])],
        compile_results=[],
        semantic=_semantic(ok=False),
    )

    assert route is not None
    assert route.start_stage == "A2"
    assert "missing_canonical_target" in route.route_tags


def test_non_lean_like_sketch_feedback_routes_to_sketch() -> None:
    candidate = _candidate()
    candidate.skeleton_audit = SketchAuditResult(
        sample_id="s1",
        audit_pass=False,
        failure_tags=["upstream_sketch_audit_failed", "non_lean_like_formal_claim"],
    )

    route = build_failure_route(
        sample_id="s1",
        round_index=0,
        candidates=[candidate],
        compile_results=[],
        semantic=_semantic(ok=False),
    )

    assert route is not None
    assert route.start_stage == "Sketch"
    assert "non_lean_like_formal_claim" in route.route_tags


def test_missing_controlled_variant_routes_to_a2() -> None:
    candidate = _candidate()
    candidate.variant_id = "no_controlled_variant_available"

    route = build_failure_route(
        sample_id="s1",
        round_index=0,
        candidates=[candidate],
        compile_results=[],
        semantic=_semantic(ok=False),
    )

    assert route is not None
    assert route.start_stage == "A2"
    assert "no_controlled_variant_available" in route.route_tags


def test_missing_controlled_sketch_routes_to_a2() -> None:
    candidate = _candidate()
    candidate.variant_id = "no_controlled_sketch_available"

    route = build_failure_route(
        sample_id="s1",
        round_index=0,
        candidates=[candidate],
        compile_results=[],
        semantic=_semantic(ok=False),
    )

    assert route is not None
    assert route.start_stage == "A2"
    assert "no_controlled_sketch_available" in route.route_tags


def test_stage_order_helper_allows_downstream_rerun_boundaries() -> None:
    assert stage_at_or_before("A2", "B") is True
    assert stage_at_or_before("EvidenceBinder", "B") is True
    assert stage_at_or_before("Sketch", "B") is True
    assert stage_at_or_before("B", "Sketch") is False
    assert stage_at_or_before("C", "B") is False
