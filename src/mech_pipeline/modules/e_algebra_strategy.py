from __future__ import annotations

import re
from typing import Any

from mech_pipeline.types import ProofContext

_EQUALITY_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_']*\s*:\s*[^:\n]+=[^=\n]+")
_PRODUCT_RE = re.compile(r"(\*|\^|·)")


def _fact_texts(current_facts: list[str]) -> list[str]:
    return [str(fact or "").strip() for fact in current_facts if str(fact or "").strip()]


def _has_equality(facts: list[str]) -> bool:
    return any("=" in fact and "≠" not in fact for fact in facts) or any(_EQUALITY_RE.search(fact) for fact in facts)


def _has_product_or_power(text: str, facts: list[str]) -> bool:
    return bool(_PRODUCT_RE.search(text)) or any(_PRODUCT_RE.search(fact) for fact in facts)


def _has_denominator_nonzero_fact(facts: list[str]) -> bool:
    return any("≠ 0" in fact or "!= 0" in fact for fact in facts)


def _has_log_exp_shape(target: str, facts: list[str]) -> bool:
    return "Real.log" in target and any("Real.exp" in fact for fact in facts)


def _has_sqrt_shape(target: str, facts: list[str]) -> bool:
    return "Real.sqrt" in target or any("Real.sqrt" in fact for fact in facts)


def available_algebra_strategy_cards(
    proof_context: ProofContext,
    current_facts: list[str],
) -> list[dict[str, Any]]:
    """Expose algebra tactics as LLM-selectable strategy cards.

    This function intentionally does not produce tactic blocks.  It only describes
    applicable algebra strategies so the LLM can decide when and how to parameterize
    the next local proof action.
    """
    target = str(proof_context.target_formula or "")
    facts = _fact_texts(current_facts)
    cards: list[dict[str, Any]] = []

    if _has_log_exp_shape(target, facts):
        cards.append(
            {
                "strategy": "log_exp_solve",
                "when": "target contains Real.log and local facts contain Real.exp",
                "recommended_tactics": ["calc", "rw", "Real.log_exp", "field_simp", "ring_nf"],
                "description": (
                    "First derive a log equation from an exponential law using Real.log_exp, "
                    "then substitute angle/turn relations and normalize the division."
                ),
            }
        )

    if _has_sqrt_shape(target, facts):
        cards.append(
            {
                "strategy": "sqrt_square_solve",
                "when": "target or local facts contain Real.sqrt",
                "recommended_tactics": ["exact", "simpa"],
                "description": (
                    "Use an already available sqrt formula directly before trying arithmetic; "
                    "do not reprove sqrt branches with nlinarith when a matching fact exists."
                ),
            }
        )

    if "∧" in target or "/\\" in target:
        cards.append(
            {
                "strategy": "split_conjunction",
                "when": "target is A ∧ B",
                "recommended_tactics": ["constructor"],
                "description": "Use constructor to split a conjunctive goal into subgoals.",
            }
        )

    if _has_equality(facts) and "=" in target:
        cards.append(
            {
                "strategy": "equation_chain_synthesis",
                "when": "target and local facts are equations that require intermediate algebraic equalities",
                "recommended_tactics": ["have", "linarith", "nlinarith", "field_simp", "ring_nf"],
                "description": (
                    "Propose one closed intermediate equation at a time, let Lean check it, "
                    "then continue from the updated local context instead of generating a full proof at once."
                ),
            }
        )

    if "/" in target:
        card: dict[str, Any] = {
            "strategy": "field_normalization",
            "when": "target contains division",
            "recommended_tactics": ["field_simp"],
            "description": "Use field_simp [hden] when a denominator nonzero fact is available.",
        }
        if _has_denominator_nonzero_fact(facts):
            card["available_denominator_fact"] = True
        else:
            card["requires_side_condition"] = "denominator_nonzero"
        cards.append(card)

    if _has_equality(facts):
        cards.append(
            {
                "strategy": "linear_arithmetic",
                "when": "local facts include linear equalities or inequalities",
                "recommended_tactics": ["linarith"],
                "description": "Use linarith when equations are linear.",
            }
        )
        cards.append(
            {
                "strategy": "definition_merge",
                "when": "model definition equations and law equations must be combined",
                "recommended_tactics": ["linarith"],
                "description": "Use linarith to merge model definition equations and extracted law equations.",
            }
        )

    if _has_product_or_power(target, facts):
        cards.append(
            {
                "strategy": "nonlinear_arithmetic",
                "when": "products, powers, or cleared denominators appear",
                "recommended_tactics": ["nlinarith"],
                "description": "Use nlinarith when products or cleared denominators appear.",
            }
        )
        cards.append(
            {
                "strategy": "ring_normalization",
                "when": "polynomial expressions need normalization",
                "recommended_tactics": ["ring_nf"],
                "description": "Use ring_nf to normalize polynomial expressions.",
            }
        )

    return cards
