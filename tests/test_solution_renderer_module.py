import json
from types import SimpleNamespace

from mech_pipeline.modules.solution_renderer import ModuleSolutionRenderer


class _Response:
    def __init__(self, text):
        self.text = text


class _MockModel:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0
        self.prompts = []

    def generate_text(self, prompt):
        self.calls += 1
        self.prompts.append(prompt)
        return _Response(self.responses.pop(0))


def _candidate():
    return {
        "sample_id": "s1",
        "candidate_id": "c1",
        "theorem_decl": "theorem t : mu_s.val = F_start.val / W.val := by",
        "proof_obligations": [
            {
                "step_id": "sk1",
                "kind": "law_to_equation",
                "claim": "最大静摩擦等于启动力",
                "formal_claim": "F_start.val = mu_s.val * W.val",
                "binding_status": "ok",
                "proof_fact_allowed": True,
                "verified_decl": "MechLib.Friction.staticFrictionMax",
            }
        ],
        "controlled_sketch": {
            "sample_id": "s1",
            "proof_steps": [
                {
                    "step_id": "sk1",
                    "kind": "law_to_equation",
                    "formal_claim": "F_start.val = mu_s.val * W.val",
                    "binding_status": "ok",
                    "proof_fact_allowed": True,
                    "verified_decl": "MechLib.Friction.staticFrictionMax",
                }
            ],
            "algebra_obligation": {"obligation_id": "alg1", "formal_claim": "mu_s.val = F_start.val / W.val"},
        },
    }


def _multi_target_candidate():
    candidate = _candidate()
    candidate["target_spec"] = {
        "lean_formula": "a.val = (m2.val * g.val) / (m1.val + m2.val)",
        "secondary_formulas": [
            "T.val = (m1.val * m2.val * g.val) / (m1.val + m2.val)",
        ],
    }
    return candidate


def _mechanics73_candidate():
    return {
        "sample_id": "s1",
        "candidate_id": "c1",
        "target_spec": {
            "lean_formula": "a = (m2 * g) / (m1 + m2)",
            "secondary_formulas": [
                "T = (m1 * m2 * g) / (m1 + m2)",
            ],
        },
        "controlled_sketch": {
            "sample_id": "s1",
            "proof_steps": [
                {
                    "step_id": "sk1",
                    "kind": "law_to_equation",
                    "formal_claim": "T = m1 * a",
                    "binding_status": "ok",
                    "proof_fact_allowed": True,
                    "verified_decl": "MechLib.Compat.PHYSlib.SI.newton_second_law",
                },
                {
                    "step_id": "sk2",
                    "kind": "law_to_equation",
                    "formal_claim": "m2 * g - T = m2 * a",
                    "binding_status": "ok",
                    "proof_fact_allowed": True,
                    "verified_decl": "MechLib.Compat.PHYSlib.SI.newton_second_law",
                },
            ],
        },
    }


def _mechanics73_modeling_only_candidate():
    return {
        "sample_id": "s1",
        "candidate_id": "c1",
        "target_spec": {
            "lean_formula": "a = (m2 * g) / (m1 + m2)",
            "secondary_formulas": [
                "T = (m1 * m2 * g) / (m1 + m2)",
            ],
        },
        "controlled_sketch": {
            "sample_id": "s1",
            "proof_steps": [],
            "algebra_obligation": None,
            "model_interface_instantiations": [
                {"instantiation_id": "dir1", "kind": "sign_convention_equation", "formal_claim": "positive_direction_m1 = toward_pulley"},
                {"instantiation_id": "dir2", "kind": "sign_convention_equation", "formal_claim": "positive_direction_m2 = downward"},
                {"instantiation_id": "mii1", "kind": "local_model_equation", "formal_claim": "T = m1 * a"},
                {"instantiation_id": "mii2", "kind": "local_model_equation", "formal_claim": "m2 * g - T = m2 * a"},
                {"instantiation_id": "mii3", "kind": "local_model_equation", "formal_claim": "Fnet_m1 = T"},
                {"instantiation_id": "mii4", "kind": "local_model_equation", "formal_claim": "a1 = a"},
                {"instantiation_id": "mii5", "kind": "constraint_acceleration_relation", "formal_claim": "a_hanging = a"},
                {"instantiation_id": "mii6", "kind": "sign_or_uniformity_convention", "formal_claim": "T_glider = T"},
            ],
        },
    }


