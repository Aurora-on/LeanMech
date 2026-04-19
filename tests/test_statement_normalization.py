from __future__ import annotations

from pathlib import Path

from mech_pipeline.model.base import ModelClient
from mech_pipeline.modules.B_statement_gen import ModuleB
from mech_pipeline.types import GroundingResult, ModelResponse


class StaticStatementClient(ModelClient):
    def __init__(self, payload: str) -> None:
        self.model_id = "static-b"
        self.supports_vision = False
        self._payload = payload

    def generate_text(self, prompt: str, **kwargs) -> ModelResponse:
        _ = (prompt, kwargs)
        return ModelResponse(text=self._payload)

    def generate_multimodal(self, prompt: str, images_b64: list[str], **kwargs) -> ModelResponse:
        _ = (prompt, images_b64, kwargs)
        return ModelResponse(text=self._payload)


class CapturePromptClient(ModelClient):
    def __init__(self, payload: str) -> None:
        self.model_id = "capture-b"
        self.supports_vision = False
        self._payload = payload
        self.last_prompt = ""

    def generate_text(self, prompt: str, **kwargs) -> ModelResponse:
        _ = kwargs
        self.last_prompt = prompt
        return ModelResponse(text=self._payload)

    def generate_multimodal(self, prompt: str, images_b64: list[str], **kwargs) -> ModelResponse:
        _ = images_b64
        return self.generate_text(prompt, **kwargs)


def _grounding(sample_id: str = "s1") -> GroundingResult:
    return GroundingResult(
        sample_id=sample_id,
        model_id="m",
        problem_ir={"unknown_target": {"symbol": "v_y", "description": "velocity"}},
        parse_ok=True,
        raw_response="",
        error=None,
    )


def test_statement_normalizes_decimal_literals_to_real_terms(tmp_path: Path) -> None:
    prompt = tmp_path / "B_generate_statements.txt"
    prompt.write_text("__TASK_B_GENERATE_STATEMENTS__", encoding="utf-8")
    payload = """
    {
      "candidates": [
        {
          "candidate_id": "c1",
          "lean_header": "import MechLib",
          "theorem_decl": "theorem descending_velocity_value_at_five_meters (v_y : Real) (hDescending : v_y < 0) (hKinematic : v_y ^ 2 = 15.0 ^ 2 + 2 * (-9.8) * (5.0 - 0.0)) : v_y = -Real.sqrt (15.0 ^ 2 + 2 * (-9.8) * (5.0 - 0.0))",
          "assumptions": [],
          "plan": "test"
        },
        {
          "candidate_id": "c2",
          "lean_header": "import MechLib",
          "theorem_decl": "theorem avg_accel (t1 t2 : Real) (hneq : t2 != t1) : ((60 + 0.50 * t2^2) - (60 + 0.50 * t1^2)) / (t2 - t1) = 0.50 * (t1 + t2)",
          "assumptions": [],
          "plan": "test"
        },
        {
          "candidate_id": "c3",
          "lean_header": "import MechLib",
          "theorem_decl": "theorem ok3 (x y : Real) (h : x = y) : y = x",
          "assumptions": [],
          "plan": "test"
        },
        {
          "candidate_id": "c4",
          "lean_header": "import MechLib",
          "theorem_decl": "theorem ok4 (x y : Real) (h : x = y) : y = x",
          "assumptions": [],
          "plan": "test"
        }
      ]
    }
    """

    out = ModuleB(StaticStatementClient(payload), prompt).run(_grounding())
    c1 = next(x for x in out if x.candidate_id == "c1")
    c2 = next(x for x in out if x.candidate_id == "c2")

    assert "15.0" not in c1.theorem_decl
    assert "9.8" not in c1.theorem_decl
    assert "(15 : Real)" in c1.theorem_decl
    assert "((49 : Real) / 5)" in c1.theorem_decl
    assert "0.50" not in c2.theorem_decl
    assert "!=" not in c2.theorem_decl
    assert "≠" in c2.theorem_decl
    assert "((1 : Real) / 2)" in c2.theorem_decl


