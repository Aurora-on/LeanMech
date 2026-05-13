from __future__ import annotations

import re
from typing import Any

from mech_pipeline.knowledge.mechlib_structured import StructuredMechLibContext
from mech_pipeline.types import (
    ControlledSketch,
    ControlledSketchStep,
    EvidenceBinding,
    HypothesisProvenance,
    ModelIR,
    ModelInterfaceInstantiation,
    SketchAuditResult,
)
from mech_pipeline.utils import is_tautological_equality

LAW_STEP_KINDS = {"law_application", "constraint_application", "law_to_equation", "constraint_to_equation"}
PROOF_STEP_KINDS = {"law_to_equation", "constraint_to_equation"}
FORBIDDEN_SKETCH_STEP_KINDS = {"positivity_or_domain", "target_rewrite", "definition_expansion", "substitution"}
NON_HYPOTHESIS_STEP_KINDS = {"algebra_elimination", "target_rewrite", "algebra_obligation"}
METADATA_SOURCE_TYPES = {
    "law_schema",
    "problem_schema",
    "concept",
    "alignment",
    "residual",
    "interface",
    "example_only",
}


def _norm(text: object) -> str:
    return " ".join(str(text or "").strip().lower().split())


def _compact(text: object) -> str:
    return re.sub(r"\s+", "", str(text or "").strip().lower())


def _tokens(text: object) -> set[str]:
    return {tok.lower() for tok in re.findall(r"[A-Za-z_][A-Za-z0-9_']*", str(text or "")) if len(tok) > 1}


def _texts_match(reference: object, candidate: object) -> bool:
    ref = _norm(reference)
    cand = _norm(candidate)
    if not ref or not cand:
        return False
    ref_compact = _compact(reference)
    cand_compact = _compact(candidate)
    if len(ref_compact) >= 4 and len(cand_compact) >= 4:
        if ref_compact in cand_compact or cand_compact in ref_compact:
            return True
    if len(ref) >= 4 and len(cand) >= 4 and (ref in cand or cand in ref):
        return True
    ref_tokens = _tokens(reference)
    cand_tokens = _tokens(candidate)
    if len(ref_tokens) >= 2 and ref_tokens.issubset(cand_tokens):
        return True
    if len(cand_tokens) >= 2 and cand_tokens.issubset(ref_tokens):
        return True
    return False


def _has_relation(text: object) -> bool:
    raw = str(text or "")
    return any(token in raw for token in ("=", "≤", "≥", "<", ">", "\\le", "\\ge"))


def _is_lean_like_formula(text: object) -> bool:
    raw = str(text or "").strip()
    if not raw:
        return False
    low = _norm(raw)
    if any(marker in low for marker in (" from ", " using ", " obtain ", " gives ", " derive ", " because ")):
        return False
    if len(raw.split()) > 80:
        return False
    return any(token in raw for token in ("=", "≠", "<", ">", "≤", "≥", "\\le", "\\ge", "∧", "∨"))


def _is_tautological_equality(text: object) -> bool:
    return is_tautological_equality(text)


def _looks_like_modeling_equation(item: dict[str, Any]) -> bool:
    text = _norm(_hyp_text(item))
    lean = str(item.get("lean") or "")
    if not _is_lean_like_formula(lean) or _is_tautological_equality(lean):
        return False
    markers = (
        "model",
        "interface",
        "net_force",
        "fnet",
        "newton",
        "force_balance",
        "torque_balance",
        "constraint",
        "explicit gap",
    )
    return any(marker in text for marker in markers) or str(item.get("source_type") or "") == "model_ir"


def _looks_like_modeling_interface(item: dict[str, Any]) -> bool:
    formal_claim = str(item.get("formal_claim") or "")
    if not _is_lean_like_formula(formal_claim) or _is_tautological_equality(formal_claim):
        return False
    blob = _norm(
        "\n".join(
            str(item.get(key) or "")
            for key in (
                "instantiation_id",
                "kind",
                "interface_name",
                "parameter_role",
                "source_type",
                "binding_status",
                "notes",
                "formal_claim",
            )
        )
    )
    markers = (
        "model",
        "interface",
        "component",
        "coordinate",
        "constraint",
        "definition",
        "net_force",
        "fnet",
        "force_balance",
        "torque_balance",
        "same_acceleration",
        "common_acceleration",
    )
    return any(marker in blob for marker in markers)


