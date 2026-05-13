from __future__ import annotations

import json
from pathlib import Path

from mech_pipeline.cli import main
from mech_pipeline.knowledge.mechlib_structured import StructuredMechLibContext
from mech_pipeline.model.base import ModelClient
from mech_pipeline.modules.A2_model_ir import ModuleA2ModelIR
from mech_pipeline.types import ModelResponse


class StaticModelIRClient(ModelClient):
    def __init__(self, payload: str) -> None:
        self.model_id = "static-model-ir"
        self.supports_vision = False
        self.payload = payload

    def generate_text(self, prompt: str, **kwargs) -> ModelResponse:
        _ = (prompt, kwargs)
        return ModelResponse(text=self.payload)

    def generate_multimodal(self, prompt: str, images_b64: list[str], **kwargs) -> ModelResponse:
        _ = (prompt, images_b64, kwargs)
        return ModelResponse(text=self.payload)


def _prompt(tmp_path: Path) -> Path:
    path = tmp_path / "A2_model_ir.txt"
    path.write_text("__TASK_A2_BUILD_MODEL_IR__", encoding="utf-8")
    return path


def _valid_payload() -> str:
    return json.dumps(
        {
            "objects": [{"name": "particle", "type": "mass_point"}],
            "variables": {"s": "displacement", "v": "speed", "t": "time"},
            "quantity_annotations": [
                {
                    "symbol": "s",
                    "semantic_role": "displacement",
                    "unit_or_dimension": "m",
                    "lean_type": "Length",
                    "confidence": 0.95,
                    "evidence_text": "displacement s",
                    "reasoning_note": "displacement is length",
                },
                {
                    "symbol": "v",
                    "semantic_role": "speed",
                    "unit_or_dimension": "m/s",
                    "lean_type": "Speed",
                    "confidence": 0.95,
                    "evidence_text": "speed v",
                    "reasoning_note": "m/s identifies speed",
                },
                {
                    "symbol": "t",
                    "semantic_role": "time",
                    "unit_or_dimension": "s",
                    "lean_type": "Time",
                    "confidence": 0.95,
                    "evidence_text": "time t",
                    "reasoning_note": "seconds identify time",
                },
            ],
            "givens": [
                {
                    "name": "h_uniform",
                    "lean": "uniform motion",
                    "role": "given_fact",
                    "source_type": "problem_ir",
                    "source_id": "assumptions[0]",
                    "allowed_in_hypotheses": True,
                }
            ],
            "coordinate_system": {"axis": "x"},
            "reference_frame": "ground",
            "local_definitions": [],
            "model_instances": [
                {
                    "instance_id": "mi1",
                    "kind": "constant_speed_kinematics",
                    "natural_language": "Use constant speed displacement relation.",
                    "entities": ["particle"],
                    "variables": {"s": "displacement", "v": "speed", "t": "time"},
                    "parameters": {},
                    "planning_schema_hint": "law.kinematics.constant_speed",
                    "expected_claim": "s = v * t",
                    "provenance": {"source_type": "problem_ir"},
                    "confidence": 0.91,
                }
            ],
            "target": {"symbol": "s", "description": "displacement"},
            "forbidden_as_assumption": ["target displacement s", "s = v * t as solved final relation"],
        },
        ensure_ascii=False,
    )


def test_model_ir_builder_parses_controlled_json_and_plans_schema(tmp_path: Path) -> None:
    context = StructuredMechLibContext(
        modeling_context={
            "matched_topics": ["Kinematics"],
            "concepts": [],
            "law_schemas": [
                {
                    "schema_id": "law.kinematics.constant_speed",
                    "corpus_type": "law_schema",
                    "topic": "constant speed displacement",
                    "statement_text": "Displacement equals speed times time.",
                    "proof_fact_allowed": False,
                }
            ],
            "problem_schemas": [],
            "aliases": [],
        },
        proof_context={"verified_decls": [], "required_imports": [], "proof_hints": [], "proof_style_examples": []},
    )
    module = ModuleA2ModelIR(StaticModelIRClient(_valid_payload()), _prompt(tmp_path))

    model_ir = module.run(
        sample_id="s1",
        problem_text="A particle moves at speed v for time t. Find displacement s.",
        problem_ir={"unknown_target": {"symbol": "s", "description": "displacement"}},
        structured_mechlib_context=context,
    )

    assert model_ir.parse_ok is True
    assert model_ir.model_instances
    assert [row.lean_type for row in model_ir.quantity_annotations] == ["Length", "Speed", "Time"]
    assert model_ir.model_instances[0].planning_schema_id == "law.kinematics.constant_speed"
    assert model_ir.canonical_target is not None
    assert model_ir.canonical_target.lean_formula == "s = v * t"
    assert model_ir.canonical_target.parse_ok is True
    assert model_ir.forbidden_as_assumption
    assert "target displacement s" in model_ir.forbidden_as_assumption
    serialized = json.dumps(model_ir.to_dict())
    assert "theorem " not in serialized.lower()
    assert ":= by" not in serialized.lower()


