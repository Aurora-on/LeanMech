from __future__ import annotations

import json
from pathlib import Path

import pytest

from mech_pipeline.knowledge.mechlib import MechLibRetriever
from mech_pipeline.knowledge.mechlib_structured import (
    build_structured_mechlib_context,
    structured_context_stage_row,
)


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + ("\n" if rows else ""), encoding="utf-8")


def _retriever(
    tmp_path: Path,
    *,
    decl_rows: list[dict[str, object]] | None = None,
    summary_rows: list[dict[str, object]] | None = None,
    write_decl_corpus: bool = True,
) -> MechLibRetriever:
    corpus = tmp_path / "corpus"
    decl_path = corpus / "decl_corpus_enriched.jsonl"
    summary_path = corpus / "theorem_corpus.jsonl"
    law_path = corpus / "law_schema_corpus.jsonl"
    problem_path = corpus / "problem_schema_corpus.jsonl"
    concept_path = corpus / "concept_corpus.jsonl"
    alias_path = corpus / "alias_map.jsonl"
    alignment_path = corpus / "decl_to_spec_index.json"
    if write_decl_corpus:
        _write_jsonl(decl_path, decl_rows or [])
    _write_jsonl(summary_path, summary_rows or [])
    _write_jsonl(
        law_path,
        [
            {
                "id": "law.kinematics.constant_speed",
                "en_name": "constant speed kinematics",
                "statement_text": "Displacement equals speed times time.",
                "verified_decls": ["MechLib.Kinematics.constant_speed_relation"],
                "status": "schema",
            }
        ],
    )
    _write_jsonl(
        problem_path,
        [
            {
                "id": "problem.uniform_motion",
                "topic": "uniform motion",
                "candidate_laws": ["law.kinematics.constant_speed"],
                "verified_decls": ["MechLib.Kinematics.constant_speed_relation"],
            }
        ],
    )
    _write_jsonl(
        concept_path,
        [
            {
                "id": "concept.displacement",
                "en_name": "displacement",
                "description": "Change in position over a time interval.",
                "related_laws": ["law.kinematics.constant_speed"],
                "tags": ["Kinematics"],
            }
        ],
    )
    _write_jsonl(
        alias_path,
        [
            {
                "alias_name": "const_speed_alias",
                "alias_fq_name": "MechLib.Compat.const_speed_alias",
                "alias_to_fq_name": "MechLib.Kinematics.constant_speed_relation",
                "source_path": "MechLib/Compat.lean",
                "source_line": 1,
            }
        ],
    )
    alignment_path.write_text("{}", encoding="utf-8")
    return MechLibRetriever(
        mechlib_dir=tmp_path,
        summary_corpus_path=summary_path,
        decl_corpus_path=decl_path,
        law_schema_corpus_path=law_path,
        problem_schema_corpus_path=problem_path,
        concept_corpus_path=concept_path,
        alias_map_path=alias_path,
        alignment_index_path=alignment_path,
    )


def _eligible_decl() -> dict[str, object]:
    return {
        "id": "decl.constant_speed_relation",
        "kind": "theorem",
        "fq_name": "MechLib.Kinematics.constant_speed_relation",
        "short_name": "constant_speed_relation",
        "namespace": "MechLib.Kinematics",
        "module": "MechLib.Kinematics",
        "statement": "theorem constant_speed_relation (s v t : Real) : s = v * t",
        "tags": ["Kinematics"],
        "summary_en": "constant speed displacement relation",
        "proof_hints": ["exact MechLib.Kinematics.constant_speed_relation"],
        "retrieval_text": "constant speed displacement relation s = v * t Kinematics",
        "status": "verified",
        "trust_level": "core",
        "callable_by_llm": True,
        "required_imports": ["MechLib"],
        "law_schema_ids": ["law.kinematics.constant_speed"],
        "problem_schema_ids": ["problem.uniform_motion"],
        "needs_review": False,
    }


