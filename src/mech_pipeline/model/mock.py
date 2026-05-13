from __future__ import annotations

import json
import re

from mech_pipeline.model.base import ModelClient
from mech_pipeline.types import ModelResponse


def _slice_between(text: str, start: str, end: str) -> str:
    lo = text.lower()
    s = lo.find(start.lower())
    if s == -1:
        return ""
    s_end = s + len(start)
    e = lo.find(end.lower(), s_end)
    if e == -1:
        return text[s_end:]
    return text[s_end:e]


def _extract_problem_focus(prompt: str) -> str:
    chunks = [
        _slice_between(prompt, "Problem text:", "Options:"),
        _slice_between(prompt, "Problem:", "Options:"),
        _slice_between(prompt, "Original problem:", "ProblemIR:"),
        _slice_between(prompt, "Question:", "Current concept:"),
    ]
    text = " ".join(c for c in chunks if c.strip())
    return text if text.strip() else prompt


def _infer_problem_mode(prompt: str) -> str:
    low = prompt.lower()
    if '"physical_laws"' in low:
        if "kinematics" in low:
            return "kinematics"
        if "newtonsecondlaw" in low:
            return "newton"
        if "workenergy" in low or "energyconservation" in low:
            return "energy"

    focus = _extract_problem_focus(prompt).lower()
    has_kinematics = any(
        kw in focus for kw in ["kinematics", "velocity", "speed", "displacement", "distance", "position", "time"]
    )
    has_force = any(kw in focus for kw in ["newton", "force", "mass", "friction", "normal"])
    has_energy = any(kw in focus for kw in ["work", "energy", "kinetic", "potential", "conservation"])
    if has_kinematics and not has_force:
        return "kinematics"
    if has_energy:
        return "energy"
    return "newton"


