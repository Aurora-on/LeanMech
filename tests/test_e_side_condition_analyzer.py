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