def _target_symbols(model_ir: ModelIR | None) -> set[str]:
    if model_ir is None:
        return set()
    out: set[str] = set()
    canonical = getattr(model_ir, "canonical_target", None)
    if canonical is not None:
        payload = canonical.to_dict() if hasattr(canonical, "to_dict") else dict(canonical or {})
        for value in payload.get("target_variables", []) if isinstance(payload.get("target_variables"), list) else []:
            token = str(value or "").strip()
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_']*", token):
                out.add(token)
    target = model_ir.target or {}
    if isinstance(target, dict):
        for key in ("symbol", "name"):
            value = str(target.get(key) or "").strip()
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_']*", value):
                out.add(value)
        for key in ("variables", "target_variables", "symbols"):
            value = target.get(key)
            if isinstance(value, list):
                for item in value:
                    token = str(item or "").strip()
                    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_']*", token):
                        out.add(token)
        for key in ("components", "component_symbols"):
            value = target.get(key)
            if isinstance(value, list):
                for item in value:
                    token = str(item or "").strip()
                    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_']*", token):
                        out.add(token)
        lean = str(target.get("lean") or "").strip()
        lhs = lean.split("=", 1)[0].strip() if "=" in lean else ""
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_']*", lhs):
            out.add(lhs)
    return out


def _mentions_target(formula: str, target_symbols: set[str]) -> bool:
    if not target_symbols:
        return True
    tokens = set(re.findall(r"[A-Za-z_][A-Za-z0-9_']*", formula or ""))
    return bool(tokens.intersection(target_symbols))


def _target_leakage_match(reference: object, candidate: object) -> bool:
    ref = _norm(reference)
    cand = _norm(candidate)
    if not ref or not cand:
        return False
    marker_present = _has_target_marker(candidate)
    if marker_present and _texts_match(reference, candidate):
        return True
    ref_compact = _compact(reference)
    cand_compact = _compact(candidate)
    if _has_relation(reference) and _has_relation(candidate):
        if len(ref_compact) >= 8 and ref_compact == cand_compact:
            return True
        if len(cand_compact) >= 16 and cand_compact in ref_compact:
            return True
        if len(ref_compact) >= 16 and ref_compact in cand_compact:
            return True
    if len(ref_compact) >= 16 and ref_compact == cand_compact:
        return True
    return False


def _has_target_marker(text: object) -> bool:
    low = _norm(text)
    if not low:
        return False
    if any(phrase in low for phrase in ("candidate answer", "final answer", "final_numeric")):
        return True
    return re.search(r"(?<![A-Za-z0-9_])(target|goal|answer|final)(?![A-Za-z0-9_])", low) is not None


def _is_target_forbidden_text(text: object) -> bool:
    low = _norm(text)
    if not low:
        return False
    return low.startswith(("target", "goal", "candidate_answer", "final", "final_numeric")) or _has_target_marker(low)


def _step_result_refs(step: ControlledSketchStep) -> list[str]:
    refs = [str(step.formal_claim or step.expected_claim or "").strip()]
    if not refs[0]:
        refs = [str(step.claim or "").strip()]
    return [ref for ref in refs if ref]


def _interface_instantiation_payload(item: ModelInterfaceInstantiation | dict[str, Any]) -> dict[str, Any]:
    if isinstance(item, ModelInterfaceInstantiation):
        return item.to_dict()
    if isinstance(item, dict):
        return dict(item)
    return {}


def _as_hypothesis_dict(item: HypothesisProvenance | dict[str, Any]) -> dict[str, Any]:
    if isinstance(item, HypothesisProvenance):
        return item.to_dict()
    if isinstance(item, dict):
        return dict(item)
    return {}


def _hyp_text(item: dict[str, Any]) -> str:
    return "\n".join(
        str(item.get(key) or "")
        for key in ("name", "lean", "role", "source_type", "source_id", "notes")
    )


