from __future__ import annotations

import json

from mech_pipeline.config import PipelineConfig
from mech_pipeline.modules.e_search_controller import run_llm_guided_search
from mech_pipeline.modules.e_strategy_controller import LLMStrategyController
from mech_pipeline.types import ProofActionCheckResult, ProofContext, ProofObligationReplayItem


class CapturingLLM:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generate_text(self, prompt: str):
        self.prompts.append(prompt)

        class Response:
            text = json.dumps({"proposals": []})

        return Response()


class InvalidLeanRunner:
    def probe_proof_prefix(self, *, lean_header, theorem_decl, proof_prefix, timeout_s=None):
        _ = (lean_header, theorem_decl, proof_prefix, timeout_s)
        return ProofActionCheckResult(
            action_id="probe",
            strategy="probe_proof_prefix",
            tactic_block=proof_prefix,
            status="invalid",
            error_type="tactic_failed",
        )

    def verify_proof(self, *, sample_id, candidate_id, lean_header, theorem_decl, proof_body, run_dir):
        _ = (sample_id, candidate_id, lean_header, theorem_decl, proof_body, run_dir)
        return {"strict_pass": False}


def _context() -> ProofContext:
    huge_retrieval = "THEOREM_CORPUS_FULL " + ("retrieval_context_blob " * 1000)
    return ProofContext(
        sample_id="s1",
        candidate_id="c1",
        theorem_decl="theorem c1 (hF : F = m * a) : F = m * a",
        lean_header="import MechLib",
        target_formula="F = m * a",
        allowed_local_facts=["hF : F = m * a", "hm : 0 < m.val"],
        local_hypotheses=["hF", "hm"],
        allowed_verified_decls=["MechLib.Dynamics.NewtonLaw.NewtonSecondLaw.to_value_equation"],
        mechlib_context_excerpt=huge_retrieval,
    )


def test_strategy_prompt_is_compact_and_whitelisted() -> None:
    controller = LLMStrategyController()
    prompt = controller.build_prompt(
        proof_context=_context(),
        local_facts=["hF : F = m * a", "hm : 0 < m.val"],
        proof_prefix_summary="have h1 : F = m * a := by\n  exact hF",
        last_error="unknown identifier " + ("x" * 2000),
        failed_actions=[{"action_id": f"a{i}", "error_message": "bad " * 200} for i in range(30)],
    )

    assert "MechLib.Dynamics.NewtonLaw.NewtonSecondLaw.to_value_equation" in prompt
    assert "hF : F = m * a" in prompt
    assert "THEOREM_CORPUS_FULL" not in prompt
    assert "retrieval_context_blob" not in prompt
    assert len(prompt) < 8000


def test_search_trace_records_compact_prompt_summary_only() -> None:
    cfg = PipelineConfig()
    cfg.proof.llm_guided_search.max_nodes = 1
    cfg.proof.llm_guided_search.max_llm_calls = 1
    cfg.proof.llm_guided_search.deterministic_obligation_replay_first = False
    cfg.proof.llm_guided_search.deterministic_side_conditions_first = False
    llm = CapturingLLM()

    trace = run_llm_guided_search(
        proof_context=_context(),
        lean_runner=InvalidLeanRunner(),
        llm_client=llm,
        cfg=cfg,
    )

    assert llm.prompts
    assert len(llm.prompts[0]) < 8000
    assert trace.strategy_prompt_summaries
    summary = trace.strategy_prompt_summaries[0]
    assert summary["prompt_chars"] < 8000
    assert "MechLib.Dynamics.NewtonLaw.NewtonSecondLaw.to_value_equation" in summary["allowed_decls"]
    assert "THEOREM_CORPUS_FULL" not in str(summary)
    assert "retrieval_context_blob" not in str(summary)


def test_search_prompt_keeps_remaining_obligation_details_after_replay() -> None:
    cfg = PipelineConfig()
    cfg.proof.llm_guided_search.max_nodes = 1
    cfg.proof.llm_guided_search.max_llm_calls = 1
    cfg.proof.llm_guided_search.deterministic_obligation_replay_first = False
    cfg.proof.llm_guided_search.deterministic_side_conditions_first = False
    context = _context()
    context.obligation_replay_items = [
        ProofObligationReplayItem(
            obligation_id="sk1",
            kind="law_to_equation",
            from_hypothesis="h_law",
            must_use="MechLib.Dynamics.NewtonLaw.NewtonSecondLaw.to_value_equation",
            formal_claim="F.val = m.val * a.val",
            produced_fact_name="h_newton_eq",
        )
    ]
    llm = CapturingLLM()

    trace = run_llm_guided_search(
        proof_context=context,
        lean_runner=InvalidLeanRunner(),
        llm_client=llm,
        cfg=cfg,
    )

    assert llm.prompts
    assert '"formal_claim": "F.val = m.val * a.val"' in llm.prompts[0]
    assert '"must_use": "MechLib.Dynamics.NewtonLaw.NewtonSecondLaw.to_value_equation"' in llm.prompts[0]
    assert '"from_hypothesis": "h_law"' in llm.prompts[0]
    remaining = trace.strategy_prompt_summaries[0]["remaining_obligations"]
    assert remaining[0]["formal_claim"] == "F.val = m.val * a.val"
    assert remaining[0]["must_use"] == "MechLib.Dynamics.NewtonLaw.NewtonSecondLaw.to_value_equation"
