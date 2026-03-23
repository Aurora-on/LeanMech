from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from mech_pipeline.utils import ensure_dir, normalize_lean_text, truncate

DECL_PATTERN = re.compile(r"^\s*(theorem|lemma|def|abbrev)\s+([A-Za-z_][A-Za-z0-9_']*)")
NEXT_DECL_PATTERN = re.compile(r"^\s*(theorem|lemma|def|abbrev|example|namespace|end)\b")
TOKEN_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_']*")
TACTIC_PATTERN = re.compile(
    r"\b(simp|linarith|nlinarith|ring|aesop|field_simp|norm_num|rw|calc|constructor|have|exact|rfl)\b"
)

MODULE_LAW_TAGS: dict[str, list[str]] = {
    "Kinematics": ["Kinematics"],
    "Dynamics": ["NewtonSecondLaw", "ForceAnalysis2D"],
    "WorkEnergy": ["WorkEnergy", "EnergyConservation"],
    "MomentumImpulse": ["NewtonSecondLaw"],
    "SHM": ["SHO"],
    "DampedSHM": ["SHO"],
    "SystemDynamics": ["NewtonSecondLaw"],
    "Rotation": ["ForceAnalysis2D"],
    "CentralForce": ["NewtonSecondLaw", "SHO"],
    "AnalyticalMechanics": ["NewtonSecondLaw"],
    "SI": ["Kinematics", "NewtonSecondLaw", "WorkEnergy", "EnergyConservation", "SHO", "ForceAnalysis2D"],
}


def _to_ascii_tokens(text: str) -> set[str]:
    return {tok.lower() for tok in TOKEN_PATTERN.findall(text)}


def _split_symbol(symbol: str) -> list[str]:
    parts: list[str] = []
    for chunk in symbol.split("_"):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts.append(chunk.lower())
        camel = re.sub(r"([a-z])([A-Z])", r"\1 \2", chunk)
        for item in camel.split():
            parts.append(item.lower())
    return parts


def _extract_signature(lines: list[str], start_idx: int) -> str:
    collected: list[str] = []
    for i in range(start_idx, min(len(lines), start_idx + 10)):
        raw = lines[i]
        if i > start_idx and NEXT_DECL_PATTERN.match(raw):
            break
        stripped = raw.strip()
        if stripped.startswith("--"):
            continue
        if not stripped:
            if collected:
                break
            continue
        collected.append(stripped)
        if ":=" in stripped:
            break
    text = " ".join(collected)
    if ":=" in text:
        text = text.split(":=", 1)[0].strip()
    return normalize_lean_text(text)


def _tactic_hints(file_text: str) -> list[str]:
    counts: dict[str, int] = {}
    for token in TACTIC_PATTERN.findall(file_text):
        counts[token] = counts.get(token, 0) + 1
    ranked = sorted(counts.items(), key=lambda x: (-x[1], x[0]))
    return [name for name, _ in ranked[:8]]


@dataclass
class MechLibEntry:
    symbol_name: str
    kind: str
    module: str
    path: str
    import_hint: str
    declaration_signature: str
    law_tags: list[str]
    keywords: list[str]
    tactic_hints: list[str]

    def to_row(self) -> dict[str, Any]:
        return asdict(self)


