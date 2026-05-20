from __future__ import annotations

from collections import Counter
from typing import Any

from mech_pipeline.types import CompileCheckResult, GroundingResult, ProofCheckResult, SampleRunSummary, SemanticRankResult

MINIMAL_SKELETON_METRIC_KEYS = (
    "model_ir_success_rate",
    "evidence_binding_success_rate",
    "verified_binding_rate",
    "retrieved_verified_decl_rate",
    "instantiated_model_predicate_binding_rate",
    "extractor_binding_rate",
    "slot_order_binding_rate",
    "gap_schema_only_rate",
    "sketch_audit_pass_rate",
    "skeleton_generation_success_rate",
    "derived_equation_hypothesis_violation_rate",
    "schema_as_proof_fact_violation_rate",
    "explicit_gap_law_rate",
)

LLM_GUIDED_E_METRIC_KEYS = (
    "llm_guided_search_enabled_rate",
    "obligation_replay_success_rate",
    "proof_obligation_coverage_rate",
    "verified_decl_use_rate",
    "fully_mechlib_verified_proof_rate",
    "partial_mechlib_verified_proof_rate",
    "gap_assisted_success_rate",
    "algebra_only_success_rate",
    "llm_strategy_success_rate",
    "valid_llm_action_rate",
    "invalid_llm_action_rate",
    "missing_side_condition_rate",
    "physical_assumption_augmentation_rate",
    "augmented_theorem_compile_success_rate",
    "average_llm_calls_per_proof",
    "average_lean_action_checks_per_proof",
)

SOLUTION_RENDERER_METRIC_KEYS = (
    "solution_render_success_rate",
    "solution_render_audit_pass_rate",
    "solution_final_answer_coverage_rate",
    "solution_law_step_coverage_rate",
    "solution_gap_disclosure_pass_rate",
    "solution_unsupported_formula_avg",
    "solution_verified_trace_rate",
    "solution_legacy_no_audit_rate",
    "solution_partial_or_failed_explanation_rate",
)


def _safe_rate(num: int, den: int) -> float:
    if den <= 0:
        return 0.0
    return round(num / den, 6)


def _is_mechlib_header(value: object) -> bool:
    if not isinstance(value, str):
        return False
    return "import MechLib" in value


def _row_sample_id(row: object) -> str:
    return str(getattr(row, "sample_id", "")) if not isinstance(row, dict) else str(row.get("sample_id", ""))


def _row_round_index(row: object) -> int:
    value = getattr(row, "round_index", 0) if not isinstance(row, dict) else row.get("round_index", 0)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return 0
    return 0


def _row_bool(row: object, key: str) -> bool:
    value = getattr(row, key, False) if not isinstance(row, dict) else row.get(key, False)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return False


def _row_string_list(row: dict[str, Any], key: str) -> list[str]:
    value = row.get(key)
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            out.append(text)
    return out


def _stage_rows(stage_rows: dict[str, list[dict[str, Any]]] | None, name: str) -> list[dict[str, Any]]:
    rows = (stage_rows or {}).get(name)
    return rows if isinstance(rows, list) else []


def _final_stage_rows(rows: list[dict[str, Any]], final_round_map: dict[str, int]) -> list[dict[str, Any]]:
    if not final_round_map:
        return rows
    return [row for row in rows if final_round_map.get(str(row.get("sample_id") or ""), 0) == _row_round_index(row)]


def _candidate_skeleton_rows(
    *,
    statement_rows: list[dict[str, Any]],
    stage_rows: dict[str, list[dict[str, Any]]] | None,
) -> list[dict[str, Any]]:
    skeleton_rows = _stage_rows(stage_rows, "theorem_skeleton_candidates.jsonl")
    if skeleton_rows:
        return skeleton_rows
    return [
        row
        for row in statement_rows
        if isinstance(row, dict) and str(row.get("generation_mode") or "") == "minimal_skeleton"
    ]


