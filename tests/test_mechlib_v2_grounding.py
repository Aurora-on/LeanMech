from __future__ import annotations

import json
from pathlib import Path

from mech_pipeline.knowledge.mechlib import MechLibRetriever
from mech_pipeline.model.base import ModelClient
from mech_pipeline.modules.B_statement_gen import ModuleB
from mech_pipeline.modules.D_semantic_rank import ModuleD
from mech_pipeline.types import CompileCheckResult, GroundingResult, ModelResponse, StatementCandidate


class StaticClient(ModelClient):
    def __init__(self, payload: str) -> None:
        self.model_id = "static"
        self.supports_vision = False
        self._payload = payload

    def generate_text(self, prompt: str, **kwargs) -> ModelResponse:
        _ = (prompt, kwargs)
        return ModelResponse(text=self._payload)

    def generate_multimodal(self, prompt: str, images_b64: list[str], **kwargs) -> ModelResponse:
        _ = (prompt, images_b64, kwargs)
        return ModelResponse(text=self._payload)


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def test_mechlib_retriever_loads_v2_verified_decl_and_schema_metadata(tmp_path: Path) -> None:
    decl_path = tmp_path / "corpus" / "decl_corpus_enriched.jsonl"
    law_path = tmp_path / "corpus" / "law_schema_corpus.jsonl"
    problem_path = tmp_path / "corpus" / "problem_schema_corpus.jsonl"
    concept_path = tmp_path / "corpus" / "concept_corpus.jsonl"
    alias_path = tmp_path / "corpus" / "alias_map.jsonl"
    alignment_path = tmp_path / "corpus" / "decl_to_spec_index.json"
    summary_path = tmp_path / "corpus" / "theorem_corpus.jsonl"

    _write_jsonl(
        decl_path,
        [
            {
                "id": "mechlib::MechLib.Kinematics.Verified.Kinematics.constant_speed_relation",
                "kind": "theorem",
                "fq_name": "MechLib.Kinematics.Verified.Kinematics.constant_speed_relation",
                "short_name": "constant_speed_relation",
                "namespace": "MechLib.Kinematics.Verified.Kinematics",
                "module": "MechLib.Kinematics.Verified.Kinematics",
                "statement": "theorem constant_speed_relation (s v t : Real) : s = v * t",
                "tags": ["Kinematics"],
                "summary_en": "constant speed displacement relation",
                "proof_hints": ["exact MechLib.Kinematics.Verified.Kinematics.constant_speed_relation"],
                "retrieval_text": "constant speed displacement relation s = v * t Kinematics",
                "status": "verified",
                "trust_level": "core",
                "callable_by_llm": True,
                "required_imports": ["MechLib.Kinematics.Verified"],
                "law_schema_ids": ["law.kinematics.constant_speed"],
                "problem_schema_ids": ["problem.kinematics.uniform_motion"],
                "needs_review": False,
            }
        ],
    )
    _write_jsonl(
        law_path,
        [
            {
                "id": "law.kinematics.constant_speed",
                "en_name": "constant speed kinematics",
                "statement_text": "Displacement equals speed times time.",
                "verified_decls": ["MechLib.Kinematics.Verified.Kinematics.constant_speed_relation"],
                "status": "schema",
            }
        ],
    )
    _write_jsonl(
        problem_path,
        [
            {
                "id": "problem.kinematics.uniform_motion",
                "topic": "uniform motion",
                "candidate_laws": ["law.kinematics.constant_speed"],
                "verified_decls": ["MechLib.Kinematics.Verified.Kinematics.constant_speed_relation"],
            }
        ],
    )
    _write_jsonl(concept_path, [])
    _write_jsonl(
        alias_path,
        [
            {
                "alias_name": "displacement_delta_t_const_v",
                "alias_fq_name": "MechLib.Compat.PHYSlib.SI.displacement_delta_t_const_v",
                "alias_to_fq_name": "MechLib.Kinematics.Verified.Kinematics.constant_speed_relation",
                "source_path": "MechLib/Compat/PHYSlib.lean",
                "source_line": 1,
            }
        ],
    )
    summary_path.write_text("", encoding="utf-8")
    alignment_path.write_text("{}", encoding="utf-8")

    retriever = MechLibRetriever(
        mechlib_dir=tmp_path,
        summary_corpus_path=summary_path,
        decl_corpus_path=decl_path,
        law_schema_corpus_path=law_path,
        problem_schema_corpus_path=problem_path,
        concept_corpus_path=concept_path,
        alias_map_path=alias_path,
        alignment_index_path=alignment_path,
    )
    pack = retriever.build_domain_context(
        problem_text="A point moves at constant speed v for time t. Find displacement s.",
        problem_ir={
            "unknown_target": {"symbol": "s", "description": "displacement"},
            "known_quantities": [{"symbol": "v"}, {"symbol": "t"}],
            "physical_laws": ["Kinematics"],
            "goal_statement": "compute displacement from speed and time",
        },
        top_k=3,
    )

    assert pack["verified_decl_items_count"] >= 1
    assert pack["verified_decl_items"][0]["proof_eligible"] is True
    assert pack["gap_schema_only"] is False
    assert "Verified Declaration Context" in pack["context_text"]
    assert "Schema Context (metadata only; not proof facts)" in pack["context_text"]


