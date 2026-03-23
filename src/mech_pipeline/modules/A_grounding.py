from __future__ import annotations

import base64
import re
from pathlib import Path
from typing import Any

from mech_pipeline.llm_schemas import ProblemIRPayload
from mech_pipeline.prompting import load_template, render_template
from mech_pipeline.response_parser import ResponseParseError, parse_json_model
from mech_pipeline.types import CanonicalSample, GroundingResult
from mech_pipeline.utils import redact_leakage_text

DEFAULT_PROMPT = """__TASK_A_EXTRACT_IR__
You are a mechanics problem parser.
Return JSON only. Do not output any extra explanation.

Required keys:
objects, known_quantities, unknown_target, units, constraints, relations,
physical_laws, assumptions, diagram_information, goal_statement,
coordinate_system, reference_frame, simplifications, symbol_table

Rules:
1) Use only information from the given problem text and image description.
2) Ignore any answer/explanation/proof content if it appears in the input.
3) If unknown, use [] / {} / "" / null.
4) Prefer ASCII variable names.
5) physical_laws must be chosen from:
   Kinematics, NewtonSecondLaw, WorkEnergy, EnergyConservation, ForceAnalysis2D
6) If the problem is pure motion description (position/velocity/time) with no force information,
   prefer Kinematics and do not default to NewtonSecondLaw.

Problem text:
{{problem_text}}

Options:
{{options_text}}

Image description:
{{image_description}}
"""

REQUIRED_KEYS = [
    "objects",
    "known_quantities",
    "unknown_target",
    "units",
    "constraints",
    "relations",
    "physical_laws",
    "assumptions",
    "diagram_information",
    "goal_statement",
    "coordinate_system",
    "reference_frame",
    "simplifications",
    "symbol_table",
]


def _read_image_b64(image_path: str | None) -> str | None:
    if not image_path:
        return None
    path = Path(image_path)
    if not path.exists():
        return None
    return base64.b64encode(path.read_bytes()).decode("utf-8")


def _ensure_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    if isinstance(value, dict):
        return [value]
    return [value]


