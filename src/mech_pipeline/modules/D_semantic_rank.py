from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from mech_pipeline.llm_schemas import SemanticRankItemPayload, SemanticRankPayload
from mech_pipeline.prompting import load_template, render_template
from mech_pipeline.response_parser import ResponseParseError, parse_json_model
from mech_pipeline.types import CompileCheckResult, GroundingResult, SemanticRankResult, StatementCandidate
from mech_pipeline.utils import redact_leakage_text, sanitize_problem_ir_for_llm

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
    if any(token in text for token in PROOFABILITY_TYPED_TOKENS):
        bias -= 0.03
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
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, mechlib_context or ""):
            refs.add(match.group(1))
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
    if matched:
        score += min(0.22, 0.1 + 0.06 * len(matched))
    elif has_law_problem and refs and not direct_translation:
        score -= 0.12
    if unsupported_claims:
        score -= min(0.25, 0.05 + 0.06 * len(unsupported_claims))
    if matched and law_match >= 0.25:
        score += 0.06
    if not has_law_problem and score < 0:
        score = 0.0
    score = round(score, 4)
    if unsupported_claims:
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
        reasons.append("known_quantity_mismatch")

    return len(reasons) == 0, reasons


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
            l = _law_match(ir, candidate.theorem_decl)
            u = _unit_consistency(ir, candidate.theorem_decl)
            a = _assumption_consistency(ir, candidate.theorem_decl)
            score_rule = round(0.35 * t + 0.25 * k + 0.2 * l + 0.1 * u + 0.1 * a, 4)
            if trivial_goal:
                score_rule = min(score_rule, 0.2)
            library_grounding_score, grounded_symbols, direct_translation, grounding_gap_summary = _library_grounding_score(
                ir=ir,
                mechlib_context=mechlib_context,
                library_symbols_used=list(candidate.library_symbols_used),
                unsupported_claims=list(candidate.unsupported_claims),
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
            ranking.append(
                {
                    "candidate_id": candidate.candidate_id,
                    "theorem_decl": candidate.theorem_decl,
                    "backend_used": backend_used,
                    "route_reason": route_reason,
                    "route_fallback_used": route_fallback_used,
                    "backend_bias": backend_bias,
                    "proofability_bias": proofability_bias,
                    "supporting_facts": list(candidate.supporting_facts),
                    "fact_sources": list(candidate.fact_sources),
                    "library_symbols_used": list(candidate.library_symbols_used),
                    "grounding_explanation": candidate.grounding_explanation,
                    "unsupported_claims": list(candidate.unsupported_claims),
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
                    "unit_consistency": u,
                    "assumption_consistency": a,
                    "semantic_score_rule": score_rule,
                    "semantic_score_llm": None,
                    "semantic_score": score_rule,
                    "semantic_rank_score": score_rule + backend_bias + proofability_bias + library_grounding_score,
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
                }
            )

        llm_error: str | None = None
        llm_rows: dict[str, dict[str, Any]] = {}
        safe_problem_text = redact_leakage_text(problem_text or "")
        safe_problem_ir = sanitize_problem_ir_for_llm(ir)
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
                        }
                        for c in compile_pass_candidates
                    ],
                    ensure_ascii=False,
                    indent=2,
                ),
                "mechlib_context": mechlib_context or "(none)",
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
            hard_gate_pass, hard_gate_reasons = _hard_semantic_gate(
                ir=ir,
                target_match=target_match,
                target_symbol_match=target_symbol_match,
                known_quantity_coverage=known_cov,
                law_match=law_match,
                trivial_goal=trivial_goal,
                target_relation=target_relation,
            )
            pass_by_score = _semantic_pass(final_score, target_match, law_match, self.pass_threshold)
            final_pass = pass_by_score if llm_pass is None else (pass_by_score and llm_pass)
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
            failure_tags = _normalize_failure_tags(failure_tags, hard_gate_reasons)
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
            row["semantic_rank_score"] = round(
                final_score + backend_bias + proofability_bias + library_grounding_score,
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
                row["hard_gate_pass"] = hard_gate_pass
                row["hard_gate_reasons"] = hard_gate_reasons
                row["semantic_pass"] = bool(row.get("semantic_pass")) and hard_gate_pass
            if not row.get("failure_tags"):
                row["failure_tags"] = _normalize_failure_tags(row.get("hard_gate_reasons"))
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
                bool(x.get("grounding_preferred")),
                bool(x.get("semantic_pass")),
                _as_float(x.get("semantic_rank_score"), 0.0),
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
            "unsupported_claims": _as_str_list(best.get("unsupported_claims")),
            "grounding_gap_summary": str(best.get("grounding_gap_summary") or "").strip() or None,
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
