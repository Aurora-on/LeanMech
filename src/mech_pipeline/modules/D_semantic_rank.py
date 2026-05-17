from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from mech_pipeline.llm_schemas import SemanticRankItemPayload, SemanticRankPayload
from mech_pipeline.prompting import load_template, render_template
from mech_pipeline.prompt_views import (
    compact_problem_ir,
    compact_skeleton_candidate_for_semantic,
)
from mech_pipeline.response_parser import ResponseParseError, parse_json_model
from mech_pipeline.types import CompileCheckResult, GroundingResult, SemanticRankResult, StatementCandidate
from mech_pipeline.utils import normalize_lean_text, redact_leakage_text, sanitize_problem_ir_for_llm

LAW_KEYWORDS = {
    "Kinematics": ["velocity", "acceleration", "displacement", "time", "speed", "v", "a", "s", "x", "t"],
    "NewtonSecondLaw": ["force", "mass", "acceleration", "f", "m", "a", "newton"],
    "WorkEnergy": ["work", "energy", "kinetic", "potential", "w", "e", "k", "u", "v"],
    "EnergyConservation": ["conservation", "energy", "e", "k", "u", "h", "g", "v"],
    "SHO": ["harmonic", "oscillation", "omega", "spring", "x", "k", "m", "t"],
    "ForceAnalysis2D": ["force", "x", "y", "component", "normal", "friction"],
}

PROOFABILITY_DECIMAL_PATTERN = re.compile(r"(?<![A-Za-z0-9_])-?\d+\.\d+(?![A-Za-z0-9_])")
PROOFABILITY_TYPED_TOKENS = ("Mass", "Force", "Acceleration", "Length", "Time", "Speed", "Momentum")
MINIMAL_ALLOWED_HYPOTHESIS_ROLES = {
    "problem_fact",
    "coordinate_convention",
    "local_definition",
    "model_instance",
    "explicit_gap_law",
}
LAW_OBLIGATION_KINDS = {
    "law_to_equation",
    "constraint_to_equation",
    "law_application",
    "constraint_application",
}
PRAGMATIC_GROUNDING_STATUSES = {
    "pragmatic_target_skeleton",
    "partial_mechlib_with_model_gaps",
    "partial_mechlib_with_evidence_gap",
    "vector_scalar_proxy",
}
QUALITATIVE_PSEUDO_PREDICATE_TOKENS = {
    "frictionless",
    "massless",
    "flexible",
    "stationary",
    "level",
    "track_is_level",
    "frictionless_track",
    "massless_string",
    "flexible_string",
    "stationary_pulley",
    "frictionless_pulley",
}

DEFAULT_PROMPT = """__TASK_D_SEMANTIC_RANK__
You are a semantic consistency checker for mechanics formalization.
For each Lean theorem candidate:
1) Translate the theorem declaration back into concise natural language.
2) Compare semantic consistency with the original problem and ProblemIR.
3) Return a score in [0, 1], where 1 means perfectly aligned.
4) Reject trivial statements (x = x, 1 = 1, True).
5) Reject law drift (e.g., Newton-force theorem for pure kinematics).
6) If the theorem is wrong, explicitly identify which part was translated incorrectly.
7) Distinguish target relation carefully:
   - exact: same target as the original problem
   - equivalent: different surface form but semantically equivalent target
   - special_case: only a special case because of extra assumptions or coordinate choices
   - weaker: only a weaker or partial version of the intended target
   - drift: genuinely different target

Output JSON only:
{
  "results": [
    {
      "candidate_id": "c1",
      "back_translation": "...",
      "semantic_score": 0.0,
      "semantic_pass": false,
      "target_relation": "drift",
      "reason": "...",
      "failure_summary": "...",
      "failure_tags": ["wrong_target"],
      "mismatch_fields": ["unknown_target", "known_quantities"],
      "missing_or_incorrect_translations": ["The target quantity should be final speed, not displacement."],
      "suggested_fix_direction": "Keep the same givens, but restate the theorem so the conclusion solves for final speed.",
      "library_grounding_judgment": "weak",
      "grounding_gap_summary": "The candidate states the right algebraic result but does not cite the retrieved theorem.",
      "unsupported_claims": ["unsupported_library_symbol:SomeLemma"]
    }
  ]
}

Original problem:
{{problem_text}}

ProblemIR:
{{problem_ir_json}}

Compile-passed Lean candidates:
{{candidate_payload_json}}

Candidate payloads may include minimal_skeleton metadata such as hypothesis_provenance,
model_predicate_bindings, proof_obligations, evidence_bindings, selected_laws, verified_decls,
gap_laws, skeleton_audit, typed_binders, excluded_hypotheses, and target_spec. In minimal_skeleton
mode, judge the theorem skeleton and proof obligations as a whole. Do not reject a skeleton merely
because a Newton/work-energy/rotation equation is absent from theorem hypotheses when it is present
as a proof_obligation. Still reject target drift, target leakage, candidate-answer hypotheses,
derived law equations placed as ordinary hypotheses, and fabricated natural-language predicates.

Retrieved MechLib context (style and ontology reference only):
{{mechlib_context}}
"""

SEMANTIC_SUB_ERROR_TYPES = {
    "wrong_target",
    "wrong_law",
    "missing_given",
    "unit_or_sign_mismatch",
    "constraint_mismatch",
    "trivial_goal",
}
TARGET_RELATION_EQUIVALENT = {"exact", "equivalent"}
TARGET_RELATION_MISMATCH = {"special_case", "weaker", "drift"}


def _tokenize(text: str) -> set[str]:
    raw = re.findall(r"[A-Za-z0-9_']+", text.lower())
    tokens: set[str] = set()
    for item in raw:
        tok = item.strip("_'")
        if not tok:
            continue
        tokens.add(tok)
        for part in tok.split("_"):
            p = part.strip("_'")
            if p:
                tokens.add(p)
    return tokens


def _symbol_hits(symbol: str, tokens: set[str]) -> bool:
    sym = symbol.lower().strip()
    if not sym:
        return False
    if sym in tokens:
        return True
    parts = [p for p in re.split(r"[^a-z0-9]+", sym) if p]
    if parts and all(p in tokens for p in parts):
        return True
    for tok in tokens:
        if len(tok) < 3:
            continue
        if tok in sym or sym in tok:
            return True
    return False


def _target_match(ir: dict[str, object], theorem_decl: str) -> float:
    unknown = ir.get("unknown_target")
    tokens = _tokenize(theorem_decl)
    if isinstance(unknown, dict):
        symbol = str(unknown.get("symbol") or "").lower()
        description = str(unknown.get("description") or "").lower()
        score = 0.0
        if symbol:
            if symbol in tokens:
                score += 0.6
            else:
                symbol_parts = [part for part in re.split(r"[^a-z0-9]+", symbol) if part]
                if symbol_parts:
                    hit = sum(1 for part in symbol_parts if _symbol_hits(part, tokens))
                    if hit == len(symbol_parts):
                        score += 0.6
                    elif hit > 0:
                        score += round(0.6 * (hit / len(symbol_parts)), 4)
        desc_tokens = _tokenize(description)
        if desc_tokens and desc_tokens.intersection(tokens):
            score += 0.4
        goal_statement = str(ir.get("goal_statement") or "").strip().lower()
        goal_tokens = _tokenize(goal_statement)
        if goal_tokens:
            overlap = len(goal_tokens.intersection(tokens))
            score += min(0.2, round(0.2 * overlap / len(goal_tokens), 4))
        return min(1.0, score)
    return 0.0


def _target_symbol_match(ir: dict[str, object], theorem_decl: str) -> float:
    unknown = ir.get("unknown_target")
    if not isinstance(unknown, dict):
        return 1.0
    symbol = str(unknown.get("symbol") or "").strip()
    if not symbol:
        return 1.0
    tokens = _tokenize(theorem_decl)
    head = symbol.split("(", 1)[0].strip()
    if head:
        normalized_head = head.lower()
        if len(normalized_head) <= 2:
            return 1.0 if normalized_head in tokens else 0.0
        return 1.0 if _symbol_hits(normalized_head, tokens) else 0.0
    return 0.0


def _known_quantity_coverage(ir: dict[str, object], theorem_decl: str) -> float:
    known = ir.get("known_quantities")
    if not isinstance(known, list) or not known:
        return 1.0
    tokens = _tokenize(theorem_decl)
    symbols: list[str] = []
    for item in known:
        if isinstance(item, dict):
            sym = str(item.get("symbol") or "").lower()
            if sym:
                symbols.append(sym)
    if not symbols:
        return 1.0
    hit = sum(1 for sym in symbols if _symbol_hits(sym, tokens))
    return round(hit / len(symbols), 4)


