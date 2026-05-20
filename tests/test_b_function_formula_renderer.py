from __future__ import annotations

from mech_pipeline.modules.B_statement_gen import (
    _has_scalarized_force_vector_sum,
    _has_unsupported_tuple_formula,
    _quantity_infos,
    _target_formula,
    _is_allowed_lean_target,
    _typed_formula_from_text,
    render_function_formula_ir,
)
from mech_pipeline.types import CanonicalTarget, FunctionFormulaIR, HypothesisProvenance, ModelIR, QuantityTypeAnnotation


def test_render_pointwise_real_domain_typed_codomain() -> None:
    quantity_infos = [
        {
            "source_name": "x",
            "name": "x",
            "lean_type": "Real -> Length",
            "requested_lean_type": "Real -> Length",
        },
        {"source_name": "v", "name": "v", "lean_type": "Speed"},
    ]

    formula, error = render_function_formula_ir(
        {
            "formula_id": "motion",
            "formula_kind": "pointwise_relation",
            "function_symbol": "x",
            "function_type": "Real -> Length",
            "bound_variables": [{"name": "t", "lean_type": "Real"}],
            "lhs": "(x t).val",
            "relation": "=",
            "rhs": "v * t",
            "parse_ok": True,
        },
        quantity_infos,
    )

    assert error is None
    assert formula == "forall t : Real, (x t).val = v.val * t"
    assert "x.val t" not in formula
    assert ".val).val" not in formula


def test_render_function_evaluation_normalizes_numeric_argument_once() -> None:
    quantity_infos = [
        {
            "source_name": "v",
            "name": "v",
            "lean_type": "Real -> Speed",
            "requested_lean_type": "Real -> Speed",
        },
        {"source_name": "v0", "name": "v0", "lean_type": "Speed"},
    ]

    formula, error = render_function_formula_ir(
        {
            "formula_id": "initial_velocity",
            "formula_kind": "evaluation_relation",
            "function_symbol": "v",
            "function_type": "Real -> Speed",
            "lhs": "v 0",
            "relation": "=",
            "rhs": "v0",
            "parse_ok": True,
        },
        quantity_infos,
    )

    assert error is None
    assert formula == "(v (0 : Real)).val = v0.val"
    assert "((v (0 : Real)).val).val" not in formula


def test_render_function_evaluation_parses_symbol_from_parenthesized_lhs() -> None:
    quantity_infos = [
        {
            "source_name": "v",
            "name": "v",
            "lean_type": "Real -> Speed",
            "requested_lean_type": "Real -> Speed",
        },
        {"source_name": "v0", "name": "v0", "lean_type": "Speed"},
    ]

    formula, error = render_function_formula_ir(
        {
            "formula_id": "initial_velocity",
            "formula_kind": "evaluation_relation",
            "function_type": "Real -> Speed",
            "lhs": "(v 0).val",
            "relation": "=",
            "rhs": "v0",
            "parse_ok": True,
        },
        quantity_infos,
    )

    assert error is None
    assert formula == "(v (0 : Real)).val = v0.val"


def test_render_time_domain_function_blocks_without_explicit_policy() -> None:
    quantity_infos = [
        {
            "source_name": "x",
            "name": "x",
            "lean_type": "MechLib.Mechanics.Kinematics.ScalarTrajectory",
            "requested_lean_type": "Time -> Length",
        },
        {"source_name": "v", "name": "v", "lean_type": "Speed"},
    ]

    formula, error = render_function_formula_ir(
        {
            "formula_id": "motion",
            "formula_kind": "pointwise_relation",
            "function_symbol": "x",
            "function_type": "Time -> Length",
            "bound_variables": [{"name": "t", "lean_type": "Time"}],
            "lhs": "x t",
            "relation": "=",
            "rhs": "v * t",
            "parse_ok": True,
        },
        quantity_infos,
    )

    assert formula == ""
    assert error == "function_domain_policy_required"


def test_render_function_formula_rejects_invalid_value_shapes() -> None:
    quantity_infos = [
        {
            "source_name": "x",
            "name": "x",
            "lean_type": "Real -> Length",
            "requested_lean_type": "Real -> Length",
        },
        {"source_name": "y", "name": "y", "lean_type": "Length"},
    ]

    formula, error = render_function_formula_ir(
        {
            "formula_id": "bad_motion",
            "formula_kind": "pointwise_relation",
            "function_symbol": "x",
            "function_type": "Real -> Length",
            "bound_variables": [{"name": "t", "lean_type": "Real"}],
            "lhs": "x.val t",
            "relation": "=",
            "rhs": "y",
            "parse_ok": True,
        },
        quantity_infos,
    )

    assert formula == ""
    assert error in {"invalid_function_lhs", "invalid_function_value_shape"}


