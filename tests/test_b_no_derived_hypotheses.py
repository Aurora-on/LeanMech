from __future__ import annotations

import json
from pathlib import Path

from mech_pipeline.model.base import ModelClient
from mech_pipeline.modules.B_statement_gen import ModuleB
from mech_pipeline.types import (
    AlgebraObligation,
    CanonicalTarget,
    ControlledSketch,
    ControlledSketchStep,
    EvidenceBinding,
    GroundingResult,
    HypothesisProvenance,
    ModelIR,
    ModelInstance,
    ModelInterfaceInstantiation,
    ModelResponse,
    QuantityTypeAnnotation,
    SketchAuditResult,
)


class StaticClient(ModelClient):
    def __init__(self, payload: str) -> None:
        self.model_id = "static-b-no-derived"
        self.supports_vision = False
        self.payload = payload

    def generate_text(self, prompt: str, **kwargs) -> ModelResponse:
        _ = (prompt, kwargs)
        return ModelResponse(text=self.payload)

    def generate_multimodal(self, prompt: str, images_b64: list[str], **kwargs) -> ModelResponse:
        _ = images_b64
        return self.generate_text(prompt, **kwargs)


def _prompt(tmp_path: Path, name: str) -> Path:
    path = tmp_path / name
    path.write_text(
        "__TASK_B_GENERATE_MINIMAL_SKELETON__" if "minimal" in name else "__TASK_B_GENERATE_STATEMENTS__",
        encoding="utf-8",
    )
    return path


def _grounding() -> GroundingResult:
    return GroundingResult(
        sample_id="airtrack",
        model_id="m",
        problem_ir={
            "unknown_target": {"symbol": "a", "description": "acceleration and tension"},
            "candidate_answer": "a = m2 * g / (m1 + m2)",
        },
        parse_ok=True,
        raw_response="",
        error=None,
    )


def _model_ir(*, include_qualitative: bool = True) -> ModelIR:
    givens = [
        HypothesisProvenance(
            name="hm1",
            lean="0 < m1",
            role="problem_fact",
            source_type="problem_ir",
            allowed_in_hypotheses=True,
        ),
        HypothesisProvenance(
            name="hm2",
            lean="0 < m2",
            role="problem_fact",
            source_type="problem_ir",
            allowed_in_hypotheses=True,
        ),
    ]
    if include_qualitative:
        givens.extend(
            [
                HypothesisProvenance(
                    name="h_track_level_and_frictionless",
                    lean="track_is_level ∧ frictionless_track",
                    role="problem_fact",
                    source_type="problem_ir",
                    allowed_in_hypotheses=True,
                ),
                HypothesisProvenance(
                    name="h_string_light",
                    lean="massless_string",
                    role="problem_fact",
                    source_type="problem_ir",
                    allowed_in_hypotheses=True,
                ),
                HypothesisProvenance(
                    name="h_string_flexible",
                    lean="flexible_string",
                    role="problem_fact",
                    source_type="problem_ir",
                    allowed_in_hypotheses=True,
                ),
            ]
        )
    return ModelIR(
        sample_id="airtrack",
        variables={
            "m1": {"type": "mass"},
            "m2": {"type": "mass"},
            "g": {"type": "acceleration"},
            "a": {"type": "acceleration"},
            "T": {"type": "force"},
        },
        quantity_annotations=[
            QuantityTypeAnnotation("m1", semantic_role="mass", lean_type="Mass", confidence=0.95),
            QuantityTypeAnnotation("m2", semantic_role="mass", lean_type="Mass", confidence=0.95),
            QuantityTypeAnnotation("g", semantic_role="gravity", lean_type="Acceleration", confidence=0.95),
            QuantityTypeAnnotation("a", semantic_role="acceleration", lean_type="Acceleration", confidence=0.95),
            QuantityTypeAnnotation("T", semantic_role="tension force", lean_type="Force", confidence=0.95),
        ],
        canonical_target=CanonicalTarget(
            target_kind="closed_form",
            target_variables=["a"],
            lean_formula="a = (m2 * g) / (m1 + m2)",
            requires_closed_form=True,
            source_text="acceleration target",
            confidence=0.9,
            parse_ok=True,
        ),
        givens=givens,
        model_instances=[
            ModelInstance(
                instance_id="glider",
                kind="newton_second_law_1d",
                natural_language="Newton law for glider.",
                variables={"force": "T", "mass": "m1", "acceleration": "a"},
                planning_schema_id="law.newton.second.1d",
                expected_claim="T = m1 * a",
            ),
            ModelInstance(
                instance_id="hanger",
                kind="newton_second_law_1d",
                natural_language="Newton law for hanging mass.",
                variables={"force": "T", "mass": "m2", "acceleration": "a"},
                planning_schema_id="law.newton.second.1d",
                expected_claim="m2 * g - T = m2 * a",
            ),
        ],
        target={
            "symbol": "a",
            "description": "acceleration",
        },
        forbidden_as_assumption=["target a", "a = m2 * g / (m1 + m2)"],
        parse_ok=True,
    )


