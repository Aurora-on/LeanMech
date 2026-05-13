from __future__ import annotations

import json

from mech_pipeline.config import PipelineConfig
from mech_pipeline.modules.e_dependency_audit import audit_proof_dependencies
from mech_pipeline.modules.e_search_controller import run_llm_guided_search
from mech_pipeline.types import ProofActionCheckResult, ProofContext, ProofObligationReplayItem


GLIDER_EXTRACTOR = "MechLib.Dynamics.NewtonLaw.NewtonSecondLaw.to_value_equation"
HANGER_EXTRACTOR = "MechLib.Dynamics.NewtonLaw.NewtonSecondLaw.to_value_equation"


class AirtrackLLM:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generate_text(self, prompt: str):
        self.prompts.append(prompt)

        class Response:
            text = json.dumps(
                {
                    "proposals": [
                        {
                            "strategy": "algebra_solve",
                            "tactic_block": "nlinarith [h_obl_glider, h_obl_hanger, h_net_glider, h_net_hanger]",
                            "uses_facts": [
                                "h_obl_glider",
                                "h_obl_hanger",
                                "h_net_glider",
                                "h_net_hanger",
                            ],
                            "uses_decls": [],
                            "expected_effect": "close the airtrack acceleration equation after law extraction",
                            "priority": 1.0,
                        }
                    ]
                }
            )

        return Response()


class AirtrackLeanRunner:
    def __init__(self) -> None:
        self.probes: list[str] = []
        self.verify_calls: list[str] = []

    def probe_proof_prefix(self, *, lean_header, theorem_decl, proof_prefix, timeout_s=None):
        _ = (lean_header, theorem_decl, timeout_s)
        self.probes.append(proof_prefix)
        if "nlinarith [h_obl_glider, h_obl_hanger, h_net_glider, h_net_hanger]" in proof_prefix:
            status = "closed"
        elif GLIDER_EXTRACTOR in proof_prefix or HANGER_EXTRACTOR in proof_prefix:
            status = "progress"
        else:
            status = "invalid"
        return ProofActionCheckResult(
            action_id="probe",
            strategy="probe_proof_prefix",
            tactic_block=proof_prefix,
            status=status,
            error_type=None if status != "invalid" else "tactic_failed",
            goals_excerpt="unsolved goals" if status == "progress" else None,
        )

    def verify_proof(self, *, sample_id, candidate_id, lean_header, theorem_decl, proof_body, run_dir):
        _ = (sample_id, candidate_id, lean_header, theorem_decl, run_dir)
        self.verify_calls.append(proof_body)
        return {"strict_pass": "nlinarith" in proof_body}


def _airtrack_context() -> ProofContext:
    return ProofContext(
        sample_id="airtrack",
        candidate_id="airtrack_c1",
        theorem_decl=(
            "theorem airtrack_demo "
            "(glider_law hanger_law h_net_glider h_net_hanger : True) : True"
        ),
        lean_header="import MechLib",
        target_formula="a.val = m2.val * g.val / (m1.val + m2.val)",
        local_hypotheses=["glider_law", "hanger_law", "h_net_glider", "h_net_hanger"],
        allowed_local_facts=["glider_law", "hanger_law", "h_net_glider", "h_net_hanger"],
        allowed_verified_decls=[GLIDER_EXTRACTOR, HANGER_EXTRACTOR],
        obligation_replay_items=[
            ProofObligationReplayItem(
                obligation_id="sk_glider",
                kind="law_to_equation",
                from_hypothesis="glider_law",
                must_use=GLIDER_EXTRACTOR,
                formal_claim="Fnet1.val = m1.val * a.val",
                produced_fact_name="h_obl_glider",
            ),
            ProofObligationReplayItem(
                obligation_id="sk_hanger",
                kind="law_to_equation",
                from_hypothesis="hanger_law",
                must_use=HANGER_EXTRACTOR,
                formal_claim="Fnet2.val = m2.val * a.val",
                produced_fact_name="h_obl_hanger",
            ),
        ],
    )


def test_airtrack_mock_llm_guided_search_replays_obligations_and_closes() -> None:
    cfg = PipelineConfig()
    cfg.proof.llm_guided_search.max_nodes = 4
    cfg.proof.llm_guided_search.max_llm_calls = 1
    cfg.proof.llm_guided_search.deterministic_side_conditions_first = False
    llm = AirtrackLLM()
    runner = AirtrackLeanRunner()
    context = _airtrack_context()

    trace = run_llm_guided_search(
        proof_context=context,
        lean_runner=runner,
        llm_client=llm,
        cfg=cfg,
    )
    audit = audit_proof_dependencies(
        proof_context=context,
        proof_body=trace.final_proof_body or "",
        final_replay_pass=trace.search_status == "success",
    )

    assert trace.search_status == "success"
    assert trace.final_proof_body is not None
    assert GLIDER_EXTRACTOR in trace.final_proof_body
    assert "h_obl_glider" in trace.final_proof_body
    assert "h_obl_hanger" in trace.final_proof_body
    assert audit.classification == "fully_mechlib_verified"
    assert llm.prompts
    assert len(llm.prompts[0]) < 8000
    assert "MechLib.Dynamics.NewtonLaw.NewtonSecondLaw.to_value_equation" in llm.prompts[0]
