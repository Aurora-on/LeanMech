from __future__ import annotations

from mech_pipeline.modules.e_action_guard import validate_action_proposal
from mech_pipeline.types import ProofActionProposal, ProofContext


ALLOWED = "MechLib.Dynamics.NewtonLaw.NewtonSecondLaw.to_value_equation"
UNAUTHORIZED = "MechLib.Dynamics.WorkEnergy.work_energy_theorem_core"


def _context() -> ProofContext:
    return ProofContext(
        sample_id="s1",
        candidate_id="c1",
        theorem_decl="theorem c1 : True",
        lean_header="import MechLib",
        local_hypotheses=["glider_law", "hFnet", "h_mi1"],
        allowed_local_facts=["glider_law", "hFnet", "h_mi1"],
        allowed_verified_decls=[ALLOWED],
    )


def _proposal(tactic_block: str, *, uses_decls=None, uses_facts=None) -> ProofActionProposal:
    return ProofActionProposal(
        action_id="a1",
        strategy="test",
        tactic_block=tactic_block,
        uses_decls=list(uses_decls or []),
        uses_facts=list(uses_facts or []),
        source="llm",
    )


def test_action_guard_rejects_sorry_admit_axiom() -> None:
    for token, reason in [
        ("sorry", "forbidden_sorry"),
        ("admit", "forbidden_admit"),
        ("axiom bad : True", "forbidden_axiom"),
    ]:
        ok, reasons = validate_action_proposal(_proposal(token), _context())
        assert ok is False
        assert reason in reasons


def test_action_guard_rejects_unauthorized_mechlib_decl() -> None:
    proposal = _proposal(
        f"have h := {UNAUTHORIZED}",
        uses_decls=[UNAUTHORIZED],
    )
    ok, reasons = validate_action_proposal(proposal, _context())

    assert ok is False
    assert "unauthorized_mechlib_decl" in reasons


def test_action_guard_accepts_allowed_extractor_decl() -> None:
    proposal = _proposal(
        f"have h_mi1 : Fnet.val = m.val * a.val := by\n  exact {ALLOWED} glider_law",
        uses_decls=[ALLOWED],
        uses_facts=["glider_law"],
    )
    ok, reasons = validate_action_proposal(proposal, _context())

    assert ok is True
    assert reasons == []


def test_action_guard_allows_intro_inside_forall_have() -> None:
    proposal = _proposal(
        "have h_all : forall t0 : Real, t0 = t0 := by\n  intro t0\n  rfl",
    )
    ok, reasons = validate_action_proposal(proposal, _context())

    assert ok is True
    assert reasons == []


def test_action_guard_allows_rcases_on_known_local_fact() -> None:
    context = _context()
    context.allowed_local_facts.append("hdom")
    context.local_hypotheses.append("hdom")
    proposal = _proposal(
        "rcases hdom with ⟨h0, h1⟩",
        uses_facts=["hdom"],
    )
    ok, reasons = validate_action_proposal(proposal, context)

    assert ok is True
    assert reasons == []


def test_action_guard_allows_cases_on_known_local_fact() -> None:
    context = _context()
    context.allowed_local_facts.append("hcase")
    context.local_hypotheses.append("hcase")
    proposal = _proposal(
        "cases hcase",
        uses_facts=["hcase"],
    )
    ok, reasons = validate_action_proposal(proposal, context)

    assert ok is True
    assert reasons == []


def test_action_guard_allows_constructor_inside_local_have() -> None:
    proposal = _proposal(
        "have h_pair : True ∧ True := by\n  constructor\n  · exact h_mi1\n  · exact h_mi1",
        uses_facts=["h_mi1"],
    )
    ok, reasons = validate_action_proposal(proposal, _context())

    assert ok is True
    assert reasons == []


def test_action_guard_allows_calc_blocks_inside_have() -> None:
    context = _context()
    for fact in ["h1", "h2", "hden_R_val"]:
        context.allowed_local_facts.append(fact)
        context.local_hypotheses.append(fact)
    proposal = _proposal(
        "have hat : (a_t t0).val = 2 * a.val := by\n"
        "  calc\n"
        "    (a_t t0).val = (alpha t0).val * R.val := h1\n"
        "    _ = ((2 * a.val) / R.val) * R.val := by rw [h2]\n"
        "    _ = 2 * a.val := by field_simp [hden_R_val]",
        uses_facts=["h1", "h2", "hden_R_val"],
    )

    ok, reasons = validate_action_proposal(proposal, context)

    assert ok is True
    assert reasons == []


def test_action_guard_allows_log_exp_and_mul_ne_zero_terms() -> None:
    context = _context()
    for fact in ["hcapstan", "hmu"]:
        context.allowed_local_facts.append(fact)
        context.local_hypotheses.append(fact)
    proposal = _proposal(
        "have hlog : Real.log (M / m) = mu * theta := by\n"
        "  calc\n"
        "    Real.log (M / m) = Real.log (Real.exp (mu * theta)) := by rw [hcapstan]\n"
        "    _ = mu * theta := Real.log_exp _\n"
        "have hden : 2 * Real.pi * mu ≠ 0 := by\n"
        "  exact mul_ne_zero (mul_ne_zero (by norm_num) Real.pi_ne_zero) hmu",
        uses_facts=["hcapstan", "hmu"],
    )

    ok, reasons = validate_action_proposal(proposal, context)

    assert ok is True
    assert reasons == []


def test_action_guard_rejects_function_valued_quantity_val_before_application() -> None:
    context = ProofContext(
        sample_id="s1",
        candidate_id="c1",
        theorem_decl="theorem c1 (m : Real -> Mass) : True",
        lean_header="import MechLib",
        local_binders=["m : Real -> Mass"],
    )
    proposal = _proposal("have h : m.val 90 = 100 := by\n  norm_num")

    ok, reasons = validate_action_proposal(proposal, context)

    assert ok is False
    assert "invalid_function_quantity_value_application" in reasons


def test_action_guard_rejects_natural_language() -> None:
    proposal = _proposal("derive the equation from Newton's law and simplify")
    ok, reasons = validate_action_proposal(proposal, _context())

    assert ok is False
    assert "disallowed_tactic_or_natural_language" in reasons


def test_action_guard_rejects_schema_metadata() -> None:
    proposal = _proposal(
        "have h := law.dynamics.newton_second_law",
        uses_decls=["law.dynamics.newton_second_law"],
    )
    ok, reasons = validate_action_proposal(proposal, _context())

    assert ok is False
    assert "schema_or_metadata_used_as_proof_fact" in reasons
