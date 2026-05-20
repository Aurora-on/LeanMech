from __future__ import annotations

from pathlib import Path

from mech_pipeline.adapters.lean_runner import LeanRunner
from mech_pipeline.config import PipelineConfig
from mech_pipeline.modules.e_search_controller import run_llm_guided_search
from mech_pipeline.types import ProofContext


class NoCallLLM:
    def generate_text(self, prompt: str):  # pragma: no cover - should not be called
        raise AssertionError(f"LLM should not be called for deterministic sqrt_square_solve: {prompt}")


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
    cfg.proof.llm_guided_search.max_nodes = 3
    cfg.proof.llm_guided_search.max_depth = 3
    cfg.proof.llm_guided_search.max_llm_calls = 0
    cfg.proof.llm_guided_search.deterministic_obligation_replay_first = False
    cfg.proof.llm_guided_search.deterministic_side_conditions_first = False
    cfg.proof.llm_guided_search.probe_timeout_s = 120
    return cfg


def test_sqrt_direct_formula_closes_without_arithmetic_search() -> None:
    context = ProofContext(
        sample_id="sqrt_direct_formula",
        candidate_id="sqrt_direct_formula",
        theorem_decl=(
            "theorem sqrt_direct_formula (x y : Real) "
            "(h_formula : x = Real.sqrt y) : x = Real.sqrt y"
        ),
        lean_header="import Mathlib",
        target_formula="x = Real.sqrt y",
        local_binders=[
            "x : Real",
            "y : Real",
            "h_formula : x = Real.sqrt y",
        ],
        allowed_local_facts=["h_formula"],
        local_hypotheses=["h_formula"],
    )

    trace = run_llm_guided_search(
        proof_context=context,
        lean_runner=_runner(),
        llm_client=NoCallLLM(),
        cfg=_cfg(),
    )

    assert trace.search_status == "success"
    assert trace.llm_calls == 0
    assert trace.final_proof_body == "exact h_formula"
    assert trace.accepted_actions[0]["strategy"] == "sqrt_square_solve"
    assert not any(row["strategy"] == "nonlinear_arithmetic" for row in trace.accepted_actions)


def test_sqrt_direct_formula_supports_reversed_local_formula() -> None:
    context = ProofContext(
        sample_id="sqrt_direct_formula_reverse",
        candidate_id="sqrt_direct_formula_reverse",
        theorem_decl=(
            "theorem sqrt_direct_formula_reverse (x y : Real) "
            "(h_formula : Real.sqrt y = x) : x = Real.sqrt y"
        ),
        lean_header="import Mathlib",
        target_formula="x = Real.sqrt y",
        local_binders=[
            "x : Real",
            "y : Real",
            "h_formula : Real.sqrt y = x",
        ],
        allowed_local_facts=["h_formula"],
        local_hypotheses=["h_formula"],
    )

    trace = run_llm_guided_search(
        proof_context=context,
        lean_runner=_runner(),
        llm_client=NoCallLLM(),
        cfg=_cfg(),
    )

    assert trace.search_status == "success"
    assert trace.final_proof_body == "exact Eq.symm h_formula"
    assert trace.accepted_actions[0]["strategy"] == "sqrt_square_solve"