def test_render_pointwise_allows_log_rhs_with_nested_function_value() -> None:
    quantity_infos = [
        {
            "source_name": "v",
            "name": "v",
            "lean_type": "Real -> Speed",
            "requested_lean_type": "Real -> Speed",
        },
        {"source_name": "m", "name": "m", "lean_type": "Real -> Mass"},
        {"source_name": "m0", "name": "m0", "lean_type": "Mass"},
        {"source_name": "v_rel", "name": "v_rel", "lean_type": "Speed"},
        {"source_name": "g", "name": "g", "lean_type": "Acceleration"},
    ]

    formula, error = render_function_formula_ir(
        {
            "formula_id": "rocket_velocity",
            "formula_kind": "pointwise_relation",
            "bound_variables": [{"name": "t0", "lean_type": "Real"}],
            "lhs": "(v t0).val",
            "relation": "=",
            "rhs": "v_rel.val * Real.log (m0.val / ((m t0).val)) - g.val * t0",
            "parse_ok": True,
        },
        quantity_infos,
    )

    assert error is None
    assert formula == (
        "forall t0 : Real, (v t0).val = "
        "v_rel.val * Real.log (m0.val / ((m t0).val)) - g.val * t0"
    )


def test_render_ode_formula_does_not_require_simple_lhs_function_symbol() -> None:
    quantity_infos = [
        {"source_name": "theta", "name": "theta", "lean_type": "Real -> PhysAngle"},
        {"source_name": "g", "name": "g", "lean_type": "Acceleration"},
    ]

    formula, error = render_function_formula_ir(
        {
            "formula_id": "theta_ode",
            "formula_kind": "ode_relation",
            "bound_variables": [{"name": "t0", "lean_type": "Real"}],
            "lhs": "deriv (fun t : Real => (theta t).val) t0",
            "relation": "=",
            "rhs": "g * Real.sin ((theta t0).val)",
            "parse_ok": True,
        },
        quantity_infos,
    )

    assert error is None
    assert formula == (
        "forall t0 : Real, "
        "deriv (fun t : Real => (theta t).val) t0 = g.val * Real.sin ((theta t0).val)"
    )


def test_render_ode_formula_normalizes_real_deriv_namespace() -> None:
    quantity_infos = [
        {"source_name": "theta", "name": "theta", "lean_type": "Real -> PhysAngle"},
        {"source_name": "g", "name": "g", "lean_type": "Acceleration"},
    ]

    formula, error = render_function_formula_ir(
        {
            "formula_id": "theta_ode",
            "formula_kind": "ode_relation",
            "bound_variables": [{"name": "t0", "lean_type": "Real"}],
            "lhs": "Real.deriv (fun t : Real => (theta t).val) t0",
            "relation": "=",
            "rhs": "g * sin ((theta t0).val)",
            "parse_ok": True,
        },
        quantity_infos,
    )

    assert error is None
    assert "Real.deriv" not in formula
    assert "deriv (fun t : Real => (theta t).val) t0" in formula
    assert "Real.sin" in formula


def test_value_level_normalization_strips_compound_real_val_projection() -> None:
    quantity_infos = [
        {"source_name": "g", "name": "g", "lean_type": "Acceleration"},
        {"source_name": "h1", "name": "h1", "lean_type": "Length"},
        {"source_name": "k", "name": "k", "lean_type": "SpringConstant"},
        {"source_name": "x", "name": "x", "lean_type": "Real -> Length"},
        {"source_name": "a", "name": "a", "lean_type": "Real -> Acceleration"},
    ]

    formula = _typed_formula_from_text(
        "0 <= (2 * g.val * h1.val).val ∧ "
        "forall t0 : Real, (-k.val * ((x t0).val)).val = (a t0).val",
        quantity_infos,
    )

    assert "(2 * g.val * h1.val).val" not in formula
    assert "(-k.val * ((x t0).val)).val" not in formula
    assert "(x t0).val" in formula


def test_real_inverse_trig_names_use_mathlib_names() -> None:
    quantity_infos = [
        {"source_name": "x", "name": "x", "lean_type": "Real"},
        {"source_name": "theta", "name": "theta", "lean_type": "PhysAngle"},
    ]

    formula = _typed_formula_from_text(
        "theta = atan x ∧ theta = asin x ∧ theta = acos x",
        quantity_infos,
    )

    assert "Real.arctan x" in formula
    assert "Real.arcsin x" in formula
    assert "Real.arccos x" in formula
    assert "Real.atan" not in formula
    assert "Real.asin" not in formula
    assert "Real.acos" not in formula