def _model_ir_with_interface_gaps() -> ModelIR:
    return ModelIR(
        sample_id="airtrack",
        variables={
            "m1": {"type": "mass"},
            "m2": {"type": "mass"},
            "g": {"type": "acceleration"},
            "a": {"type": "acceleration"},
            "T": {"type": "force"},
        },
        quantity_annotations=[
            QuantityTypeAnnotation("m1", semantic_role="mass", lean_type="Mass", confidence=0.95),
            QuantityTypeAnnotation("m2", semantic_role="mass", lean_type="Mass", confidence=0.95),
            QuantityTypeAnnotation("g", semantic_role="gravity", lean_type="Acceleration", confidence=0.95),
            QuantityTypeAnnotation("a", semantic_role="acceleration", lean_type="Acceleration", confidence=0.95),
            QuantityTypeAnnotation("T", semantic_role="tension force", lean_type="Force", confidence=0.95),
        ],
        canonical_target=CanonicalTarget(
            target_kind="closed_form",
            target_variables=["a"],
            lean_formula="a = (m2 * g) / (m1 + m2)",
            requires_closed_form=True,
            source_text="acceleration target",
            confidence=0.9,
            parse_ok=True,
        ),
        model_instances=[
            ModelInstance(
                instance_id="glider",
                kind="newton_second_law_1d",
                natural_language="Newton law for glider with net force interface.",
                variables={"net_force": "Fnet1", "mass": "m1", "acceleration": "a"},
                planning_schema_id="law.newton.second.1d",
                expected_claim="Fnet1 = m1 * a",
                interface_instantiations=[
                    ModelInterfaceInstantiation(
                        instantiation_id="glider_net_force",
                        kind="net_force_balance",
                        formal_claim="Fnet1 = T",
                        source_model_instance="glider",
                        interface_name="net_force",
                        introduced_variable={"name": "Fnet1", "lean_type": "Force"},
                        binding_status="explicit_model_gap",
                        proof_fact_allowed=False,
                    )
                ],
            ),
            ModelInstance(
                instance_id="hanger",
                kind="newton_second_law_1d",
                natural_language="Newton law for hanging mass with net force interface.",
                variables={"net_force": "Fnet2", "mass": "m2", "acceleration": "a"},
                planning_schema_id="law.newton.second.1d",
                expected_claim="Fnet2 = m2 * a",
                interface_instantiations=[
                    ModelInterfaceInstantiation(
                        instantiation_id="hanger_net_force",
                        kind="net_force_balance",
                        formal_claim="Fnet2 = m2 * g - T",
                        source_model_instance="hanger",
                        interface_name="net_force",
                        introduced_variable={"name": "Fnet2", "lean_type": "Force"},
                        binding_status="explicit_model_gap",
                        proof_fact_allowed=False,
                    )
                ],
            ),
        ],
        target={
            "symbol": "a",
            "description": "acceleration",
            "lean": "a = (m2 * g) / (m1 + m2)",
        },
        forbidden_as_assumption=["target a", "a = m2 * g / (m1 + m2)"],
        parse_ok=True,
    )


