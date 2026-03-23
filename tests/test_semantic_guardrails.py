from __future__ import annotations

from pathlib import Path

from mech_pipeline.model.base import ModelClient
from mech_pipeline.modules.D_semantic_rank import ModuleD
from mech_pipeline.types import CompileCheckResult, GroundingResult, ModelResponse, StatementCandidate


class GuardrailLLM(ModelClient):
    def __init__(self, payload: str) -> None:
        self.model_id = "guardrail-llm"
        self.supports_vision = False
        self._payload = payload

    def generate_text(self, prompt: str, **kwargs) -> ModelResponse:
        _ = (prompt, kwargs)
        return ModelResponse(text=self._payload)

    def generate_multimodal(self, prompt: str, images_b64: list[str], **kwargs) -> ModelResponse:
        _ = (prompt, images_b64, kwargs)
        return ModelResponse(text=self._payload)


def test_semantic_guard_rejects_law_drift_even_if_llm_prefers_it(tmp_path: Path) -> None:
    prompt = tmp_path / "D_semantic_rank.txt"
    prompt.write_text("__TASK_D_SEMANTIC_RANK__", encoding="utf-8")
    llm_payload = """
    {
      "results": [
        {"candidate_id":"c1","back_translation":"newton statement","semantic_score":0.99,"semantic_pass":true,"reason":"looks good"},
        {"candidate_id":"c2","back_translation":"kinematics statement","semantic_score":0.61,"semantic_pass":true,"reason":"acceptable"}
      ]
    }
    """
    mod = ModuleD(model_client=GuardrailLLM(llm_payload), prompt_path=prompt, pass_threshold=0.6)

    grounding = GroundingResult(
        sample_id="s1",
        model_id="m",
        problem_ir={
            "unknown_target": {"symbol": "s", "description": "displacement"},
            "known_quantities": [{"symbol": "v"}, {"symbol": "t"}],
            "physical_laws": ["Kinematics"],
            "units": [{"symbol": "s", "unit": "m"}],
            "assumptions": ["uniform motion"],
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
            theorem_decl="theorem c1_newton (F m a : Real) (h : F = m * a) : a = F / m",
        ),
        StatementCandidate(
            sample_id="s1",
            candidate_id="c2",
            lean_header="import PhysLean",
            theorem_decl="theorem c2_kin (s v t : Real) (h : s = v * t) (ht : t != 0) : v = s / t",
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

    rank = mod.run(grounding, candidates, compile_rows, problem_text="Given velocity and time, compute displacement.")
    assert rank.selected_candidate_id == "c2"
    assert rank.semantic_pass is True
    row_c1 = next(x for x in rank.ranking if x["candidate_id"] == "c1")
    assert row_c1["hard_gate_pass"] is False
    assert "target_mismatch" in row_c1["hard_gate_reasons"]


def test_semantic_guard_rejects_trivial_goal(tmp_path: Path) -> None:
    prompt = tmp_path / "D_semantic_rank.txt"
    prompt.write_text("__TASK_D_SEMANTIC_RANK__", encoding="utf-8")
    llm_payload = """
    {
      "results": [
        {"candidate_id":"c1","back_translation":"trivial equality","semantic_score":0.99,"semantic_pass":true,"reason":"very easy"},
        {"candidate_id":"c2","back_translation":"newton relation","semantic_score":0.65,"semantic_pass":true,"reason":"valid"}
      ]
    }
    """
    mod = ModuleD(model_client=GuardrailLLM(llm_payload), prompt_path=prompt, pass_threshold=0.6)

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
            theorem_decl="theorem c1_trivial (a : Real) : a = a",
        ),
        StatementCandidate(
            sample_id="s2",
            candidate_id="c2",
            lean_header="import PhysLean",
            theorem_decl="theorem c2_newton (F m a : Real) (h : F = m * a) (hm : m != 0) : a = F / m",
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

    rank = mod.run(grounding, candidates, compile_rows, problem_text="Given force and mass, compute acceleration.")
    assert rank.selected_candidate_id == "c2"
    row_c1 = next(x for x in rank.ranking if x["candidate_id"] == "c1")
    assert row_c1["trivial_goal"] is True
    assert row_c1["semantic_pass"] is False