def test_target_variable_n_is_not_rejected_as_unit_newton() -> None:
    formula = "n = (1 / (2 * Real.pi * mu.val)) * Real.log (M.val / m.val)"

    assert _is_allowed_lean_target(formula) is True


def test_render_tuple_ode_relation_as_conjunction() -> None:
    quantity_infos = [
        {"source_name": "m1", "name": "m1", "lean_type": "Mass"},
        {"source_name": "m2", "name": "m2", "lean_type": "Mass"},
        {"source_name": "g", "name": "g", "lean_type": "Acceleration"},
        {"source_name": "l", "name": "l", "lean_type": "Length"},
        {"source_name": "k", "name": "k", "lean_type": "SpringConstant"},
        {"source_name": "x", "name": "x", "lean_type": "Real -> Length"},
        {"source_name": "ax", "name": "ax", "lean_type": "Real -> Acceleration"},
        {"source_name": "phi", "name": "phi", "lean_type": "Real -> PhysAngle"},
        {"source_name": "omega", "name": "omega", "lean_type": "Real -> AngularVelocity"},
        {"source_name": "alpha", "name": "alpha", "lean_type": "Real -> AngularAcceleration"},
    ]

    formula, error = render_function_formula_ir(
        {
            "formula_id": "coupled_ode",
            "formula_kind": "ode_relation",
            "bound_variables": [{"name": "t0", "lean_type": "Real"}],
            "lhs": (
                "((m1.val + m2.val) * (ax t0).val + "
                "m2.val * l.val * (cos ((phi t0).val) * (alpha t0).val - "
                "sin ((phi t0).val) * ((omega t0).val ^ 2)) + k.val * (x t0).val, "
                "l.val * (alpha t0).val + (ax t0).val * cos ((phi t0).val) + "
                "g.val * sin ((phi t0).val))"
            ),
            "relation": "=",
            "rhs": "(0, 0)",
            "parse_ok": True,
        },
        quantity_infos,
    )

    assert error is None
    assert formula.startswith("forall t0 : Real, ")
    assert " ∧ " in formula
    assert "(0, 0)" not in formula
    assert "Real.sin" in formula
    assert "Real.cos" in formula


def test_typed_formula_inserts_space_after_qualified_real_function() -> None:
    quantity_infos = [
        {"source_name": "a", "name": "a", "lean_type": "Length"},
        {"source_name": "k", "name": "k", "lean_type": "AngularVelocity"},
        {"source_name": "t", "name": "t", "lean_type": "Time"},
        {"source_name": "beta", "name": "beta", "lean_type": "PhysAngle"},
        {"source_name": "y", "name": "y", "lean_type": "Length"},
    ]

    formula = _typed_formula_from_text(
        "y = a * cos(k * t + beta)",
        quantity_infos,
    )

    assert "Real.cos (" in formula
    assert "Real.cos(" not in formula


def test_tuple_detection_handles_nested_numeric_cast_tuple() -> None:
    assert _has_unsupported_tuple_formula("a = (((1 : Real) / 2), ((3 : Real) / 10))") is True


def test_function_quantity_scalar_projection_is_blocked() -> None:
    quantity_infos = [
        {"source_name": "Fnet", "name": "Fnet", "lean_type": "Force"},
        {"source_name": "m", "name": "m", "lean_type": "Mass"},
        {"source_name": "k", "name": "k", "lean_type": "SpringConstant"},
        {
            "source_name": "y",
            "name": "y",
            "lean_type": "MechLib.Mechanics.Kinematics.ScalarTrajectory",
        },
    ]
    trace: list[dict[str, object]] = []

    formula = _typed_formula_from_text(
        "Fnet = m * g - k * y.val",
        quantity_infos,
        trace_sink=trace,
        trace_source="regression:y_scalar_projection",
    )

    assert "y.val" in formula
    assert trace[-1]["blocked_reason"] == "function_quantity_scalar_projection"


def test_canonical_function_target_type_overrides_scalar_annotation() -> None:
    model_ir = ModelIR(
        sample_id="angular_momentum_function",
        variables={"L_Oz": "z component of angular momentum"},
        quantity_annotations=[
            QuantityTypeAnnotation(symbol="L_Oz", lean_type="AngularMomentum", confidence=0.98)
        ],
        canonical_target=CanonicalTarget(
            target_kind="pointwise_function_relation",
            target_variables=["L_Oz"],
            lean_formula="forall t0 : Real, (L_Oz t0).val = 0",
            function_formula_ir=[
                FunctionFormulaIR(
                    formula_kind="pointwise_relation",
                    function_symbol="L_Oz",
                    function_type="Real -> AngularMomentum",
                    bound_variables=[{"name": "t0", "lean_type": "Real"}],
                    lhs="(L_Oz t0).val",
                    relation="=",
                    rhs="0",
                    parse_ok=True,
                )
            ],
            parse_ok=True,
        ),
        parse_ok=True,
    )

    infos = _quantity_infos(model_ir)
    l_oz = next(info for info in infos if info["name"] == "L_Oz")
    formula, error = _target_formula(
        model_ir=model_ir,
        controlled_sketch=None,
        quantity_infos=infos,
    )

    assert l_oz["lean_type"] == "Real -> AngularMomentum"
    assert error is None
    assert formula == "forall t0 : Real, (L_Oz t0).val = 0"


