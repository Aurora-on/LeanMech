from __future__ import annotations

import json
import re
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
    re.compile(r"^\s*(proof)\s*[:：]", re.IGNORECASE),
    re.compile(r"^\s*(\u8bc1\u660e)\s*[:：]"),
]
INLINE_LEAKAGE_CUTOFF_PATTERNS = [
    re.compile(r"\bfinal\s+answer\s*[:：]", re.IGNORECASE),
    re.compile(r"\bcorrect\s+answer\s*[:：]", re.IGNORECASE),
    re.compile(r"\banswer\s*[:：]", re.IGNORECASE),
    re.compile(r"\bsolution\s*[:：]", re.IGNORECASE),
    re.compile(r"\bexplanation\s*[:：]", re.IGNORECASE),
    re.compile(r"\banalysis\s*[:：]", re.IGNORECASE),
    re.compile(r"\bproof\s*[:：]", re.IGNORECASE),
    re.compile(r"答案\s*[:：]"),
    re.compile(r"参考答案\s*[:：]"),
    re.compile(r"解析\s*[:：]"),
    re.compile(r"解答\s*[:：]"),
    re.compile(r"证明\s*[:：]"),
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
    ("≠", "!="),
    ("鈩?", "Real"),
    ("鈩", "Real"),
    ("鈫?", "->"),
    ("鈫", "->"),
    ("鈭€", "forall"),
    ("鈭", "forall"),
    ("鈮?", ">="),
    ("鈮", ">="),
    ("鉁?", "!="),
    ("鉁", "!="),
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
    lines = text.splitlines()
    kept: list[str] = []
    for line in lines:
        if any(p.search(line) for p in LEAKAGE_LINE_PATTERNS):
            continue
        kept.append(line)
    merged = "\n".join(kept).strip()
    cut_idx = len(merged)
    for pattern in INLINE_LEAKAGE_CUTOFF_PATTERNS:
        m = pattern.search(merged)
        if m:
            cut_idx = min(cut_idx, m.start())
    return merged[:cut_idx].strip()


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
    out = out.replace("�", "")
    return out
