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

DEFAULT_PROMPT = """__TASK_D_SEMANTIC_RANK__
You are a semantic consistency checker for mechanics formalization.
For each Lean theorem candidate:
1) Translate the theorem declaration back into concise natural language.
2) Compare semantic consistency with the original problem and ProblemIR.
3) Return a score in [0, 1], where 1 means perfectly aligned.
4) Reject trivial statements (x = x, 1 = 1, True).
5) Reject law drift (e.g., Newton-force theorem for pure kinematics).

Output JSON only:
{
  "results": [
    {
      "candidate_id": "c1",
      "back_translation": "...",
      "semantic_score": 0.0,
      "semantic_pass": false,
      "reason": "..."
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
        if symbol and symbol in tokens:
            score += 0.6
        desc_tokens = _tokenize(description)
        if desc_tokens and desc_tokens.intersection(tokens):
            score += 0.4
        return min(1.0, score)
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
    known_quantity_coverage: float,
    law_match: float,
    trivial_goal: bool,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if trivial_goal:
        reasons.append("trivial_goal")

    if _has_unknown_target(ir) and target_match < 0.4:
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
                error="semantic_drift",
            )

        ranking: list[dict[str, object]] = []
        for candidate in compile_pass_candidates:
            goal_expr = _extract_goal_expr(candidate.theorem_decl)
            trivial_goal = _is_trivial_goal(goal_expr)
            t = _target_match(ir, candidate.theorem_decl)
            k = _known_quantity_coverage(ir, candidate.theorem_decl)
            l = _law_match(ir, candidate.theorem_decl)
            u = _unit_consistency(ir, candidate.theorem_decl)
            a = _assumption_consistency(ir, candidate.theorem_decl)
            score_rule = round(0.35 * t + 0.25 * k + 0.2 * l + 0.1 * u + 0.1 * a, 4)
            if trivial_goal:
                score_rule = min(score_rule, 0.2)
            ranking.append(
                {
                    "candidate_id": candidate.candidate_id,
                    "theorem_decl": candidate.theorem_decl,
                    "goal_expr": goal_expr,
                    "trivial_goal": trivial_goal,
                    "target_match": t,
                    "known_quantity_coverage": k,
                    "law_match": l,
                    "unit_consistency": u,
                    "assumption_consistency": a,
                    "semantic_score_rule": score_rule,
                    "semantic_score_llm": None,
                    "semantic_score": score_rule,
                    "semantic_pass_llm": None,
                    "semantic_pass": _semantic_pass(score_rule, t, l, self.pass_threshold),
                    "back_translation_text": "",
                    "semantic_reason": "",
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
            known_cov = _as_float(row.get("known_quantity_coverage"), 0.0)
            law_match = _as_float(row.get("law_match"), 0.0)
            trivial_goal = bool(row.get("trivial_goal"))
            hard_gate_pass, hard_gate_reasons = _hard_semantic_gate(
                ir=ir,
                target_match=target_match,
                known_quantity_coverage=known_cov,
                law_match=law_match,
                trivial_goal=trivial_goal,
            )
            pass_by_score = _semantic_pass(final_score, target_match, law_match, self.pass_threshold)
            final_pass = pass_by_score if llm_pass is None else (pass_by_score and llm_pass)
            final_pass = final_pass and hard_gate_pass

            row["semantic_score"] = final_score
            row["semantic_pass_llm"] = llm_pass
            row["semantic_pass"] = final_pass
            row["back_translation_text"] = back_translation
            row["semantic_reason"] = llm_reason
            row["hard_gate_pass"] = hard_gate_pass
            row["hard_gate_reasons"] = hard_gate_reasons

        ranking.sort(
            key=lambda x: (
                bool(x.get("semantic_pass")),
                _as_float(x.get("semantic_score"), 0.0),
                -assumptions_len_map.get(str(x["candidate_id"]), 0),
                x["candidate_id"],
            ),
            reverse=True,
        )
        best = ranking[0]
        return SemanticRankResult(
            sample_id=grounding.sample_id,
            selected_candidate_id=str(best["candidate_id"]),
            selected_theorem_decl=str(best["theorem_decl"]),
            semantic_pass=bool(best["semantic_pass"]),
            ranking=ranking,
            error=None if best["semantic_pass"] else "semantic_drift",
        )