def test_model_ir_builder_preserves_secondary_canonical_target_formulas(tmp_path: Path) -> None:
    payload = json.loads(_valid_payload())
    payload["canonical_target"] = {
        "target_id": "target_1",
        "target_kind": "component_relation",
        "target_variables": ["x", "t_star"],
        "lean_formula": "forall t, x t = v * t",
        "secondary_formulas": ["t_star = L / v"],
        "requires_closed_form": False,
        "source_text": "Find the motion and stopping time.",
        "confidence": 0.9,
        "parse_ok": True,
        "error": None,
    }
    payload["forbidden_as_assumption"] = ["target motion", "forall t, x t = v * t", "t_star = L / v"]
    module = ModuleA2ModelIR(StaticModelIRClient(json.dumps(payload)), _prompt(tmp_path))

    model_ir = module.run(
        sample_id="multi-target",
        problem_text="Find x(t) and t_star.",
        problem_ir={"unknown_target": {"symbol": "x", "description": "motion and time"}},
        structured_mechlib_context=None,
    )

    assert model_ir.parse_ok is True
    assert model_ir.canonical_target is not None
    assert model_ir.canonical_target.lean_formula == "forall t, x t = v * t"
    assert model_ir.canonical_target.secondary_formulas == ["t_star = L / v"]


def test_model_ir_builder_preserves_function_formula_ir(tmp_path: Path) -> None:
    payload = json.loads(_valid_payload())
    payload["quantity_annotations"] = [
        {
            "symbol": "x",
            "semantic_role": "position over time",
            "unit_or_dimension": "m",
            "lean_type": "Time -> Length",
            "confidence": 0.95,
        },
        {
            "symbol": "v",
            "semantic_role": "speed",
            "unit_or_dimension": "m/s",
            "lean_type": "Speed",
            "confidence": 0.95,
        },
    ]
    payload["canonical_target"] = {
        "target_id": "target_1",
        "target_kind": "relation",
        "target_variables": ["x"],
        "lean_formula": "forall t, x t = v * t",
        "secondary_formulas": [],
        "function_formula_ir": [
            {
                "formula_id": "motion_relation",
                "formula_kind": "pointwise_relation",
                "bound_variables": [{"name": "t", "lean_type": "Time"}],
                "domain_conditions": [],
                "lhs": "x t",
                "relation": "=",
                "rhs": "v * t",
                "lean_formula": "",
                "source_text": "find x(t)",
                "parse_ok": True,
            }
        ],
        "requires_closed_form": False,
        "source_text": "Find x(t).",
        "confidence": 0.9,
        "parse_ok": True,
        "error": None,
    }
    payload["forbidden_as_assumption"] = ["target x(t)", "forall t, x t = v * t"]
    module = ModuleA2ModelIR(StaticModelIRClient(json.dumps(payload)), _prompt(tmp_path))

    model_ir = module.run(
        sample_id="function-ir",
        problem_text="Find x(t).",
        problem_ir={"unknown_target": {"symbol": "x", "description": "position function"}},
        structured_mechlib_context=None,
    )

    assert model_ir.parse_ok is True
    assert model_ir.canonical_target is not None
    assert model_ir.canonical_target.function_formula_ir
    row = model_ir.canonical_target.function_formula_ir[0]
    assert row.formula_kind == "pointwise_relation"
    assert row.bound_variables == [{"name": "t", "lean_type": "Time"}]
    assert row.lean_formula == "x t = v * t"


