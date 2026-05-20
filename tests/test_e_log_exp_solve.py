from __future__ import annotations

from pathlib import Path

from mech_pipeline.adapters.lean_runner import LeanRunner
from mech_pipeline.config import PipelineConfig
from mech_pipeline.modules.e_search_controller import run_llm_guided_search
from mech_pipeline.types import ProofContext


class NoCallLLM:
    def generate_text(self, prompt: str):  # pragma: no cover - should not be called
        raise AssertionError(f"LLM should not be called for deterministic log_exp_solve: {prompt}")


def _runner() -> LeanRunner:
    root = Path(__file__).resolve().parents[1]
    return LeanRunner(
        physlean_dir=root,
        mechlib_dir=root,
        timeout_s=120,
        strict_blocklist=["sorry", "admit", "axiom"],
        lean_header="import Mathlib",
        route_policy="auto_by_import",
        default_backend="plain",
        route_fallback=False,
    )


def _cfg() -> PipelineConfig:
    cfg = PipelineConfig()
    cfg.proof.llm_guided_search.max_nodes = 4
    cfg.proof.llm_guided_search.max_depth = 4
    cfg.proof.llm_guided_search.max_llm_calls = 0
    cfg.proof.llm_guided_search.deterministic_obligation_replay_first = False
    cfg.proof.llm_guided_search.deterministic_side_conditions_first = False
    cfg.proof.llm_guided_search.probe_timeout_s = 120
    return cfg


def _capstan_context(*, reverse_exp_fact: bool = False) -> ProofContext:
    hcapstan_type = (
        "Real.exp (mu * theta) = M / m"
        if reverse_exp_fact
        else "M / m = Real.exp (mu * theta)"
    )
    return ProofContext(
        sample_id="capstan_solve_real",
        candidate_id="capstan_solve_real",
        theorem_decl=(
            "theorem capstan_solve_real (M m mu theta n : Real) "
            "(hmu : mu ≠ 0) "
            f"(hcapstan : {hcapstan_type}) "
            "(htheta : theta = 2 * Real.pi * n) : "
            "n = Real.log (M / m) / (2 * Real.pi * mu)"
        ),
        lean_header="import Mathlib",
        target_formula="n = Real.log (M / m) / (2 * Real.pi * mu)",
        local_binders=[
            "M : Real",
            "m : Real",
            "mu : Real",
            "theta : Real",
            "n : Real",
            "hmu : mu ≠ 0",
            f"hcapstan : {hcapstan_type}",
            "htheta : theta = 2 * Real.pi * n",
        ],
        allowed_local_facts=["hmu", "hcapstan", "htheta"],
        local_hypotheses=["hmu", "hcapstan", "htheta"],
    )


def test_capstan_solve_real_log_exp_strategy() -> None:
    trace = run_llm_guided_search(
        proof_context=_capstan_context(),
        lean_runner=_runner(),
        llm_client=NoCallLLM(),
        cfg=_cfg(),
    )

    assert trace.search_status == "success"
    assert trace.llm_calls == 0
    assert trace.final_proof_body is not None
    assert "Real.log_exp" in trace.final_proof_body
    assert any(
        row["strategy"] == "log_exp_solve"
        and "hlog" in " ".join(row.get("new_local_facts") or [])
        for row in trace.accepted_actions
    )


def test_capstan_solve_real_log_exp_strategy_supports_reverse_exp_equality() -> None:
    trace = run_llm_guided_search(
        proof_context=_capstan_context(reverse_exp_fact=True),
        lean_runner=_runner(),
        llm_client=NoCallLLM(),
        cfg=_cfg(),
    )

    assert trace.search_status == "success"
    assert trace.final_proof_body is not None
    assert "rw [← hcapstan]" in trace.final_proof_body
