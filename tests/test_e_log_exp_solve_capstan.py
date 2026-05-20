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


def test_capstan_solve_real_generates_hlog_and_closes() -> None:
    context = ProofContext(
        sample_id="capstan_solve_real",
        candidate_id="capstan_solve_real",
        theorem_decl=(
            "theorem capstan_solve_real (M m mu theta n : Real) "
            "(hcapstan : M / m = Real.exp (mu * theta)) "
            "(htheta : theta = 2 * Real.pi * n) "
            "(hmu : mu ≠ 0) : "
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
            "hcapstan : M / m = Real.exp (mu * theta)",
            "htheta : theta = 2 * Real.pi * n",
            "hmu : mu ≠ 0",
        ],
        allowed_local_facts=["hcapstan", "htheta", "hmu"],
        local_hypotheses=["hcapstan", "htheta", "hmu"],
    )

    trace = run_llm_guided_search(
        proof_context=context,
        lean_runner=_runner(),
        llm_client=NoCallLLM(),
        cfg=_cfg(),
    )

    assert trace.search_status == "success"
    assert trace.llm_calls == 0
    assert trace.final_proof_body is not None
    assert "hlog" in trace.final_proof_body
    assert "Real.log_exp" in trace.final_proof_body
    assert any(row["strategy"] == "log_exp_solve" for row in trace.accepted_actions)


def test_capstan_solve_from_tension_ratio_derives_mass_ratio_first() -> None:
    context = ProofContext(
        sample_id="capstan_solve_from_tension_ratio",
        candidate_id="capstan_solve_from_tension_ratio",
        theorem_decl=(
            "theorem capstan_solve_from_tension_ratio "
            "(M m g T_heavy T_light mu theta n : Real) "
            "(given_m_value : m = 10) "
            "(hg_pos : 0 < g) "
            "(hcapstan : T_heavy / T_light = Real.exp (mu * theta)) "
            "(hheavy : T_heavy = M * g) "
            "(hlight : T_light = m * g) "
            "(htheta : theta = 2 * Real.pi * n) "
            "(hmu : mu ≠ 0) : "
            "n = (1 / (2 * Real.pi * mu)) * Real.log (M / m)"
        ),
        lean_header="import Mathlib",
        target_formula="n = (1 / (2 * Real.pi * mu)) * Real.log (M / m)",
        local_binders=[
            "M : Real",
            "m : Real",
            "g : Real",
            "T_heavy : Real",
            "T_light : Real",
            "mu : Real",
            "theta : Real",
            "n : Real",
            "given_m_value : m = 10",
            "hg_pos : 0 < g",
            "hcapstan : T_heavy / T_light = Real.exp (mu * theta)",
            "hheavy : T_heavy = M * g",
            "hlight : T_light = m * g",
            "htheta : theta = 2 * Real.pi * n",
            "hmu : mu ≠ 0",
        ],
        allowed_local_facts=[
            "given_m_value",
            "hg_pos",
            "hcapstan",
            "hheavy",
            "hlight",
            "htheta",
            "hmu",
        ],
        local_hypotheses=[
            "given_m_value",
            "hg_pos",
            "hcapstan",
            "hheavy",
            "hlight",
            "htheta",
            "hmu",
        ],
    )

    trace = run_llm_guided_search(
        proof_context=context,
        lean_runner=_runner(),
        llm_client=NoCallLLM(),
        cfg=_cfg(),
    )

    assert trace.search_status == "success"
    assert trace.llm_calls == 0
    assert trace.final_proof_body is not None
    assert "T_heavy / T_light" in trace.final_proof_body
    assert "M / m = Real.exp" in trace.final_proof_body
    assert "Real.log_exp" in trace.final_proof_body
