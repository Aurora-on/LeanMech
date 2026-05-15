from mech_pipeline.modules.solution_renderer import build_solution_trace


def _base_evidence(status="fully_mechlib_verified"):
    return {
        "sample_id": "s1",
        "candidate_id": "c1",
        "proof_status": status,
        "target": "mu_s.val = F_start.val / W.val",
        "problem_ir": {"goal_statement": "求静摩擦系数"},
        "model_ir": {"model_instances": [{"instance_id": "m1", "kind": "friction", "natural_language": "最大静摩擦模型"}]},
        "controlled_sketch_steps": [
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
        "blocked_law_steps": [],
        "proof_obligations": [],
        "accepted_actions": [{"action_id": "a1", "proof_obligation_id": "sk1"}],
        "dependency_audit": {"covered_obligations": ["sk1"], "classification": status},
        "algebra_obligation": {"obligation_id": "alg1", "formal_claim": "mu_s.val = F_start.val / W.val"},
        "final_answers": [{"formula_id": "ans", "formal_formula": "mu_s.val = F_start.val / W.val"}],
        "warnings": [],
        "source_status": {},
    }


def test_trace_builds_verified_law_application_from_sketch_and_obligations():
    trace = build_solution_trace(_base_evidence())
    law_steps = [step for step in trace.steps if step.kind == "law_application"]
    assert law_steps
    assert law_steps[0].verified is True
    assert law_steps[0].verified_decl == "MechLib.Friction.staticFrictionMax"


def test_blocked_law_steps_are_not_verified():
    evidence = _base_evidence()
    evidence["blocked_law_steps"] = [{"step_id": "sk1", "binding_status": "gap_schema_only"}]
    trace = build_solution_trace(evidence)
    law_step = next(step for step in trace.steps if step.kind == "law_application")
    assert law_step.verified is False
    assert law_step.gap_assisted is True


def test_gap_schema_only_not_verified():
    evidence = _base_evidence()
    evidence["controlled_sketch_steps"][0]["binding_status"] = "gap_schema_only"
    trace = build_solution_trace(evidence)
    law_step = next(step for step in trace.steps if step.kind == "law_application")
    assert law_step.verified is False


def test_legacy_success_no_audit_status_kept():
    trace = build_solution_trace(_base_evidence("legacy_verified_no_audit"))
    assert trace.proof_status == "legacy_verified_no_audit"


def test_proof_failed_final_answer_not_verified():
    trace = build_solution_trace(_base_evidence("proof_failed"))
    assert trace.final_answers
    assert trace.final_answers[0].verified is False
