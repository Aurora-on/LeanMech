from __future__ import annotations

import json

from mech_pipeline.knowledge.mechlib_structured import StructuredMechLibContext
from mech_pipeline.modules.sketch_audit import SketchAuditor, sketch_audit_stage_row
from mech_pipeline.types import (
    AlgebraObligation,
    BlockedLawStep,
    CanonicalTarget,
    ControlledSketch,
    ControlledSketchStep,
    EvidenceBinding,
    FunctionFormulaIR,
    HypothesisProvenance,
    ModelIR,
    ModelInterfaceInstantiation,
    ModelInstance,
)


def _context() -> StructuredMechLibContext:
    return StructuredMechLibContext(
        modeling_context={
            "matched_topics": ["Kinematics"],
            "concepts": [{"id": "concept.displacement", "proof_fact_allowed": False}],
            "law_schemas": [{"id": "law.kinematics.constant_speed", "proof_fact_allowed": False}],
            "problem_schemas": [{"id": "problem.uniform_motion", "proof_fact_allowed": False}],
            "aliases": [],
        },
        proof_context={
            "verified_decls": [
                {
                    "fq_name": "MechLib.Kinematics.constant_speed_relation",
                    "status": "verified",
                    "trust_level": "core",
                    "callable_by_llm": True,
                    "proof_fact_allowed": True,
                }
            ],
            "required_imports": ["import MechLib"],
            "proof_hints": [],
            "proof_style_examples": [],
        },
    )


def _model_ir(extra_givens: list[HypothesisProvenance | dict[str, object]] | None = None) -> ModelIR:
    givens: list[HypothesisProvenance | dict[str, object]] = [
        HypothesisProvenance(
            name="h_v",
            lean="v = 10",
            role="problem_fact",
            source_type="problem_ir",
            source_id="known_quantities.v",
            allowed_in_hypotheses=True,
        ),
        HypothesisProvenance(
            name="h_t",
            lean="t = 3",
            role="problem_fact",
            source_type="problem_ir",
            source_id="known_quantities.t",
            allowed_in_hypotheses=True,
        ),
    ]
    if extra_givens:
        givens.extend(extra_givens)
    return ModelIR(
        sample_id="s1",
        givens=givens,
        model_instances=[
            ModelInstance(
                instance_id="mi1",
                kind="constant_speed_kinematics",
                natural_language="Use constant speed displacement.",
                planning_schema_id="law.kinematics.constant_speed",
                expected_claim="s = v * t",
            )
        ],
        target={"symbol": "s", "description": "displacement"},
        forbidden_as_assumption=["target displacement s", "final answer s = 30"],
        parse_ok=True,
    )


def _ok_binding() -> EvidenceBinding:
    return EvidenceBinding(
        binding_id="b1",
        model_instance_id="mi1",
        planning_schema="law.kinematics.constant_speed",
        verified_decl="MechLib.Kinematics.constant_speed_relation",
        proof_fact_allowed=True,
        binding_status="ok",
        expected_claim="s = v * t",
    )


def _gap_binding() -> EvidenceBinding:
    return EvidenceBinding(
        binding_id="b_gap",
        model_instance_id="mi1",
        planning_schema="law.kinematics.constant_speed",
        verified_decl=None,
        proof_fact_allowed=False,
        binding_status="gap_schema_only",
        expected_claim="s = v * t",
    )


def _ok_step() -> ControlledSketchStep:
    return ControlledSketchStep(
        step_id="sk1",
        kind="law_to_equation",
        claim="constant speed law",
        formal_claim="s = v * t",
        source_model_instance="mi1",
        planning_schema="law.kinematics.constant_speed",
        verified_decl="MechLib.Kinematics.constant_speed_relation",
        binding_status="ok",
        expected_claim="s = v * t",
        proof_fact_allowed=True,
        required_hypotheses=["h_v", "h_t"],
        produces="h_law",
    )


