from __future__ import annotations

import re

from mech_pipeline.config import PipelineConfig
from mech_pipeline.modules.e_search_controller import run_llm_guided_search
from mech_pipeline.types import ProofActionCheckResult, ProofContext


class NoCallLLM:
    def generate_text(self, prompt: str):  # pragma: no cover - deterministic tests must not call LLM
        raise AssertionError(f"LLM should not be called for deterministic equation-chain tests: {prompt}")


class EquationChainFakeLeanRunner:
    def __init__(self, *, closed_tokens: list[str]) -> None:
        self.closed_tokens = list(closed_tokens)
        self.probes: list[str] = []
        self.verify_calls: list[str] = []

    def probe_proof_prefix(self, *, lean_header, theorem_decl, proof_prefix, timeout_s=None):
        _ = (lean_header, theorem_decl, timeout_s)
        self.probes.append(proof_prefix)
        if any(token in proof_prefix for token in self.closed_tokens):
            return ProofActionCheckResult(
                action_id="probe",
                strategy="probe_proof_prefix",
                tactic_block=proof_prefix,
                status="closed",
                unsolved_goal_count=0,
            )
        fact_names = re.findall(r"^\s*have\s+([A-Za-z_][A-Za-z0-9_']*)\s*:", proof_prefix, re.MULTILINE)
        if fact_names:
            latest = fact_names[-1]
            return ProofActionCheckResult(
                action_id="probe",
                strategy="probe_proof_prefix",
                tactic_block=proof_prefix,
                status="progress",
                goals_excerpt=f"{latest} : checked fact\n⊢ remaining target",
                unsolved_goal_count=1,
            )
        return ProofActionCheckResult(
            action_id="probe",
            strategy="probe_proof_prefix",
            tactic_block=proof_prefix,
            status="invalid",
            error_type="fake_unmatched_probe",
            error_message="fake runner did not match this proof prefix",
        )

    def verify_proof(self, *, sample_id, candidate_id, lean_header, theorem_decl, proof_body, run_dir):
        _ = (sample_id, candidate_id, lean_header, theorem_decl, run_dir)
        self.verify_calls.append(proof_body)
        return {"strict_pass": True}


def _cfg(max_nodes: int = 12) -> PipelineConfig:
    cfg = PipelineConfig()
    cfg.proof.llm_guided_search.max_nodes = max_nodes
    cfg.proof.llm_guided_search.max_depth = max_nodes
    cfg.proof.llm_guided_search.max_llm_calls = 0
    cfg.proof.llm_guided_search.deterministic_obligation_replay_first = False
    cfg.proof.llm_guided_search.deterministic_side_conditions_first = False
    cfg.proof.llm_guided_search.probe_timeout_s = 120
    return cfg


QUANTITY_HEADER = """import Mathlib

structure Q where
  val : Real
"""


