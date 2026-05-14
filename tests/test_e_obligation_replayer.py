from __future__ import annotations

from mech_pipeline.modules.e_obligation_replayer import ProofObligationReplayer
from mech_pipeline.types import ProofActionCheckResult, ProofActionProposal, ProofContext, ProofObligationReplayItem


EXTRACTOR = "MechLib.Dynamics.NewtonLaw.NewtonSecondLaw.to_value_equation"


def _context(item: ProofObligationReplayItem, allowed: list[str] | None = None) -> ProofContext:
    return ProofContext(
        sample_id="s1",
        candidate_id="c1",
        theorem_decl="theorem c1 : True",
        lean_header="import MechLib",
        allowed_verified_decls=allowed if allowed is not None else [EXTRACTOR],
        obligation_replay_items=[item],
    )


def _ok_checker(_context: ProofContext, _prefix: str, proposal: ProofActionProposal) -> ProofActionCheckResult:
    return ProofActionCheckResult(
        action_id=proposal.action_id,
        strategy=proposal.strategy,
        tactic_block=proposal.tactic_block,
        status="progress",
        goals_excerpt="1 goal",
    )


def test_law_to_equation_obligation_generates_have() -> None:
    item = ProofObligationReplayItem(
        obligation_id="sk1",
        kind="law_to_equation",
        from_hypothesis="glider_law",
        must_use=EXTRACTOR,
        formal_claim="Fnet.val = m.val * a.val",
        produced_fact_name="h_obl_1",
    )
    result = ProofObligationReplayer(action_checker=_ok_checker).replay(_context(item))

    assert result.replay_status == "ok"
    assert result.replayed_items[0].replay_status == "replayed"
    assert "have h_obl_1 : Fnet.val = m.val * a.val := by" in result.proof_prefix
    assert f"exact {EXTRACTOR} glider_law" in result.proof_prefix


def test_replayer_records_from_hypothesis_and_must_use() -> None:
    item = ProofObligationReplayItem(
        obligation_id="sk1",
        kind="constraint_to_equation",
        from_hypothesis="constraint_law",
        must_use=EXTRACTOR,
        formal_claim="a1.val = a2.val",
        produced_fact_name="h_constraint",
    )
    result = ProofObligationReplayer(action_checker=_ok_checker).replay(_context(item))

    proposal = result.proposals[0]
    assert proposal.source == "deterministic"
    assert proposal.uses_facts == ["constraint_law"]
    assert proposal.uses_decls == [EXTRACTOR]
    assert "constraint_law" in proposal.tactic_block
    assert EXTRACTOR in proposal.tactic_block


def test_replayer_blocks_missing_must_use() -> None:
    item = ProofObligationReplayItem(
        obligation_id="sk1",
        kind="law_to_equation",
        from_hypothesis="glider_law",
        must_use=None,
        formal_claim="Fnet.val = m.val * a.val",
        produced_fact_name="h_obl_1",
    )
    result = ProofObligationReplayer(action_checker=_ok_checker).replay(_context(item))

    assert result.replay_status == "blocked"
    assert result.blocked_items[0].error == "extractor_decl_mismatch"
    assert result.proposals == []
    assert result.proof_prefix == ""


def test_replayer_blocks_missing_from_hypothesis() -> None:
    item = ProofObligationReplayItem(
        obligation_id="sk1",
        kind="law_to_equation",
        from_hypothesis=None,
        must_use=EXTRACTOR,
        formal_claim="Fnet.val = m.val * a.val",
        produced_fact_name="h_obl_1",
    )
    result = ProofObligationReplayer(action_checker=_ok_checker).replay(_context(item))

    assert result.replay_status == "blocked"
    assert result.blocked_items[0].error == "from_hypothesis_missing"
    assert result.proposals == []


def test_replayer_does_not_use_schema_metadata_as_proof_fact() -> None:
    schema_decl = "law.schema.newton_second_law"
    item = ProofObligationReplayItem(
        obligation_id="sk_schema",
        kind="law_to_equation",
        from_hypothesis="schema_law",
        must_use=schema_decl,
        formal_claim="Fnet.val = m.val * a.val",
        produced_fact_name="h_schema",
    )
    result = ProofObligationReplayer(action_checker=_ok_checker).replay(_context(item, allowed=[]))

    assert result.replay_status == "blocked"
    assert result.blocked_items[0].error == "extractor_decl_mismatch"
    assert result.proposals == []
    assert schema_decl not in result.proof_prefix


def test_replayer_tries_structured_alternatives_after_failure() -> None:
    item = ProofObligationReplayItem(
        obligation_id="sk1",
        kind="law_to_equation",
        from_hypothesis="glider_law",
        must_use=EXTRACTOR,
        formal_claim="Fnet.val = m.val * a.val",
        produced_fact_name="h_obl_1",
    )

    def checker(_context: ProofContext, _prefix: str, proposal: ProofActionProposal) -> ProofActionCheckResult:
        if proposal.strategy == "deterministic_simpa_using_extractor":
            status = "progress"
            error_type = None
        else:
            status = "invalid"
            error_type = "formal_claim_shape_mismatch"
        return ProofActionCheckResult(
            action_id=proposal.action_id,
            strategy=proposal.strategy,
            tactic_block=proposal.tactic_block,
            status=status,
            error_type=error_type,
        )

    result = ProofObligationReplayer(action_checker=checker).replay(_context(item))

    assert result.replay_status == "ok"
    assert len(result.action_checks) == 2
    assert result.action_checks[0].status == "invalid"
    assert result.action_checks[1].status == "progress"
    assert "simpa using" in result.proof_prefix


def test_replayer_reports_type_mismatch_as_extractor_decl_mismatch() -> None:
    item = ProofObligationReplayItem(
        obligation_id="sk1",
        kind="law_to_equation",
        from_hypothesis="glider_law",
        must_use=EXTRACTOR,
        formal_claim="Fnet.val = m.val * a.val",
        produced_fact_name="h_obl_1",
    )

    def checker(_context: ProofContext, _prefix: str, proposal: ProofActionProposal) -> ProofActionCheckResult:
        return ProofActionCheckResult(
            action_id=proposal.action_id,
            strategy=proposal.strategy,
            tactic_block=proposal.tactic_block,
            status="invalid",
            error_type="type_mismatch",
            error_message="Application type mismatch: The argument",
        )

    result = ProofObligationReplayer(action_checker=checker).replay(_context(item))

    assert result.replay_status == "blocked"
    assert result.proof_prefix == ""
    assert result.blocked_items[0].error == "missing_proof_friendly_extractor"
    assert result.failure_tags == ["missing_proof_friendly_extractor"]
    assert len(result.action_checks) == 1
