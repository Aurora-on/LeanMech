from __future__ import annotations

import json

from mech_pipeline.types import (
    ProofActionCheckResult,
    ProofActionProposal,
    ProofContext,
    ProofDependencyAudit,
    ProofObligationReplayItem,
    ProofSearchNode,
    ProofSearchTrace,
)


def test_proof_search_types_are_json_serializable() -> None:
    replay = ProofObligationReplayItem(
        obligation_id="sk1",
        kind="law_to_equation",
        from_hypothesis="glider_law",
        must_use="MechLib.Dynamics.NewtonLaw.NewtonSecondLaw.to_value_equation",
        formal_claim="Fnet.val = m.val * a.val",
        produced_fact_name="h_glider_eq",
    )
    proposal = ProofActionProposal(
        action_id="a1",
        strategy="apply_extractor",
        tactic_block="have h_glider_eq := MechLib.Dynamics.NewtonLaw.NewtonSecondLaw.to_value_equation glider_law",
        uses_facts=["glider_law"],
        uses_decls=["MechLib.Dynamics.NewtonLaw.NewtonSecondLaw.to_value_equation"],
        expected_effect="adds value-level Newton equation",
        source="deterministic",
        priority=1.0,
    )
    check = ProofActionCheckResult(
        action_id="a1",
        strategy="apply_extractor",
        tactic_block=proposal.tactic_block,
        status="progress",
        goals_excerpt="1 goal",
    )
    node = ProofSearchNode(
        node_id="n1",
        parent_id=None,
        depth=0,
        proof_prefix="",
        local_facts=["glider_law"],
        remaining_obligations=["sk1"],
        score=1.0,
    )
    trace = ProofSearchTrace(
        sample_id="s1",
        candidate_id="c1",
        nodes_expanded=1,
        llm_calls=0,
        accepted_actions=[check.to_dict()],
        rejected_actions=[],
        search_status="in_progress",
    )
    audit = ProofDependencyAudit(
        sample_id="s1",
        candidate_id="c1",
        proof_success=False,
        used_verified_decls=proposal.uses_decls,
        required_verified_decls=proposal.uses_decls,
        covered_obligations=["sk1"],
        gap_assisted=False,
        fully_mechlib_verified=True,
        classification="partial_trace",
    )
    context = ProofContext(
        sample_id="s1",
        candidate_id="c1",
        theorem_decl="theorem c1 : True",
        lean_header="import MechLib",
        proof_obligations=[{"step_id": "sk1"}],
        allowed_verified_decls=proposal.uses_decls,
        obligation_replay_items=[replay],
    )

    for payload in (
        replay.to_dict(),
        proposal.to_dict(),
        check.to_dict(),
        node.to_dict(),
        trace.to_dict(),
        audit.to_dict(),
        context.to_dict(),
    ):
        assert isinstance(json.loads(json.dumps(payload)), dict)