def test_statement_repairs_quantity_cast_and_hallucinated_mechlib_symbols(tmp_path: Path) -> None:
    prompt = tmp_path / "B_generate_statements.txt"
    prompt.write_text("__TASK_B_GENERATE_STATEMENTS__", encoding="utf-8")
    payload = """
    {
      "candidates": [
        {
          "candidate_id": "c1",
          "lean_header": "import MechLib",
          "theorem_decl": "theorem motorcyclist_velocity_difference_equals_acceleration_times_time (v0 vTarget : Speed) (a : Acceleration) (t : Time) (hvt : vTarget = velocityConstAccel v0 a t) : vTarget - v0 = Quantity.cast (a * t) SI.acceleration_time_eq_speed",
          "assumptions": [],
          "plan": "test"
        },
        {
          "candidate_id": "c2",
          "lean_header": "import MechLib",
          "theorem_decl": "theorem motorcyclist_position_relative_to_signpost_from_displacement (x : Length) (x0 : Length) (dx : Length) (hdisp : dx = displacement x x0) : x = x0 + dx",
          "assumptions": [],
          "plan": "test"
        },
        {
          "candidate_id": "c3",
          "lean_header": "import MechLib",
          "theorem_decl": "theorem ok3 (x y : Real) (h : x = y) : y = x",
          "assumptions": [],
          "plan": "test"
        },
        {
          "candidate_id": "c4",
          "lean_header": "import MechLib",
          "theorem_decl": "theorem ok4 (x y : Real) (h : x = y) : y = x",
          "assumptions": [],
          "plan": "test"
        }
      ]
    }
    """

    out = ModuleB(StaticStatementClient(payload), prompt).run(
        _grounding("s2"),
        mechlib_context="Law-Matched Declarations:\n[1] module=Dynamics kind=theorem symbol=acceleration score=1.0",
    )
    c1 = next(x for x in out if x.candidate_id == "c1")
    c2 = next(x for x in out if x.candidate_id == "c2")

    assert "fallback_goal" not in c1.theorem_decl
    assert "Quantity.cast" not in c1.theorem_decl
    assert "velocityConstAccel" not in c1.theorem_decl
    assert "(v0 vTarget : Real)" in c1.theorem_decl
    assert "(a : Real)" in c1.theorem_decl
    assert "(t : Real)" in c1.theorem_decl
    assert "vTarget = (v0 + a * t)" in c1.theorem_decl
    assert ": vTarget - v0 = (a * t)" in c1.theorem_decl

    assert "fallback_goal" not in c2.theorem_decl
    assert "(x : Real)" in c2.theorem_decl
    assert "(x0 : Real)" in c2.theorem_decl
    assert "(dx : Real)" in c2.theorem_decl
    assert "dx = (x - x0)" in c2.theorem_decl


def test_statement_preserves_unknown_mechlib_symbol_for_compile_stage_feedback(tmp_path: Path) -> None:
    prompt = tmp_path / "B_generate_statements.txt"
    prompt.write_text("__TASK_B_GENERATE_STATEMENTS__", encoding="utf-8")
    payload = """
    {
      "candidates": [
        {
          "candidate_id": "c1",
          "lean_header": "import MechLib",
          "theorem_decl": "theorem impossible_api_use (x y : Real) (h : y = mysteryConstAccel x) : y = x",
          "assumptions": [],
          "plan": "test"
        },
        {
          "candidate_id": "c2",
          "lean_header": "import MechLib",
          "theorem_decl": "theorem ok2 (F m a : Real) (hm : m ≠ 0) (h : F = m * a) : a = F / m",
          "assumptions": [],
          "plan": "test"
        },
        {
          "candidate_id": "c3",
          "lean_header": "import MechLib",
          "theorem_decl": "theorem ok3 (F m a : Real) (hm : m ≠ 0) (h : F = m * a) : a = F / m",
          "assumptions": [],
          "plan": "test"
        },
        {
          "candidate_id": "c4",
          "lean_header": "import MechLib",
          "theorem_decl": "theorem ok4 (F m a : Real) (hm : m ≠ 0) (h : F = m * a) : a = F / m",
          "assumptions": [],
          "plan": "test"
        }
      ]
    }
    """

    out = ModuleB(StaticStatementClient(payload), prompt).run(_grounding("s3"))
    c1 = next(x for x in out if x.candidate_id == "c1")

    assert len(out) == 4
    assert "fallback_goal" not in c1.theorem_decl
    assert "mysteryConstAccel" in c1.theorem_decl
    assert "impossible_api_use" in c1.theorem_decl


