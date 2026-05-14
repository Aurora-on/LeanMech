from __future__ import annotations

from pathlib import Path

from mech_pipeline.adapters.lean_runner import LeanRunner, classify_proof_probe_result


def _runner() -> LeanRunner:
    root = Path(__file__).resolve().parents[1]
    return LeanRunner(
        physlean_dir=root,
        mechlib_dir=root,
        timeout_s=120,
        strict_blocklist=["sorry", "admit", "axiom"],
        lean_header="import Mathlib",
        route_policy="force_mechlib",
        default_backend="mechlib",
        route_fallback=False,
    )


THEOREM_DECL = "theorem e_probe_real_symm (a b : Real) (h : a = b) : b = a"


def test_probe_proof_prefix_closed_for_complete_prefix() -> None:
    result = _runner().probe_proof_prefix(
        lean_header="import Mathlib",
        theorem_decl=THEOREM_DECL,
        proof_prefix="symm\nexact h",
        timeout_s=120,
    )

    assert result.status == "closed"
    assert result.error_type is None


def test_probe_proof_prefix_progress_for_unsolved_goals() -> None:
    result = _runner().probe_proof_prefix(
        lean_header="import Mathlib",
        theorem_decl=THEOREM_DECL,
        proof_prefix="symm",
        timeout_s=120,
    )

    assert result.status == "progress"
    assert result.error_type == "unsolved_goals"
    assert result.goals_excerpt
    assert "unsolved goals" in result.goals_excerpt.lower()


def test_probe_proof_prefix_invalid_for_unknown_identifier() -> None:
    result = _runner().probe_proof_prefix(
        lean_header="import Mathlib",
        theorem_decl=THEOREM_DECL,
        proof_prefix="exact missing_h",
        timeout_s=120,
    )

    assert result.status == "invalid"
    assert result.error_type == "symbol_hallucination"
    assert result.stderr_excerpt
    assert "missing_h" in result.stderr_excerpt


def test_probe_result_rejects_elaboration_error_even_with_unsolved_goals() -> None:
    stderr = """
/tmp/pipeline_proof_probe.lean:24:54: error: Application type mismatch: The argument
  mi1_law
has type
  Dynamics.NewtonLaw.NewtonSecondLaw m1 a Fnet1
but is expected to have type
  Compat.PHYSlib.SI.Mass
/tmp/pipeline_proof_probe.lean:22:59: error: unsolved goals
m1 m2 : Mass
⊢ True
"""

    result = classify_proof_probe_result(
        ok=False,
        stdout="",
        stderr=stderr,
        tactic_block="have h_bad : T = m1 * a := by\n  exact bad mi1_law",
    )

    assert result.status == "invalid"
    assert result.error_type == "type_mismatch"
    assert result.goals_excerpt is None
    assert result.stderr_excerpt
    assert "Application type mismatch" in result.stderr_excerpt


def test_probe_result_classifies_no_goals_with_location_and_debug_body() -> None:
    stderr = """
/tmp/pipeline_proof_probe.lean:21:59: error: unsolved goals
m1 m2 : Mass
⊢ True
/tmp/pipeline_proof_probe.lean:34:4: error: No goals to be solved
"""
    proof_body = "have h : True := by\n  trivial\n  trivial"

    result = classify_proof_probe_result(
        ok=False,
        stdout="",
        stderr=stderr,
        tactic_block=proof_body,
        probe_full_proof_body=proof_body,
    )

    assert result.status == "invalid"
    assert result.error_type == "tactic_no_goals"
    assert result.error_message == "No goals to be solved"
    assert result.error_line == 34
    assert result.error_col == 4
    assert result.error_snippet
    assert "No goals to be solved" in result.error_snippet
    assert result.probe_full_proof_body == proof_body
    assert result.goals_excerpt is None


def test_probe_proof_prefix_rejects_sorry_without_running_as_progress() -> None:
    result = _runner().probe_proof_prefix(
        lean_header="import Mathlib",
        theorem_decl=THEOREM_DECL,
        proof_prefix="sorry",
        timeout_s=120,
    )

    assert result.status == "invalid"
    assert result.error_type == "forbidden_token"