def _candidate_audit(row: dict[str, Any]) -> dict[str, Any]:
    audit = row.get("skeleton_audit")
    return audit if isinstance(audit, dict) else {}


def _unique_sample_ids(rows: list[dict[str, Any]]) -> set[str]:
    return {str(row.get("sample_id") or "") for row in rows if str(row.get("sample_id") or "").strip()}


def _minimal_sample_denominator(
    summaries: list[SampleRunSummary],
    *,
    model_rows: list[dict[str, Any]],
    evidence_rows: list[dict[str, Any]],
    sketch_audit_rows: list[dict[str, Any]],
    skeleton_rows: list[dict[str, Any]],
) -> int:
    summary_ids = {s.sample_id for s in summaries}
    if summary_ids:
        return len(summary_ids)
    row_ids: set[str] = set()
    for rows in (model_rows, evidence_rows, sketch_audit_rows, skeleton_rows):
        row_ids.update(_unique_sample_ids(rows))
    return len(row_ids)


def _sample_has_explicit_gap_law(row: dict[str, Any]) -> bool:
    provenance = row.get("hypothesis_provenance")
    if isinstance(provenance, list):
        for item in provenance:
            if isinstance(item, dict) and str(item.get("role") or "") == "explicit_gap_law":
                return True
    return False


def _sample_has_audit_flag(row: dict[str, Any], key: str) -> bool:
    return bool(_candidate_audit(row).get(key))


def _minimal_rows_present(
    *,
    model_rows: list[dict[str, Any]],
    evidence_rows: list[dict[str, Any]],
    sketch_rows: list[dict[str, Any]],
    sketch_audit_rows: list[dict[str, Any]],
    skeleton_rows: list[dict[str, Any]],
) -> bool:
    return bool(model_rows or evidence_rows or sketch_rows or sketch_audit_rows or skeleton_rows)


def build_minimal_skeleton_stage_summary(stage_rows: dict[str, list[dict[str, Any]]] | None) -> dict[str, Any]:
    model_rows = _stage_rows(stage_rows, "model_ir.jsonl")
    evidence_rows = _stage_rows(stage_rows, "evidence_bindings.jsonl")
    sketch_audit_rows = _stage_rows(stage_rows, "sketch_audit.jsonl")
    skeleton_rows = _candidate_skeleton_rows(
        statement_rows=_stage_rows(stage_rows, "statement_candidates.jsonl"),
        stage_rows=stage_rows,
    )
    model_sample_total = len(_unique_sample_ids(model_rows))
    model_ok = len({str(row.get("sample_id") or "") for row in model_rows if _row_bool(row, "parse_ok")})
    audit_sample_total = len(_unique_sample_ids(sketch_audit_rows))
    audit_pass = len({str(row.get("sample_id") or "") for row in sketch_audit_rows if _row_bool(row, "audit_pass")})
    forbidden_flags = (
        "target_leakage",
        "candidate_answer_leakage",
        "raw_law_equation_in_hypotheses",
        "algebra_result_in_hypotheses",
        "schema_used_as_proof_fact",
    )
    forbidden_count = sum(
        1
        for row in skeleton_rows
        if any(bool(_candidate_audit(row).get(flag)) for flag in forbidden_flags)
    )
    is_minimal = _minimal_rows_present(
        model_rows=model_rows,
        evidence_rows=evidence_rows,
        sketch_rows=_stage_rows(stage_rows, "controlled_sketch.jsonl"),
        sketch_audit_rows=sketch_audit_rows,
        skeleton_rows=skeleton_rows,
    )
    return {
        "generation_mode": "minimal_skeleton" if is_minimal else "legacy_candidate",
        "model_ir_ok": f"{model_ok}/{model_sample_total}" if model_sample_total else None,
        "evidence_binding_count": len(evidence_rows),
        "verified_binding_count": sum(1 for row in evidence_rows if _row_bool(row, "proof_fact_allowed")),
        "gap_schema_only_count": sum(1 for row in evidence_rows if str(row.get("binding_status") or "") == "gap_schema_only"),
        "sketch_audit_pass": f"{audit_pass}/{audit_sample_total}" if audit_sample_total else None,
        "forbidden_hypothesis_count": forbidden_count,
        "skeleton_candidate_count": len(skeleton_rows),
    }


