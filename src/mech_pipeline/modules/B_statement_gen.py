from __future__ import annotations

import json
import re
from pathlib import Path

from mech_pipeline.llm_schemas import StatementCandidatesPayload
from mech_pipeline.prompting import load_template, render_template
from mech_pipeline.response_parser import ResponseParseError, parse_json_model
from mech_pipeline.types import GroundingResult, StatementCandidate
from mech_pipeline.utils import (
    lean_ident,
    normalize_lean_text,
    sanitize_problem_ir_for_llm,
)

DEFAULT_PROMPT = """__TASK_B_GENERATE_STATEMENTS__
You are a Lean4 statement generator.
Generate exactly 4 theorem/lemma declaration candidates from ProblemIR.
Output JSON only:
{
  "candidates": [
    {"candidate_id":"c1","lean_header":"import PhysLean","theorem_decl":"theorem ... : ...","assumptions":[]},
    {"candidate_id":"c2","lean_header":"import PhysLean","theorem_decl":"theorem ... : ...","assumptions":[]},
    {"candidate_id":"c3","lean_header":"import PhysLean","theorem_decl":"theorem ... : ...","assumptions":[]},
    {"candidate_id":"c4","lean_header":"import PhysLean","theorem_decl":"theorem ... : ...","assumptions":[]}
  ]
}
Constraints:
1) No proof body. Do not output ':= by'.
2) Forbidden trivial goals: ': True', ': False', ': Prop'.
3) Keep physics quantities, units, and target variable from ProblemIR.
4) Align with physical_laws in ProblemIR and avoid off-topic laws.
5) Prefer multi-line readable declarations, not one extremely long line.
6) Use this declaration style:
   theorem/lemma name
     (arg1 : Type)
     (arg2 : Type)
     ...
     : goal
7) Put each binder on its own line with 2-space indentation.
8) Keep lines reasonably short (recommended <= 100 chars).
9) Use meaningful hypothesis names.
10) Use the retrieved MechLib references only as style/ontology hints.
11) Do not copy declarations verbatim; adapt them to the current problem.
12) If your declaration uses `MechLib.` symbols, set `lean_header` to include `import MechLib`.
ProblemIR:
{{problem_ir_json}}

Retrieved MechLib context:
{{mechlib_context}}
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
    return True


def _parse_decl_name(text: str) -> tuple[str, str, str] | None:
    decl = _declaration_only(text)
    m = re.match(r"^\s*(theorem|lemma)\s+([A-Za-z_][A-Za-z0-9_']*)([\s\S]*)$", decl)
    if not m:
        return None
    return m.group(1), m.group(2), m.group(3)


def _fallback_decl(sample_id: str, candidate_id: str) -> str:
    name = lean_ident(f"{sample_id}_{candidate_id}_goal", prefix="thm")
    return f"theorem {name} : (1 = 1)"


def _normalize_theorem_decl(sample_id: str, candidate_id: str, value: object) -> str:
    text = normalize_lean_text(_declaration_only(str(value or "")))
    if _is_meaningful_decl(text):
        parsed = _parse_decl_name(text)
        if parsed:
            kw, old_name, rest = parsed
            safe_name = lean_ident(f"{sample_id}_{candidate_id}_{old_name}", prefix="thm")
            return f"{kw} {safe_name}{rest}"
        return text
    return _fallback_decl(sample_id, candidate_id)


class ModuleB:
    def __init__(self, model_client, prompt_path: Path) -> None:
        self.model_client = model_client
        self.template = load_template(prompt_path, DEFAULT_PROMPT)

    def run(self, grounding: GroundingResult, mechlib_context: str = "(none)") -> list[StatementCandidate]:
        safe_ir = sanitize_problem_ir_for_llm(grounding.problem_ir or {})
        prompt = render_template(
            self.template,
            {
                "problem_ir_json": json.dumps(safe_ir, ensure_ascii=False, indent=2),
                "mechlib_context": mechlib_context or "(none)",
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
            payload.append(
                {
                    "candidate_id": cid,
                    "lean_header": "import PhysLean",
                    "theorem_decl": _fallback_decl(grounding.sample_id, cid),
                    "assumptions": [],
                }
            )

        payload = payload[:4]
        out: list[StatementCandidate] = []
        for item in payload:
            cid = str(item.get("candidate_id") or "c1")
            assumptions = item.get("assumptions")
            out.append(
                StatementCandidate(
                    sample_id=grounding.sample_id,
                    candidate_id=cid,
                    lean_header=str(item.get("lean_header") or "import PhysLean"),
                    theorem_decl=_normalize_theorem_decl(
                        grounding.sample_id,
                        cid,
                        item.get("theorem_decl"),
                    ),
                    assumptions=[str(x) for x in assumptions] if isinstance(assumptions, list) else [],
                    parse_ok=parse_ok,
                    raw_response=raw,
                    error=error,
                )
            )
        return out
