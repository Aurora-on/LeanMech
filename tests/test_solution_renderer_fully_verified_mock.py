from types import SimpleNamespace

from mech_pipeline.modules.solution_renderer import ModuleSolutionRenderer


def test_fully_verified_mock_allows_verified_disclosure():
    module = ModuleSolutionRenderer(
        config=SimpleNamespace(
            natural_language_enabled=False,
            repair_on_audit_fail=True,
            max_trace_steps_for_prompt=24,
            max_prompt_chars=8000,
        )
    )
    result = module.run(
        sample={"sample_id": "mock_full"},
        grounding={"sample_id": "mock_full", "problem_ir": {"goal_statement": "求加速度"}},
        model_ir={"sample_id": "mock_full"},
        controlled_sketch={
            "sample_id": "mock_full",
            "proof_steps": [
                {
                    "step_id": "sk1",
                    "kind": "law_to_equation",
                    "formal_claim": "Fnet.val = m1.val * a.val",
                    "binding_status": "ok",
                    "proof_fact_allowed": True,
                    "verified_decl": "MechLib.Dynamics.NewtonLaw.newtonSecondLaw_course_form",
                }
            ],
            "algebra_obligation": {"obligation_id": "alg1", "formal_claim": "a.val = Fnet.val / m1.val"},
        },
        selected_candidate={
            "sample_id": "mock_full",
            "candidate_id": "c1",
            "theorem_decl": "theorem t : a.val = Fnet.val / m1.val := by",
        },
        proof_attempts=[{"sample_id": "mock_full", "attempt_index": 0, "proof_mode": "llm_guided_search"}],
        proof_check={"sample_id": "mock_full", "proof_success": True, "proof_mode": "llm_guided_search"},
        dependency_audit={
            "classification": "fully_mechlib_verified",
            "covered_obligations": ["sk1", "alg1"],
            "used_verified_decls": ["MechLib.Dynamics.NewtonLaw.newtonSecondLaw_course_form"],
            "missing_obligations": [],
        },
    )
    assert result.proof_status == "fully_mechlib_verified"
    assert "上述物理定律应用和代数推导均已由 Lean 验证" in result.natural_solution
    assert result.render_audit.audit_pass is True
