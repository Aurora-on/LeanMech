from __future__ import annotations

import json
import re
from fractions import Fraction
from pathlib import Path
from typing import Any

from mech_pipeline.llm_schemas import StatementCandidatesPayload
from mech_pipeline.prompting import load_template, render_template
from mech_pipeline.response_parser import ResponseParseError, parse_json_model
from mech_pipeline.types import GroundingResult, StatementCandidate
from mech_pipeline.utils import (
    lean_ident,
    normalize_lean_text,
    sanitize_problem_ir_for_llm,
)

MECHLIB_HEADER = "\n".join(
    [
        "import MechLib",
        "open MechLib",
        "open MechLib.SI",
        "open MechLib.Mechanics",
    ]
)
PHYSLEAN_HEADER = "\n".join(["import PhysLean", "open PhysLean"])
TYPED_MECHLIB_TYPES = ("Mass", "Force", "Acceleration", "Length", "Time", "Speed", "Momentum")
MOJIBAKE_PATTERN = re.compile(r"[鈧鈮鈭鉁锛晑�]")
DECIMAL_LITERAL_PATTERN = re.compile(r"(?<![A-Za-z0-9_])-?\d+\.\d+(?![A-Za-z0-9_])")
IDENT_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_']*")
ALLOWED_UNICODE = {"≠", "≤", "≥", "→", "∀", "∧", "∨", "ℝ", "ℕ", "ℤ"}
MOJIBAKE_REPLACEMENTS = {
    "鈭€": "∀",
    "鈮?": "≠",
    "鈥?": "*",
}
LEAN_CORE_TOKENS = {
    "theorem",
    "lemma",
    "import",
    "open",
    "by",
    "fun",
    "let",
    "in",
    "if",
    "then",
    "else",
    "forall",
    "True",
    "False",
    "Prop",
    "Type",
    "Real",
    "Nat",
    "Int",
    "Rat",
    "And",
    "Or",
    "Not",
    "Quantity",
    "SI",
}
SAFE_FUNCTION_TOKENS = {"sqrt", "abs", "min", "max"}

DEFAULT_PROMPT = """__TASK_B_GENERATE_STATEMENTS__
You are a Lean4 statement generator for classical mechanics.

Important workflow:
1) First learn the target library conventions from the provided library context.
2) Then generate formal theorem declarations that follow import/namespace discipline.
3) Output JSON only.

Target library policy:
- library_target={{library_target}}
- required_header_template:
{{required_header_template}}

Generate exactly 4 theorem/lemma declaration candidates from ProblemIR.
Output JSON only:
{
  "candidates": [
    {
      "candidate_id":"c1",
      "lean_header":"...",
      "theorem_decl":"theorem ... : ...",
      "assumptions":[],
      "plan":"short modeling plan"
    },
    {
      "candidate_id":"c2",
      "lean_header":"...",
      "theorem_decl":"theorem ... : ...",
      "assumptions":[],
      "plan":"short modeling plan"
    },
    {
      "candidate_id":"c3",
      "lean_header":"...",
      "theorem_decl":"theorem ... : ...",
      "assumptions":[],
      "plan":"short modeling plan"
    },
    {
      "candidate_id":"c4",
      "lean_header":"...",
      "theorem_decl":"theorem ... : ...",
      "assumptions":[],
      "plan":"short modeling plan"
    }
  ]
}

Constraints:
1) No proof body. Never output ':= by'.
2) Forbidden trivial goals: ': True', ': False', ': Prop', 'x = x', '1 = 1'.
3) Reject assumption-replay goals: do not output `h : x = y ⊢ y = x` or any conclusion that merely restates a given hypothesis.
4) Keep physics quantities, units, and unknown target aligned with ProblemIR.
5) Read Domain Summary Context first, then generate declarations.
6) Align with physical_laws in ProblemIR. Reject off-topic law drift.
7) Stay inside selected domain tags from context; avoid cross-domain drift.
8) Prefer symbol naming and theorem semantics consistent with MechLib domain summaries.
9) Use multiline readable declarations:
   theorem/lemma name
     (arg1 : Type)
     (arg2 : Type)
     ...
     : goal
10) Put each binder on its own line with 2-space indentation.
11) Keep lines reasonably short (recommended <= 100 chars).
12) Use meaningful names for hypotheses and quantities.
13) Use retrieved MechLib references as ontology/style hints only.
14) Never copy retrieved declarations verbatim.
15) If library_target is mechlib, do not import PhysLean.
16) If library_target is physlean, do not import MechLib.
17) Prefer typed mechanics quantities (Mass/Force/Acceleration/Length/Time) when available.
18) If typed quantities are uncertain, use Real but keep units and laws explicit in assumptions.
19) Never use `!=` in theorem propositions; use propositional inequality (`≠`) or `Not (...)`.
20) For expressions that divide physical quantities (e.g., m2 / (m1 + m2)), prefer Real modeling.
21) Avoid `Quantity.cast` unless you are certain the identifier and dimension lemma exist.
22) Do not invent MechLib APIs or helper names. If uncertain, write direct algebraic equalities over binders.
23) If typed MechLib modeling would require undocumented helper defs or `Quantity.cast`, back off to `Real`.

ProblemIR:
{{problem_ir_json}}

Domain Summary Context + Retrieved library context:
{{mechlib_context}}
"""