def _mechanics73_model_ir():
    return {
        "sample_id": "s1",
        "model_instances": [
            {
                "instance_id": "mi1",
                "kind": "particle_dynamics_along_track",
                "natural_language": "Model the glider m1 as a particle moving horizontally on a frictionless level track, with tension as the only unbalanced force along the track.",
                "variables": {"mass": "m1", "acceleration": "a", "tension": "T"},
                "coordinate_convention": "For m1, positive x is along the track toward the pulley.",
                "expected_claim": "The net force on m1 along the track equals the string tension, and this net force equals m1 times the common acceleration.",
                "planning_schema_id": "Apply Newton's second law to the glider along the track direction.",
            },
            {
                "instance_id": "mi2",
                "kind": "particle_dynamics_hanging_mass",
                "natural_language": "Model the hanging mass m2 as a particle moving vertically, with weight downward and tension upward.",
                "variables": {"mass": "m2", "acceleration": "a", "tension": "T", "gravity": "g"},
                "coordinate_convention": "For m2, positive y is vertically downward.",
                "expected_claim": "The net downward force on m2 is weight minus tension, and this equals m2 times the common acceleration.",
                "planning_schema_id": "Apply Newton's second law to the hanging mass along the vertical direction.",
            },
        ],
        "interface_instantiations": [
            {
                "instantiation_id": "global_glider_force_equation",
                "kind": "sign_or_constraint_equation",
                "formal_claim": "T = m1 * a",
                "source_model_instance": "mi1",
                "notes": "This is the assembled modeling equation for m1.",
            },
            {
                "instantiation_id": "global_hanging_force_equation",
                "kind": "sign_or_constraint_equation",
                "formal_claim": "m2 * g - T = m2 * a",
                "source_model_instance": "mi2",
                "notes": "This is the assembled modeling equation for m2.",
            },
        ],
    }


def _config(enabled=False, repair=True):
    return SimpleNamespace(
        natural_language_enabled=enabled,
        repair_on_audit_fail=repair,
        max_trace_steps_for_prompt=24,
        max_prompt_chars=8000,
    )


def test_module_deterministic_fallback_when_llm_disabled():
    module = ModuleSolutionRenderer(config=_config(False))
    result = module.run(
        sample={"sample_id": "s1", "problem_text": "求静摩擦系数"},
        grounding={"sample_id": "s1", "problem_ir": {"goal_statement": "求静摩擦系数"}},
        model_ir={"sample_id": "s1"},
        controlled_sketch=None,
        selected_candidate=_candidate(),
        proof_attempts=[{"sample_id": "s1", "attempt_index": 0, "proof_mode": "legacy_full_proof"}],
        proof_check={"sample_id": "s1", "proof_success": True, "proof_mode": "legacy_full_proof"},
    )
    assert result.render_success is True
    assert result.proof_status == "legacy_verified_no_audit"
    assert "缺少 dependency audit" in result.natural_solution


def test_module_llm_enabled_uses_mock_json():
    payload = {
        "natural_solution": "应用物理定律得到 F_start = μ_s W。最终答案 μ_s = \\frac{F_start}{W}。上述物理定律应用和代数推导均已由 Lean 验证。",
        "used_step_ids": ["problem_understanding_1"],
        "mentioned_formulas": ["μ_s = \\frac{F_start}{W}"],
        "verification_note": "ok",
    }
    model = _MockModel([json.dumps(payload, ensure_ascii=False)])
    module = ModuleSolutionRenderer(model_client=model, config=_config(True, False))
    result = module.run(
        sample={"sample_id": "s1"},
        grounding={"sample_id": "s1", "problem_ir": {}},
        model_ir={"sample_id": "s1"},
        controlled_sketch=None,
        selected_candidate=_candidate(),
        proof_attempts=[{"sample_id": "s1", "attempt_index": 0, "proof_mode": "llm_guided_search"}],
        proof_check={"sample_id": "s1", "proof_success": True},
        dependency_audit={"classification": "fully_mechlib_verified", "covered_obligations": ["sk1"]},
    )
    assert model.calls == 1
    assert result.natural_solution == payload["natural_solution"]


