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

LAW_TO_SUMMARY_TAGS: dict[str, list[str]] = {
    "Kinematics": ["Kinematics"],
    "NewtonSecondLaw": ["Dynamics", "SystemDynamics", "MomentumImpulse"],
    "WorkEnergy": ["WorkEnergy"],
    "EnergyConservation": ["WorkEnergy"],
    "ForceAnalysis2D": ["Dynamics", "Rotation"],
    "SHO": ["SHM", "DampedSHM"],
}

TAG_KEYWORDS: dict[str, list[str]] = {
    "Kinematics": ["kinematics", "position", "displacement", "velocity", "speed", "acceleration", "time"],
    "Dynamics": ["force", "newton", "mass", "friction", "normal", "tension"],
    "SystemDynamics": ["system", "center", "centroid", "combined"],
    "MomentumImpulse": ["momentum", "impulse", "collision", "impact"],
    "WorkEnergy": ["work", "energy", "potential", "kinetic", "conservation", "power"],
    "Rotation": ["torque", "angular", "rotation", "moment", "inertia"],
    "SHM": ["harmonic", "spring", "omega", "period", "frequency", "oscillation"],
    "DampedSHM": ["damped", "damping", "underdamped", "overdamped", "critical"],
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


def _extract_proof_style_example(lines: list[str], start_idx: int) -> str:
    in_proof = False
    snippet: list[str] = []
    for i in range(start_idx, min(len(lines), start_idx + 28)):
        raw = lines[i]
        if i > start_idx and NEXT_DECL_PATTERN.match(raw):
            break

        if not in_proof:
            if ":= by" in raw:
                in_proof = True
                tail = raw.split(":= by", 1)[1].strip()
                if tail:
                    snippet.append(tail)
                continue
            continue

        stripped = raw.strip()
        if not stripped or stripped.startswith("--"):
            if snippet:
                break
            continue
        if NEXT_DECL_PATTERN.match(raw):
            break

        head = stripped.split()[0]
        if TACTIC_PATTERN.search(stripped) or head in {"intro", "apply", "have", "rw", "calc", "simpa", "exact"}:
            snippet.append(stripped)
        if len(snippet) >= 3:
            break

    if not snippet:
        return ""
    return normalize_lean_text(" ; ".join(snippet))


def _tactic_hints(file_text: str) -> list[str]:
    counts: dict[str, int] = {}
    for token in TACTIC_PATTERN.findall(file_text):
        counts[token] = counts.get(token, 0) + 1
    ranked = sorted(counts.items(), key=lambda x: (-x[1], x[0]))
    return [name for name, _ in ranked[:8]]


def _normalize_tag(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    return text[0].upper() + text[1:]


@dataclass
class MechLibEntry:
    symbol_name: str
    kind: str
    module: str
    path: str
    import_hint: str
    declaration_signature: str
    proof_style_example: str
    law_tags: list[str]
    keywords: list[str]
    tactic_hints: list[str]

    def to_row(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SummaryCorpusEntry:
    line_no: int
    row_id: str
    fq_name: str
    statement: str
    tags: list[str]
    retrieval_text: str
    summary_en: str
    raw_preview: str

    def to_row(self) -> dict[str, Any]:
        return asdict(self)


class MechLibRetriever:
    def __init__(
        self,
        mechlib_dir: Path,
        scope: str = "mechanics_si",
        top_k: int = 6,
        cache_path: Path | None = None,
        context_source: str = "hybrid",
        summary_corpus_path: Path | None = None,
        summary_injection_mode: str = "domain_full",
        always_include_core_tags: list[str] | None = None,
    ) -> None:
        self.mechlib_dir = Path(mechlib_dir)
        self.scope = scope
        self.top_k = top_k
        self.cache_path = Path(cache_path) if cache_path else None
        self.context_source = context_source
        self.summary_corpus_path = (
            Path(summary_corpus_path)
            if summary_corpus_path
            else (self.mechlib_dir / "theorem_corpus.jsonl")
        )
        self.summary_injection_mode = summary_injection_mode
        self.core_tags = [_normalize_tag(x) for x in (always_include_core_tags or ["SI", "Units"]) if x.strip()]

        self.entries: list[MechLibEntry] = []
        self.summary_entries: list[SummaryCorpusEntry] = []
        self.summary_entries_by_tag: dict[str, list[SummaryCorpusEntry]] = {}

        self._build_index()
        self._load_summary_corpus()

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
                proof_style = _extract_proof_style_example(lines, idx)
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
                        proof_style_example=proof_style,
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

    def _load_summary_corpus(self) -> None:
        path = self.summary_corpus_path
        if not path.exists():
            self.summary_entries = []
            self.summary_entries_by_tag = {}
            return

        entries: list[SummaryCorpusEntry] = []

        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line_no, raw_line in enumerate(f, start=1):
                line = raw_line.rstrip("\n")
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue

                if not isinstance(obj, dict):
                    continue

                tags_raw = obj.get("tags")
                tags: list[str] = []
                if isinstance(tags_raw, list):
                    for tag in tags_raw:
                        t = _normalize_tag(str(tag))
                        if t:
                            tags.append(t)
                if not tags:
                    tags = ["Unknown"]

                entry = SummaryCorpusEntry(
                    line_no=line_no,
                    row_id=str(obj.get("id") or "").strip(),
                    fq_name=str(obj.get("fq_name") or "").strip(),
                    statement=normalize_lean_text(str(obj.get("statement") or "").strip()),
                    tags=tags,
                    retrieval_text=normalize_lean_text(str(obj.get("retrieval_text") or "").strip()),
                    summary_en=normalize_lean_text(str(obj.get("summary_en") or "").strip()),
                    raw_preview=truncate(line, 280),
                )
                entries.append(entry)

        by_tag: dict[str, list[SummaryCorpusEntry]] = {}
        for entry in entries:
            for tag in entry.tags:
                by_tag.setdefault(tag, []).append(entry)

        for tag in by_tag:
            by_tag[tag].sort(key=lambda x: (x.fq_name, x.row_id, x.line_no))

        self.summary_entries = entries
        self.summary_entries_by_tag = by_tag

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

    def _extract_domain_from_a(self, problem_ir: dict[str, Any] | None) -> list[str]:
        ir = problem_ir or {}
        laws = ir.get("physical_laws")
        if not isinstance(laws, list):
            return []
        out: list[str] = []
        for law in laws:
            text = str(law).strip()
            if text and text not in out:
                out.append(text)
        return out

    def _infer_domain_tags_from_text(self, problem_text: str, problem_ir: dict[str, Any] | None) -> list[str]:
        ir = problem_ir or {}
        constraints = ir.get("constraints")
        assumptions = ir.get("assumptions")
        constraints_text = " ".join(str(x) for x in constraints) if isinstance(constraints, list) else ""
        assumptions_text = " ".join(str(x) for x in assumptions) if isinstance(assumptions, list) else ""
        text = " ".join(
            [
                problem_text,
                str(ir.get("goal_statement") or ""),
                constraints_text,
                assumptions_text,
            ]
        )
        tokens = _to_ascii_tokens(text)
        scores: dict[str, int] = {}
        for tag, kws in TAG_KEYWORDS.items():
            score = 0
            for kw in kws:
                if kw in tokens:
                    score += 2
                elif any(kw in tok for tok in tokens):
                    score += 1
            if score > 0:
                scores[tag] = score
        if not scores:
            return ["Kinematics"]
        ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
        top = ranked[0][1]
        return [tag for tag, score in ranked if score >= max(1, top - 1)]

    def _select_summary_tags(self, problem_text: str, problem_ir: dict[str, Any] | None) -> tuple[list[str], list[str]]:
        domain_from_a = self._extract_domain_from_a(problem_ir)
        selected: list[str] = []
        for law in domain_from_a:
            for tag in LAW_TO_SUMMARY_TAGS.get(law, []):
                if tag not in selected:
                    selected.append(tag)
        if not selected:
            for tag in self._infer_domain_tags_from_text(problem_text, problem_ir):
                if tag not in selected:
                    selected.append(tag)
        for tag in self.core_tags:
            if tag not in selected:
                selected.append(tag)
        return domain_from_a, selected

    def _select_summary_rows(self, selected_tags: list[str]) -> list[dict[str, Any]]:
        seen: set[str] = set()
        out: list[dict[str, Any]] = []
        for tag in selected_tags:
            for entry in self.summary_entries_by_tag.get(tag, []):
                key = entry.row_id or f"{entry.fq_name}@{entry.line_no}"
                if key in seen:
                    continue
                seen.add(key)
                out.append(
                    {
                        "line_no": entry.line_no,
                        "id": entry.row_id,
                        "fq_name": entry.fq_name,
                        "statement": entry.statement,
                        "tags": entry.tags,
                        "summary_en": entry.summary_en,
                        "retrieval_text": entry.retrieval_text,
                        "raw_preview": entry.raw_preview,
                    }
                )
        out.sort(key=lambda x: (str(x.get("fq_name") or ""), int(x.get("line_no") or 0)))
        return out

    def _retrieve_source_rows(
        self,
        problem_text: str,
        problem_ir: dict[str, Any] | None,
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
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
                    "proof_style_example": truncate(entry.proof_style_example, 220),
                    "path": entry.path,
                }
            )
        return rows

    # Backward-compatible API: source retrieval.
    def retrieve(
        self,
        problem_text: str,
        problem_ir: dict[str, Any] | None,
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        return self._retrieve_source_rows(problem_text=problem_text, problem_ir=problem_ir, top_k=top_k)

    def build_context_pack_from_rows(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        if not rows:
            return {
                "import_hints": [],
                "law_matched_items": [],
                "proof_style_examples": [],
            }

        import_hints: list[str] = []
        seen_import: set[str] = set()
        for row in rows:
            hint = str(row.get("import_hint") or "").strip()
            if not hint or hint in seen_import:
                continue
            seen_import.add(hint)
            import_hints.append(hint)

        law_matched_items: list[dict[str, Any]] = []
        for row in rows:
            law_matched_items.append(
                {
                    "module": row.get("module"),
                    "symbol_name": row.get("symbol_name"),
                    "kind": row.get("kind"),
                    "score": row.get("score"),
                    "law_tags": row.get("law_tags"),
                    "declaration_signature": truncate(str(row.get("declaration_signature") or ""), 200),
                }
            )

        proof_style_examples: list[str] = []
        seen_example: set[str] = set()
        for row in rows:
            ex = str(row.get("proof_style_example") or "").strip()
            if not ex or ex in seen_example:
                continue
            seen_example.add(ex)
            proof_style_examples.append(ex)
            if len(proof_style_examples) >= 2:
                break

        if len(proof_style_examples) < 2:
            target_modules = {str(row.get("module") or "") for row in rows}
            target_laws: set[str] = set()
            for row in rows:
                tags = row.get("law_tags")
                if isinstance(tags, list):
                    for tag in tags:
                        text = str(tag).strip()
                        if text:
                            target_laws.add(text)
            for entry in self.entries:
                if len(proof_style_examples) >= 2:
                    break
                if not entry.proof_style_example:
                    continue
                if entry.proof_style_example in seen_example:
                    continue
                if target_modules and entry.module not in target_modules and not target_laws.intersection(entry.law_tags):
                    continue
                seen_example.add(entry.proof_style_example)
                proof_style_examples.append(entry.proof_style_example)

        return {
            "import_hints": import_hints[:6],
            "law_matched_items": law_matched_items,
            "proof_style_examples": proof_style_examples,
        }

    def render_context(self, rows: list[dict[str, Any]]) -> str:
        if not rows:
            return "(none)"
        pack = self.build_context_pack_from_rows(rows)
        lines: list[str] = []
        lines.append("Library Learning Preamble:")
        lines.append(
            "Learn this library context first, then generate Lean using the configured imports/namespaces."
        )
        lines.append("Do not copy declarations verbatim; adapt symbols to the current problem.")
        lines.append("")
        lines.append("Import Hints:")
        for hint in pack["import_hints"]:
            lines.append(f"- {hint}")
        lines.append("")
        lines.append("Law-Matched Declarations:")
        for idx, row in enumerate(pack["law_matched_items"], start=1):
            lines.append(
                f"[{idx}] module={row.get('module')} kind={row.get('kind')} "
                f"symbol={row.get('symbol_name')} score={row.get('score')} law_tags={row.get('law_tags')}"
            )
            lines.append(f"signature: {truncate(str(row.get('declaration_signature') or ''), 260)}")
        if pack["proof_style_examples"]:
            lines.append("")
            lines.append("Proof-Style Examples (style only):")
            for idx, ex in enumerate(pack["proof_style_examples"], start=1):
                lines.append(f"[{idx}] {truncate(ex, 260)}")
        return "\n".join(lines)

    def build_domain_context(
        self,
        problem_text: str,
        problem_ir: dict[str, Any] | None,
        top_k: int | None = None,
    ) -> dict[str, Any]:
        domain_from_a, selected_tags = self._select_summary_tags(problem_text=problem_text, problem_ir=problem_ir)
        summary_items: list[dict[str, Any]] = []
        source_items: list[dict[str, Any]] = []

        if self.context_source in {"hybrid", "summary_only"} and self.summary_entries:
            summary_items = self._select_summary_rows(selected_tags=selected_tags)
        if self.context_source in {"hybrid", "source_only"}:
            source_items = self._retrieve_source_rows(problem_text=problem_text, problem_ir=problem_ir, top_k=top_k)

        source_pack = self.build_context_pack_from_rows(source_items)
        lines: list[str] = []
        lines.append("Library Learning Preamble:")
        lines.append("Learn this MechLib domain summary context first, then generate Lean declarations.")
        lines.append("Do not copy verbatim; adapt symbols and assumptions to this specific problem.")
        lines.append("")
        lines.append(f"Domain from A.physical_laws: {domain_from_a if domain_from_a else ['(fallback)']}")
        lines.append(f"Selected domain tags: {selected_tags}")

        if summary_items:
            lines.append("")
            lines.append("Domain Summary Context (from theorem_corpus.jsonl):")
            for idx, row in enumerate(summary_items, start=1):
                retrieval_text = str(row.get("retrieval_text") or "").strip()
                if retrieval_text:
                    lines.append(f"[{idx}] {retrieval_text}")
                else:
                    fq = str(row.get("fq_name") or "")
                    statement = str(row.get("statement") or "").strip()
                    summary_en = str(row.get("summary_en") or "").strip()
                    tags = row.get("tags")
                    lines.append(f"[{idx}] {fq}")
                    lines.append(f"statement: {statement}")
                    if summary_en:
                        lines.append(f"summary: {summary_en}")
                    lines.append(f"tags: {tags}")
        else:
            lines.append("")
            lines.append("Domain Summary Context (from theorem_corpus.jsonl): (none)")

        lines.append("")
        lines.append("Source Supplement (from MechLib .lean parsing):")
        lines.append(f"source_items_count: {len(source_items)}")
        lines.append("Import Hints:")
        for hint in source_pack["import_hints"]:
            lines.append(f"- {hint}")
        lines.append("Law-Matched Declarations:")
        for idx, row in enumerate(source_pack["law_matched_items"], start=1):
            lines.append(
                f"[{idx}] module={row.get('module')} kind={row.get('kind')} "
                f"symbol={row.get('symbol_name')} score={row.get('score')} law_tags={row.get('law_tags')}"
            )
            lines.append(f"signature: {truncate(str(row.get('declaration_signature') or ''), 260)}")
        if source_pack["proof_style_examples"]:
            lines.append("Proof-Style Examples (style only):")
            for idx, ex in enumerate(source_pack["proof_style_examples"], start=1):
                lines.append(f"[{idx}] {truncate(ex, 260)}")

        context_text = "\n".join(lines)
        return {
            "domain_from_a": domain_from_a,
            "selected_tags": selected_tags,
            "summary_items": summary_items,
            "source_items": source_items,
            "import_hints": source_pack.get("import_hints", []),
            "law_matched_items": source_pack.get("law_matched_items", []),
            "proof_style_examples": source_pack.get("proof_style_examples", []),
            "context_text": context_text,
            "summary_items_count": len(summary_items),
            "source_items_count": len(source_items),
            "final_context_chars": len(context_text),
        }