def test_model_ir_builder_lifts_target_spec_secondary_goal(tmp_path: Path) -> None:
    payload = json.loads(_valid_payload())
    payload["canonical_target"] = {
        "target_id": "target_1",
        "target_kind": "relation",
        "target_variables": ["x", "t_star"],
        "lean_formula": "forall t, x t = v * t",
        "secondary_formulas": [],
        "requires_closed_form": False,
        "source_text": "Find the motion and stopping time.",
        "confidence": 0.9,
        "parse_ok": True,
        "error": None,
    }
    payload["target_spec"] = {
        "primary_goal": "forall t, x t = v * t",
        "secondary_goal": "t_star = L / v",
    }
    payload["forbidden_as_assumption"] = ["target motion", "forall t, x t = v * t", "t_star = L / v"]
    module = ModuleA2ModelIR(StaticModelIRClient(json.dumps(payload)), _prompt(tmp_path))

    model_ir = module.run(
        sample_id="multi-target-spec",
        problem_text="Find x(t) and t_star.",
        problem_ir={"unknown_target": {"symbol": "x", "description": "motion and time"}},
        structured_mechlib_context=None,
    )

    assert model_ir.canonical_target is not None
    assert model_ir.canonical_target.secondary_formulas == ["t_star = L / v"]


def test_model_ir_builder_marks_tautological_canonical_target_invalid(tmp_path: Path) -> None:
    payload = json.loads(_valid_payload())
    payload["quantity_annotations"] = [
        {
            "symbol": "v_x",
            "semantic_role": "velocity over time",
            "unit_or_dimension": "m/s",
            "lean_type": "Time -> Speed",
            "confidence": 0.95,
        }
    ]
    payload["canonical_target"] = {
        "target_id": "target_1",
        "target_kind": "relation",
        "target_variables": ["v_x"],
        "lean_formula": "forall t, v_x t = v_x t",
        "secondary_formulas": [],
        "requires_closed_form": False,
        "source_text": "velocity relation",
        "confidence": 0.9,
        "parse_ok": True,
        "error": None,
    }
    payload["forbidden_as_assumption"] = ["target velocity relation", "forall t, v_x t = v_x t"]
    module = ModuleA2ModelIR(StaticModelIRClient(json.dumps(payload)), _prompt(tmp_path))

    model_ir = module.run(
        sample_id="tautology-target",
        problem_text="Find the velocity relation.",
        problem_ir={"unknown_target": {"symbol": "v_x", "description": "velocity relation"}},
        structured_mechlib_context=None,
    )

    assert model_ir.parse_ok is True
    assert model_ir.canonical_target is not None
    assert model_ir.canonical_target.parse_ok is False
    assert model_ir.canonical_target.error == "tautological_canonical_target"


def test_model_ir_builder_accepts_structured_forbidden_assumptions(tmp_path: Path) -> None:
    payload = json.loads(_valid_payload())
    payload["forbidden_as_assumption"] = [
        {
            "name": "target_displacement",
            "description": "target displacement s",
            "notes": "final target must be proved, not assumed",
        },
        {
            "name": "derived_relation",
            "claim": "s = v * t",
            "notes": "law application result must stay out of hypotheses",
        },
    ]
    module = ModuleA2ModelIR(StaticModelIRClient(json.dumps(payload)), _prompt(tmp_path))

    model_ir = module.run(
        sample_id="s1",
        problem_text="A particle moves at speed v for time t. Find displacement s.",
        problem_ir={"unknown_target": {"symbol": "s", "description": "displacement"}},
        structured_mechlib_context=None,
    )

    assert model_ir.parse_ok is True
    assert any("target displacement s" in item for item in model_ir.forbidden_as_assumption)
    assert any("s = v * t" in item for item in model_ir.forbidden_as_assumption)


def test_model_ir_builder_accepts_target_symbol_in_structured_forbidden_item(tmp_path: Path) -> None:
    payload = json.loads(_valid_payload())
    payload["target"] = {
        "symbol": "v_m_per_s",
        "description": "speed expressed in meters per second",
        "goal": "Convert the given speed into m/s.",
    }
    payload["forbidden_as_assumption"] = [
        {
            "name": "target_speed_in_m_per_s",
            "lean": "v_m_per_s",
            "reason": "The target quantity itself must not be assumed.",
        }
    ]
    module = ModuleA2ModelIR(StaticModelIRClient(json.dumps(payload)), _prompt(tmp_path))

    model_ir = module.run(
        sample_id="s1",
        problem_text="Convert speed to meters per second.",
        problem_ir={"unknown_target": {"symbol": "v", "description": "speed expressed in meters per second"}},
        structured_mechlib_context=None,
    )

    assert model_ir.parse_ok is True
    assert any("v_m_per_s" in item for item in model_ir.forbidden_as_assumption)


