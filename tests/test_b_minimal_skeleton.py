from __future__ import annotations

import json
from pathlib import Path

from mech_pipeline.model.base import ModelClient
from mech_pipeline.modules.B_statement_gen import ModuleB
from mech_pipeline.types import (
    AlgebraObligation,
    BlockedLawStep,
    CanonicalTarget,
    ControlledSketch,
    ControlledSketchStep,
    EvidenceBinding,
    FunctionFormulaIR,
    GroundingResult,
    HypothesisProvenance,
    ModelIR,
    ModelInstance,
    ModelResponse,
    QuantityTypeAnnotation,
    SketchVariant,
    SketchAuditResult,
    TheoremSkeletonCandidate,
)
from mech_pipeline.utils import to_row, write_jsonl


class StaticClient(ModelClient):
    def __init__(self, payload: str) -> None:
        self.model_id = "static-b-minimal"
        self.supports_vision = False
        self.payload = payload
        self.calls = 0

    def generate_text(self, prompt: str, **kwargs) -> ModelResponse:
        _ = (prompt, kwargs)
        self.calls += 1
        return ModelResponse(text=self.payload)

    def generate_multimodal(self, prompt: str, images_b64: list[str], **kwargs) -> ModelResponse:
        _ = images_b64
        return self.generate_text(prompt, **kwargs)


def _prompt(tmp_path: Path) -> Path:
    path = tmp_path / "B_generate_statements.txt"
    path.write_text("__TASK_B_GENERATE_STATEMENTS__", encoding="utf-8")
    return path


def _minimal_prompt(tmp_path: Path) -> Path:
    path = tmp_path / "B_generate_minimal_skeleton.txt"
    path.write_text("__TASK_B_GENERATE_MINIMAL_SKELETON__", encoding="utf-8")
    return path


def _grounding() -> GroundingResult:
    return GroundingResult(
        sample_id="atwood-1",
        model_id="m",
        problem_ir={
            "unknown_target": {"symbol": "alpha", "description": "angular acceleration"},
            "candidate_answer": "alpha = a / R",
            "physical_laws": ["NewtonSecondLaw", "FixedAxisRotation"],
        },
        parse_ok=True,
        raw_response="",
        error=None,
    )


def _model_ir() -> ModelIR:
    return ModelIR(
        sample_id="atwood-1",
        variables={
            "m1": {"type": "mass"},
            "m2": {"type": "mass"},
            "g": {"type": "acceleration"},
            "a": {"type": "acceleration"},
            "T1": {"type": "force"},
            "T2": {"type": "force"},
            "R": {"type": "length"},
            "I": {"type": "moment_of_inertia"},
            "alpha": {"type": "angular_acceleration"},
        },
        quantity_annotations=[
            QuantityTypeAnnotation("m1", semantic_role="mass", lean_type="Mass", confidence=0.95),
            QuantityTypeAnnotation("m2", semantic_role="mass", lean_type="Mass", confidence=0.95),
            QuantityTypeAnnotation("g", semantic_role="gravity", lean_type="Acceleration", confidence=0.95),
            QuantityTypeAnnotation("a", semantic_role="acceleration", lean_type="Acceleration", confidence=0.95),
            QuantityTypeAnnotation("T1", semantic_role="tension force", lean_type="Force", confidence=0.95),
            QuantityTypeAnnotation("T2", semantic_role="tension force", lean_type="Force", confidence=0.95),
            QuantityTypeAnnotation("R", semantic_role="radius", lean_type="Length", confidence=0.95),
            QuantityTypeAnnotation("I", semantic_role="moment of inertia", lean_type="MomentOfInertia", confidence=0.95),
            QuantityTypeAnnotation("alpha", semantic_role="angular acceleration", lean_type="AngularAcceleration", confidence=0.95),
        ],
        givens=[
            HypothesisProvenance(
                name="h_m1_pos",
                lean="0 < m1",
                role="problem_fact",
                source_type="problem_ir",
                source_id="givens.m1",
                allowed_in_hypotheses=True,
            ),
            HypothesisProvenance(
                name="h_m2_pos",
                lean="0 < m2",
                role="problem_fact",
                source_type="problem_ir",
                source_id="givens.m2",
                allowed_in_hypotheses=True,
            ),
        ],
        model_instances=[
            ModelInstance(
                instance_id="mi_m1",
                kind="newton_second_law_1d",
                natural_language="Newton law for mass m1.",
                variables={"force": "T1", "mass": "m1", "acceleration": "a"},
                planning_schema_id="law.newton.second.1d",
                expected_claim="T1 - m1 * g = m1 * a",
            ),
            ModelInstance(
                instance_id="mi_m2",
                kind="newton_second_law_1d",
                natural_language="Newton law for mass m2.",
                variables={"force": "T2", "mass": "m2", "acceleration": "a"},
                planning_schema_id="law.newton.second.1d",
                expected_claim="m2 * g - T2 = m2 * a",
            ),
            ModelInstance(
                instance_id="mi_rot",
                kind="fixed_axis_rotation",
                natural_language="Torque law for pulley rotation.",
                variables={"torque": "T2", "moment_of_inertia": "I", "angular_acceleration": "alpha"},
                planning_schema_id="law.rotation.fixed_axis",
                expected_claim="(T2 - T1) * R = I * alpha",
            ),
        ],
        canonical_target=CanonicalTarget(
            target_kind="closed_form",
            target_variables=["alpha"],
            lean_formula="alpha = a / R",
            requires_closed_form=True,
            source_text="target angular acceleration alpha",
            confidence=0.9,
            parse_ok=True,
        ),
        target={"symbol": "alpha", "description": "angular acceleration"},
        forbidden_as_assumption=["target angular acceleration alpha", "alpha = a / R"],
        parse_ok=True,
    )