def test_statement_rejects_assumption_replay_goals(tmp_path: Path) -> None:
    prompt = tmp_path / "B_generate_statements.txt"
    prompt.write_text("__TASK_B_GENERATE_STATEMENTS__", encoding="utf-8")
    payload = """
    {
      "candidates": [
        {
          "candidate_id": "c1",
          "lean_header": "import MechLib",
          "theorem_decl": "theorem bad1 (x y : Real) (h : x = y) : y = x",
          "assumptions": [],
          "plan": "test"
        },
        {
          "candidate_id": "c2",
          "lean_header": "import MechLib",
          "theorem_decl": "theorem ok2 (F m a : Real) (hm : m ≠ 0) (h : F = m * a) : a = F / m",
          "assumptions": [],
          "plan": "test"
        },
        {
          "candidate_id": "c3",
          "lean_header": "import MechLib",
          "theorem_decl": "theorem ok3 (F m a : Real) (hm : m ≠ 0) (h : F = m * a) : a = F / m",
          "assumptions": [],
          "plan": "test"
        },
        {
          "candidate_id": "c4",
          "lean_header": "import MechLib",
          "theorem_decl": "theorem ok4 (F m a : Real) (hm : m ≠ 0) (h : F = m * a) : a = F / m",
          "assumptions": [],
          "plan": "test"
        }
      ]
    }
    """

    out = ModuleB(StaticStatementClient(payload), prompt).run(_grounding("s4"))

    assert len(out) == 3
    assert all(c.candidate_id != "c1" for c in out)
    assert all("fallback_goal" not in c.theorem_decl for c in out)


def test_statement_normalizes_greek_identifiers_instead_of_dropping_candidate(tmp_path: Path) -> None:
    prompt = tmp_path / "B_generate_statements.txt"
    prompt.write_text("__TASK_B_GENERATE_STATEMENTS__", encoding="utf-8")
    payload = """
    {
      "candidates": [
        {
          "candidate_id": "c1",
          "lean_header": "import MechLib",
          "theorem_decl": "theorem archimedean_spiral_from_time_param (r phi : Real -> Real) (v omega : Real) (h_r : forall t, r t = v * t) (h_phi : forall t, phi t = omega * t) (hω : omega ≠ 0) : forall t, r t = (v / omega) * phi t",
          "assumptions": [],
          "plan": "test"
        }
      ]
    }
    """

    out = ModuleB(StaticStatementClient(payload), prompt).run(_grounding("s5"))

    assert len(out) == 1
    assert "fallback_goal" not in out[0].theorem_decl
    assert "homega" in out[0].theorem_decl


def test_statement_does_not_invent_fallback_candidates_when_model_returns_too_few(tmp_path: Path) -> None:
    prompt = tmp_path / "B_generate_statements.txt"
    prompt.write_text("__TASK_B_GENERATE_STATEMENTS__", encoding="utf-8")
    payload = """
    {
      "candidates": [
        {
          "candidate_id": "c1",
          "lean_header": "import MechLib",
          "theorem_decl": "theorem usable_candidate (F m a : Real) (hm : m ≠ 0) (h : F = m * a) : a = F / m",
          "assumptions": [],
          "plan": "test"
        }
      ]
    }
    """

    out = ModuleB(StaticStatementClient(payload), prompt).run(_grounding("s6"))

    assert len(out) == 1
    assert out[0].candidate_id == "c1"
    assert "fallback_goal" not in out[0].theorem_decl