class MechLibRetriever:
    def __init__(
        self,
        mechlib_dir: Path,
        scope: str = "mechanics_si",
        top_k: int = 6,
        cache_path: Path | None = None,
    ) -> None:
        self.mechlib_dir = Path(mechlib_dir)
        self.scope = scope
        self.top_k = top_k
        self.cache_path = Path(cache_path) if cache_path else None
        self.entries: list[MechLibEntry] = []
        self._build_index()

    def _iter_target_files(self) -> list[Path]:
        root = self.mechlib_dir / "MechLib"
        if not root.exists():
            return []
        if self.scope == "mechanics":
            return sorted((root / "Mechanics").glob("*.lean"))
        if self.scope == "mechanics_si":
            files = sorted((root / "Mechanics").glob("*.lean"))
            si = root / "SI.lean"
            if si.exists():
                files.append(si)
            return files
        return sorted(root.rglob("*.lean"))

    def _module_name(self, path: Path) -> str:
        stem = path.stem
        if path.name == "SI.lean":
            return "SI"
        return stem

    def _import_hint(self, module: str) -> str:
        if module == "SI":
            return "import MechLib.SI"
        return f"import MechLib.Mechanics.{module}"

    def _build_index(self) -> None:
        entries: list[MechLibEntry] = []
        for path in self._iter_target_files():
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            text = normalize_lean_text(text)
            lines = text.splitlines()
            module = self._module_name(path)
            tags = MODULE_LAW_TAGS.get(module, [])
            hints = _tactic_hints(text)
            for idx, line in enumerate(lines):
                m = DECL_PATTERN.match(line)
                if not m:
                    continue
                kind = m.group(1)
                symbol = m.group(2)
                signature = _extract_signature(lines, idx)
                kw = set(_split_symbol(symbol))
                kw.update(_to_ascii_tokens(signature))
                kw.update(tok.lower() for tok in tags)
                entries.append(
                    MechLibEntry(
                        symbol_name=symbol,
                        kind=kind,
                        module=module,
                        path=str(path),
                        import_hint=self._import_hint(module),
                        declaration_signature=signature,
                        law_tags=tags,
                        keywords=sorted(kw),
                        tactic_hints=hints,
                    )
                )
        self.entries = entries
        if self.cache_path:
            ensure_dir(self.cache_path.parent)
            with self.cache_path.open("w", encoding="utf-8") as f:
                for row in self.entries:
                    f.write(json.dumps(row.to_row(), ensure_ascii=False) + "\n")

    def _query_tokens(self, problem_text: str, problem_ir: dict[str, Any] | None) -> tuple[set[str], set[str]]:
        ir = problem_ir or {}
        tokens = _to_ascii_tokens(problem_text)
        laws = ir.get("physical_laws")
        law_tokens: set[str] = set()
        if isinstance(laws, list):
            law_tokens = {str(x).strip() for x in laws if str(x).strip()}
            for item in law_tokens:
                tokens.update(_to_ascii_tokens(item))
        unknown = ir.get("unknown_target")
        if isinstance(unknown, dict):
            tokens.update(_to_ascii_tokens(str(unknown.get("symbol") or "")))
            tokens.update(_to_ascii_tokens(str(unknown.get("description") or "")))
        known = ir.get("known_quantities")
        if isinstance(known, list):
            for item in known:
                if isinstance(item, dict):
                    tokens.update(_to_ascii_tokens(str(item.get("symbol") or "")))
                    tokens.update(_to_ascii_tokens(str(item.get("description") or "")))
        goal = ir.get("goal_statement")
        if isinstance(goal, str):
            tokens.update(_to_ascii_tokens(goal))
        return tokens, law_tokens

    def retrieve(self, problem_text: str, problem_ir: dict[str, Any] | None, top_k: int | None = None) -> list[dict[str, Any]]:
        if not self.entries:
            return []
        k = top_k or self.top_k
        query_tokens, target_laws = self._query_tokens(problem_text, problem_ir)
        scored: list[tuple[float, MechLibEntry]] = []
        for entry in self.entries:
            kws = set(entry.keywords)
            overlap = len(query_tokens.intersection(kws))
            if overlap == 0 and not target_laws.intersection(set(entry.law_tags)):
                continue
            law_overlap = len(target_laws.intersection(set(entry.law_tags)))
            score = 0.0
            score += min(1.0, overlap / max(1, min(8, len(kws)))) * 0.7
            score += min(1.0, law_overlap / 2.0) * 0.3
            scored.append((round(score, 6), entry))
        scored.sort(key=lambda x: (-x[0], x[1].module, x[1].symbol_name))
        rows: list[dict[str, Any]] = []
        for score, entry in scored[:k]:
            rows.append(
                {
                    "score": score,
                    "symbol_name": entry.symbol_name,
                    "kind": entry.kind,
                    "module": entry.module,
                    "import_hint": entry.import_hint,
                    "declaration_signature": entry.declaration_signature,
                    "law_tags": entry.law_tags,
                    "tactic_hints": entry.tactic_hints[:5],
                    "path": entry.path,
                }
            )
        return rows

    def render_context(self, rows: list[dict[str, Any]]) -> str:
        if not rows:
            return "(none)"
        lines: list[str] = []
        for idx, row in enumerate(rows, start=1):
            lines.append(
                f"[{idx}] module={row.get('module')} kind={row.get('kind')} "
                f"symbol={row.get('symbol_name')} score={row.get('score')}"
            )
            lines.append(f"import_hint: {row.get('import_hint')}")
            lines.append(f"law_tags: {row.get('law_tags')}")
            lines.append(f"signature: {truncate(str(row.get('declaration_signature') or ''), 260)}")
            lines.append(f"tactic_hints: {row.get('tactic_hints')}")
        return "\n".join(lines)