def _minimal_skeleton_metrics(
    *,
    summaries: list[SampleRunSummary],
    statement_rows: list[dict[str, Any]],
    stage_rows: dict[str, list[dict[str, Any]]] | None,
) -> dict[str, Any]:
    model_rows = _stage_rows(stage_rows, "model_ir.jsonl")
    evidence_rows = _stage_rows(stage_rows, "evidence_bindings.jsonl")
    sketch_rows = _stage_rows(stage_rows, "controlled_sketch.jsonl")
    sketch_audit_rows = _stage_rows(stage_rows, "sketch_audit.jsonl")
    skeleton_rows = _candidate_skeleton_rows(statement_rows=statement_rows, stage_rows=stage_rows)
    if not _minimal_rows_present(
        model_rows=model_rows,
        evidence_rows=evidence_rows,
        sketch_rows=sketch_rows,
        sketch_audit_rows=sketch_audit_rows,
        skeleton_rows=skeleton_rows,
    ):
        return {key: None for key in MINIMAL_SKELETON_METRIC_KEYS}

    sample_den = _minimal_sample_denominator(
        summaries,
        model_rows=model_rows,
        evidence_rows=evidence_rows,
        sketch_audit_rows=sketch_audit_rows,
        skeleton_rows=skeleton_rows,
    )
    model_ok_samples = {str(row.get("sample_id") or "") for row in model_rows if _row_bool(row, "parse_ok")}
    sketch_audit_pass_samples = {
        str(row.get("sample_id") or "") for row in sketch_audit_rows if _row_bool(row, "audit_pass")
    }
    skeleton_ok_samples = {
        str(row.get("sample_id") or "")
        for row in skeleton_rows
        if _row_bool(row, "parse_ok") and bool(_candidate_audit(row).get("audit_pass"))
    }
    derived_violation_samples = {
        str(row.get("sample_id") or "")
        for row in skeleton_rows
        if _sample_has_audit_flag(row, "raw_law_equation_in_hypotheses")
    }
    schema_violation_samples = {
        str(row.get("sample_id") or "")
        for row in skeleton_rows
        if _sample_has_audit_flag(row, "schema_used_as_proof_fact")
    }
    for row in sketch_audit_rows:
        if _row_bool(row, "schema_used_as_proof_fact"):
            sid = str(row.get("sample_id") or "")
            if sid:
                schema_violation_samples.add(sid)
    explicit_gap_law_samples = {
        str(row.get("sample_id") or "") for row in skeleton_rows if _sample_has_explicit_gap_law(row)
    }
    binding_total = len(evidence_rows)
    binding_ok = sum(1 for row in evidence_rows if str(row.get("binding_status") or "") == "ok")
    verified_bindings = sum(1 for row in evidence_rows if _row_bool(row, "proof_fact_allowed"))
    retrieved_verified_decls = sum(1 for row in evidence_rows if str(row.get("verified_decl") or "").strip())
    slot_order_bindings = sum(
        1 for row in evidence_rows if isinstance(row.get("slot_order"), list) and bool(row.get("slot_order"))
    )
    extractor_bindings = sum(
        1
        for row in evidence_rows
        if any(
            token in " ".join(
                str(row.get(key) or "").lower()
                for key in ("binding_id", "verified_decl", "planning_schema", "notes")
            )
            for token in ("extract", "extractor", "to_", "hasderivat", "hasvelocity", "hasacceleration")
        )
    )
    gap_bindings = sum(1 for row in evidence_rows if str(row.get("binding_status") or "") == "gap_schema_only")
    instantiated_model_predicate_candidates = sum(
        1
        for row in skeleton_rows
        if isinstance(row.get("model_predicate_bindings"), list) and bool(row.get("model_predicate_bindings"))
    )

    return {
        "model_ir_success_rate": _safe_rate(len(model_ok_samples), sample_den),
        "evidence_binding_success_rate": _safe_rate(binding_ok, binding_total),
        "verified_binding_rate": _safe_rate(verified_bindings, binding_total),
        "retrieved_verified_decl_rate": _safe_rate(retrieved_verified_decls, binding_total),
        "instantiated_model_predicate_binding_rate": _safe_rate(instantiated_model_predicate_candidates, len(skeleton_rows)),
        "extractor_binding_rate": _safe_rate(extractor_bindings, binding_total),
        "slot_order_binding_rate": _safe_rate(slot_order_bindings, binding_total),
        "gap_schema_only_rate": _safe_rate(gap_bindings, binding_total),
        "sketch_audit_pass_rate": _safe_rate(len(sketch_audit_pass_samples), sample_den),
        "skeleton_generation_success_rate": _safe_rate(len(skeleton_ok_samples), sample_den),
        "derived_equation_hypothesis_violation_rate": _safe_rate(len(derived_violation_samples), sample_den),
        "schema_as_proof_fact_violation_rate": _safe_rate(len(schema_violation_samples), sample_den),
        "explicit_gap_law_rate": _safe_rate(len(explicit_gap_law_samples), sample_den),
    }