def test_statement_revision_prompt_includes_previous_candidates_and_feedback(tmp_path: Path) -> None:
    generate_prompt = tmp_path / "B_generate_statements.txt"
    revise_prompt = tmp_path / "B_revise_statements.txt"
    generate_prompt.write_text("GEN {{problem_ir_json}}", encoding="utf-8")
    revise_prompt.write_text(
        "REVISION {{previous_candidates_json}} {{revision_feedback}} {{mechlib_context}}",
        encoding="utf-8",
    )
    payload = """
    {
      "candidates": [
        {"candidate_id":"c1","lean_header":"import MechLib","theorem_decl":"theorem ok1 (F m a : Real) (hm : m ≠ 0) (h : F = m * a) : a = F / m","assumptions":[],"plan":"test"},
        {"candidate_id":"c2","lean_header":"import MechLib","theorem_decl":"theorem ok2 (F m a : Real) (hm : m ≠ 0) (h : F = m * a) : a = F / m","assumptions":[],"plan":"test"},
        {"candidate_id":"c3","lean_header":"import MechLib","theorem_decl":"theorem ok3 (F m a : Real) (hm : m ≠ 0) (h : F = m * a) : a = F / m","assumptions":[],"plan":"test"},
        {"candidate_id":"c4","lean_header":"import MechLib","theorem_decl":"theorem ok4 (F m a : Real) (hm : m ≠ 0) (h : F = m * a) : a = F / m","assumptions":[],"plan":"test"}
      ]
    }
    """
    client = CapturePromptClient(payload)
    previous = ModuleB(StaticStatementClient(payload), generate_prompt).run(_grounding("s4"))

    ModuleB(client, generate_prompt, revise_prompt_path=revise_prompt).run(
        _grounding("s4"),
        mechlib_context="context-text",
        revision_feedback='{"retry_reason":"semantic_fail","candidates":[{"candidate_id":"c1","error_type":"unknown_constant"}]}',
        round_index=1,
        previous_candidates=previous,
    )

    assert "REVISION" in client.last_prompt
    assert "semantic_fail" in client.last_prompt
    assert "unknown_constant" in client.last_prompt
    assert 'candidate_id": "c1"' in client.last_prompt
    assert "context-text" in client.last_prompt


def test_statement_preserves_grounding_metadata_and_marks_unsupported_library_refs(tmp_path: Path) -> None:
    prompt = tmp_path / "B_generate_statements.txt"
    prompt.write_text("__TASK_B_GENERATE_STATEMENTS__", encoding="utf-8")
    payload = """
    {
      "candidates": [
        {
          "candidate_id": "c1",
          "lean_header": "import MechLib",
          "theorem_decl": "theorem usable_candidate (F m a : Real) (hm : m 鈮?0) (h : F = m * a) : a = F / m",
          "assumptions": [],
          "plan": "test",
          "supporting_facts": ["Newton second law"],
          "fact_sources": ["problem", "mechlib:UnknownTheorem"],
          "library_symbols_used": ["UnknownTheorem"],
          "grounding_explanation": "Uses an unsupported theorem name."
        }
      ]
    }
    """

    out = ModuleB(StaticStatementClient(payload), prompt).run(
        _grounding("s7"),
        mechlib_context="Law-Matched Declarations:\n[1] theorem_name=NewtonSecondLaw symbol=NewtonSecondLaw score=1.0",
    )

    assert len(out) == 1
    assert out[0].supporting_facts == ["Newton second law"]
    assert out[0].fact_sources == ["problem", "mechlib:UnknownTheorem"]
    assert out[0].library_symbols_used == ["UnknownTheorem"]
    assert "unsupported_fact_source:UnknownTheorem" in out[0].unsupported_claims
    assert "unsupported_library_symbol:UnknownTheorem" in out[0].unsupported_claims
