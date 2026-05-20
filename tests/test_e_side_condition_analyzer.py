from __future__ import annotations

from mech_pipeline.modules.e_side_conditions import extract_denominators, propose_side_condition_actions
from mech_pipeline.types import ProofContext


def _context(target: str) -> ProofContext:
    return ProofContext(
        sample_id="s1",
        candidate_id="c1",
        theorem_decl="theorem c1 : True",
        lean_header="import MechLib",
        target_formula=target,
        allowed_local_facts=["hm1", "hm2"],
        local_hypotheses=["hm1", "hm2"],
    )


def test_side_condition_analyzer_extracts_sum_denominator() -> None:
    assert extract_denominators("a.val = F.val / (m1.val + m2.val)") == ["m1.val + m2.val"]


def test_side_condition_analyzer_generates_nonzero_denominator_action() -> None:
    context = _context("a.val = F.val / (m1.val + m2.val)")
    proposals = propose_side_condition_actions(
        context,
        ["hm1 : 0 < m1.val", "hm2 : 0 < m2.val"],
    )

    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal.strategy == "prove_side_condition"
    assert "m1.val + m2.val ≠ 0" in proposal.tactic_block
    assert "nlinarith [hm1, hm2]" in proposal.tactic_block
    assert proposal.uses_facts == ["hm1", "hm2"]


def test_side_condition_analyzer_reports_missing_positive_fact() -> None:
    context = _context("a.val = F.val / (m1.val + m2.val)")
    proposals = propose_side_condition_actions(context, ["hm1 : 0 < m1.val"])

    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal.strategy == "missing_side_condition"
    assert proposal.tactic_block == ""
    assert "m2.val" in str(proposal.expected_effect)


def test_side_condition_analyzer_extracts_simple_denominator() -> None:
    assert extract_denominators("a.val = F.val / m.val") == ["m.val"]


def test_side_condition_analyzer_discovers_denominator_from_accepted_fact() -> None:
    context = ProofContext(
        sample_id="s1",
        candidate_id="c1",
        theorem_decl="theorem c1 (g : Acceleration) (h_g_pos : 0 < g.val) : True",
        lean_header="import MechLib",
        target_formula="x.val = y.val",
        local_binders=["g : Acceleration", "h_g_pos : 0 < g.val"],
        allowed_local_facts=["h_g_pos"],
        local_hypotheses=["h_g_pos"],
    )

    proposals = propose_side_condition_actions(
        context,
        ["h_sub : (P.val / g.val) * x.val + (Q.val / g.val) * y.val = 0", "h_g_pos : 0 < g.val"],
    )

    assert len(proposals) == 1
    assert proposals[0].strategy == "prove_side_condition"
    assert proposals[0].expected_effect == "prove denominator nonzero: g.val"
    assert proposals[0].uses_facts == ["h_g_pos"]


def test_side_condition_analyzer_handles_constant_times_positive_quantity() -> None:
    context = ProofContext(
        sample_id="s1",
        candidate_id="c1",
        theorem_decl="theorem c1 (g : Acceleration) (h_g_pos : 0 < g.val) : True",
        lean_header="import MechLib",
        target_formula="h.val = v.val ^ 2 / (2 * g.val)",
        local_binders=["g : Acceleration", "h_g_pos : 0 < g.val"],
        allowed_local_facts=["h_g_pos"],
        local_hypotheses=["h_g_pos"],
    )

    proposals = propose_side_condition_actions(context, ["h_g_pos"])

    assert len(proposals) == 1
    assert proposals[0].strategy == "prove_side_condition"
    assert "2 * g.val ≠ 0" in proposals[0].tactic_block
    assert "nlinarith [h_g_pos]" in proposals[0].tactic_block


def test_side_condition_analyzer_includes_pi_pos_for_pi_denominator() -> None:
    context = ProofContext(
        sample_id="s1",
        candidate_id="c1",
        theorem_decl="theorem c1 (k : SpringConstant) (h_k_pos : 0 < k.val) : True",
        lean_header="import MechLib",
        target_formula="T.val = x.val / (4 * Real.pi * k.val)",
        local_binders=["k : SpringConstant", "h_k_pos : 0 < k.val"],
        allowed_local_facts=["h_k_pos"],
        local_hypotheses=["h_k_pos"],
    )

    proposals = propose_side_condition_actions(context, ["h_k_pos"])

    assert len(proposals) == 1
    assert proposals[0].strategy == "prove_side_condition"
    assert "4 * Real.pi * k.val ≠ 0" in proposals[0].tactic_block
    assert "nlinarith [Real.pi_pos, h_k_pos]" in proposals[0].tactic_block
    assert proposals[0].uses_facts == ["h_k_pos"]


