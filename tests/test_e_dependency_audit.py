from __future__ import annotations

from mech_pipeline.modules.e_dependency_audit import audit_proof_dependencies
from mech_pipeline.types import ProofContext, ProofObligationReplayItem


EXTRACTOR_1 = "MechLib.Dynamics.NewtonLaw.NewtonSecondLaw.to_value_equation"
EXTRACTOR_2 = "MechLib.Dynamics.NewtonLaw.NewtonSecondLaw.to_value_equation_hanger"


def _context(*, gap: bool = False) -> ProofContext:
    return ProofContext(
        sample_id="s1",
        candidate_id="c1",
        theorem_decl="theorem c1 : True",
        lean_header="import MechLib",
        gap_laws=[{"id": "gap.law"}] if gap else [],
        obligation_replay_items=[
            ProofObligationReplayItem(
                obligation_id="obl1",
                kind="law_to_equation",
                from_hypothesis="glider_law",
                must_use=EXTRACTOR_1,
                formal_claim="Fnet1.val = m1.val * a.val",
                produced_fact_name="h_obl_1",
            ),
            ProofObligationReplayItem(
                obligation_id="obl2",
                kind="law_to_equation",
                from_hypothesis="hanger_law",
                must_use=EXTRACTOR_2,
                formal_claim="Fnet2.val = m2.val * a.val",
                produced_fact_name="h_obl_2",
            ),
        ],
    )


def test_dependency_audit_classifies_full_mechlib_verified() -> None:
    proof = f"""
have h_obl_1 : Fnet1.val = m1.val * a.val := by
  exact {EXTRACTOR_1} glider_law
have h_obl_2 : Fnet2.val = m2.val * a.val := by
  exact {EXTRACTOR_2} hanger_law
linarith [h_obl_1, h_obl_2]
"""

    audit = audit_proof_dependencies(
        proof_context=_context(),
        proof_body=proof,
        final_replay_pass=True,
    )

    assert audit.classification == "fully_mechlib_verified"
    assert audit.fully_mechlib_verified is True
    assert audit.missing_required_decls == []
    assert audit.missing_obligations == []


def test_dependency_audit_classifies_algebra_only_success() -> None:
    audit = audit_proof_dependencies(
        proof_context=_context(),
        proof_body="linarith [h1, h2]",
        final_replay_pass=True,
    )

    assert audit.classification == "algebra_only_success"
    assert audit.algebra_only is True
    assert audit.fully_mechlib_verified is False


def test_dependency_audit_does_not_cover_obligation_from_algebra_fact_name_only() -> None:
    proof = """
have h_obl_1 : Fnet1.val = m1.val * a.val := by
  linarith [h1, h2]
linarith [h_obl_1]
"""

    audit = audit_proof_dependencies(
        proof_context=_context(),
        proof_body=proof,
        final_replay_pass=True,
    )

    assert audit.classification == "algebra_only_success"
    assert audit.covered_obligations == []
    assert audit.missing_obligations == ["obl1", "obl2"]


def test_dependency_audit_uses_exact_lean_identifier_boundaries() -> None:
    proof = f"""
have h_obl_1_pos : True := by
  exact True.intro
have h_decl := {EXTRACTOR_1} glider_law
exact h_obl_1_pos
"""

    audit = audit_proof_dependencies(
        proof_context=_context(),
        proof_body=proof,
        final_replay_pass=True,
    )

    assert audit.covered_obligations == []
    assert audit.missing_obligations == ["obl1", "obl2"]


def test_dependency_audit_classifies_gap_assisted_success() -> None:
    proof = f"""
have h_obl_1 := {EXTRACTOR_1} glider_law
have h_obl_2 := {EXTRACTOR_2} hanger_law
exact gap_law_solution
"""

    audit = audit_proof_dependencies(
        proof_context=_context(gap=True),
        proof_body=proof,
        final_replay_pass=True,
    )

    assert audit.classification == "gap_assisted_success"
    assert audit.gap_laws_used is True
    assert audit.fully_mechlib_verified is False


def test_dependency_audit_classifies_partial_mechlib_verified() -> None:
    proof = f"""
have h_obl_1 : Fnet1.val = m1.val * a.val := by
  exact {EXTRACTOR_1} glider_law
linarith [h_obl_1]
"""

    audit = audit_proof_dependencies(
        proof_context=_context(),
        proof_body=proof,
        final_replay_pass=True,
    )

    assert audit.classification == "partial_mechlib_verified"
    assert audit.covered_obligations == ["obl1"]
    assert audit.missing_obligations == ["obl2"]