def test_structured_context_separates_modeling_metadata_from_proof_context(tmp_path: Path) -> None:
    retriever = _retriever(
        tmp_path,
        decl_rows=[
            _eligible_decl(),
            {
                **_eligible_decl(),
                "id": "decl.not_callable",
                "fq_name": "MechLib.Kinematics.not_callable",
                "short_name": "not_callable",
                "callable_by_llm": False,
            },
            {
                **_eligible_decl(),
                "id": "decl.needs_review",
                "fq_name": "MechLib.Kinematics.needs_review",
                "short_name": "needs_review",
                "needs_review": True,
            },
            {
                **_eligible_decl(),
                "id": "decl.schema_status",
                "fq_name": "MechLib.Kinematics.schema_status",
                "short_name": "schema_status",
                "status": "schema",
            },
        ],
    )

    context = build_structured_mechlib_context(
        retriever,
        problem_text="A point moves at constant speed v for time t. Find displacement s.",
        problem_ir={
            "physical_laws": ["Kinematics"],
            "goal_statement": "constant speed displacement",
            "unknown_target": {"symbol": "s", "description": "displacement"},
        },
        top_k=10,
    )
    payload = context.to_dict()

    assert payload["modeling_context"]["law_schemas"]
    assert payload["modeling_context"]["problem_schemas"]
    assert payload["modeling_context"]["concepts"]
    for key in ("law_schemas", "problem_schemas", "concepts", "aliases"):
        assert all(row["proof_fact_allowed"] is False for row in payload["modeling_context"][key])

    proof_decls = payload["proof_context"]["verified_decls"]
    assert [row["fq_name"] for row in proof_decls] == ["MechLib.Kinematics.constant_speed_relation"]
    assert proof_decls[0]["proof_fact_allowed"] is True
    assert proof_decls[0]["required_imports"] == ["import MechLib"]
    assert "schema" in payload["forbidden_as_proof_fact"]
    json.dumps(structured_context_stage_row("s1", context))


def test_structured_context_does_not_fall_back_to_theorem_corpus(tmp_path: Path) -> None:
    retriever = _retriever(
        tmp_path,
        write_decl_corpus=False,
        summary_rows=[
            {
                "id": "summary.constant_speed_relation",
                "fq_name": "MechLib.Kinematics.constant_speed_relation",
                "statement": "theorem constant_speed_relation (s v t : Real) : s = v * t",
                "tags": ["Kinematics"],
                "summary_en": "constant speed displacement relation",
                "retrieval_text": "constant speed displacement relation",
            }
        ],
    )

    context = build_structured_mechlib_context(
        retriever,
        problem_text="constant speed displacement",
        problem_ir={"physical_laws": ["Kinematics"]},
        top_k=5,
    )

    proof_decls = context.to_dict()["proof_context"]["verified_decls"]
    assert proof_decls == []


def test_structured_context_handles_missing_corpus_gracefully(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    retriever = MechLibRetriever(
        mechlib_dir=tmp_path,
        summary_corpus_path=missing / "theorem_corpus.jsonl",
        decl_corpus_path=missing / "decl_corpus_enriched.jsonl",
        law_schema_corpus_path=missing / "law_schema_corpus.jsonl",
        problem_schema_corpus_path=missing / "problem_schema_corpus.jsonl",
        concept_corpus_path=missing / "concept_corpus.jsonl",
        alias_map_path=missing / "alias_map.jsonl",
        alignment_index_path=missing / "decl_to_spec_index.json",
    )
    context = build_structured_mechlib_context(retriever, "anything", {}, top_k=3)
    payload = context.to_dict()
    assert payload["modeling_context"]["law_schemas"] == []
    assert payload["proof_context"]["verified_decls"] == []


def test_real_mechlib_corpus_structured_counts_if_available() -> None:
    corpus = Path("../MechLib/corpus")
    if not corpus.exists():
        pytest.skip("local MechLib corpus is not available")
    retriever = MechLibRetriever(mechlib_dir=Path("../MechLib"), top_k=5)
    context = build_structured_mechlib_context(
        retriever,
        problem_text="A point moves at constant speed v for time t. Find displacement s.",
        problem_ir={"physical_laws": ["Kinematics"], "goal_statement": "displacement from speed and time"},
        top_k=5,
    )
    counts = context.source_counts
    assert counts["law_schema_entries"] >= 1
    assert counts["problem_schema_entries"] >= 1
    assert counts["decl_entries"] >= 1
