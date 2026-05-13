from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any


def _to_dict(value: object) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "to_dict"):
        payload = value.to_dict()
        return payload if isinstance(payload, dict) else {}
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return dict(value)
    return {}


def _to_list(values: object) -> list[Any]:
    if values is None:
        return []
    if isinstance(values, list):
        return values
    if isinstance(values, tuple):
        return list(values)
    return []


def _clip_text(value: object, max_chars: int = 900) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars].rstrip()}...<truncated>"


def _compact_row(row: object, keys: tuple[str, ...], *, clip_long_text: bool = True) -> dict[str, Any]:
    payload = _to_dict(row)
    out: dict[str, Any] = {}
    for key in keys:
        value = payload.get(key)
        if value in (None, "", [], {}):
            continue
        if clip_long_text and isinstance(value, str):
            out[key] = _clip_text(value)
        else:
            out[key] = value
    return out


def compact_problem_ir(problem_ir: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(problem_ir or {})
    noisy = {
        "raw_response",
        "Statement",
        "Proof",
        "Header",
        "informal_proof",
        "Informal_proof",
        "source_json",
    }
    return {key: value for key, value in payload.items() if key not in noisy}


def compact_structured_context(context: object, *, max_decls: int = 8, max_schemas: int = 6) -> dict[str, Any]:
    payload = _to_dict(context)
    modeling = _to_dict(payload.get("modeling_context"))
    proof = _to_dict(payload.get("proof_context"))

    def schema_rows(name: str) -> list[dict[str, Any]]:
        rows = _to_list(modeling.get(name))
        return [
            _compact_row(
                row,
                (
                    "id",
                    "schema_id",
                    "topic",
                    "en_name",
                    "zh_name",
                    "statement_text",
                    "verified_decls",
                    "candidate_laws",
                    "target_objects",
                    "used_for",
                ),
            )
            for row in rows[:max_schemas]
        ]

    verified = [
        _compact_row(
            row,
            (
                "fq_name",
                "short_name",
                "statement",
                "status",
                "trust_level",
                "callable_by_llm",
                "needs_review",
                "required_imports",
                "law_schema_ids",
                "problem_schema_ids",
                "proof_hints",
                "proof_fact_allowed",
            ),
        )
        for row in _to_list(proof.get("verified_decls"))[:max_decls]
    ]
    return {
        "modeling_context": {
            "matched_topics": _to_list(modeling.get("matched_topics"))[:max_schemas],
            "concepts": schema_rows("concepts"),
            "law_schemas": schema_rows("law_schemas"),
            "problem_schemas": schema_rows("problem_schemas"),
            "aliases": [
                _compact_row(row, ("alias_name", "alias_fq_name", "alias_to_fq_name"))
                for row in _to_list(modeling.get("aliases"))[:max_schemas]
            ],
        },
        "proof_context": {
            "verified_decls": verified,
            "required_imports": _to_list(proof.get("required_imports"))[:max_decls],
            "proof_hints": _to_list(proof.get("proof_hints"))[:max_decls],
        },
        "forbidden_as_proof_fact": payload.get("forbidden_as_proof_fact") or {},
        "source_counts": payload.get("source_counts") or {},
    }


def compact_model_ir(model_ir: object) -> dict[str, Any]:
    payload = _to_dict(model_ir)
    return {
        "sample_id": payload.get("sample_id"),
        "parse_ok": payload.get("parse_ok"),
        "error": payload.get("error"),
        "objects": payload.get("objects") or [],
        "variables": payload.get("variables") or {},
        "quantity_annotations": [
            _compact_row(
                row,
                (
                    "symbol",
                    "semantic_role",
                    "unit_or_dimension",
                    "lean_type",
                    "confidence",
                    "evidence_text",
                ),
            )
            for row in _to_list(payload.get("quantity_annotations"))
        ],
        "givens": [
            _compact_row(row, ("name", "lean", "role", "source_type", "source_id", "allowed_in_hypotheses"))
            for row in _to_list(payload.get("givens"))
        ],
        "local_definitions": [
            _compact_row(row, ("name", "lean", "role", "source_type", "source_id", "allowed_in_hypotheses"))
            for row in _to_list(payload.get("local_definitions"))
        ],
        "model_instances": [
            _compact_row(
                row,
                (
                    "instance_id",
                    "kind",
                    "natural_language",
                    "variables",
                    "parameters",
                    "planning_schema_id",
                    "expected_claim",
                    "hypothesis_form",
                    "confidence",
                ),
            )
            for row in _to_list(payload.get("model_instances"))
        ],
        "model_interface_instantiations": [
            _compact_row(
                row,
                (
                    "instantiation_id",
                    "kind",
                    "formal_claim",
                    "source_model_instance",
                    "introduced_variable",
                    "proof_fact_allowed",
                    "binding_status",
                ),
            )
            for row in _to_list(payload.get("model_interface_instantiations"))
        ],
        "target": payload.get("target") or {},
        "canonical_target": payload.get("canonical_target") or {},
        "forbidden_as_assumption": payload.get("forbidden_as_assumption") or [],
    }


def compact_evidence_bindings(bindings: object, *, max_items: int | None = None) -> list[dict[str, Any]]:
    rows = _to_list(bindings)
    if max_items is not None:
        rows = rows[:max_items]
    return [
        _compact_row(
            row,
            (
                "binding_id",
                "model_instance_id",
                "planning_schema",
                "verified_decl",
                "decl_statement",
                "decl_status",
                "trust_level",
                "callable_by_llm",
                "required_imports",
                "lean_check_pass",
                "proof_fact_allowed",
                "binding_status",
                "expected_claim",
                "notes",
            ),
        )
        for row in rows
    ]


def compact_controlled_sketch(sketch: object) -> dict[str, Any]:
    payload = _to_dict(sketch)
    return {
        "sample_id": payload.get("sample_id"),
        "schema_version": payload.get("schema_version"),
        "status": payload.get("status"),
        "parse_ok": payload.get("parse_ok"),
        "error": payload.get("error"),
        "proof_steps": payload.get("proof_steps") or [],
        "algebra_obligation": payload.get("algebra_obligation"),
        "blocked_law_steps": payload.get("blocked_law_steps") or [],
        "model_interface_instantiations": payload.get("model_interface_instantiations") or [],
        "repair_directives": payload.get("repair_directives") or [],
        "sketch_variants": [
            _compact_row(
                row,
                (
                    "variant_id",
                    "baseline_id",
                    "variant_policy",
                    "target_form_policy",
                    "hypothesis_policy",
                    "law_policy",
                    "gap_policy",
                    "obligation_policy",
                    "repair_directives",
                    "proof_steps",
                    "algebra_obligation",
                    "blocked_law_steps",
                ),
                clip_long_text=False,
            )
            for row in _to_list(payload.get("sketch_variants"))
        ],
    }


def compact_sketch_audit(audit: object) -> dict[str, Any]:
    return _compact_row(
        audit,
        (
            "sample_id",
            "audit_pass",
            "failure_tags",
            "failure_summary",
            "target_leakage",
            "candidate_answer_leakage",
            "raw_law_equation_in_hypotheses",
            "algebra_result_in_hypotheses",
            "schema_used_as_proof_fact",
            "unbound_verified_decl",
            "missing_provenance",
            "details",
        ),
        clip_long_text=False,
    )


def compact_candidate_for_feedback(candidate: object) -> dict[str, Any]:
    payload = _to_dict(candidate)
    audit = _to_dict(payload.get("skeleton_audit"))
    return {
        "candidate_id": payload.get("candidate_id"),
        "generation_mode": payload.get("generation_mode"),
        "variant_id": payload.get("variant_id"),
        "variant_policy": payload.get("variant_policy"),
        "target_form_policy": payload.get("target_form_policy"),
        "gap_policy": payload.get("gap_policy"),
        "unsupported_claims": payload.get("unsupported_claims") or [],
        "generation_blocked_reason": payload.get("generation_blocked_reason"),
        "verified_decls": payload.get("verified_decls") or [],
        "gap_laws_count": len(_to_list(payload.get("gap_laws"))),
        "proof_obligations_count": len(_to_list(payload.get("proof_obligations"))),
        "fully_mechlib_verified": bool(payload.get("fully_mechlib_verified")),
        "skeleton_audit": {
            "audit_pass": audit.get("audit_pass"),
            "failure_tags": audit.get("failure_tags") or [],
            "failure_summary": audit.get("failure_summary"),
            "details": audit.get("details") or {},
        },
        "target_spec": payload.get("target_spec") or {},
    }


def compact_skeleton_candidate_for_semantic(candidate: object) -> dict[str, Any]:
    payload = _to_dict(candidate)
    return {
        "generation_mode": payload.get("generation_mode"),
        "variant_id": payload.get("variant_id"),
        "target_form_policy": payload.get("target_form_policy"),
        "gap_policy": payload.get("gap_policy"),
        "grounding_status": payload.get("grounding_status"),
        "verified_decls": payload.get("verified_decls") or [],
        "proof_obligations": [
            _compact_row(
                row,
                (
                    "step_id",
                    "kind",
                    "formal_claim",
                    "source_model_instance",
                    "planning_schema",
                    "verified_decl",
                    "binding_status",
                    "expected_claim",
                    "proof_fact_allowed",
                    "required_hypotheses",
                    "produces",
                ),
            )
            for row in _to_list(payload.get("proof_obligations"))
        ],
        "model_predicate_bindings": [
            _compact_row(
                row,
                ("name", "proposition", "verified_decl", "source_model_instance", "proof_fact_allowed"),
            )
            for row in _to_list(payload.get("model_predicate_bindings"))
        ],
        "evidence_bindings": compact_evidence_bindings(payload.get("evidence_bindings"), max_items=8),
        "gap_laws": [
            _compact_row(
                row,
                ("step_id", "source_model_instance", "planning_schema", "expected_claim", "binding_status"),
            )
            for row in _to_list(payload.get("gap_laws"))[:8]
        ],
        "skeleton_audit": compact_sketch_audit(payload.get("skeleton_audit")),
        "typed_binders": [
            _compact_row(row, ("name", "lean_type", "proposition", "type_status", "source_name"))
            for row in _to_list(payload.get("typed_binders"))[:24]
        ],
        "excluded_hypotheses": [
            _compact_row(row, ("name", "role", "reason", "typed_lean"))
            for row in _to_list(payload.get("excluded_hypotheses"))[:16]
        ],
        "target_spec": payload.get("target_spec") or {},
        "generation_blocked_reason": payload.get("generation_blocked_reason"),
        "fully_mechlib_verified": bool(payload.get("fully_mechlib_verified")),
        "gap_laws_count": len(_to_list(payload.get("gap_laws"))),
    }