def _ok_sketch() -> ControlledSketch:
    return ControlledSketch(sample_id="s1", status="ok", proof_steps=[_ok_step()], parse_ok=True)


def _audit(
    model_ir: ModelIR,
    sketch: ControlledSketch,
    bindings: list[EvidenceBinding] | None = None,
) -> object:
    return SketchAuditor().audit(
        sample_id="s1",
        model_ir=model_ir,
        sketch=sketch,
        evidence_bindings=bindings if bindings is not None else [_ok_binding()],
        structured_mechlib_context=_context(),
        hypothesis_provenance=list(model_ir.givens) + list(model_ir.local_definitions),
    )


def test_sketch_audit_passes_for_verified_law_to_equation() -> None:
    result = _audit(_model_ir(), _ok_sketch())

    assert result.audit_pass is True
    assert result.failure_tags == []
    json.dumps(sketch_audit_stage_row("s1", result))


def test_sketch_audit_fails_when_proof_step_uses_schema_as_decl() -> None:
    bad = _ok_step()
    bad.verified_decl = "law.kinematics.constant_speed"
    sketch = ControlledSketch(sample_id="s1", status="ok", proof_steps=[bad], parse_ok=True)

    result = _audit(_model_ir(), sketch, bindings=[])

    assert result.audit_pass is False
    assert result.schema_used_as_proof_fact is True
    assert "schema_used_as_proof_fact" in result.failure_tags


def test_sketch_audit_whitelist_beats_alias_metadata_target() -> None:
    context = _context()
    context.modeling_context["aliases"] = [
        {
            "alias_name": "constantSpeed",
            "alias_to_fq_name": "MechLib.Kinematics.constant_speed_relation",
            "proof_fact_allowed": False,
        }
    ]

    result = SketchAuditor().audit(
        sample_id="s1",
        model_ir=_model_ir(),
        sketch=_ok_sketch(),
        evidence_bindings=[_ok_binding()],
        structured_mechlib_context=context,
        hypothesis_provenance=list(_model_ir().givens),
    )

    assert result.audit_pass is True
    assert result.schema_used_as_proof_fact is False
    assert "schema_used_as_proof_fact" not in result.failure_tags


def test_sketch_audit_hard_fails_gap_or_false_proof_step() -> None:
    bad = _ok_step()
    bad.verified_decl = None
    bad.binding_status = "gap_schema_only"
    bad.proof_fact_allowed = False
    sketch = ControlledSketch(sample_id="s1", status="ok", proof_steps=[bad], parse_ok=True)

    result = _audit(_model_ir(), sketch, bindings=[_gap_binding()])

    assert result.audit_pass is False
    assert "unbound_verified_decl" in result.failure_tags
    assert "schema_used_as_proof_fact" in result.failure_tags


def test_sketch_audit_fails_natural_language_formal_claim_and_forbidden_kind() -> None:
    bad = _ok_step()
    bad.kind = "target_rewrite"
    bad.formal_claim = "Use the target rewrite to obtain the answer."
    sketch = ControlledSketch(sample_id="s1", status="ok", proof_steps=[bad], parse_ok=True)

    result = _audit(_model_ir(), sketch)

    assert result.audit_pass is False
    assert "controlled_sketch_invalid_step_kind" in result.failure_tags
    assert "non_lean_like_formal_claim" in result.failure_tags


def test_sketch_audit_fails_unknown_required_hypothesis() -> None:
    bad = _ok_step()
    bad.required_hypotheses = ["h_missing"]
    sketch = ControlledSketch(sample_id="s1", status="ok", proof_steps=[bad], parse_ok=True)

    result = _audit(_model_ir(), sketch)

    assert result.audit_pass is False
    assert "unknown_required_hypotheses" in result.failure_tags


def test_sketch_audit_allows_required_model_instance_id() -> None:
    step = _ok_step()
    step.required_hypotheses = ["mi1"]
    sketch = ControlledSketch(sample_id="s1", status="ok", proof_steps=[step], parse_ok=True)

    result = _audit(_model_ir(), sketch)

    assert result.audit_pass is True
    assert "unknown_required_hypotheses" not in result.failure_tags