DEFAULT_REVISE_PROMPT = """__TASK_B_REVISE_STATEMENTS__
You are revising Lean4 mechanics theorem declarations after compile/semantic feedback.

Your job:
1) Read the original ProblemIR and library context.
2) Read the previous candidates and structured feedback from compile + semantic ranking.
3) Generate a fresh set of 4 candidates that avoids the failed patterns.
4) Output JSON only.

Target library policy:
- library_target={{library_target}}
- required_header_template:
{{required_header_template}}

Return exactly 4 candidates:
{
  "candidates": [
    {
      "candidate_id":"c1",
      "lean_header":"...",
      "theorem_decl":"theorem ... : ...",
      "assumptions":[],
      "plan":"short revision plan"
    },
    {
      "candidate_id":"c2",
      "lean_header":"...",
      "theorem_decl":"theorem ... : ...",
      "assumptions":[],
      "plan":"short revision plan"
    },
    {
      "candidate_id":"c3",
      "lean_header":"...",
      "theorem_decl":"theorem ... : ...",
      "assumptions":[],
      "plan":"short revision plan"
    },
    {
      "candidate_id":"c4",
      "lean_header":"...",
      "theorem_decl":"theorem ... : ...",
      "assumptions":[],
      "plan":"short revision plan"
    }
  ]
}

Revision rules:
1) Do not repeat the same theorem declarations from the previous round.
2) If compile feedback reports syntax/library-symbol/import issues, fix those first.
3) If semantic feedback reports target mismatch, law drift, trivial goals, or wrong known quantities, correct those before trying stylistic variation.
4) Do not output assumption-replay goals whose conclusion merely restates a hypothesis or flips an equality assumption.
5) Keep the unknown target, known quantities, laws, and constraints aligned with ProblemIR.
6) Prefer direct algebraic statements over undocumented helper APIs.
7) If typed MechLib modeling is causing failures, switch to `Real`.
8) Never output proof bodies.
9) Keep output fully valid JSON.

ProblemIR:
{{problem_ir_json}}

Domain Summary Context + Retrieved library context:
{{mechlib_context}}

Previous candidates:
{{previous_candidates_json}}

Structured revision feedback:
{{revision_feedback}}
"""


def _strip_code_fence(text: str) -> str:
    out = text.strip()
    if out.startswith("```"):
        out = out.replace("```lean", "").replace("```", "").strip()
    return out


def _declaration_only(text: str) -> str:
    out = _strip_code_fence(text)
    if ":= by" in out:
        out = out.split(":= by", 1)[0].rstrip()
    elif ":=" in out:
        out = out.split(":=", 1)[0].rstrip()
    if out.endswith(" by"):
        out = out[:-3].rstrip()
    return out


