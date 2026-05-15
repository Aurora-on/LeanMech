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

    def generate_text(self, prompt):
        self.calls += 1
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
        "natural_solution": "应用物理定律得到 F_start = μ_s W。最终答案 μ_s = F_start / W。上述物理定律应用和代数推导均已由 Lean 验证。",
        "used_step_ids": ["problem_understanding_1"],
        "mentioned_formulas": ["μ_s = F_start / W"],
        "verification_note": "ok",
    }
    module = ModuleSolutionRenderer(model_client=_MockModel([json.dumps(payload, ensure_ascii=False)]), config=_config(True, False))
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
    assert "最终答案" in result.natural_solution


def test_module_repairs_after_audit_fail():
    bad = {"natural_solution": "额外公式 x = y。最终答案 μ_s = F_start / W。", "used_step_ids": [], "mentioned_formulas": []}
    good = {
        "natural_solution": "应用物理定律得到 F_start = μ_s W。最终答案 μ_s = F_start / W。上述物理定律应用和代数推导均已由 Lean 验证。",
        "used_step_ids": ["sk1"],
        "mentioned_formulas": ["μ_s = F_start / W"],
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
    assert "m₁ m₂ g" in result.natural_solution