def _nested_dict_rows(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        value = row.get(key)
        if isinstance(value, dict):
            out.append(value)
    return out


def _list_field(row: dict[str, Any], key: str) -> list[Any]:
    value = row.get(key)
    return value if isinstance(value, list) else []


def _llm_guided_e_metrics(
    *,
    proof_attempt_rows: list[dict[str, Any]] | None,
    proof_rows: list[ProofCheckResult],
    stage_rows: dict[str, list[dict[str, Any]]] | None,
    final_round_map: dict[str, int],
) -> dict[str, Any]:
    raw_attempt_rows = proof_attempt_rows or _stage_rows(stage_rows, "proof_attempts.jsonl")
    attempt_rows = _final_stage_rows(raw_attempt_rows, final_round_map)
    trace_rows = _final_stage_rows(_stage_rows(stage_rows, "proof_search_trace.jsonl"), final_round_map)
    action_rows = _final_stage_rows(_stage_rows(stage_rows, "proof_action_checks.jsonl"), final_round_map)
    audit_rows = _final_stage_rows(_stage_rows(stage_rows, "proof_dependency_audit.jsonl"), final_round_map)
    if not audit_rows:
        audit_rows = _nested_dict_rows(attempt_rows, "dependency_audit")
    if not trace_rows:
        trace_rows = _nested_dict_rows(attempt_rows, "proof_search_trace")
    if not action_rows:
        for row in attempt_rows:
            for action in _list_field(row, "proof_action_checks"):
                if isinstance(action, dict):
                    action_rows.append(action)

    proof_den = len(attempt_rows) or len(proof_rows)
    llm_attempts = [
        row
        for row in attempt_rows
        if str(row.get("proof_mode") or "") == "llm_guided_search" or isinstance(row.get("proof_search_trace"), dict)
    ]
    audit_den = len(audit_rows)
    trace_den = len(trace_rows)
    action_den = len(action_rows)
    llm_action_rows = [row for row in action_rows if str(row.get("source") or "") == "llm"]
    llm_action_den = len(llm_action_rows)

    covered_obligations = sum(len(_list_field(row, "covered_obligations")) for row in audit_rows)
    missing_obligations = sum(len(_list_field(row, "missing_obligations")) for row in audit_rows)
    required_obligations = covered_obligations + missing_obligations
    verified_decl_use = sum(
        1
        for row in audit_rows
        if set(map(str, _list_field(row, "used_verified_decls")))
        & set(map(str, _list_field(row, "required_verified_decls")))
    )
    classifications = Counter(str(row.get("classification") or "") for row in audit_rows)
    successful_traces = sum(1 for row in trace_rows if str(row.get("search_status") or "") == "success")
    valid_llm_actions = sum(
        1
        for row in llm_action_rows
        if bool(row.get("accepted")) or str(row.get("status") or "") in {"progress", "closed"}
    )
    invalid_llm_actions = sum(
        1
        for row in llm_action_rows
        if not bool(row.get("accepted")) and str(row.get("status") or "") == "invalid"
    )
    missing_side_conditions = sum(
        1
        for row in action_rows
        if str(row.get("strategy") or "") == "missing_side_condition"
        or str(row.get("error_type") or "") == "missing_side_condition"
    )
    augmentation_actions = [
        row for row in action_rows if str(row.get("strategy") or "") == "augment_physical_positive_hypotheses"
    ]
    augmentation_success = sum(
        1
        for row in augmentation_actions
        if bool(row.get("accepted")) and str(row.get("status") or "") in {"context_augmented", "progress", "closed"}
    )
    augmentation_compile_success = sum(
        1
        for row in augmentation_actions
        if bool(row.get("compile_pass")) or bool((row.get("compile_result") or {}).get("compile_pass"))
    )
    augmented_audits = sum(1 for row in audit_rows if bool(row.get("physical_assumption_augmented")))

    avg_llm_calls = _safe_rate(
        sum(int(row.get("llm_calls") or 0) for row in trace_rows),
        trace_den,
    )
    avg_action_checks = _safe_rate(action_den, trace_den)

    return {
        "llm_guided_search_enabled_rate": _safe_rate(len(llm_attempts), proof_den),
        "obligation_replay_success_rate": _safe_rate(covered_obligations, required_obligations),
        "proof_obligation_coverage_rate": _safe_rate(covered_obligations, required_obligations),
        "verified_decl_use_rate": _safe_rate(verified_decl_use, audit_den),
        "fully_mechlib_verified_proof_rate": _safe_rate(classifications["fully_mechlib_verified"], audit_den),
        "partial_mechlib_verified_proof_rate": _safe_rate(classifications["partial_mechlib_verified"], audit_den),
        "gap_assisted_success_rate": _safe_rate(classifications["gap_assisted_success"], audit_den),
        "algebra_only_success_rate": _safe_rate(classifications["algebra_only_success"], audit_den),
        "llm_strategy_success_rate": _safe_rate(successful_traces, trace_den),
        "valid_llm_action_rate": _safe_rate(valid_llm_actions, llm_action_den),
        "invalid_llm_action_rate": _safe_rate(invalid_llm_actions, llm_action_den),
        "missing_side_condition_rate": _safe_rate(missing_side_conditions, action_den),
        "physical_assumption_augmentation_rate": _safe_rate(augmented_audits or augmentation_success, audit_den or trace_den or len(augmentation_actions)),
        "augmented_theorem_compile_success_rate": _safe_rate(augmentation_compile_success, len(augmentation_actions)),
        "average_llm_calls_per_proof": avg_llm_calls,
        "average_lean_action_checks_per_proof": avg_action_checks,
    }


def _solution_renderer_metrics(
    *,
    stage_rows: dict[str, list[dict[str, Any]]] | None,
    final_round_map: dict[str, int],
) -> dict[str, Any]:
    natural_rows = _final_stage_rows(_stage_rows(stage_rows, "natural_solution.jsonl"), final_round_map)
    audit_rows = _final_stage_rows(_stage_rows(stage_rows, "solution_render_audit.jsonl"), final_round_map)
    trace_rows = _final_stage_rows(_stage_rows(stage_rows, "solution_trace.jsonl"), final_round_map)
    if not natural_rows and not audit_rows and not trace_rows:
        return {key: None for key in SOLUTION_RENDERER_METRIC_KEYS}

    render_den = len(natural_rows) or len(trace_rows) or len(audit_rows)
    audit_den = len(audit_rows)
    status_rows = natural_rows or trace_rows
    statuses = Counter(str(row.get("proof_status") or "") for row in status_rows)
    render_success = sum(1 for row in natural_rows if _row_bool(row, "render_success") and str(row.get("natural_solution") or "").strip())
    audit_pass = sum(1 for row in audit_rows if _row_bool(row, "audit_pass"))
    final_answer_coverage = sum(1 for row in audit_rows if _row_bool(row, "formula_coverage_pass"))
    law_step_coverage = sum(1 for row in audit_rows if _row_bool(row, "law_step_coverage_pass"))
    unsupported_total = sum(int(row.get("unsupported_formula_count") or 0) for row in audit_rows)

    disclosure_rows = [
        row
        for row in audit_rows
        if any(
            token in str((row.get("details") or {}).get("proof_status") or "")
            for token in ("gap", "partial", "legacy", "proof_failed", "skipped", "not_checked", "algebra_only")
        )
    ]
    if not disclosure_rows:
        disclosure_rows = [
            row
            for row in natural_rows
            if any(
                token in str(row.get("proof_status") or "")
                for token in ("gap", "partial", "legacy", "proof_failed", "skipped", "not_checked", "algebra_only")
            )
        ]
    disclosure_pass = sum(1 for row in disclosure_rows if _row_bool(row, "gap_disclosure_pass") or _row_bool(row, "proof_status_disclosure_pass"))

    partial_statuses = {
        "partial_mechlib_verified",
        "gap_assisted_success",
        "algebra_only_success",
        "legacy_verified_no_audit",
        "proof_failed",
        "proof_skipped_due_to_semantic_fail",
        "not_checked",
    }
    partial_rows = [row for row in natural_rows if str(row.get("proof_status") or "") in partial_statuses]
    partial_explained = sum(1 for row in partial_rows if _row_bool(row, "render_success") and str(row.get("natural_solution") or "").strip())

    return {
        "solution_render_success_rate": _safe_rate(render_success, render_den),
        "solution_render_audit_pass_rate": _safe_rate(audit_pass, audit_den),
        "solution_final_answer_coverage_rate": _safe_rate(final_answer_coverage, audit_den),
        "solution_law_step_coverage_rate": _safe_rate(law_step_coverage, audit_den),
        "solution_gap_disclosure_pass_rate": _safe_rate(disclosure_pass, len(disclosure_rows)),
        "solution_unsupported_formula_avg": round(unsupported_total / audit_den, 6) if audit_den else 0.0,
        "solution_verified_trace_rate": _safe_rate(statuses["fully_mechlib_verified"], len(status_rows)),
        "solution_legacy_no_audit_rate": _safe_rate(statuses["legacy_verified_no_audit"], len(status_rows)),
        "solution_partial_or_failed_explanation_rate": _safe_rate(partial_explained, len(partial_rows)),
    }


def _retrieval_refs_by_sample(retrieval_rows: list[dict[str, Any]]) -> dict[str, set[str]]:
    refs: dict[str, set[str]] = {}
    for row in retrieval_rows:
        sid = str(row.get("sample_id") or "")
        bucket = refs.setdefault(sid, set())
        for item in row.get("law_matched_items", []) if isinstance(row.get("law_matched_items"), list) else []:
            if not isinstance(item, dict):
                continue
            for key in ("theorem_name", "symbol_name", "fq_name"):
                text = str(item.get(key) or "").strip()
                if text:
                    bucket.add(text)
                    bucket.add(text.rsplit(".", 1)[-1])
        for item in row.get("verified_decl_items", []) if isinstance(row.get("verified_decl_items"), list) else []:
            if not isinstance(item, dict):
                continue
            for key in ("theorem_name", "symbol_name", "fq_name"):
                text = str(item.get(key) or "").strip()
                if text:
                    bucket.add(text)
                    bucket.add(text.rsplit(".", 1)[-1])
    return refs


def _statement_uses_mechlib(row: dict[str, Any], refs: set[str]) -> bool:
    verified_refs = row.get("verified_decl_refs")
    if isinstance(verified_refs, list) and verified_refs:
        return True
    symbols = _row_string_list(row, "library_symbols_used")
    return bool(symbols and any(sym in refs for sym in symbols))


def _proof_uses_mechlib(row: dict[str, Any], refs: set[str]) -> bool:
    if not refs:
        return False
    theorems = _row_string_list(row, "theorems_to_apply")
    if theorems and any(name in refs for name in theorems):
        return True
    proof_body = str(row.get("proof_body") or "")
    proof_plan = str(row.get("proof_plan") or "")
    text = f"{proof_body}\n{proof_plan}"
    return any(ref and ref in text for ref in refs)


def build_metrics(
    summaries: list[SampleRunSummary],
    statement_rows: list[dict[str, Any]],
    grounding_rows: list[GroundingResult],
    compile_rows: list[CompileCheckResult],
    semantic_rows: list[SemanticRankResult],
    proof_rows: list[ProofCheckResult],
    retrieval_rows: list[dict[str, Any]] | None = None,
    proof_attempt_rows: list[dict[str, Any]] | None = None,
    stage_rows: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    total = len(summaries)
    final_round_map = {s.sample_id: int(s.final_round_index) for s in summaries}
    final_statement_rows = [
        row for row in statement_rows if final_round_map.get(_row_sample_id(row), 0) == _row_round_index(row)
    ]
    final_compile_rows = [
        row for row in compile_rows if final_round_map.get(_row_sample_id(row), 0) == _row_round_index(row)
    ]
    final_semantic_rows = [
        row for row in semantic_rows if final_round_map.get(_row_sample_id(row), 0) == _row_round_index(row)
    ]
    final_proof_rows = [
        row for row in proof_rows if final_round_map.get(_row_sample_id(row), 0) == _row_round_index(row)
    ]
    compile_check_total = len(final_compile_rows)
    retrieval_refs = _retrieval_refs_by_sample(retrieval_rows or [])
    grounding_success = sum(1 for row in grounding_rows if row.parse_ok)
    statement_generation_success = sum(1 for s in summaries if s.statement_generation_ok)
    compile_by_sample: dict[str, bool] = {}
    for row in final_compile_rows:
        sid = _row_sample_id(row)
        compile_by_sample[sid] = compile_by_sample.get(sid, False) or _row_bool(row, "compile_pass")
    compile_pass = sum(1 for passed in compile_by_sample.values() if passed)
    compile_total = total
    semantic_by_sample: dict[str, bool] = {}
    for row in final_semantic_rows:
        sid = _row_sample_id(row)
        if not sid:
            continue
        semantic_by_sample[sid] = semantic_by_sample.get(sid, False) or bool(row.semantic_pass)
    semantic_pass = sum(1 for passed in semantic_by_sample.values() if passed)
    semantic_total = total
    proof_success = sum(1 for row in final_proof_rows if row.proof_success)
    proof_total = len(final_proof_rows)
    e2e_success = sum(1 for s in summaries if s.end_to_end_ok)
    mechlib_header = sum(1 for row in final_statement_rows if _is_mechlib_header(row.get("lean_header")))
    mechlib_header_total = len(final_statement_rows)
    mechlib_compile_pass = sum(
        1
        for row in final_compile_rows
        if row.compile_pass and (row.backend_used or "").strip().lower() == "mechlib"
    )
    selected_rows = [row for row in final_semantic_rows if row.selected_candidate_id]
    selected_mechlib = sum(
        1
        for row in selected_rows
        if (row.selected_backend or "").strip().lower() == "mechlib"
    )
    candidate_map: dict[tuple[str, int, str], dict[str, Any]] = {}
    for row in final_statement_rows:
        candidate_map[(str(row.get("sample_id") or ""), _row_round_index(row), str(row.get("candidate_id") or ""))] = row
    statement_mechlib_usage = sum(
        1
        for row in final_statement_rows
        if _statement_uses_mechlib(row, retrieval_refs.get(str(row.get("sample_id") or ""), set()))
    )
    selected_statement_mechlib_usage = 0
    library_grounded_selection = 0
    for row in selected_rows:
        sid = _row_sample_id(row)
        cid = str(row.selected_candidate_id or "")
        selected_candidate_row = candidate_map.get((sid, _row_round_index(row), cid))
        if selected_candidate_row and _statement_uses_mechlib(selected_candidate_row, retrieval_refs.get(sid, set())):
            selected_statement_mechlib_usage += 1
        if bool(selected_candidate_row and _statement_uses_mechlib(selected_candidate_row, retrieval_refs.get(sid, set()))) or any(
            isinstance(item, dict) and str(item.get("candidate_id") or "") == cid and float(item.get("library_grounding_score") or 0.0) > 0
            for item in (row.ranking or [])
        ):
            library_grounded_selection += 1
    final_attempt_by_sample: dict[str, dict[str, Any]] = {}
    for row in proof_attempt_rows or []:
        sid = str(row.get("sample_id") or "")
        if final_round_map.get(sid, 0) != _row_round_index(row):
            continue
        current = final_attempt_by_sample.get(sid)
        if current is None or _row_round_index(row) > _row_round_index(current) or int(row.get("attempt_index") or 0) >= int(current.get("attempt_index") or 0):
            final_attempt_by_sample[sid] = row
    proof_mechlib_usage = sum(
        1
        for sid, row in final_attempt_by_sample.items()
        if _proof_uses_mechlib(row, retrieval_refs.get(sid, set()))
    )
    feedback_loop_used = sum(1 for s in summaries if s.feedback_loop_used)

    error_counter: Counter[str] = Counter()
    for s in summaries:
        if s.final_error_type:
            error_counter[s.final_error_type] += 1

    metrics = {
        "num_total_samples": total,
        "grounding_success_rate": _safe_rate(grounding_success, total),
        "statement_generation_success_rate": _safe_rate(statement_generation_success, total),
        "lean_compile_success_rate": _safe_rate(compile_pass, compile_total),
        "semantic_consistency_pass_rate": _safe_rate(semantic_pass, semantic_total),
        "proof_success_rate": _safe_rate(proof_success, proof_total),
        "end_to_end_verified_solve_rate": _safe_rate(e2e_success, total),
        "mechlib_header_rate": _safe_rate(mechlib_header, mechlib_header_total),
        "mechlib_compile_pass_rate": _safe_rate(mechlib_compile_pass, compile_check_total),
        "selected_mechlib_candidate_rate": _safe_rate(selected_mechlib, len(selected_rows)),
        "statement_mechlib_usage_rate": _safe_rate(statement_mechlib_usage, len(final_statement_rows)),
        "selected_statement_mechlib_usage_rate": _safe_rate(selected_statement_mechlib_usage, len(selected_rows)),
        "proof_mechlib_usage_rate": _safe_rate(proof_mechlib_usage, len(final_attempt_by_sample)),
        "library_grounded_selection_rate": _safe_rate(library_grounded_selection, len(selected_rows)),
        "feedback_loop_used_rate": _safe_rate(feedback_loop_used, total),
        "error_type_distribution": dict(error_counter),
    }
    metrics.update(
        _minimal_skeleton_metrics(
            summaries=summaries,
            statement_rows=statement_rows,
            stage_rows=stage_rows,
        )
    )
    metrics.update(
        _llm_guided_e_metrics(
            proof_attempt_rows=proof_attempt_rows,
            proof_rows=proof_rows,
            stage_rows=stage_rows,
            final_round_map=final_round_map,
        )
    )
    metrics.update(_solution_renderer_metrics(stage_rows=stage_rows, final_round_map=final_round_map))
    return metrics