def test_sketch_audit_fails_non_target_algebra_obligation() -> None:
    sketch = ControlledSketch(
        sample_id="s1",
        status="ok",
        proof_steps=[_ok_step()],
        algebra_obligation=AlgebraObligation(
            obligation_id="alg_bad",
            claim="solve other variable",
            formal_claim="u = 30",
            required_equations=["h_law"],
            target_variables=["u"],
        ),
        parse_ok=True,
    )

    result = _audit(_model_ir(), sketch)

    assert result.audit_pass is False
    assert "non_target_final_formula" in result.failure_tags


def test_sketch_audit_passes_for_blocked_gap_schema_only_step() -> None:
    sketch = ControlledSketch(
        sample_id="s1",
        status="blocked_by_evidence_gap",
        proof_steps=[],
        blocked_law_steps=[
            BlockedLawStep(
                step_id="sk_gap",
                source_model_instance="mi1",
                planning_schema="law.kinematics.constant_speed",
                expected_claim="s = v * t",
                binding_status="gap_schema_only",
                proof_fact_allowed=False,
            )
        ],
        parse_ok=True,
    )

    result = _audit(_model_ir(), sketch, bindings=[_gap_binding()])

    assert result.audit_pass is True
    assert result.failure_tags == []


def test_sketch_audit_preserves_hypothesis_leakage_checks() -> None:
    target_hyp = HypothesisProvenance(
        name="h_target",
        lean="target displacement s",
        role="target",
        source_type="model_ir",
        source_id="target",
        allowed_in_hypotheses=True,
    )

    result = _audit(_model_ir([target_hyp]), _ok_sketch())

    assert result.audit_pass is False
    assert result.target_leakage is True
    assert "target_leakage" in result.failure_tags


def test_sketch_audit_flags_exact_final_formula_hypothesis() -> None:
    final_hyp = HypothesisProvenance(
        name="h_final_answer",
        lean="s = 30",
        role="problem_fact",
        source_type="problem_ir",
        source_id="bad_final_answer",
        allowed_in_hypotheses=True,
    )

    result = _audit(_model_ir([final_hyp]), _ok_sketch())

    assert result.audit_pass is False
    assert result.target_leakage is True
    assert "target_leakage" in result.failure_tags


def test_sketch_audit_does_not_treat_forbidden_local_definition_as_target_leakage() -> None:
    local_definition = HypothesisProvenance(
        name="def_h_cm",
        lean="h_cm.val = block_height.val / 2",
        role="local_definition",
        source_type="problem_ir",
        source_id="relations.h_cm",
        allowed_in_hypotheses=True,
        notes="Uniform rectangular block center-of-mass definition.",
    )
    model_ir = _model_ir([local_definition])
    model_ir.forbidden_as_assumption.append("h_cm.val = block_height.val / 2")

    result = _audit(model_ir, _ok_sketch())

    assert result.target_leakage is False
    assert "target_leakage" not in result.failure_tags


def test_sketch_audit_allows_explicit_modeling_equation_hypothesis() -> None:
    modeling_hyp = HypothesisProvenance(
        name="h_newton2_glider",
        lean="Fnet1 = m1 * a",
        role="problem_fact",
        source_type="model_ir",
        source_id="model_interface.glider_newton2",
        allowed_in_hypotheses=True,
        notes="explicit model interface equation",
    )
    model_ir = _model_ir([modeling_hyp])
    model_ir.variables = {"Fnet1": {}, "m1": {}, "a": {}}
    step = _ok_step()
    step.formal_claim = "Fnet1 = m1 * a"
    step.expected_claim = "Fnet1 = m1 * a"
    sketch = ControlledSketch(sample_id="s1", status="ok", proof_steps=[step], parse_ok=True)

    result = _audit(model_ir, sketch)

    assert result.audit_pass is True
    assert result.raw_law_equation_in_hypotheses is False
    assert "raw_law_equation_in_hypotheses" not in result.failure_tags


