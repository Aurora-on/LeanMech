from __future__ import annotations

from mech_pipeline.modules.e_algebra_strategy import available_algebra_strategy_cards
from mech_pipeline.types import ProofContext


def _context(target: str) -> ProofContext:
    return ProofContext(
        sample_id="s1",
        candidate_id="c1",
        theorem_decl="theorem c1 : True",
        lean_header="import Mathlib",
        target_formula=target,
    )


def _strategies(cards: list[dict]) -> set[str]:
    return {str(card["strategy"]) for card in cards}


def test_algebra_cards_offer_split_for_conjunction_target() -> None:
    cards = available_algebra_strategy_cards(_context("A ∧ B"), [])

    assert "split_conjunction" in _strategies(cards)


def test_algebra_cards_offer_field_normalization_for_division_target() -> None:
    cards = available_algebra_strategy_cards(
        _context("a = F / (m1.val + m2.val)"),
        ["hden : m1.val + m2.val ≠ 0"],
    )

    field_card = next(card for card in cards if card["strategy"] == "field_normalization")
    assert field_card["available_denominator_fact"] is True


def test_algebra_cards_offer_linear_and_nonlinear_arithmetic_from_equalities() -> None:
    cards = available_algebra_strategy_cards(
        _context("F = m * a"),
        ["h1 : F = m * a", "h2 : T = F"],
    )
    strategies = _strategies(cards)

    assert "linear_arithmetic" in strategies
    assert "definition_merge" in strategies
    assert "nonlinear_arithmetic" in strategies
    assert "ring_normalization" in strategies