def test_side_condition_analyzer_uses_positive_value_equality_for_pi_product() -> None:
    context = ProofContext(
        sample_id="s1",
        candidate_id="c1",
        theorem_decl="theorem c1 (mu : Dimensionless) (given_mu_value : mu.val = 1 / 20) : True",
        lean_header="import MechLib",
        target_formula="x.val = y.val / (2 * Real.pi * mu.val)",
        local_binders=["mu : Dimensionless", "given_mu_value : mu.val = 1 / 20"],
        allowed_local_facts=["given_mu_value"],
        local_hypotheses=["given_mu_value"],
    )

    proposals = propose_side_condition_actions(context, ["given_mu_value : mu.val = 1 / 20"])

    assert len(proposals) == 1
    assert proposals[0].strategy == "prove_side_condition"
    assert "2 * Real.pi * mu.val ≠ 0" in proposals[0].tactic_block
    assert "nlinarith [Real.pi_pos, given_mu_value]" in proposals[0].tactic_block
    assert proposals[0].uses_facts == ["given_mu_value"]


def test_side_condition_analyzer_supports_bare_real_pi_product_with_positive_fact() -> None:
    context = ProofContext(
        sample_id="s1",
        candidate_id="c1",
        theorem_decl="theorem c1 (mu : Real) (hmu_pos : 0 < mu) : True",
        lean_header="import Mathlib",
        target_formula="x = y / (2 * Real.pi * mu)",
        local_binders=["mu : Real", "hmu_pos : 0 < mu"],
        allowed_local_facts=["hmu_pos"],
        local_hypotheses=["hmu_pos"],
    )

    proposals = propose_side_condition_actions(context, ["hmu_pos"])

    assert len(proposals) == 1
    assert proposals[0].strategy == "prove_side_condition"
    assert "2 * Real.pi * mu ≠ 0" in proposals[0].tactic_block
    assert "nlinarith [Real.pi_pos, hmu_pos]" in proposals[0].tactic_block


def test_side_condition_analyzer_supports_bare_real_pi_product_with_nonzero_fact() -> None:
    context = ProofContext(
        sample_id="s1",
        candidate_id="c1",
        theorem_decl="theorem c1 (mu : Real) (hmu : mu ≠ 0) : True",
        lean_header="import Mathlib",
        target_formula="x = y / (2 * Real.pi * mu)",
        local_binders=["mu : Real", "hmu : mu ≠ 0"],
        allowed_local_facts=["hmu"],
        local_hypotheses=["hmu"],
    )

    proposals = propose_side_condition_actions(context, ["hmu"])

    assert len(proposals) == 1
    assert proposals[0].strategy == "prove_side_condition"
    assert "2 * Real.pi * mu ≠ 0" in proposals[0].tactic_block
    assert "mul_ne_zero (mul_ne_zero (by norm_num) Real.pi_ne_zero) hmu" in proposals[0].tactic_block


def test_side_condition_analyzer_marks_difference_denominator_unavailable() -> None:
    context = ProofContext(
        sample_id="s1",
        candidate_id="c1",
        theorem_decl="theorem c1 (h b : Length) : True",
        lean_header="import MechLib",
        target_formula="x.val = y.val / (h.val - b.val)",
        local_binders=["h b : Length"],
    )

    proposals = propose_side_condition_actions(context, [])

    assert len(proposals) == 1
    assert proposals[0].strategy == "missing_side_condition_unavailable"
    assert "h.val - b.val" in str(proposals[0].expected_effect)


def test_side_condition_analyzer_uses_context_binder_positive_facts_after_augmentation() -> None:
    context = ProofContext(
        sample_id="s1",
        candidate_id="c1",
        theorem_decl="theorem c1 (m1 m2 : Mass) (h_m1_pos : 0 < m1.val) (h_m2_pos : 0 < m2.val) : True",
        lean_header="import MechLib",
        target_formula="a.val = F.val / (m1.val + m2.val)",
        local_binders=["m1 m2 : Mass", "h_m1_pos : 0 < m1.val", "h_m2_pos : 0 < m2.val"],
        allowed_local_facts=["h_m1_pos", "h_m2_pos"],
        local_hypotheses=["h_m1_pos", "h_m2_pos"],
    )

    proposals = propose_side_condition_actions(context, ["h_m1_pos", "h_m2_pos"])

    assert len(proposals) == 1
    assert proposals[0].strategy == "prove_side_condition"
    assert proposals[0].uses_facts == ["h_m1_pos", "h_m2_pos"]
