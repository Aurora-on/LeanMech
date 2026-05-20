from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from fractions import Fraction

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
_VALUE_EQ_RE = re.compile(
    r"(?P<name>[A-Za-z_][A-Za-z0-9_']*)\s*:\s*"
    r"(?P<term>[A-Za-z_][A-Za-z0-9_']*\.val)\s*=\s*(?P<value>[^,\]\n;]+)"
)
_NE_ZERO_RE = re.compile(
    r"(?P<name>[A-Za-z_][A-Za-z0-9_']*)\s*:\s*"
    r"(?P<term>[^,\]\n;]+?)\s*≠\s*0\b"
)
_BARE_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_']*$")
_NONZERO_NUMERIC_RE = re.compile(r"^[+-]?\d+(?:\.\d+)?$")


@dataclass(frozen=True)
class SideConditionNeed:
    kind: str
    expression: str
    missing_terms: list[str]


def _normalize_term(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip()).strip("() ")


def normalize_side_condition_expression(text: str) -> str:
    return _normalize_term(text)


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


def _extract_denominators_from_sources(sources: Iterable[str | None]) -> list[str]:
    seen: set[str] = set()
    denoms: list[str] = []
    for source in sources:
        for denom in extract_denominators(source):
            normalized = normalize_side_condition_expression(denom)
            if normalized and normalized not in seen:
                seen.add(normalized)
                denoms.append(denom)
    return denoms


def _sum_terms(expr: str) -> list[str]:
    parts = [_normalize_term(part) for part in expr.split("+")]
    return [part for part in parts if part]


def _product_factors(expr: str) -> list[str]:
    return [_normalize_term(part) for part in expr.split("*") if _normalize_term(part)]


def _is_ignorable_nonzero_factor(factor: str) -> bool:
    cleaned = _clean_numeric_literal(factor)
    if cleaned and _NONZERO_NUMERIC_RE.fullmatch(cleaned):
        return cleaned not in {"0", "+0", "-0"}
    return factor == "Real.pi"


def _required_positive_terms(expr: str) -> list[str]:
    """Return `.val` terms whose positivity is enough for supported denominators."""
    normalized = _normalize_term(expr)
    if "-" in normalized:
        return [normalized]
    terms = [match.group(0) for match in _VAL_TERM_RE.finditer(normalized)]
    if terms:
        return list(dict.fromkeys(terms))
    factors = _product_factors(normalized)
    if len(factors) > 1:
        variable_factors = [
            factor
            for factor in factors
            if not _is_ignorable_nonzero_factor(factor)
        ]
        if variable_factors:
            return list(dict.fromkeys(variable_factors))
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
        for term, name, value in _constant_value_equalities(fact):
            if value > 0:
                mapping.setdefault(term, name)
    return mapping


def _clean_numeric_literal(text: str) -> str:
    value = re.sub(r":\s*Real\b", "", text)
    value = value.replace("(", " ").replace(")", " ")
    return re.sub(r"\s+", " ", value).strip()


def _parse_numeric_literal(text: str) -> Fraction | None:
    value = _clean_numeric_literal(text)
    if not value:
        return None
    if re.fullmatch(r"[+-]?\d+", value):
        return Fraction(int(value), 1)
    if re.fullmatch(r"[+-]?\d+\s*/\s*[+-]?\d+", value):
        left, right = value.split("/", 1)
        denominator = int(right.strip())
        if denominator == 0:
            return None
        return Fraction(int(left.strip()), denominator)
    return None


def _constant_value_equalities(fact: str) -> list[tuple[str, str, Fraction]]:
    out: list[tuple[str, str, Fraction]] = []
    for match in _VALUE_EQ_RE.finditer(fact):
        numeric = _parse_numeric_literal(match.group("value"))
        if numeric is None:
            continue
        out.append((_normalize_term(match.group("term")), match.group("name").strip(), numeric))
    return out


