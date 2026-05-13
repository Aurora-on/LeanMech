from __future__ import annotations

from mech_pipeline.modules.e_certified_replay import run_deterministic_obligation_replay_with_probe
from mech_pipeline.types import ProofActionCheckResult, ProofContext, ProofObligationReplayItem


EXTRACTOR = "MechLib.Dynamics.NewtonLaw.NewtonSecondLaw.to_value_equation"


class FakeLeanRunner:
    def probe_proof_prefix(self, *, lean_header, theorem_decl, proof_prefix, timeout_s=None):
        _ = (lean_header, theorem_decl, timeout_s)
        if "exact" in proof_prefix:
            return ProofActionCheckResult(
                action_id="probe",
                strategy="probe_proof_prefix",
                tactic_block=proof_prefix,
                status="progress",
                goals_excerpt="unsolved goals",
            )
        return ProofActionCheckResult(
            action_id="probe",
            strategy="probe_proof_prefix",
            tactic_block=proof_prefix,
            status="invalid",
            error_type="type_mismatch",
        )


def test_certified_replay_writes_action_rows_and_trace_payloads() -> None:
    context = ProofContext(
        sample_id="s1",
        candidate_id="c1",
        theorem_decl="theorem c1 : True",
        lean_header="import MechLib",
        allowed_verified_decls=[EXTRACTOR],
        obligation_replay_items=[
            ProofObligationReplayItem(
                obligation_id="sk1",
                kind="law_to_equation",
                from_hypothesis="glider_law",
                must_use=EXTRACTOR,
                formal_claim="Fnet.val = m.val * a.val",
                produced_fact_name="h_obl_1",
            )
        ],
    )

    run = run_deterministic_obligation_replay_with_probe(
        context=context,
        lean_runner=FakeLeanRunner(),  # type: ignore[arg-type]
        timeout_s=10,
    )

    assert run.replay_result.replay_status == "ok"
    assert run.action_check_rows
    assert run.action_check_rows[0]["sample_id"] == "s1"
    assert run.action_check_rows[0]["candidate_id"] == "c1"
    assert run.action_check_rows[0]["accepted"] is True
    assert run.trace.nodes_expanded == 1
    assert len(run.trace.accepted_actions) == 1
    assert run.trace.rejected_actions == []
    assert run.dependency_audit.used_verified_decls == [EXTRACTOR]
    assert run.dependency_audit.covered_obligations == ["sk1"]
