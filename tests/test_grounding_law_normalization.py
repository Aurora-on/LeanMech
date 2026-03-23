from __future__ import annotations

from pathlib import Path

from mech_pipeline.model.base import ModelClient
from mech_pipeline.modules.A_grounding import ModuleA
from mech_pipeline.types import CanonicalSample, ModelResponse


class StaticAClient(ModelClient):
    def __init__(self, ir_json: str) -> None:
        self.model_id = "static-a"
        self.supports_vision = False
        self._ir_json = ir_json

    def generate_text(self, prompt: str, **kwargs) -> ModelResponse:
        _ = (prompt, kwargs)
        return ModelResponse(text=self._ir_json)

    def generate_multimodal(self, prompt: str, images_b64: list[str], **kwargs) -> ModelResponse:
        _ = (prompt, images_b64, kwargs)
        return ModelResponse(text=self._ir_json)


def test_grounding_normalizes_newton_to_kinematics_when_no_force_signal(tmp_path: Path) -> None:
    prompt = tmp_path / "A_extract_ir.txt"
    prompt.write_text("__TASK_A_EXTRACT_IR__\n{{problem_text}}", encoding="utf-8")
    ir_json = (
        '{"objects":[],"known_quantities":[{"symbol":"m","value":1.0}],"unknown_target":{"symbol":"s","description":"displacement"},'
        '"units":[{"symbol":"s","unit":"m"}],"constraints":[],"relations":["F = m * a"],'
        '"physical_laws":["NewtonSecondLaw"],"assumptions":[],"diagram_information":[],'
        '"goal_statement":"compute displacement","coordinate_system":"x","reference_frame":"ground",'
        '"simplifications":[],"symbol_table":{"m":"mass","s":"displacement"}}'
    )
    module = ModuleA(StaticAClient(ir_json), "static-a", prompt)
    sample = CanonicalSample(
        sample_id="k1",
        source="unit",
        problem_text="A particle moves with constant velocity 10 m/s for 3 s. Find displacement.",
        options=[],
        gold_answer=None,
    )
    out = module.run(sample)
    assert out.parse_ok
    laws = out.problem_ir.get("physical_laws") if out.problem_ir else []
    assert "Kinematics" in laws
    assert "NewtonSecondLaw" not in laws


def test_grounding_keeps_newton_when_force_signal_exists(tmp_path: Path) -> None:
    prompt = tmp_path / "A_extract_ir.txt"
    prompt.write_text("__TASK_A_EXTRACT_IR__\n{{problem_text}}", encoding="utf-8")
    ir_json = (
        '{"objects":[],"known_quantities":[{"symbol":"F","value":10.0},{"symbol":"m","value":2.0}],"unknown_target":{"symbol":"a","description":"acceleration"},'
        '"units":[{"symbol":"a","unit":"m/s^2"}],"constraints":[],"relations":["F = m * a"],'
        '"physical_laws":["NewtonSecondLaw"],"assumptions":[],"diagram_information":[],'
        '"goal_statement":"compute acceleration","coordinate_system":"x","reference_frame":"ground",'
        '"simplifications":[],"symbol_table":{"F":"force","m":"mass","a":"acceleration"}}'
    )
    module = ModuleA(StaticAClient(ir_json), "static-a", prompt)
    sample = CanonicalSample(
        sample_id="n1",
        source="unit",
        problem_text="A force of 10 N acts on a 2 kg block. Find the acceleration.",
        options=[],
        gold_answer=None,
    )
    out = module.run(sample)
    assert out.parse_ok
    laws = out.problem_ir.get("physical_laws") if out.problem_ir else []
    assert "NewtonSecondLaw" in laws