def _target_texts(model_ir: ModelIR) -> list[str]:
    out: list[str] = []
    canonical = getattr(model_ir, "canonical_target", None)
    if canonical is not None:
        payload = canonical.to_dict() if hasattr(canonical, "to_dict") else dict(canonical or {})
        keys = ("lean_formula", "source_text") if payload.get("parse_ok") is True else ("source_text",)
        for key in keys:
            value = str(payload.get(key) or "").strip()
            if value:
                out.append(value)
        secondary = payload.get("secondary_formulas")
        if payload.get("parse_ok") is True and isinstance(secondary, list):
            out.extend(str(item).strip() for item in secondary if str(item).strip())
        function_formula_ir = payload.get("function_formula_ir")
        if payload.get("parse_ok") is True and isinstance(function_formula_ir, list):
            for item in function_formula_ir:
                if hasattr(item, "to_dict"):
                    row = item.to_dict()
                elif isinstance(item, dict):
                    row = dict(item)
                else:
                    continue
                for key in ("lean_formula", "lhs", "rhs", "source_text"):
                    value = str(row.get(key) or "").strip()
                    if value:
                        out.append(value)
    else:
        target = model_ir.target or {}
        if isinstance(target, dict):
            pieces = [str(value).strip() for value in target.values() if str(value).strip()]
            if len(pieces) > 1:
                out.append(" ".join(pieces))
            for value in pieces:
                if len(value) >= 4:
                    out.append(value)
    for item in model_ir.forbidden_as_assumption:
        text = str(item or "").strip()
        if text and _is_target_forbidden_text(text):
            out.append(text)
    seen: set[str] = set()
    unique: list[str] = []
    for item in out:
        key = _norm(item)
        if key and key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def _context_dict(context: StructuredMechLibContext | dict[str, Any] | None) -> dict[str, Any]:
    if context is None:
        return {}
    if isinstance(context, StructuredMechLibContext):
        return context.to_dict()
    return context


def _metadata_ids(context: StructuredMechLibContext | dict[str, Any] | None) -> set[str]:
    payload = _context_dict(context)
    modeling = payload.get("modeling_context", {}) if isinstance(payload, dict) else {}
    ids: set[str] = set()
    if isinstance(modeling, dict):
        for key in ("concepts", "law_schemas", "problem_schemas", "aliases"):
            rows = modeling.get(key, [])
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                for field in ("id", "schema_id", "alias_name", "alias_fq_name", "alias_to_fq_name"):
                    value = str(row.get(field) or "").strip()
                    if value:
                        ids.add(value)
    forbidden = payload.get("forbidden_as_proof_fact", {}) if isinstance(payload, dict) else {}
    if isinstance(forbidden, dict):
        for value in forbidden.values():
            if isinstance(value, list):
                ids.update(str(item).strip() for item in value if str(item).strip())
            elif str(value or "").strip():
                ids.add(str(value).strip())
    return ids


def _binding_whitelist(bindings: list[EvidenceBinding]) -> set[str]:
    return {
        str(binding.verified_decl).strip()
        for binding in bindings
        if binding.binding_status == "ok" and binding.proof_fact_allowed and binding.verified_decl
    }


def _decl_looks_like_metadata(value: str | None, metadata_ids: set[str]) -> bool:
    decl = str(value or "").strip()
    if not decl:
        return False
    if decl in metadata_ids:
        return True
    low = decl.lower()
    return low.startswith(("law.", "problem.", "concept.", "schema.", "alignment."))


def _failure_summary(tags: list[str]) -> str | None:
    if not tags:
        return None
    return "; ".join(tags)