def _is_meaningful_decl(text: str) -> bool:
    stripped = _declaration_only(text)
    if not re.match(r"^\s*(theorem|lemma)\s+", stripped):
        return False
    if ":" not in stripped:
        return False
    lowered = stripped.lower()
    if re.search(r":\s*(true|false)\s*$", lowered):
        return False
    if re.search(r":\s*prop\s*$", lowered):
        return False
    if re.search(r":\s*1\s*=\s*1\s*$", lowered):
        return False
    goal = stripped.rsplit(":", 1)[1].strip()
    ident_eq = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_']*)\s*=\s*([A-Za-z_][A-Za-z0-9_']*)", goal)
    if ident_eq and ident_eq.group(1) == ident_eq.group(2):
        return False
    num_eq = re.fullmatch(r"(-?\d+(?:\.\d+)?)\s*=\s*(-?\d+(?:\.\d+)?)", goal)
    if num_eq and num_eq.group(1) == num_eq.group(2):
        return False
    if _is_trivial_assumption_replay(stripped):
        return False
    return True


def _has_balanced_delimiters(text: str) -> bool:
    pairs = {"(": ")", "[": "]", "{": "}"}
    stack: list[str] = []
    for ch in text:
        if ch in pairs:
            stack.append(pairs[ch])
        elif ch in pairs.values():
            if not stack or stack.pop() != ch:
                return False
    return not stack


def _has_disallowed_non_ascii(text: str) -> bool:
    for ch in text:
        if ord(ch) <= 127:
            continue
        if ch in ALLOWED_UNICODE:
            continue
        return True
    return False


def _parse_decl_name(text: str) -> tuple[str, str, str] | None:
    decl = _declaration_only(text)
    m = re.match(r"^\s*(theorem|lemma)\s+([A-Za-z_][A-Za-z0-9_']*)([\s\S]*)$", decl)
    if not m:
        return None
    return m.group(1), m.group(2), m.group(3)


def _normalize_common_mojibake(text: str) -> str:
    out = text
    for src, dst in MOJIBAKE_REPLACEMENTS.items():
        out = out.replace(src, dst)
    return out


def _render_real_literal(value: Fraction) -> str:
    abs_num = abs(value.numerator)
    if value.denominator == 1:
        base = f"({abs_num} : Real)"
    else:
        base = f"(({abs_num} : Real) / {value.denominator})"
    if value < 0:
        return f"(-{base})"
    return base


def _normalize_numeric_literals(text: str) -> str:
    def _replace(match: re.Match[str]) -> str:
        literal = match.group(0)
        try:
            value = Fraction(literal)
        except ValueError:
            return literal
        return _render_real_literal(value)

    return DECIMAL_LITERAL_PATTERN.sub(_replace, text)


def _extract_context_symbols(mechlib_context: str) -> set[str]:
    symbols: set[str] = set()
    for match in re.finditer(r"symbol=([A-Za-z_][A-Za-z0-9_']*)", mechlib_context or ""):
        symbols.add(match.group(1))
    return symbols


def _normalize_library_target(raw: str | None) -> str:
    value = (raw or "mechlib").strip().lower()
    if value in {"mechlib", "physlean", "auto"}:
        return value
    return "mechlib"


def _required_header(target: str) -> str:
    return MECHLIB_HEADER if target == "mechlib" else PHYSLEAN_HEADER


def _infer_library_target(lean_header: str, theorem_decl: str, default_target: str) -> str:
    text = f"{lean_header}\n{theorem_decl}"
    if "MechLib" in text:
        return "mechlib"
    if "PhysLean" in text:
        return "physlean"
    if default_target == "auto":
        return "mechlib"
    return default_target


def _normalize_header(lean_header: str, target: str) -> str:
    raw_lines = [ln.rstrip() for ln in normalize_lean_text(lean_header).splitlines() if ln.strip()]
    kept: list[str] = []
    for line in raw_lines:
        if target == "mechlib" and "PhysLean" in line:
            continue
        if target == "physlean" and "MechLib" in line:
            continue
        kept.append(line)

    required = _required_header(target).splitlines()
    merged: list[str] = []
    seen: set[str] = set()
    for line in required + kept:
        if line in seen:
            continue
        seen.add(line)
        merged.append(line)
    return "\n".join(merged).strip()