def _sketch() -> ControlledSketch:
    return ControlledSketch(
        sample_id="airtrack",
        status="ok",
        proof_steps=[
            ControlledSketchStep(
                step_id="sk_glider",
                kind="law_to_equation",
                claim="glider law",
                formal_claim="T = m1 * a",
                source_model_instance="glider",
                planning_schema="law.newton.second.1d",
                verified_decl="MechLib.Test.Newton1D",
                binding_status="ok",
                expected_claim="T = m1 * a",
                proof_fact_allowed=True,
            ),
            ControlledSketchStep(
                step_id="sk_hanger",
                kind="law_to_equation",
                claim="hanger law",
                formal_claim="m2 * g - T = m2 * a",
                source_model_instance="hanger",
                planning_schema="law.newton.second.1d",
                verified_decl="MechLib.Test.Newton1D",
                binding_status="ok",
                expected_claim="m2 * g - T = m2 * a",
                proof_fact_allowed=True,
            ),
        ],
        algebra_obligation=AlgebraObligation(
            obligation_id="alg_target",
            claim="solve target",
            formal_claim="a = (m2 * g) / (m1 + m2)",
            required_equations=["sk_glider", "sk_hanger"],
            target_variables=["a"],
        ),
        parse_ok=True,
    )


def _predicate_bindings() -> list[EvidenceBinding]:
    return [
        EvidenceBinding(
            binding_id="b_glider",
            model_instance_id="glider",
            verified_decl="MechLib.Test.Newton1D",
            decl_statement="def Newton1D (F : Force) (m : Mass) (a : Acceleration) : Prop",
            callable_by_llm=True,
            lean_check_pass=True,
            proof_fact_allowed=True,
            binding_status="ok",
            expected_claim="T = m1 * a",
        ),
        EvidenceBinding(
            binding_id="b_hanger",
            model_instance_id="hanger",
            verified_decl="MechLib.Test.Newton1D",
            decl_statement="def Newton1D (F : Force) (m : Mass) (a : Acceleration) : Prop",
            callable_by_llm=True,
            lean_check_pass=True,
            proof_fact_allowed=True,
            binding_status="ok",
            expected_claim="m2 * g - T = m2 * a",
        ),
    ]


def _theorem_only_bindings() -> list[EvidenceBinding]:
    return [
        EvidenceBinding(
            binding_id="b_glider",
            model_instance_id="glider",
            verified_decl="MechLib.Test.newton_second_law",
            decl_statement="theorem newton_second_law (m : Mass) (a : Acceleration) : F_of m a = m * a",
            callable_by_llm=True,
            lean_check_pass=True,
            proof_fact_allowed=True,
            binding_status="ok",
            expected_claim="T = m1 * a",
        )
    ]


def _run(
    tmp_path: Path,
    payload: dict[str, object],
    bindings: list[EvidenceBinding] | None = None,
    model_ir: ModelIR | None = None,
):
    module = ModuleB(
        StaticClient(json.dumps(payload)),
        _prompt(tmp_path, "B_generate_statements.txt"),
        minimal_prompt_path=_prompt(tmp_path, "B_generate_minimal_skeleton.txt"),
    )
    return module.run(
        _grounding(),
        generation_mode="minimal_skeleton",
        model_ir=model_ir or _model_ir(),
        controlled_sketch=_sketch(),
        evidence_bindings=bindings if bindings is not None else _predicate_bindings(),
        sketch_audit_result=SketchAuditResult(sample_id="airtrack", audit_pass=True),
    )[0]