class MockModelClient(ModelClient):
    def __init__(self, model_id: str | None, supports_vision: bool) -> None:
        self.model_id = model_id or "mock-model"
        self.supports_vision = supports_vision

    def generate_text(self, prompt: str, **kwargs) -> ModelResponse:
        return ModelResponse(text=self._respond(prompt), raw={"provider": "mock"})

    def generate_multimodal(self, prompt: str, images_b64: list[str], **kwargs) -> ModelResponse:
        return ModelResponse(
            text=self._respond(prompt),
            raw={"provider": "mock", "num_images": len(images_b64)},
        )

    def _respond(self, prompt: str) -> str:
        mode = _infer_problem_mode(prompt)
        if "__TASK_A_EXTRACT_IR__" in prompt:
            if mode == "kinematics":
                payload = {
                    "objects": [{"name": "particle", "type": "mass_point"}],
                    "known_quantities": [
                        {"symbol": "v", "value": 10.0, "unit": "m/s"},
                        {"symbol": "t", "value": 3.0, "unit": "s"},
                    ],
                    "unknown_target": {"symbol": "s", "description": "displacement"},
                    "units": [{"symbol": "s", "unit": "m"}],
                    "constraints": ["1D motion", "constant velocity"],
                    "relations": ["s = v * t"],
                    "physical_laws": ["Kinematics"],
                    "assumptions": ["uniform motion"],
                    "diagram_information": [],
                    "goal_statement": "solve displacement s",
                    "coordinate_system": "x",
                    "reference_frame": "ground",
                    "simplifications": ["ignore drag"],
                    "symbol_table": {"s": "displacement", "v": "velocity", "t": "time"},
                }
            elif mode == "energy":
                payload = {
                    "objects": [{"name": "block", "type": "mass_point"}],
                    "known_quantities": [
                        {"symbol": "m", "value": 2.0, "unit": "kg"},
                        {"symbol": "h", "value": 5.0, "unit": "m"},
                    ],
                    "unknown_target": {"symbol": "v", "description": "speed"},
                    "units": [{"symbol": "v", "unit": "m/s"}],
                    "constraints": ["no non-conservative work"],
                    "relations": ["m * g * h = (1/2) * m * v^2"],
                    "physical_laws": ["EnergyConservation"],
                    "assumptions": ["no friction"],
                    "diagram_information": [],
                    "goal_statement": "solve final speed v",
                    "coordinate_system": "vertical",
                    "reference_frame": "ground",
                    "simplifications": ["point mass"],
                    "symbol_table": {"m": "mass", "g": "gravity", "h": "height", "v": "speed"},
                }
            else:
                payload = {
                    "objects": [{"name": "block", "type": "mass_point"}],
                    "known_quantities": [{"symbol": "m", "value": 1.0, "unit": "kg"}],
                    "unknown_target": {"symbol": "a", "description": "acceleration"},
                    "units": [{"symbol": "a", "unit": "m/s^2"}],
                    "constraints": ["1D motion"],
                    "relations": ["F = m * a"],
                    "physical_laws": ["NewtonSecondLaw"],
                    "assumptions": ["inertial frame"],
                    "diagram_information": [],
                    "goal_statement": "solve acceleration a",
                    "coordinate_system": "x",
                    "reference_frame": "ground",
                    "simplifications": ["ignore friction"],
                    "symbol_table": {"F": "force", "m": "mass", "a": "acceleration"},
                }
            return json.dumps(payload, ensure_ascii=False)

        if "__TASK_A2_BUILD_MODEL_IR__" in prompt:
            if mode == "kinematics":
                payload = {
                    "objects": [{"name": "particle", "type": "mass_point"}],
                    "variables": {"s": "displacement", "v": "speed", "t": "time"},
                    "quantity_annotations": [
                        {
                            "symbol": "s",
                            "semantic_role": "displacement",
                            "unit_or_dimension": "m",
                            "lean_type": "Length",
                            "confidence": 0.95,
                            "evidence_text": "unknown displacement s in meters",
                            "reasoning_note": "displacement is length",
                        },
                        {
                            "symbol": "v",
                            "semantic_role": "speed",
                            "unit_or_dimension": "m/s",
                            "lean_type": "Speed",
                            "confidence": 0.95,
                            "evidence_text": "given speed v",
                            "reasoning_note": "m/s identifies speed",
                        },
                        {
                            "symbol": "t",
                            "semantic_role": "time",
                            "unit_or_dimension": "s",
                            "lean_type": "Time",
                            "confidence": 0.95,
                            "evidence_text": "given time t",
                            "reasoning_note": "seconds identify time",
                        },
                    ],
                    "givens": [
                        {
                            "name": "h_v",
                            "lean": "v = 10",
                            "role": "given_fact",
                            "source_type": "problem_ir",
                            "source_id": "known_quantities.v",
                            "allowed_in_hypotheses": True,
                        },
                        {
                            "name": "h_t",
                            "lean": "t = 3",
                            "role": "given_fact",
                            "source_type": "problem_ir",
                            "source_id": "known_quantities.t",
                            "allowed_in_hypotheses": True,
                        },
                    ],
                    "coordinate_system": {"axis": "x"},
                    "reference_frame": "ground",
                    "local_definitions": [],
                    "model_instances": [
                        {
                            "instance_id": "mi1",
                            "kind": "constant_speed_kinematics",
                            "natural_language": "Use the constant speed displacement relation.",
                            "entities": ["particle"],
                            "variables": {"s": "displacement", "v": "speed", "t": "time"},
                            "parameters": {},
                            "coordinate_convention": "positive x is direction of motion",
                            "planning_schema_hint": "law.kinematics.constant_speed",
                            "expected_claim": "s = v * t",
                            "hypothesis_form": "",
                            "provenance": {"source_type": "problem_ir", "source_id": "physical_laws.Kinematics"},
                            "confidence": 0.9,
                        }
                    ],
                    "canonical_target": {
                        "target_id": "target_1",
                        "target_kind": "closed_form",
                        "target_variables": ["s"],
                        "lean_formula": "s = v * t",
                        "requires_closed_form": True,
                        "source_text": "Find displacement s.",
                        "confidence": 0.9,
                        "parse_ok": True,
                    },
                    "target": {"symbol": "s", "description": "displacement"},
                    "forbidden_as_assumption": ["target displacement s", "s = v * t solved result"],
                }
            elif mode == "energy":
                payload = {
                    "objects": [{"name": "block", "type": "mass_point"}],
                    "variables": {"m": "mass", "g": "gravity", "h": "height", "v": "speed"},
                    "quantity_annotations": [
                        {
                            "symbol": "m",
                            "semantic_role": "mass",
                            "unit_or_dimension": "kg",
                            "lean_type": "Mass",
                            "confidence": 0.95,
                            "evidence_text": "mass m",
                            "reasoning_note": "kg identifies mass",
                        },
                        {
                            "symbol": "g",
                            "semantic_role": "gravitational acceleration",
                            "unit_or_dimension": "m/s^2",
                            "lean_type": "Acceleration",
                            "confidence": 0.9,
                            "evidence_text": "gravity g",
                            "reasoning_note": "standard gravity is acceleration",
                        },
                        {
                            "symbol": "h",
                            "semantic_role": "height",
                            "unit_or_dimension": "m",
                            "lean_type": "Length",
                            "confidence": 0.95,
                            "evidence_text": "height h",
                            "reasoning_note": "height is length",
                        },
                        {
                            "symbol": "v",
                            "semantic_role": "speed",
                            "unit_or_dimension": "m/s",
                            "lean_type": "Speed",
                            "confidence": 0.95,
                            "evidence_text": "final speed v",
                            "reasoning_note": "target speed uses m/s",
                        },
                    ],
                    "givens": [
                        {
                            "name": "h_no_friction",
                            "lean": "no friction",
                            "role": "given_fact",
                            "source_type": "problem_ir",
                            "source_id": "assumptions.no_friction",
                            "allowed_in_hypotheses": True,
                        }
                    ],
                    "coordinate_system": {"axis": "vertical"},
                    "reference_frame": "ground",
                    "local_definitions": [],
                    "model_instances": [
                        {
                            "instance_id": "mi1",
                            "kind": "work_energy_balance",
                            "natural_language": "Use conservation of mechanical energy.",
                            "entities": ["block"],
                            "variables": {"m": "mass", "g": "gravity", "h": "height", "v": "speed"},
                            "parameters": {},
                            "coordinate_convention": "vertical height h above reference level",
                            "planning_schema_hint": "law.energy.conservation",
                            "expected_claim": "m * g * h = (1/2) * m * v^2",
                            "hypothesis_form": "",
                            "provenance": {"source_type": "problem_ir", "source_id": "physical_laws.EnergyConservation"},
                            "confidence": 0.85,
                        }
                    ],
                    "canonical_target": {
                        "target_id": "target_1",
                        "target_kind": "relation",
                        "target_variables": ["v"],
                        "lean_formula": "v^2 = 2 * g * h",
                        "requires_closed_form": False,
                        "source_text": "Find final speed v.",
                        "confidence": 0.85,
                        "parse_ok": True,
                    },
                    "target": {"symbol": "v", "description": "final speed"},
                    "forbidden_as_assumption": ["target final speed v", "v^2 = 2 * g * h"],
                }
            else:
                payload = {
                    "objects": [{"name": "block", "type": "mass_point"}],
                    "variables": {"F": "force", "m": "mass", "a": "acceleration"},
                    "quantity_annotations": [
                        {
                            "symbol": "F",
                            "semantic_role": "net force",
                            "unit_or_dimension": "N",
                            "lean_type": "Force",
                            "confidence": 0.95,
                            "evidence_text": "force F",
                            "reasoning_note": "newtons identify force",
                        },
                        {
                            "symbol": "m",
                            "semantic_role": "mass",
                            "unit_or_dimension": "kg",
                            "lean_type": "Mass",
                            "confidence": 0.95,
                            "evidence_text": "mass m",
                            "reasoning_note": "kg identifies mass",
                        },
                        {
                            "symbol": "a",
                            "semantic_role": "acceleration",
                            "unit_or_dimension": "m/s^2",
                            "lean_type": "Acceleration",
                            "confidence": 0.95,
                            "evidence_text": "target acceleration a",
                            "reasoning_note": "m/s^2 identifies acceleration",
                        },
                    ],
                    "givens": [
                        {
                            "name": "h_m",
                            "lean": "m = 1",
                            "role": "given_fact",
                            "source_type": "problem_ir",
                            "source_id": "known_quantities.m",
                            "allowed_in_hypotheses": True,
                        }
                    ],
                    "coordinate_system": {"axis": "x"},
                    "reference_frame": "ground",
                    "local_definitions": [],
                    "model_instances": [
                        {
                            "instance_id": "mi1",
                            "kind": "newton_second_law_1d",
                            "natural_language": "Apply Newton second law in one dimension.",
                            "entities": ["block"],
                            "variables": {"F": "net force", "m": "mass", "a": "acceleration"},
                            "parameters": {},
                            "coordinate_convention": "positive x is direction of force",
                            "planning_schema_hint": "law.newton.second.1d",
                            "expected_claim": "F = m * a",
                            "hypothesis_form": "",
                            "provenance": {"source_type": "problem_ir", "source_id": "physical_laws.NewtonSecondLaw"},
                            "confidence": 0.9,
                        }
                    ],
                    "canonical_target": {
                        "target_id": "target_1",
                        "target_kind": "closed_form",
                        "target_variables": ["a"],
                        "lean_formula": "a = F / m",
                        "requires_closed_form": True,
                        "source_text": "solve acceleration a",
                        "confidence": 0.9,
                        "parse_ok": True,
                    },
                    "target": {"symbol": "a", "description": "acceleration"},
                    "forbidden_as_assumption": ["target acceleration a", "a = F / m"],
                }
            return json.dumps(payload, ensure_ascii=False)

        if "__TASK_CONTROLLED_SKETCH__" in prompt:
            evidence_text = _slice_between(prompt, "EvidenceBindings:", "Structured MechLib context:")
            verified_match = re.search(r'"verified_decl"\s*:\s*"([^"]+)"', evidence_text)
            verified_decl = verified_match.group(1) if verified_match else None
            if mode == "kinematics":
                planning_schema = "law.kinematics.constant_speed"
                expected_claim = "s = v * t"
                claim = "Apply constant speed kinematics to obtain s = v * t."
            elif mode == "energy":
                planning_schema = "law.energy.conservation"
                expected_claim = "m * g * h = (1/2) * m * v^2"
                claim = "Apply energy conservation to relate height loss to final kinetic energy."
            else:
                planning_schema = "law.newton.second.1d"
                expected_claim = "F = m * a"
                claim = "Apply Newton second law in one dimension to obtain F = m * a."
            step = {
                "step_id": "sk1",
                "kind": "law_to_equation",
                "claim": "bound mechanics law equation",
                "formal_claim": expected_claim,
                "source_model_instance": "mi1",
                "planning_schema": planning_schema,
                "verified_decl": verified_decl,
                "binding_status": "ok" if verified_decl else "gap_schema_only",
                "expected_claim": expected_claim,
                "proof_fact_allowed": bool(verified_decl),
                "allowed_solvers": ["simp", "linarith", "ring"],
                "required_hypotheses": [],
                "produces": "h_law" if verified_decl else None,
                "notes": "",
            }
            payload = {
                "status": "ok" if verified_decl else "blocked_by_evidence_gap",
                "proof_steps": [step] if verified_decl else [],
                "algebra_obligation": None,
                "blocked_law_steps": []
                if verified_decl
                else [
                    {
                        "step_id": "blocked_mi1",
                        "source_model_instance": "mi1",
                        "planning_schema": planning_schema,
                        "expected_claim": expected_claim,
                        "binding_status": "gap_schema_only",
                        "proof_fact_allowed": False,
                        "reason": "No proof-eligible verified declaration is bound.",
                    }
                ],
            }
            return json.dumps(payload, ensure_ascii=False)

        if "__TASK_B_GENERATE_MINIMAL_SKELETON__" in prompt:
            evidence_text = _slice_between(prompt, "EvidenceBindings:", "StructuredMechLibContext:")
            verified_match = re.search(r'"verified_decl"\s*:\s*"([^"]+)"', evidence_text)
            verified_decl = verified_match.group(1) if verified_match else None
            if mode == "kinematics":
                theorem_decl = (
                    "theorem minimal_displacement_skeleton "
                    "(s v t : Real) (h_v : v = 10) (h_t : t = 3) : s = v * t"
                )
                provenance = [
                    {
                        "name": "h_v",
                        "lean": "v = 10",
                        "role": "problem_fact",
                        "source_type": "problem_ir",
                        "source_id": "known_quantities.v",
                        "allowed_in_hypotheses": True,
                        "proof_fact_allowed": False,
                    },
                    {
                        "name": "h_t",
                        "lean": "t = 3",
                        "role": "problem_fact",
                        "source_type": "problem_ir",
                        "source_id": "known_quantities.t",
                        "allowed_in_hypotheses": True,
                        "proof_fact_allowed": False,
                    },
                ]
                selected_laws = ["law.kinematics.constant_speed"]
            elif mode == "energy":
                theorem_decl = (
                    "theorem minimal_energy_skeleton "
                    "(m g h v : Real) (h_no_friction : 0 = 0) : v ^ (2 : Nat) = 2 * g * h"
                )
                provenance = [
                    {
                        "name": "h_no_friction",
                        "lean": "0 = 0",
                        "role": "problem_fact",
                        "source_type": "problem_ir",
                        "source_id": "assumptions.no_friction",
                        "allowed_in_hypotheses": True,
                        "proof_fact_allowed": False,
                    }
                ]
                selected_laws = ["law.energy.conservation"]
            else:
                theorem_decl = (
                    "theorem minimal_newton_skeleton "
                    "(F m a : Real) (h_m : m = 1) : a * m = F"
                )
                provenance = [
                    {
                        "name": "h_m",
                        "lean": "m = 1",
                        "role": "problem_fact",
                        "source_type": "problem_ir",
                        "source_id": "known_quantities.m",
                        "allowed_in_hypotheses": True,
                        "proof_fact_allowed": False,
                    }
                ]
                selected_laws = ["law.newton.second.1d"]
            payload = {
                "candidates": [
                    {
                        "candidate_id": "c1",
                        "lean_header": "import MechLib",
                        "theorem_decl": theorem_decl,
                        "assumptions": [],
                        "plan": "minimal skeleton",
                        "supporting_facts": [],
                        "fact_sources": [],
                        "library_symbols_used": [],
                        "grounding_explanation": "minimal skeleton generated from ModelIR and controlled sketch",
                        "hypothesis_provenance": provenance,
                        "selected_laws": selected_laws,
                        "verified_decls": [verified_decl] if verified_decl else [],
                        "gap_laws": [],
                        "proof_obligations": [],
                        "controlled_sketch_steps_used": ["sk1"],
                        "unsupported_claims": [],
                        "skeleton_audit": {},
                    }
                ]
            }
            return json.dumps(payload, ensure_ascii=False)

        if "__TASK_B_GENERATE_STATEMENTS__" in prompt:
            if mode == "kinematics":
                payload = {
                    "candidates": [
                        {
                            "candidate_id": "c1",
                            "lean_header": "import Physlib",
                            "theorem_decl": "theorem displacement_from_velocity_time (s v t : Real) (h : s = v * t) : s = v * t",
                            "assumptions": ["uniform motion"],
                        },
                        {
                            "candidate_id": "c2",
                            "lean_header": "import Physlib",
                            "theorem_decl": "theorem velocity_from_displacement_time (s v t : Real) (h : s = v * t) (ht : t != 0) : v = s / t",
                            "assumptions": ["uniform motion", "t != 0"],
                        },
                        {
                            "candidate_id": "c3",
                            "lean_header": "import Physlib",
                            "theorem_decl": "theorem wrong_newton_form (F m a : Real) (h : F = m * a) : a = F / m",
                            "assumptions": [],
                        },
                        {
                            "candidate_id": "c4",
                            "lean_header": "import Physlib",
                            "theorem_decl": "theorem trivial_displacement (s : Real) : s = s",
                            "assumptions": [],
                        },
                    ]
                }
            elif mode == "energy":
                payload = {
                    "candidates": [
                        {
                            "candidate_id": "c1",
                            "lean_header": "import Physlib",
                            "theorem_decl": "theorem mech_energy_conservation (m g h v : Real) (hm : m != 0) (hrel : m * g * h = (1/2) * m * v^2) : v^2 = 2 * g * h",
                            "assumptions": ["no friction"],
                        },
                        {
                            "candidate_id": "c2",
                            "lean_header": "import Physlib",
                            "theorem_decl": "theorem speed_positive_from_height (g h v : Real) (hg : g > 0) (hh : h >= 0) (hrel : v^2 = 2 * g * h) : v^2 >= 0",
                            "assumptions": [],
                        },
                        {
                            "candidate_id": "c3",
                            "lean_header": "import Physlib",
                            "theorem_decl": "theorem wrong_kinematics_form (s v t : Real) (h : s = v * t) : v = s / t",
                            "assumptions": [],
                        },
                        {
                            "candidate_id": "c4",
                            "lean_header": "import Physlib",
                            "theorem_decl": "theorem trivial_energy (e : Real) : e = e",
                            "assumptions": [],
                        },
                    ]
                }
            else:
                payload = {
                    "candidates": [
                        {
                            "candidate_id": "c1",
                            "lean_header": "import Physlib",
                            "theorem_decl": (
                                "theorem newton_second_law_force_mass_acceleration "
                                "(F m a : Real) (h : F = m * a) : F = m * a"
                            ),
                            "assumptions": ["inertial frame", "Newton second law relation"],
                        },
                        {
                            "candidate_id": "c2",
                            "lean_header": "import Physlib",
                            "theorem_decl": (
                                "theorem acceleration_from_force_mass "
                                "(F m a : Real) (h : F = m * a) (hm : m != 0) : a = F / m"
                            ),
                            "assumptions": ["m != 0"],
                        },
                        {
                            "candidate_id": "c3",
                            "lean_header": "import Physlib",
                            "theorem_decl": "theorem wrong_kinematics_shape (s v t : Real) (h : s = v * t) : s = v * t",
                            "assumptions": [],
                        },
                        {
                            "candidate_id": "c4",
                            "lean_header": "import Physlib",
                            "theorem_decl": "theorem trivial_mass (m : Real) : m = m",
                            "assumptions": [],
                        },
                    ]
                }
            return json.dumps(payload, ensure_ascii=False)

        if "__TASK_Z_DIRECT_FORMALIZE__" in prompt:
            if mode == "kinematics":
                payload = {
                    "theorem_decl": (
                        "theorem direct_displacement_from_velocity_time "
                        "(s v t : Real) "
                        "(h : s = v * t) : s = v * t"
                    ),
                    "proof_body": "exact h",
                    "plan": "Use the provided kinematics relation directly.",
                    "used_facts": ["h"],
                }
            elif mode == "energy":
                payload = {
                    "theorem_decl": (
                        "theorem direct_speed_sq_from_energy "
                        "(m g h v : Real) "
                        "(hm : m != 0) "
                        "(hrel : m * g * h = (1 / 2 : Real) * m * v^2) : v^2 = 2 * g * h"
                    ),
                    "proof_body": "\n".join(
                        [
                            "apply (eq_div_iff hm).2",
                            "calc",
                            "  v ^ 2 * m = m * v ^ 2 := by ring",
                            "  _ = 2 * (m * g * h) := by",
                            "    have hmul := congrArg (fun x : Real => 2 * x) hrel",
                            "    simpa [pow_two] using hmul",
                            "  _ = m * (2 * g * h) := by ring",
                        ]
                    ),
                    "plan": "Multiply the energy equation by 2 and divide by the nonzero mass.",
                    "used_facts": ["hrel", "hm"],
                }
            else:
                payload = {
                    "theorem_decl": (
                        "theorem direct_acceleration_from_force_mass "
                        "(F m a : Real) "
                        "(hm : m != 0) "
                        "(h : F = m * a) : a = F / m"
                    ),
                    "proof_body": "\n".join(
                        [
                            "apply (eq_div_iff hm).2",
                            "calc",
                            "  a * m = m * a := by ring",
                            "  _ = F := by rw [<- h]",
                        ]
                    ),
                    "plan": "Solve the Newton second law relation for acceleration.",
                    "used_facts": ["h", "hm"],
                }
            return json.dumps(payload, ensure_ascii=False)

        if "__TASK_D_SEMANTIC_RANK__" in prompt:
            cids = re.findall(r'"candidate_id"\s*:\s*"([^"]+)"', prompt)
            ordered: list[str] = []
            for cid in cids:
                if cid not in ordered:
                    ordered.append(cid)
            if not ordered:
                ordered = ["c1", "c2", "c3", "c4"]

            results = []
            for cid in ordered:
                score = 0.65
                reason = "Partially aligned with the source problem."
                if cid == "c2":
                    score = 0.92
                    reason = "Target variable and governing relation are well aligned."
                elif cid == "c1":
                    score = 0.45
                    reason = "The target or constraints are underspecified."
                elif cid == "c4":
                    score = 0.2
                    reason = "The statement is trivial."
                back_translation = f"{cid} states a relation among force, mass, and acceleration."
                if mode == "kinematics":
                    back_translation = f"{cid} states a relation among displacement, velocity, and time."
                if mode == "energy":
                    back_translation = f"{cid} states a relation among energy, gravity, height, and speed."
                results.append(
                    {
                        "candidate_id": cid,
                        "back_translation": back_translation,
                        "semantic_score": score,
                        "semantic_pass": score >= 0.6,
                        "reason": reason,
                    }
                )
            return json.dumps({"results": results}, ensure_ascii=False)

        if "__TASK_E_PLAN_PROOF__" in prompt:
            payload = {
                "plan": "Use the theorem assumptions first and leave algebraic simplification to the end.",
                "theorems_to_apply": [],
                "givens_to_use": ["h"],
                "intermediate_claims": ["Rearrange the main relation into the target form."],
                "algebraic_cleanup_only": False,
            }
            return json.dumps(payload, ensure_ascii=False)

        if "__TASK_E_GENERATE_PROOF__" in prompt or "__TASK_E_REPAIR_PROOF__" in prompt:
            payload = {
                "proof_body": "first | aesop | rfl | simp",
                "strategy": "mock baseline",
                "plan": "Use assumptions first, then simplify.",
                "used_facts": ["aesop", "rfl", "simp"],
            }
            return json.dumps(payload, ensure_ascii=False)

        return json.dumps({"message": "mock-default"}, ensure_ascii=False)