def _sketch() -> ControlledSketch:
    return ControlledSketch(
        sample_id="atwood-1",
        status="ok",
        proof_steps=[
            ControlledSketchStep(
                step_id="sk_m1",
                kind="law_to_equation",
                claim="Newton law for m1",
                formal_claim="T1 - m1 * g = m1 * a",
                source_model_instance="mi_m1",
                planning_schema="law.newton.second.1d",
                verified_decl="MechLib.Atwood.newton_m1",
                binding_status="ok",
                expected_claim="T1 - m1 * g = m1 * a",
                proof_fact_allowed=True,
            ),
            ControlledSketchStep(
                step_id="sk_m2",
                kind="law_to_equation",
                claim="Newton law for m2",
                formal_claim="m2 * g - T2 = m2 * a",
                source_model_instance="mi_m2",
                planning_schema="law.newton.second.1d",
                verified_decl="MechLib.Atwood.newton_m2",
                binding_status="ok",
                expected_claim="m2 * g - T2 = m2 * a",
                proof_fact_allowed=True,
            ),
        ],
        algebra_obligation=AlgebraObligation(
            obligation_id="sk_alg",
            claim="solve target",
            formal_claim="alpha = a / R",
            required_equations=["sk_m1", "sk_m2"],
            target_variables=["alpha"],
        ),
        blocked_law_steps=[
            BlockedLawStep(
                step_id="sk_rot",
                source_model_instance="mi_rot",
                planning_schema="law.rotation.fixed_axis",
                expected_claim="(T2 - T1) * R = I * alpha",
                binding_status="gap_schema_only",
                proof_fact_allowed=False,
            )
        ],
        parse_ok=True,
    )


def _bindings() -> list[EvidenceBinding]:
    return [
        EvidenceBinding(
            binding_id="b_m1",
            model_instance_id="mi_m1",
            planning_schema="law.newton.second.1d",
            verified_decl="MechLib.Atwood.newton_m1",
            decl_statement="def Newton1D (F : Force) (m : Mass) (a : Acceleration) : Prop",
            callable_by_llm=True,
            required_imports=["import MechLib.Atwood.Newton"],
            lean_check_pass=True,
            proof_fact_allowed=True,
            binding_status="ok",
            expected_claim="T1 - m1 * g = m1 * a",
        ),
        EvidenceBinding(
            binding_id="b_m2",
            model_instance_id="mi_m2",
            planning_schema="law.newton.second.1d",
            verified_decl="MechLib.Atwood.newton_m2",
            decl_statement="def Newton1D (F : Force) (m : Mass) (a : Acceleration) : Prop",
            callable_by_llm=True,
            required_imports=["MechLib.Atwood.Newton", "import MechLib.Atwood.Pulley"],
            lean_check_pass=True,
            proof_fact_allowed=True,
            binding_status="ok",
            expected_claim="m2 * g - T2 = m2 * a",
        ),
        EvidenceBinding(
            binding_id="b_rot",
            model_instance_id="mi_rot",
            planning_schema="law.rotation.fixed_axis",
            verified_decl=None,
            required_imports=["import MechLib.Atwood.Rotation"],
            proof_fact_allowed=False,
            binding_status="gap_schema_only",
            expected_claim="(T2 - T1) * R = I * alpha",
        ),
    ]


def _pass_audit() -> SketchAuditResult:
    return SketchAuditResult(sample_id="atwood-1", audit_pass=True)


def _sketch_without_gap() -> ControlledSketch:
    sketch = _sketch()
    sketch.blocked_law_steps = []
    return sketch


def test_b_minimal_skeleton_outputs_theorem_skeleton_candidate(tmp_path: Path) -> None:
    payload = json.dumps(
        {
            "candidates": [
                    {
                        "candidate_id": "c1",
                        "theorem_name_hint": "atwood_minimal",
                        "lean_header": "import MechLib",
                        "theorem_decl": (
                            "theorem atwood_minimal "
                            "(m1 m2 g T1 T2 R I alpha a : Real) "
                            "(h_m1_pos : 0 < m1) (h_m2_pos : 0 < m2) : alpha = a / R"
                        ),
                        "selected_model_instances": ["mi_m1", "mi_m2"],
                        "controlled_sketch_steps_used": ["sk_m1", "sk_m2", "sk_rot", "sk_alg"],
                        "unsupported_claims": [],
                    }
            ]
        }
    )
    module = ModuleB(
        StaticClient(payload),
        _prompt(tmp_path),
        minimal_prompt_path=_minimal_prompt(tmp_path),
    )

    out = module.run(
        _grounding(),
        generation_mode="minimal_skeleton",
        model_ir=_model_ir(),
        controlled_sketch=_sketch(),
        evidence_bindings=_bindings(),
        sketch_audit_result=_pass_audit(),
    )

    assert len(out) == 1
    candidate = out[0]
    assert isinstance(candidate, TheoremSkeletonCandidate)
    assert candidate.generation_mode == "minimal_skeleton"
    assert candidate.skeleton_audit and candidate.skeleton_audit.audit_pass is True
    assert candidate.parse_ok is True
    assert candidate.generation_blocked_reason is None
    assert candidate.ignored_llm_theorem_decl
    assert candidate.lean_header.splitlines()[:2] == ["import Mathlib", "import MechLib"]
    assert candidate.lean_header.index("import MechLib.Atwood.Newton") < candidate.lean_header.index("open MechLib")
    assert "import MechLib.Atwood.Pulley" in candidate.lean_header
    assert candidate.lean_header.count("import MechLib.Atwood.Newton") == 1
    assert "import MechLib.Atwood.Rotation" not in candidate.lean_header
    assert "atwood_minimal (m1 m2 g T1 T2 R I alpha a : Real)" not in candidate.theorem_decl
    assert "(m1 m2 : Mass)" in candidate.theorem_decl
    assert "(T1 T2 : Force)" in candidate.theorem_decl
    assert "(g a : Acceleration)" in candidate.theorem_decl
    assert "alpha.val = a.val / R.val" in candidate.theorem_decl
    assert "(h_m1_pos : 0 < m1.val)" in candidate.theorem_decl
    assert "MechLib.Atwood.newton_m1 T1 m1 a" in candidate.theorem_decl
    assert candidate.verified_decls == ["MechLib.Atwood.newton_m1", "MechLib.Atwood.newton_m2"]
    assert any(step.expected_claim == "T1 - m1 * g = m1 * a" for step in candidate.proof_obligations)
    assert any(step.expected_claim == "m2 * g - T2 = m2 * a" for step in candidate.proof_obligations)
    assert any(row["step_id"] == "sk_rot" for row in candidate.gap_laws)
    assert "MechLib.Atwood.newton_m1" not in json.dumps(candidate.gap_laws)
    assert candidate.fully_mechlib_verified is False
    assert candidate.model_predicate_bindings
    assert any(row["lean_type"] == "Mass" for row in candidate.typed_binders)

    row = to_row(candidate)
    assert row["generation_mode"] == "minimal_skeleton"
    assert row["hypothesis_provenance"]
    assert row["proof_obligations"]
    assert row["verified_decls"]
    assert row["gap_laws"]
    write_jsonl(tmp_path / "statement_candidates.jsonl", [row])
    write_jsonl(tmp_path / "theorem_skeleton_candidates.jsonl", [row])
    assert json.loads((tmp_path / "theorem_skeleton_candidates.jsonl").read_text(encoding="utf-8").splitlines()[0])