def _contains_typed_mechlib_types(text: str) -> bool:
    return any(re.search(rf"\b{re.escape(tp)}\b", text) for tp in TYPED_MECHLIB_TYPES)


def _extract_binder_names(text: str) -> set[str]:
    names: set[str] = set()
    for m in re.finditer(
        r"\(\s*([A-Za-z_][A-Za-z0-9_']*(?:\s+[A-Za-z_][A-Za-z0-9_']*)*)\s*:\s*[^)]+\)",
        text,
    ):
        for token in m.group(1).split():
            names.add(token)
    return names


def _decl_local_symbols(text: str) -> set[str]:
    names = _extract_binder_names(text)
    parsed = _parse_decl_name(text)
    if parsed:
        names.add(parsed[1])
    return names


def _ensure_real_binder(text: str, symbol: str) -> str:
    binders = _extract_binder_names(text)
    if symbol in binders:
        return text
    if not re.search(rf"\b{re.escape(symbol)}\b", text):
        return text
    lines = text.splitlines()
    if not lines:
        return text
    # Insert just after theorem/lemma line.
    lines.insert(1, f"  ({symbol} : Real)")
    return "\n".join(lines)


def _coerce_typed_binders_to_real(text: str) -> str:
    out = text
    out = re.sub(
        r":\s*(Mass|Force|Acceleration|Length|Time|Speed|Momentum)\b",
        ": Real",
        out,
    )
    out = out.replace(".val", "")
    out = _ensure_real_binder(out, "g")
    return out


def _looks_like_library_symbol(token: str) -> bool:
    if len(token) <= 1:
        return False
    if "_" in token:
        return True
    return token[0].islower() and any(ch.isupper() for ch in token[1:])


def _looks_like_unknown_prefix_application(token: str, text: str) -> bool:
    if len(token) <= 2 or not token.islower():
        return False
    return re.search(rf"\b{re.escape(token)}\b\s+[A-Za-z_(]", text) is not None


def _find_unknown_library_symbols(text: str, mechlib_context: str) -> list[str]:
    known = _extract_context_symbols(mechlib_context)
    known.update(TYPED_MECHLIB_TYPES)
    known.update(LEAN_CORE_TOKENS)
    known.update(SAFE_FUNCTION_TOKENS)
    known.update(_decl_local_symbols(text))
    unknown: set[str] = set()
    for token in IDENT_PATTERN.findall(text):
        if token in known:
            continue
        if not _looks_like_library_symbol(token) and not _looks_like_unknown_prefix_application(token, text):
            continue
        unknown.add(token)
    return sorted(unknown)


def _strip_quantity_casts(text: str) -> str:
    needle = "Quantity.cast"
    idx = 0
    out: list[str] = []
    while True:
        start = text.find(needle, idx)
        if start < 0:
            out.append(text[idx:])
            break
        out.append(text[idx:start])
        pos = start + len(needle)
        while pos < len(text) and text[pos].isspace():
            pos += 1
        if pos >= len(text) or text[pos] != "(":
            out.append(needle)
            idx = pos
            continue
        depth = 1
        pos += 1
        expr_start = pos
        while pos < len(text) and depth > 0:
            ch = text[pos]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            pos += 1
        if depth != 0:
            out.append(text[start:])
            break
        expr = text[expr_start : pos - 1].strip()
        trail = pos
        while trail < len(text) and text[trail].isspace():
            trail += 1
        if text.startswith("SI.", trail):
            trail += 3
            while trail < len(text) and (text[trail].isalnum() or text[trail] in {"_", "'"}):
                trail += 1
        out.append(f"({expr})")
        idx = trail
    return "".join(out)