def test_module_repairs_after_audit_fail(monkeypatch):
    monkeypatch.setattr(
        "mech_pipeline.modules.solution_renderer.render_deterministic_solution",
        lambda trace: "额外公式 x = y。",
    )
    bad = {"natural_solution": "额外公式 x = y。最终答案 μ_s = F_start / W。", "used_step_ids": [], "mentioned_formulas": []}
    good = {
        "natural_solution": "应用物理定律得到 F_start = μ_s W。最终答案 μ_s = \\frac{F_start}{W}。上述物理定律应用和代数推导均已由 Lean 验证。",
        "used_step_ids": ["sk1"],
        "mentioned_formulas": ["μ_s = \\frac{F_start}{W}"],
    }
    model = _MockModel([json.dumps(bad, ensure_ascii=False), json.dumps(good, ensure_ascii=False)])
    module = ModuleSolutionRenderer(model_client=model, config=_config(True, True))
    result = module.run(
        sample={"sample_id": "s1"},
        grounding={"sample_id": "s1", "problem_ir": {}},
        model_ir={"sample_id": "s1"},
        controlled_sketch=None,
        selected_candidate=_candidate(),
        proof_attempts=[{"sample_id": "s1", "attempt_index": 0, "proof_mode": "llm_guided_search"}],
        proof_check={"sample_id": "s1", "proof_success": True},
        dependency_audit={"classification": "fully_mechlib_verified", "covered_obligations": ["sk1"]},
    )
    assert model.calls == 2
    assert result.render_audit.audit_pass is True
    assert result.natural_solution == good["natural_solution"]


def test_module_semantic_fail_outputs_partial_explanation():
    module = ModuleSolutionRenderer(config=_config(False))
    result = module.run(
        sample={"sample_id": "s1"},
        grounding={"sample_id": "s1", "problem_ir": {}},
        model_ir={"sample_id": "s1"},
        controlled_sketch=None,
        selected_candidate=_candidate(),
        proof_attempts=[],
        proof_check={"sample_id": "s1", "proof_success": False, "error_type": "proof_skipped_due_to_semantic_fail"},
    )
    assert result.proof_status == "proof_skipped_due_to_semantic_fail"
    assert "被跳过" in result.natural_solution


def test_module_legacy_success_no_audit_disclosure():
    module = ModuleSolutionRenderer(config=_config(False))
    result = module.run(
        sample={"sample_id": "s1"},
        grounding={"sample_id": "s1", "problem_ir": {}},
        model_ir={"sample_id": "s1"},
        controlled_sketch=None,
        selected_candidate=_candidate(),
        proof_attempts=[{"sample_id": "s1", "attempt_index": 0, "proof_mode": "legacy_full_proof"}],
        proof_check={"sample_id": "s1", "proof_success": True, "proof_mode": "legacy_full_proof"},
    )
    assert result.proof_status == "legacy_verified_no_audit"
    assert "不能确认所有物理步骤" in result.natural_solution


def test_module_falls_back_when_llm_omits_secondary_final_answer():
    bad = {
        "natural_solution": (
            "最终答案 a = m₂ g / (m₁ + m₂)。"
            "当前形式化证明未通过，因此以下只展示已构造的建模和计划步骤，不作为最终 verified solution。"
        ),
        "used_step_ids": [],
        "mentioned_formulas": ["a = m₂ g / (m₁ + m₂)"],
    }
    model = _MockModel([json.dumps(bad, ensure_ascii=False)])
    module = ModuleSolutionRenderer(model_client=model, config=_config(True, False))

    result = module.run(
        sample={"sample_id": "s1"},
        grounding={"sample_id": "s1", "problem_ir": {}},
        model_ir={"sample_id": "s1"},
        controlled_sketch=None,
        selected_candidate=_multi_target_candidate(),
        proof_attempts=[{"sample_id": "s1", "attempt_index": 0, "proof_mode": "llm_guided_search"}],
        proof_check={"sample_id": "s1", "proof_success": False},
    )

    assert model.calls == 1
    assert result.render_audit.audit_pass is True
    assert "T =" in result.natural_solution
    assert "m₁m₂g" in result.natural_solution


