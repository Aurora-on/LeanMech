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
