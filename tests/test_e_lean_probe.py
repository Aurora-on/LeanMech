from __future__ import annotations

from pathlib import Path

from mech_pipeline.adapters.lean_runner import LeanRunner


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


def test_probe_proof_prefix_rejects_sorry_without_running_as_progress() -> None:
    result = _runner().probe_proof_prefix(
        lean_header="import Mathlib",
        theorem_decl=THEOREM_DECL,
        proof_prefix="sorry",
        timeout_s=120,
    )

    assert result.status == "invalid"
    assert result.error_type == "forbidden_token"
