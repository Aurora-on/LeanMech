from __future__ import annotations

from dataclasses import dataclass

from mech_pipeline.adapters.lean_runner import LeanRunner
from mech_pipeline.modules.e_obligation_replayer import ObligationReplayResult, ProofObligationReplayer
from mech_pipeline.types import (
    ProofActionCheckResult,
    ProofActionProposal,
    ProofContext,
    ProofDependencyAudit,
    ProofSearchTrace,
)


def probe_action_checker(lean_runner: LeanRunner, timeout_s: int | None = None):
    def _check(
        context: ProofContext,
        proof_prefix: str,
        proposal: ProofActionProposal,
    ) -> ProofActionCheckResult:
        result = lean_runner.probe_proof_prefix(
            lean_header=context.lean_header,
            theorem_decl=context.theorem_decl,
            proof_prefix=proof_prefix,
            timeout_s=timeout_s,
        )
        return ProofActionCheckResult(
            action_id=proposal.action_id,
            strategy=proposal.strategy,
            tactic_block=proposal.tactic_block,
            status=result.status,
            error_type=result.error_type,
            error_message=result.error_message,
            stderr_excerpt=result.stderr_excerpt,
            goals_excerpt=result.goals_excerpt,
        )

    return _check


@dataclass
class CertifiedReplayRun:
    replay_result: ObligationReplayResult
    trace: ProofSearchTrace
    dependency_audit: ProofDependencyAudit
    action_check_rows: list[dict[str, object]]


def _proposal_map(result: ObligationReplayResult) -> dict[str, ProofActionProposal]:
    return {proposal.action_id: proposal for proposal in result.proposals}


def _accepted_action_ids(result: ObligationReplayResult) -> set[str]:
    return {check.action_id for check in result.action_checks if check.status in {"progress", "closed"}}


def _action_payload(
    *,
    context: ProofContext,
    check: ProofActionCheckResult,
    proposal: ProofActionProposal | None,
    accepted: bool,
) -> dict[str, object]:
    payload = {
        "sample_id": context.sample_id,
        "candidate_id": context.candidate_id,
        "accepted": accepted,
        **check.to_dict(),
    }
    if proposal is not None:
        payload["source"] = proposal.source
        payload["uses_facts"] = list(proposal.uses_facts)
        payload["uses_decls"] = list(proposal.uses_decls)
        payload["expected_effect"] = proposal.expected_effect
        payload["priority"] = proposal.priority
    return payload


def _dependency_audit(context: ProofContext, result: ObligationReplayResult) -> ProofDependencyAudit:
    accepted_ids = _accepted_action_ids(result)
    proposal_by_id = _proposal_map(result)
    used_decls: list[str] = []
    for action_id in accepted_ids:
        proposal = proposal_by_id.get(action_id)
        if proposal is not None:
            used_decls.extend(proposal.uses_decls)
    required_decls = [item.must_use or "" for item in context.obligation_replay_items if item.must_use]
    covered = [item.obligation_id for item in result.replayed_items]
    required_obligations = [item.obligation_id for item in context.obligation_replay_items]
    missing_obligations = [item for item in required_obligations if item not in set(covered)]
    missing_required_decls = [decl for decl in required_decls if decl not in set(used_decls)]
    gap_assisted = bool(context.gap_laws or context.explicit_model_gaps or context.obligation_replay_blocked)
    fully_verified = not gap_assisted and not missing_obligations and not missing_required_decls
    return ProofDependencyAudit(
        sample_id=context.sample_id,
        candidate_id=context.candidate_id,
        proof_success=False,
        used_verified_decls=sorted(set(decl for decl in used_decls if decl)),
        required_verified_decls=sorted(set(decl for decl in required_decls if decl)),
        missing_required_decls=sorted(set(decl for decl in missing_required_decls if decl)),
        covered_obligations=covered,
        missing_obligations=missing_obligations,
        gap_assisted=gap_assisted,
        fully_mechlib_verified=fully_verified,
        classification="deterministic_obligation_replay",
    )


def run_deterministic_obligation_replay_with_probe(
    *,
    context: ProofContext,
    lean_runner: LeanRunner,
    timeout_s: int | None = None,
) -> CertifiedReplayRun:
    replayer = ProofObligationReplayer(action_checker=probe_action_checker(lean_runner, timeout_s=timeout_s))
    replay_result = replayer.replay(context)
    proposal_by_id = _proposal_map(replay_result)
    accepted_ids = _accepted_action_ids(replay_result)
    action_rows = [
        _action_payload(
            context=context,
            check=check,
            proposal=proposal_by_id.get(check.action_id),
            accepted=check.action_id in accepted_ids,
        )
        for check in replay_result.action_checks
    ]
    accepted_actions = [row for row in action_rows if bool(row.get("accepted"))]
    rejected_actions = [row for row in action_rows if not bool(row.get("accepted"))]
    trace = ProofSearchTrace(
        sample_id=context.sample_id,
        candidate_id=context.candidate_id,
        nodes_expanded=len(replay_result.action_checks),
        llm_calls=0,
        accepted_actions=accepted_actions,
        rejected_actions=rejected_actions,
        final_proof_body=None,
        search_status=f"deterministic_obligation_replay_{replay_result.replay_status}",
        failure_reason=";".join(replay_result.failure_tags) if replay_result.failure_tags else None,
    )
    return CertifiedReplayRun(
        replay_result=replay_result,
        trace=trace,
        dependency_audit=_dependency_audit(context, replay_result),
        action_check_rows=action_rows,
    )