def test_b_minimal_skeleton_can_skip_llm_selection(tmp_path: Path) -> None:
    client = StaticClient("not json")
    module = ModuleB(
        client,
        _prompt(tmp_path),
        minimal_prompt_path=_minimal_prompt(tmp_path),
        b_minimal_llm_enabled=False,
        b_minimal_llm_on_retry=False,
    )

    out = module.run(
        _grounding(),
        generation_mode="minimal_skeleton",
        model_ir=_model_ir(),
        controlled_sketch=_sketch(),
        evidence_bindings=_bindings(),
        sketch_audit_result=_pass_audit(),
    )

    assert client.calls == 0
    assert len(out) == 1
    assert out[0].candidate_id == "c1"
    assert out[0].generation_mode == "minimal_skeleton"
    assert out[0].theorem_decl.startswith("theorem ")


def test_b_minimal_skeleton_checked_predicate_can_enter_compile_path(tmp_path: Path) -> None:
    payload = json.dumps(
        {
            "candidates": [
                {
                    "candidate_id": "c1",
                    "theorem_name_hint": "typed_checked",
                    "theorem_decl": "theorem fake (m1 : Real) (h_bad : massless_string) : m1 = m1",
                    "selected_model_instances": ["mi_m1", "mi_m2"],
                    "controlled_sketch_steps_used": ["sk_m1", "sk_m2", "sk_alg"],
                }
            ]
        }
    )
    module = ModuleB(StaticClient(payload), _prompt(tmp_path), minimal_prompt_path=_minimal_prompt(tmp_path))

    candidate = module.run(
        _grounding(),
        generation_mode="minimal_skeleton",
        model_ir=_model_ir(),
        controlled_sketch=_sketch_without_gap(),
        evidence_bindings=_bindings(),
        sketch_audit_result=_pass_audit(),
    )[0]

    assert candidate.parse_ok is True
    assert candidate.generation_blocked_reason is None
    assert candidate.fully_mechlib_verified is True
    assert "massless_string" not in candidate.theorem_decl
    assert candidate.ignored_llm_theorem_decl
    assert "MechLib.Atwood.newton_m1 T1 m1 a" in candidate.theorem_decl
    assert candidate.assumptions == [
        "0 < m1.val",
        "0 < m2.val",
        "MechLib.Atwood.newton_m1 T1 m1 a",
        "MechLib.Atwood.newton_m2 T2 m2 a",
    ]


def test_b_minimal_skeleton_does_not_emit_unsupported_volume_type(tmp_path: Path) -> None:
    payload = json.dumps(
        {
            "candidates": [
                {
                    "candidate_id": "c1",
                    "theorem_name_hint": "volume_target",
                    "selected_model_instances": [],
                    "selected_target": {"lean": "V = 3"},
                    "controlled_sketch_steps_used": [],
                }
            ]
        }
    )
    module = ModuleB(StaticClient(payload), _prompt(tmp_path), minimal_prompt_path=_minimal_prompt(tmp_path))
    grounding = GroundingResult(
        sample_id="volume-1",
        model_id="m",
        problem_ir={"unknown_target": {"symbol": "V", "description": "volume"}},
        parse_ok=True,
        raw_response="",
        error=None,
    )
    model_ir = ModelIR(
        sample_id="volume-1",
        variables={"V": {"description": "volume of a tank"}},
        quantity_annotations=[
            QuantityTypeAnnotation(
                symbol="V",
                semantic_role="volume",
                unit_or_dimension="m^3",
                lean_type="Volume",
                confidence=0.95,
                supported=False,
                status="unsupported_si_type",
            )
        ],
        canonical_target=CanonicalTarget(
            target_kind="closed_form",
            target_variables=["V"],
            lean_formula="V = 3",
            requires_closed_form=True,
            source_text="volume target",
            confidence=0.9,
            parse_ok=True,
        ),
        target={"symbol": "V", "lean": "V = 3"},
        forbidden_as_assumption=["target V", "V = 3"],
        parse_ok=True,
    )
    sketch = ControlledSketch(sample_id="volume-1", status="ok", parse_ok=True)

    candidate = module.run(
        grounding,
        generation_mode="minimal_skeleton",
        model_ir=model_ir,
        controlled_sketch=sketch,
        evidence_bindings=[],
        sketch_audit_result=SketchAuditResult(sample_id="volume-1", audit_pass=True),
    )[0]

    assert "(V : Volume)" not in candidate.theorem_decl
    assert "(V : Real)" in candidate.theorem_decl
    assert "unsupported_si_type:V:Volume" in candidate.unsupported_claims


