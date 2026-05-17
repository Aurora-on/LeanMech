from __future__ import annotations

import json
from typing import Any

from mech_pipeline.prompt_views import compact_candidate_for_feedback
from mech_pipeline.types import CompileCheckResult, FailureRoute, SemanticRankResult, StatementCandidate

STAGE_ORDER = {
    "A2": 0,
    "EvidenceBinder": 1,
    "Sketch": 2,
    "B": 3,
    "C": 4,
    "D": 5,
    "none": 99,
}

ARTIFACTS_BY_STAGE = {
    "A2": "ModelIR",
    "EvidenceBinder": "EvidenceBindings",
    "Sketch": "ControlledSketch",
    "B": "B",
    "C": "C",
    "D": "D",
}
BASE_ARTIFACTS = ["ProblemIR", "StructuredMechLibContext"]
DOWNSTREAM_ARTIFACTS = ["ModelIR", "EvidenceBindings", "ControlledSketch", "SketchAudit", "B", "C", "D"]

A2_TAGS = {
    "canonical_target_missing",
    "missing_canonical_target",
    "target_formula_invalid",
    "invalid_canonical_target_formula",
    "target_function_formula_invalid",
    "invalid_function_formula_ir",
    "invalid_function_formula_kind",
    "missing_function_bound_variables",
    "missing_function_formula",
    "tautological_function_formula",
    "tautological_canonical_target",
    "quantity_type_missing",
    "quantity_type_issue",
    "quantity_type_unsupported",
    "unsupported_si_type",
    "unit_dimension_conflict",
    "unknown_target",
    "known_quantities",
    "units",
    "wrong_target",
    "target_mismatch",
    "missing_typed_target_formula",
    "model_ir_unavailable",
    "no_controlled_variant_available",
    "no_controlled_sketch_available",
}
EVIDENCE_BINDER_TAGS = {
    "evidence_binding_missing",
    "evidence_gap",
    "no_verified_decl",
    "no_model_predicate_decl",
    "no_extractor_decl",
    "signature_mismatch",
    "lean_check_decl_failed",
    "lean_check_failed",
    "bad_decl",
    "wrong_decl",
    "fabricated_decl_detected",
    "schema_used_as_proof_fact",
    "proof_obligation_gap_violation",
}
SKETCH_TAGS = {
    "sketch_audit_failed",
    "upstream_sketch_audit_failed",
    "verified_decl_uninstantiated",
    "proof_step_missing_verified_decl",
    "gap_step_in_proof_steps",
    "too_many_sketch_steps",
    "algebra_obligation_invalid",
    "natural_language_formal_claim",
    "non_lean_like_formal_claim",
    "law_drift",
    "law_selection",
    "proof_obligation",
    "proof_obligation_missing",
    "missing_proof_obligations",
    "gap_step",
    "sketch_raw_law_equation_in_hypotheses",
}
B_TAGS = {
    "skeleton_audit_failed",
    "skeleton_audit_fail",
    "skeleton_audit",
    "theorem_shape_invalid",
    "invalid_decl_shape",
    "binder_type_invalid",
    "qualitative_prop_hypothesis",
    "qualitative_pseudo_predicate_hypothesis",
    "derived_equation_hypothesis",
    "derived_equation_hypothesis_violation",
    "target_leakage_hypothesis",
    "candidate_answer_hypothesis_violation",
    "header_invalid",
    "val_projection_invalid",
    "unknown_identifier",
    "application_type_mismatch",
    "binder",
    "type mismatch",
    "invalid field notation",
    "function expected",
    "tuple_valued_formula",
    "skeleton_raw_law_equation_in_hypotheses",
}
C_TAGS = {
    "lean_compile_failed",
    "elaboration_failed",
    "import_failed",
    "preflight_timeout",
    "lean_timeout",
    "backend_unavailable",
    "lean_disabled",
    "timeout_or_tooling",
    "timeout_or_tooling_block",
    "empty_stderr_timeout",
}
D_TAGS = {
    "semantic_rank_parse_failed",
    "semantic_score_unavailable",
    "skeleton_semantic_inconsistency",
}


def stage_at_or_before(stage: str, target: str) -> bool:
    return STAGE_ORDER.get(stage, 99) <= STAGE_ORDER.get(target, 99)


def _contains_any_tag(joined: str, tags: set[str]) -> bool:
    return any(tag in joined for tag in tags)