def test_mechanics76_equation_chain_derives_force_balances_and_closes() -> None:
    theorem_decl = (
        "theorem Mechanics_76_equation_chain "
        "(F theta mu_k W F_x F_y f_k N Fnet_x Fnet_y m a_x a_y : Q) "
        "(given_constant_velocity : a_x.val = 0 ∧ a_y.val = 0) "
        "(h_newton_x : Fnet_x.val = m.val * a_x.val) "
        "(h_newton_y : Fnet_y.val = m.val * a_y.val) "
        "(h_net_force_horizontal_crate : Fnet_x.val = F_x.val - f_k.val) "
        "(h_net_force_vertical_crate : Fnet_y.val = N.val + F_y.val - W.val) "
        "(def_pull_horizontal_component : F_x.val = F.val * Real.cos theta.val) "
        "(def_pull_vertical_component : F_y.val = F.val * Real.sin theta.val) "
        "(h_if1 : f_k.val = mu_k.val * N.val) : "
        "F.val * Real.cos theta.val = mu_k.val * (W.val - F.val * Real.sin theta.val)"
    )
    context = ProofContext(
        sample_id="Mechanics_76",
        candidate_id="Mechanics_76",
        theorem_decl=theorem_decl,
        lean_header=QUANTITY_HEADER,
        target_formula="F.val * Real.cos theta.val = mu_k.val * (W.val - F.val * Real.sin theta.val)",
        local_binders=[
            "F : Q",
            "theta : Q",
            "mu_k : Q",
            "W : Q",
            "F_x : Q",
            "F_y : Q",
            "f_k : Q",
            "N : Q",
            "Fnet_x : Q",
            "Fnet_y : Q",
            "m : Q",
            "a_x : Q",
            "a_y : Q",
            "given_constant_velocity : a_x.val = 0 ∧ a_y.val = 0",
            "h_newton_x : Fnet_x.val = m.val * a_x.val",
            "h_newton_y : Fnet_y.val = m.val * a_y.val",
            "h_net_force_horizontal_crate : Fnet_x.val = F_x.val - f_k.val",
            "h_net_force_vertical_crate : Fnet_y.val = N.val + F_y.val - W.val",
            "def_pull_horizontal_component : F_x.val = F.val * Real.cos theta.val",
            "def_pull_vertical_component : F_y.val = F.val * Real.sin theta.val",
            "h_if1 : f_k.val = mu_k.val * N.val",
        ],
        allowed_local_facts=[
            "given_constant_velocity",
            "h_newton_x",
            "h_newton_y",
            "h_net_force_horizontal_crate",
            "h_net_force_vertical_crate",
            "def_pull_horizontal_component",
            "def_pull_vertical_component",
            "h_if1",
        ],
        local_hypotheses=[
            "given_constant_velocity",
            "h_newton_x",
            "h_newton_y",
            "h_net_force_horizontal_crate",
            "h_net_force_vertical_crate",
            "def_pull_horizontal_component",
            "def_pull_vertical_component",
            "h_if1",
        ],
    )

    trace = run_llm_guided_search(
        proof_context=context,
        lean_runner=EquationChainFakeLeanRunner(
            closed_tokens=["nlinarith [def_pull_horizontal_component"]
        ),
        llm_client=NoCallLLM(),
        cfg=_cfg(),
    )

    assert trace.search_status == "success"
    assert trace.llm_calls == 0
    assert trace.final_proof_body is not None
    assert "hFx_eq_fk" in trace.final_proof_body
    assert "hN_eq" in trace.final_proof_body
    assert any(row["strategy"] == "equation_chain_synthesis" for row in trace.accepted_actions)


def test_archive_part1_10_4_equation_chain_solves_delta_x_formula() -> None:
    theorem_decl = (
        "theorem archive_part1_10_4_equation_chain "
        "(m_A m_B x_Ai x_Bi x_Af x_Bf Delta_x_A_signed Delta_x_B_signed Delta_x_rel delta_x a b : Q) "
        "(h_sys_horizontal_com_relation : "
        "m_A.val * x_Ai.val + m_B.val * x_Bi.val = m_A.val * x_Af.val + m_B.val * x_Bf.val) "
        "(h_relative_shift_geometry : Delta_x_rel.val = a.val - b.val) "
        "(h_mii1 : Delta_x_A_signed.val = x_Af.val - x_Ai.val) "
        "(h_mii2 : Delta_x_B_signed.val = x_Bf.val - x_Bi.val) "
        "(h_mii3 : Delta_x_rel.val = Delta_x_B_signed.val - Delta_x_A_signed.val) "
        "(h_mii4 : delta_x.val = -Delta_x_A_signed.val) "
        "(hden : m_A.val + m_B.val ≠ 0) : "
        "delta_x.val = (m_B.val * (a.val - b.val)) / (m_A.val + m_B.val)"
    )
    facts = [
        "h_sys_horizontal_com_relation",
        "h_relative_shift_geometry",
        "h_mii1",
        "h_mii2",
        "h_mii3",
        "h_mii4",
        "hden",
    ]
    context = ProofContext(
        sample_id="archive_part1_10_4",
        candidate_id="archive_part1_10_4",
        theorem_decl=theorem_decl,
        lean_header=QUANTITY_HEADER,
        target_formula="delta_x.val = (m_B.val * (a.val - b.val)) / (m_A.val + m_B.val)",
        local_binders=[
            "m_A : Q",
            "m_B : Q",
            "x_Ai : Q",
            "x_Bi : Q",
            "x_Af : Q",
            "x_Bf : Q",
            "Delta_x_A_signed : Q",
            "Delta_x_B_signed : Q",
            "Delta_x_rel : Q",
            "delta_x : Q",
            "a : Q",
            "b : Q",
            "h_sys_horizontal_com_relation : m_A.val * x_Ai.val + m_B.val * x_Bi.val = m_A.val * x_Af.val + m_B.val * x_Bf.val",
            "h_relative_shift_geometry : Delta_x_rel.val = a.val - b.val",
            "h_mii1 : Delta_x_A_signed.val = x_Af.val - x_Ai.val",
            "h_mii2 : Delta_x_B_signed.val = x_Bf.val - x_Bi.val",
            "h_mii3 : Delta_x_rel.val = Delta_x_B_signed.val - Delta_x_A_signed.val",
            "h_mii4 : delta_x.val = -Delta_x_A_signed.val",
            "hden : m_A.val + m_B.val ≠ 0",
        ],
        allowed_local_facts=facts,
        local_hypotheses=facts,
    )

    trace = run_llm_guided_search(
        proof_context=context,
        lean_runner=EquationChainFakeLeanRunner(closed_tokens=["nlinarith [h_delta_balance]"]),
        llm_client=NoCallLLM(),
        cfg=_cfg(max_nodes=8),
    )

    assert trace.search_status == "success"
    assert trace.llm_calls == 0
    assert trace.final_proof_body is not None
    assert "h_com_shift" in trace.final_proof_body
    assert "h_delta_balance" in trace.final_proof_body