def _normalize_known_quantities(value: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                out.append(dict(item))
            elif item is not None:
                out.append({"symbol": str(item)})
        return out
    if isinstance(value, dict):
        for sym, info in value.items():
            if isinstance(info, dict):
                row = {"symbol": str(sym)}
                row.update(info)
            else:
                row = {"symbol": str(sym), "value": info}
            out.append(row)
        return out
    if value is not None:
        out.append({"symbol": str(value)})
    return out


def _normalize_unknown_target(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        if value.get("symbol") or value.get("description"):
            return dict(value)

        pairs = list(value.items())
        if not pairs:
            return {}

        symbol = ""
        description = ""
        extras: list[dict[str, str]] = []
        for idx, (k, v) in enumerate(pairs):
            key = str(k).strip()
            val = str(v).strip() if v is not None else ""
            candidate_symbol = ""
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_']*", val):
                candidate_symbol = val
            elif re.fullmatch(r"[A-Za-z_][A-Za-z0-9_']*", key):
                candidate_symbol = key

            row = {
                "symbol": candidate_symbol,
                "description": key if val == "" else f"{key}: {val}",
            }
            if idx == 0:
                symbol = row["symbol"]
                description = row["description"]
            else:
                extras.append(row)

        out: dict[str, Any] = {"symbol": symbol, "description": description}
        if extras:
            out["extra_targets"] = extras
        return out

    if isinstance(value, list):
        candidates = []
        for item in value:
            if isinstance(item, dict):
                sym = str(item.get("symbol") or "").strip()
                desc = str(item.get("description") or "").strip()
                if sym or desc:
                    candidates.append({"symbol": sym, "description": desc})
        if candidates:
            out = dict(candidates[0])
            if len(candidates) > 1:
                out["extra_targets"] = candidates[1:]
            return out
        return {}

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_']*", text):
            return {"symbol": text, "description": text}
        return {"symbol": "", "description": text}

    return {}


def _normalize_ir(ir: dict[str, object]) -> dict[str, object]:
    out: dict[str, object] = dict(ir)
    out["objects"] = _ensure_list(out.get("objects"))
    out["known_quantities"] = _normalize_known_quantities(out.get("known_quantities"))
    out["unknown_target"] = _normalize_unknown_target(out.get("unknown_target"))
    out["constraints"] = [str(x) for x in _ensure_list(out.get("constraints"))]
    out["relations"] = [x for x in _ensure_list(out.get("relations"))]
    laws_val = out.get("physical_laws")
    if isinstance(laws_val, dict):
        out["physical_laws"] = [str(k) for k in laws_val.keys()]
    else:
        out["physical_laws"] = [str(x) for x in _ensure_list(laws_val)]
    out["assumptions"] = [str(x) for x in _ensure_list(out.get("assumptions"))]
    out["diagram_information"] = [x for x in _ensure_list(out.get("diagram_information"))]
    out["simplifications"] = [str(x) for x in _ensure_list(out.get("simplifications"))]
    if not isinstance(out.get("symbol_table"), dict):
        out["symbol_table"] = {}
    if not isinstance(out.get("goal_statement"), str):
        out["goal_statement"] = str(out.get("goal_statement") or "")

    for key in REQUIRED_KEYS:
        if key not in out:
            if key == "unknown_target":
                out[key] = {}
            elif key == "goal_statement":
                out[key] = ""
            elif key in {"coordinate_system", "reference_frame"}:
                out[key] = None
            elif key == "symbol_table":
                out[key] = {}
            else:
                out[key] = []
    return out


def _tokenize_text(text: str) -> set[str]:
    return set(re.findall(r"[A-Za-z_][A-Za-z0-9_']*", text.lower()))


def _normalize_physical_laws(problem_text: str, ir: dict[str, object]) -> dict[str, object]:
    out = dict(ir)
    laws_raw = out.get("physical_laws")
    if isinstance(laws_raw, list):
        laws = [str(x).strip() for x in laws_raw if str(x).strip()]
    else:
        laws = []

    signals: list[str] = [problem_text]
    goal = out.get("goal_statement")
    if isinstance(goal, str):
        signals.append(goal)

    relations = out.get("relations")
    if isinstance(relations, list):
        signals.extend(str(x) for x in relations)

    known = out.get("known_quantities")
    if isinstance(known, list):
        for item in known:
            if isinstance(item, dict):
                signals.append(str(item.get("symbol") or ""))
                signals.append(str(item.get("description") or ""))

    tokens = _tokenize_text(" ".join(signals))

    has_force_terms = bool(tokens.intersection({"force", "mass", "newton", "friction", "normal"}))
    symbols = {str(item.get("symbol") or "").lower() for item in known if isinstance(item, dict)} if isinstance(known, list) else set()
    if {"f", "m"}.issubset(symbols):
        has_force_terms = True

    has_kinematics_terms = bool(
        tokens.intersection(
            {
                "kinematics",
                "position",
                "displacement",
                "distance",
                "velocity",
                "speed",
                "acceleration",
                "time",
            }
        )
    )

    if "NewtonSecondLaw" in laws and (not has_force_terms) and has_kinematics_terms:
        laws = [x for x in laws if x != "NewtonSecondLaw"]
        if "Kinematics" not in laws:
            laws.insert(0, "Kinematics")
    if not laws and has_kinematics_terms:
        laws = ["Kinematics"]

    out["physical_laws"] = laws
    return out


class ModuleA:
    def __init__(self, model_client, model_id: str | None, prompt_path: Path) -> None:
        self.model_client = model_client
        self.model_id = model_id
        self.template = load_template(prompt_path, DEFAULT_PROMPT)

    def run(self, sample: CanonicalSample) -> GroundingResult:
        options_text = "\n".join(sample.options) if sample.options else "(none)"
        image_description = sample.image_description or ""
        safe_problem_text = redact_leakage_text(sample.problem_text)
        prompt = render_template(
            self.template,
            {
                "problem_text": safe_problem_text,
                "options_text": options_text,
                "image_description": image_description,
            },
        )

        raw = ""
        parse_ok = False
        error: str | None = None
        vision_fallback = False
        problem_ir: dict[str, object] | None = None

        try:
            image_b64 = sample.image_b64 or _read_image_b64(sample.image_path)
            if image_b64 and self.model_client.supports_vision:
                resp = self.model_client.generate_multimodal(prompt, [image_b64])
            else:
                resp = self.model_client.generate_text(prompt)
            raw = resp.text
        except Exception as exc:
            if sample.image_b64 or sample.image_path:
                vision_fallback = True
                try:
                    resp = self.model_client.generate_text(prompt)
                    raw = resp.text
                except Exception as fallback_exc:
                    error = f"{type(fallback_exc).__name__}: {fallback_exc}"
            else:
                error = f"{type(exc).__name__}: {exc}"

        if raw:
            try:
                parsed = parse_json_model(raw, ProblemIRPayload)
                parse_ok = True
                problem_ir = _normalize_physical_laws(
                    safe_problem_text,
                    _normalize_ir(parsed.model_dump()),
                )
            except ResponseParseError:
                error = error or "variable_mapping_error"
        else:
            error = error or "variable_mapping_error"

        if parse_ok and problem_ir:
            unknown = problem_ir.get("unknown_target")
            if isinstance(unknown, dict) and not unknown.get("symbol") and not unknown.get("description"):
                error = "wrong_target_extraction"
                parse_ok = False

        return GroundingResult(
            sample_id=sample.sample_id,
            model_id=self.model_id,
            problem_ir=problem_ir,
            parse_ok=parse_ok,
            raw_response=raw,
            error=error,
            vision_fallback=vision_fallback,
        )
