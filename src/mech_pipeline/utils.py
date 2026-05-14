from __future__ import annotations

import json
import re
import os
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


JSON_BLOCK_PATTERN = re.compile(r"\{.*\}", re.DOTALL)
LEAKAGE_LINE_PATTERNS = [
    re.compile(r"^\s*(answer|final answer|correct answer)\s*[:：]", re.IGNORECASE),
    re.compile(r"^\s*(\u7b54\u6848|\u53c2\u8003\u7b54\u6848)\s*[:：]"),
    re.compile(r"^\s*(solution|explanation|analysis)\s*[:：]", re.IGNORECASE),
    re.compile(r"^\s*(\u89e3\u6790|\u89e3\u7b54)\s*[:：]"),
]
INLINE_LEAKAGE_CUTOFF_PATTERNS = [
    re.compile(r"\bfinal\s+answer\s*[:：]", re.IGNORECASE),
    re.compile(r"\bcorrect\s+answer\s*[:：]", re.IGNORECASE),
    re.compile(r"\banswer\s*[:：]", re.IGNORECASE),
    re.compile(r"\bsolution\s*[:：]", re.IGNORECASE),
    re.compile(r"\bexplanation\s*[:：]", re.IGNORECASE),
    re.compile(r"\banalysis\s*[:：]", re.IGNORECASE),
    re.compile(r"答案\s*[:：]"),
    re.compile(r"参考答案\s*[:：]"),
    re.compile(r"解析\s*[:：]"),
    re.compile(r"解答\s*[:：]"),
    re.compile(r"(?m)^\s*解\s*[:：]"),
    re.compile(r"(?m)^\s*解得\b"),
]
ALLOWED_IR_KEYS = {
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
}
LEAN_MOJIBAKE_REPLACEMENTS = [
    ("ℝ", "Real"),
    ("ℕ", "Nat"),
    ("ℤ", "Int"),
    ("→", "->"),
    ("∀", "forall"),
    ("≥", ">="),
    ("≤", "<="),
    ("≠", "≠"),
    ("鈩?", "Real"),
    ("鈩", "Real"),
    ("鈫?", "->"),
    ("鈫", "->"),
    ("鈭€", "forall"),
    ("鈭", "forall"),
    ("鈮?", "≠"),
    ("鈮", "≠"),
    ("鉁?", "≠"),
    ("鉁", "≠"),
    ("鈭?", "∧"),
    ("鈭", "∧"),
    ("鈥?", "-"),
    ("鈥", "-"),
    ("晑", ""),
    ("锛?", ""),
    ("锛?", ""),
    ("锛", ""),
]


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def build_run_name(tag: str | None) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if not tag:
        return stamp
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "-", tag).strip("-")
    return f"{stamp}_{safe or 'run'}"


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        f.write(text)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def append_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def to_row(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return asdict(value)


def extract_json_object(text: str) -> dict[str, Any] | None:
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = candidate.replace("```json", "").replace("```", "").strip()
    try:
        parsed = json.loads(candidate)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    match = JSON_BLOCK_PATTERN.search(text)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        return None
    return None


def safe_stem(value: str) -> str:
    stem = re.sub(r"[^a-zA-Z0-9._-]", "_", value)
    return stem or "sample"


def lean_ident(value: str, prefix: str = "thm") -> str:
    ident = re.sub(r"[^A-Za-z0-9_']", "_", value)
    ident = re.sub(r"_+", "_", ident).strip("_")
    if not ident:
        ident = prefix
    if ident[0].isdigit():
        ident = f"{prefix}_{ident}"
    return ident


def truncate(text: str, limit: int = 500) -> str:
    stripped = text.strip()
    if len(stripped) <= limit:
        return stripped
    return stripped[: limit - 3] + "..."


def redact_leakage_text(text: str) -> str:
    cut_idx = len(text)
    for pattern in INLINE_LEAKAGE_CUTOFF_PATTERNS:
        m = pattern.search(text)
        if m:
            cut_idx = min(cut_idx, m.start())
    text = text[:cut_idx]

    lines = text.splitlines()
    kept: list[str] = []
    for line in lines:
        if any(p.search(line) for p in LEAKAGE_LINE_PATTERNS):
            continue
        kept.append(line)
    merged = "\n".join(kept).strip()
    return merged.strip()


def sanitize_problem_ir_for_llm(ir: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(ir, dict):
        return {}
    safe: dict[str, Any] = {}
    for key in ALLOWED_IR_KEYS:
        if key in ir:
            safe[key] = ir[key]
    return safe


def normalize_lean_text(text: str) -> str:
    out = text
    for bad, good in LEAN_MOJIBAKE_REPLACEMENTS:
        out = out.replace(bad, good)
    # In Lean theorem propositions, `!=` is boolean inequality (BEq), which is often wrong here.
    # Normalize to propositional inequality to avoid BEq synthesis failures.
    out = out.replace("!=", "≠")
    out = out.replace("�", "")
    return out


def _strip_balanced_outer_parens(text: str) -> str:
    value = text.strip()
    while value.startswith("(") and value.endswith(")"):
        depth = 0
        balanced = True
        for index, char in enumerate(value):
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0 and index != len(value) - 1:
                    balanced = False
                    break
            if depth < 0:
                balanced = False
                break
        if not balanced or depth != 0:
            break
        value = value[1:-1].strip()
    return value


def _tautology_body(text: str) -> str:
    value = _strip_balanced_outer_parens(normalize_lean_text(text).strip())
    quantifier_pattern = re.compile(r"^(?:∀|forall)\s+.+?,\s*(.+)$", re.DOTALL)
    while True:
        match = quantifier_pattern.match(value)
        if not match:
            break
        value = _strip_balanced_outer_parens(match.group(1).strip())
    for marker in ("->", "→"):
        if marker in value:
            value = _strip_balanced_outer_parens(value.rsplit(marker, 1)[1].strip())
    return value


def is_tautological_equality(text: object) -> bool:
    """Return True for equality-only tautologies such as `x = x` or `forall t, f t = f t`.

    This intentionally stays syntactic. It catches no-information model/target formulas without
    treating meaningful shared-variable constraints such as `a1 = a ∧ a2 = a` as duplicates.
    """
    value = _tautology_body(str(text or ""))
    if not value:
        return False
    parts = re.split(r"\s*(?:∧|\\land|\band\b)\s*", value)
    checked = 0
    for part in parts:
        piece = _strip_balanced_outer_parens(part.strip())
        if not piece:
            continue
        if any(token in piece for token in ("≠", "≤", "≥", "<", ">")):
            return False
        if piece.count("=") != 1:
            return False
        lhs, rhs = [
            re.sub(r"\s+", "", _strip_balanced_outer_parens(side.strip()))
            for side in piece.split("=", 1)
        ]
        if not lhs or lhs != rhs:
            return False
        checked += 1
    return checked > 0


def load_dotenv_if_present(path: Path, override: bool = False) -> bool:
    if not path.exists():
        return False
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if override or key not in os.environ:
            os.environ[key] = value
    return True