def _law_match(ir: dict[str, object], theorem_decl: str) -> float:
    laws = ir.get("physical_laws")
    if not isinstance(laws, list) or not laws:
        return 0.5
    tokens = _tokenize(theorem_decl)
    total = 0.0
    counted = 0
    for law in laws:
        kws = LAW_KEYWORDS.get(str(law), [])
        if not kws:
            continue
        counted += 1
        kws_set = set(k.lower() for k in kws)
        hit = 0
        for kw in kws_set:
            if kw in tokens or any(kw in tok for tok in tokens):
                hit += 1
        total += min(1.0, hit / max(1, len(kws_set) // 2))
    if counted == 0:
        return 0.5
    return round(total / counted, 4)


def _unit_consistency(ir: dict[str, object], theorem_decl: str) -> float:
    units = ir.get("units")
    if isinstance(units, dict) and units:
        tokens = _tokenize(theorem_decl)
        keys = [str(k).lower() for k in units.keys() if str(k).strip()]
        if not keys:
            return 1.0
        hit = sum(1 for key in keys if _symbol_hits(key, tokens))
        return round(hit / len(keys), 4)
    if isinstance(units, list) and units:
        tokens = _tokenize(theorem_decl)
        symbols: list[str] = []
        for item in units:
            if isinstance(item, dict):
                sym = str(item.get("symbol") or "").lower()
                if sym:
                    symbols.append(sym)
        if not symbols:
            return 1.0
        hit = sum(1 for sym in symbols if _symbol_hits(sym, tokens))
        return round(hit / len(symbols), 4)
    return 1.0


def _assumption_consistency(ir: dict[str, object], theorem_decl: str) -> float:
    assumptions = ir.get("assumptions")
    if not isinstance(assumptions, list) or not assumptions:
        return 1.0
    tokens = _tokenize(theorem_decl)
    hits = 0
    for assumption in assumptions:
        a_tokens = _tokenize(str(assumption))
        if not a_tokens:
            continue
        if tokens.intersection(a_tokens):
            hits += 1
    return round(hits / len(assumptions), 4)


def _semantic_pass(score: float, target_match: float, law_match: float, threshold: float) -> bool:
    if score >= threshold:
        return True
    # Baseline-friendly fallback: allow medium score when target and law both align.
    return score >= 0.5 and target_match >= 0.6 and law_match >= 0.3


def _backend_bias(backend_used: str | None, route_fallback_used: bool) -> float:
    bias = 0.0
    if (backend_used or "").strip().lower() == "mechlib":
        bias += 0.03
    if route_fallback_used and (backend_used or "").strip().lower() != "mechlib":
        bias -= 0.02
    return round(bias, 4)


def _proofability_bias(theorem_decl: str) -> float:
    text = theorem_decl
    lowered = text.lower()
    bias = 0.0
    if "Real.sqrt" in text or re.search(r"\bsqrt\b", lowered):
        bias -= 0.12
    if PROOFABILITY_DECIMAL_PATTERN.search(text):
        bias -= 0.06
    if "->" in text or "∀" in text or "forall" in lowered:
        bias -= 0.06
    if "Quantity.cast" in text:
        bias -= 0.08
    if any(token in text for token in PROOFABILITY_TYPED_TOKENS) and ".val" in text:
        bias += 0.02
    if "/" in text:
        bias -= 0.02
    if (
        "Real.sqrt" not in text
        and "->" not in text
        and "∀" not in text
        and "forall" not in lowered
        and "Quantity.cast" not in text
    ):
        bias += 0.03
    return round(bias, 4)


def _step_payload(step: object) -> dict[str, object]:
    if isinstance(step, dict):
        raw = step
    elif hasattr(step, "to_dict"):
        raw = step.to_dict()
    else:
        return {}
    return {
        "step_id": raw.get("step_id"),
        "kind": raw.get("kind"),
        "formal_claim": raw.get("formal_claim"),
        "expected_claim": raw.get("expected_claim"),
        "verified_decl": raw.get("verified_decl"),
        "proof_fact_allowed": raw.get("proof_fact_allowed"),
        "produces": raw.get("produces"),
    }


def _jsonable(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "to_dict"):
        return _jsonable(value.to_dict())
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return str(value)


def _as_dict_list(value: object) -> list[dict[str, Any]]:
    payload = _jsonable(value)
    if isinstance(payload, dict):
        return [payload]
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _normalize_formula_text(value: object) -> str:
    text = normalize_lean_text(str(value or "")).strip()
    if not text:
        return ""
    text = re.sub(r"\s+", "", text)
    while text.startswith("(") and text.endswith(")") and len(text) > 2:
        inner = text[1:-1]
        depth = 0
        balanced = True
        for ch in inner:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth < 0:
                    balanced = False
                    break
        if not balanced or depth != 0:
            break
        text = inner
    return text


def _split_conjunctive_target(value: object) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    parts = [part.strip() for part in re.split(r"\s+∧\s+|\s+and\s+", text) if part.strip()]
    return parts or [text]


def _target_spec_score(target_spec: object, theorem_decl: str) -> float:
    if not isinstance(target_spec, dict) or not target_spec:
        return 0.0
    goal = _extract_goal_expr(theorem_decl)
    goal_norm = _normalize_formula_text(goal)
    formulas: list[str] = []
    primary = str(target_spec.get("lean_formula") or "").strip()
    if primary:
        formulas.append(primary)
        formulas.extend(_split_conjunctive_target(primary))
    secondary = target_spec.get("secondary_formulas")
    if isinstance(secondary, list):
        formulas.extend(str(item).strip() for item in secondary if str(item).strip())
    formula_norms = [_normalize_formula_text(item) for item in formulas if _normalize_formula_text(item)]
    if goal_norm and formula_norms:
        if goal_norm in formula_norms:
            return 1.0
        if any(item and item in goal_norm for item in formula_norms):
            return 0.9
        if any(goal_norm and goal_norm in item for item in formula_norms):
            return 0.8

    variables = _as_str_list(target_spec.get("target_variables"))
    if variables:
        tokens = _tokenize(goal)
        hits = sum(1 for var in variables if _symbol_hits(var, tokens))
        if hits == len(variables):
            return 0.75
        if hits:
            return round(0.45 + 0.3 * hits / len(variables), 4)
    return 0.0


def _extract_decl_binder_props(theorem_decl: str) -> list[dict[str, str]]:
    decl = theorem_decl.split(":=", 1)[0]
    out: list[dict[str, str]] = []
    for match in re.finditer(r"\(([^()]*)\)", decl):
        body = match.group(1).strip()
        if ":" not in body:
            continue
        names, prop = body.split(":", 1)
        prop = prop.strip()
        if not prop:
            continue
        names_list = [item.strip() for item in names.split() if item.strip()]
        proposition_like = bool(
            re.search(r"(=|<|>|≤|≥|≠|∧|∨|¬)", prop)
            or prop.startswith("MechLib.")
            or any(token in prop.lower() for token in QUALITATIVE_PSEUDO_PREDICATE_TOKENS)
        )
        if not proposition_like:
            continue
        out.append({"names": " ".join(names_list), "prop": prop})
    return out


def _proof_obligation_claim_norms(proof_obligations: list[dict[str, Any]]) -> set[str]:
    out: set[str] = set()
    for step in proof_obligations:
        if str(step.get("kind") or "") not in LAW_OBLIGATION_KINDS:
            continue
        for key in ("formal_claim", "expected_claim", "claim"):
            norm = _normalize_formula_text(step.get(key))
            if norm:
                out.add(norm)
    return out


def _target_formula_norms(target_spec: object, theorem_decl: str) -> set[str]:
    out: set[str] = set()
    if isinstance(target_spec, dict):
        formulas: list[str] = []
        primary = str(target_spec.get("lean_formula") or "").strip()
        if primary:
            formulas.append(primary)
            formulas.extend(_split_conjunctive_target(primary))
        secondary = target_spec.get("secondary_formulas")
        if isinstance(secondary, list):
            formulas.extend(str(item).strip() for item in secondary if str(item).strip())
        out.update(_normalize_formula_text(item) for item in formulas if _normalize_formula_text(item))
    goal = _extract_goal_expr(theorem_decl)
    if goal:
        out.add(_normalize_formula_text(goal))
        out.update(_normalize_formula_text(item) for item in _split_conjunctive_target(goal))
    out.discard("")
    return out


def _has_qualitative_pseudo_predicate(prop: str) -> bool:
    lowered = prop.lower()
    if "mechlib." in lowered:
        return False
    return any(token in lowered for token in QUALITATIVE_PSEUDO_PREDICATE_TOKENS)


def _extract_skeleton_semantic_payload(candidate: StatementCandidate) -> dict[str, Any]:
    generation_mode = getattr(candidate, "generation_mode", None)
    payload: dict[str, Any] = {
        "generation_mode": generation_mode,
        "theorem_decl": candidate.theorem_decl,
        "grounding_status": candidate.grounding_status,
        "grounding_level": getattr(candidate, "grounding_level", None) or candidate.grounding_status,
    }
    if generation_mode != "minimal_skeleton":
        return payload
    for field_name in (
        "hypothesis_provenance",
        "model_predicate_bindings",
        "proof_obligations",
        "evidence_bindings",
        "selected_laws",
        "verified_decls",
        "gap_laws",
        "skeleton_audit",
        "typed_binders",
        "excluded_hypotheses",
        "generation_blocked_reason",
        "target_spec",
        "fully_mechlib_verified",
        "explicit_model_gaps",
        "variant_policy",
    ):
        payload[field_name] = _jsonable(getattr(candidate, field_name, None))
    return payload


def _summarize_proof_obligations(proof_obligations: list[dict[str, Any]]) -> str:
    if not proof_obligations:
        return "no proof obligations"
    law_count = sum(1 for step in proof_obligations if str(step.get("kind") or "") in LAW_OBLIGATION_KINDS)
    gap_count = sum(
        1
        for step in proof_obligations
        if str(step.get("binding_status") or "").strip() in {"gap_schema_only", "decl_not_found", "lean_check_failed"}
        or step.get("proof_fact_allowed") is False and str(step.get("kind") or "") in LAW_OBLIGATION_KINDS
    )
    algebra_count = sum(1 for step in proof_obligations if str(step.get("kind") or "") == "algebra_obligation")
    return f"{law_count} law/constraint obligations, {algebra_count} algebra obligations, {gap_count} gap obligations"


def _summarize_model_predicates(model_predicates: list[dict[str, Any]], evidence_bindings: list[dict[str, Any]]) -> str:
    checked = [
        row
        for row in model_predicates
        if row.get("verified_decl") and row.get("proof_fact_allowed") is not False
    ]
    ok_bindings = [
        row
        for row in evidence_bindings
        if str(row.get("binding_status") or "") == "ok" and row.get("proof_fact_allowed") is True
    ]
    return f"{len(checked)} model predicate binders, {len(ok_bindings)} eligible evidence bindings"


def _summarize_gaps(gap_laws: list[dict[str, Any]], gap_obligation_count: int, generation_blocked_reason: object) -> str:
    reason = str(generation_blocked_reason or "").strip()
    parts = [f"{len(gap_laws)} gap laws", f"{gap_obligation_count} gap proof obligations"]
    if reason:
        parts.append(f"blocked_reason={reason}")
    return "; ".join(parts)


def _score_skeleton_semantics(
    *,
    candidate: StatementCandidate,
    ir: dict[str, object],
    target_match: float,
    theorem_law_match: float,
) -> dict[str, Any]:
    payload = _extract_skeleton_semantic_payload(candidate)
    if payload.get("generation_mode") != "minimal_skeleton":
        return {}

    theorem_decl = str(payload.get("theorem_decl") or "")
    target_spec = payload.get("target_spec")
    proof_obligations = _as_dict_list(payload.get("proof_obligations"))
    evidence_bindings = _as_dict_list(payload.get("evidence_bindings"))
    model_predicates = _as_dict_list(payload.get("model_predicate_bindings"))
    gap_laws = _as_dict_list(payload.get("gap_laws"))
    hypothesis_provenance = _as_dict_list(payload.get("hypothesis_provenance"))
    skeleton_audit = payload.get("skeleton_audit") if isinstance(payload.get("skeleton_audit"), dict) else {}
    grounding_status = str(payload.get("grounding_status") or "").strip()
    pragmatic_grounding = grounding_status in PRAGMATIC_GROUNDING_STATUSES

    target_spec_match = _target_spec_score(target_spec, theorem_decl)
    target_match_score = max(target_match, target_spec_match)

    hard_gate_reasons: list[str] = []
    soft_reasons: list[str] = []
    binder_props = _extract_decl_binder_props(theorem_decl)
    obligation_norms = _proof_obligation_claim_norms(proof_obligations)
    target_norms = _target_formula_norms(target_spec, theorem_decl)
    allowed_modeling_norms: set[str] = set()
    for row in hypothesis_provenance:
        role = str(row.get("role") or "").strip()
        source_type = str(row.get("source_type") or "").strip()
        if role == "target":
            continue
        blob = " ".join(
            str(row.get(key) or "").lower()
            for key in ("name", "role", "source_type", "source_id", "notes")
        )
        if any(token in blob for token in ("target", "goal", "answer", "final", "candidate")):
            continue
        if source_type in {"problem_text", "problem_ir", "model_ir", "gap"} and role in {
            "problem_fact",
            "coordinate_convention",
            "local_definition",
            "model_instance",
            "explicit_gap_law",
        }:
            norm = _normalize_formula_text(row.get("lean"))
            if norm:
                allowed_modeling_norms.add(norm)
    for binder in binder_props:
        prop = str(binder.get("prop") or "")
        norm = _normalize_formula_text(prop)
        if norm and norm in obligation_norms and norm not in allowed_modeling_norms:
            hard_gate_reasons.append("derived_equation_hypothesis_violation")
        if norm and norm in target_norms and norm not in allowed_modeling_norms:
            hard_gate_reasons.append("candidate_answer_hypothesis_violation")
        if _has_qualitative_pseudo_predicate(prop):
            hard_gate_reasons.append("qualitative_pseudo_predicate_hypothesis")

    allowed_bad_roles = [
        row
        for row in hypothesis_provenance
        if row.get("allowed_in_hypotheses") is not False
        and str(row.get("role") or "unknown") not in MINIMAL_ALLOWED_HYPOTHESIS_ROLES
    ]
    if allowed_bad_roles:
        hard_gate_reasons.append("unsupported_hypothesis_role")

    audit_tags = _as_str_list(skeleton_audit.get("failure_tags") if isinstance(skeleton_audit, dict) else None)
    for tag in audit_tags:
        lowered = tag.lower()
        if "raw_law_equation_in_hypotheses" in lowered:
            hard_gate_reasons.append("derived_equation_hypothesis_violation")
        elif "target" in lowered and "hypothes" in lowered:
            hard_gate_reasons.append("candidate_answer_hypothesis_violation")
        elif "qualitative" in lowered:
            hard_gate_reasons.append("qualitative_pseudo_predicate_hypothesis")

    unique_hard_reasons: list[str] = []
    for reason in hard_gate_reasons:
        if reason not in unique_hard_reasons:
            unique_hard_reasons.append(reason)
    hard_gate_reasons = unique_hard_reasons

    hypothesis_penalty = 0.0
    hypothesis_penalty += 0.35 if "derived_equation_hypothesis_violation" in hard_gate_reasons else 0.0
    hypothesis_penalty += 0.3 if "candidate_answer_hypothesis_violation" in hard_gate_reasons else 0.0
    hypothesis_penalty += 0.25 if "qualitative_pseudo_predicate_hypothesis" in hard_gate_reasons else 0.0
    hypothesis_penalty += min(0.25, 0.08 * len(allowed_bad_roles))
    hypothesis_minimality_score = _clamp_score(1.0 - hypothesis_penalty)

    law_obligations = [step for step in proof_obligations if str(step.get("kind") or "") in LAW_OBLIGATION_KINDS]
    gap_obligations = [
        step
        for step in law_obligations
        if str(step.get("binding_status") or "").strip() in {"gap_schema_only", "decl_not_found", "lean_check_failed"}
        or step.get("proof_fact_allowed") is False
        or not str(step.get("verified_decl") or "").strip()
    ]
    eligible_obligations = [
        step
        for step in law_obligations
        if step not in gap_obligations
        and str(step.get("verified_decl") or "").strip()
        and step.get("proof_fact_allowed") is True
    ]
    algebra_obligations = [step for step in proof_obligations if str(step.get("kind") or "") == "algebra_obligation"]
    if gap_obligations:
        if not pragmatic_grounding:
            hard_gate_reasons.append("proof_obligation_gap_violation")
        soft_reasons.append("evidence_gap")
    if len(algebra_obligations) > 1:
        hard_gate_reasons.append("multiple_algebra_obligations")

    has_law_problem = isinstance(ir.get("physical_laws"), list) and bool(ir.get("physical_laws"))
    if law_obligations:
        proof_obligation_coverage_score = round(len(eligible_obligations) / len(law_obligations), 4)
        if pragmatic_grounding and proof_obligation_coverage_score == 0.0:
            proof_obligation_coverage_score = 0.55
    elif has_law_problem:
        proof_obligation_coverage_score = 0.55 if pragmatic_grounding else 0.0
        if not payload.get("generation_blocked_reason"):
            soft_reasons.append("missing_proof_obligations")
    else:
        proof_obligation_coverage_score = 1.0

    ok_bindings = [
        row
        for row in evidence_bindings
        if str(row.get("binding_status") or "") == "ok" and row.get("proof_fact_allowed") is True
    ]
    ok_model_predicates = [
        row
        for row in model_predicates
        if str(row.get("verified_decl") or "").strip() and row.get("proof_fact_allowed") is not False
    ]
    verified_decls = _as_str_list(payload.get("verified_decls"))
    if ok_model_predicates or ok_bindings:
        denominator = max(len(evidence_bindings), len(model_predicates), 1)
        evidence_binding_score = min(1.0, round((len(ok_bindings) + len(ok_model_predicates)) / denominator, 4))
    elif gap_laws or gap_obligations or payload.get("generation_blocked_reason") == "blocked_by_evidence_gap":
        evidence_binding_score = 0.15
        soft_reasons.append("evidence_gap")
    elif verified_decls:
        evidence_binding_score = 0.65
    else:
        evidence_binding_score = 0.5

    gap_penalty = min(0.35, round(0.08 * len(gap_laws) + 0.12 * len(gap_obligations), 4))
    if pragmatic_grounding:
        gap_penalty = min(gap_penalty, 0.12)
    if payload.get("generation_blocked_reason") == "blocked_by_evidence_gap":
        gap_penalty = max(gap_penalty, 0.2)
        soft_reasons.append("evidence_gap")

    skeleton_semantic_score = _clamp_score(
        round(
            0.42 * target_match_score
            + 0.18 * hypothesis_minimality_score
            + 0.24 * proof_obligation_coverage_score
            + 0.16 * evidence_binding_score
            - gap_penalty,
            4,
        )
    )

    effective_law_match = max(theorem_law_match, proof_obligation_coverage_score)
    all_reasons = []
    for reason in [*hard_gate_reasons, *soft_reasons]:
        if reason not in all_reasons:
            all_reasons.append(reason)

    return {
        "skeleton_payload": payload,
        "skeleton_semantic_score": skeleton_semantic_score,
        "target_match_score": round(target_match_score, 4),
        "hypothesis_minimality_score": round(hypothesis_minimality_score, 4),
        "proof_obligation_coverage_score": round(proof_obligation_coverage_score, 4),
        "evidence_binding_score": round(evidence_binding_score, 4),
        "gap_penalty": gap_penalty,
        "skeleton_hard_gate_reasons": hard_gate_reasons,
        "skeleton_warning_reasons": soft_reasons,
        "skeleton_failure_reasons": all_reasons,
        "proof_obligation_summary": _summarize_proof_obligations(proof_obligations),
        "model_predicate_binding_summary": _summarize_model_predicates(model_predicates, evidence_bindings),
        "gap_summary": _summarize_gaps(gap_laws, len(gap_obligations), payload.get("generation_blocked_reason")),
        "effective_law_match": round(effective_law_match, 4),
    }


def _minimal_candidate_metadata(candidate: StatementCandidate) -> dict[str, object]:
    proof_obligations = [
        payload
        for payload in (_step_payload(step) for step in (getattr(candidate, "proof_obligations", []) or []))
        if payload
    ]
    gap_laws = getattr(candidate, "gap_laws", []) or []
    explicit_model_gaps = getattr(candidate, "explicit_model_gaps", []) or []
    return {
        "generation_mode": getattr(candidate, "generation_mode", None),
        "variant_id": getattr(candidate, "variant_id", None),
        "variant_policy": getattr(candidate, "variant_policy", None),
        "target_form_policy": getattr(candidate, "target_form_policy", None),
        "gap_policy": getattr(candidate, "gap_policy", None),
        "repair_directives": list(getattr(candidate, "repair_directives", []) or []),
        "grounding_status": candidate.grounding_status,
        "grounding_level": getattr(candidate, "grounding_level", None) or candidate.grounding_status,
        "verified_decls": list(getattr(candidate, "verified_decls", []) or []),
        "proof_obligations": proof_obligations,
        "hypothesis_provenance": _jsonable(getattr(candidate, "hypothesis_provenance", []) or []),
        "model_predicate_bindings": _jsonable(getattr(candidate, "model_predicate_bindings", []) or []),
        "evidence_bindings": _jsonable(getattr(candidate, "evidence_bindings", []) or []),
        "selected_laws": list(getattr(candidate, "selected_laws", []) or []),
        "gap_laws": _jsonable(gap_laws),
        "skeleton_audit": _jsonable(getattr(candidate, "skeleton_audit", None)),
        "typed_binders": _jsonable(getattr(candidate, "typed_binders", []) or []),
        "excluded_hypotheses": _jsonable(getattr(candidate, "excluded_hypotheses", []) or []),
        "gap_laws_count": len(gap_laws),
        "explicit_model_gaps_count": len(explicit_model_gaps),
        "fully_mechlib_verified": bool(getattr(candidate, "fully_mechlib_verified", False)),
        "target_spec": dict(getattr(candidate, "target_spec", {}) or {}),
        "generation_blocked_reason": getattr(candidate, "generation_blocked_reason", None),
    }


def _minimal_grounding_bias(candidate: StatementCandidate) -> float:
    if getattr(candidate, "generation_mode", None) != "minimal_skeleton":
        return 0.0
    if bool(getattr(candidate, "fully_mechlib_verified", False)):
        return 0.06
    if getattr(candidate, "explicit_model_gaps", None):
        return 0.02
    if getattr(candidate, "verified_decls", None):
        return 0.04
    if bool(candidate.gap_schema_only):
        return -0.02
    return 0.0


def _as_float(value: object, default: float = 0.0) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return default
    return default


def _as_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if value == 1:
            return True
        if value == 0:
            return False
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "1"}:
            return True
        if lowered in {"false", "no", "0"}:
            return False
    return None


def _clamp_score(value: float) -> float:
    return max(0.0, min(1.0, value))


def _as_str_list(value: object) -> list[str]:
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            text = str(item).strip()
            if text:
                out.append(text)
        return out
    if isinstance(value, dict):
        out = []
        for key, item in value.items():
            if item in (None, "", [], {}, False):
                continue
            text = str(key).strip()
            if text:
                out.append(text)
        return out
    return []


def _normalize_failure_tags(*values: object) -> list[str]:
    tags: list[str] = []
    seen: set[str] = set()
    for value in values:
        for item in _as_str_list(value):
            normalized = re.sub(r"\s+", "_", item.strip().lower())
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            tags.append(normalized)
    return tags


def _extract_context_refs(mechlib_context: str) -> set[str]:
    refs: set[str] = set()
    patterns = [
        r"theorem_name=([A-Za-z_][A-Za-z0-9_']*)",
        r"symbol=([A-Za-z_][A-Za-z0-9_']*)",
        r"fq_name=([A-Za-z_][A-Za-z0-9_'.]*)",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, mechlib_context or ""):
            value = match.group(1)
            refs.add(value)
            refs.add(value.rsplit(".", 1)[-1])
    return refs


def _looks_like_direct_translation(
    *,
    target_match: float,
    known_quantity_coverage: float,
    law_match: float,
    unsupported_claims: list[str],
) -> bool:
    return (
        target_match >= 0.75
        and known_quantity_coverage >= 0.5
        and law_match >= 0.3
        and not unsupported_claims
    )


def _library_grounding_score(
    *,
    ir: dict[str, object],
    mechlib_context: str,
    library_symbols_used: list[str],
    unsupported_claims: list[str],
    verified_decl_refs: list[dict[str, Any]],
    gap_schema_only: bool,
    target_match: float,
    known_quantity_coverage: float,
    law_match: float,
) -> tuple[float, list[str], bool, str | None]:
    refs = _extract_context_refs(mechlib_context)
    matched = [sym for sym in library_symbols_used if sym in refs]
    direct_translation = _looks_like_direct_translation(
        target_match=target_match,
        known_quantity_coverage=known_quantity_coverage,
        law_match=law_match,
        unsupported_claims=unsupported_claims,
    )
    has_law_problem = isinstance(ir.get("physical_laws"), list) and bool(ir.get("physical_laws"))
    score = 0.0
    if verified_decl_refs:
        score += min(0.28, 0.14 + 0.06 * len(verified_decl_refs))
    elif matched:
        score += min(0.22, 0.1 + 0.06 * len(matched))
    elif has_law_problem and refs and not direct_translation:
        score -= 0.12
    if gap_schema_only and not verified_decl_refs:
        score -= 0.18
    if unsupported_claims:
        score -= min(0.25, 0.05 + 0.06 * len(unsupported_claims))
    if (matched or verified_decl_refs) and law_match >= 0.25:
        score += 0.06
    if not has_law_problem and score < 0:
        score = 0.0
    score = round(score, 4)
    if gap_schema_only and not verified_decl_refs:
        gap = "Only schema metadata matched; no verified MechLib declaration was bound."
    elif unsupported_claims:
        gap = "Candidate contains unsupported library-grounding claims."
    elif has_law_problem and refs and not matched and not direct_translation:
        gap = "Semantic content is plausible, but the candidate does not ground the law with retrieved library theorems."
    else:
        gap = None
    return score, matched, direct_translation, gap


def _normalize_target_relation(value: object) -> str | None:
    text = str(value or "").strip().lower()
    if not text:
        return None
    aliases = {
        "same": "exact",
        "exact_match": "exact",
        "equivalent_form": "equivalent",
        "equivalent_target": "equivalent",
        "special-case": "special_case",
        "specialcase": "special_case",
        "partial": "weaker",
        "partial_answer": "weaker",
        "weaker_equivalent_form": "weaker",
        "wrong_target": "drift",
        "off_topic": "drift",
        "target_drift": "drift",
    }
    normalized = aliases.get(text, text)
    if normalized in TARGET_RELATION_EQUIVALENT or normalized in TARGET_RELATION_MISMATCH:
        return normalized
    return None


def _infer_target_relation(
    *,
    model_target_relation: object,
    llm_pass: bool | None,
    failure_tags: list[str],
    mismatch_fields: list[str],
    llm_reason: str,
    target_match: float,
    known_quantity_coverage: float,
    law_match: float,
) -> str | None:
    normalized = _normalize_target_relation(model_target_relation)
    if normalized is not None:
        return normalized

    tags_text = " ".join(failure_tags + mismatch_fields).lower()
    reason = llm_reason.lower()
    if "wrong_target" in tags_text or "off_topic" in tags_text or "law_drift" in tags_text:
        return "drift"
    if "special_case" in tags_text or "special_case_only" in tags_text:
        return "special_case"
    if "weaker" in tags_text or "partial" in tags_text:
        return "weaker"
    if any(phrase in reason for phrase in ["special case", "coordinate choice", "zero-initial-angle case"]):
        return "special_case"
    if any(phrase in reason for phrase in ["weaker", "partial answer", "partial version"]):
        return "weaker"
    if llm_pass is True and law_match >= 0.3:
        if target_match >= 0.4:
            return "exact"
        if known_quantity_coverage >= 0.8:
            return "equivalent"
        return "drift"
    return None


def _derive_mismatch_fields(
    *,
    llm_fields: object,
    hard_gate_reasons: list[str],
    trivial_goal: bool,
) -> list[str]:
    fields = _as_str_list(llm_fields)
    normalized = {item.lower(): item for item in fields}
    if "target_mismatch" in hard_gate_reasons and "unknown_target" not in normalized:
        fields.append("unknown_target")
    if "law_mismatch" in hard_gate_reasons and "physical_laws" not in normalized:
        fields.append("physical_laws")
    if "known_quantity_mismatch" in hard_gate_reasons and "known_quantities" not in normalized:
        fields.append("known_quantities")
    if trivial_goal and "goal" not in normalized:
        fields.append("goal")
    return fields


def _is_coordinate_sign_convention_equivalence(
    *,
    target_relation: str | None,
    failure_tags: list[str],
    mismatch_fields: list[str],
    llm_reason: str,
    failure_summary: str = "",
) -> bool:
    """Recognize sign-only differences explained by an explicit coordinate convention.

    Archive mechanics problems often state a physical direction in words ("moves left")
    while the formal target uses a coordinate attached to the moving object, where that
    direction is positive.  This is an acceptable equivalent target only when the
    semantic judge itself describes the issue as a coordinate/orientation convention,
    not a unit error or a wrong-target error.
    """
    relation = _normalize_target_relation(target_relation)
    if relation not in TARGET_RELATION_EQUIVALENT:
        return False
    text = " ".join(failure_tags + mismatch_fields + [llm_reason, failure_summary]).lower()
    if any(token in text for token in ("wrong_target", "target_mismatch", "unknown_target", "unit")):
        return False
    sign_like = any(token in text for token in ("sign", "leftward", "rightward", "positive direction"))
    convention_like = any(
        token in text
        for token in (
            "coordinate",
            "orientation",
            "axis",
            "direction choice",
            "sign convention",
            "absorbed",
        )
    )
    return sign_like and convention_like


def _infer_semantic_sub_error_type(
    *,
    model_sub_error_type: str | None,
    failure_tags: list[str],
    mismatch_fields: list[str],
    hard_gate_reasons: list[str],
    trivial_goal: bool,
    llm_reason: str,
) -> str | None:
    candidate = str(model_sub_error_type or "").strip()
    if candidate in SEMANTIC_SUB_ERROR_TYPES:
        return candidate

    text = " ".join(failure_tags + mismatch_fields + hard_gate_reasons + [llm_reason.lower()])
    lowered_reason = llm_reason.lower()
    negative_trivial_claim = any(
        phrase in lowered_reason
        for phrase in [
            "not a tautology",
            "not tautological",
            "not trivial",
            "is not trivial",
            "is not a tautology",
            "not a trivial",
        ]
    )
    if trivial_goal or "trivial_goal" in text or ("tautolog" in text and not negative_trivial_claim):
        return "trivial_goal"
    if (
        "wrong_target" in text
        or "target_mismatch" in text
        or "unknown_target" in text
        or "target quantity" in text
    ):
        return "wrong_target"
    if "wrong_law" in text or "law_mismatch" in text or "physical_laws" in text or "law drift" in text:
        return "wrong_law"
    if "unit" in text or "sign" in text:
        return "unit_or_sign_mismatch"
    if "constraint" in text or "assumption" in text:
        return "constraint_mismatch"
    if "known_quantity_mismatch" in text or "known_quantities" in text or "missing_given" in text:
        return "missing_given"
    return None


def _extract_goal_expr(theorem_decl: str) -> str:
    header = theorem_decl
    if ":=" in header:
        header = header.split(":=", 1)[0]
    if ":" not in header:
        return ""
    return header.rsplit(":", 1)[1].strip()


def _is_trivial_goal(goal_expr: str) -> bool:
    if not goal_expr:
        return True
    low = goal_expr.strip().lower()
    if low in {"true", "prop", "(true)", "(prop)"}:
        return True
    if low in {"false", "(false)"}:
        return True

    raw = goal_expr.strip()
    # Strip one outer pair of parentheses for common shapes like "(a = a)".
    if raw.startswith("(") and raw.endswith(")") and len(raw) > 2:
        raw = raw[1:-1].strip()
    m = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_']*)\s*=\s*([A-Za-z_][A-Za-z0-9_']*)", raw)
    if m and m.group(1) == m.group(2):
        return True
    m_num = re.fullmatch(r"(-?\d+(?:\.\d+)?)\s*=\s*(-?\d+(?:\.\d+)?)", raw)
    if m_num and m_num.group(1) == m_num.group(2):
        return True
    return False