def test_target_conjunction_parenthesizes_conditional_conclusion() -> None:
    model_ir = ModelIR(
        sample_id="conditional_target",
        variables={"F2": "force magnitude", "gamma": "angle"},
        quantity_annotations=[
            QuantityTypeAnnotation(symbol="F2", lean_type="Force", confidence=0.99),
            QuantityTypeAnnotation(symbol="gamma", lean_type="PhysAngle", confidence=0.99),
        ],
        canonical_target=CanonicalTarget(
            target_kind="relation",
            target_variables=["F2", "gamma"],
            lean_formula="F2 = 10",
            secondary_formulas=["F2 > 0 -> gamma = Real.pi / 3"],
            parse_ok=True,
        ),
        parse_ok=True,
    )

    formula, error = _target_formula(
        model_ir=model_ir,
        controlled_sketch=None,
        quantity_infos=_quantity_infos(model_ir),
    )

    assert error is None
    assert "F2.val = 10" in formula
    assert "∧\n  (F2.val > 0 -> gamma.val = Real.pi / 3)" in formula


def test_target_component_relations_covering_target_variables_are_not_minimized_away() -> None:
    model_ir = ModelIR(
        sample_id="force_angle_target",
        variables={"F1": {}, "F2": {}, "P": {}, "theta": {}, "gamma": {}},
        quantity_annotations=[
            QuantityTypeAnnotation(symbol="F1", lean_type="Force", confidence=0.99),
            QuantityTypeAnnotation(symbol="F2", lean_type="Force", confidence=0.99),
            QuantityTypeAnnotation(symbol="P", lean_type="Force", confidence=0.99),
            QuantityTypeAnnotation(symbol="theta", lean_type="PhysAngle", confidence=0.99),
            QuantityTypeAnnotation(symbol="gamma", lean_type="PhysAngle", confidence=0.99),
        ],
        local_definitions=[
            HypothesisProvenance(
                name="h_tangent",
                lean="F2.val * Real.cos gamma.val = F1.val * Real.cos theta.val",
                role="local_definition",
                source_type="model_ir",
                allowed_in_hypotheses=True,
            ),
            HypothesisProvenance(
                name="h_normal",
                lean="F2.val * Real.sin gamma.val = P.val - F1.val * Real.sin theta.val",
                role="local_definition",
                source_type="model_ir",
                allowed_in_hypotheses=True,
            ),
        ],
        canonical_target=CanonicalTarget(
            target_kind="relation",
            target_variables=["F2", "gamma"],
            lean_formula=(
                "F2.val * Real.cos gamma.val = F1.val * Real.cos theta.val ∧ "
                "F2.val * Real.sin gamma.val = P.val - F1.val * Real.sin theta.val"
            ),
            secondary_formulas=[
                "F2.val = Real.sqrt ((F1.val * Real.cos theta.val)^2 + (P.val - F1.val * Real.sin theta.val)^2)"
            ],
            parse_ok=True,
        ),
        parse_ok=True,
    )

    formula, error = _target_formula(
        model_ir=model_ir,
        controlled_sketch=None,
        quantity_infos=_quantity_infos(model_ir),
    )

    assert error is None
    assert "F2.val * Real.cos gamma.val = F1.val * Real.cos theta.val" in formula
    assert "F2.val * Real.sin gamma.val = P.val - F1.val * Real.sin theta.val" in formula


def test_scalarized_force_vector_sum_is_blocked() -> None:
    quantity_infos = [
        {"source_name": "F1", "name": "F1", "lean_type": "Force"},
        {"source_name": "F2", "name": "F2", "lean_type": "Force"},
        {"source_name": "P", "name": "P", "lean_type": "Force"},
        {"source_name": "Fx_net", "name": "Fx_net", "lean_type": "Force"},
    ]

    assert _has_scalarized_force_vector_sum("F1.val + F2.val + P.val = 0", quantity_infos) is True
    assert (
        _has_scalarized_force_vector_sum(
            "Fx_net.val = F1.val * Real.cos theta.val - F2.val * Real.cos gamma.val",
            quantity_infos,
        )
        is False
    )