def _rewrite_known_mechlib_hallucinations(text: str) -> str:
    ident = r"([A-Za-z_][A-Za-z0-9_']*)"
    out = text.replace("**", "^")
    out = _strip_quantity_casts(out)
    out = re.sub(
        rf"\bvelocityConstAccel\s+{ident}\s+{ident}\s+{ident}",
        lambda m: f"({m.group(1)} + {m.group(2)} * {m.group(3)})",
        out,
    )
    out = re.sub(
        rf"\bpositionConstAccel\s+{ident}\s+{ident}\s+{ident}\s+{ident}",
        lambda m: (
            f"({m.group(1)} + {m.group(2)} * {m.group(4)} + "
            f"((1 : Real) / 2) * {m.group(3)} * ({m.group(4)} ^ (2 : Nat)))"
        ),
        out,
    )
    out = re.sub(
        rf"\bdisplacementConstAccelForm2\s+{ident}\s+{ident}\s+{ident}",
        lambda m: f"((({m.group(1)} + {m.group(2)}) / 2) * {m.group(3)})",
        out,
    )
    out = re.sub(
        rf"\bdisplacement\s+{ident}\s+{ident}",
        lambda m: f"({m.group(1)} - {m.group(2)})",
        out,
    )
    out = re.sub(
        rf"\bF_of\s+{ident}\s+{ident}",
        lambda m: f"({m.group(1)} * {m.group(2)})",
        out,
    )
    return out


def _fallback_decl(sample_id: str, candidate_id: str) -> str:
    name = lean_ident(f"{sample_id}_{candidate_id}_fallback_goal", prefix="thm")
    return (
        f"theorem {name}\n"
        "  (F m a : Real)\n"
        "  (hm : m ≠ 0)\n"
        "  (h_force : F = m * a)\n"
        "  : a = F / m"
    )


def _repair_decl_for_mechlib_safety(
    *,
    sample_id: str,
    candidate_id: str,
    theorem_decl: str,
    problem_ir: dict[str, Any] | None,
    mechlib_context: str,
    library_target: str,
) -> str | None:
    text = _normalize_common_mojibake(theorem_decl.replace("!=", "≠"))
    text = _normalize_numeric_literals(text)
    if MOJIBAKE_PATTERN.search(text):
        return None
    if not _has_balanced_delimiters(text):
        return None
    if _has_disallowed_non_ascii(text):
        return None
    unknown_library_symbols: list[str] = []
    if library_target == "mechlib":
        unknown_library_symbols = _find_unknown_library_symbols(text, mechlib_context)
    if "Quantity.cast" in text or unknown_library_symbols:
        text = _rewrite_known_mechlib_hallucinations(text)
        text = _coerce_typed_binders_to_real(text)
        text = _normalize_numeric_literals(text)
        if MOJIBAKE_PATTERN.search(text):
            return None
        if not _has_balanced_delimiters(text):
            return None
        if _has_disallowed_non_ascii(text):
            return None
        if library_target == "mechlib" and _find_unknown_library_symbols(text, mechlib_context):
            return None
    if _contains_typed_mechlib_types(text):
        risky = "/" in text or "≠ 0" in text or ".val" in text
        if risky:
            text = _coerce_typed_binders_to_real(text)
            if not _has_balanced_delimiters(text):
                return None
    return text


def _normalize_theorem_decl(
    sample_id: str,
    candidate_id: str,
    value: object,
    problem_ir: dict[str, Any] | None,
    mechlib_context: str,
    library_target: str,
) -> str | None:
    text = normalize_lean_text(_declaration_only(str(value or "")))
    text = text.replace("!=", "≠")
    if _is_meaningful_decl(text):
        parsed = _parse_decl_name(text)
        if parsed:
            kw, old_name, rest = parsed
            safe_name = lean_ident(f"{sample_id}_{candidate_id}_{old_name}", prefix="thm")
            renamed = f"{kw} {safe_name}{rest}"
            return _repair_decl_for_mechlib_safety(
                sample_id=sample_id,
                candidate_id=candidate_id,
                theorem_decl=renamed,
                problem_ir=problem_ir,
                mechlib_context=mechlib_context,
                library_target=library_target,
            )
        return _repair_decl_for_mechlib_safety(
            sample_id=sample_id,
            candidate_id=candidate_id,
            theorem_decl=text,
            problem_ir=problem_ir,
            mechlib_context=mechlib_context,
            library_target=library_target,
        )
    return None


