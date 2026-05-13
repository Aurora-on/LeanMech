from __future__ import annotations

from mech_pipeline.failure_routing import build_failure_route
from mech_pipeline.types import CompileCheckResult, SemanticRankResult, TheoremSkeletonCandidate


def _candidate(unsupported: list[str] | None = None) -> TheoremSkeletonCandidate:
    return TheoremSkeletonCandidate(
        sample_id="s-route",
        candidate_id="c1",
        lean_header="import MechLib",
        theorem_decl="theorem c1 : True",
        unsupported_claims=unsupported or [],
        parse_ok=True,
    )


def _compile(*, ok: bool = False, tags: list[str] | None = None) -> CompileCheckResult:
    return CompileCheckResult(
        sample_id="s-route",
        candidate_id="c1",
        compile_pass=ok,
        syntax_ok=ok,
        elaboration_ok=ok,
        error_type=None if ok else "compile_failed",
        stderr_digest="",
        log_path=None,
        failure_tags=tags or ([] if ok else ["compile_failed"]),
        failure_summary=None if ok else "compile failed",
    )


def _semantic(*, tags: list[str] | None = None, fields: list[str] | None = None, summary: str = "") -> SemanticRankResult:
    return SemanticRankResult(
        sample_id="s-route",
        selected_candidate_id="c1",
        selected_theorem_decl="theorem c1 : True",
        semantic_pass=False,
        ranking=[
            {
                "candidate_id": "c1",
                "semantic_pass": False,
                "failure_tags": tags or [],
                "mismatch_fields": fields or [],
                "failure_summary": summary,
            }
        ],
        error="semantic_drift",
        failure_summary=summary or None,
    )


def _route(*, candidate_tags: list[str] | None = None, compile_tags: list[str] | None = None, semantic_tags: list[str] | None = None, semantic_fields: list[str] | None = None):
    compile_rows = [_compile(ok=compile_tags is None, tags=compile_tags)]
    return build_failure_route(
        sample_id="s-route",
        round_index=0,
        candidates=[_candidate(candidate_tags)],
        compile_results=compile_rows,
        semantic=_semantic(tags=semantic_tags, fields=semantic_fields),
    )


def test_target_formula_invalid_routes_to_a2() -> None:
    route = _route(candidate_tags=["target_formula_invalid"])

    assert route is not None
    assert route.start_stage == "A2"
    assert route.responsible_stage == "A2"
    assert "target_formula_invalid" in route.failure_tags
    assert "ModelIR" in route.artifacts_invalidated


def test_no_extractor_decl_routes_to_evidence_binder() -> None:
    route = _route(candidate_tags=["no_extractor_decl"])

    assert route is not None
    assert route.start_stage == "EvidenceBinder"
    assert route.responsible_stage == "EvidenceBinder"
    assert "no_extractor_decl" in route.failure_tags
    assert "ModelIR" in route.artifacts_reused
    assert "EvidenceBindings" in route.artifacts_invalidated


def test_gap_step_in_proof_steps_routes_to_sketch() -> None:
    route = _route(candidate_tags=["gap_step_in_proof_steps"])

    assert route is not None
    assert route.start_stage == "Sketch"
    assert "gap_step_in_proof_steps" in route.failure_tags


def test_qualitative_prop_hypothesis_routes_to_b() -> None:
    route = _route(candidate_tags=["qualitative_prop_hypothesis"])

    assert route is not None
    assert route.start_stage == "B"
    assert "qualitative_prop_hypothesis" in route.failure_tags


def test_import_failed_and_lean_timeout_route_to_c() -> None:
    for tag in ("import_failed", "lean_timeout"):
        route = _route(compile_tags=[tag])

        assert route is not None
        assert route.start_stage == "C"
        assert tag in route.failure_tags


def test_skeleton_semantic_missing_proof_obligation_routes_to_sketch() -> None:
    route = _route(semantic_tags=["skeleton_semantic_inconsistency", "missing_proof_obligations"])

    assert route is not None
    assert route.start_stage == "Sketch"
    assert "skeleton_semantic_inconsistency" in route.failure_tags
    assert "missing_proof_obligations" in route.failure_tags