def test_b_minimal_skeleton_handles_function_quantity_target(tmp_path: Path) -> None:
    payload = json.dumps(
        {
            "candidates": [
                {
                    "candidate_id": "c1",
                    "theorem_name_hint": "position_function",
                    "selected_model_instances": [],
                    "controlled_sketch_steps_used": [],
                }
            ]
        }
    )
    module = ModuleB(StaticClient(payload), _prompt(tmp_path), minimal_prompt_path=_minimal_prompt(tmp_path))
    grounding = GroundingResult(
        sample_id="function-target",
        model_id="m",
        problem_ir={"unknown_target": {"symbol": "x", "description": "position function"}},
        parse_ok=True,
        raw_response="",
        error=None,
    )
    model_ir = ModelIR(
        sample_id="function-target",
        variables={"x": {}, "t": {}},
        quantity_annotations=[
            QuantityTypeAnnotation("x", semantic_role="position over time", lean_type="Time -> Length", confidence=0.95),
            QuantityTypeAnnotation("t", semantic_role="time", lean_type="Time", confidence=0.95),
        ],
        canonical_target=CanonicalTarget(
            target_kind="relation",
            target_variables=["x"],
            lean_formula="forall t : Time, (x t).val = t.val",
            source_text="position-time relation",
            confidence=0.9,
            parse_ok=True,
        ),
        target={"symbol": "x", "description": "position function"},
        forbidden_as_assumption=["target position function x"],
        parse_ok=True,
    )
    sketch = ControlledSketch(sample_id="function-target", status="ok", parse_ok=True)

    candidate = module.run(
        grounding,
        generation_mode="minimal_skeleton",
        model_ir=model_ir,
        controlled_sketch=sketch,
        evidence_bindings=[],
        sketch_audit_result=SketchAuditResult(sample_id="function-target", audit_pass=True),
    )[0]

    assert "(x : Time -> Length)" in candidate.theorem_decl
    assert "forall t.val" not in candidate.theorem_decl
    assert "(x t).val = t.val" in candidate.theorem_decl


def test_b_minimal_skeleton_normalizes_untyped_function_quantifier(tmp_path: Path) -> None:
    payload = json.dumps({"candidates": [{"candidate_id": "c1", "theorem_name_hint": "velocity_function"}]})
    module = ModuleB(StaticClient(payload), _prompt(tmp_path), minimal_prompt_path=_minimal_prompt(tmp_path))
    grounding = GroundingResult(
        sample_id="velocity-function",
        model_id="m",
        problem_ir={"unknown_target": {"symbol": "v_x", "description": "velocity function"}},
        parse_ok=True,
        raw_response="",
        error=None,
    )
    model_ir = ModelIR(
        sample_id="velocity-function",
        variables={"v_x": {}, "k": {}, "t": {}, "t_interval": {}},
        quantity_annotations=[
            QuantityTypeAnnotation("v_x", semantic_role="velocity over time", lean_type="Time -> Speed", confidence=0.95),
            QuantityTypeAnnotation("k", semantic_role="acceleration coefficient", lean_type="Acceleration", confidence=0.95),
            QuantityTypeAnnotation("t", semantic_role="time", lean_type="Time", confidence=0.95),
            QuantityTypeAnnotation("t_interval", semantic_role="time interval", lean_type="Time", confidence=0.95),
        ],
        canonical_target=CanonicalTarget(
            target_kind="relation",
            target_variables=["v_x", "t"],
            lean_formula="forall t, 0 <= t ∧ t <= t_interval -> v_x t = (2 : Real) * (k * t)",
            source_text="velocity-time relation",
            confidence=0.9,
            parse_ok=True,
        ),
        parse_ok=True,
    )

    candidate = module.run(
        grounding,
        generation_mode="minimal_skeleton",
        model_ir=model_ir,
        controlled_sketch=ControlledSketch(sample_id="velocity-function", status="ok", parse_ok=True),
        evidence_bindings=[],
        sketch_audit_result=SketchAuditResult(sample_id="velocity-function", audit_pass=True),
    )[0]

    assert candidate.parse_ok is True
    assert "(v_x : Time -> Speed)" in candidate.theorem_decl
    assert "(k : Acceleration)" in candidate.theorem_decl
    assert "forall t.val" not in candidate.theorem_decl
    assert "(v_x t.val).val" not in candidate.theorem_decl
    assert "forall t : Time" in candidate.theorem_decl
    assert "(v_x t).val = (2 : Real) * (k.val * t.val)" in candidate.theorem_decl