def test_archive_part1_13_3_equation_chain_solves_m3_max_formula() -> None:
    theorem_decl = (
        "theorem archive_part1_13_3_equation_chain "
        "(m1 m2 m3_max g T a h b : Q) "
        "(given_h : h.val = (1 : Real)) "
        "(hg_pos : 0 < g.val) "
        "(h_tip : a.val = g.val * b.val / h.val) "
        "(h_cart_block : T.val = (m1.val + m2.val) * a.val) "
        "(h_hanging_crit : m3_max.val * g.val - T.val = m3_max.val * a.val) "
        "(hden : h.val - b.val ≠ 0) : "
        "m3_max.val = (m1.val + m2.val) * b.val / (h.val - b.val)"
    )
    facts = ["given_h", "hg_pos", "h_tip", "h_cart_block", "h_hanging_crit", "hden"]
    context = ProofContext(
        sample_id="archive_part1_13_3",
        candidate_id="archive_part1_13_3",
        theorem_decl=theorem_decl,
        lean_header=QUANTITY_HEADER,
        target_formula="m3_max.val = (m1.val + m2.val) * b.val / (h.val - b.val)",
        local_binders=[
            "m1 : Q",
            "m2 : Q",
            "m3_max : Q",
            "g : Q",
            "T : Q",
            "a : Q",
            "h : Q",
            "b : Q",
            "given_h : h.val = (1 : Real)",
            "hg_pos : 0 < g.val",
            "h_tip : a.val = g.val * b.val / h.val",
            "h_cart_block : T.val = (m1.val + m2.val) * a.val",
            "h_hanging_crit : m3_max.val * g.val - T.val = m3_max.val * a.val",
            "hden : h.val - b.val ≠ 0",
        ],
        allowed_local_facts=facts,
        local_hypotheses=facts,
    )

    trace = run_llm_guided_search(
        proof_context=context,
        lean_runner=EquationChainFakeLeanRunner(closed_tokens=["nlinarith [h_balance]"]),
        llm_client=NoCallLLM(),
        cfg=_cfg(max_nodes=8),
    )

    assert trace.search_status == "success"
    assert trace.llm_calls == 0
    assert trace.final_proof_body is not None
    assert "h_balance" in trace.final_proof_body
    assert "mul_left_cancel₀" in trace.final_proof_body


def test_nested_conjunction_component_planner_flattens_and_closes() -> None:
    theorem_decl = (
        "theorem nested_conjunction_components "
        "(A B C : Prop) (hA : A) (hB : B) (hC : C) : A ∧ (B ∧ C)"
    )
    context = ProofContext(
        sample_id="nested_conjunction_components",
        candidate_id="nested_conjunction_components",
        theorem_decl=theorem_decl,
        lean_header="import Mathlib",
        target_formula="A ∧ (B ∧ C)",
        local_binders=["A : Prop", "B : Prop", "C : Prop", "hA : A", "hB : B", "hC : C"],
        allowed_local_facts=["hA", "hB", "hC"],
        local_hypotheses=["hA", "hB", "hC"],
    )

    trace = run_llm_guided_search(
        proof_context=context,
        lean_runner=EquationChainFakeLeanRunner(closed_tokens=["exact ⟨hA, hB, hC⟩"]),
        llm_client=NoCallLLM(),
        cfg=_cfg(max_nodes=2),
    )

    assert trace.search_status == "success"
    assert trace.llm_calls == 0
    assert trace.final_proof_body == "exact ⟨hA, hB, hC⟩"
    assert trace.accepted_actions[0]["strategy"] == "close_target_components"