def test_llm_theorem_decl_is_ignored_and_qualitative_binders_are_excluded(tmp_path: Path) -> None:
    candidate = _run(
        tmp_path,
        {
            "candidates": [
                {
                    "candidate_id": "c1",
                    "theorem_name_hint": "airtrack",
                    "theorem_decl": (
                        "theorem fake (m1 m2 g a T : Real) "
                        "(h_track_level_and_frictionless : track_is_level ∧ frictionless_track) "
                        "(h_string_light : massless_string) : a = a"
                    ),
                    "selected_model_instances": ["glider", "hanger"],
                    "controlled_sketch_steps_used": ["sk_glider", "sk_hanger", "alg_target"],
                }
            ]
        },
    )

    assert candidate.ignored_llm_theorem_decl
    assert "track_is_level" not in candidate.theorem_decl
    assert "frictionless_track" not in candidate.theorem_decl
    assert "massless_string" not in candidate.theorem_decl
    assert {row["name"] for row in candidate.excluded_hypotheses} >= {
        "h_track_level_and_frictionless",
        "h_string_light",
        "h_string_flexible",
    }
    assert "(m1 m2 : Mass)" in candidate.theorem_decl
    assert "(T : Force)" in candidate.theorem_decl
    assert "(g a : Acceleration)" in candidate.theorem_decl
    assert "a.val = (m2.val * g.val) / (m1.val + m2.val)" in candidate.theorem_decl
    assert "MechLib.Test.Newton1D T m1 a" in candidate.theorem_decl
    assert candidate.parse_ok is True


def test_explicit_model_interface_gaps_preserve_typed_force_modeling(tmp_path: Path) -> None:
    candidate = _run(
        tmp_path,
        {
            "candidates": [
                {
                    "candidate_id": "c1",
                    "theorem_name_hint": "airtrack_typed_interfaces",
                    "selected_model_instances": ["glider", "hanger"],
                    "controlled_sketch_steps_used": ["sk_glider", "sk_hanger", "alg_target"],
                }
            ]
        },
        model_ir=_model_ir_with_interface_gaps(),
    )

    assert candidate.parse_ok is True
    assert candidate.generation_blocked_reason is None
    assert candidate.grounding_status == "partial_mechlib_with_model_gaps"
    assert "Fnet1" in candidate.theorem_decl and "Fnet2" in candidate.theorem_decl and ": Force)" in candidate.theorem_decl
    assert "(m1 m2 : Mass)" in candidate.theorem_decl
    assert "(g a : Acceleration)" in candidate.theorem_decl
    assert "MechLib.Test.Newton1D Fnet1 m1 a" in candidate.theorem_decl
    assert "MechLib.Test.Newton1D Fnet2 m2 a" in candidate.theorem_decl
    assert "(h_glider_net_force : Fnet1.val = T.val)" in candidate.theorem_decl
    assert "(h_hanger_net_force : Fnet2.val = m2.val * g.val - T.val)" in candidate.theorem_decl
    assert "a.val = (m2.val * g.val) / (m1.val + m2.val)" in candidate.theorem_decl
    assert candidate.fully_mechlib_verified is False
    assert candidate.explicit_model_gaps
    assert all(row.get("proof_fact_allowed") is False for row in candidate.explicit_model_gaps)


def test_common_acceleration_constraint_is_allowed_as_modeling_fact(tmp_path: Path) -> None:
    model_ir = _model_ir(include_qualitative=False)
    model_ir.variables.update({"a1": {"type": "acceleration"}, "a2": {"type": "acceleration"}})
    model_ir.quantity_annotations.extend(
        [
            QuantityTypeAnnotation("a1", semantic_role="glider acceleration", lean_type="Acceleration", confidence=0.95),
            QuantityTypeAnnotation("a2", semantic_role="hanger acceleration", lean_type="Acceleration", confidence=0.95),
        ]
    )
    model_ir.givens.append(
        HypothesisProvenance(
            name="same_acceleration_magnitude",
            lean="a1 = a ∧ a2 = a",
            role="problem_fact",
            source_type="problem_ir",
            source_id="constraints_4",
            allowed_in_hypotheses=True,
            notes="Both bodies share the same acceleration magnitude from the string constraint.",
        )
    )
    model_ir.local_definitions.append(
        HypothesisProvenance(
            name="common_acceleration_definition",
            lean="a1 = a ∧ a2 = a",
            role="local_definition",
            source_type="problem_ir",
            source_id="relations_1",
            allowed_in_hypotheses=True,
            notes="Defines the common acceleration magnitude variable a.",
        )
    )
    model_ir.model_instances.append(
        ModelInstance(
            instance_id="string_constraint",
            kind="nonstretching_string_constraint",
            natural_language="The string imposes a shared acceleration magnitude.",
            variables={"acceleration_1": "a1", "acceleration_2": "a2", "common_acceleration": "a"},
            planning_schema_id="problem.systems.atwood_constraint_modeling",
            expected_claim="a1 = a ∧ a2 = a",
        )
    )

    candidate = _run(
        tmp_path,
        {
            "candidates": [
                {
                    "candidate_id": "c1",
                    "theorem_name_hint": "airtrack_common_acceleration",
                    "selected_model_instances": ["glider", "hanger"],
                    "controlled_sketch_steps_used": ["sk_glider", "sk_hanger", "alg_target"],
                }
            ]
        },
        model_ir=model_ir,
    )

    assert candidate.parse_ok is True
    assert "same_acceleration_magnitude" in candidate.theorem_decl
    assert "common_acceleration_definition" in candidate.theorem_decl
    assert "raw_law_equation_in_hypotheses" not in candidate.skeleton_audit.failure_tags


