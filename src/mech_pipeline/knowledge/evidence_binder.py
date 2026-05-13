from __future__ import annotations

import re
import tempfile
import threading
from pathlib import Path
from typing import Any

from mech_pipeline.knowledge.mechlib_structured import StructuredMechLibContext
from mech_pipeline.types import EvidenceBinding, ModelIR, ModelInstance
from mech_pipeline.utils import ensure_dir, safe_stem

TOKEN_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_']*")
STOP_TOKENS = {
    "a",
    "an",
    "and",
    "by",
    "decl",
    "declaration",
    "is",
    "law",
    "lemma",
    "mechlib",
    "of",
    "real",
    "relation",
    "the",
    "theorem",
    "to",
    "use",
}


class LeanDeclCheckCache:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._values: dict[str, bool | None] = {}
        self._inflight: dict[str, threading.Event] = {}
        self.hits = 0
        self.misses = 0
        self.waits = 0

    def get_or_compute(self, fq_name: str, compute) -> bool | None:
        key = str(fq_name or "").strip()
        if not key:
            return compute()
        with self._lock:
            if key in self._values:
                self.hits += 1
                return self._values[key]
            event = self._inflight.get(key)
            if event is None:
                event = threading.Event()
                self._inflight[key] = event
                self.misses += 1
                should_wait = False
            else:
                self.waits += 1
                should_wait = True
        if should_wait:
            event.wait()
            with self._lock:
                self.hits += 1
                return self._values.get(key)
        result: bool | None = None
        try:
            result = compute()
            return result
        finally:
            with self._lock:
                self._values[key] = result
                self._inflight.pop(key, None)
                event.set()

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "checked_decl_count": len(self._values),
                "decl_check_cache_hits": self.hits,
                "decl_check_cache_misses": self.misses,
                "decl_check_cache_waits": self.waits,
            }


def _tokens(text: str) -> set[str]:
    out = {tok.lower() for tok in TOKEN_PATTERN.findall(text or "")}
    for chunk in re.split(r"[._:/-]+", text or ""):
        out.update(tok.lower() for tok in TOKEN_PATTERN.findall(chunk))
    return {tok for tok in out if tok not in STOP_TOKENS and len(tok) > 1}


def _string_list(value: object) -> list[str]:
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _import_lines(value: object) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()
    for item in _string_list(value):
        line = item if item.startswith(("import ", "open ")) else f"import {item}"
        if line in seen:
            continue
        seen.add(line)
        lines.append(line)
    return lines or ["import MechLib"]


def _context_dict(context: StructuredMechLibContext | dict[str, Any]) -> dict[str, Any]:
    if isinstance(context, StructuredMechLibContext):
        return context.to_dict()
    return context


def _model_instances(value: ModelIR | list[ModelInstance]) -> tuple[str | None, list[ModelInstance]]:
    if isinstance(value, ModelIR):
        return value.sample_id, list(value.model_instances)
    return None, list(value)


def _model_text(instance: ModelInstance, problem_text: str, problem_ir: dict[str, Any] | None) -> str:
    ir = problem_ir or {}
    parts = [
        instance.instance_id,
        instance.kind,
        instance.natural_language,
        instance.coordinate_convention or "",
        instance.planning_schema_id or "",
        instance.expected_claim or "",
        instance.hypothesis_form or "",
        " ".join(str(x) for x in instance.entities),
        " ".join(str(k) for k in instance.variables.keys()),
        " ".join(str(v) for v in instance.variables.values()),
        " ".join(str(k) for k in instance.parameters.keys()),
        " ".join(str(v) for v in instance.parameters.values()),
        " ".join(str(v) for v in instance.provenance.values()),
        problem_text,
        str(ir.get("goal_statement") or ""),
    ]
    laws = ir.get("physical_laws")
    if isinstance(laws, list):
        parts.extend(str(x) for x in laws)
    unknown = ir.get("unknown_target")
    if isinstance(unknown, dict):
        parts.extend(str(v) for v in unknown.values())
    return "\n".join(parts)


def _decl_text(row: dict[str, Any]) -> str:
    pieces = [
        str(row.get("fq_name") or ""),
        str(row.get("theorem_name") or ""),
        str(row.get("symbol_name") or ""),
        str(row.get("short_name") or ""),
        str(row.get("statement") or ""),
        str(row.get("declaration_signature") or ""),
        str(row.get("summary_en") or ""),
        str(row.get("retrieval_text") or ""),
        " ".join(_string_list(row.get("tags"))),
        " ".join(_string_list(row.get("law_schema_ids"))),
        " ".join(_string_list(row.get("problem_schema_ids"))),
        str(row.get("primary_spec_id") or ""),
        " ".join(_string_list(row.get("secondary_spec_ids"))),
        " ".join(_string_list(row.get("concept_ids"))),
    ]
    return "\n".join(pieces)