def _extract_binder_types(text: str) -> list[str]:
    types: list[str] = []
    for m in re.finditer(r"\(\s*[A-Za-z_][A-Za-z0-9_']*(?:\s+[A-Za-z_][A-Za-z0-9_']*)*\s*:\s*([^)]+)\)", text):
        types.append(" ".join(m.group(1).split()))
    return types


def _is_simple_commutativity_goal(goal: str) -> bool:
    patterns = [
        r"^\(?([A-Za-z_][A-Za-z0-9_']*)\s*\*\s*([A-Za-z_][A-Za-z0-9_']*)\)?\s*=\s*\(?\2\s*\*\s*\1\)?$",
        r"^\(?([A-Za-z_][A-Za-z0-9_']*)\s*\+\s*([A-Za-z_][A-Za-z0-9_']*)\)?\s*=\s*\(?\2\s*\+\s*\1\)?$",
    ]
    compact = " ".join(goal.split())
    return any(re.fullmatch(pattern, compact) for pattern in patterns)


def _is_trivial_assumption_replay(text: str) -> bool:
    stripped = _declaration_only(text)
    if ":" not in stripped:
        return False
    goal = " ".join(stripped.rsplit(":", 1)[1].strip().split())
    if _is_simple_commutativity_goal(goal):
        return True
    for binder_type in _extract_binder_types(stripped):
        binder_prop = " ".join(binder_type.split())
        if goal == binder_prop:
            return True
        eq = re.fullmatch(r"(.+?)\s*=\s*(.+)", binder_prop)
        goal_eq = re.fullmatch(r"(.+?)\s*=\s*(.+)", goal)
        if eq and goal_eq:
            lhs = " ".join(eq.group(1).split())
            rhs = " ".join(eq.group(2).split())
            goal_lhs = " ".join(goal_eq.group(1).split())
            goal_rhs = " ".join(goal_eq.group(2).split())
            if (goal_lhs == lhs and goal_rhs == rhs) or (goal_lhs == rhs and goal_rhs == lhs):
                return True
    return False