def test_tuple_valued_problem_fact_is_excluded_from_theorem(tmp_path: Path) -> None:
    model_ir = _model_ir(include_qualitative=False)
    model_ir.variables.update({"v": {}, "vx": {}, "vy": {}})
    model_ir.quantity_annotations.extend(
        [
            QuantityTypeAnnotation("vx", semantic_role="horizontal speed", lean_type="Speed", confidence=0.95),
            QuantityTypeAnnotation("vy", semantic_role="vertical speed", lean_type="Speed", confidence=0.95),
        ]
    )
    model_ir.givens.append(
        HypothesisProvenance(
            name="velocity_components_definition",
            lean="v = (vx, vy)",
            role="local_definition",
            source_type="problem_ir",
            source_id="relations.velocity_components",
            allowed_in_hypotheses=True,
        )
    )

    candidate = _run(
        tmp_path,
        {
            "candidates": [
                {
                    "candidate_id": "c1",
                    "theorem_name_hint": "no_tuple_fact",
                    "selected_model_instances": ["glider", "hanger"],
                    "controlled_sketch_steps_used": ["sk_glider", "sk_hanger", "alg_target"],
                }
            ]
        },
        model_ir=model_ir,
    )

    assert "velocity_components_definition" not in candidate.theorem_decl
    assert any(
        row.get("name") == "velocity_components_definition" and row.get("reason") == "tuple_valued_formula"
        for row in candidate.excluded_hypotheses
    )


def test_tautological_model_interface_gap_is_excluded(tmp_path: Path) -> None:
    model_ir = _model_ir_with_interface_gaps()
    model_ir.model_instances[0].interface_instantiations.append(
        ModelInterfaceInstantiation(
            instantiation_id="same_tension_tautology",
            kind="sign_convention_equation",
            formal_claim="T = T",
            source_model_instance="glider",
            interface_name="same_tension",
            binding_status="explicit_model_gap",
            proof_fact_allowed=False,
        )
    )

    candidate = _run(
        tmp_path,
        {
            "candidates": [
                {
                    "candidate_id": "c1",
                    "theorem_name_hint": "airtrack_tautology",
                    "selected_model_instances": ["glider", "hanger"],
                    "controlled_sketch_steps_used": ["sk_glider", "sk_hanger", "alg_target"],
                }
            ]
        },
        model_ir=model_ir,
    )

    assert "T.val = T.val" not in candidate.theorem_decl
    assert any(
        row.get("source_id") == "same_tension_tautology"
        and row.get("reason") == "tautological_model_interface"
        for row in candidate.excluded_hypotheses
    )


def test_non_prop_verified_decl_blocks_instead_of_faking_model_predicate(tmp_path: Path) -> None:
    candidate = _run(
        tmp_path,
        {
            "candidates": [
                {
                    "candidate_id": "c1",
                    "theorem_name_hint": "blocked",
                    "selected_model_instances": ["glider", "hanger"],
                    "controlled_sketch_steps_used": ["sk_glider", "sk_hanger", "alg_target"],
                }
            ]
        },
        bindings=_theorem_only_bindings(),
    )

    assert candidate.parse_ok is True
    assert candidate.generation_blocked_reason is None
    assert candidate.model_predicate_bindings == []
    assert candidate.gap_laws
    assert all(row["proof_fact_allowed"] is False for row in candidate.gap_laws)
    assert "MechLib.Dynamics.Newton1D" not in candidate.theorem_decl
    assert "forceSub" not in candidate.theorem_decl
    assert "weight" not in candidate.theorem_decl


