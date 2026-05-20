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


def test_algebra_cards_offer_log_exp_solve_for_capstan_shape() -> None:
    cards = available_algebra_strategy_cards(
        _context("n = Real.log (M / m) / (2 * Real.pi * mu)"),
        ["hcapstan : M / m = Real.exp (mu * theta)"],
    )

    log_card = next(card for card in cards if card["strategy"] == "log_exp_solve")
    assert "Real.log_exp" in log_card["recommended_tactics"]


def test_algebra_cards_offer_sqrt_square_solve_for_sqrt_shape() -> None:
    cards = available_algebra_strategy_cards(
        _context("v_max.val = Real.sqrt y"),
        ["h_vmax_formula : v_max.val = Real.sqrt y"],
    )

    sqrt_card = next(card for card in cards if card["strategy"] == "sqrt_square_solve")
    assert "exact" in sqrt_card["recommended_tactics"]


def test_algebra_cards_offer_linear_and_nonlinear_arithmetic_from_equalities() -> None:
    cards = available_algebra_strategy_cards(
        _context("F = m * a"),
        ["h1 : F = m * a", "h2 : T = F"],
    )
    strategies = _strategies(cards)

    assert "equation_chain_synthesis" in strategies
    assert "linear_arithmetic" in strategies
    assert "definition_merge" in strategies
    assert "nonlinear_arithmetic" in strategies
    assert "ring_normalization" in strategies


def test_algebra_cards_describe_incremental_equation_chain() -> None:
    cards = available_algebra_strategy_cards(
        _context("delta_x.val = m_B.val * (a.val - b.val) / (m_A.val + m_B.val)"),
        ["h_com : m_A.val * dxA.val + m_B.val * dxB.val = 0"],
    )

    card = next(card for card in cards if card["strategy"] == "equation_chain_synthesis")
    assert "one closed intermediate equation" in card["description"]
    assert "nlinarith" in card["recommended_tactics"]