def _alias_targets(context: dict[str, Any], model_tokens: set[str]) -> set[str]:
    aliases = context.get("modeling_context", {}).get("aliases", [])
    targets: set[str] = set()
    if not isinstance(aliases, list):
        return targets
    for row in aliases:
        if not isinstance(row, dict):
            continue
        alias_name = str(row.get("alias_name") or "")
        alias_fq_name = str(row.get("alias_fq_name") or "")
        alias_tokens = _tokens(f"{alias_name} {alias_fq_name}")
        if model_tokens.intersection(alias_tokens):
            target = str(row.get("alias_to_fq_name") or "").strip()
            if target:
                targets.add(target)
    return targets


def _score_decl(
    *,
    instance: ModelInstance,
    row: dict[str, Any],
    model_tokens: set[str],
    alias_targets: set[str],
) -> float:
    fq_name = str(row.get("fq_name") or "").strip()
    short_name = str(row.get("theorem_name") or row.get("symbol_name") or fq_name.rsplit(".", 1)[-1]).strip()
    score = 0.0

    planning_schema = str(instance.planning_schema_id or "").strip()
    schema_ids = {
        *(_string_list(row.get("law_schema_ids"))),
        *(_string_list(row.get("problem_schema_ids"))),
        str(row.get("primary_spec_id") or "").strip(),
        *(_string_list(row.get("secondary_spec_ids"))),
    }
    schema_ids.discard("")
    if planning_schema and planning_schema in schema_ids:
        score += 6.0
    if fq_name and fq_name in alias_targets:
        score += 4.0
    if short_name and short_name.lower() in model_tokens:
        score += 3.0
    if fq_name and _tokens(fq_name).intersection(model_tokens):
        score += 1.5
    tag_overlap = len(set(_string_list(row.get("tags"))).intersection({tok.title() for tok in model_tokens}))
    score += min(2.0, float(tag_overlap))
    overlap = len(model_tokens.intersection(_tokens(_decl_text(row))))
    if overlap:
        score += min(2.5, overlap / 4.0)
    return round(score, 6)


def _eligible_decl_rows(context: dict[str, Any]) -> list[dict[str, Any]]:
    rows = context.get("proof_context", {}).get("verified_decls", [])
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        fq_name = str(row.get("fq_name") or "").strip()
        if not fq_name:
            continue
        if row.get("proof_fact_allowed") is not True:
            continue
        if str(row.get("status") or "").strip().lower() != "verified":
            continue
        if str(row.get("trust_level") or "").strip().lower() not in {"core", "derived"}:
            continue
        if row.get("callable_by_llm") is not True:
            continue
        out.append(row)
    return out