def test_module_b_marks_verified_decl_refs_and_schema_only_gap(tmp_path: Path) -> None:
    prompt = tmp_path / "B_generate_statements.txt"
    prompt.write_text("__TASK_B_GENERATE_STATEMENTS__", encoding="utf-8")
    grounding = GroundingResult(
        sample_id="s1",
        model_id="m",
        problem_ir={"unknown_target": {"symbol": "s"}},
        parse_ok=True,
        raw_response="",
        error=None,
    )
    payload = """
    {
      "candidates": [
        {
          "candidate_id": "c1",
          "lean_header": "import MechLib",
          "theorem_decl": "theorem use_const_speed (s v t : Real) (h : s = v * t) : s + 0 = v * t",
          "fact_sources": ["problem", "mechlib:constant_speed_relation"],
          "library_symbols_used": ["constant_speed_relation"]
        }
      ]
    }
    """
    context = """
gap_schema_only: False
Verified Declaration Context (from decl_corpus_enriched.jsonl; proof-eligible only):
[1] theorem_name=constant_speed_relation fq_name=MechLib.Kinematics.Verified.Kinematics.constant_speed_relation module=MechLib.Kinematics.Verified.Kinematics kind=theorem score=1.0 status=verified trust_level=core callable_by_llm=True proof_eligible=True
"""

    out = ModuleB(StaticClient(payload), prompt).run(grounding, mechlib_context=context)

    assert out[0].grounding_status == "verified_decl_bound"
    assert out[0].gap_schema_only is False
    assert out[0].verified_decl_refs[0]["fq_name"] == "MechLib.Kinematics.Verified.Kinematics.constant_speed_relation"

    gap_context = """
gap_schema_only: True
Schema Context (metadata only; not proof facts):
[1] schema_id=law.kinematics.constant_speed corpus_type=law_schema score=1.0 proof_eligible=False
"""
    gap_out = ModuleB(StaticClient(payload), prompt).run(grounding, mechlib_context=gap_context)
    assert gap_out[0].grounding_status == "gap_schema_only"
    assert gap_out[0].gap_schema_only is True
    assert gap_out[0].schema_refs[0]["schema_id"] == "law.kinematics.constant_speed"
    assert "gap_schema_only:no_verified_decl_binding" in gap_out[0].unsupported_claims


def test_semantic_rank_prefers_verified_decl_bound_candidate_over_schema_only_gap(tmp_path: Path) -> None:
    prompt = tmp_path / "D_semantic_rank.txt"
    prompt.write_text("__TASK_D_SEMANTIC_RANK__", encoding="utf-8")
    llm_payload = """
    {
      "results": [
        {"candidate_id":"c1","back_translation":"constant speed relation","semantic_score":0.9,"semantic_pass":true,"target_relation":"exact","reason":"aligned"},
        {"candidate_id":"c2","back_translation":"constant speed relation","semantic_score":0.9,"semantic_pass":true,"target_relation":"exact","reason":"aligned"}
      ]
    }
    """
    mod = ModuleD(model_client=StaticClient(llm_payload), prompt_path=prompt, pass_threshold=0.7)
    grounding = GroundingResult(
        sample_id="s2",
        model_id="m",
        problem_ir={
            "unknown_target": {"symbol": "s", "description": "displacement"},
            "known_quantities": [{"symbol": "v"}, {"symbol": "t"}],
            "physical_laws": ["Kinematics"],
        },
        parse_ok=True,
        raw_response="",
        error=None,
    )
    candidates = [
        StatementCandidate(
            sample_id="s2",
            candidate_id="c1",
            lean_header="import MechLib",
            theorem_decl="theorem c1 (s v t : Real) (h : s = v * t) : s = v * t",
            library_symbols_used=["constant_speed_relation"],
            verified_decl_refs=[{"theorem_name": "constant_speed_relation"}],
            grounding_status="verified_decl_bound",
        ),
        StatementCandidate(
            sample_id="s2",
            candidate_id="c2",
            lean_header="import MechLib",
            theorem_decl="theorem c2 (s v t : Real) (h : s = v * t) : s = v * t",
            schema_refs=[{"schema_id": "law.kinematics.constant_speed"}],
            grounding_status="gap_schema_only",
            gap_schema_only=True,
        ),
    ]
    compile_rows = [
        CompileCheckResult(
            sample_id="s2",
            candidate_id=c.candidate_id,
            compile_pass=True,
            syntax_ok=True,
            elaboration_ok=True,
            error_type=None,
            stderr_digest="",
            log_path=None,
        )
        for c in candidates
    ]

    rank = mod.run(
        grounding,
        candidates,
        compile_rows,
        problem_text="constant speed displacement",
        mechlib_context="Law-Matched Declarations:\n[1] theorem_name=constant_speed_relation fq_name=MechLib.Kinematics.Verified.Kinematics.constant_speed_relation symbol=constant_speed_relation proof_eligible=True",
    )

    row_c1 = next(row for row in rank.ranking if row["candidate_id"] == "c1")
    row_c2 = next(row for row in rank.ranking if row["candidate_id"] == "c2")
    assert row_c1["library_grounding_score"] > row_c2["library_grounding_score"]
    assert rank.selected_candidate_id == "c1"
