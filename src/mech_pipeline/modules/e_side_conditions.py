from __future__ import annotations

import re
from dataclasses import dataclass

from mech_pipeline.types import ProofActionProposal, ProofContext

_DENOM_RE = re.compile(r"/\s*\((?P<denom>[^()]+)\)")
_SIMPLE_DENOM_RE = re.compile(r"/\s*(?P<denom>[A-Za-z_][A-Za-z0-9_']*\.val)\b")
_VAL_TERM_RE = re.compile(r"\b(?P<name>[A-Za-z_][A-Za-z0-9_']*)\.val\b")
_POS_LT_RE = re.compile(
    r"(?P<name>[A-Za-z_][A-Za-z0-9_']*)\s*:\s*0\s*<\s*(?P<term>[^,\]\n;]+)"
)
_POS_GT_RE = re.compile(
    r"(?P<name>[A-Za-z_][A-Za-z0-9_']*)\s*:\s*(?P<term>[^,\]\n;]+)\s*>\s*0"
)
_HAVE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_']*$")


@dataclass(frozen=True)
class SideConditionNeed:
    kind: str
    expression: str
    missing_terms: list[str]


def _normalize_term(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip()).strip("() ")


def extract_denominators(target: str | None) -> list[str]:
    """Extract simple parenthesized denominator expressions from a Lean target string."""
    if not target:
        return []
    seen: set[str] = set()
    denoms: list[str] = []
    for match in _DENOM_RE.finditer(target):
        denom = _normalize_term(match.group("denom"))
        if denom and denom not in seen:
            seen.add(denom)
            denoms.append(denom)
    for match in _SIMPLE_DENOM_RE.finditer(target):
        denom = _normalize_term(match.group("denom"))
        if denom and denom not in seen:
            seen.add(denom)
            denoms.append(denom)
    return denoms


def _sum_terms(expr: str) -> list[str]:
    parts = [_normalize_term(part) for part in expr.split("+")]
    return [part for part in parts if part]


def _required_positive_terms(expr: str) -> list[str]:
    """Return `.val` terms whose positivity is enough for supported denominators."""
    normalized = _normalize_term(expr)
    if "-" in normalized:
        return [normalized]
    terms = [match.group(0) for match in _VAL_TERM_RE.finditer(normalized)]
    if terms:
        return list(dict.fromkeys(terms))
    sum_terms = _sum_terms(normalized)
    return sum_terms if sum_terms else [normalized]


def _positive_fact_map(current_facts: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for fact in current_facts:
        for regex in (_POS_LT_RE, _POS_GT_RE):
            match = regex.search(fact)
            if match:
                name = match.group("name").strip()
                term = _normalize_term(match.group("term"))
                mapping.setdefault(term, name)
    return mapping


def _context_positive_facts(proof_context: ProofContext) -> list[str]:
    return [chunk for chunk in proof_context.local_binders if ":" in chunk]


def _safe_have_name(base: str, used: set[str]) -> str:
    stem = re.sub(r"[^A-Za-z0-9_']", "_", base).strip("_") or "den"
    if stem[0].isdigit():
        stem = f"den_{stem}"
    candidate = f"hden_{stem}"
    if not _HAVE_NAME_RE.match(candidate):
        candidate = "hden"
    if candidate not in used:
        used.add(candidate)
        return candidate
    idx = 2
    while f"{candidate}_{idx}" in used:
        idx += 1
    out = f"{candidate}_{idx}"
    used.add(out)
    return out


def _side_condition_proposal(
    *,
    idx: int,
    denominator: str,
    fact_names: list[str],
    have_name: str,
) -> ProofActionProposal:
    return ProofActionProposal(
        action_id=f"side_condition_{idx}",
        strategy="prove_side_condition",
        tactic_block=f"have {have_name} : {denominator} ≠ 0 := by\n  nlinarith [{', '.join(fact_names)}]",
        uses_facts=fact_names,
        uses_decls=[],
        expected_effect=f"prove denominator nonzero: {denominator}",
        source="deterministic",
        priority=0.8,
    )


def _missing_side_condition_proposal(
    *,
    idx: int,
    denominator: str,
    missing_terms: list[str],
) -> ProofActionProposal:
    return ProofActionProposal(
        action_id=f"missing_side_condition_{idx}",
        strategy="missing_side_condition",
        tactic_block="",
        uses_facts=[],
        uses_decls=[],
        expected_effect=(
            f"missing_side_condition: denominator {denominator} requires positivity facts for "
            + ", ".join(missing_terms)
        ),
        source="deterministic",
        priority=0.0,
    )


def propose_side_condition_actions(
    proof_context: ProofContext,
    current_facts: list[str],
) -> list[ProofActionProposal]:
    """Propose deterministic nonzero-denominator actions from already checked facts.

    The initial implementation intentionally handles a narrow, proof-friendly pattern:
    a denominator that is a sum of positive `.val` terms.  If a positivity fact is missing,
    it returns a structured `missing_side_condition` proposal instead of asking the LLM to
    invent a proof.
    """
    denoms = extract_denominators(proof_context.target_formula)
    if not denoms:
        return []

    pos_facts = _positive_fact_map([*current_facts, *_context_positive_facts(proof_context)])
    used_names = set(current_facts) | set(proof_context.allowed_local_facts) | set(proof_context.local_hypotheses)
    proposals: list[ProofActionProposal] = []
    for idx, denom in enumerate(denoms, start=1):
        terms = _required_positive_terms(denom)
        missing = [term for term in terms if term not in pos_facts]
        if missing:
            proposals.append(
                _missing_side_condition_proposal(
                    idx=idx,
                    denominator=denom,
                    missing_terms=missing,
                )
            )
            continue
        fact_names = [pos_facts[term] for term in terms]
        proposals.append(
            _side_condition_proposal(
                idx=idx,
                denominator=denom,
                fact_names=fact_names,
                have_name=_safe_have_name(denom, used_names),
            )
        )
    return proposals