def _has_unknown_target(ir: dict[str, object]) -> bool:
    unknown = ir.get("unknown_target")
    if isinstance(unknown, dict):
        symbol = str(unknown.get("symbol") or "").strip()
        desc = str(unknown.get("description") or "").strip()
        return bool(symbol or desc)
    return False


def _hard_semantic_gate(
    *,
    ir: dict[str, object],
    target_match: float,
    target_symbol_match: float,
    known_quantity_coverage: float,
    law_match: float,
    trivial_goal: bool,
    target_relation: str | None = None,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if trivial_goal:
        reasons.append("trivial_goal")

    relation = _normalize_target_relation(target_relation)
    if _has_unknown_target(ir) and relation in TARGET_RELATION_MISMATCH:
        reasons.append("target_mismatch")
    elif _has_unknown_target(ir) and relation not in TARGET_RELATION_EQUIVALENT and target_match < 0.4:
        reasons.append("target_mismatch")

    laws = ir.get("physical_laws")
    if isinstance(laws, list) and laws and law_match < 0.25:
        reasons.append("law_mismatch")

    known = ir.get("known_quantities")
    if isinstance(known, list) and known and known_quantity_coverage < 0.2:
        # Legacy B often compresses problem givens into a modeling equation instead of
        # restating every known quantity.  If the semantic judge says the target is
        # exact/equivalent and the theorem text still has a reasonable target match,
        # treat sparse known-quantity surface coverage as a score penalty/feedback tag
        # rather than a hard gate.  Wrong-target and weak-target candidates remain
        # blocked by the target/law/trivial gates above.
        target_is_semantically_aligned = relation in TARGET_RELATION_EQUIVALENT and target_match >= 0.5
        if not target_is_semantically_aligned:
            reasons.append("known_quantity_mismatch")

    return len(reasons) == 0, reasons


def _relax_pragmatic_hard_gate(
    *,
    grounding_status: object,
    hard_gate_reasons: list[str],
    target_relation: str | None,
    target_match: float,
    target_symbol_match: float,
    trivial_goal: bool,
) -> tuple[bool, list[str]]:
    status = str(grounding_status or "").strip()
    if status not in PRAGMATIC_GROUNDING_STATUSES:
        return len(hard_gate_reasons) == 0, hard_gate_reasons
    relation = _normalize_target_relation(target_relation)
    target_ok = (
        relation in TARGET_RELATION_EQUIVALENT
        or (relation not in TARGET_RELATION_MISMATCH and target_match >= 0.72 and target_symbol_match >= 0.5)
    )
    if not target_ok or trivial_goal:
        return len(hard_gate_reasons) == 0, hard_gate_reasons
    relaxed = [
        reason
        for reason in hard_gate_reasons
        if reason
        not in {
            "law_mismatch",
            "known_quantity_mismatch",
            "proof_obligation_gap_violation",
            "missing_proof_obligations",
        }
    ]
    return len(relaxed) == 0, relaxed


def _parse_llm_results(raw_text: str) -> dict[str, dict[str, Any]]:
    try:
        parsed = parse_json_model(raw_text, SemanticRankPayload)
    except ResponseParseError:
        return {}

    rows_obj: list[SemanticRankItemPayload] = []
    if parsed.results:
        rows_obj = parsed.results
    elif parsed.ranking:
        rows_obj = parsed.ranking
    elif parsed.candidates:
        rows_obj = parsed.candidates
    elif parsed.items:
        rows_obj = parsed.items
    elif parsed.candidate_id:
        rows_obj = [
            SemanticRankItemPayload(
                candidate_id=parsed.candidate_id,
                back_translation=parsed.back_translation,
                natural_language_statement=parsed.natural_language_statement,
                translation=parsed.translation,
                semantic_score=parsed.semantic_score,
                consistency_score=parsed.consistency_score,
                semantic_pass=parsed.semantic_pass,
                reason=parsed.reason,
                semantic_analysis=parsed.semantic_analysis,
                comparison=parsed.comparison,
            )
        ]

    out: dict[str, dict[str, Any]] = {}
    for row in rows_obj:
        cid = str(row.candidate_id).strip()
        if not cid:
            continue
        out[cid] = row.model_dump()
    return out


class ModuleD:
    def __init__(self, model_client, prompt_path: Path, pass_threshold: float) -> None:
        self.model_client = model_client
        self.prompt_text = load_template(prompt_path, DEFAULT_PROMPT)
        self.pass_threshold = pass_threshold

    def run(
        self,
        grounding: GroundingResult,
        candidates: list[StatementCandidate],
        compile_checks: list[CompileCheckResult],
        problem_text: str | None = None,
        mechlib_context: str = "(none)",
    ) -> SemanticRankResult:
        ir = grounding.problem_ir or {}
        status_map = {row.candidate_id: row for row in compile_checks}
        assumptions_len_map = {candidate.candidate_id: len(candidate.assumptions) for candidate in candidates}
        compile_pass_candidates = [
            c for c in candidates if status_map.get(c.candidate_id) and status_map[c.candidate_id].compile_pass
        ]
        if not compile_pass_candidates:
            return SemanticRankResult(
                sample_id=grounding.sample_id,
                selected_candidate_id=None,
                selected_theorem_decl=None,
                semantic_pass=False,
                ranking=[],
                selected_backend=None,
                selected_route_reason=None,
                selected_route_fallback_used=False,
                error="semantic_drift",
                failure_summary="No compile-passed candidates available for semantic ranking.",
                failure_tags=["no_compile_pass_candidates"],
                failure_details={"ranking_stage": "skipped_due_to_no_compile_pass_candidates"},
            )

        ranking: list[dict[str, object]] = []
        for candidate in compile_pass_candidates:
            goal_expr = _extract_goal_expr(candidate.theorem_decl)
            trivial_goal = _is_trivial_goal(goal_expr)
            t = _target_match(ir, candidate.theorem_decl)
            target_symbol_match = _target_symbol_match(ir, candidate.theorem_decl)
            k = _known_quantity_coverage(ir, candidate.theorem_decl)
            theorem_law_match = _law_match(ir, candidate.theorem_decl)
            l = theorem_law_match
            u = _unit_consistency(ir, candidate.theorem_decl)
            a = _assumption_consistency(ir, candidate.theorem_decl)
            score_rule = round(0.35 * t + 0.25 * k + 0.2 * l + 0.1 * u + 0.1 * a, 4)
            if trivial_goal:
                score_rule = min(score_rule, 0.2)
            skeleton_semantic = _score_skeleton_semantics(
                candidate=candidate,
                ir=ir,
                target_match=t,
                theorem_law_match=theorem_law_match,
            )
            if skeleton_semantic:
                t = max(t, _as_float(skeleton_semantic.get("target_match_score"), t))
                l = max(l, _as_float(skeleton_semantic.get("effective_law_match"), l))
                score_rule = _as_float(skeleton_semantic.get("skeleton_semantic_score"), score_rule)
                if trivial_goal:
                    score_rule = min(score_rule, 0.2)
            library_grounding_score, grounded_symbols, direct_translation, grounding_gap_summary = _library_grounding_score(
                ir=ir,
                mechlib_context=mechlib_context,
                library_symbols_used=list(candidate.library_symbols_used),
                unsupported_claims=list(candidate.unsupported_claims),
                verified_decl_refs=list(candidate.verified_decl_refs),
                gap_schema_only=bool(candidate.gap_schema_only),
                target_match=t,
                known_quantity_coverage=k,
                law_match=l,
            )
            status = status_map.get(candidate.candidate_id)
            backend_used = str(getattr(status, "backend_used", "") or "")
            route_reason = str(getattr(status, "route_reason", "") or "")
            route_fallback_used = bool(getattr(status, "route_fallback_used", False))
            backend_bias = _backend_bias(backend_used, route_fallback_used)
            proofability_bias = _proofability_bias(candidate.theorem_decl)
            minimal_metadata = _minimal_candidate_metadata(candidate)
            skeleton_grounding_bias = _minimal_grounding_bias(candidate)
            ranking.append(
                {
                    "candidate_id": candidate.candidate_id,
                    "theorem_decl": candidate.theorem_decl,
                    **minimal_metadata,
                    "backend_used": backend_used,
                    "route_reason": route_reason,
                    "route_fallback_used": route_fallback_used,
                    "backend_bias": backend_bias,
                    "proofability_bias": proofability_bias,
                    "skeleton_grounding_bias": skeleton_grounding_bias,
                    "supporting_facts": list(candidate.supporting_facts),
                    "fact_sources": list(candidate.fact_sources),
                    "library_symbols_used": list(candidate.library_symbols_used),
                    "grounding_explanation": candidate.grounding_explanation,
                    "unsupported_claims": list(candidate.unsupported_claims),
                    "verified_decl_refs": list(candidate.verified_decl_refs),
                    "schema_refs": list(candidate.schema_refs),
                    "alias_refs": list(candidate.alias_refs),
                    "grounding_status": candidate.grounding_status,
                    "gap_schema_only": bool(candidate.gap_schema_only),
                    "grounded_library_symbols": grounded_symbols,
                    "direct_translation": direct_translation,
                    "library_grounding_score": library_grounding_score,
                    "grounding_gap_summary": grounding_gap_summary,
                    "goal_expr": goal_expr,
                    "trivial_goal": trivial_goal,
                    "target_match": t,
                    "target_symbol_match": target_symbol_match,
                    "known_quantity_coverage": k,
                    "law_match": l,
                    "theorem_law_match": theorem_law_match,
                    "unit_consistency": u,
                    "assumption_consistency": a,
                    "semantic_score_rule": score_rule,
                    "semantic_score_llm": None,
                    "semantic_score": score_rule,
                    "semantic_rank_score": round(
                        score_rule
                        + backend_bias
                        + proofability_bias
                        + library_grounding_score
                        + skeleton_grounding_bias,
                        4,
                    ),
                    "semantic_pass_llm": None,
                    "semantic_pass": _semantic_pass(score_rule, t, l, self.pass_threshold),
                    "back_translation_text": "",
                    "semantic_reason": "",
                    "failure_summary": "",
                    "failure_tags": [],
                    "mismatch_fields": [],
                    "missing_or_incorrect_translations": [],
                    "suggested_fix_direction": "",
                    "target_relation": None,
                    "sub_error_type": None,
                    "semantic_source": "rule_only",
                    **{
                        key: value
                        for key, value in skeleton_semantic.items()
                        if key != "skeleton_payload"
                    },
                }
            )

        llm_error: str | None = None
        llm_rows: dict[str, dict[str, Any]] = {}
        safe_problem_text = redact_leakage_text(problem_text or "")
        safe_problem_ir = compact_problem_ir(sanitize_problem_ir_for_llm(ir))
        prompt = render_template(
            self.prompt_text,
            {
                "problem_text": safe_problem_text,
                "problem_ir_json": json.dumps(safe_problem_ir, ensure_ascii=False, indent=2),
                "candidate_payload_json": json.dumps(
                    [
                        {
                            "candidate_id": c.candidate_id,
                            "theorem_decl": c.theorem_decl,
                            "assumptions": c.assumptions,
                            "backend_used": str(getattr(status_map.get(c.candidate_id), "backend_used", "") or ""),
                            "route_reason": str(getattr(status_map.get(c.candidate_id), "route_reason", "") or ""),
                            "route_fallback_used": bool(
                                getattr(status_map.get(c.candidate_id), "route_fallback_used", False)
                            ),
                            **compact_skeleton_candidate_for_semantic(c),
                        }
                        for c in compile_pass_candidates
                    ],
                    ensure_ascii=False,
                    indent=2,
                ),
                "mechlib_context": (
                    mechlib_context[:3000] + "...<truncated>"
                    if mechlib_context and mechlib_context != "(none)" and len(mechlib_context) > 3000
                    else mechlib_context or "(none)"
                ),
            },
        )
        if self.model_client is not None:
            try:
                llm_rows = _parse_llm_results(self.model_client.generate_text(prompt).text)
                if not llm_rows:
                    llm_error = "semantic_rank_parse_failed"
            except Exception as exc:
                llm_error = f"{type(exc).__name__}: {exc}"

        for row in ranking:
            cid = str(row["candidate_id"])
            llm_row = llm_rows.get(cid)
            if not llm_row:
                if llm_error:
                    row["semantic_llm_error"] = llm_error
                continue

            back_translation = str(
                llm_row.get("back_translation")
                or llm_row.get("natural_language_statement")
                or llm_row.get("translation")
                or ""
            ).strip()
            llm_reason = str(
                llm_row.get("reason")
                or llm_row.get("semantic_analysis")
                or llm_row.get("comparison")
                or ""
            ).strip()
            failure_summary = str(llm_row.get("failure_summary") or "").strip()
            failure_tags = _normalize_failure_tags(llm_row.get("failure_tags"))
            missing_translations = _as_str_list(llm_row.get("missing_or_incorrect_translations"))
            suggested_fix_direction = str(llm_row.get("suggested_fix_direction") or "").strip()
            llm_score_raw = llm_row.get("semantic_score")
            if llm_score_raw is None:
                llm_score_raw = llm_row.get("consistency_score")

            llm_score = _as_float(llm_score_raw, default=-1.0)
            llm_score_ok = llm_score >= 0.0
            llm_score = _clamp_score(llm_score) if llm_score_ok else None
            llm_pass = _as_bool(llm_row.get("semantic_pass"))

            rule_score = _as_float(row.get("semantic_score_rule"), 0.0)
            final_score = rule_score
            if llm_score is not None:
                # LLM is primary for semantic comparison, rule score acts as safety anchor.
                final_score = round(0.65 * llm_score + 0.35 * rule_score, 4)
                if "skeleton_semantic_score" in row:
                    final_score = max(rule_score, final_score)
                row["semantic_score_llm"] = llm_score
                row["semantic_source"] = "llm_plus_rule"

            target_match = _as_float(row.get("target_match"), 0.0)
            target_symbol_match = _as_float(row.get("target_symbol_match"), 1.0)
            known_cov = _as_float(row.get("known_quantity_coverage"), 0.0)
            law_match = _as_float(row.get("law_match"), 0.0)
            trivial_goal = bool(row.get("trivial_goal"))
            target_relation = _infer_target_relation(
                model_target_relation=llm_row.get("target_relation"),
                llm_pass=llm_pass,
                failure_tags=failure_tags,
                mismatch_fields=_as_str_list(llm_row.get("mismatch_fields")),
                llm_reason=llm_reason,
                target_match=target_match,
                known_quantity_coverage=known_cov,
                law_match=law_match,
            )
            coordinate_sign_equivalence = _is_coordinate_sign_convention_equivalence(
                target_relation=target_relation,
                failure_tags=failure_tags,
                mismatch_fields=_as_str_list(llm_row.get("mismatch_fields")),
                llm_reason=llm_reason,
                failure_summary=failure_summary,
            )
            if coordinate_sign_equivalence:
                target_relation = "equivalent"
            if (
                "skeleton_semantic_score" in row
                and target_relation in TARGET_RELATION_MISMATCH
                and target_match >= 0.75
            ):
                llm_target_text = " ".join(
                    [
                        " ".join(failure_tags),
                        " ".join(_as_str_list(llm_row.get("mismatch_fields"))),
                        llm_reason.lower(),
                    ]
                )
                if not any(
                    key in llm_target_text
                    for key in ("wrong_target", "target_mismatch", "unknown_target", "unit", "sign")
                ):
                    target_relation = "exact"
            hard_gate_pass, hard_gate_reasons = _hard_semantic_gate(
                ir=ir,
                target_match=target_match,
                target_symbol_match=target_symbol_match,
                known_quantity_coverage=known_cov,
                law_match=law_match,
                trivial_goal=trivial_goal,
                target_relation=target_relation,
            )
            skeleton_hard_gate_reasons = _normalize_failure_tags(row.get("skeleton_hard_gate_reasons"))
            if skeleton_hard_gate_reasons:
                hard_gate_pass = False
                hard_gate_reasons = _normalize_failure_tags(hard_gate_reasons, skeleton_hard_gate_reasons)
            if row.get("grounding_status") in PRAGMATIC_GROUNDING_STATUSES:
                pragmatic_reasons: list[str] = []
                if target_match < 0.72 and not coordinate_sign_equivalence:
                    pragmatic_reasons.append("pragmatic_target_low_match")
                if target_symbol_match < 0.5:
                    pragmatic_reasons.append("pragmatic_target_symbol_mismatch")
                if trivial_goal:
                    pragmatic_reasons.append("pragmatic_target_trivial_goal")
                if pragmatic_reasons:
                    hard_gate_pass = False
                    hard_gate_reasons = _normalize_failure_tags(hard_gate_reasons, pragmatic_reasons)
                else:
                    hard_gate_pass, hard_gate_reasons = _relax_pragmatic_hard_gate(
                        grounding_status=row.get("grounding_status"),
                        hard_gate_reasons=hard_gate_reasons,
                        target_relation=target_relation,
                        target_match=target_match,
                        target_symbol_match=target_symbol_match,
                        trivial_goal=trivial_goal,
                    )
            pass_by_score = _semantic_pass(final_score, target_match, law_match, self.pass_threshold)
            final_pass = pass_by_score if llm_pass is None else (pass_by_score and llm_pass)
            if "skeleton_semantic_score" in row and llm_pass is False:
                llm_failure_text = " ".join(
                    [
                        " ".join(failure_tags),
                        " ".join(_as_str_list(llm_row.get("mismatch_fields"))),
                        llm_reason.lower(),
                        failure_summary.lower(),
                    ]
                )
                critical_llm_target_failure = any(
                    key in llm_failure_text
                    for key in (
                        "wrong_target",
                        "target_mismatch",
                        "unknown_target",
                        "unit",
                        *(() if coordinate_sign_equivalence else ("sign",)),
                    )
                )
                if not critical_llm_target_failure:
                    final_pass = pass_by_score
            final_pass = final_pass and hard_gate_pass
            mismatch_fields = _derive_mismatch_fields(
                llm_fields=llm_row.get("mismatch_fields"),
                hard_gate_reasons=hard_gate_reasons,
                trivial_goal=trivial_goal,
            )
            if not failure_summary and not final_pass:
                failure_summary = llm_reason or "Semantic checker rejected this candidate."
            if not failure_summary and row.get("grounding_gap_summary"):
                failure_summary = str(row.get("grounding_gap_summary") or "").strip() or failure_summary
            failure_tags = _normalize_failure_tags(
                failure_tags,
                hard_gate_reasons,
                row.get("skeleton_warning_reasons"),
            )
            sub_error_type = _infer_semantic_sub_error_type(
                model_sub_error_type=str(llm_row.get("sub_error_type") or "").strip() or None,
                failure_tags=failure_tags,
                mismatch_fields=mismatch_fields,
                hard_gate_reasons=hard_gate_reasons,
                trivial_goal=trivial_goal,
                llm_reason=llm_reason,
            )
            if final_pass:
                sub_error_type = None

            row["semantic_score"] = final_score
            backend_bias = _as_float(row.get("backend_bias"), 0.0)
            proofability_bias = _as_float(row.get("proofability_bias"), 0.0)
            library_grounding_score = _as_float(row.get("library_grounding_score"), 0.0)
            skeleton_grounding_bias = _as_float(row.get("skeleton_grounding_bias"), 0.0)
            row["semantic_rank_score"] = round(
                final_score + backend_bias + proofability_bias + library_grounding_score + skeleton_grounding_bias,
                4,
            )
            row["semantic_pass_llm"] = llm_pass
            row["semantic_pass"] = final_pass
            row["back_translation_text"] = back_translation
            row["semantic_reason"] = llm_reason
            row["hard_gate_pass"] = hard_gate_pass
            row["hard_gate_reasons"] = hard_gate_reasons
            row["failure_summary"] = failure_summary
            row["failure_tags"] = failure_tags
            row["mismatch_fields"] = mismatch_fields
            row["missing_or_incorrect_translations"] = missing_translations
            row["suggested_fix_direction"] = suggested_fix_direction
            row["target_relation"] = target_relation
            row["sub_error_type"] = sub_error_type

        for row in ranking:
            if "hard_gate_pass" not in row or "hard_gate_reasons" not in row:
                target_match = _as_float(row.get("target_match"), 0.0)
                target_symbol_match = _as_float(row.get("target_symbol_match"), 1.0)
                known_cov = _as_float(row.get("known_quantity_coverage"), 0.0)
                law_match = _as_float(row.get("law_match"), 0.0)
                trivial_goal = bool(row.get("trivial_goal"))
                hard_gate_pass, hard_gate_reasons = _hard_semantic_gate(
                    ir=ir,
                    target_match=target_match,
                    target_symbol_match=target_symbol_match,
                    known_quantity_coverage=known_cov,
                    law_match=law_match,
                    trivial_goal=trivial_goal,
                    target_relation=str(row.get("target_relation") or "").strip() or None,
                )
                skeleton_hard_gate_reasons = _normalize_failure_tags(row.get("skeleton_hard_gate_reasons"))
                if skeleton_hard_gate_reasons:
                    hard_gate_pass = False
                    hard_gate_reasons = _normalize_failure_tags(hard_gate_reasons, skeleton_hard_gate_reasons)
                if row.get("grounding_status") in PRAGMATIC_GROUNDING_STATUSES:
                    pragmatic_reasons: list[str] = []
                    if target_match < 0.72:
                        pragmatic_reasons.append("pragmatic_target_low_match")
                    if target_symbol_match < 0.5:
                        pragmatic_reasons.append("pragmatic_target_symbol_mismatch")
                    if trivial_goal:
                        pragmatic_reasons.append("pragmatic_target_trivial_goal")
                    if pragmatic_reasons:
                        hard_gate_pass = False
                        hard_gate_reasons = _normalize_failure_tags(hard_gate_reasons, pragmatic_reasons)
                    else:
                        hard_gate_pass, hard_gate_reasons = _relax_pragmatic_hard_gate(
                            grounding_status=row.get("grounding_status"),
                            hard_gate_reasons=hard_gate_reasons,
                            target_relation=str(row.get("target_relation") or "").strip() or None,
                            target_match=target_match,
                            target_symbol_match=target_symbol_match,
                            trivial_goal=trivial_goal,
                        )
                row["hard_gate_pass"] = hard_gate_pass
                row["hard_gate_reasons"] = hard_gate_reasons
                row["semantic_pass"] = bool(row.get("semantic_pass")) and hard_gate_pass
            if not row.get("failure_tags"):
                row["failure_tags"] = _normalize_failure_tags(
                    row.get("hard_gate_reasons"),
                    row.get("skeleton_warning_reasons"),
                )
            if row.get("unsupported_claims"):
                row["failure_tags"] = _normalize_failure_tags(row.get("failure_tags"), ["unsupported_claim"])
            if not row.get("mismatch_fields"):
                row["mismatch_fields"] = _derive_mismatch_fields(
                    llm_fields=row.get("mismatch_fields"),
                    hard_gate_reasons=_as_str_list(row.get("hard_gate_reasons")),
                    trivial_goal=bool(row.get("trivial_goal")),
                )
            if not row.get("failure_summary") and not bool(row.get("semantic_pass")):
                row["failure_summary"] = (
                    str(row.get("semantic_reason") or "").strip()
                    or str(row.get("grounding_gap_summary") or "").strip()
                    or "Semantic checker rejected this candidate."
                )
            if row.get("skeleton_warning_reasons") and not row.get("failure_tags"):
                row["failure_tags"] = _normalize_failure_tags(row.get("skeleton_warning_reasons"))
            if not row.get("sub_error_type") and not bool(row.get("semantic_pass")):
                row["sub_error_type"] = _infer_semantic_sub_error_type(
                    model_sub_error_type=None,
                    failure_tags=_normalize_failure_tags(row.get("failure_tags")),
                    mismatch_fields=_as_str_list(row.get("mismatch_fields")),
                    hard_gate_reasons=_as_str_list(row.get("hard_gate_reasons")),
                    trivial_goal=bool(row.get("trivial_goal")),
                    llm_reason=str(row.get("semantic_reason") or ""),
                )
            row.setdefault("missing_or_incorrect_translations", [])
            row.setdefault("suggested_fix_direction", "")
            has_law_problem = isinstance(ir.get("physical_laws"), list) and bool(ir.get("physical_laws"))
            has_context_refs = bool(_extract_context_refs(mechlib_context))
            row["grounding_preferred"] = bool(
                row.get("grounded_library_symbols")
                or row.get("direct_translation")
                or not (has_law_problem and has_context_refs)
            )

        ranking.sort(
            key=lambda x: (
                bool(x.get("semantic_pass")),
                _as_float(x.get("semantic_rank_score"), 0.0),
                bool(x.get("grounding_preferred")),
                -assumptions_len_map.get(str(x["candidate_id"]), 0),
                x["candidate_id"],
            ),
            reverse=True,
        )
        best = ranking[0]
        best_failure_summary = str(best.get("failure_summary") or "").strip() or None
        best_failure_tags = _normalize_failure_tags(best.get("failure_tags"))
        best_failure_details = {
            "mismatch_fields": _as_str_list(best.get("mismatch_fields")),
            "missing_or_incorrect_translations": _as_str_list(best.get("missing_or_incorrect_translations")),
            "suggested_fix_direction": str(best.get("suggested_fix_direction") or "").strip() or None,
            "back_translation_text": str(best.get("back_translation_text") or "").strip() or None,
            "semantic_reason": str(best.get("semantic_reason") or "").strip() or None,
            "target_relation": str(best.get("target_relation") or "").strip() or None,
            "hard_gate_reasons": _as_str_list(best.get("hard_gate_reasons")),
            "library_grounding_score": best.get("library_grounding_score"),
            "grounded_library_symbols": _as_str_list(best.get("grounded_library_symbols")),
            "verified_decl_refs": best.get("verified_decl_refs") if isinstance(best.get("verified_decl_refs"), list) else [],
            "schema_refs": best.get("schema_refs") if isinstance(best.get("schema_refs"), list) else [],
            "alias_refs": best.get("alias_refs") if isinstance(best.get("alias_refs"), list) else [],
            "grounding_status": str(best.get("grounding_status") or "").strip() or None,
            "gap_schema_only": bool(best.get("gap_schema_only")),
            "unsupported_claims": _as_str_list(best.get("unsupported_claims")),
            "grounding_gap_summary": str(best.get("grounding_gap_summary") or "").strip() or None,
            "generation_mode": best.get("generation_mode"),
            "verified_decls": _as_str_list(best.get("verified_decls")),
            "gap_laws_count": int(best.get("gap_laws_count") or 0),
            "explicit_model_gaps_count": int(best.get("explicit_model_gaps_count") or 0),
            "fully_mechlib_verified": bool(best.get("fully_mechlib_verified")),
            "target_spec": best.get("target_spec") if isinstance(best.get("target_spec"), dict) else {},
            "skeleton_semantic_score": best.get("skeleton_semantic_score"),
            "target_match_score": best.get("target_match_score"),
            "hypothesis_minimality_score": best.get("hypothesis_minimality_score"),
            "proof_obligation_coverage_score": best.get("proof_obligation_coverage_score"),
            "evidence_binding_score": best.get("evidence_binding_score"),
            "gap_penalty": best.get("gap_penalty"),
            "skeleton_hard_gate_reasons": _as_str_list(best.get("skeleton_hard_gate_reasons")),
            "proof_obligation_summary": str(best.get("proof_obligation_summary") or "").strip() or None,
            "model_predicate_binding_summary": str(best.get("model_predicate_binding_summary") or "").strip() or None,
            "gap_summary": str(best.get("gap_summary") or "").strip() or None,
        }
        return SemanticRankResult(
            sample_id=grounding.sample_id,
            selected_candidate_id=str(best["candidate_id"]),
            selected_theorem_decl=str(best["theorem_decl"]),
            semantic_pass=bool(best["semantic_pass"]),
            ranking=ranking,
            selected_backend=str(best.get("backend_used") or ""),
            selected_route_reason=str(best.get("route_reason") or ""),
            selected_route_fallback_used=bool(best.get("route_fallback_used", False)),
            error=None if best["semantic_pass"] else "semantic_drift",
            sub_error_type=None if bool(best["semantic_pass"]) else (str(best.get("sub_error_type") or "").strip() or None),
            failure_tags=best_failure_tags,
            failure_summary=best_failure_summary,
            failure_details=best_failure_details,
        )
