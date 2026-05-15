from mech_pipeline.modules.solution_renderer import collect_solution_evidence


def _candidate():
    return {
        "sample_id": "s1",
        "candidate_id": "c1",
        "theorem_decl": "theorem t : mu_s.val = F_start.val / W.val := by",
        "proof_obligations": [
            {
                "step_id": "sk1",
                "kind": "law_to_equation",
                "formal_claim": "F_start.val = mu_s.val * W.val",
                "binding_status": "ok",
                "proof_fact_allowed": True,
                "verified_decl": "MechLib.Friction.staticFrictionMax",
            }
        ],
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


def test_collect_llm_guided_with_dependency_audit():
    evidence = collect_solution_evidence(
        problem_ir=None,
        model_ir=None,
        controlled_sketch=None,
        theorem_candidate=_candidate(),
        proof_attempt={"sample_id": "s1", "attempt_index": 0, "proof_mode": "llm_guided_search"},
        proof_check={"sample_id": "s1", "proof_success": True, "selected_candidate_id": "c1"},
        proof_search_trace={"accepted_actions": [{"action_id": "a1", "proof_obligation_id": "sk1"}]},
        dependency_audit={"classification": "fully_mechlib_verified", "covered_obligations": ["sk1"]},
    )
    assert evidence["proof_status"] == "fully_mechlib_verified"
    assert evidence["accepted_actions"][0]["action_id"] == "a1"


def test_collect_legacy_success_without_audit():
    evidence = collect_solution_evidence(
        problem_ir=None,
        model_ir=None,
        controlled_sketch=None,
        theorem_candidate=_candidate(),
        proof_attempt={"sample_id": "s1", "attempt_index": 0, "proof_mode": "legacy_full_proof"},
        proof_check={"sample_id": "s1", "proof_success": True, "proof_mode": "legacy_full_proof"},
        proof_search_trace=None,
        dependency_audit=None,
    )
    assert evidence["proof_status"] == "legacy_verified_no_audit"
    assert "dependency_audit_missing_or_empty" in evidence["warnings"]


def test_collect_semantic_fail_skip():
    evidence = collect_solution_evidence(
        problem_ir=None,
        model_ir=None,
        controlled_sketch=None,
        theorem_candidate=_candidate(),
        proof_attempt=None,
        proof_check={"sample_id": "s1", "proof_success": False, "error_type": "proof_skipped_due_to_semantic_fail"},
        proof_search_trace=None,
        dependency_audit=None,
    )
    assert evidence["proof_status"] == "proof_skipped_due_to_semantic_fail"


def test_collect_proof_failed():
    evidence = collect_solution_evidence(
        problem_ir=None,
        model_ir=None,
        controlled_sketch=None,
        theorem_candidate=_candidate(),
        proof_attempt=None,
        proof_check={"sample_id": "s1", "proof_success": False, "error_type": "proof_search_failure"},
        proof_search_trace=None,
        dependency_audit=None,
    )
    assert evidence["proof_status"] == "proof_failed"


def test_collect_uses_embedded_trace_when_file_trace_empty():
    evidence = collect_solution_evidence(
        problem_ir=None,
        model_ir=None,
        controlled_sketch=None,
        theorem_candidate=_candidate(),
        proof_attempt={
            "sample_id": "s1",
            "attempt_index": 0,
            "proof_mode": "llm_guided_search",
            "proof_search_trace": {"accepted_actions": [{"action_id": "embedded"}]},
        },
        proof_check={"sample_id": "s1", "proof_success": False},
        proof_search_trace=None,
        dependency_audit=None,
    )
    assert evidence["accepted_actions"][0]["action_id"] == "embedded"


def test_collect_target_spec_secondary_formulas_as_final_answers():
    evidence = collect_solution_evidence(
        problem_ir=None,
        model_ir=None,
        controlled_sketch=None,
        theorem_candidate=_multi_target_candidate(),
        proof_attempt={"sample_id": "s1", "attempt_index": 0, "proof_mode": "llm_guided_search"},
        proof_check={"sample_id": "s1", "proof_success": False},
        proof_search_trace=None,
        dependency_audit=None,
    )

    assert evidence["target"] == (
        "a.val = (m2.val * g.val) / (m1.val + m2.val)"
        " ∧ T.val = (m1.val * m2.val * g.val) / (m1.val + m2.val)"
    )
    assert [row["formal_formula"] for row in evidence["final_answers"]] == [
        "a.val = (m2.val * g.val) / (m1.val + m2.val)",
        "T.val = (m1.val * m2.val * g.val) / (m1.val + m2.val)",
    ]
