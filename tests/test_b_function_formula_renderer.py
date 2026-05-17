from __future__ import annotations

from mech_pipeline.modules.B_statement_gen import (
    _is_allowed_lean_target,
    _typed_formula_from_text,
    render_function_formula_ir,
)


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