def test_module_renders_generic_textbook_plan_for_two_body_system():
    module = ModuleSolutionRenderer(config=_config(False, True))

    result = module.run(
        sample={"sample_id": "s1"},
        grounding={"sample_id": "s1", "problem_ir": {}},
        model_ir=_mechanics73_model_ir(),
        controlled_sketch=None,
        selected_candidate=_mechanics73_candidate(),
        proof_attempts=[
            {
                "sample_id": "s1",
                "attempt_index": 0,
                "proof_mode": "llm_guided_search",
                "proof_search_trace": {
                    "accepted_actions": [
                        {
                            "action_id": "augment_physical_positive_hypotheses_1",
                            "added_physical_assumptions": [
                                {"variable": "m1", "expression": "0 < m1.val"},
                                {"variable": "m2", "expression": "0 < m2.val"},
                            ],
                        },
                        {"action_id": "side_condition_1", "new_local_fact_claims": ["m1.val + m2.val ≠ 0"]},
                    ]
                },
            }
        ],
        proof_check={"sample_id": "s1", "proof_success": False},
    )

    assert result.render_audit.audit_pass is True
    assert "设小车质量为 m₁，悬挂物质量为 m₂" in result.natural_solution
    assert "取小车运动方向和悬挂物向下方向为正方向" in result.natural_solution
    assert "对小车进行受力分析" in result.natural_solution
    assert "对悬挂物进行受力分析" in result.natural_solution
    assert "T = m₁a。        (1)" in result.natural_solution
    assert "m₂g - m₁a = m₂a" in result.natural_solution
    assert "由 (1) 和 (2) 联立" in result.natural_solution
    assert "\\qquad" in result.natural_solution
    assert "\\frac{m₂g}{m₁ + m₂}" in result.natural_solution
    assert "轨迹中给出" not in result.natural_solution
    assert "目标公式：" not in result.natural_solution
    assert "当前形式化证明未通过" in result.natural_solution
    assert "均已由 Lean 验证" not in result.natural_solution


def test_module_generic_textbook_plan_handles_modeling_only_two_body_equations():
    module = ModuleSolutionRenderer(config=_config(False, True))

    result = module.run(
        sample={"sample_id": "s1"},
        grounding={"sample_id": "s1", "problem_ir": {}},
        model_ir=_mechanics73_model_ir(),
        controlled_sketch=None,
        selected_candidate=_mechanics73_modeling_only_candidate(),
        proof_attempts=[
            {
                "sample_id": "s1",
                "attempt_index": 0,
                "proof_mode": "llm_guided_search",
                "proof_search_trace": {
                    "accepted_actions": [
                        {
                            "action_id": "augment_physical_positive_hypotheses_1",
                            "added_physical_assumptions": [
                                {"variable": "m1", "expression": "0 < m1.val"},
                                {"variable": "m2", "expression": "0 < m2.val"},
                            ],
                        },
                        {"action_id": "side_condition_1", "new_local_fact_claims": ["m1.val + m2.val ≠ 0"]},
                    ]
                },
            }
        ],
        proof_check={"sample_id": "s1", "proof_success": True},
        dependency_audit={"classification": "gap_assisted_success"},
    )

    assert result.render_audit.audit_pass is True
    assert "设小车质量为 m₁，悬挂物质量为 m₂" in result.natural_solution
    assert "对小车进行受力分析" in result.natural_solution
    assert "T = m₁a。        (1)" in result.natural_solution
    assert "m₂g - m₁a = m₂a" in result.natural_solution
    assert "Fnet_m1" not in result.natural_solution
    assert "a1 = a" not in result.natural_solution
    assert "a_hanging = a" not in result.natural_solution
    assert "positive_direction_m1" not in result.natural_solution
    assert "T_glider = T" not in result.natural_solution
    assert "摩擦模型" not in result.natural_solution
    assert "本题 Lean replay 已通过" in result.natural_solution
    assert "gap law" in result.natural_solution
    assert "目标公式：" not in result.natural_solution