class ModuleB:
    def __init__(
        self,
        model_client,
        prompt_path: Path,
        revise_prompt_path: Path | None = None,
        library_target: str = "mechlib",
    ) -> None:
        self.model_client = model_client
        self.template = load_template(prompt_path, DEFAULT_PROMPT)
        self.revise_template = (
            load_template(revise_prompt_path, DEFAULT_REVISE_PROMPT)
            if revise_prompt_path is not None
            else DEFAULT_REVISE_PROMPT
        )
        self.library_target = _normalize_library_target(library_target)

    def run(
        self,
        grounding: GroundingResult,
        mechlib_context: str = "(none)",
        revision_feedback: str = "(none)",
        round_index: int = 0,
        previous_candidates: list[StatementCandidate] | None = None,
    ) -> list[StatementCandidate]:
        safe_ir = sanitize_problem_ir_for_llm(grounding.problem_ir or {})
        use_revision_prompt = round_index > 0 and revision_feedback.strip() != "(none)"
        template = self.revise_template if use_revision_prompt else self.template
        previous_candidates_payload = [
            {
                "candidate_id": c.candidate_id,
                "lean_header": c.lean_header,
                "theorem_decl": c.theorem_decl,
                "assumptions": c.assumptions,
                "plan": c.plan,
                "round_index": c.round_index,
            }
            for c in (previous_candidates or [])
        ]
        prompt = render_template(
            template,
            {
                "problem_ir_json": json.dumps(safe_ir, ensure_ascii=False, indent=2),
                "mechlib_context": mechlib_context or "(none)",
                "library_target": self.library_target,
                "required_header_template": _required_header(
                    "mechlib" if self.library_target in {"mechlib", "auto"} else "physlean"
                ),
                "previous_candidates_json": json.dumps(previous_candidates_payload, ensure_ascii=False, indent=2),
                "revision_feedback": revision_feedback or "(none)",
            },
        )

        raw = ""
        parse_ok = False
        error: str | None = None
        try:
            resp = self.model_client.generate_text(prompt)
            raw = resp.text
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"

        payload: list[dict[str, object]] = []
        if raw:
            try:
                parsed = parse_json_model(raw, StatementCandidatesPayload)
                for idx, item in enumerate(parsed.candidates):
                    cand = item.model_dump()
                    cand.setdefault("candidate_id", f"c{idx + 1}")
                    payload.append(cand)
                parse_ok = True
            except ResponseParseError:
                error = error or "statement_generation_parse_failed"
        else:
            error = error or "statement_generation_parse_failed"

        while len(payload) < 4:
            cid = f"c{len(payload) + 1}"
            fallback_target = "mechlib" if self.library_target in {"mechlib", "auto"} else "physlean"
            payload.append(
                {
                    "candidate_id": cid,
                    "lean_header": _required_header(fallback_target),
                    "theorem_decl": _fallback_decl(grounding.sample_id, cid),
                    "assumptions": [],
                    "plan": "Fallback mechanics declaration after incomplete model output.",
                }
            )

        payload = payload[:4]
        fallback_target = "mechlib" if self.library_target in {"mechlib", "auto"} else "physlean"
        prepared: list[dict[str, object]] = []
        valid_templates: list[dict[str, object]] = []

        for item in payload:
            cid = str(item.get("candidate_id") or "c1")
            assumptions = item.get("assumptions")
            initial_target = _infer_library_target(
                str(item.get("lean_header") or ""),
                str(item.get("theorem_decl") or ""),
                self.library_target,
            )
            target = initial_target if self.library_target == "auto" else self.library_target
            if target == "auto":
                target = "mechlib"
            decl = _normalize_theorem_decl(
                grounding.sample_id,
                cid,
                item.get("theorem_decl"),
                grounding.problem_ir,
                mechlib_context=mechlib_context,
                library_target=target,
            )
            inferred_target = _infer_library_target(
                str(item.get("lean_header") or ""),
                decl,
                self.library_target,
            )
            target = inferred_target if self.library_target == "auto" else self.library_target
            if target == "auto":
                target = "mechlib"
            prepared_item = {
                "candidate_id": cid,
                "lean_header": _normalize_header(str(item.get("lean_header") or ""), target),
                "theorem_decl": decl,
                "assumptions": [str(x) for x in assumptions] if isinstance(assumptions, list) else [],
                "plan": str(item.get("plan") or "").strip() or None,
                "target": target,
            }
            prepared.append(prepared_item)
            if decl is not None:
                valid_templates.append(prepared_item)

        out: list[StatementCandidate] = []
        clone_index = 0
        for item in prepared:
            cid = str(item["candidate_id"])
            decl = item["theorem_decl"]
            header = str(item["lean_header"])
            assumptions = list(item["assumptions"]) if isinstance(item["assumptions"], list) else []
            plan = item["plan"] if isinstance(item["plan"], str) else None
            target = str(item["target"])

            if decl is None and valid_templates:
                source = valid_templates[clone_index % len(valid_templates)]
                clone_index += 1
                target = str(source["target"])
                header = str(source["lean_header"])
                assumptions = list(source["assumptions"]) if isinstance(source["assumptions"], list) else []
                plan = f"Cloned from a valid candidate because the original {cid} declaration was invalid."
                decl = _normalize_theorem_decl(
                    grounding.sample_id,
                    cid,
                    source["theorem_decl"],
                    grounding.problem_ir,
                    mechlib_context=mechlib_context,
                    library_target=target,
                )

            if decl is None:
                target = fallback_target
                header = _required_header(target)
                decl = _fallback_decl(grounding.sample_id, cid)
                assumptions = []
                plan = "Catastrophic fallback declaration after unusable model output."

            out.append(
                StatementCandidate(
                    sample_id=grounding.sample_id,
                    candidate_id=cid,
                    lean_header=header,
                    theorem_decl=decl,
                    assumptions=assumptions,
                    plan=plan,
                    parse_ok=parse_ok,
                    raw_response=raw,
                    error=error,
                    round_index=round_index,
                    source_round_index=(round_index - 1) if round_index > 0 else None,
                )
            )
        return out
