from types import SimpleNamespace

from mech_pipeline.modules.solution_renderer import ModuleSolutionRenderer


def test_mechanics74_legacy_success_no_audit_regression():
    module = ModuleSolutionRenderer(
        config=SimpleNamespace(
            natural_language_enabled=False,
            repair_on_audit_fail=True,
            max_trace_steps_for_prompt=24,
            max_prompt_chars=8000,
        )
    )
    candidate = {
        "sample_id": "Mechanics_74_University",
        "candidate_id": "c74",
        "theorem_decl": "theorem t : mu_s.val = F_start.val / W.val := by",
        "controlled_sketch": {
            "sample_id": "Mechanics_74_University",
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
    result = module.run(
        sample={"sample_id": "Mechanics_74_University", "problem_text": "Find coefficient of static friction."},
        grounding={"sample_id": "Mechanics_74_University", "problem_ir": {"goal_statement": "求静摩擦系数"}},
        model_ir={"sample_id": "Mechanics_74_University"},
        controlled_sketch=None,
        selected_candidate=candidate,
        proof_attempts=[{"sample_id": "Mechanics_74_University", "attempt_index": 0, "proof_mode": "legacy_full_proof"}],
        proof_check={"sample_id": "Mechanics_74_University", "proof_success": True, "proof_mode": "legacy_full_proof"},
    )
    assert result.proof_status == "legacy_verified_no_audit"
    assert "Lean proof 已通过" in result.natural_solution
    assert "缺少 dependency audit" in result.natural_solution
    assert "不能确认所有物理步骤" in result.natural_solution
