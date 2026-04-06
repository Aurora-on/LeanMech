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


class DetailedSemanticLLM(ModelClient):
    def __init__(self, payload: str) -> None:
        self.model_id = "detailed-semantic-llm"
        self.supports_vision = False
        self._payload = payload

    def generate_text(self, prompt: str, **kwargs) -> ModelResponse:
        _ = (prompt, kwargs)
        return ModelResponse(text=self._payload)

    def generate_multimodal(self, prompt: str, images_b64: list[str], **kwargs) -> ModelResponse:
        _ = (prompt, images_b64, kwargs)
        return ModelResponse(text=self._payload)


def test_semantic_rank_preserves_detailed_mismatch_feedback(tmp_path: Path) -> None:
    prompt = tmp_path / "D_semantic_rank.txt"
    prompt.write_text("__TASK_D_SEMANTIC_RANK__", encoding="utf-8")
    payload = """
    {
      "results": [
        {
          "candidate_id": "c1",
          "back_translation": "solves for displacement instead of acceleration",
          "semantic_score": 0.2,
          "semantic_pass": false,
          "reason": "The theorem answers the wrong target quantity.",
          "failure_summary": "The theorem solves for displacement instead of acceleration.",
          "failure_tags": ["wrong_target", "missing_given"],
          "mismatch_fields": ["unknown_target", "known_quantities"],
          "missing_or_incorrect_translations": ["The original problem asks for acceleration, but the theorem concludes a displacement equation."],
          "suggested_fix_direction": "Keep force and mass as givens and solve for acceleration."
        }
      ]
    }
    """
    mod = ModuleD(model_client=DetailedSemanticLLM(payload), prompt_path=prompt, pass_threshold=0.6)

    grounding = GroundingResult(
        sample_id="s3",
        model_id="m",
        problem_ir={
            "unknown_target": {"symbol": "a", "description": "acceleration"},
            "known_quantities": [{"symbol": "F"}, {"symbol": "m"}],
            "physical_laws": ["NewtonSecondLaw"],
        },
        parse_ok=True,
        raw_response="",
        error=None,
    )
    candidates = [
        StatementCandidate(
            sample_id="s3",
            candidate_id="c1",
            lean_header="import PhysLean",
            theorem_decl="theorem c1 (s F m : Real) : s = F + m",
        )
    ]
    compile_rows = [
        CompileCheckResult(
            sample_id="s3",
            candidate_id="c1",
            compile_pass=True,
            syntax_ok=True,
            elaboration_ok=True,
            error_type=None,
            stderr_digest="",
            log_path=None,
        )
    ]

    rank = mod.run(grounding, candidates, compile_rows, problem_text="Given force and mass, compute acceleration.")
    assert rank.semantic_pass is False
    assert rank.sub_error_type == "wrong_target"
    assert rank.failure_summary == "The theorem solves for displacement instead of acceleration."
    assert "wrong_target" in rank.failure_tags
    assert rank.failure_details["mismatch_fields"] == ["unknown_target", "known_quantities"]
    row = rank.ranking[0]
    assert row["mismatch_fields"] == ["unknown_target", "known_quantities"]
    assert row["missing_or_incorrect_translations"] == [
        "The original problem asks for acceleration, but the theorem concludes a displacement equation."
    ]
    assert row["suggested_fix_direction"] == "Keep force and mass as givens and solve for acceleration."


def test_semantic_rank_accepts_surface_different_but_equivalent_target(tmp_path: Path) -> None:
    prompt = tmp_path / "D_semantic_rank.txt"
    prompt.write_text("__TASK_D_SEMANTIC_RANK__", encoding="utf-8")
    payload = """
    {
      "results": [
        {
          "candidate_id": "c1",
          "back_translation": "The ring satisfies r(t)=(v/omega)(phi(t)-phi(0)).",
          "semantic_score": 0.98,
          "semantic_pass": true,
          "target_relation": "equivalent",
          "reason": "This is the same target up to the arbitrary angular origin.",
          "failure_summary": "",
          "failure_tags": [],
          "mismatch_fields": [],
          "missing_or_incorrect_translations": [],
          "suggested_fix_direction": "No major change needed."
        }
      ]
    }
    """
    mod = ModuleD(model_client=DetailedSemanticLLM(payload), prompt_path=prompt, pass_threshold=0.7)

    grounding = GroundingResult(
        sample_id="s4",
        model_id="m",
        problem_ir={
            "unknown_target": {"symbol": "r(phi)", "description": "trajectory of the ring in polar form"},
            "goal_statement": "prove the trajectory is an Archimedean spiral r = (v / omega) phi",
            "known_quantities": [{"symbol": "v"}, {"symbol": "omega"}],
            "physical_laws": ["Kinematics"],
        },
        parse_ok=True,
        raw_response="",
        error=None,
    )
    candidates = [
        StatementCandidate(
            sample_id="s4",
            candidate_id="c1",
            lean_header="import MechLib",
            theorem_decl=(
                "theorem c1 (r phi : Real -> Real) (v omega : Real) "
                "(h_r : forall t, r t = v * t) "
                "(h_phi : forall t, phi t = phi 0 + omega * t) "
                "(h_omega_ne : omega ≠ 0) : forall t, r t = (v / omega) * (phi t - phi 0)"
            ),
        )
    ]
    compile_rows = [
        CompileCheckResult(
            sample_id="s4",
            candidate_id="c1",
            compile_pass=True,
            syntax_ok=True,
            elaboration_ok=True,
            error_type=None,
            stderr_digest="",
            log_path=None,
        )
    ]

    rank = mod.run(grounding, candidates, compile_rows, problem_text="Prove the trajectory is an Archimedean spiral.")
    row = rank.ranking[0]
    assert rank.semantic_pass is True
    assert rank.selected_candidate_id == "c1"
    assert row["target_relation"] == "equivalent"
    assert row["hard_gate_reasons"] == []