def test_b_minimal_skeleton_normalizes_function_evaluation_argument(tmp_path: Path) -> None:
    payload = json.dumps({"candidates": [{"candidate_id": "c1", "theorem_name_hint": "velocity_eval"}]})
    module = ModuleB(StaticClient(payload), _prompt(tmp_path), minimal_prompt_path=_minimal_prompt(tmp_path))
    grounding = GroundingResult(
        sample_id="velocity-eval",
        model_id="m",
        problem_ir={"unknown_target": {"symbol": "v_x", "description": "velocity at t_1"}},
        parse_ok=True,
        raw_response="",
        error=None,
    )
    model_ir = ModelIR(
        sample_id="velocity-eval",
        variables={"v_x": {}, "k": {}, "t_1": {}},
        quantity_annotations=[
            QuantityTypeAnnotation("v_x", semantic_role="velocity over time", lean_type="Time -> Speed", confidence=0.95),
            QuantityTypeAnnotation("k", semantic_role="acceleration coefficient", lean_type="Acceleration", confidence=0.95),
            QuantityTypeAnnotation("t_1", semantic_role="evaluation time", lean_type="Time", confidence=0.95),
        ],
        canonical_target=CanonicalTarget(
            target_kind="relation",
            target_variables=["v_x"],
            lean_formula="v_x t_1 = k * t_1",
            source_text="velocity evaluation",
            confidence=0.9,
            parse_ok=True,
        ),
        parse_ok=True,
    )

    candidate = module.run(
        grounding,
        generation_mode="minimal_skeleton",
        model_ir=model_ir,
        controlled_sketch=ControlledSketch(sample_id="velocity-eval", status="ok", parse_ok=True),
        evidence_bindings=[],
        sketch_audit_result=SketchAuditResult(sample_id="velocity-eval", audit_pass=True),
    )[0]

    assert candidate.parse_ok is True
    assert "(v_x t_1).val = k.val * t_1.val" in candidate.theorem_decl
    assert "(v_x t_1.val).val" not in candidate.theorem_decl


def test_b_minimal_skeleton_rewrites_function_lambda_equalities_to_pointwise_relations(tmp_path: Path) -> None:
    payload = json.dumps({"candidates": [{"candidate_id": "c1", "theorem_name_hint": "pointwise_function"}]})
    module = ModuleB(StaticClient(payload), _prompt(tmp_path), minimal_prompt_path=_minimal_prompt(tmp_path))
    grounding = GroundingResult(
        sample_id="pointwise-function",
        model_id="m",
        problem_ir={"unknown_target": {"symbol": "xA", "description": "position function"}},
        parse_ok=True,
        raw_response="",
        error=None,
    )
    model_ir = ModelIR(
        sample_id="pointwise-function",
        variables={"xA": {}, "yA": {}, "v_f": {}, "t": {}},
        quantity_annotations=[
            QuantityTypeAnnotation("xA", semantic_role="x position over time", lean_type="Time -> Length", confidence=0.95),
            QuantityTypeAnnotation("yA", semantic_role="y position over time", lean_type="Time -> Length", confidence=0.95),
            QuantityTypeAnnotation("v_f", semantic_role="vertical speed", lean_type="Speed", confidence=0.95),
            QuantityTypeAnnotation("t", semantic_role="time", lean_type="Time", confidence=0.95),
        ],
        givens=[
            HypothesisProvenance(
                name="aircraft_position",
                lean="xA = fun t => 0 ∧ yA = fun t => v_f * t",
                role="problem_fact",
                source_type="problem_ir",
                allowed_in_hypotheses=True,
            )
        ],
        canonical_target=CanonicalTarget(
            target_kind="relation",
            target_variables=["yA"],
            lean_formula="forall t, yA t = v_f * t",
            source_text="position-time relation",
            confidence=0.9,
            parse_ok=True,
        ),
        parse_ok=True,
    )

    candidate = module.run(
        grounding,
        generation_mode="minimal_skeleton",
        model_ir=model_ir,
        controlled_sketch=ControlledSketch(sample_id="pointwise-function", status="ok", parse_ok=True),
        evidence_bindings=[],
        sketch_audit_result=SketchAuditResult(sample_id="pointwise-function", audit_pass=True),
    )[0]

    assert candidate.parse_ok is True
    assert "= fun" not in candidate.theorem_decl
    assert "(forall t : Time, (xA t).val = 0)" in candidate.theorem_decl
    assert "(forall t : Time, (yA t).val = v_f.val * t.val)" in candidate.theorem_decl


def test_b_minimal_skeleton_conjoins_secondary_canonical_targets(tmp_path: Path) -> None:
    payload = json.dumps({"candidates": [{"candidate_id": "c1", "theorem_name_hint": "multi_target"}]})
    module = ModuleB(StaticClient(payload), _prompt(tmp_path), minimal_prompt_path=_minimal_prompt(tmp_path))
    grounding = GroundingResult(
        sample_id="multi-target",
        model_id="m",
        problem_ir={"unknown_target": {"symbol": "x", "description": "motion and arrival time"}},
        parse_ok=True,
        raw_response="",
        error=None,
    )
    model_ir = ModelIR(
        sample_id="multi-target",
        variables={"x": {}, "v": {}, "t_star": {}, "L": {}},
        quantity_annotations=[
            QuantityTypeAnnotation("x", semantic_role="position over time", lean_type="Time -> Length", confidence=0.95),
            QuantityTypeAnnotation("v", semantic_role="speed", lean_type="Speed", confidence=0.95),
            QuantityTypeAnnotation("t_star", semantic_role="arrival time", lean_type="Time", confidence=0.95),
            QuantityTypeAnnotation("L", semantic_role="distance", lean_type="Length", confidence=0.95),
        ],
        canonical_target=CanonicalTarget(
            target_kind="component_relation",
            target_variables=["x", "t_star"],
            lean_formula="forall t, x t = v * t",
            secondary_formulas=["t_star = L / v"],
            source_text="find motion and arrival time",
            confidence=0.9,
            parse_ok=True,
        ),
        parse_ok=True,
    )

    candidate = module.run(
        grounding,
        generation_mode="minimal_skeleton",
        model_ir=model_ir,
        controlled_sketch=ControlledSketch(sample_id="multi-target", status="ok", parse_ok=True),
        evidence_bindings=[],
        sketch_audit_result=SketchAuditResult(sample_id="multi-target", audit_pass=True),
    )[0]

    assert candidate.parse_ok is True
    assert "forall t : Time, (x t).val = v.val * t.val" in candidate.theorem_decl
    assert "t_star.val = L.val / v.val" in candidate.theorem_decl
    assert " ∧" in candidate.theorem_decl