def _nonzero_fact_map(current_facts: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for fact in current_facts:
        for match in _NE_ZERO_RE.finditer(fact):
            term = _normalize_term(match.group("term"))
            name = match.group("name").strip()
            if term:
                mapping.setdefault(term, name)
        for term, name, value in _constant_value_equalities(fact):
            if value != 0:
                mapping.setdefault(term, name)
    return mapping


def _direct_nonzero_fact_map(current_facts: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for fact in current_facts:
        for match in _NE_ZERO_RE.finditer(fact):
            term = _normalize_term(match.group("term"))
            name = match.group("name").strip()
            if term:
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
    nonzero_product_proof: str | None = None,
) -> ProofActionProposal:
    if nonzero_product_proof:
        tactic_block = f"have {have_name} : {denominator} ≠ 0 := by\n  exact {nonzero_product_proof}"
    else:
        tactic_terms = [*fact_names]
        if "Real.pi" in denominator:
            tactic_terms.insert(0, "Real.pi_pos")
        tactic_block = f"have {have_name} : {denominator} ≠ 0 := by\n  nlinarith [{', '.join(tactic_terms)}]"
    return ProofActionProposal(
        action_id=f"side_condition_{idx}",
        strategy="prove_side_condition",
        tactic_block=tactic_block,
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
    unavailable: bool = False,
) -> ProofActionProposal:
    strategy = "missing_side_condition_unavailable" if unavailable else "missing_side_condition"
    prefix = "missing_side_condition_unavailable" if unavailable else "missing_side_condition"
    return ProofActionProposal(
        action_id=f"missing_side_condition_{idx}",
        strategy=strategy,
        tactic_block="",
        uses_facts=[],
        uses_decls=[],
        expected_effect=(
            f"{prefix}: denominator {denominator} requires positivity/nonzero facts for "
            + ", ".join(missing_terms)
        ),
        source="deterministic",
        priority=0.0,
    )


def _is_unsupported_missing_denominator(denominator: str, missing_terms: list[str]) -> bool:
    normalized = _normalize_term(denominator)
    if "-" in normalized:
        return True
    if "Real.cos" in normalized or "Real.sin" in normalized or "Real.sqrt" in normalized:
        return True
    return any(term == normalized and not _VAL_TERM_RE.fullmatch(term) for term in missing_terms)


def _factor_nonzero_proof(factor: str, nonzero_facts: dict[str, str]) -> str | None:
    cleaned = _clean_numeric_literal(factor)
    if cleaned and _NONZERO_NUMERIC_RE.fullmatch(cleaned) and cleaned not in {"0", "+0", "-0"}:
        return "by norm_num"
    if factor == "Real.pi":
        return "Real.pi_ne_zero"
    return nonzero_facts.get(factor)


def _combine_mul_ne_zero(proofs: list[str]) -> str | None:
    if not proofs:
        return None
    combined = proofs[0]
    for proof in proofs[1:]:
        combined = f"mul_ne_zero ({combined}) {proof}"
    return combined


def _nonzero_product_proof(denominator: str, terms: list[str], nonzero_facts: dict[str, str]) -> str | None:
    if not terms or any(term not in nonzero_facts for term in terms):
        return None
    factors = _product_factors(denominator)
    if len(factors) <= 1:
        return nonzero_facts.get(_normalize_term(denominator))
    proofs: list[str] = []
    for factor in factors:
        proof = _factor_nonzero_proof(factor, nonzero_facts)
        if proof is None:
            return None
        proofs.append(proof)
    return _combine_mul_ne_zero(proofs)


def propose_side_condition_actions(
    proof_context: ProofContext,
    current_facts: list[str],
    known_denominators: Iterable[str] | None = None,
) -> list[ProofActionProposal]:
    """Propose deterministic nonzero-denominator actions from already checked facts.

    The initial implementation intentionally handles a narrow, proof-friendly pattern:
    a denominator that is a sum of positive `.val` terms.  If a positivity fact is missing,
    it returns a structured `missing_side_condition` proposal instead of asking the LLM to
    invent a proof.
    """
    denoms = _extract_denominators_from_sources(
        [
            proof_context.target_formula,
            *current_facts,
            *proof_context.allowed_local_facts,
            *proof_context.local_binders,
        ]
    )
    if not denoms:
        return []

    known = {normalize_side_condition_expression(denom) for denom in known_denominators or []}
    fact_sources = [*current_facts, *_context_positive_facts(proof_context)]
    pos_facts = _positive_fact_map(fact_sources)
    nonzero_facts = _nonzero_fact_map(fact_sources)
    direct_nonzero_facts = _direct_nonzero_fact_map(fact_sources)
    used_names = set(current_facts) | set(proof_context.allowed_local_facts) | set(proof_context.local_hypotheses)
    proposals: list[ProofActionProposal] = []
    for idx, denom in enumerate(denoms, start=1):
        if normalize_side_condition_expression(denom) in known:
            continue
        terms = _required_positive_terms(denom)
        missing = [term for term in terms if term not in pos_facts and term not in nonzero_facts]
        if missing:
            proposals.append(
                _missing_side_condition_proposal(
                    idx=idx,
                    denominator=denom,
                    missing_terms=missing,
                    unavailable=_is_unsupported_missing_denominator(denom, missing),
                )
            )
            continue
        fact_names = [pos_facts.get(term) or nonzero_facts[term] for term in terms]
        nonzero_product_proof = _nonzero_product_proof(denom, terms, direct_nonzero_facts)
        proposals.append(
            _side_condition_proposal(
                idx=idx,
                denominator=denom,
                fact_names=fact_names,
                have_name=_safe_have_name(denom, used_names),
                nonzero_product_proof=nonzero_product_proof,
            )
        )
    return proposals