class SketchAuditor:
    def __init__(self, *, allow_explicit_gap_laws: bool = True) -> None:
        self.allow_explicit_gap_laws = allow_explicit_gap_laws

    def audit(
        self,
        *,
        sample_id: str,
        model_ir: ModelIR | None,
        sketch: ControlledSketch | None,
        evidence_bindings: list[EvidenceBinding],
        structured_mechlib_context: StructuredMechLibContext | dict[str, Any] | None = None,
        hypothesis_provenance: list[HypothesisProvenance | dict[str, Any]] | None = None,
        candidate_answer: str | None = None,
    ) -> SketchAuditResult:
        tags: list[str] = []
        bad_steps: list[dict[str, Any]] = []
        bad_hypotheses: list[dict[str, Any]] = []

        target_leakage = False
        candidate_answer_leakage = False
        raw_law_equation_in_hypotheses = False
        algebra_result_in_hypotheses = False
        schema_used_as_proof_fact = False
        unbound_verified_decl = False
        missing_provenance = False

        model_ir_ok = model_ir is not None and model_ir.parse_ok
        sketch_ok = sketch is not None and sketch.parse_ok
        if not model_ir_ok:
            tags.append("model_ir_parse_failed")
        if not sketch_ok:
            tags.append("controlled_sketch_parse_failed")

        steps: list[ControlledSketchStep] = []
        if sketch is not None:
            if sketch.schema_version >= 2:
                steps = list(sketch.proof_steps)
            else:
                steps = list(sketch.steps) + list(sketch.gap_steps)
        algebra_refs: list[str] = []
        if sketch is not None and sketch.schema_version >= 2 and sketch.algebra_obligation is not None:
            algebra_refs.append(sketch.algebra_obligation.formal_claim)
        interface_instantiations = [
            _interface_instantiation_payload(item)
            for item in (getattr(sketch, "model_interface_instantiations", []) if sketch is not None else [])
        ]
        law_step_refs = [
            ref
            for step in steps
            if step.kind in LAW_STEP_KINDS
            for ref in _step_result_refs(step)
        ]
        algebra_step_refs = [
            ref
            for step in steps
            if step.kind == "algebra_elimination"
            for ref in _step_result_refs(step)
        ] + algebra_refs

        whitelist = _binding_whitelist(evidence_bindings)
        metadata_ids = _metadata_ids(structured_mechlib_context)
        target_symbols = _target_symbols(model_ir)
        registered_hypothesis_names = {
            str(item.get("name") or "")
            for item in [_as_hypothesis_dict(x) for x in (hypothesis_provenance or [])]
            if str(item.get("name") or "")
        }
        registered_hypothesis_names.update(step.produces for step in steps if step.produces)
        registered_hypothesis_names.update(step.step_id for step in steps if step.step_id)
        verified_binding_count = sum(
            1 for binding in evidence_bindings if binding.binding_status == "ok" and binding.proof_fact_allowed
        )

        if sketch is not None and sketch.schema_version >= 2:
            if sketch.status == "invalid":
                tags.append("controlled_sketch_invalid")
            if len(steps) > verified_binding_count + 1:
                tags.append("controlled_sketch_too_many_steps")

        for step in steps:
            step_issues: list[str] = []
            if sketch is not None and sketch.schema_version >= 2 and step.kind not in PROOF_STEP_KINDS:
                step_issues.append("invalid_proof_step_kind")
                if "controlled_sketch_invalid_step_kind" not in tags:
                    tags.append("controlled_sketch_invalid_step_kind")
            if step.kind in FORBIDDEN_SKETCH_STEP_KINDS:
                step_issues.append("forbidden_sketch_step_kind")
                if "controlled_sketch_invalid_step_kind" not in tags:
                    tags.append("controlled_sketch_invalid_step_kind")
            if sketch is not None and sketch.schema_version >= 2:
                formal_claim = str(step.formal_claim or step.expected_claim or step.claim or "")
                if not _is_lean_like_formula(formal_claim):
                    step_issues.append("non_lean_like_formal_claim")
                    if "non_lean_like_formal_claim" not in tags:
                        tags.append("non_lean_like_formal_claim")
                if not step.verified_decl:
                    step_issues.append("proof_step_missing_verified_decl")
                    unbound_verified_decl = True
                    if "unbound_verified_decl" not in tags:
                        tags.append("unbound_verified_decl")
                if step.binding_status == "gap_schema_only":
                    step_issues.append("gap_schema_only_in_proof_steps")
                    schema_used_as_proof_fact = True
                    if "schema_used_as_proof_fact" not in tags:
                        tags.append("schema_used_as_proof_fact")
                if not step.proof_fact_allowed:
                    step_issues.append("proof_step_not_proof_fact_allowed")
                    schema_used_as_proof_fact = True
                    if "schema_used_as_proof_fact" not in tags:
                        tags.append("schema_used_as_proof_fact")
                unknown_required = [
                    name for name in step.required_hypotheses if name and name not in registered_hypothesis_names
                ]
                if unknown_required:
                    step_issues.append("unknown_required_hypotheses")
                    if "unknown_required_hypotheses" not in tags:
                        tags.append("unknown_required_hypotheses")
            if step.kind in LAW_STEP_KINDS:
                if not step.source_model_instance:
                    step_issues.append("missing_source_model_instance")
                if not step.planning_schema:
                    step_issues.append("missing_planning_schema")
                if not step.expected_claim:
                    step_issues.append("missing_expected_claim")
                if step.binding_status == "gap_schema_only" and (step.proof_fact_allowed or step.verified_decl):
                    step_issues.append("gap_schema_only_used_as_proof_fact")
                    schema_used_as_proof_fact = True
                    if "schema_used_as_proof_fact" not in tags:
                        tags.append("schema_used_as_proof_fact")
                if step.proof_fact_allowed and not step.verified_decl:
                    step_issues.append("proof_fact_without_verified_decl")
                    unbound_verified_decl = True
                    if "unbound_verified_decl" not in tags:
                        tags.append("unbound_verified_decl")
                if step.verified_decl and step.verified_decl not in whitelist:
                    step_issues.append("verified_decl_not_in_evidence_whitelist")
                    unbound_verified_decl = True
                    if "unbound_verified_decl" not in tags:
                        tags.append("unbound_verified_decl")
            if _decl_looks_like_metadata(step.verified_decl, metadata_ids):
                step_issues.append("metadata_used_as_verified_decl")
                schema_used_as_proof_fact = True
                if "schema_used_as_proof_fact" not in tags:
                    tags.append("schema_used_as_proof_fact")
            if step.kind in NON_HYPOTHESIS_STEP_KINDS and step.proof_fact_allowed:
                step_issues.append("non_hypothesis_step_marked_as_proof_fact")
                algebra_result_in_hypotheses = True
                if "algebra_result_in_hypotheses" not in tags:
                    tags.append("algebra_result_in_hypotheses")
            if step_issues:
                bad_steps.append({"step_id": step.step_id, "kind": step.kind, "issues": step_issues})

        target_refs = _target_texts(model_ir) if model_ir is not None else []
        for item in interface_instantiations:
            issues: list[str] = []
            step_id = str(item.get("instantiation_id") or "")
            formal_claim = str(item.get("formal_claim") or "").strip()
            if not _is_lean_like_formula(formal_claim):
                issues.append("non_lean_like_formal_claim")
            if item.get("proof_fact_allowed") is True and not str(item.get("verified_constructor") or "").strip():
                issues.append("model_interface_gap_marked_as_proof_fact")
                schema_used_as_proof_fact = True
                if "schema_used_as_proof_fact" not in tags:
                    tags.append("schema_used_as_proof_fact")
            if "MechLib." in formal_claim and not str(item.get("verified_constructor") or "").strip():
                issues.append("unbound_mechlib_reference_in_model_interface")
                unbound_verified_decl = True
                if "unbound_verified_decl" not in tags:
                    tags.append("unbound_verified_decl")
            if any(_target_leakage_match(ref, formal_claim) for ref in target_refs) and not _looks_like_modeling_interface(item):
                issues.append("target_leakage")
                target_leakage = True
                if "target_leakage" not in tags:
                    tags.append("target_leakage")
            if issues:
                bad_steps.append(
                    {
                        "step_id": step_id,
                        "kind": "model_interface_instantiation",
                        "issues": issues,
                    }
                )

        if sketch is not None and sketch.schema_version >= 2 and sketch.algebra_obligation is not None:
            obligation = sketch.algebra_obligation
            obligation_issues: list[str] = []
            if not _is_lean_like_formula(obligation.formal_claim):
                obligation_issues.append("non_lean_like_formal_claim")
                if "non_lean_like_formal_claim" not in tags:
                    tags.append("non_lean_like_formal_claim")
            if not _mentions_target(obligation.formal_claim, target_symbols):
                obligation_issues.append("non_target_final_formula")
                if "non_target_final_formula" not in tags:
                    tags.append("non_target_final_formula")
            known_names = set(registered_hypothesis_names)
            known_names.update(step.produces for step in steps if step.produces)
            known_names.update(step.step_id for step in steps if step.step_id)
            unknown_required = [
                name for name in obligation.required_equations if name and name not in known_names
            ]
            if unknown_required:
                obligation_issues.append("unknown_required_hypotheses")
                if "unknown_required_hypotheses" not in tags:
                    tags.append("unknown_required_hypotheses")
            if obligation_issues:
                bad_steps.append(
                    {
                        "step_id": obligation.obligation_id,
                        "kind": "algebra_obligation",
                        "issues": obligation_issues,
                    }
                )

        hypotheses = [_as_hypothesis_dict(item) for item in (hypothesis_provenance or [])]
        for item in hypotheses:
            hyp_issues: list[str] = []
            required = ("name", "lean", "role", "source_type", "allowed_in_hypotheses")
            if any(key not in item or item.get(key) in (None, "") for key in required):
                missing_provenance = True
                hyp_issues.append("missing_provenance")
                if "missing_provenance" not in tags:
                    tags.append("missing_provenance")

            role = str(item.get("role") or "").strip()
            source_type = str(item.get("source_type") or "").strip()
            allowed = item.get("allowed_in_hypotheses") is True
            text = _hyp_text(item)
            lean_text = str(item.get("lean") or "")

            if role == "target" or (allowed and any(_target_leakage_match(ref, lean_text) for ref in target_refs)):
                target_leakage = True
                hyp_issues.append("target_leakage")
                if "target_leakage" not in tags:
                    tags.append("target_leakage")
            if candidate_answer and _texts_match(candidate_answer, text):
                candidate_answer_leakage = True
                hyp_issues.append("candidate_answer_leakage")
                if "candidate_answer_leakage" not in tags:
                    tags.append("candidate_answer_leakage")
            if allowed and source_type in METADATA_SOURCE_TYPES and role != "explicit_gap_law":
                schema_used_as_proof_fact = True
                hyp_issues.append("metadata_hypothesis")
                if "schema_used_as_proof_fact" not in tags:
                    tags.append("schema_used_as_proof_fact")

            if role == "problem_fact":
                for ref in law_step_refs:
                    if _texts_match(ref, text):
                        if _looks_like_modeling_equation(item):
                            break
                        raw_law_equation_in_hypotheses = True
                        hyp_issues.append("law_application_claim_as_problem_fact")
                        if "raw_law_equation_in_hypotheses" not in tags:
                            tags.append("raw_law_equation_in_hypotheses")
                        break
                for ref in algebra_step_refs:
                    if _texts_match(ref, text):
                        algebra_result_in_hypotheses = True
                        hyp_issues.append("algebra_claim_as_problem_fact")
                        if "algebra_result_in_hypotheses" not in tags:
                            tags.append("algebra_result_in_hypotheses")
                        break
            elif role == "explicit_gap_law":
                if not self.allow_explicit_gap_laws:
                    raw_law_equation_in_hypotheses = True
                    hyp_issues.append("explicit_gap_law_not_allowed")
                    if "raw_law_equation_in_hypotheses" not in tags:
                        tags.append("raw_law_equation_in_hypotheses")
            elif role == "algebra_elimination" and allowed:
                algebra_result_in_hypotheses = True
                hyp_issues.append("algebra_hypothesis")
                if "algebra_result_in_hypotheses" not in tags:
                    tags.append("algebra_result_in_hypotheses")

            if hyp_issues:
                bad_hypotheses.append(
                    {
                        "name": item.get("name"),
                        "role": role,
                        "source_type": source_type,
                        "issues": hyp_issues,
                    }
                )

        details = {
            "bad_steps": bad_steps,
            "bad_hypotheses": bad_hypotheses,
            "verified_decl_whitelist": sorted(whitelist),
            "metadata_ids_checked": sorted(metadata_ids),
        }
        return SketchAuditResult(
            sample_id=sample_id,
            audit_pass=not tags,
            failure_tags=tags,
            failure_summary=_failure_summary(tags),
            target_leakage=target_leakage,
            candidate_answer_leakage=candidate_answer_leakage,
            raw_law_equation_in_hypotheses=raw_law_equation_in_hypotheses,
            algebra_result_in_hypotheses=algebra_result_in_hypotheses,
            schema_used_as_proof_fact=schema_used_as_proof_fact,
            unbound_verified_decl=unbound_verified_decl,
            missing_provenance=missing_provenance,
            details=details,
        )


def sketch_audit_stage_row(sample_id: str, audit: SketchAuditResult, round_index: int | None = None) -> dict[str, Any]:
    row = {"sample_id": sample_id, **audit.to_dict()}
    if round_index is not None:
        row["round_index"] = round_index
    return row
