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
