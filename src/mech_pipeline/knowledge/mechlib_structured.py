from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


FORBIDDEN_AS_PROOF_FACT: dict[str, list[str]] = {
    "schema": ["law_schema"],
    "problem_schema": ["problem_schema"],
    "concept": ["concept"],
    "alignment": ["decl_to_spec_index", "spec_to_decl_index", "spec_alignment_report"],
    "residual": ["summary_context", "source_supplement"],
    "interface": ["module_metadata_corpus"],
    "example_only": ["proof_style_examples"],
}


@dataclass
class StructuredMechLibContext:
    modeling_context: dict[str, Any] = field(default_factory=dict)
    proof_context: dict[str, Any] = field(default_factory=dict)
    forbidden_as_proof_fact: dict[str, Any] = field(default_factory=lambda: dict(FORBIDDEN_AS_PROOF_FACT))
    source_counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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


def _import_hints(required_imports: object) -> list[str]:
    hints: list[str] = []
    seen: set[str] = set()
    for item in _string_list(required_imports):
        hint = item if item.startswith("import ") else f"import {item}"
        if hint in seen:
            continue
        seen.add(hint)
        hints.append(hint)
    return hints or ["import MechLib"]


def _is_proof_eligible_decl(row: dict[str, Any]) -> bool:
    status = str(row.get("status") or "").strip().lower()
    trust_level = str(row.get("trust_level") or "").strip().lower()
    callable_by_llm = row.get("callable_by_llm") is True
    needs_review = row.get("needs_review") is True
    return status == "verified" and trust_level in {"core", "derived"} and callable_by_llm and not needs_review


def _schema_row_for_modeling(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out["proof_fact_allowed"] = False
    out["proof_eligible"] = False
    return out


def _decl_row_for_proof(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out["required_imports"] = _import_hints(out.get("required_imports") or out.get("import_hint"))
    out["proof_fact_allowed"] = _is_proof_eligible_decl(out)
    out["source_type"] = "verified_decl"
    return out


def _retriever_source_counts(retriever: Any) -> dict[str, int]:
    schema_entries = list(getattr(retriever, "schema_entries", []) or [])
    counts = {
        "decl_entries": len(getattr(retriever, "decl_entries", []) or []),
        "summary_entries": len(getattr(retriever, "summary_entries", []) or []),
        "schema_entries": len(schema_entries),
        "law_schema_entries": 0,
        "problem_schema_entries": 0,
        "concept_entries": 0,
        "alias_entries": len(getattr(retriever, "alias_entries", []) or []),
    }
    for entry in schema_entries:
        corpus_type = str(getattr(entry, "corpus_type", "") or "")
        if corpus_type == "law_schema":
            counts["law_schema_entries"] += 1
        elif corpus_type == "problem_schema":
            counts["problem_schema_entries"] += 1
        elif corpus_type == "concept":
            counts["concept_entries"] += 1
    return counts


def _select_summary_rows(retriever: Any, selected_tags: list[str]) -> list[dict[str, Any]]:
    selector = getattr(retriever, "_select_summary_rows", None)
    if callable(selector):
        rows = selector(selected_tags)
        return [dict(row) for row in rows if isinstance(row, dict)]
    return []


def build_structured_mechlib_context(
    retriever: Any,
    problem_text: str,
    problem_ir: dict[str, Any] | None,
    top_k: int | None = None,
) -> StructuredMechLibContext:
    if retriever is None:
        return StructuredMechLibContext(
            modeling_context={
                "matched_topics": [],
                "concepts": [],
                "law_schemas": [],
                "problem_schemas": [],
                "aliases": [],
            },
            proof_context={
                "verified_decls": [],
                "required_imports": [],
                "proof_hints": [],
                "proof_style_examples": [],
            },
            source_counts={},
        )

    select_tags = getattr(retriever, "_select_summary_tags", None)
    if callable(select_tags):
        domain_from_a, selected_tags = select_tags(problem_text=problem_text, problem_ir=problem_ir)
    else:
        domain_from_a, selected_tags = [], []

    schema_rows: list[dict[str, Any]] = []
    retrieve_schema = getattr(retriever, "_retrieve_schema_rows", None)
    if callable(retrieve_schema):
        schema_rows = [dict(row) for row in retrieve_schema(problem_text, problem_ir, top_k) if isinstance(row, dict)]

    decl_rows: list[dict[str, Any]] = []
    retrieve_decls = getattr(retriever, "_retrieve_decl_rows", None)
    if callable(retrieve_decls):
        decl_rows = [dict(row) for row in retrieve_decls(problem_text, problem_ir, top_k) if isinstance(row, dict)]
    extend_decls = getattr(retriever, "_extend_decl_rows_from_schema", None)
    if callable(extend_decls):
        decl_rows = [dict(row) for row in extend_decls(decl_rows, schema_rows, top_k) if isinstance(row, dict)]

    proof_decls = [_decl_row_for_proof(row) for row in decl_rows]
    proof_decls = [row for row in proof_decls if row["proof_fact_allowed"]]

    alias_rows: list[dict[str, Any]] = []
    select_aliases = getattr(retriever, "_select_alias_rows", None)
    if callable(select_aliases):
        alias_seed_rows = proof_decls or decl_rows
        alias_rows = [dict(row) for row in select_aliases(alias_seed_rows) if isinstance(row, dict)]
    for row in alias_rows:
        row["proof_fact_allowed"] = False

    source_rows: list[dict[str, Any]] = []
    retrieve_source = getattr(retriever, "_retrieve_source_rows", None)
    if callable(retrieve_source):
        source_rows = [dict(row) for row in retrieve_source(problem_text, problem_ir, top_k) if isinstance(row, dict)]

    law_schemas = [_schema_row_for_modeling(row) for row in schema_rows if row.get("corpus_type") == "law_schema"]
    problem_schemas = [
        _schema_row_for_modeling(row) for row in schema_rows if row.get("corpus_type") == "problem_schema"
    ]
    concepts = [_schema_row_for_modeling(row) for row in schema_rows if row.get("corpus_type") == "concept"]
    matched_topics = list(domain_from_a or [])
    for row in schema_rows:
        topic = str(row.get("topic") or "").strip()
        if topic and topic not in matched_topics:
            matched_topics.append(topic)

    required_imports: list[str] = []
    seen_imports: set[str] = set()
    proof_hints: list[str] = []
    proof_style_examples: list[str] = []
    for row in proof_decls:
        for item in _string_list(row.get("required_imports")):
            if item not in seen_imports:
                seen_imports.add(item)
                required_imports.append(item)
        for item in _string_list(row.get("proof_hints")):
            if item not in proof_hints:
                proof_hints.append(item)
    for row in source_rows:
        example = str(row.get("proof_style_example") or row.get("proof_usage_hint") or "").strip()
        if example and example not in proof_style_examples:
            proof_style_examples.append(example)

    return StructuredMechLibContext(
        modeling_context={
            "matched_topics": matched_topics,
            "concepts": concepts,
            "law_schemas": law_schemas,
            "problem_schemas": problem_schemas,
            "aliases": alias_rows,
        },
        proof_context={
            "verified_decls": proof_decls,
            "required_imports": required_imports,
            "proof_hints": proof_hints,
            "proof_style_examples": proof_style_examples,
        },
        forbidden_as_proof_fact=dict(FORBIDDEN_AS_PROOF_FACT),
        source_counts=_retriever_source_counts(retriever),
    )


def structured_context_stage_row(sample_id: str, context: StructuredMechLibContext) -> dict[str, Any]:
    return {"sample_id": sample_id, **context.to_dict()}
