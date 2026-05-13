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


@dataclass
class EnrichedDeclEntry:
    row_id: str
    kind: str
    fq_name: str
    short_name: str
    namespace: str
    module: str
    statement: str
    attrs: list[str]
    source_path: str
    source_line: int | None
    tags: list[str]
    summary_en: str
    proof_hints: list[str]
    retrieval_text: str
    status: str
    trust_level: str
    callable_by_llm: bool
    required_imports: list[str]
    dependencies: list[str]
    primary_spec_id: str
    secondary_spec_ids: list[str]
    concept_ids: list[str]
    law_schema_ids: list[str]
    problem_schema_ids: list[str]
    premise_role: list[str]
    alignment_method: str
    alignment_score: float | None
    needs_review: bool

    def to_row(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SchemaCorpusEntry:
    corpus_type: str
    row_id: str
    retrieval_text: str
    raw: dict[str, Any]

    def to_row(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AliasMapEntry:
    alias_name: str
    alias_fq_name: str
    alias_to_fq_name: str
    source_path: str
    source_line: int | None

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
        enriched_corpus_enabled: bool = True,
        decl_corpus_path: Path | None = None,
        law_schema_corpus_path: Path | None = None,
        problem_schema_corpus_path: Path | None = None,
        concept_corpus_path: Path | None = None,
        alias_map_path: Path | None = None,
        alignment_index_path: Path | None = None,
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
            else (self.mechlib_dir / "corpus" / "theorem_corpus.jsonl")
        )
        self.enriched_corpus_enabled = enriched_corpus_enabled
        self.decl_corpus_path = Path(decl_corpus_path) if decl_corpus_path else (self.mechlib_dir / "corpus" / "decl_corpus_enriched.jsonl")
        self.law_schema_corpus_path = (
            Path(law_schema_corpus_path) if law_schema_corpus_path else (self.mechlib_dir / "corpus" / "law_schema_corpus.jsonl")
        )
        self.problem_schema_corpus_path = (
            Path(problem_schema_corpus_path) if problem_schema_corpus_path else (self.mechlib_dir / "corpus" / "problem_schema_corpus.jsonl")
        )
        self.concept_corpus_path = Path(concept_corpus_path) if concept_corpus_path else (self.mechlib_dir / "corpus" / "concept_corpus.jsonl")
        self.alias_map_path = Path(alias_map_path) if alias_map_path else (self.mechlib_dir / "corpus" / "alias_map.jsonl")
        self.alignment_index_path = (
            Path(alignment_index_path) if alignment_index_path else (self.mechlib_dir / "corpus" / "decl_to_spec_index.json")
        )
        self.summary_injection_mode = summary_injection_mode
        self.core_tags = [_normalize_tag(x) for x in (always_include_core_tags or ["SI", "Units"]) if x.strip()]

        self.entries: list[MechLibEntry] = []
        self.summary_entries: list[SummaryCorpusEntry] = []
        self.summary_entries_by_tag: dict[str, list[SummaryCorpusEntry]] = {}
        self.decl_entries: list[EnrichedDeclEntry] = []
        self.decl_entries_by_name: dict[str, EnrichedDeclEntry] = {}
        self.schema_entries: list[SchemaCorpusEntry] = []
        self.alias_entries: list[AliasMapEntry] = []
        self.alias_entries_by_name: dict[str, AliasMapEntry] = {}
        self.alignment_index: dict[str, Any] = {}

        self._build_index()
        self._load_summary_corpus()
        self._load_enriched_decl_corpus()
        self._load_schema_corpora()
        self._load_alias_map()
        self._load_alignment_index()

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

    def _string_list(self, value: object) -> list[str]:
        if isinstance(value, str):
            text = normalize_lean_text(value.strip())
            return [text] if text else []
        if not isinstance(value, list):
            return []
        out: list[str] = []
        seen: set[str] = set()
        for item in value:
            text = normalize_lean_text(str(item or "").strip())
            if not text or text in seen:
                continue
            seen.add(text)
            out.append(text)
        return out

    def _as_bool(self, value: object, default: bool = False) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "yes", "1"}:
                return True
            if lowered in {"false", "no", "0"}:
                return False
        return default

    def _as_float_or_none(self, value: object) -> float | None:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value.strip())
            except ValueError:
                return None
        return None

    def _as_int_or_none(self, value: object) -> int | None:
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            try:
                return int(value.strip())
            except ValueError:
                return None
        return None

    def _load_jsonl_dicts(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if isinstance(obj, dict):
                    rows.append(obj)
        return rows

    def _load_enriched_decl_corpus(self) -> None:
        if not self.enriched_corpus_enabled:
            self.decl_entries = []
            self.decl_entries_by_name = {}
            return

        entries: list[EnrichedDeclEntry] = []
        for obj in self._load_jsonl_dicts(self.decl_corpus_path):
            fq_name = normalize_lean_text(str(obj.get("fq_name") or "").strip())
            short_name = normalize_lean_text(str(obj.get("short_name") or "").strip())
            statement = normalize_lean_text(str(obj.get("statement") or "").strip())
            if not fq_name or not short_name or not statement:
                continue
            entry = EnrichedDeclEntry(
                row_id=str(obj.get("id") or "").strip(),
                kind=str(obj.get("kind") or "").strip(),
                fq_name=fq_name,
                short_name=short_name,
                namespace=str(obj.get("namespace") or "").strip(),
                module=str(obj.get("module") or "").strip(),
                statement=statement,
                attrs=self._string_list(obj.get("attrs")),
                source_path=str(obj.get("source_path") or "").strip(),
                source_line=self._as_int_or_none(obj.get("source_line")),
                tags=[_normalize_tag(x) for x in self._string_list(obj.get("tags"))],
                summary_en=normalize_lean_text(str(obj.get("summary_en") or "").strip()),
                proof_hints=self._string_list(obj.get("proof_hints")),
                retrieval_text=normalize_lean_text(str(obj.get("retrieval_text") or "").strip()),
                status=str(obj.get("status") or "").strip().lower(),
                trust_level=str(obj.get("trust_level") or "").strip().lower(),
                callable_by_llm=self._as_bool(obj.get("callable_by_llm"), default=False),
                required_imports=self._string_list(obj.get("required_imports")),
                dependencies=self._string_list(obj.get("dependencies")),
                primary_spec_id=str(obj.get("primary_spec_id") or "").strip(),
                secondary_spec_ids=self._string_list(obj.get("secondary_spec_ids")),
                concept_ids=self._string_list(obj.get("concept_ids")),
                law_schema_ids=self._string_list(obj.get("law_schema_ids")),
                problem_schema_ids=self._string_list(obj.get("problem_schema_ids")),
                premise_role=self._string_list(obj.get("premise_role")),
                alignment_method=str(obj.get("alignment_method") or "").strip(),
                alignment_score=self._as_float_or_none(obj.get("alignment_score")),
                needs_review=self._as_bool(obj.get("needs_review"), default=False),
            )
            entries.append(entry)

        by_name: dict[str, EnrichedDeclEntry] = {}
        for entry in entries:
            by_name[entry.fq_name] = entry
            by_name[entry.short_name] = entry
        self.decl_entries = entries
        self.decl_entries_by_name = by_name

    def _schema_retrieval_text(self, corpus_type: str, obj: dict[str, Any]) -> str:
        pieces: list[str] = [str(obj.get("id") or "")]
        for key in (
            "topic",
            "zh_name",
            "en_name",
            "statement_text",
            "formal_prop_name",
            "status",
        ):
            value = str(obj.get(key) or "").strip()
            if value:
                pieces.append(value)
        for key in (
            "candidate_laws",
            "expected_lean_objects",
            "input_objects",
            "target_objects",
            "modeling_steps",
            "schema_decls",
            "verified_decls",
            "prerequisites",
            "used_for",
            "aliases_en",
            "aliases_zh",
            "related_laws",
            "related_problem_schemas",
            "tags",
        ):
            for item in self._string_list(obj.get(key)):
                pieces.append(item)
        return normalize_lean_text(f"{corpus_type}\n" + "\n".join(x for x in pieces if x))

    def _load_schema_corpora(self) -> None:
        entries: list[SchemaCorpusEntry] = []
        for corpus_type, path in (
            ("law_schema", self.law_schema_corpus_path),
            ("problem_schema", self.problem_schema_corpus_path),
            ("concept", self.concept_corpus_path),
        ):
            for obj in self._load_jsonl_dicts(path):
                row_id = str(obj.get("id") or "").strip()
                if not row_id:
                    continue
                entries.append(
                    SchemaCorpusEntry(
                        corpus_type=corpus_type,
                        row_id=row_id,
                        retrieval_text=self._schema_retrieval_text(corpus_type, obj),
                        raw=obj,
                    )
                )
        self.schema_entries = entries

    def _load_alias_map(self) -> None:
        entries: list[AliasMapEntry] = []
        for obj in self._load_jsonl_dicts(self.alias_map_path):
            alias_name = str(obj.get("alias_name") or "").strip()
            alias_fq_name = str(obj.get("alias_fq_name") or "").strip()
            alias_to_fq_name = str(obj.get("alias_to_fq_name") or "").strip()
            if not alias_name or not alias_fq_name or not alias_to_fq_name:
                continue
            entries.append(
                AliasMapEntry(
                    alias_name=alias_name,
                    alias_fq_name=alias_fq_name,
                    alias_to_fq_name=alias_to_fq_name,
                    source_path=str(obj.get("source_path") or "").strip(),
                    source_line=self._as_int_or_none(obj.get("source_line")),
                )
            )
        self.alias_entries = entries
        self.alias_entries_by_name = {entry.alias_name: entry for entry in entries}

    def _load_alignment_index(self) -> None:
        if not self.alignment_index_path.exists():
            self.alignment_index = {}
            return
        try:
            obj = json.loads(self.alignment_index_path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            obj = {}
        self.alignment_index = obj if isinstance(obj, dict) else {}

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
            applicability_hint = (
                f"module={entry.module}; law_tags={entry.law_tags}"
                if entry.law_tags
                else f"module={entry.module}"
            )
            rows.append(
                {
                    "score": score,
                    "theorem_name": entry.symbol_name,
                    "symbol_name": entry.symbol_name,
                    "kind": entry.kind,
                    "module": entry.module,
                    "import_hint": entry.import_hint,
                    "declaration_signature": entry.declaration_signature,
                    "law_tags": entry.law_tags,
                    "applicability_hint": applicability_hint,
                    "proof_usage_hint": truncate(entry.proof_style_example, 220),
                    "tactic_hints": entry.tactic_hints[:5],
                    "proof_style_example": truncate(entry.proof_style_example, 220),
                    "path": entry.path,
                }
            )
        return rows

    def _import_hints_from_required_imports(self, imports: list[str]) -> list[str]:
        hints: list[str] = []
        seen: set[str] = set()
        for item in imports:
            text = item.strip()
            if not text:
                continue
            hint = text if text.startswith("import ") else f"import {text}"
            if hint in seen:
                continue
            seen.add(hint)
            hints.append(hint)
        if not hints:
            hints.append("import MechLib")
        return hints

    def _decl_keywords(self, entry: EnrichedDeclEntry) -> set[str]:
        parts = [
            entry.fq_name,
            entry.short_name,
            entry.module,
            entry.namespace,
            entry.statement,
            entry.summary_en,
            entry.retrieval_text,
            " ".join(entry.tags),
            " ".join(entry.law_schema_ids),
            " ".join(entry.problem_schema_ids),
            " ".join(entry.concept_ids),
            entry.primary_spec_id,
            " ".join(entry.secondary_spec_ids),
            " ".join(entry.premise_role),
        ]
        tokens: set[str] = set()
        for part in parts:
            tokens.update(_to_ascii_tokens(part))
            for chunk in re.split(r"[._:/-]+", part):
                tokens.update(_to_ascii_tokens(chunk))
        return tokens

    def _schema_keywords(self, entry: SchemaCorpusEntry) -> set[str]:
        tokens = _to_ascii_tokens(entry.retrieval_text)
        for chunk in re.split(r"[._:/-]+", entry.retrieval_text):
            tokens.update(_to_ascii_tokens(chunk))
        return tokens

    def _decl_to_retrieval_row(self, entry: EnrichedDeclEntry, score: float) -> dict[str, Any]:
        import_hints = self._import_hints_from_required_imports(entry.required_imports)
        proof_hint = "; ".join(entry.proof_hints[:2])
        return {
            "score": score,
            "theorem_name": entry.short_name,
            "symbol_name": entry.short_name,
            "fq_name": entry.fq_name,
            "kind": entry.kind,
            "module": entry.module,
            "namespace": entry.namespace,
            "import_hint": import_hints[0],
            "required_imports": import_hints,
            "declaration_signature": entry.statement,
            "statement": entry.statement,
            "tags": entry.tags,
            "law_tags": entry.tags,
            "summary_en": entry.summary_en,
            "proof_hints": entry.proof_hints,
            "proof_usage_hint": truncate(proof_hint, 220),
            "proof_style_example": truncate(proof_hint, 220),
            "applicability_hint": truncate(
                (
                    f"status={entry.status}; trust_level={entry.trust_level}; "
                    f"callable_by_llm={entry.callable_by_llm}; "
                    f"law_schema_ids={entry.law_schema_ids}; problem_schema_ids={entry.problem_schema_ids}"
                ),
                260,
            ),
            "status": entry.status,
            "trust_level": entry.trust_level,
            "callable_by_llm": entry.callable_by_llm,
            "needs_review": entry.needs_review,
            "proof_eligible": bool(entry.status == "verified" and entry.callable_by_llm and not entry.needs_review),
            "primary_spec_id": entry.primary_spec_id,
            "secondary_spec_ids": entry.secondary_spec_ids,
            "concept_ids": entry.concept_ids,
            "law_schema_ids": entry.law_schema_ids,
            "problem_schema_ids": entry.problem_schema_ids,
            "alignment_method": entry.alignment_method,
            "alignment_score": entry.alignment_score,
            "source_path": entry.source_path,
            "source_line": entry.source_line,
            "source": "decl_corpus_enriched",
        }

    def _schema_to_retrieval_row(self, entry: SchemaCorpusEntry, score: float) -> dict[str, Any]:
        raw = entry.raw
        return {
            "score": score,
            "schema_id": entry.row_id,
            "corpus_type": entry.corpus_type,
            "topic": raw.get("topic") or raw.get("zh_name") or raw.get("en_name"),
            "statement_text": raw.get("statement_text"),
            "candidate_laws": raw.get("candidate_laws", []),
            "verified_decls": raw.get("verified_decls", []),
            "schema_decls": raw.get("schema_decls", []),
            "expected_lean_objects": raw.get("expected_lean_objects", []),
            "retrieval_text": truncate(entry.retrieval_text, 420),
            "proof_eligible": False,
            "source": entry.corpus_type,
        }

    def _retrieve_decl_rows(
        self,
        problem_text: str,
        problem_ir: dict[str, Any] | None,
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        if not self.decl_entries:
            return []
        k = top_k or self.top_k
        query_tokens, target_laws = self._query_tokens(problem_text, problem_ir)
        scored: list[tuple[float, EnrichedDeclEntry]] = []
        for entry in self.decl_entries:
            proof_eligible = entry.status == "verified" and entry.callable_by_llm and not entry.needs_review
            if not proof_eligible:
                continue
            kws = self._decl_keywords(entry)
            overlap = len(query_tokens.intersection(kws))
            law_text = " ".join([*entry.tags, *entry.law_schema_ids, entry.primary_spec_id, *entry.secondary_spec_ids])
            law_tokens = _to_ascii_tokens(law_text)
            law_overlap = len({law.lower() for law in target_laws}.intersection(law_tokens))
            if overlap == 0 and law_overlap == 0:
                continue
            score = 0.0
            score += min(1.0, overlap / max(1, min(12, len(kws)))) * 0.72
            score += min(1.0, law_overlap / 2.0) * 0.18
            if entry.trust_level == "core":
                score += 0.05
            if entry.proof_hints:
                score += 0.03
            if entry.required_imports:
                score += 0.02
            scored.append((round(min(score, 1.0), 6), entry))
        scored.sort(key=lambda x: (-x[0], x[1].module, x[1].fq_name))
        return [self._decl_to_retrieval_row(entry, score) for score, entry in scored[:k]]

    def _retrieve_schema_rows(
        self,
        problem_text: str,
        problem_ir: dict[str, Any] | None,
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        if not self.schema_entries:
            return []
        k = top_k or self.top_k
        query_tokens, target_laws = self._query_tokens(problem_text, problem_ir)
        scored: list[tuple[float, SchemaCorpusEntry]] = []
        for entry in self.schema_entries:
            kws = self._schema_keywords(entry)
            overlap = len(query_tokens.intersection(kws))
            law_overlap = len({law.lower() for law in target_laws}.intersection(kws))
            if overlap == 0 and law_overlap == 0:
                continue
            score = 0.0
            score += min(1.0, overlap / max(1, min(12, len(kws)))) * 0.8
            score += min(1.0, law_overlap / 2.0) * 0.2
            scored.append((round(score, 6), entry))
        scored.sort(key=lambda x: (-x[0], x[1].corpus_type, x[1].row_id))
        return [self._schema_to_retrieval_row(entry, score) for score, entry in scored[:k]]

    def _extend_decl_rows_from_schema(
        self,
        decl_rows: list[dict[str, Any]],
        schema_rows: list[dict[str, Any]],
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        k = top_k or self.top_k
        seen = {str(row.get("fq_name") or "") for row in decl_rows}
        out = list(decl_rows)
        for row in schema_rows:
            verified_decls = row.get("verified_decls")
            if not isinstance(verified_decls, list):
                continue
            for ref in verified_decls:
                name = str(ref or "").strip()
                entry = self.decl_entries_by_name.get(name)
                if entry is None:
                    continue
                if not (entry.status == "verified" and entry.callable_by_llm and not entry.needs_review):
                    continue
                if entry.fq_name in seen:
                    continue
                seen.add(entry.fq_name)
                out.append(self._decl_to_retrieval_row(entry, 0.01))
                if len(out) >= k:
                    return out
        return out

    def _select_alias_rows(self, decl_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not self.alias_entries:
            return []
        targets = {str(row.get("fq_name") or "") for row in decl_rows}
        targets.update(str(row.get("theorem_name") or "") for row in decl_rows)
        out: list[dict[str, Any]] = []
        for entry in self.alias_entries:
            if entry.alias_to_fq_name not in targets and entry.alias_name not in targets:
                continue
            out.append(entry.to_row())
        return out

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
            hints: list[str] = []
            required = row.get("required_imports")
            if isinstance(required, list):
                hints.extend(str(item).strip() for item in required if str(item).strip())
            hint = str(row.get("import_hint") or "").strip()
            if hint:
                hints.append(hint)
            for item in hints:
                if item in seen_import:
                    continue
                seen_import.add(item)
                import_hints.append(item)

        law_matched_items: list[dict[str, Any]] = []
        for row in rows:
            law_matched_items.append(
                {
                    "theorem_name": row.get("theorem_name") or row.get("symbol_name"),
                    "fq_name": row.get("fq_name"),
                    "module": row.get("module"),
                    "symbol_name": row.get("symbol_name"),
                    "kind": row.get("kind"),
                    "score": row.get("score"),
                    "law_tags": row.get("law_tags"),
                    "status": row.get("status"),
                    "trust_level": row.get("trust_level"),
                    "callable_by_llm": row.get("callable_by_llm"),
                    "proof_eligible": row.get("proof_eligible"),
                    "required_imports": row.get("required_imports", []),
                    "law_schema_ids": row.get("law_schema_ids", []),
                    "problem_schema_ids": row.get("problem_schema_ids", []),
                    "alignment_score": row.get("alignment_score"),
                    "declaration_signature": truncate(str(row.get("declaration_signature") or ""), 200),
                    "applicability_hint": truncate(str(row.get("applicability_hint") or ""), 220),
                    "proof_usage_hint": truncate(str(row.get("proof_usage_hint") or ""), 220),
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
                f"[{idx}] theorem_name={row.get('theorem_name')} module={row.get('module')} "
                f"kind={row.get('kind')} symbol={row.get('symbol_name')} "
                f"fq_name={row.get('fq_name')} score={row.get('score')} "
                f"law_tags={row.get('law_tags')} proof_eligible={row.get('proof_eligible')}"
            )
            lines.append(f"signature: {truncate(str(row.get('declaration_signature') or ''), 260)}")
            applicability_hint = str(row.get("applicability_hint") or "").strip()
            if applicability_hint:
                lines.append(f"applicability_hint: {truncate(applicability_hint, 260)}")
            proof_usage_hint = str(row.get("proof_usage_hint") or "").strip()
            if proof_usage_hint:
                lines.append(f"proof_usage_hint: {truncate(proof_usage_hint, 260)}")
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
        verified_decl_items: list[dict[str, Any]] = []
        schema_items: list[dict[str, Any]] = []
        alias_items: list[dict[str, Any]] = []

        if self.context_source in {"hybrid", "summary_only"} and self.summary_entries:
            summary_items = self._select_summary_rows(selected_tags=selected_tags)
        if self.enriched_corpus_enabled:
            verified_decl_items = self._retrieve_decl_rows(
                problem_text=problem_text,
                problem_ir=problem_ir,
                top_k=top_k,
            )
            schema_items = self._retrieve_schema_rows(
                problem_text=problem_text,
                problem_ir=problem_ir,
                top_k=top_k,
            )
            verified_decl_items = self._extend_decl_rows_from_schema(
                verified_decl_items,
                schema_items,
                top_k=top_k,
            )
            alias_items = self._select_alias_rows(verified_decl_items)
        if self.context_source in {"hybrid", "source_only"}:
            source_items = self._retrieve_source_rows(problem_text=problem_text, problem_ir=problem_ir, top_k=top_k)

        decl_pack = self.build_context_pack_from_rows(verified_decl_items)
        source_pack = self.build_context_pack_from_rows(source_items)
        combined_import_hints: list[str] = []
        seen_import: set[str] = set()
        for hint in [*decl_pack.get("import_hints", []), *source_pack.get("import_hints", [])]:
            text = str(hint or "").strip()
            if not text or text in seen_import:
                continue
            seen_import.add(text)
            combined_import_hints.append(text)
        combined_law_items = [
            *decl_pack.get("law_matched_items", []),
            *source_pack.get("law_matched_items", []),
        ]
        gap_schema_only = bool(schema_items and not verified_decl_items)
        lines: list[str] = []
        lines.append("Library Learning Preamble:")
        lines.append("Learn this MechLib domain summary context first, then generate Lean declarations.")
        lines.append("Do not copy verbatim; adapt symbols and assumptions to this specific problem.")
        lines.append("Only Verified Declaration Context items are proof-eligible.")
        lines.append("Schema Context items are modeling metadata only; never cite them as proof facts.")
        lines.append("")
        lines.append(f"Domain from A.physical_laws: {domain_from_a if domain_from_a else ['(fallback)']}")
        lines.append(f"Selected domain tags: {selected_tags}")
        lines.append(f"gap_schema_only: {gap_schema_only}")

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
        lines.append("Verified Declaration Context (from decl_corpus_enriched.jsonl; proof-eligible only):")
        if verified_decl_items:
            for idx, row in enumerate(verified_decl_items, start=1):
                lines.append(
                    f"[{idx}] theorem_name={row.get('theorem_name')} "
                    f"fq_name={row.get('fq_name')} module={row.get('module')} kind={row.get('kind')} "
                    f"score={row.get('score')} status={row.get('status')} trust_level={row.get('trust_level')} "
                    f"callable_by_llm={row.get('callable_by_llm')} proof_eligible={row.get('proof_eligible')}"
                )
                lines.append(f"required_imports: {row.get('required_imports', [])}")
                lines.append(f"statement: {truncate(str(row.get('statement') or row.get('declaration_signature') or ''), 320)}")
                lines.append(f"proof_hints: {truncate(json.dumps(row.get('proof_hints', []), ensure_ascii=False), 260)}")
                lines.append(f"law_schema_ids: {row.get('law_schema_ids', [])}")
                lines.append(f"problem_schema_ids: {row.get('problem_schema_ids', [])}")
        else:
            lines.append("(none)")

        lines.append("")
        lines.append("Schema Context (metadata only; not proof facts):")
        if schema_items:
            for idx, row in enumerate(schema_items, start=1):
                lines.append(
                    f"[{idx}] schema_id={row.get('schema_id')} corpus_type={row.get('corpus_type')} "
                    f"score={row.get('score')} proof_eligible=False"
                )
                topic = str(row.get("topic") or "").strip()
                if topic:
                    lines.append(f"topic: {truncate(topic, 160)}")
                statement_text = str(row.get("statement_text") or "").strip()
                if statement_text:
                    lines.append(f"statement_text: {truncate(statement_text, 260)}")
                lines.append(f"verified_decls: {row.get('verified_decls', [])}")
                lines.append(f"candidate_laws: {row.get('candidate_laws', [])}")
        else:
            lines.append("(none)")

        if alias_items:
            lines.append("")
            lines.append("Alias Context (aliases to verified declarations):")
            for idx, row in enumerate(alias_items, start=1):
                lines.append(
                    f"[{idx}] alias_name={row.get('alias_name')} alias_fq_name={row.get('alias_fq_name')} "
                    f"alias_to_fq_name={row.get('alias_to_fq_name')}"
                )

        lines.append("")
        lines.append("Source Supplement (from MechLib .lean parsing):")
        lines.append(f"source_items_count: {len(source_items)}")
        lines.append("Import Hints:")
        for hint in combined_import_hints:
            lines.append(f"- {hint}")
        lines.append("Law-Matched Declarations:")
        for idx, row in enumerate(combined_law_items, start=1):
            lines.append(
                f"[{idx}] theorem_name={row.get('theorem_name')} module={row.get('module')} "
                f"kind={row.get('kind')} symbol={row.get('symbol_name')} "
                f"fq_name={row.get('fq_name')} score={row.get('score')} "
                f"law_tags={row.get('law_tags')} proof_eligible={row.get('proof_eligible')}"
            )
            lines.append(f"signature: {truncate(str(row.get('declaration_signature') or ''), 260)}")
            applicability_hint = str(row.get("applicability_hint") or "").strip()
            if applicability_hint:
                lines.append(f"applicability_hint: {truncate(applicability_hint, 260)}")
            proof_usage_hint = str(row.get("proof_usage_hint") or "").strip()
            if proof_usage_hint:
                lines.append(f"proof_usage_hint: {truncate(proof_usage_hint, 260)}")
        if source_pack["proof_style_examples"]:
            lines.append("Proof-Style Examples (style only):")
            for idx, ex in enumerate(source_pack["proof_style_examples"], start=1):
                lines.append(f"[{idx}] {truncate(ex, 260)}")

        context_text = "\n".join(lines)
        return {
            "domain_from_a": domain_from_a,
            "selected_tags": selected_tags,
            "summary_items": summary_items,
            "verified_decl_items": verified_decl_items,
            "schema_items": schema_items,
            "alias_items": alias_items,
            "source_items": source_items,
            "import_hints": combined_import_hints,
            "law_matched_items": combined_law_items,
            "proof_style_examples": source_pack.get("proof_style_examples", []),
            "context_text": context_text,
            "summary_items_count": len(summary_items),
            "verified_decl_items_count": len(verified_decl_items),
            "schema_items_count": len(schema_items),
            "alias_items_count": len(alias_items),
            "source_items_count": len(source_items),
            "final_context_chars": len(context_text),
            "gap_schema_only": gap_schema_only,
        }
