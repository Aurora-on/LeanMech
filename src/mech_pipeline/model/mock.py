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

        if "__TASK_B_GENERATE_STATEMENTS__" in prompt:
            if mode == "kinematics":
                payload = {
                    "candidates": [
                        {
                            "candidate_id": "c1",
                            "lean_header": "import PhysLean",
                            "theorem_decl": "theorem displacement_from_velocity_time (s v t : Real) (h : s = v * t) : s = v * t",
                            "assumptions": ["uniform motion"],
                        },
                        {
                            "candidate_id": "c2",
                            "lean_header": "import PhysLean",
                            "theorem_decl": "theorem velocity_from_displacement_time (s v t : Real) (h : s = v * t) (ht : t != 0) : v = s / t",
                            "assumptions": ["uniform motion", "t != 0"],
                        },
                        {
                            "candidate_id": "c3",
                            "lean_header": "import PhysLean",
                            "theorem_decl": "theorem wrong_newton_form (F m a : Real) (h : F = m * a) : a = F / m",
                            "assumptions": [],
                        },
                        {
                            "candidate_id": "c4",
                            "lean_header": "import PhysLean",
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
                            "lean_header": "import PhysLean",
                            "theorem_decl": "theorem mech_energy_conservation (m g h v : Real) (hm : m != 0) (hrel : m * g * h = (1/2) * m * v^2) : v^2 = 2 * g * h",
                            "assumptions": ["no friction"],
                        },
                        {
                            "candidate_id": "c2",
                            "lean_header": "import PhysLean",
                            "theorem_decl": "theorem speed_positive_from_height (g h v : Real) (hg : g > 0) (hh : h >= 0) (hrel : v^2 = 2 * g * h) : v^2 >= 0",
                            "assumptions": [],
                        },
                        {
                            "candidate_id": "c3",
                            "lean_header": "import PhysLean",
                            "theorem_decl": "theorem wrong_kinematics_form (s v t : Real) (h : s = v * t) : v = s / t",
                            "assumptions": [],
                        },
                        {
                            "candidate_id": "c4",
                            "lean_header": "import PhysLean",
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
                            "lean_header": "import PhysLean",
                            "theorem_decl": (
                                "theorem newton_second_law_force_mass_acceleration "
                                "(F m a : Real) (h : F = m * a) : F = m * a"
                            ),
                            "assumptions": ["inertial frame", "Newton second law relation"],
                        },
                        {
                            "candidate_id": "c2",
                            "lean_header": "import PhysLean",
                            "theorem_decl": (
                                "theorem acceleration_from_force_mass "
                                "(F m a : Real) (h : F = m * a) (hm : m != 0) : a = F / m"
                            ),
                            "assumptions": ["m != 0"],
                        },
                        {
                            "candidate_id": "c3",
                            "lean_header": "import PhysLean",
                            "theorem_decl": "theorem wrong_kinematics_shape (s v t : Real) (h : s = v * t) : s = v * t",
                            "assumptions": [],
                        },
                        {
                            "candidate_id": "c4",
                            "lean_header": "import PhysLean",
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