def test_sketch_audit_allows_component_model_interface_overlap_with_target() -> None:
    model_ir = _model_ir()
    model_ir.canonical_target = CanonicalTarget(
        target_kind="component_relation",
        target_variables=["R_x", "R_y"],
        lean_formula="R_x = d2 ∧ R_y = d1",
        source_text="component displacement relation",
        confidence=0.9,
        parse_ok=True,
    )
    sketch = _ok_sketch()
    sketch.model_interface_instantiations = [
        ModelInterfaceInstantiation(
            instantiation_id="disp_components_mi1",
            kind="component_relation",
            formal_claim="R_x = d2 ∧ R_y = d1",
            source_model_instance="mi1",
            interface_name="displacement_components",
            binding_status="explicit_model_gap",
            proof_fact_allowed=False,
            notes="component modeling interface",
        )
    ]

    result = _audit(model_ir, sketch)

    assert result.target_leakage is False
    assert "target_leakage" not in result.failure_tags


def test_sketch_audit_records_non_lean_interface_metadata_without_hard_fail() -> None:
    sketch = _ok_sketch()
    sketch.model_interface_instantiations = [
        ModelInterfaceInstantiation(
            instantiation_id="uniform_tension_metadata",
            kind="string_metadata",
            formal_claim="uniform tension applies to the ideal string",
            source_model_instance="mi1",
            binding_status="explicit_model_gap",
            proof_fact_allowed=False,
        )
    ]

    result = _audit(_model_ir(), sketch)

    assert result.audit_pass is True
    assert "non_lean_like_formal_claim" not in result.failure_tags
    assert result.details["bad_steps"][0]["step_id"] == "uniform_tension_metadata"


def test_sketch_audit_does_not_treat_definition_applicability_as_target_leakage() -> None:
    definition_given = HypothesisProvenance(
        name="h_avg_velocity_definition_applicable",
        lean="average velocity definition applies on the given time interval",
        role="problem_fact",
        source_type="problem_ir",
        source_id="assumptions.average_velocity_definition",
        allowed_in_hypotheses=True,
    )
    model_ir = _model_ir([definition_given])
    model_ir.target = {"symbol": "v_avg", "description": "average velocity"}
    model_ir.forbidden_as_assumption = ["final answer v_avg = displacement / time"]

    result = _audit(model_ir, _ok_sketch())

    assert result.target_leakage is False
    assert "target_leakage" not in result.failure_tags


def test_sketch_audit_does_not_treat_function_target_lhs_overlap_as_leakage() -> None:
    derivative_relation = HypothesisProvenance(
        name="h_velocity_definition",
        lean="forall t0 : Time, (v t0).val = deriv (fun tau : Real => 3 * tau ^ 2) t0.val",
        role="local_definition",
        source_type="model_ir",
        source_id="relations.velocity_derivative",
        allowed_in_hypotheses=True,
        notes="kinematic definition interface",
    )
    model_ir = _model_ir([derivative_relation])
    model_ir.canonical_target = CanonicalTarget(
        target_kind="relation",
        target_variables=["v"],
        lean_formula="forall t0 : Time, (v t0).val = 6 * t0.val",
        function_formula_ir=[
            FunctionFormulaIR(
                formula_id="target_velocity",
                formula_kind="pointwise_relation",
                bound_variables=[{"name": "t0", "lean_type": "Time"}],
                lhs="(v t0).val",
                relation="=",
                rhs="6 * t0.val",
                lean_formula="forall t0 : Time, (v t0).val = 6 * t0.val",
                source_text="find the velocity function",
                parse_ok=True,
            )
        ],
        source_text="find the velocity function",
        confidence=0.9,
        parse_ok=True,
    )

    result = _audit(model_ir, _ok_sketch())

    assert result.target_leakage is False
    assert "target_leakage" not in result.failure_tags