def test_course_form_with_higher_order_args_is_not_truncated_to_predicate(tmp_path: Path) -> None:
    bindings = [
        EvidenceBinding(
            binding_id="b_glider",
            model_instance_id="glider",
            verified_decl="MechLib.Dynamics.NewtonLaw.newtonSecondLaw_course_form",
            decl_statement=(
                "theorem newtonSecondLaw_course_form "
                "(m : MechLib.SI.Mass) (a : MechLib.SI.Acceleration) (F : MechLib.SI.Force) : "
                "NewtonSecondLaw m a F = (F = MechLib.Mechanics.Dynamics.secondLaw m a)"
            ),
            callable_by_llm=True,
            lean_check_pass=True,
            proof_fact_allowed=True,
            binding_status="ok",
            expected_claim="T = m1 * a",
        ),
        EvidenceBinding(
            binding_id="b_hanger",
            model_instance_id="hanger",
            verified_decl="MechLib.Dynamics.SystemDynamics.centerOfMassBalance_eq",
            decl_statement=(
                "theorem centerOfMassBalance_eq "
                "(M : MechLib.SI.Mass) "
                "(Rddot : Real -> MechLib.SI.Acceleration) "
                "(Fext : Real -> MechLib.SI.Force) : "
                "CenterOfMassBalance M Rddot Fext = (forall t, M * Rddot t = Fext t)"
            ),
            callable_by_llm=True,
            lean_check_pass=True,
            proof_fact_allowed=True,
            binding_status="ok",
            expected_claim="m2 * g - T = m2 * a",
        ),
    ]
    candidate = _run(
        tmp_path,
        {
            "candidates": [
                {
                    "candidate_id": "c1",
                    "theorem_name_hint": "higher_order_blocked",
                    "selected_model_instances": ["glider", "hanger"],
                    "controlled_sketch_steps_used": ["sk_glider", "sk_hanger", "alg_target"],
                }
            ]
        },
        bindings=bindings,
    )

    assert "MechLib.Dynamics.NewtonLaw.NewtonSecondLaw m1 a T" in candidate.theorem_decl
    assert "CenterOfMassBalance m2" not in candidate.theorem_decl
    assert candidate.parse_ok is True
    assert candidate.generation_blocked_reason is None
    assert candidate.grounding_status == "partial_mechlib_with_model_gaps"
    assert any(row["source_model_instance"] == "hanger" for row in candidate.gap_laws)


def test_legacy_sketch_steps_are_not_directly_consumed_by_minimal_b(tmp_path: Path) -> None:
    legacy_sketch = ControlledSketch(
        sample_id="airtrack",
        schema_version=1,
        steps=[
            ControlledSketchStep(
                step_id="legacy_law",
                kind="law_application",
                claim="legacy law",
                formal_claim="T = m1 * a",
                verified_decl="MechLib.Test.Newton1D",
                proof_fact_allowed=True,
            )
        ],
        parse_ok=True,
    )
    module = ModuleB(
        StaticClient(json.dumps({"candidates": [{"candidate_id": "c1", "theorem_name_hint": "legacy"}]})),
        _prompt(tmp_path, "B_generate_statements.txt"),
        minimal_prompt_path=_prompt(tmp_path, "B_generate_minimal_skeleton.txt"),
    )

    candidate = module.run(
        _grounding(),
        generation_mode="minimal_skeleton",
        model_ir=_model_ir(include_qualitative=False),
        controlled_sketch=legacy_sketch,
        evidence_bindings=_predicate_bindings(),
        sketch_audit_result=SketchAuditResult(sample_id="airtrack", audit_pass=True),
    )[0]

    assert candidate.proof_obligations == []
    assert "legacy_law" not in candidate.controlled_sketch_steps_used