def test_b_minimal_skeleton_uses_function_formula_ir_for_pointwise_target(tmp_path: Path) -> None:
    payload = json.dumps({"candidates": [{"candidate_id": "c1", "theorem_name_hint": "function_ir"}]})
    module = ModuleB(StaticClient(payload), _prompt(tmp_path), minimal_prompt_path=_minimal_prompt(tmp_path))
    grounding = GroundingResult(
        sample_id="function-ir",
        model_id="m",
        problem_ir={"unknown_target": {"symbol": "x", "description": "position function"}},
        parse_ok=True,
        raw_response="",
        error=None,
    )
    model_ir = ModelIR(
        sample_id="function-ir",
        variables={"x": {}, "v": {}},
        quantity_annotations=[
            QuantityTypeAnnotation("x", semantic_role="position over time", lean_type="Time -> Length", confidence=0.95),
            QuantityTypeAnnotation("v", semantic_role="speed", lean_type="Speed", confidence=0.95),
        ],
        canonical_target=CanonicalTarget(
            target_kind="relation",
            target_variables=["x"],
            lean_formula="unused fallback formula",
            function_formula_ir=[
                FunctionFormulaIR(
                    formula_id="motion_relation",
                    formula_kind="pointwise_relation",
                    bound_variables=[{"name": "t", "lean_type": "Time"}],
                    lhs="x t",
                    relation="=",
                    rhs="v * t",
                    parse_ok=True,
                )
            ],
            source_text="find x(t)",
            confidence=0.9,
            parse_ok=True,
        ),
        parse_ok=True,
    )

    candidate = module.run(
        grounding,
        generation_mode="minimal_skeleton",
        model_ir=model_ir,
        controlled_sketch=ControlledSketch(sample_id="function-ir", status="ok", parse_ok=True),
        evidence_bindings=[],
        sketch_audit_result=SketchAuditResult(sample_id="function-ir", audit_pass=True),
    )[0]

    assert candidate.parse_ok is True
    assert "forall t : Time, (x t).val = v.val * t.val" in candidate.theorem_decl
    assert "unused fallback formula" not in candidate.theorem_decl


def test_b_minimal_skeleton_blocks_invalid_function_formula_ir(tmp_path: Path) -> None:
    payload = json.dumps({"candidates": [{"candidate_id": "c1", "theorem_name_hint": "bad_function_ir"}]})
    module = ModuleB(StaticClient(payload), _prompt(tmp_path), minimal_prompt_path=_minimal_prompt(tmp_path))
    grounding = GroundingResult(
        sample_id="bad-function-ir",
        model_id="m",
        problem_ir={"unknown_target": {"symbol": "x", "description": "position function"}},
        parse_ok=True,
        raw_response="",
        error=None,
    )
    model_ir = ModelIR(
        sample_id="bad-function-ir",
        variables={"x": {}},
        quantity_annotations=[
            QuantityTypeAnnotation("x", semantic_role="position over time", lean_type="Time -> Length", confidence=0.95)
        ],
        canonical_target=CanonicalTarget(
            target_kind="relation",
            target_variables=["x"],
            lean_formula="forall t, x t = x t",
            function_formula_ir=[
                FunctionFormulaIR(
                    formula_id="bad_motion",
                    formula_kind="pointwise_relation",
                    bound_variables=[{"name": "t", "lean_type": "Time"}],
                    lhs="x t",
                    relation="=",
                    rhs="x t",
                    parse_ok=False,
                    error="tautological_function_formula",
                )
            ],
            source_text="find x(t)",
            confidence=0.9,
            parse_ok=True,
        ),
        parse_ok=True,
    )

    candidate = module.run(
        grounding,
        generation_mode="minimal_skeleton",
        model_ir=model_ir,
        controlled_sketch=ControlledSketch(sample_id="bad-function-ir", status="ok", parse_ok=True),
        evidence_bindings=[],
        sketch_audit_result=SketchAuditResult(sample_id="bad-function-ir", audit_pass=True),
    )[0]

    assert candidate.parse_ok is False
    assert candidate.generation_blocked_reason == "tautological_function_formula"


def test_b_minimal_skeleton_blocks_tautological_function_target(tmp_path: Path) -> None:
    payload = json.dumps({"candidates": [{"candidate_id": "c1", "theorem_name_hint": "bad_function_target"}]})
    module = ModuleB(StaticClient(payload), _prompt(tmp_path), minimal_prompt_path=_minimal_prompt(tmp_path))
    grounding = GroundingResult(
        sample_id="tautology-target",
        model_id="m",
        problem_ir={"unknown_target": {"symbol": "v_x", "description": "velocity relation"}},
        parse_ok=True,
        raw_response="",
        error=None,
    )
    model_ir = ModelIR(
        sample_id="tautology-target",
        variables={"v_x": {}, "t": {}},
        quantity_annotations=[
            QuantityTypeAnnotation("v_x", semantic_role="velocity over time", lean_type="Time -> Speed", confidence=0.95),
            QuantityTypeAnnotation("t", semantic_role="time", lean_type="Time", confidence=0.95),
        ],
        canonical_target=CanonicalTarget(
            target_kind="relation",
            target_variables=["v_x"],
            lean_formula="forall t, v_x t = v_x t",
            source_text="velocity relation",
            confidence=0.9,
            parse_ok=True,
        ),
        parse_ok=True,
    )

    candidate = module.run(
        grounding,
        generation_mode="minimal_skeleton",
        model_ir=model_ir,
        controlled_sketch=ControlledSketch(sample_id="tautology-target", status="ok", parse_ok=True),
        evidence_bindings=[],
        sketch_audit_result=SketchAuditResult(sample_id="tautology-target", audit_pass=True),
    )[0]

    assert candidate.parse_ok is False
    assert candidate.generation_blocked_reason == "tautological_canonical_target"
    assert "generation_blocked:tautological_canonical_target" in candidate.unsupported_claims