def test_sketch_audit_allows_target_variable_local_constraint() -> None:
    theta_constraint = HypothesisProvenance(
        name="h_wrap_count",
        lean="theta = 2 * Real.pi * n",
        role="local_definition",
        source_type="problem_ir",
        source_id="constraints.wrap_count",
        allowed_in_hypotheses=True,
        notes="problem constraint relating angle and number of wraps",
    )
    model_ir = _model_ir([theta_constraint])
    model_ir.canonical_target = CanonicalTarget(
        target_kind="closed_form",
        target_variables=["theta"],
        lean_formula="n = theta / (2 * Real.pi)",
        source_text="find wrap count",
        confidence=0.9,
        parse_ok=True,
    )

    result = _audit(model_ir, _ok_sketch())

    assert result.target_leakage is False
    assert "target_leakage" not in result.failure_tags


def test_sketch_audit_allows_explicit_problem_function_definition_matching_law_claim() -> None:
    given_position = HypothesisProvenance(
        name="h_position_function",
        lean="forall t0 : Time, (x t0).val = (3 : Real) * t0.val ^ 2",
        role="problem_fact",
        source_type="problem_ir",
        source_id="known_quantities.position_function",
        allowed_in_hypotheses=True,
    )
    model_ir = _model_ir([given_position])
    step = _ok_step()
    step.formal_claim = "forall t0 : Time, (x t0).val = (3 : Real) * t0.val ^ 2"
    step.expected_claim = step.formal_claim
    sketch = ControlledSketch(sample_id="s1", status="ok", proof_steps=[step], parse_ok=True)

    result = _audit(model_ir, sketch)

    assert result.audit_pass is True
    assert result.raw_law_equation_in_hypotheses is False
    assert "raw_law_equation_in_hypotheses" not in result.failure_tags


def test_sketch_audit_allows_explicit_numeric_problem_given_matching_law_claim() -> None:
    given_force = HypothesisProvenance(
        name="given_start_force",
        lean="F_start.val = 230",
        role="problem_fact",
        source_type="problem_ir",
        source_id="known_quantities.start_force",
        allowed_in_hypotheses=True,
    )
    model_ir = _model_ir([given_force])
    step = _ok_step()
    step.formal_claim = "F_start.val = 230"
    step.expected_claim = "F_start.val = 230"
    sketch = ControlledSketch(sample_id="s1", status="ok", proof_steps=[step], parse_ok=True)

    result = _audit(model_ir, sketch)

    assert result.audit_pass is True
    assert result.raw_law_equation_in_hypotheses is False
    assert "raw_law_equation_in_hypotheses" not in result.failure_tags


def test_sketch_audit_allows_center_of_mass_modeling_constraint() -> None:
    com_constraint = HypothesisProvenance(
        name="center_of_mass_displacement_constraint",
        lean="m_person.val * delta_x_person.val + m_boat.val * delta_x_boat.val = 0",
        role="local_definition",
        source_type="model_ir",
        source_id="relations.center_of_mass",
        allowed_in_hypotheses=True,
        notes="center_of_mass displacement relation from the problem setup",
    )
    model_ir = _model_ir([com_constraint])
    step = _ok_step()
    step.formal_claim = "m_person.val * delta_x_person.val + m_boat.val * delta_x_boat.val = 0"
    step.expected_claim = step.formal_claim
    sketch = ControlledSketch(sample_id="s1", status="ok", proof_steps=[step], parse_ok=True)

    result = _audit(model_ir, sketch)

    assert result.raw_law_equation_in_hypotheses is False
    assert "raw_law_equation_in_hypotheses" not in result.failure_tags


def test_sketch_audit_requires_hypothesis_provenance() -> None:
    missing = {"name": "h_missing", "lean": "v = 10"}

    result = _audit(_model_ir([missing]), _ok_sketch())

    assert result.audit_pass is False
    assert result.missing_provenance is True
    assert "missing_provenance" in result.failure_tags