def test_model_ir_builder_rejects_theorem_or_proof_artifacts(tmp_path: Path) -> None:
    payload = json.loads(_valid_payload())
    payload["model_instances"][0]["expected_claim"] = "theorem bad : True := by trivial"
    module = ModuleA2ModelIR(StaticModelIRClient(json.dumps(payload)), _prompt(tmp_path))

    model_ir = module.run(sample_id="s1", problem_text="problem", problem_ir={}, structured_mechlib_context=None)

    assert model_ir.parse_ok is False
    assert model_ir.error == "model_ir_contains_lean_theorem_or_proof"
    assert model_ir.model_instances == []


def test_model_ir_builder_does_not_synthesize_on_parse_failure(tmp_path: Path) -> None:
    module = ModuleA2ModelIR(StaticModelIRClient("not json"), _prompt(tmp_path))

    model_ir = module.run(sample_id="s1", problem_text="problem", problem_ir={}, structured_mechlib_context=None)

    assert model_ir.parse_ok is False
    assert model_ir.error and model_ir.error.startswith("model_ir_parse_failed")
    assert model_ir.model_instances == []
    assert model_ir.givens == []


def test_minimal_skeleton_cli_writes_model_ir_jsonl(tmp_path: Path) -> None:
    archive_root = tmp_path / "archive"
    (archive_root / "output_description_part1").mkdir(parents=True)
    (archive_root / "output_description_part1" / "1-1.md").write_text(
        "A particle moves at constant speed v for time t. Find displacement s.",
        encoding="utf-8",
    )
    output_latest = tmp_path / "latest"
    config_path = tmp_path / "minimal.yaml"
    config_path.write_text(
        f"""
dataset:
  source: local_archive
  limit: 1
  local_archive:
    root: "{archive_root.as_posix()}"
    mode: text_only
model:
  provider: mock
  model_id: mock-minimal
knowledge:
  enabled: false
lean:
  enabled: false
  preflight_enabled: false
statement:
  generation_mode: minimal_skeleton
  feedback_loop_enabled: false
output:
  output_dir: "{output_latest.as_posix()}"
  runs_dir: "{(tmp_path / 'runs').as_posix()}"
  tag: "minimal-skeleton-smoke"
""",
        encoding="utf-8",
    )

    code = main(["run", "--config", str(config_path)])

    assert code == 0
    rows = [
        json.loads(line)
        for line in (output_latest / "model_ir.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(rows) == 1
    assert rows[0]["parse_ok"] is True
    assert rows[0]["model_instances"]


def test_model_ir_builder_normalizes_angle_to_physangle(tmp_path: Path) -> None:
    payload = json.loads(_valid_payload())
    payload["variables"] = {"theta": "angle"}
    payload["quantity_annotations"] = [
        {
            "symbol": "theta",
            "semantic_role": "pendulum angle",
            "unit_or_dimension": "rad",
            "lean_type": "Angle",
            "confidence": 0.91,
            "evidence_text": "theta is an angular displacement",
            "reasoning_note": "MechLib.SI uses PhysAngle for physical angles",
        }
    ]
    payload["model_instances"][0]["variables"] = {"theta": "angle"}
    module = ModuleA2ModelIR(StaticModelIRClient(json.dumps(payload)), _prompt(tmp_path))

    model_ir = module.run(
        sample_id="angle",
        problem_text="A pendulum has angular displacement theta. Find theta.",
        problem_ir={"unknown_target": {"symbol": "theta", "description": "angular displacement"}},
        structured_mechlib_context=None,
    )

    assert model_ir.parse_ok is True
    assert model_ir.quantity_annotations[0].lean_type == "PhysAngle"
    assert model_ir.quantity_annotations[0].supported is True


def test_model_ir_builder_marks_volume_as_unsupported_si_type(tmp_path: Path) -> None:
    payload = json.loads(_valid_payload())
    payload["variables"] = {"V": "volume"}
    payload["quantity_annotations"] = [
        {
            "symbol": "V",
            "semantic_role": "volume",
            "unit_or_dimension": "m^3",
            "lean_type": "Volume",
            "confidence": 0.93,
            "evidence_text": "V is described as volume",
            "reasoning_note": "MechLib.SI currently has no Volume abbrev",
        }
    ]
    payload["model_instances"][0]["variables"] = {"V": "volume"}
    module = ModuleA2ModelIR(StaticModelIRClient(json.dumps(payload)), _prompt(tmp_path))

    model_ir = module.run(
        sample_id="volume",
        problem_text="A tank has volume V. Find V.",
        problem_ir={"unknown_target": {"symbol": "V", "description": "volume"}},
        structured_mechlib_context=None,
    )

    assert model_ir.parse_ok is True
    assert model_ir.quantity_annotations[0].lean_type == "Volume"
    assert model_ir.quantity_annotations[0].supported is False
    assert model_ir.quantity_annotations[0].status == "unsupported_si_type"


def test_same_symbol_can_have_different_llm_quantity_types(tmp_path: Path) -> None:
    force_payload = json.loads(_valid_payload())
    force_payload["variables"] = {"T": "tension"}
    force_payload["quantity_annotations"] = [
        {"symbol": "T", "semantic_role": "tension force", "lean_type": "Force", "confidence": 0.95}
    ]
    force_payload["model_instances"][0]["variables"] = {"T": "tension"}
    time_payload = json.loads(_valid_payload())
    time_payload["variables"] = {"T": "period"}
    time_payload["quantity_annotations"] = [
        {"symbol": "T", "semantic_role": "oscillation period", "lean_type": "Time", "confidence": 0.95}
    ]
    time_payload["model_instances"][0]["variables"] = {"T": "period"}

    force_ir = ModuleA2ModelIR(StaticModelIRClient(json.dumps(force_payload)), _prompt(tmp_path)).run(
        sample_id="force",
        problem_text="The tension T acts on a string.",
        problem_ir={"unknown_target": {"symbol": "T", "description": "tension force"}},
        structured_mechlib_context=None,
    )
    time_ir = ModuleA2ModelIR(StaticModelIRClient(json.dumps(time_payload)), _prompt(tmp_path)).run(
        sample_id="time",
        problem_text="The period T is measured in seconds.",
        problem_ir={"unknown_target": {"symbol": "T", "description": "period"}},
        structured_mechlib_context=None,
    )

    assert force_ir.quantity_annotations[0].lean_type == "Force"
    assert time_ir.quantity_annotations[0].lean_type == "Time"


def test_model_ir_builder_accepts_function_quantity_and_canonical_relation(tmp_path: Path) -> None:
    payload = json.loads(_valid_payload())
    payload["variables"] = {"x": "position function", "t": "time"}
    payload["quantity_annotations"] = [
        {
            "symbol": "x",
            "semantic_role": "position as a function of time",
            "unit_or_dimension": "m over s",
            "lean_type": "Time -> Length",
            "confidence": 0.91,
            "evidence_text": "x(t) is the position",
            "reasoning_note": "time-dependent position",
        },
        {"symbol": "t", "semantic_role": "time", "lean_type": "Time", "confidence": 0.95},
    ]
    payload["canonical_target"] = {
        "target_id": "target_1",
        "target_kind": "relation",
        "target_variables": ["x"],
        "lean_formula": "forall t : Time, x t = t",
        "requires_closed_form": False,
        "source_text": "target is a position-time relation",
        "confidence": 0.82,
        "parse_ok": True,
    }
    payload["target"] = {"symbol": "x", "description": "position function"}
    payload["forbidden_as_assumption"] = ["target position function x"]
    module = ModuleA2ModelIR(StaticModelIRClient(json.dumps(payload)), _prompt(tmp_path))

    model_ir = module.run(
        sample_id="function-target",
        problem_text="A particle has position x(t). State the position-time relation.",
        problem_ir={"unknown_target": {"symbol": "x", "description": "position function"}},
        structured_mechlib_context=None,
    )

    assert model_ir.parse_ok is True
    assert model_ir.quantity_annotations[0].lean_type == "Time -> Length"
    assert model_ir.quantity_annotations[0].supported is True
    assert model_ir.canonical_target is not None
    assert model_ir.canonical_target.lean_formula == "forall t : Time, x t = t"