def test_b_minimal_skeleton_cleans_numeric_quantity_casts_and_trailing_periods(tmp_path: Path) -> None:
    payload = json.dumps({"candidates": [{"candidate_id": "c1", "theorem_name_hint": "clean_formula"}]})
    module = ModuleB(StaticClient(payload), _prompt(tmp_path), minimal_prompt_path=_minimal_prompt(tmp_path))
    grounding = GroundingResult(
        sample_id="clean-formula",
        model_id="m",
        problem_ir={"unknown_target": {"symbol": "d", "description": "distance"}},
        parse_ok=True,
        raw_response="",
        error=None,
    )
    model_ir = ModelIR(
        sample_id="clean-formula",
        variables={"d": {}},
        quantity_annotations=[QuantityTypeAnnotation("d", semantic_role="distance", lean_type="Length", confidence=0.95)],
        givens=[
            HypothesisProvenance(
                name="h_d",
                lean="d = ((1 : Real) : Length).",
                role="problem_fact",
                source_type="problem_ir",
                allowed_in_hypotheses=True,
            )
        ],
        canonical_target=CanonicalTarget(
            target_kind="relation",
            target_variables=["d"],
            lean_formula="d = ((1 : Real) : Length).",
            source_text="distance is one",
            confidence=0.9,
            parse_ok=True,
        ),
        target={"symbol": "d", "description": "distance"},
        forbidden_as_assumption=["target distance d"],
        parse_ok=True,
    )

    candidate = module.run(
        grounding,
        generation_mode="minimal_skeleton",
        model_ir=model_ir,
        controlled_sketch=ControlledSketch(sample_id="clean-formula", status="ok", parse_ok=True),
        evidence_bindings=[],
        sketch_audit_result=SketchAuditResult(sample_id="clean-formula", audit_pass=True),
    )[0]

    assert "((1 : Real) : Length)" not in candidate.theorem_decl
    assert "d.val = 1" in candidate.theorem_decl


def test_b_minimal_skeleton_cleans_simple_numeric_quantity_casts(tmp_path: Path) -> None:
    payload = json.dumps({"candidates": [{"candidate_id": "c1", "theorem_name_hint": "clean_simple_cast"}]})
    module = ModuleB(StaticClient(payload), _prompt(tmp_path), minimal_prompt_path=_minimal_prompt(tmp_path))
    grounding = GroundingResult(
        sample_id="clean-simple-cast",
        model_id="m",
        problem_ir={"unknown_target": {"symbol": "x_c0", "description": "initial position"}},
        parse_ok=True,
        raw_response="",
        error=None,
    )
    model_ir = ModelIR(
        sample_id="clean-simple-cast",
        variables={"x_c0": {}},
        quantity_annotations=[QuantityTypeAnnotation("x_c0", semantic_role="position", lean_type="Length", confidence=0.95)],
        givens=[
            HypothesisProvenance(
                name="given_initial_position",
                lean="x_c0 = (20 : Length)",
                role="problem_fact",
                source_type="problem_ir",
                allowed_in_hypotheses=True,
            )
        ],
        canonical_target=CanonicalTarget(
            target_kind="relation",
            target_variables=["x_c0"],
            lean_formula="x_c0 = (20 : Length)",
            source_text="initial position is 20 m",
            confidence=0.9,
            parse_ok=True,
        ),
        parse_ok=True,
    )

    candidate = module.run(
        grounding,
        generation_mode="minimal_skeleton",
        model_ir=model_ir,
        controlled_sketch=ControlledSketch(sample_id="clean-simple-cast", status="ok", parse_ok=True),
        evidence_bindings=[],
        sketch_audit_result=SketchAuditResult(sample_id="clean-simple-cast", audit_pass=True),
    )[0]

    assert "(20 : Length)" not in candidate.theorem_decl
    assert "x_c0.val = 20" in candidate.theorem_decl


def test_b_minimal_skeleton_does_not_guess_target_formal_targets_list(tmp_path: Path) -> None:
    payload = json.dumps(
        {
            "candidates": [
                {
                    "candidate_id": "c1",
                    "theorem_name_hint": "target_list",
                    "selected_model_instances": [],
                    "controlled_sketch_steps_used": [],
                }
            ]
        }
    )
    module = ModuleB(StaticClient(payload), _prompt(tmp_path), minimal_prompt_path=_minimal_prompt(tmp_path))
    grounding = GroundingResult(
        sample_id="target-list",
        model_id="m",
        problem_ir={"unknown_target": {"symbol": "a", "description": "acceleration and tension"}},
        parse_ok=True,
        raw_response="",
        error=None,
    )
    model_ir = ModelIR(
        sample_id="target-list",
        variables={"m1": {}, "m2": {}, "g": {}, "a": {}, "T": {}},
        quantity_annotations=[
            QuantityTypeAnnotation("m1", semantic_role="mass", lean_type="Mass", confidence=0.95),
            QuantityTypeAnnotation("m2", semantic_role="mass", lean_type="Mass", confidence=0.95),
            QuantityTypeAnnotation("g", semantic_role="gravity", lean_type="Acceleration", confidence=0.95),
            QuantityTypeAnnotation("a", semantic_role="acceleration", lean_type="Acceleration", confidence=0.95),
            QuantityTypeAnnotation("T", semantic_role="tension", lean_type="Force", confidence=0.95),
        ],
        target={
            "formal_targets": [
                "a = (m2 * g) / (m1 + m2)",
                "T = (m1 * m2 * g) / (m1 + m2)",
            ]
        },
        forbidden_as_assumption=[
            "a = (m2 * g) / (m1 + m2)",
            "T = (m1 * m2 * g) / (m1 + m2)",
        ],
        parse_ok=True,
    )
    sketch = ControlledSketch(sample_id="target-list", status="ok", parse_ok=True)

    candidate = module.run(
        grounding,
        generation_mode="minimal_skeleton",
        model_ir=model_ir,
        controlled_sketch=sketch,
        evidence_bindings=[],
        sketch_audit_result=SketchAuditResult(sample_id="target-list", audit_pass=True),
    )[0]

    assert candidate.generation_blocked_reason == "missing_canonical_target"
    assert "a.val = (m2.val * g.val) / (m1.val + m2.val)" not in candidate.theorem_decl
    assert "T.val = (m1.val * m2.val * g.val) / (m1.val + m2.val)" not in candidate.theorem_decl


