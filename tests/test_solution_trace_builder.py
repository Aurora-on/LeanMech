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


def test_conjunction_target_splits_without_dropping_denominator_parentheses():
    evidence = _base_evidence("proof_failed")
    evidence["target"] = (
        "a.val = (m2.val * g.val) / (m1.val + m2.val)"
        " ∧ T.val = (m1.val * m2.val * g.val) / (m1.val + m2.val)"
    )
    evidence["final_answers"] = []

    trace = build_solution_trace(evidence)

    assert [formula.formal_formula for formula in trace.final_answers] == [
        "a.val = (m2.val * g.val) / (m1.val + m2.val)",
        "T.val = (m1.val * m2.val * g.val) / (m1.val + m2.val)",
    ]


def test_two_body_linear_system_adds_structured_algebra_step():
    evidence = _base_evidence("proof_failed")
    evidence["target"] = (
        "a = (m2 * g) / (m1 + m2)"
        " ∧ T = (m1 * m2 * g) / (m1 + m2)"
    )
    evidence["controlled_sketch_steps"] = [
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
    ]
    evidence["final_answers"] = []
    evidence["accepted_actions"] = [
        {
            "action_id": "augment_physical_positive_hypotheses_1",
            "added_physical_assumptions": [
                {"variable": "m1", "expression": "0 < m1.val"},
                {"variable": "m2", "expression": "0 < m2.val"},
            ],
        },
        {"action_id": "side_condition_1", "new_local_fact_claims": ["m1.val + m2.val ≠ 0"]},
    ]

    trace = build_solution_trace(evidence)
    algebra = next(step for step in trace.steps if step.step_id == "algebra_elimination_two_body_linear_1")

    assert algebra.verified is False
    assert [formula.display_formula for formula in algebra.output_formulas] == [
        "m₂g - m₁a = m₂a",
        "m₂g = (m₁ + m₂)a",
        "m₁ + m₂ ≠ 0",
    ]
