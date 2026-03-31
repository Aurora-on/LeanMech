from __future__ import annotations

from pathlib import Path

from mech_pipeline.model.base import ModelClient
from mech_pipeline.model.mock import MockModelClient
from mech_pipeline.modules.D_semantic_rank import ModuleD
from mech_pipeline.types import CompileCheckResult, GroundingResult, ModelResponse, StatementCandidate


def test_semantic_rank_selects_best(tmp_path: Path) -> None:
    prompt = tmp_path / "D_semantic_rank.txt"
    prompt.write_text("__TASK_D_SEMANTIC_RANK__", encoding="utf-8")
    mod = ModuleD(model_client=MockModelClient("mock", False), prompt_path=prompt, pass_threshold=0.2)

    grounding = GroundingResult(
        sample_id="s1",
        model_id="m",
        problem_ir={
            "unknown_target": {"symbol": "a", "description": "acceleration"},
            "known_quantities": [{"symbol": "m"}, {"symbol": "F"}],
            "physical_laws": ["NewtonSecondLaw"],
            "units": [{"symbol": "a", "unit": "m/s^2"}],
            "assumptions": ["inertial frame"],
        },
        parse_ok=True,
        raw_response="",
        error=None,
    )
    candidates = [
        StatementCandidate(
            sample_id="s1",
            candidate_id="c1",
            lean_header="import PhysLean",
            theorem_decl="theorem t1 : True",
        ),
        StatementCandidate(
            sample_id="s1",
            candidate_id="c2",
            lean_header="import PhysLean",
            theorem_decl="theorem t2 : a = F / m",
        ),
    ]
    compile_rows = [
        CompileCheckResult(
            sample_id="s1",
            candidate_id="c1",
            compile_pass=True,
            syntax_ok=True,
            elaboration_ok=True,
            error_type=None,
            stderr_digest="",
            log_path=None,
        ),
        CompileCheckResult(
            sample_id="s1",
            candidate_id="c2",
            compile_pass=True,
            syntax_ok=True,
            elaboration_ok=True,
            error_type=None,
            stderr_digest="",
            log_path=None,
        ),
    ]
    rank = mod.run(grounding, candidates, compile_rows, problem_text="Given force and mass, find acceleration.")
    assert rank.selected_candidate_id == "c2"
    assert len(rank.ranking) == 2
    assert rank.ranking[0]["back_translation_text"] != ""
    assert rank.ranking[0]["semantic_source"] == "llm_plus_rule"


class EqualSemanticLLM(ModelClient):
    def __init__(self) -> None:
        self.model_id = "equal-semantic-llm"
        self.supports_vision = False

    def generate_text(self, prompt: str, **kwargs) -> ModelResponse:
        _ = (prompt, kwargs)
        return ModelResponse(
            text=(
                '{"results":['
                '{"candidate_id":"c1","back_translation":"sqrt form","semantic_score":0.9,"semantic_pass":true,"reason":"aligned"},'
                '{"candidate_id":"c2","back_translation":"linear form","semantic_score":0.9,"semantic_pass":true,"reason":"aligned"}'
                "]}"
            )
        )

    def generate_multimodal(self, prompt: str, images_b64: list[str], **kwargs) -> ModelResponse:
        _ = (prompt, images_b64, kwargs)
        return self.generate_text(prompt, **kwargs)


def test_semantic_rank_uses_proofability_bias(tmp_path: Path) -> None:
    prompt = tmp_path / "D_semantic_rank.txt"
    prompt.write_text("__TASK_D_SEMANTIC_RANK__", encoding="utf-8")
    mod = ModuleD(model_client=EqualSemanticLLM(), prompt_path=prompt, pass_threshold=0.2)

    grounding = GroundingResult(
        sample_id="s2",
        model_id="m",
        problem_ir={
            "unknown_target": {"symbol": "a", "description": "acceleration"},
            "known_quantities": [{"symbol": "F"}, {"symbol": "m"}],
            "physical_laws": ["NewtonSecondLaw"],
            "units": [{"symbol": "a", "unit": "m/s^2"}],
            "assumptions": ["inertial frame"],
        },
        parse_ok=True,
        raw_response="",
        error=None,
    )
    candidates = [
        StatementCandidate(
            sample_id="s2",
            candidate_id="c1",
            lean_header="import PhysLean",
            theorem_decl="theorem t1 (a F m : Real) (hm : m ≠ 0) : a = Real.sqrt ((F / m)^2)",
        ),
        StatementCandidate(
            sample_id="s2",
            candidate_id="c2",
            lean_header="import PhysLean",
            theorem_decl="theorem t2 (a F m : Real) (hm : m ≠ 0) : a = F / m",
        ),
    ]
    compile_rows = [
        CompileCheckResult(
            sample_id="s2",
            candidate_id="c1",
            compile_pass=True,
            syntax_ok=True,
            elaboration_ok=True,
            error_type=None,
            stderr_digest="",
            log_path=None,
        ),
        CompileCheckResult(
            sample_id="s2",
            candidate_id="c2",
            compile_pass=True,
            syntax_ok=True,
            elaboration_ok=True,
            error_type=None,
            stderr_digest="",
            log_path=None,
        ),
    ]

    rank = mod.run(grounding, candidates, compile_rows, problem_text="Given force and mass, find acceleration.")
    row_c1 = next(x for x in rank.ranking if x["candidate_id"] == "c1")
    row_c2 = next(x for x in rank.ranking if x["candidate_id"] == "c2")

    assert row_c1["proofability_bias"] < row_c2["proofability_bias"]
    assert rank.selected_candidate_id == "c2"