def test_b_minimal_skeleton_emits_one_candidate_even_if_llm_returns_two(tmp_path: Path) -> None:
    payload = json.dumps(
        {
            "candidates": [
                {
                    "candidate_id": "c1",
                    "theorem_name_hint": "typed_one",
                    "selected_model_instances": ["mi_m1", "mi_m2"],
                    "controlled_sketch_steps_used": ["sk_m1", "sk_m2", "sk_alg"],
                },
                {
                    "candidate_id": "c2",
                    "theorem_name_hint": "typed_two",
                    "selected_model_instances": ["mi_m1", "mi_m2"],
                    "controlled_sketch_steps_used": ["sk_m1", "sk_m2", "sk_alg"],
                },
            ]
        }
    )
    module = ModuleB(StaticClient(payload), _prompt(tmp_path), minimal_prompt_path=_minimal_prompt(tmp_path))

    out = module.run(
        _grounding(),
        generation_mode="minimal_skeleton",
        model_ir=_model_ir(),
        controlled_sketch=_sketch_without_gap(),
        evidence_bindings=_bindings(),
        sketch_audit_result=_pass_audit(),
    )

    assert [candidate.candidate_id for candidate in out] == ["c1"]
    assert "candidate_count_above_requested_truncated" in out[0].unsupported_claims


def test_b_minimal_skeleton_emits_one_candidate_even_if_llm_returns_many(tmp_path: Path) -> None:
    payload = json.dumps(
        {
            "candidates": [
                {
                    "candidate_id": f"c{i}",
                    "theorem_name_hint": f"typed_{i}",
                    "selected_model_instances": ["mi_m1", "mi_m2"],
                    "controlled_sketch_steps_used": ["sk_m1", "sk_m2", "sk_alg"],
                }
                for i in range(1, 6)
            ]
        }
    )
    module = ModuleB(StaticClient(payload), _prompt(tmp_path), minimal_prompt_path=_minimal_prompt(tmp_path))

    out = module.run(
        _grounding(),
        generation_mode="minimal_skeleton",
        model_ir=_model_ir(),
        controlled_sketch=_sketch_without_gap(),
        evidence_bindings=_bindings(),
        sketch_audit_result=_pass_audit(),
    )

    assert [candidate.candidate_id for candidate in out] == ["c1"]
    assert "candidate_count_above_requested_truncated" in out[0].unsupported_claims


def test_b_minimal_skeleton_selects_explicit_gap_variant_when_available(tmp_path: Path) -> None:
    sketch = _sketch()
    sketch.sketch_variants = [
        SketchVariant(
            variant_id="v1_verified_only",
            variant_policy="verified_only",
            target_form_policy="algebra_obligation",
            gap_policy="block",
            proof_steps=list(sketch.proof_steps),
            algebra_obligation=sketch.algebra_obligation,
            blocked_law_steps=list(sketch.blocked_law_steps),
        ),
        SketchVariant(
            variant_id="v2_explicit_gap_allowed",
            variant_policy="explicit_gap_allowed",
            target_form_policy="algebra_obligation",
            gap_policy="explicit_gap_law",
            proof_steps=list(sketch.proof_steps),
            algebra_obligation=sketch.algebra_obligation,
            blocked_law_steps=list(sketch.blocked_law_steps),
        ),
        SketchVariant(
            variant_id="v3_implicit_relation",
            variant_policy="implicit_relation",
            target_form_policy="proof_obligation_conjunction",
            gap_policy="block",
            proof_steps=list(sketch.proof_steps),
            algebra_obligation=None,
            blocked_law_steps=list(sketch.blocked_law_steps),
        ),
        SketchVariant(
            variant_id="v4_compile_oriented",
            variant_policy="compile_oriented",
            target_form_policy="model_target_then_forbidden",
            gap_policy="block",
            proof_steps=sketch.proof_steps[:1],
            algebra_obligation=None,
            blocked_law_steps=list(sketch.blocked_law_steps),
            repair_directives=["compile_oriented"],
        ),
    ]
    payload = json.dumps(
        {
            "candidates": [
                {
                    "candidate_id": "c1",
                    "variant_id": "v1_verified_only",
                    "theorem_name_hint": "llm_selection",
                    "selected_model_instances": ["mi_m1", "mi_m2"],
                    "controlled_sketch_steps_used": ["sk_m1", "sk_m2", "sk_alg"],
                }
            ]
        }
    )
    module = ModuleB(StaticClient(payload), _prompt(tmp_path), minimal_prompt_path=_minimal_prompt(tmp_path))

    out = module.run(
        _grounding(),
        generation_mode="minimal_skeleton",
        model_ir=_model_ir(),
        controlled_sketch=sketch,
        evidence_bindings=_bindings(),
        sketch_audit_result=_pass_audit(),
    )

    assert len(out) == 1
    candidate = out[0]
    assert candidate.variant_id == "v2_explicit_gap_allowed"
    assert candidate.gap_policy == "explicit_gap_law"
    assert candidate.explicit_model_gaps
    assert candidate.target_form_policy == "algebra_obligation"