def _artifacts_for_start_stage(start_stage: str) -> tuple[list[str], list[str]]:
    if start_stage == "none":
        return [*BASE_ARTIFACTS, *DOWNSTREAM_ARTIFACTS], []
    order = STAGE_ORDER.get(start_stage, 99)
    reused = list(BASE_ARTIFACTS)
    invalidated: list[str] = []
    for stage, artifact in ARTIFACTS_BY_STAGE.items():
        if STAGE_ORDER[stage] < order:
            reused.append(artifact)
        elif STAGE_ORDER[stage] >= order:
            invalidated.append(artifact)
            if stage == "Sketch" and "SketchAudit" not in invalidated:
                invalidated.append("SketchAudit")
    return reused, invalidated


def _strings(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if item is not None]
    if isinstance(value, dict):
        return [json.dumps(value, ensure_ascii=False, sort_keys=True)]
    return [str(value)]


def _lower_blob(*values: object) -> str:
    pieces: list[str] = []
    for value in values:
        pieces.extend(_strings(value))
    return " ".join(pieces).lower()


def _semantic_rows(semantic: SemanticRankResult) -> list[dict[str, Any]]:
    return [row for row in semantic.ranking if isinstance(row, dict)]


def _candidate_compact(
    candidate: StatementCandidate,
    compile_map: dict[str, CompileCheckResult],
    semantic_map: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    compile_row = compile_map.get(candidate.candidate_id)
    semantic_row = semantic_map.get(candidate.candidate_id, {})
    out = compact_candidate_for_feedback(candidate)
    out.update(
        {
        "skeleton_audit_details": (out.get("skeleton_audit") or {}).get("details") if isinstance(out.get("skeleton_audit"), dict) else {},
        "compile_pass": bool(compile_row.compile_pass) if compile_row else False,
        "compile_error_type": compile_row.error_type if compile_row else "compile_not_run",
        "compile_sub_error_type": compile_row.sub_error_type if compile_row else None,
        "compile_failure_tags": list(compile_row.failure_tags) if compile_row else [],
        "compile_failure_summary": compile_row.failure_summary if compile_row else None,
        "compile_error_message": (
            (compile_row.error_message[:900] + "...<truncated>")
            if compile_row and compile_row.error_message and len(compile_row.error_message) > 900
            else compile_row.error_message if compile_row else None
        ),
        "semantic_pass": semantic_row.get("semantic_pass"),
        "semantic_failure_tags": semantic_row.get("failure_tags"),
        "mismatch_fields": semantic_row.get("mismatch_fields"),
        "semantic_failure_summary": semantic_row.get("failure_summary"),
        "suggested_fix_direction": semantic_row.get("suggested_fix_direction"),
        }
    )
    return out


def _route_stage_from_tags(route_tags: set[str], retry_reason: str) -> str:
    joined = " ".join(route_tags).lower()
    if _contains_any_tag(joined, A2_TAGS):
        return "A2"
    if _contains_any_tag(joined, EVIDENCE_BINDER_TAGS):
        return "EvidenceBinder"
    if _contains_any_tag(joined, SKETCH_TAGS):
        return "Sketch"
    if _contains_any_tag(joined, B_TAGS):
        return "B"
    if _contains_any_tag(joined, C_TAGS):
        return "C"
    if _contains_any_tag(joined, D_TAGS):
        return "D"
    if retry_reason == "semantic_fail":
        return "D"
    return "B" if retry_reason == "no_compile_pass" else "D"


def _add_known_route_tags(route_tags: set[str], blob: str) -> None:
    for tag in A2_TAGS | EVIDENCE_BINDER_TAGS | SKETCH_TAGS | B_TAGS | C_TAGS | D_TAGS:
        if tag in blob:
            route_tags.add(tag)


def _failed_stage_for_retry(retry_reason: str, compile_results: list[CompileCheckResult]) -> str:
    if retry_reason == "semantic_fail":
        return "D"
    if retry_reason == "no_compile_pass":
        return "C" if compile_results else "B"
    return "D"


def _failure_summary(
    *,
    retry_reason: str,
    candidates: list[StatementCandidate],
    compile_results: list[CompileCheckResult],
    semantic: SemanticRankResult,
) -> str:
    pieces: list[str] = []
    if semantic.failure_summary:
        pieces.append(str(semantic.failure_summary))
    for row in compile_results:
        if row.failure_summary:
            pieces.append(str(row.failure_summary))
        elif row.error_type:
            pieces.append(str(row.error_type))
    for candidate in candidates:
        reason = getattr(candidate, "generation_blocked_reason", None)
        if reason:
            pieces.append(str(reason))
        audit = getattr(candidate, "skeleton_audit", None)
        summary = getattr(audit, "failure_summary", None)
        if summary:
            pieces.append(str(summary))
    if not pieces:
        pieces.append(retry_reason)
    return "; ".join(dict.fromkeys(piece for piece in pieces if piece))


def apply_minimal_feedback_scope(route: FailureRoute, scope: str) -> FailureRoute | None:
    normalized = str(scope or "routed_stage").strip()
    if normalized == "none":
        return None
    original_stage = route.start_stage
    if normalized == "routed_stage":
        start_stage = route.start_stage
    elif normalized == "sketch_and_b":
        start_stage = "Sketch"
    elif normalized == "b_only":
        start_stage = "B"
    elif normalized == "all_downstream":
        start_stage = "A2"
    else:
        start_stage = route.start_stage
    if start_stage == original_stage and normalized == "routed_stage":
        route.feedback_payload["minimal_feedback_scope"] = normalized
        return route

    artifacts_reused, artifacts_invalidated = _artifacts_for_start_stage(start_stage)
    route.feedback_payload["minimal_feedback_scope"] = normalized
    route.feedback_payload["router_responsible_stage"] = original_stage
    route.feedback_payload["responsible_stage"] = start_stage
    route.feedback_payload["start_stage"] = start_stage
    route.feedback_payload["rerun_from_stage"] = start_stage
    route.feedback_payload["artifacts_reused"] = artifacts_reused
    route.feedback_payload["artifacts_invalidated"] = artifacts_invalidated
    route.start_stage = start_stage
    route.responsible_stage = start_stage
    route.rerun_downstream_from = start_stage
    route.rerun_from_stage = start_stage
    route.artifacts_reused = artifacts_reused
    route.artifacts_invalidated = artifacts_invalidated
    return route


def build_failure_route(
    *,
    sample_id: str,
    round_index: int,
    candidates: list[StatementCandidate],
    compile_results: list[CompileCheckResult],
    semantic: SemanticRankResult,
) -> FailureRoute | None:
    retry_reason: str | None = None
    if not any(row.compile_pass for row in compile_results):
        retry_reason = "no_compile_pass"
    elif not semantic.semantic_pass:
        retry_reason = "semantic_fail"
    if retry_reason is None:
        return None

    compile_map = {row.candidate_id: row for row in compile_results}
    semantic_map = {
        str(row.get("candidate_id")): row
        for row in _semantic_rows(semantic)
        if str(row.get("candidate_id") or "").strip()
    }
    route_tags: set[str] = {retry_reason}
    affected: set[str] = set()

    for candidate in candidates:
        variant_id = str(getattr(candidate, "variant_id", "") or "").strip()
        skeleton_tags = list(getattr(getattr(candidate, "skeleton_audit", None), "failure_tags", []) or [])
        blob = _lower_blob(
            getattr(candidate, "unsupported_claims", []),
            getattr(candidate, "generation_blocked_reason", None),
            skeleton_tags,
            getattr(getattr(candidate, "skeleton_audit", None), "failure_summary", None),
            variant_id,
        )
        _add_known_route_tags(route_tags, blob)
        if variant_id in {"no_controlled_variant_available", "no_controlled_sketch_available"}:
            route_tags.add(variant_id)
        if "quantity_type" in blob:
            route_tags.add("quantity_type_issue")
        if "unsupported_si_type" in blob:
            route_tags.add("unsupported_si_type")
        if "skeleton_audit" in blob or skeleton_tags:
            route_tags.add("skeleton_audit_fail")
            route_tags.add("skeleton_audit_failed")
        if "missing_typed_target_formula" in blob:
            route_tags.add("missing_typed_target_formula")
        if "missing_canonical_target" in blob:
            route_tags.add("missing_canonical_target")
        if "invalid_canonical_target_formula" in blob:
            route_tags.add("invalid_canonical_target_formula")
        if "tautological_canonical_target" in blob:
            route_tags.add("tautological_canonical_target")
        if "invalid_function_formula_ir" in blob:
            route_tags.add("invalid_function_formula_ir")
        if "invalid_function_formula_kind" in blob:
            route_tags.add("invalid_function_formula_kind")
        if "missing_function_bound_variables" in blob:
            route_tags.add("missing_function_bound_variables")
        if "missing_function_formula" in blob:
            route_tags.add("missing_function_formula")
        if "tautological_function_formula" in blob:
            route_tags.add("tautological_function_formula")
        if "non_lean_like_formal_claim" in blob:
            route_tags.add("non_lean_like_formal_claim")
        if "verified_decl_uninstantiated" in blob:
            route_tags.add("verified_decl_uninstantiated")
        if "upstream_sketch_audit_failed" in blob:
            route_tags.add("upstream_sketch_audit_failed")
        if "raw_law_equation_in_hypotheses" in blob:
            if skeleton_tags or "skeleton_audit" in blob:
                route_tags.add("skeleton_raw_law_equation_in_hypotheses")
                route_tags.add("derived_equation_hypothesis")
            else:
                route_tags.add("sketch_raw_law_equation_in_hypotheses")
        if "tuple_valued_formula" in blob or "tuple_valued_model_interface" in blob:
            route_tags.add("tuple_valued_formula")
        if any(key in blob for key in ("lean_check_failed", "signature_mismatch")):
            route_tags.add("signature_mismatch")
        if blob:
            affected.add(candidate.candidate_id)

    for row in compile_results:
        blob = _lower_blob(
            row.error_type,
            row.sub_error_type,
            row.failure_tags,
            row.failure_summary,
            row.error_message,
            row.error_snippet,
        )
        _add_known_route_tags(route_tags, blob)
        if not row.compile_pass:
            affected.add(row.candidate_id)
        for key in (
            "lean_disabled",
            "timeout_or_tooling",
            "empty_stderr_timeout",
            "invalid_decl_shape",
            "unknown_identifier",
            "application_type_mismatch",
            "import",
            "binder",
            "type mismatch",
            "invalid field notation",
            "function expected",
        ):
            if key in blob:
                route_tags.add(key)

    for row in _semantic_rows(semantic):
        blob = _lower_blob(
            row.get("failure_tags"),
            row.get("mismatch_fields"),
            row.get("hard_gate_reasons"),
            row.get("skeleton_hard_gate_reasons"),
            row.get("skeleton_warning_reasons"),
            row.get("skeleton_failure_reasons"),
            row.get("failure_summary"),
            row.get("missing_or_incorrect_translations"),
            row.get("suggested_fix_direction"),
        )
        _add_known_route_tags(route_tags, blob)
        if not bool(row.get("semantic_pass")) and str(row.get("candidate_id") or "").strip():
            affected.add(str(row.get("candidate_id")))
        for key in ("unknown_target", "known_quantities", "units", "wrong_target", "target"):
            if key in blob:
                route_tags.add(key)
        if "law" in blob:
            route_tags.add("law_drift")
        if "missing proof obligation" in blob or "missing_proof_obligations" in blob:
            route_tags.add("missing_proof_obligations")
        if "evidence gap" in blob or "evidence_gap" in blob:
            route_tags.add("evidence_gap")

    start_stage = _route_stage_from_tags(route_tags, retry_reason)
    failed_stage = _failed_stage_for_retry(retry_reason, compile_results)
    artifacts_reused, artifacts_invalidated = _artifacts_for_start_stage(start_stage)
    failure_summary = _failure_summary(
        retry_reason=retry_reason,
        candidates=candidates,
        compile_results=compile_results,
        semantic=semantic,
    )
    compact_candidates = [
        _candidate_compact(candidate, compile_map, semantic_map)
        for candidate in candidates
        if not affected or candidate.candidate_id in affected
    ]
    payload = {
        "retry_reason": retry_reason,
        "start_stage": start_stage,
        "responsible_stage": start_stage,
        "failed_stage": failed_stage,
        "route_tags": sorted(route_tags),
        "failure_tags": sorted(route_tags),
        "failure_summary": failure_summary,
        "rerun_from_stage": start_stage,
        "artifacts_reused": artifacts_reused,
        "artifacts_invalidated": artifacts_invalidated,
        "affected_candidates": sorted(affected),
        "candidates": compact_candidates,
    }
    return FailureRoute(
        sample_id=sample_id,
        round_index=round_index,
        retry_reason=retry_reason,
        start_stage=start_stage,
        route_tags=sorted(route_tags),
        affected_candidates=sorted(affected),
        feedback_payload=payload,
        rerun_downstream_from=start_stage,
        generation_mode="minimal_skeleton" if any(getattr(c, "generation_mode", None) == "minimal_skeleton" for c in candidates) else None,
        failed_stage=failed_stage,
        responsible_stage=start_stage,
        failure_tags=sorted(route_tags),
        failure_summary=failure_summary,
        rerun_from_stage=start_stage,
        artifacts_reused=artifacts_reused,
        artifacts_invalidated=artifacts_invalidated,
    )