class EvidenceBinder:
    def __init__(
        self,
        top_k: int = 8,
        lean_runner: Any | None = None,
        lean_check_decls: bool = True,
        run_dir: Path | None = None,
        excluded_decl_names: set[str] | list[str] | None = None,
        lean_check_cache: LeanDeclCheckCache | None = None,
    ) -> None:
        self.top_k = top_k
        self.lean_runner = lean_runner
        self.lean_check_decls = lean_check_decls
        self.run_dir = Path(run_dir).resolve() if run_dir is not None else None
        self._lean_check_cache: dict[str, bool] = {}
        self.shared_lean_check_cache = lean_check_cache
        self.excluded_decl_names = {str(name).strip() for name in (excluded_decl_names or []) if str(name).strip()}

    def bind(
        self,
        model_ir_or_instances: ModelIR | list[ModelInstance],
        context: StructuredMechLibContext | dict[str, Any],
        *,
        problem_text: str = "",
        problem_ir: dict[str, Any] | None = None,
    ) -> list[EvidenceBinding]:
        _sample_id, instances = _model_instances(model_ir_or_instances)
        context_dict = _context_dict(context)
        rows = [
            row
            for row in _eligible_decl_rows(context_dict)
            if str(row.get("fq_name") or "").strip() not in self.excluded_decl_names
        ]
        bindings: list[EvidenceBinding] = []
        for instance in instances:
            scored = self._rank_rows(instance, rows, context_dict, problem_text, problem_ir)
            if not scored:
                bindings.append(self._gap_binding(instance))
                continue
            for rank, (score, row) in enumerate(scored[: self.top_k], start=1):
                bindings.append(self._binding_from_row(instance, row, rank, score))
        return bindings

    def _rank_rows(
        self,
        instance: ModelInstance,
        rows: list[dict[str, Any]],
        context: dict[str, Any],
        problem_text: str,
        problem_ir: dict[str, Any] | None,
    ) -> list[tuple[float, dict[str, Any]]]:
        model_tokens = _tokens(_model_text(instance, problem_text, problem_ir))
        aliases = _alias_targets(context, model_tokens)
        scored: list[tuple[float, dict[str, Any]]] = []
        for row in rows:
            score = _score_decl(instance=instance, row=row, model_tokens=model_tokens, alias_targets=aliases)
            if score <= 0:
                continue
            scored.append((score, row))
        scored.sort(key=lambda item: (-item[0], str(item[1].get("fq_name") or "")))
        return scored

    def _gap_binding(self, instance: ModelInstance) -> EvidenceBinding:
        return EvidenceBinding(
            binding_id=f"{instance.instance_id}_binding_gap",
            model_instance_id=instance.instance_id,
            planning_schema=instance.planning_schema_id,
            verified_decl=None,
            required_imports=[],
            lean_check_pass=None,
            proof_fact_allowed=False,
            binding_status="gap_schema_only",
            expected_claim=instance.expected_claim,
            notes="No proof-eligible verified declaration matched this model instance.",
        )

    def _binding_from_row(
        self,
        instance: ModelInstance,
        row: dict[str, Any],
        rank: int,
        score: float,
    ) -> EvidenceBinding:
        fq_name = str(row.get("fq_name") or "").strip()
        required_imports = _import_lines(row.get("required_imports"))
        lean_check_pass = self._check_decl(fq_name, required_imports)
        binding_status = "ok"
        proof_fact_allowed = True
        notes = f"matched_score={score}"
        if lean_check_pass is False:
            binding_status = "lean_check_failed"
            proof_fact_allowed = False
            notes = f"{notes}; #check failed"
        return EvidenceBinding(
            binding_id=f"{instance.instance_id}_binding_{rank}",
            model_instance_id=instance.instance_id,
            planning_schema=instance.planning_schema_id,
            verified_decl=fq_name,
            decl_statement=str(row.get("statement") or row.get("declaration_signature") or "").strip() or None,
            decl_status=str(row.get("status") or "").strip() or None,
            trust_level=str(row.get("trust_level") or "").strip() or None,
            callable_by_llm=bool(row.get("callable_by_llm")),
            required_imports=required_imports,
            lean_check_pass=lean_check_pass,
            proof_fact_allowed=proof_fact_allowed,
            binding_status=binding_status,
            expected_claim=instance.expected_claim,
            notes=notes,
        )

    def _check_decl(self, fq_name: str, required_imports: list[str]) -> bool | None:
        if not self.lean_check_decls or self.lean_runner is None:
            return None
        if getattr(self.lean_runner, "enabled", True) is False:
            return None
        if hasattr(self.lean_runner, "_mechlib_ready") and getattr(self.lean_runner, "_mechlib_ready") is False:
            return None
        if fq_name in self._lean_check_cache:
            return self._lean_check_cache[fq_name]
        if self.shared_lean_check_cache is not None:
            result = self.shared_lean_check_cache.get_or_compute(
                fq_name,
                lambda: self._check_decl_uncached(fq_name, required_imports),
            )
            if result is not None:
                self._lean_check_cache[fq_name] = bool(result)
            return result
        result = self._check_decl_uncached(fq_name, required_imports)
        if result is not None:
            self._lean_check_cache[fq_name] = bool(result)
        return result

    def _check_decl_uncached(self, fq_name: str, required_imports: list[str]) -> bool | None:
        if hasattr(self.lean_runner, "check_decl"):
            result = self.lean_runner.check_decl(fq_name, required_imports)
            ok = bool(result[0] if isinstance(result, tuple) else result)
            return ok
        if not hasattr(self.lean_runner, "_run_lean"):
            return None
        root = self._lean_root()
        if root is None:
            return None
        imports = _import_lines(required_imports)
        code = "\n".join(imports) + f"\n\n#check {fq_name}\n"
        if self.run_dir is not None:
            tmp_dir = self.run_dir / ".pipeline1_tmp" / "evidence_check"
            ensure_dir(tmp_dir)
            tmp_file = tmp_dir / f"{safe_stem(fq_name)}.lean"
            tmp_file.write_text(code, encoding="utf-8")
            ok, _stdout, _stderr = self.lean_runner._run_lean(root_dir=root, rel_file=tmp_file)
        else:
            with tempfile.TemporaryDirectory(prefix="mech_evidence_check_") as tmp:
                tmp_file = Path(tmp) / f"{safe_stem(fq_name)}.lean"
                tmp_file.write_text(code, encoding="utf-8")
                ok, _stdout, _stderr = self.lean_runner._run_lean(root_dir=root, rel_file=tmp_file)
        return bool(ok)

    def _lean_root(self) -> Path | None:
        if hasattr(self.lean_runner, "_backend_root"):
            try:
                return self.lean_runner._backend_root("mechlib")
            except Exception:
                pass
        mechlib_dir = getattr(self.lean_runner, "mechlib_dir", None)
        if mechlib_dir:
            return Path(mechlib_dir)
        return None


def evidence_binding_stage_rows(sample_id: str, bindings: list[EvidenceBinding]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for binding in bindings:
        rows.append({"sample_id": sample_id, **binding.to_dict()})
    return rows
