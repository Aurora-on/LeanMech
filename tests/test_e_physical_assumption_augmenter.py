from __future__ import annotations

from mech_pipeline.modules.e_physical_assumption_augmenter import (
    augment_context_for_missing_side_condition,
    physical_quantity_vars,
)
from mech_pipeline.types import ProofActionProposal, ProofContext


POSITIVE_TYPES = ["Mass", "Length", "Time", "Acceleration"]


class RecordingLeanRunner:
    def __init__(self, *, compile_pass: bool = True) -> None:
        self.compile_pass = compile_pass
        self.compile_calls: list[str] = []

    def compile_statement(self, *, sample_id, candidate_id, lean_header, theorem_decl, run_dir):
        _ = (sample_id, candidate_id, lean_header, run_dir)
        self.compile_calls.append(theorem_decl)
        return {
            "compile_pass": self.compile_pass,
            "syntax_ok": self.compile_pass,
            "elaboration_ok": self.compile_pass,
            "candidate_id": candidate_id,
            "error_message": None if self.compile_pass else "bad augmented theorem",
            "stderr_digest": "",
        }


def _proposal(missing: str) -> ProofActionProposal:
    return ProofActionProposal(
        action_id="missing_side_condition_1",
        strategy="missing_side_condition",
        tactic_block="",
        expected_effect=f"missing_side_condition: denominator {missing} requires positivity facts for {missing}",
        source="deterministic",
    )


def test_physical_vars_include_typed_quantity_but_not_real_or_function() -> None:
    context = ProofContext(
        sample_id="s1",
        candidate_id="c1",
        theorem_decl="theorem c1 (m : Mass) (x : Real) (f : Time -> Length) : True",
        lean_header="import MechLib",
        local_binders=["m : Mass", "x : Real", "f : Time -> Length"],
    )

    assert physical_quantity_vars(context, POSITIVE_TYPES) == {"m": "Mass"}


def test_mass_denominator_adds_positive_hypothesis_and_compiles_augmented_theorem() -> None:
    runner = RecordingLeanRunner()
    context = ProofContext(
        sample_id="s1",
        candidate_id="c1",
        theorem_decl="theorem c1 (m : Mass) (a : Acceleration) : a.val = a.val / m.val",
        lean_header="import MechLib",
        target_formula="a.val = a.val / m.val",
        local_binders=["m : Mass", "a : Acceleration"],
        typed_binders=[{"symbol": "m", "lean_type": "Mass"}],
    )

    result = augment_context_for_missing_side_condition(
        context=context,
        proposal=_proposal("m.val"),
        positive_types=POSITIVE_TYPES,
        max_added=8,
        lean_runner=runner,
        require_compile=True,
    )

    assert result.check.status == "progress"
    assert "(h_m_pos : 0 < m.val)" in result.context.theorem_decl
    assert result.context.added_physical_assumptions[0]["source"] == "e_physical_assumption_augmentation"
    assert runner.compile_calls == [result.context.theorem_decl]


def test_sum_denominator_adds_two_positive_hypotheses() -> None:
    context = ProofContext(
        sample_id="s1",
        candidate_id="c1",
        theorem_decl="theorem c1 (m1 m2 : Mass) : True",
        lean_header="import MechLib",
        target_formula="a.val = F.val / (m1.val + m2.val)",
        local_binders=["m1 m2 : Mass"],
    )

    proposal = ProofActionProposal(
        action_id="missing_side_condition_1",
        strategy="missing_side_condition",
        tactic_block="",
        expected_effect=(
            "missing_side_condition: denominator m1.val + m2.val requires positivity facts for "
            "m1.val, m2.val"
        ),
        source="deterministic",
    )
    result = augment_context_for_missing_side_condition(
        context=context,
        proposal=proposal,
        positive_types=POSITIVE_TYPES,
        max_added=8,
        lean_runner=None,
        require_compile=False,
    )

    names = [item["name"] for item in result.context.added_physical_assumptions]
    assert names == ["h_m1_pos", "h_m2_pos"]
    assert "(h_m1_pos : 0 < m1.val)" in result.context.theorem_decl
    assert "(h_m2_pos : 0 < m2.val)" in result.context.theorem_decl


def test_real_variable_is_not_augmented() -> None:
    context = ProofContext(
        sample_id="s1",
        candidate_id="c1",
        theorem_decl="theorem c1 (x : Real) : True",
        lean_header="import Mathlib",
        local_binders=["x : Real"],
    )

    result = augment_context_for_missing_side_condition(
        context=context,
        proposal=_proposal("x.val"),
        positive_types=POSITIVE_TYPES,
        max_added=8,
        lean_runner=None,
        require_compile=False,
    )

    assert result.check.status == "invalid"
    assert result.check.error_type == "missing_term_not_typed_physical_quantity"
    assert result.context.theorem_decl == context.theorem_decl


def test_existing_name_conflict_gets_fresh_name() -> None:
    context = ProofContext(
        sample_id="s1",
        candidate_id="c1",
        theorem_decl="theorem c1 (m : Mass) (h_m_pos : True) : True",
        lean_header="import MechLib",
        local_binders=["m : Mass", "h_m_pos : True"],
        local_hypotheses=["h_m_pos"],
    )

    result = augment_context_for_missing_side_condition(
        context=context,
        proposal=_proposal("m.val"),
        positive_types=POSITIVE_TYPES,
        max_added=8,
        lean_runner=None,
        require_compile=False,
    )

    assert "(h_m_pos_2 : 0 < m.val)" in result.context.theorem_decl