def test_semantic_rank_rejects_special_case_target_relation(tmp_path: Path) -> None:
    prompt = tmp_path / "D_semantic_rank.txt"
    prompt.write_text("__TASK_D_SEMANTIC_RANK__", encoding="utf-8")
    payload = """
    {
      "results": [
        {
          "candidate_id": "c1",
          "back_translation": "This proves the target only after fixing phi(0)=0.",
          "semantic_score": 0.95,
          "semantic_pass": true,
          "target_relation": "special_case",
          "reason": "This is only a special case after a coordinate choice.",
          "failure_summary": "Only proves a special case of the intended target.",
          "failure_tags": ["special_case_only"],
          "mismatch_fields": ["constraints"],
          "missing_or_incorrect_translations": ["The theorem fixes an extra coordinate convention not required by the problem."],
          "suggested_fix_direction": "Generalize the conclusion to include the angle offset."
        }
      ]
    }
    """
    mod = ModuleD(model_client=DetailedSemanticLLM(payload), prompt_path=prompt, pass_threshold=0.7)

    grounding = GroundingResult(
        sample_id="s5",
        model_id="m",
        problem_ir={
            "unknown_target": {"symbol": "r(phi)", "description": "trajectory of the ring in polar form"},
            "goal_statement": "prove the trajectory is an Archimedean spiral r = (v / omega) phi",
            "known_quantities": [{"symbol": "v"}, {"symbol": "omega"}],
            "physical_laws": ["Kinematics"],
        },
        parse_ok=True,
        raw_response="",
        error=None,
    )
    candidates = [
        StatementCandidate(
            sample_id="s5",
            candidate_id="c1",
            lean_header="import MechLib",
            theorem_decl=(
                "theorem c1 (r phi : Real -> Real) (v omega : Real) "
                "(h_r : forall t, r t = v * t) "
                "(h_phi : forall t, phi t = omega * t) "
                "(h_omega_ne : omega ≠ 0) : forall t, r t = (v / omega) * phi t"
            ),
        )
    ]
    compile_rows = [
        CompileCheckResult(
            sample_id="s5",
            candidate_id="c1",
            compile_pass=True,
            syntax_ok=True,
            elaboration_ok=True,
            error_type=None,
            stderr_digest="",
            log_path=None,
        )
    ]

    rank = mod.run(grounding, candidates, compile_rows, problem_text="Prove the trajectory is an Archimedean spiral.")
    row = rank.ranking[0]
    assert rank.semantic_pass is False
    assert row["target_relation"] == "special_case"
    assert "target_mismatch" in row["hard_gate_reasons"]


def test_semantic_rank_does_not_mark_not_tautology_as_trivial_goal(tmp_path: Path) -> None:
    prompt = tmp_path / "D_semantic_rank.txt"
    prompt.write_text("__TASK_D_SEMANTIC_RANK__", encoding="utf-8")
    payload = """
    {
      "results": [
        {
          "candidate_id": "c1",
          "back_translation": "Equivalent target with an angular offset.",
          "semantic_score": 0.95,
          "semantic_pass": true,
          "target_relation": "equivalent",
          "reason": "This is not a tautology and not trivial; it is the same target in equivalent form.",
          "failure_summary": "",
          "failure_tags": [],
          "mismatch_fields": [],
          "missing_or_incorrect_translations": [],
          "suggested_fix_direction": ""
        }
      ]
    }
    """
    mod = ModuleD(model_client=DetailedSemanticLLM(payload), prompt_path=prompt, pass_threshold=0.7)

    grounding = GroundingResult(
        sample_id="s6",
        model_id="m",
        problem_ir={
            "unknown_target": {"symbol": "r(phi)", "description": "trajectory of the ring in polar form"},
            "goal_statement": "prove the trajectory is an Archimedean spiral",
            "known_quantities": [{"symbol": "v"}, {"symbol": "omega"}],
            "physical_laws": ["Kinematics"],
        },
        parse_ok=True,
        raw_response="",
        error=None,
    )
    candidates = [
        StatementCandidate(
            sample_id="s6",
            candidate_id="c1",
            lean_header="import MechLib",
            theorem_decl=(
                "theorem c1 (r phi : Real -> Real) (v omega : Real) "
                "(h_r : forall t, r t = r 0 + v * t) "
                "(h_phi : forall t, phi t = phi 0 + omega * t) "
                "(h_r0 : r 0 = 0) (h_omega_ne : omega ≠ 0) "
                ": forall t, r t = (v / omega) * (phi t - phi 0)"
            ),
        )
    ]
    compile_rows = [
        CompileCheckResult(
            sample_id="s6",
            candidate_id="c1",
            compile_pass=True,
            syntax_ok=True,
            elaboration_ok=True,
            error_type=None,
            stderr_digest="",
            log_path=None,
        )
    ]

    rank = mod.run(grounding, candidates, compile_rows, problem_text="Prove the trajectory is an Archimedean spiral.")
    row = rank.ranking[0]
    assert row["sub_error_type"] is None
    assert rank.semantic_pass is True
