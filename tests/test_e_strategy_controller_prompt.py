from __future__ import annotations

from pathlib import Path

from mech_pipeline.modules.e_strategy_controller import LLMStrategyController
from mech_pipeline.types import ProofContext, ProofObligationReplayItem


def _context() -> ProofContext:
    return ProofContext(
        sample_id="s1",
        candidate_id="c1",
        theorem_decl="theorem c1 : True",
        lean_header="import MechLib",
        target_formula="T.val = m1.val * a.val",
        allowed_local_facts=["hFnet1", "h_mi1"],
        allowed_verified_decls=["MechLib.Dynamics.NewtonLaw.NewtonSecondLaw.to_value_equation"],
        obligation_replay_items=[
            ProofObligationReplayItem(
                obligation_id="sk1",
                kind="law_to_equation",
                from_hypothesis="glider_law",
                must_use="MechLib.Dynamics.NewtonLaw.NewtonSecondLaw.to_value_equation",
                formal_claim="Fnet1.val = m1.val * a.val",
                produced_fact_name="h_mi1",
            )
        ],
        mechlib_context_excerpt="FULL RETRIEVAL CONTEXT SHOULD NOT APPEAR",
    )


def test_strategy_controller_prompt_is_compact_and_not_full_retrieval_context() -> None:
    prompt = LLMStrategyController(Path("prompts/E_strategy_controller.md")).build_prompt(
        proof_context=_context(),
        last_error="type mismatch",
        failed_actions=[{"tactic_block": "exact bad"}],
    )

    assert "FULL RETRIEVAL CONTEXT SHOULD NOT APPEAR" not in prompt
    assert "retrieval_context" not in prompt


def test_strategy_controller_prompt_does_not_ask_for_complete_proof() -> None:
    prompt = LLMStrategyController(Path("prompts/E_strategy_controller.md")).build_prompt(
        proof_context=_context()
    )

    assert "not a complete proof" in prompt
    assert "complete Lean proof" not in prompt
    assert "full proof body" not in prompt


def test_strategy_controller_prompt_requires_json_proposals() -> None:
    prompt = LLMStrategyController(Path("prompts/E_strategy_controller.md")).build_prompt(
        proof_context=_context()
    )

    assert "Return JSON only" in prompt
    assert '"proposals"' in prompt
    assert '"tactic_block"' in prompt


def test_strategy_controller_prompt_contains_allowed_decls_whitelist() -> None:
    prompt = LLMStrategyController(Path("prompts/E_strategy_controller.md")).build_prompt(
        proof_context=_context()
    )

    assert '"allowed_decls"' in prompt
    assert "MechLib.Dynamics.NewtonLaw.NewtonSecondLaw.to_value_equation" in prompt


def test_strategy_controller_prompt_keeps_complete_forall_target() -> None:
    context = _context()
    context.target_formula = "forall t0 : Real, 0 <= t0 ∧ t0 <= 4 -> (v t0).val = 6 * t0 - 2"

    prompt = LLMStrategyController(Path("prompts/E_strategy_controller.md")).build_prompt(
        proof_context=context,
    )

    assert "forall t0 : Real, 0 <= t0 ∧ t0 <= 4 -> (v t0).val = 6 * t0 - 2" in prompt
    assert '"target": "Real,' not in prompt


def test_strategy_controller_prompt_includes_target_components_for_conjunction() -> None:
    context = _context()
    context.target_formula = "rho.val = r.val ∧ a_t.val = 0 ∧ rho.val = s.val"

    prompt = LLMStrategyController(Path("prompts/E_strategy_controller.md")).build_prompt(
        proof_context=context,
    )

    assert '"target_components"' in prompt
    assert "rho.val = r.val" in prompt
    assert "a_t.val = 0" in prompt


def test_strategy_controller_prompt_flattens_nested_target_components_after_domain() -> None:
    context = _context()
    context.target_formula = (
        "forall t0 : Real, 0 <= t0 ∧ t0 <= 4 -> "
        "A ∧ B ∧ (C ∧ D)"
    )

    prompt = LLMStrategyController(Path("prompts/E_strategy_controller.md")).build_prompt(
        proof_context=context,
        local_facts=["hA : A", "hC : C"],
        search_mode="target_proof_from_available_facts",
    )

    assert '"target_components": [\n    "A",\n    "B",\n    "C",\n    "D"\n  ]' in prompt
    assert '"matched_fact": "hA"' in prompt
    assert '"matched_fact": "hC"' in prompt
    assert '"claim": "0 <= t0' not in prompt
    assert '"claim": "t0 <= 4' not in prompt


def test_strategy_controller_prompt_classifies_log_exp_target() -> None:
    context = _context()
    context.target_formula = "n = Real.log (M / m) / (2 * Real.pi * mu)"

    prompt = LLMStrategyController(Path("prompts/E_strategy_controller.md")).build_prompt(
        proof_context=context,
        local_facts=["hcapstan : M / m = Real.exp (mu * theta)"],
        search_mode="target_proof_from_available_facts",
    )

    assert '"proof_target_classification": "log_exp_solve"' in prompt
    assert "first derive a log equation using" in prompt
    assert "Real.log_exp" in prompt


def test_strategy_controller_prompt_classifies_sqrt_target() -> None:
    context = _context()
    context.target_formula = "v_max.val = Real.sqrt y"

    prompt = LLMStrategyController(Path("prompts/E_strategy_controller.md")).build_prompt(
        proof_context=context,
        local_facts=["h_vmax_formula : v_max.val = Real.sqrt y"],
        search_mode="target_proof_from_available_facts",
    )

    assert '"proof_target_classification": "sqrt_square_solve"' in prompt
    assert "matching sqrt formula" in prompt
    assert "nlinarith" in prompt
