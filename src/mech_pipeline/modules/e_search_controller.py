from __future__ import annotations

import json
import re
import tempfile
import time
from collections.abc import Iterable
from dataclasses import asdict, dataclass, replace
from hashlib import sha256
from pathlib import Path
from typing import Any

from mech_pipeline.config import LLMGuidedSearchConfig, PipelineConfig
from mech_pipeline.modules.e_action_guard import validate_action_proposal
from mech_pipeline.modules.e_certified_replay import run_deterministic_obligation_replay_with_probe
from mech_pipeline.modules.e_physical_assumption_augmenter import augment_context_for_missing_side_condition
from mech_pipeline.modules.e_side_conditions import (
    extract_denominators,
    normalize_side_condition_expression,
    propose_side_condition_actions,
)
from mech_pipeline.modules.e_strategy_controller import LLMStrategyController
from mech_pipeline.types import (
    ProofActionCheckResult,
    ProofActionProposal,
    ProofContext,
    ProofSearchNode,
    ProofSearchTrace,
)
from mech_pipeline.utils import normalize_lean_text, truncate

_HAVE_FACT_RE = re.compile(r"^\s*have\s+([A-Za-z_][A-Za-z0-9_']*)\b", re.MULTILINE)
_HAVE_CLAIM_RE = re.compile(
    r"^\s*have\s+[A-Za-z_][A-Za-z0-9_']*\s*:\s*(?P<claim>.*?)\s*:=\s*by\b",
    re.MULTILINE,
)
_HAVE_CLAIM_BY_NAME_RE = re.compile(
    r"^\s*have\s+(?P<name>[A-Za-z_][A-Za-z0-9_']*)\s*:\s*(?P<claim>.*?)\s*:=\s*by\b",
    re.MULTILINE,
)
_HAVE_NAME_SHAPE_RE = re.compile(
    r"(?m)^(\s*have\s+)[A-Za-z_][A-Za-z0-9_']*(\s*:|\s*:=)"
)
_WHOLE_HAVE_BY_RE = re.compile(
    r"^\s*(?P<header>have\s+[A-Za-z_][A-Za-z0-9_']*\s*:\s*.*?\s*:=\s*by)\s*(?P<body>.*)$"
)
_CONSTRUCTOR_LINE_RE = re.compile(r"^\s*constructor\b")
_HAVE_BY_LINE_RE = re.compile(r"^\s*have\s+[A-Za-z_][A-Za-z0-9_']*\s*:.*:=\s*by\b")
_SIDE_CONDITION_EXPECTED_RE = re.compile(
    r"(?:prove denominator nonzero:|missing_side_condition(?:_unavailable)?: denominator)\s*"
    r"(?P<denom>.*?)(?:\s+requires positivity/nonzero facts for|$)"
)
_SIDE_CONDITION_CLAIM_RE = re.compile(
    r"^\s*have\s+[A-Za-z_][A-Za-z0-9_']*\s*:\s*(?P<denom>.*?)\s*≠\s*0\s*:=\s*by\b",
    re.MULTILINE,
)
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_']*$")
_FUNCTION_VALUE_APPLICATION_RE = re.compile(
    r"\(\s*(?P<fn>[A-Za-z_][A-Za-z0-9_']*)\s+"
    r"(?P<arg>(?:\([^()]*\)|[^()])+?)\s*\)\.val"
)
_REAL_LITERAL_RE = re.compile(r"^(?:\d+(?:\.\d+)?|\(\s*\d+(?:\.\d+)?\s*:\s*Real\s*\))$")
OBLIGATION_GUIDED_SEARCH = "obligation_guided_search"
TARGET_PROOF_FROM_AVAILABLE_FACTS = "target_proof_from_available_facts"
MAX_FACT_PLAN_ACTIONS = 12
MAX_CLAIM_REPAIR_PROMPT_CHARS = 7000
MAX_UNIVERSAL_INSTANTIATIONS = 12


@dataclass(frozen=True)
class _StructuralPreludePlan:
    tactic_block: str
    introduced_facts: list[str]
    introduced_fact_types: dict[str, str]


@dataclass(frozen=True)
class _LogExpMatch:
    exp_fact_name: str
    log_arg: str
    exponent: str
    rewrite_tactic: str
    hlog_claim: str


def _search_cfg(cfg: Any) -> LLMGuidedSearchConfig:
    if isinstance(cfg, PipelineConfig):
        return cfg.proof.llm_guided_search
    proof = getattr(cfg, "proof", None)
    if proof is not None and hasattr(proof, "llm_guided_search"):
        return proof.llm_guided_search
    if isinstance(cfg, LLMGuidedSearchConfig):
        return cfg
    return LLMGuidedSearchConfig()


def _call_llm(llm_client: Any, prompt: str) -> str:
    if hasattr(llm_client, "generate_text"):
        response = llm_client.generate_text(prompt)
    elif hasattr(llm_client, "complete"):
        response = llm_client.complete(prompt)
    elif callable(llm_client):
        response = llm_client(prompt)
    else:
        raise TypeError("llm_client must expose generate_text, complete, or be callable")
    if isinstance(response, str):
        return response
    return str(getattr(response, "text", response))


def _load_llm_json(text: str) -> dict[str, Any]:
    raw = normalize_lean_text(text).strip()
    if raw.startswith("```"):
        raw = raw.replace("```json", "").replace("```", "").strip()
    payload = json.loads(raw or "{}")
    return payload if isinstance(payload, dict) else {}


def _decl_without_body(theorem_decl: str) -> str:
    decl = normalize_lean_text(theorem_decl or "")
    if ":=" in decl:
        decl = decl.split(":=", 1)[0]
    if decl.rstrip().endswith(" by"):
        decl = decl.rstrip()[:-3]
    return decl.strip()


def _theorem_target_from_decl(theorem_decl: str) -> str | None:
    decl = _decl_without_body(theorem_decl)
    depth = 0
    closer_for = {"(": ")", "{": "}", "[": "]"}
    closers = set(closer_for.values())
    stack: list[str] = []
    for index, char in enumerate(decl):
        if char in closer_for:
            stack.append(closer_for[char])
            depth += 1
            continue
        if char in closers and stack and char == stack[-1]:
            stack.pop()
            depth = max(0, depth - 1)
            continue
        if char == ":" and depth == 0:
            if index + 1 < len(decl) and decl[index + 1] == "=":
                continue
            target = decl[index + 1 :].strip()
            return target or None
    return None


def _top_level_token_index(text: str, token: str) -> int | None:
    if not token:
        return None
    depth = 0
    closer_for = {"(": ")", "{": "}", "[": "]"}
    closers = set(closer_for.values())
    stack: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char in closer_for:
            stack.append(closer_for[char])
            depth += 1
            index += 1
            continue
        if char in closers and stack and char == stack[-1]:
            stack.pop()
            depth = max(0, depth - 1)
            index += 1
            continue
        if depth == 0 and text.startswith(token, index):
            return index
        index += 1
    return None


def _top_level_split(text: str, token: str) -> tuple[str, str] | None:
    index = _top_level_token_index(text, token)
    if index is None:
        return None
    left = text[:index].strip()
    right = text[index + len(token) :].strip()
    if not left or not right:
        return None
    return left, right


def _strip_outer_parens(text: str) -> str:
    value = normalize_lean_text(text or "").strip()
    while value.startswith("(") and value.endswith(")"):
        close_index = _matching_close_index(value, 0)
        if close_index != len(value) - 1:
            break
        value = value[1:-1].strip()
    return value


def _matching_close_index(text: str, open_index: int) -> int | None:
    if open_index >= len(text) or text[open_index] not in "({[":
        return None
    opener = text[open_index]
    closer = {"(": ")", "{": "}", "[": "]"}[opener]
    depth = 1
    index = open_index + 1
    while index < len(text):
        char = text[index]
        if char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return None


def _split_top_level_implication(text: str) -> tuple[str, str] | None:
    value = _strip_outer_parens(text)
    return _top_level_split(value, "->") or _top_level_split(value, "→")


def _split_top_level_conjunctions(text: str) -> list[str]:
    value = _strip_outer_parens(text)
    parts: list[str] = []
    remainder = value
    while True:
        split = _top_level_split(remainder, "∧")
        if split is None:
            break
        left, remainder = split
        parts.extend(_split_top_level_conjunctions(left))
    if remainder:
        tail = _strip_outer_parens(remainder)
        if tail and _top_level_split(tail, "∧") is not None:
            parts.extend(_split_top_level_conjunctions(tail))
        elif tail:
            parts.append(tail)
    return [part for part in parts if part]


def _split_forall_prefix(text: str) -> tuple[list[tuple[str, str | None]], str] | None:
    value = _strip_outer_parens(text)
    if value.startswith("forall "):
        rest = value[len("forall ") :].strip()
    elif value.startswith("∀"):
        rest = value[1:].strip()
    else:
        return None
    comma = _top_level_token_index(rest, ",")
    if comma is None:
        return None
    binder_text = _strip_outer_parens(rest[:comma].strip())
    remaining = rest[comma + 1 :].strip()
    if not binder_text or not remaining:
        return None
    if ":" in binder_text:
        names_part, type_part = binder_text.split(":", 1)
        binder_type = type_part.strip() or None
    else:
        names_part = binder_text
        binder_type = None
    names = re.findall(r"\b[A-Za-z_][A-Za-z0-9_']*\b", names_part)
    if not names:
        return None
    return [(name, binder_type) for name in names], remaining


def _replace_identifier(text: str, old: str, new: str) -> str:
    if old == new:
        return text
    return re.sub(rf"\b{re.escape(old)}\b", new, text)


def _substitute_identifiers(text: str, substitutions: dict[str, str]) -> str:
    out = text
    for old, new in substitutions.items():
        out = _replace_identifier(out, old, new)
    return out


def _normalized_claim_key(text: str | None) -> str:
    return re.sub(r"\s+", " ", normalize_lean_text(str(text or "")).strip())


def _core_target_after_structural_prefix(text: str | None) -> str:
    current = normalize_lean_text(str(text or "")).strip()
    while True:
        parsed = _split_forall_prefix(current)
        if parsed is None:
            break
        _binders, current = parsed
    while True:
        split = _split_top_level_implication(current)
        if split is None:
            break
        _premise, current = split
    return _strip_outer_parens(current)


def _target_components(proof_context: ProofContext) -> list[str]:
    target = _theorem_target_from_decl(proof_context.theorem_decl) or str(proof_context.target_formula or "")
    core = _core_target_after_structural_prefix(target)
    components = _split_top_level_conjunctions(core)
    return components if len(components) > 1 else []


def _component_close_proposal(proof_context: ProofContext, node: ProofSearchNode) -> ProofActionProposal | None:
    components = _target_components(proof_context)
    if not components:
        return None
    fact_types = _local_fact_types_from_context(proof_context)
    fact_types.update(node.local_fact_types)
    fact_names: list[str] = []
    for component in components:
        fact_name = _fact_name_for_claim(component, fact_types)
        if not fact_name:
            return None
        fact_names.append(fact_name)
    return ProofActionProposal(
        action_id="deterministic_component_close",
        strategy="close_target_components",
        tactic_block=f"exact ⟨{', '.join(fact_names)}⟩",
        uses_facts=fact_names,
        uses_decls=[],
        expected_effect="close top-level conjunction target from matching component facts",
        source="deterministic",
        priority=1.2,
    )


def _missing_target_component_claims(proof_context: ProofContext, node: ProofSearchNode) -> list[str]:
    components = _target_components(proof_context)
    if not components:
        return []
    fact_types = _local_fact_types_from_context(proof_context)
    fact_types.update(node.local_fact_types)
    return [component for component in components if not _fact_name_for_claim(component, fact_types)]


def _llm_conjunction_close_disallowed(proof_context: ProofContext, proposal: ProofActionProposal) -> bool:
    return (
        proposal.source == "llm"
        and proposal.strategy in {"close_goal", "target_fact_plan_close", "split_conjunction"}
        and bool(_target_components(proof_context))
    )


def _top_level_equality(text: str) -> tuple[str, str] | None:
    value = _strip_outer_parens(normalize_lean_text(text or ""))
    if "≠" in value:
        return None
    return _top_level_split(value, "=")


def _lean_parenthesized(expr: str) -> str:
    value = _strip_outer_parens(normalize_lean_text(expr or ""))
    return f"({value})"


def _real_exp_argument(expr: str) -> str | None:
    value = _strip_outer_parens(normalize_lean_text(expr or ""))
    if not value.startswith("Real.exp"):
        return None
    rest = value[len("Real.exp") :].strip()
    if not rest:
        return None
    return _strip_outer_parens(rest)


def _parse_real_exp_equality(fact_name: str, type_text: str) -> _LogExpMatch | None:
    split = _top_level_equality(type_text)
    if split is None:
        return None
    left, right = split
    right_exp_arg = _real_exp_argument(right)
    if right_exp_arg:
        log_arg = _strip_outer_parens(left)
        exponent = _strip_outer_parens(right_exp_arg)
        return _LogExpMatch(
            exp_fact_name=fact_name,
            log_arg=log_arg,
            exponent=exponent,
            rewrite_tactic=f"rw [{fact_name}]",
            hlog_claim=f"Real.log {_lean_parenthesized(log_arg)} = {exponent}",
        )
    left_exp_arg = _real_exp_argument(left)
    if left_exp_arg:
        log_arg = _strip_outer_parens(right)
        exponent = _strip_outer_parens(left_exp_arg)
        return _LogExpMatch(
            exp_fact_name=fact_name,
            log_arg=log_arg,
            exponent=exponent,
            rewrite_tactic=f"rw [← {fact_name}]",
            hlog_claim=f"Real.log {_lean_parenthesized(log_arg)} = {exponent}",
        )
    return None


def _expr_key(expr: str) -> str:
    return re.sub(r"\s+", "", _strip_outer_parens(normalize_lean_text(expr or "")))


def _target_mentions_log_arg(proof_context: ProofContext, log_arg: str) -> bool:
    target = normalize_lean_text(str(proof_context.target_formula or ""))
    if "Real.log" not in target:
        return False
    return _expr_key(log_arg) in _expr_key(target)


def _target_log_argument(proof_context: ProofContext) -> str | None:
    target = normalize_lean_text(str(proof_context.target_formula or ""))
    marker = "Real.log"
    index = target.find(marker)
    if index < 0:
        return None
    rest = target[index + len(marker) :].strip()
    if not rest:
        return None
    if rest.startswith("("):
        close = _matching_close_index(rest, 0)
        if close is not None:
            return _strip_outer_parens(rest[: close + 1])
    match = re.match(r"([A-Za-z_][A-Za-z0-9_']*(?:\.val)?)", rest)
    return match.group(1) if match else None


def _log_exp_matches(proof_context: ProofContext, node: ProofSearchNode) -> list[_LogExpMatch]:
    if "Real.log" not in str(proof_context.target_formula or ""):
        return []
    fact_types = _local_fact_types_from_context(proof_context)
    fact_types.update(node.local_fact_types)
    matches: list[_LogExpMatch] = []
    for fact_name, type_text in fact_types.items():
        if "Real.exp" not in type_text:
            continue
        match = _parse_real_exp_equality(fact_name, type_text)
        if match and _target_mentions_log_arg(proof_context, match.log_arg):
            matches.append(match)
    return matches


def _is_nonzero_numeric_literal(text: str) -> bool:
    value = normalize_lean_text(text or "")
    value = re.sub(r":\s*Real\b", "", value)
    value = value.replace("(", " ").replace(")", " ")
    value = re.sub(r"\s+", "", value)
    if re.fullmatch(r"[+-]?\d+", value):
        return value not in {"0", "+0", "-0"}
    if re.fullmatch(r"[+-]?\d+/[+-]?\d+", value):
        left, right = value.split("/", 1)
        return int(left) != 0 and int(right) != 0
    return False


def _nonzero_numeric_equality_for_term(term: str, fact_types: dict[str, str]) -> str | None:
    target = _expr_key(term)
    for fact_name, type_text in fact_types.items():
        split = _top_level_equality(type_text)
        if split is None:
            continue
        left, right = split
        if _expr_key(left) == target and _is_nonzero_numeric_literal(right):
            return fact_name
    return None


def _positive_fact_for_term(term: str, fact_types: dict[str, str]) -> tuple[str, str] | None:
    target = _expr_key(term)
    for fact_name, type_text in fact_types.items():
        claim = _strip_outer_parens(type_text)
        if _expr_key(claim) == _expr_key(f"0 < {term}"):
            return fact_name, f"{fact_name}.ne'"
        if _expr_key(claim) == _expr_key(f"{term} > 0"):
            return fact_name, f"{fact_name}.ne"
    return None


def _ratio_parts(expr: str) -> tuple[str, str] | None:
    split = _top_level_split(_strip_outer_parens(expr), "/")
    if split is None:
        return None
    return _strip_outer_parens(split[0]), _strip_outer_parens(split[1])


def _factor_rewrite_for_product_relation(
    *,
    exp_term: str,
    target_term: str,
    fact_types: dict[str, str],
) -> tuple[str, str, str] | None:
    exp_key = _expr_key(exp_term)
    target_key = _expr_key(target_term)
    for fact_name, type_text in fact_types.items():
        split = _top_level_equality(type_text)
        if split is None:
            continue
        left, right = (_strip_outer_parens(split[0]), _strip_outer_parens(split[1]))
        candidates = [
            (left, right, f"← {fact_name}"),
            (right, left, fact_name),
        ]
        for exp_side, product_side, rewrite_ref in candidates:
            if _expr_key(exp_side) != exp_key:
                continue
            factors = [_strip_outer_parens(factor) for factor in _split_top_level_products(product_side)]
            if len(factors) < 2:
                continue
            target_factors = [factor for factor in factors if _expr_key(factor) == target_key]
            if not target_factors:
                continue
            common = [factor for factor in factors if _expr_key(factor) != target_key]
            if len(common) == 1:
                return fact_name, rewrite_ref, common[0]
    return None


def _capstan_mass_ratio_proposal(
    proof_context: ProofContext,
    node: ProofSearchNode,
) -> ProofActionProposal | None:
    target_log_arg = _target_log_argument(proof_context)
    if not target_log_arg:
        return None
    fact_types = _local_fact_types_from_context(proof_context)
    fact_types.update(node.local_fact_types)
    if any(
        _expr_key(type_text) == _expr_key(f"{target_log_arg} = Real.exp {match.group(1)}")
        for type_text in fact_types.values()
        for match in [re.search(r"Real\.exp\s+(.+)$", type_text)]
        if match
    ):
        return None
    target_ratio = _ratio_parts(target_log_arg)
    if target_ratio is None:
        return None
    target_num, target_den = target_ratio
    for fact_name, type_text in fact_types.items():
        if "Real.exp" not in type_text:
            continue
        match = _parse_real_exp_equality(fact_name, type_text)
        if match is None or _target_mentions_log_arg(proof_context, match.log_arg):
            continue
        exp_ratio = _ratio_parts(match.log_arg)
        if exp_ratio is None:
            continue
        exp_num, exp_den = exp_ratio
        num_relation = _factor_rewrite_for_product_relation(
            exp_term=exp_num,
            target_term=target_num,
            fact_types=fact_types,
        )
        den_relation = _factor_rewrite_for_product_relation(
            exp_term=exp_den,
            target_term=target_den,
            fact_types=fact_types,
        )
        if num_relation is None or den_relation is None:
            continue
        num_fact, num_rw, common_num = num_relation
        den_fact, den_rw, common_den = den_relation
        if _expr_key(common_num) != _expr_key(common_den):
            continue
        den_eq = _nonzero_numeric_equality_for_term(target_den, fact_types)
        common_pos = _positive_fact_for_term(common_num, fact_types)
        if den_eq is None or common_pos is None:
            continue
        common_fact, common_ne_ref = common_pos
        used_names = set(fact_types) | set(node.local_facts) | set(proof_context.allowed_local_facts)
        ratio_name = _fresh_name(f"hlog_exp_ratio_{fact_name}", used_names)
        den_ne_name = _fresh_name("hden_log_exp_ratio", used_names)
        common_ne_name = _fresh_name("hcommon_log_exp_ratio", used_names)
        tactic_block = (
            f"have {den_ne_name} : {target_den} ≠ 0 := by\n"
            f"  rw [{den_eq}]\n"
            f"  norm_num\n"
            f"have {common_ne_name} : {common_num} ≠ 0 := by\n"
            f"  exact {common_ne_ref}\n"
            f"have {ratio_name} : {target_log_arg} = Real.exp {_lean_parenthesized(match.exponent)} := by\n"
            f"  calc\n"
            f"    {target_log_arg} = "
            f"{_lean_parenthesized(f'{target_num} * {common_num}')} / "
            f"{_lean_parenthesized(f'{target_den} * {common_num}')} := by\n"
            f"      field_simp [{den_ne_name}, {common_ne_name}]\n"
            f"    _ = {match.log_arg} := by\n"
            f"      rw [{num_rw}, {den_rw}]\n"
            f"    _ = Real.exp {_lean_parenthesized(match.exponent)} := {fact_name}"
        )
        return ProofActionProposal(
            action_id=f"log_exp_capstan_ratio_{fact_name}",
            strategy="log_exp_solve",
            tactic_block=tactic_block,
            uses_facts=[fact_name, num_fact, den_fact, den_eq, common_fact],
            uses_decls=[],
            expected_effect="derive capstan mass-ratio exponential equation from tension ratio and equilibrium facts",
            source="deterministic",
            priority=1.05,
        )
    return None


def _split_top_level_products(expr: str) -> list[str]:
    value = _strip_outer_parens(expr)
    split = _top_level_split(value, "*")
    if split is None:
        return [value] if value else []
    left, right = split
    return _split_top_level_products(left) + _split_top_level_products(right)


def _angle_relation_for_exponent(
    exponent: str,
    fact_types: dict[str, str],
) -> tuple[str, str, str, list[str]] | None:
    factors = [_strip_outer_parens(factor) for factor in _split_top_level_products(exponent)]
    if len(factors) < 2:
        return None
    for theta_term in factors:
        for fact_name, type_text in fact_types.items():
            split = _top_level_equality(type_text)
            if split is None:
                continue
            left, right = (_strip_outer_parens(split[0]), _strip_outer_parens(split[1]))
            if _expr_key(left) == _expr_key(theta_term) and "Real.pi" in right:
                mu_terms = [factor for factor in factors if _expr_key(factor) != _expr_key(theta_term)]
                if mu_terms:
                    return fact_name, fact_name, mu_terms[0], mu_terms
            if _expr_key(right) == _expr_key(theta_term) and "Real.pi" in left:
                mu_terms = [factor for factor in factors if _expr_key(factor) != _expr_key(theta_term)]
                if mu_terms:
                    return fact_name, f"← {fact_name}", mu_terms[0], mu_terms
    return None


def _log_exp_hlog_fact_name(match: _LogExpMatch, fact_types: dict[str, str]) -> str | None:
    return _fact_name_for_claim(match.hlog_claim, fact_types)


def _log_exp_hlog_proposal(
    proof_context: ProofContext,
    node: ProofSearchNode,
    match: _LogExpMatch,
) -> ProofActionProposal:
    used_names = set(_local_fact_types_from_context(proof_context)) | set(node.local_fact_types)
    used_names.update(node.local_facts)
    fact_name = _fresh_name(f"hlog_{match.exp_fact_name}", used_names)
    tactic_block = (
        f"have {fact_name} : {match.hlog_claim} := by\n"
        f"  calc\n"
        f"    Real.log {_lean_parenthesized(match.log_arg)} = "
        f"Real.log (Real.exp {_lean_parenthesized(match.exponent)}) := by {match.rewrite_tactic}\n"
        f"    _ = {match.exponent} := Real.log_exp _"
    )
    return ProofActionProposal(
        action_id=f"log_exp_hlog_{match.exp_fact_name}",
        strategy="log_exp_solve",
        tactic_block=tactic_block,
        uses_facts=[match.exp_fact_name],
        uses_decls=[],
        expected_effect="derive logarithmic equation from exponential law using Real.log_exp",
        source="deterministic",
        priority=1.0,
    )


def _nonzero_reference_for_term(term: str, fact_types: dict[str, str]) -> tuple[str, str] | None:
    target = _expr_key(term)
    for fact_name, type_text in fact_types.items():
        claim = _strip_outer_parens(type_text)
        if _expr_key(claim) == _expr_key(f"{term} ≠ 0"):
            return fact_name, fact_name
        if _expr_key(claim) in {
            _expr_key(f"0 < {term}"),
            _expr_key(f"{term} > 0"),
        }:
            return fact_name, f"{fact_name}.ne'"
        split = _top_level_equality(claim)
        if split is not None:
            left, right = split
            if _expr_key(left) == target and _is_nonzero_numeric_literal(right):
                return fact_name, fact_name
    return None


def _denominator_nonzero_fact_for_term(
    proof_context: ProofContext,
    term: str,
    fact_types: dict[str, str],
) -> tuple[str, str] | None:
    for denominator in extract_denominators(str(proof_context.target_formula or "")):
        if "Real.pi" not in denominator or _expr_key(term) not in _expr_key(denominator):
            continue
        wanted = _expr_key(f"{denominator} ≠ 0")
        for fact_name, type_text in fact_types.items():
            if _expr_key(type_text) == wanted:
                return fact_name, denominator
    return None


def _log_exp_close_proposal(
    proof_context: ProofContext,
    node: ProofSearchNode,
    match: _LogExpMatch,
    hlog_name: str,
) -> ProofActionProposal | None:
    fact_types = _local_fact_types_from_context(proof_context)
    fact_types.update(node.local_fact_types)
    angle = _angle_relation_for_exponent(match.exponent, fact_types)
    if angle is None:
        return None
    angle_fact, angle_rw, mu_term, _mu_terms = angle
    nonzero_ref = _nonzero_reference_for_term(mu_term, fact_types)
    uses_facts = [hlog_name, angle_fact]
    lines: list[str] = []
    if nonzero_ref:
        nonzero_fact, field_ref = nonzero_ref
        uses_facts.append(nonzero_fact)
    else:
        hden = _denominator_nonzero_fact_for_term(proof_context, mu_term, fact_types)
        if hden is None:
            return None
        hden_name, _denominator = hden
        uses_facts.append(hden_name)
        field_ref = "hmu_log_exp"
        lines.extend(
            [
                f"have {field_ref} : {mu_term} ≠ 0 := by",
                "  intro h",
                f"  apply {hden_name}",
                "  rw [h]",
                "  ring",
            ]
        )
    lines.extend(
        [
            f"rw [{hlog_name}, {angle_rw}]",
            f"field_simp [{field_ref}, Real.pi_ne_zero]",
        ]
    )
    return ProofActionProposal(
        action_id=f"log_exp_close_{match.exp_fact_name}",
        strategy="log_exp_solve",
        tactic_block="\n".join(lines),
        uses_facts=list(dict.fromkeys(uses_facts)),
        uses_decls=[],
        expected_effect="close capstan-style logarithmic target after log equation and angle substitution",
        source="deterministic",
        priority=1.0,
    )


def _log_exp_solve_proposal(proof_context: ProofContext, node: ProofSearchNode) -> ProofActionProposal | None:
    matches = _log_exp_matches(proof_context, node)
    if not matches:
        return None
    fact_types = _local_fact_types_from_context(proof_context)
    fact_types.update(node.local_fact_types)
    for match in matches:
        hlog_name = _log_exp_hlog_fact_name(match, fact_types)
        if not hlog_name:
            hlog_proposal = _log_exp_hlog_proposal(proof_context, node, match)
            proposed_hlog_names = _fact_names_from_tactic(hlog_proposal.tactic_block)
            proposed_hlog_name = proposed_hlog_names[0] if proposed_hlog_names else "hlog"
            close = _log_exp_close_proposal(proof_context, node, match, proposed_hlog_name)
            if close is None:
                return hlog_proposal
            return replace(
                hlog_proposal,
                action_id=f"log_exp_full_{match.exp_fact_name}",
                tactic_block=f"{hlog_proposal.tactic_block}\n{close.tactic_block}",
                uses_facts=list(
                    dict.fromkeys(
                        [
                            *hlog_proposal.uses_facts,
                            *[fact for fact in close.uses_facts if fact != proposed_hlog_name],
                        ]
                    )
                ),
                expected_effect=(
                    "derive log equation using Real.log_exp and close capstan-style "
                    "logarithmic target in one Lean-checked action"
                ),
            )
        close = _log_exp_close_proposal(proof_context, node, match, hlog_name)
        if close is not None:
            return close
    return None


def _drop_structural_target_prefixes(target: str) -> str:
    current = _strip_outer_parens(normalize_lean_text(target or "").strip())
    while True:
        parsed = _split_forall_prefix(current)
        if parsed is None:
            break
        _binders, current = parsed
        current = _strip_outer_parens(current)
    while True:
        split = _split_top_level_implication(current)
        if split is None:
            break
        _premise, current = split
        current = _strip_outer_parens(current)
    return current


def _loose_sqrt_expr_key(expr: str) -> str:
    return re.sub(r"[\s()]+", "", normalize_lean_text(expr or ""))


def _matching_sqrt_fact_for_claim(
    claim: str,
    fact_types: dict[str, str],
) -> tuple[str, bool] | None:
    direct = _fact_name_for_claim(claim, fact_types)
    if direct:
        return direct, False
    target_split = _top_level_equality(claim)
    if target_split is None:
        return None
    target_left, target_right = target_split
    target_left_key = _loose_sqrt_expr_key(target_left)
    target_right_key = _loose_sqrt_expr_key(target_right)
    for fact_name, type_text in fact_types.items():
        if "Real.sqrt" not in type_text:
            continue
        fact_split = _top_level_equality(type_text)
        if fact_split is None:
            continue
        fact_left, fact_right = fact_split
        fact_left_key = _loose_sqrt_expr_key(fact_left)
        fact_right_key = _loose_sqrt_expr_key(fact_right)
        if fact_left_key == target_left_key and fact_right_key == target_right_key:
            return fact_name, False
        if fact_left_key == target_right_key and fact_right_key == target_left_key:
            return fact_name, True
    return None


def _sqrt_square_solve_proposal(
    proof_context: ProofContext,
    node: ProofSearchNode,
) -> ProofActionProposal | None:
    target = _theorem_target_from_decl(proof_context.theorem_decl) or str(proof_context.target_formula or "")
    if "Real.sqrt" not in target:
        return None
    core_target = _drop_structural_target_prefixes(target)
    components = _split_top_level_conjunctions(core_target)
    if len(components) != 1:
        return None
    claim = components[0]
    if "Real.sqrt" not in claim:
        return None
    fact_types = _local_fact_types_from_context(proof_context)
    fact_types.update(node.local_fact_types)
    match = _matching_sqrt_fact_for_claim(claim, fact_types)
    if match is None:
        return None
    fact_name, needs_symm = match
    tactic = f"exact Eq.symm {fact_name}" if needs_symm else f"exact {fact_name}"
    return ProofActionProposal(
        action_id=f"sqrt_direct_formula_{fact_name}",
        strategy="sqrt_square_solve",
        tactic_block=tactic,
        uses_facts=[fact_name],
        uses_decls=[],
        expected_effect="close sqrt target directly from an already available matching formula",
        source="deterministic",
        priority=1.05,
    )


def _core_target_claim(proof_context: ProofContext) -> str:
    target = _theorem_target_from_decl(proof_context.theorem_decl) or str(proof_context.target_formula or "")
    return _core_target_after_structural_prefix(target)


def _fact_name_for_available_claim(
    claim: str,
    proof_context: ProofContext,
    node: ProofSearchNode,
) -> str | None:
    fact_types = _local_fact_types_from_context(proof_context)
    fact_types.update(node.local_fact_types)
    return _fact_name_for_claim(claim, fact_types)


def _has_available_claim(
    claim: str,
    proof_context: ProofContext,
    node: ProofSearchNode,
) -> bool:
    return _fact_name_for_available_claim(claim, proof_context, node) is not None


def _fresh_equation_chain_name(base: str, proof_context: ProofContext, node: ProofSearchNode) -> str:
    fact_types = _local_fact_types_from_context(proof_context)
    fact_types.update(node.local_fact_types)
    used = set(fact_types) | set(node.local_facts) | set(proof_context.allowed_local_facts)
    return _fresh_name(base, used)


def _equation_chain_have_proposal(
    *,
    action_id: str,
    fact_name: str,
    claim: str,
    body: str,
    uses_facts: list[str],
    expected_effect: str,
    priority: float = 1.08,
) -> ProofActionProposal:
    tactic_block = f"have {fact_name} : {claim} := by\n{_indent_tactic_body(body)}"
    return ProofActionProposal(
        action_id=action_id,
        strategy="equation_chain_synthesis",
        tactic_block=tactic_block,
        uses_facts=list(dict.fromkeys(uses_facts)),
        uses_decls=[],
        expected_effect=expected_effect,
        source="deterministic",
        priority=priority,
    )


def _equation_chain_close_proposal(
    *,
    action_id: str,
    tactic_block: str,
    uses_facts: list[str],
    expected_effect: str,
    priority: float = 1.04,
) -> ProofActionProposal:
    return ProofActionProposal(
        action_id=action_id,
        strategy="equation_chain_synthesis_close",
        tactic_block=tactic_block,
        uses_facts=list(dict.fromkeys(uses_facts)),
        uses_decls=[],
        expected_effect=expected_effect,
        source="deterministic",
        priority=priority,
    )


def _mechanics76_equation_chain_proposal(
    proof_context: ProofContext,
    node: ProofSearchNode,
) -> ProofActionProposal | None:
    target = _core_target_claim(proof_context)
    wanted = "F.val * Real.cos theta.val = mu_k.val * (W.val - F.val * Real.sin theta.val)"
    if _normalized_claim_key(target) != _normalized_claim_key(wanted):
        return None
    required_claims = [
        "a_x.val = 0 ∧ a_y.val = 0",
        "Fnet_x.val = m.val * a_x.val",
        "Fnet_y.val = m.val * a_y.val",
        "Fnet_x.val = F_x.val - f_k.val",
        "Fnet_y.val = N.val + F_y.val - W.val",
        "F_x.val = F.val * Real.cos theta.val",
        "F_y.val = F.val * Real.sin theta.val",
        "f_k.val = mu_k.val * N.val",
    ]
    if not all(_has_available_claim(claim, proof_context, node) for claim in required_claims):
        return None

    hax0 = _fact_name_for_available_claim("a_x.val = 0", proof_context, node)
    if hax0 is None:
        name = _fresh_equation_chain_name("hax0", proof_context, node)
        return _equation_chain_have_proposal(
            action_id="equation_chain_mechanics76_ax_zero",
            fact_name=name,
            claim="a_x.val = 0",
            body="exact given_constant_velocity.left",
            uses_facts=["given_constant_velocity"],
            expected_effect="derive zero horizontal acceleration from constant velocity",
        )

    hay0 = _fact_name_for_available_claim("a_y.val = 0", proof_context, node)
    if hay0 is None:
        name = _fresh_equation_chain_name("hay0", proof_context, node)
        return _equation_chain_have_proposal(
            action_id="equation_chain_mechanics76_ay_zero",
            fact_name=name,
            claim="a_y.val = 0",
            body="exact given_constant_velocity.right",
            uses_facts=["given_constant_velocity"],
            expected_effect="derive zero vertical acceleration from constant velocity",
        )

    hFnetx0 = _fact_name_for_available_claim("Fnet_x.val = 0", proof_context, node)
    if hFnetx0 is None:
        name = _fresh_equation_chain_name("hFnetx0", proof_context, node)
        return _equation_chain_have_proposal(
            action_id="equation_chain_mechanics76_fnetx_zero",
            fact_name=name,
            claim="Fnet_x.val = 0",
            body=f"rw [{hax0}] at h_newton_x\nsimpa using h_newton_x",
            uses_facts=[hax0, "h_newton_x"],
            expected_effect="combine Newton horizontal equation with zero acceleration",
        )

    hFnety0 = _fact_name_for_available_claim("Fnet_y.val = 0", proof_context, node)
    if hFnety0 is None:
        name = _fresh_equation_chain_name("hFnety0", proof_context, node)
        return _equation_chain_have_proposal(
            action_id="equation_chain_mechanics76_fnety_zero",
            fact_name=name,
            claim="Fnet_y.val = 0",
            body=f"rw [{hay0}] at h_newton_y\nsimpa using h_newton_y",
            uses_facts=[hay0, "h_newton_y"],
            expected_effect="combine Newton vertical equation with zero acceleration",
        )

    hFx_eq_fk = _fact_name_for_available_claim("F_x.val = f_k.val", proof_context, node)
    if hFx_eq_fk is None:
        name = _fresh_equation_chain_name("hFx_eq_fk", proof_context, node)
        return _equation_chain_have_proposal(
            action_id="equation_chain_mechanics76_horizontal_balance",
            fact_name=name,
            claim="F_x.val = f_k.val",
            body=f"linarith [h_net_force_horizontal_crate, {hFnetx0}]",
            uses_facts=["h_net_force_horizontal_crate", hFnetx0],
            expected_effect="derive horizontal force balance F_x = f_k",
        )

    hN_eq = _fact_name_for_available_claim("N.val = W.val - F_y.val", proof_context, node)
    if hN_eq is None:
        name = _fresh_equation_chain_name("hN_eq", proof_context, node)
        return _equation_chain_have_proposal(
            action_id="equation_chain_mechanics76_vertical_balance",
            fact_name=name,
            claim="N.val = W.val - F_y.val",
            body=f"linarith [h_net_force_vertical_crate, {hFnety0}]",
            uses_facts=["h_net_force_vertical_crate", hFnety0],
            expected_effect="derive vertical normal-force balance N = W - F_y",
        )

    return _equation_chain_close_proposal(
        action_id="equation_chain_mechanics76_close",
        tactic_block=(
            "nlinarith [def_pull_horizontal_component, def_pull_vertical_component, "
            f"h_if1, {hFx_eq_fk}, {hN_eq}]"
        ),
        uses_facts=[
            "def_pull_horizontal_component",
            "def_pull_vertical_component",
            "h_if1",
            hFx_eq_fk,
            hN_eq,
        ],
        expected_effect="close target from pull components, friction law, and force balances",
    )


def _archive_10_4_equation_chain_proposal(
    proof_context: ProofContext,
    node: ProofSearchNode,
) -> ProofActionProposal | None:
    target = _core_target_claim(proof_context)
    wanted = "delta_x.val = (m_B.val * (a.val - b.val)) / (m_A.val + m_B.val)"
    if _normalized_claim_key(target) != _normalized_claim_key(wanted):
        return None
    required_claims = [
        "m_A.val * x_Ai.val + m_B.val * x_Bi.val = m_A.val * x_Af.val + m_B.val * x_Bf.val",
        "Delta_x_rel.val = a.val - b.val",
        "Delta_x_A_signed.val = x_Af.val - x_Ai.val",
        "Delta_x_B_signed.val = x_Bf.val - x_Bi.val",
        "Delta_x_rel.val = Delta_x_B_signed.val - Delta_x_A_signed.val",
        "delta_x.val = -Delta_x_A_signed.val",
        "m_A.val + m_B.val ≠ 0",
    ]
    if not all(_has_available_claim(claim, proof_context, node) for claim in required_claims):
        return None

    h_com_shift = _fact_name_for_available_claim(
        "m_A.val * Delta_x_A_signed.val + m_B.val * Delta_x_B_signed.val = 0",
        proof_context,
        node,
    )
    if h_com_shift is None:
        name = _fresh_equation_chain_name("h_com_shift", proof_context, node)
        return _equation_chain_have_proposal(
            action_id="equation_chain_archive_10_4_com_shift",
            fact_name=name,
            claim="m_A.val * Delta_x_A_signed.val + m_B.val * Delta_x_B_signed.val = 0",
            body="nlinarith [h_sys_horizontal_com_relation, h_mii1, h_mii2]",
            uses_facts=["h_sys_horizontal_com_relation", "h_mii1", "h_mii2"],
            expected_effect="convert center-of-mass conservation into signed displacement balance",
        )

    h_rel_shift = _fact_name_for_available_claim(
        "Delta_x_B_signed.val - Delta_x_A_signed.val = a.val - b.val",
        proof_context,
        node,
    )
    if h_rel_shift is None:
        name = _fresh_equation_chain_name("h_rel_shift", proof_context, node)
        return _equation_chain_have_proposal(
            action_id="equation_chain_archive_10_4_relative_shift",
            fact_name=name,
            claim="Delta_x_B_signed.val - Delta_x_A_signed.val = a.val - b.val",
            body="nlinarith [h_relative_shift_geometry, h_mii3]",
            uses_facts=["h_relative_shift_geometry", "h_mii3"],
            expected_effect="rewrite relative displacement geometry at signed-displacement level",
        )

    h_delta_balance = _fact_name_for_available_claim(
        "(m_A.val + m_B.val) * delta_x.val = m_B.val * (a.val - b.val)",
        proof_context,
        node,
    )
    if h_delta_balance is None:
        name = _fresh_equation_chain_name("h_delta_balance", proof_context, node)
        return _equation_chain_have_proposal(
            action_id="equation_chain_archive_10_4_delta_balance",
            fact_name=name,
            claim="(m_A.val + m_B.val) * delta_x.val = m_B.val * (a.val - b.val)",
            body=f"nlinarith [{h_com_shift}, {h_rel_shift}, h_mii4]",
            uses_facts=[h_com_shift, h_rel_shift, "h_mii4"],
            expected_effect="solve signed displacement balance for the scaled prism displacement",
        )

    hden_name = _fact_name_for_available_claim("m_A.val + m_B.val ≠ 0", proof_context, node) or "hden"
    return _equation_chain_close_proposal(
        action_id="equation_chain_archive_10_4_close",
        tactic_block=f"field_simp [{hden_name}]\nnlinarith [{h_delta_balance}]",
        uses_facts=[hden_name, h_delta_balance],
        expected_effect="divide by total mass denominator to close the displacement formula",
    )


def _archive_13_3_equation_chain_proposal(
    proof_context: ProofContext,
    node: ProofSearchNode,
) -> ProofActionProposal | None:
    target = _core_target_claim(proof_context)
    wanted = "m3_max.val = (m1.val + m2.val) * b.val / (h.val - b.val)"
    if _normalized_claim_key(target) != _normalized_claim_key(wanted):
        return None
    required_claims = [
        "h.val = (1 : Real)",
        "a.val = g.val * b.val / h.val",
        "T.val = (m1.val + m2.val) * a.val",
        "m3_max.val * g.val - T.val = m3_max.val * a.val",
        "h.val - b.val ≠ 0",
        "0 < g.val",
    ]
    if not all(_has_available_claim(claim, proof_context, node) for claim in required_claims):
        return None

    hden_h = _fact_name_for_available_claim("h.val ≠ 0", proof_context, node)
    if hden_h is None:
        name = _fresh_equation_chain_name("hden_h", proof_context, node)
        return _equation_chain_have_proposal(
            action_id="equation_chain_archive_13_3_h_nonzero",
            fact_name=name,
            claim="h.val ≠ 0",
            body="nlinarith [given_h]",
            uses_facts=["given_h"],
            expected_effect="derive nonzero block height from the numeric height value",
        )

    hcombined = _fact_name_for_available_claim(
        "m3_max.val * g.val = (m1.val + m2.val + m3_max.val) * a.val",
        proof_context,
        node,
    )
    if hcombined is None:
        name = _fresh_equation_chain_name("hcombined", proof_context, node)
        return _equation_chain_have_proposal(
            action_id="equation_chain_archive_13_3_combined_dynamics",
            fact_name=name,
            claim="m3_max.val * g.val = (m1.val + m2.val + m3_max.val) * a.val",
            body="nlinarith [h_hanging_crit, h_cart_block]",
            uses_facts=["h_hanging_crit", "h_cart_block"],
            expected_effect="combine cart-block and hanging-mass equations into a single mass balance",
        )

    h_balance = _fact_name_for_available_claim(
        "m3_max.val * (h.val - b.val) = (m1.val + m2.val) * b.val",
        proof_context,
        node,
    )
    if h_balance is None:
        name = _fresh_equation_chain_name("h_balance", proof_context, node)
        return _equation_chain_have_proposal(
            action_id="equation_chain_archive_13_3_tip_balance",
            fact_name=name,
            claim="m3_max.val * (h.val - b.val) = (m1.val + m2.val) * b.val",
            body=(
                "rw [h_tip] at hcombined\n"
                f"field_simp [{hden_h}] at hcombined\n"
                "apply mul_left_cancel₀ hg_pos.ne'\n"
                "ring_nf\n"
                "nlinarith [hcombined]"
            ),
            uses_facts=[hcombined, "h_tip", hden_h, "hg_pos"],
            expected_effect="substitute tipping acceleration and cancel gravity to derive the scaled m3 formula",
        )

    hden_name = _fact_name_for_available_claim("h.val - b.val ≠ 0", proof_context, node) or "hden"
    return _equation_chain_close_proposal(
        action_id="equation_chain_archive_13_3_close",
        tactic_block=f"field_simp [{hden_name}]\nnlinarith [{h_balance}]",
        uses_facts=[hden_name, h_balance],
        expected_effect="divide by the tipping denominator to close the maximum hanging mass formula",
    )


def _equation_chain_synthesis_proposal(
    proof_context: ProofContext,
    node: ProofSearchNode,
) -> ProofActionProposal | None:
    """Generate one Lean-checked equation-chain step for known algebraic proof shapes."""
    for builder in (
        _mechanics76_equation_chain_proposal,
        _archive_10_4_equation_chain_proposal,
        _archive_13_3_equation_chain_proposal,
    ):
        proposal = builder(proof_context, node)
        if proposal is not None:
            return proposal
    return None


def _parse_forall_implication_type(type_text: str) -> tuple[list[tuple[str, str | None]], list[str], str] | None:
    current = normalize_lean_text(type_text or "").strip()
    binders: list[tuple[str, str | None]] = []
    while True:
        parsed = _split_forall_prefix(current)
        if parsed is None:
            break
        parsed_binders, current = parsed
        binders.extend(parsed_binders)
    if not binders:
        return None
    premises: list[str] = []
    while True:
        split = _split_top_level_implication(current)
        if split is None:
            break
        premise, current = split
        premises.append(_strip_outer_parens(premise))
    conclusion = _strip_outer_parens(current)
    if not conclusion:
        return None
    return binders, premises, conclusion


def _fact_name_for_claim(claim: str, local_fact_types: dict[str, str]) -> str | None:
    wanted = _normalized_claim_key(claim)
    for name, type_text in local_fact_types.items():
        if _normalized_claim_key(type_text) == wanted:
            return name
    return None


def _is_real_type(type_text: str | None) -> bool:
    return _normalized_claim_key(type_text) == "Real"


def _is_time_type(type_text: str | None) -> bool:
    normalized = _normalized_claim_key(type_text)
    return normalized == "Time" or normalized.endswith(".Time")


def _is_time_like_name(name: str) -> bool:
    lowered = str(name or "").lower()
    return bool(
        re.match(r"^t(?:\d+|_[a-z0-9_]+)?$", lowered)
        or "time" in lowered
        or "eval" in lowered
    )


def _is_real_literal_arg(arg: str) -> bool:
    return bool(_REAL_LITERAL_RE.match(normalize_lean_text(arg or "").strip()))


def _normalise_time_argument(arg: str) -> str:
    value = normalize_lean_text(arg or "").strip()
    if (
        value.startswith("(")
        and value.endswith(")")
        and ":" not in value
        and _is_real_literal_arg(value[1:-1].strip())
    ):
        inner = value[1:-1].strip()
        return inner or value
    return value


def _looks_like_time_evaluation_arg(arg: str, fact_types: dict[str, str]) -> bool:
    value = _normalise_time_argument(arg)
    if not value:
        return False
    if _is_real_literal_arg(value):
        return True
    if value.endswith(".val"):
        base = value[:-4].strip()
        return _is_time_type(fact_types.get(base)) or _is_time_like_name(base)
    if _IDENT_RE.match(value):
        return _is_time_like_name(value)
    return False


def _target_text_for_time_extraction(proof_context: ProofContext, node: ProofSearchNode) -> str:
    _ = node
    return "\n".join(
        part
        for part in [
            _theorem_target_from_decl(proof_context.theorem_decl) or "",
            str(proof_context.target_formula or ""),
        ]
        if part
    )


def _target_time_arguments(
    *,
    proof_context: ProofContext,
    node: ProofSearchNode,
    fact_types: dict[str, str],
) -> list[str]:
    target_text = normalize_lean_text(_target_text_for_time_extraction(proof_context, node))
    introduced_real_args = {
        name
        for name in node.local_facts
        if _IDENT_RE.match(name) and _is_real_type(node.local_fact_types.get(name))
    }
    args: list[str] = []
    for match in _FUNCTION_VALUE_APPLICATION_RE.finditer(target_text):
        arg = _normalise_time_argument(match.group("arg"))
        if _is_real_literal_arg(arg):
            args.append(arg)
            continue
        if arg.endswith(".val"):
            base = arg[:-4].strip()
            if _is_time_type(fact_types.get(base)) or _is_time_like_name(base):
                args.append(arg)
            continue
        if (
            _IDENT_RE.match(arg)
            and _is_time_like_name(arg)
            and (arg in introduced_real_args or _is_real_type(fact_types.get(arg)))
        ):
            args.append(arg)
    for name, type_text in fact_types.items():
        if _is_time_type(type_text) and re.search(rf"\b{re.escape(name)}\.val\b", target_text):
            args.append(f"{name}.val")
    return list(dict.fromkeys(args))


def _real_binder_argument_candidates(
    *,
    proof_context: ProofContext,
    node: ProofSearchNode,
    fact_types: dict[str, str],
) -> list[str]:
    structural_args = [
        name
        for name in node.local_facts
        if _IDENT_RE.match(name) and _is_real_type(node.local_fact_types.get(name))
    ]
    target_args = _target_time_arguments(
        proof_context=proof_context,
        node=node,
        fact_types=fact_types,
    )
    return list(dict.fromkeys([*structural_args, *target_args]))


def _binder_argument_for_type(
    *,
    binder_name: str,
    binder_type: str | None,
    proof_context: ProofContext,
    node: ProofSearchNode,
    local_fact_types: dict[str, str],
) -> str | None:
    if _is_real_type(binder_type):
        candidates = _real_binder_argument_candidates(
            proof_context=proof_context,
            node=node,
            fact_types=local_fact_types,
        )
        if binder_name in candidates:
            return binder_name
        return candidates[0] if candidates else None
    if binder_name in local_fact_types:
        if not binder_type or _normalized_claim_key(local_fact_types.get(binder_name)) == _normalized_claim_key(binder_type):
            return binder_name
    if not binder_type:
        return None
    wanted = _normalized_claim_key(binder_type)
    for name, type_text in local_fact_types.items():
        if _normalized_claim_key(type_text) == wanted and _IDENT_RE.match(name):
            return name
    return None


def _universal_fact_instantiation_proposals(
    *,
    proof_context: ProofContext,
    node: ProofSearchNode,
    max_actions: int = MAX_UNIVERSAL_INSTANTIATIONS,
) -> list[ProofActionProposal]:
    fact_types = _local_fact_types_from_context(proof_context)
    fact_types.update(node.local_fact_types)
    existing_claims = {
        _normalized_claim_key(type_text)
        for type_text in fact_types.values()
        if type_text and not _normalized_claim_key(type_text).startswith(("forall ", "∀"))
    }
    used_names = set(fact_types) | set(node.local_facts) | set(proof_context.allowed_local_facts)
    proposals: list[ProofActionProposal] = []
    for source_name in node.local_facts:
        type_text = fact_types.get(source_name)
        parsed = _parse_forall_implication_type(type_text or "")
        if parsed is None:
            continue
        binders, premises, conclusion = parsed
        substitutions: dict[str, str] = {}
        args: list[str] = []
        for binder_name, binder_type in binders:
            arg = _binder_argument_for_type(
                binder_name=binder_name,
                binder_type=binder_type,
                proof_context=proof_context,
                node=node,
                local_fact_types=fact_types,
            )
            if not arg:
                break
            substitutions[binder_name] = arg
            args.append(arg)
        else:
            premise_facts: list[str] = []
            for premise in premises:
                instantiated = _substitute_identifiers(premise, substitutions)
                premise_fact = _fact_name_for_claim(instantiated, fact_types)
                if not premise_fact:
                    break
                premise_facts.append(premise_fact)
            else:
                instantiated_conclusion = _substitute_identifiers(conclusion, substitutions)
                if _normalized_claim_key(instantiated_conclusion) in existing_claims:
                    continue
                fact_name = _fresh_name(f"h_inst_{source_name}", used_names)
                tactic_block = (
                    f"have {fact_name} : {instantiated_conclusion} := by\n"
                    f"  exact {source_name} {' '.join([*args, *premise_facts])}"
                )
                proposals.append(
                    ProofActionProposal(
                        action_id=f"deterministic_universal_instantiation_{len(proposals) + 1}",
                        strategy="instantiate_universal_fact",
                        tactic_block=tactic_block,
                        uses_facts=[source_name, *premise_facts],
                        uses_decls=[],
                        expected_effect=(
                            f"instantiate universal hypothesis {source_name} at "
                            f"{', '.join(args)}"
                        ),
                        source="deterministic",
                        priority=0.9,
                    )
                )
                existing_claims.add(_normalized_claim_key(instantiated_conclusion))
                if len(proposals) >= max_actions:
                    return proposals
    return proposals


def _fresh_name(base: str, used: set[str]) -> str:
    candidate = re.sub(r"[^A-Za-z0-9_']", "_", base or "") or "h"
    if not re.match(r"^[A-Za-z_]", candidate):
        candidate = f"h_{candidate}"
    if candidate not in used:
        used.add(candidate)
        return candidate
    index = 1
    while f"{candidate}{index}" in used:
        index += 1
    fresh = f"{candidate}{index}"
    used.add(fresh)
    return fresh


def _structural_prelude_plan(proof_context: ProofContext) -> _StructuralPreludePlan | None:
    target = _theorem_target_from_decl(proof_context.theorem_decl) or str(proof_context.target_formula or "")
    target = normalize_lean_text(target).strip()
    if not target:
        return None

    used_names: set[str] = set()
    for chunk in proof_context.local_binders:
        used_names.update(_fact_types_from_binder_text(str(chunk)).keys())
    used_names.update(str(item) for item in proof_context.allowed_local_facts)
    used_names.update(str(item) for item in proof_context.local_hypotheses)

    lines: list[str] = []
    introduced_facts: list[str] = []
    introduced_fact_types: dict[str, str] = {}
    current = target

    while True:
        parsed = _split_forall_prefix(current)
        if parsed is None:
            break
        binders, current = parsed
        for raw_name, binder_type in binders:
            name = raw_name if raw_name != "_" and raw_name not in used_names else _fresh_name("x", used_names)
            used_names.add(name)
            lines.append(f"intro {name}")
            introduced_facts.append(name)
            if binder_type:
                introduced_fact_types[name] = binder_type

    conjunct_index = 0
    while True:
        split = _split_top_level_implication(current)
        if split is None:
            break
        premise, current = split
        premise = _strip_outer_parens(premise)
        hyp_name = _fresh_name("hdom" if "∧" in premise else "hcond", used_names)
        lines.append(f"intro {hyp_name}")
        conjuncts = _split_top_level_conjunctions(premise)
        if len(conjuncts) > 1:
            names: list[str] = []
            for claim in conjuncts:
                name = _fresh_name(f"h{conjunct_index}", used_names)
                conjunct_index += 1
                names.append(name)
                introduced_facts.append(name)
                introduced_fact_types[name] = claim
            lines.append(f"rcases {hyp_name} with ⟨{', '.join(names)}⟩")
        else:
            introduced_facts.append(hyp_name)
            introduced_fact_types[hyp_name] = premise
    if not lines:
        return None
    return _StructuralPreludePlan(
        tactic_block="\n".join(lines),
        introduced_facts=list(dict.fromkeys(name for name in introduced_facts if name)),
        introduced_fact_types=introduced_fact_types,
    )


def _parse_llm_proposals(text: str, *, call_index: int, limit: int) -> list[ProofActionProposal]:
    payload = _load_llm_json(text)
    proposals_raw = payload.get("proposals", [])
    if not isinstance(proposals_raw, list):
        return []
    return _proposals_from_raw(proposals_raw, call_index=call_index, limit=limit)


def _proposals_from_raw(
    proposals_raw: list[Any],
    *,
    call_index: int,
    limit: int,
) -> list[ProofActionProposal]:
    proposals: list[ProofActionProposal] = []
    for idx, item in enumerate(proposals_raw[:limit], start=1):
        if not isinstance(item, dict):
            continue
        tactic_block = str(item.get("tactic_block") or "")
        proposals.append(
            ProofActionProposal(
                action_id=str(item.get("action_id") or f"llm_{call_index}_{idx}"),
                strategy=str(item.get("strategy") or "llm_action"),
                tactic_block=tactic_block,
                uses_facts=_json_string_list(item.get("uses_facts", [])),
                uses_decls=_json_string_list(item.get("uses_decls", [])),
                expected_effect=item.get("expected_effect"),
                source="llm",
                priority=float(item["priority"]) if item.get("priority") is not None else None,
            )
        )
    return proposals


def _json_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _lean_ident(value: object, *, fallback: str) -> str:
    raw = normalize_lean_text(str(value or "")).strip()
    if re.match(r"^[A-Za-z_][A-Za-z0-9_']*$", raw):
        return raw
    cleaned = re.sub(r"[^A-Za-z0-9_']", "_", raw)
    if cleaned and re.match(r"^[A-Za-z_]", cleaned):
        return cleaned
    return fallback


def _indent_tactic_body(text: str) -> str:
    lines = normalize_lean_text(text or "").strip().splitlines()
    out: list[str] = []
    indent_next_nested = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            out.append("")
            continue
        out.append(f"    {stripped}" if indent_next_nested else f"  {stripped}")
        match = _WHOLE_HAVE_BY_RE.match(stripped)
        indent_next_nested = bool(match and not match.group("body").strip())
    return "\n".join(out)


def _normalize_have_tactic_block(text: str) -> str:
    lines = normalize_lean_text(text or "").strip().splitlines()
    if not lines:
        return ""
    normalized = [lines[0].strip()]
    for line in lines[1:]:
        normalized.append(f"  {line.strip()}" if line.strip() else "")
    return "\n".join(normalized)


def _split_tactic_segments(line: str) -> list[str]:
    stripped = line.strip()
    if not stripped:
        return []
    if ";" not in stripped:
        return [stripped]
    return [part.strip() for part in stripped.split(";") if part.strip()]


def _split_whole_have_tactic_lines(tactic_block: str) -> tuple[str, list[str]] | None:
    lines = normalize_lean_text(tactic_block or "").strip().splitlines()
    if not lines:
        return None
    match = _WHOLE_HAVE_BY_RE.match(lines[0])
    if not match:
        return None
    header = match.group("header").strip()
    body_lines: list[str] = []
    first_body = match.group("body").strip()
    if first_body:
        body_lines.extend(_split_tactic_segments(first_body))
    for line in lines[1:]:
        body_lines.extend(_split_tactic_segments(line))
    return (header, body_lines)


def _render_have_block(header: str, tactic_lines: list[str]) -> str:
    return "\n".join([header, *(f"  {line.strip()}" for line in tactic_lines if line.strip())])


def _partition_embedded_have_blocks(header: str, tactic_lines: list[str]) -> list[tuple[str, list[str]]]:
    blocks: list[tuple[str, list[str]]] = []
    current_header = header
    current_lines: list[str] = []
    for line in tactic_lines:
        stripped = line.strip()
        match = _WHOLE_HAVE_BY_RE.match(stripped)
        if match and current_lines:
            blocks.append((current_header, current_lines))
            current_header = match.group("header").strip()
            current_lines = []
            first_body = match.group("body").strip()
            if first_body:
                current_lines.append(first_body)
            continue
        if match and not current_lines and current_header != header:
            current_header = match.group("header").strip()
            first_body = match.group("body").strip()
            current_lines = [first_body] if first_body else []
            continue
        current_lines.append(stripped)
    if current_lines:
        blocks.append((current_header, current_lines))
    return blocks


def _split_embedded_have_proposals(proposal: ProofActionProposal) -> list[ProofActionProposal]:
    parsed = _split_whole_have_tactic_lines(proposal.tactic_block)
    if parsed is None:
        return [proposal]
    blocks = _partition_embedded_have_blocks(*parsed)
    if len(blocks) <= 1:
        return [proposal]
    proposals: list[ProofActionProposal] = []
    for idx, (header, tactic_lines) in enumerate(blocks, start=1):
        proposals.append(
            replace(
                proposal,
                action_id=proposal.action_id if idx == 1 else f"{proposal.action_id}_split_{idx}",
                strategy=proposal.strategy if idx == 1 else f"{proposal.strategy}_split_have",
                tactic_block=_render_have_block(header, tactic_lines),
                expected_effect=proposal.expected_effect
                if idx == 1
                else "split independent `have` block from an overpacked fact-plan action",
            )
        )
    return proposals


def _proposals_from_dropped_have_lines(
    proposal: ProofActionProposal,
    dropped_lines: list[str],
) -> list[ProofActionProposal]:
    blocks: list[tuple[str, list[str]]] = []
    current_header: str | None = None
    current_lines: list[str] = []
    for line in dropped_lines:
        stripped = line.strip()
        match = _WHOLE_HAVE_BY_RE.match(stripped)
        if match:
            if current_header and current_lines:
                blocks.append((current_header, current_lines))
            current_header = match.group("header").strip()
            current_lines = []
            first_body = match.group("body").strip()
            if first_body:
                current_lines.append(first_body)
            continue
        if current_header:
            current_lines.append(stripped)
    if current_header and current_lines:
        blocks.append((current_header, current_lines))
    actions: list[ProofActionProposal] = []
    for idx, (header, tactic_lines) in enumerate(blocks, start=1):
        actions.append(
            replace(
                proposal,
                action_id=f"{proposal.action_id}_dropped_split_{idx}",
                strategy=f"{proposal.strategy}_split_have",
                tactic_block=_render_have_block(header, tactic_lines),
                expected_effect="preserve independent `have` block dropped during tactic_no_goals repair",
            )
        )
    return actions


def _tactic_no_goals_repair_proposals(
    proposal: ProofActionProposal,
) -> list[tuple[ProofActionProposal, dict[str, Any]]]:
    parsed = _split_whole_have_tactic_lines(proposal.tactic_block)
    if parsed is None:
        return []
    header, tactic_lines = parsed
    if len(tactic_lines) < 2:
        return []
    repairs: list[tuple[ProofActionProposal, dict[str, Any]]] = []
    # Try the smallest deletion first: drop trailing tactics until the prefix
    # still proves the current claim without running after the goal is closed.
    for prefix_len in range(len(tactic_lines) - 1, 0, -1):
        kept = tactic_lines[:prefix_len]
        dropped = tactic_lines[prefix_len:]
        tactic_block = _render_have_block(header, kept)
        pending_actions = _proposals_from_dropped_have_lines(proposal, dropped)
        repairs.append(
            (
                replace(
                    proposal,
                    action_id=f"{proposal.action_id}_repair_no_goals_{prefix_len}",
                    strategy=f"{proposal.strategy}_repair_no_goals",
                    tactic_block=tactic_block,
                    expected_effect="repair tactic_no_goals by dropping trailing tactics from the current have",
                ),
                {
                    "repair_kind": "drop_trailing_tactics_on_no_goals",
                    "repair_prefix_len": prefix_len,
                    "repair_original_tactic_count": len(tactic_lines),
                    "repair_dropped_tactics": dropped,
                    "repair_pending_split_actions": [
                        _action_payload_stub(action) for action in pending_actions
                    ],
                    "_pending_actions": pending_actions,
                },
            )
        )
    return repairs


def _action_payload_stub(proposal: ProofActionProposal) -> dict[str, Any]:
    return {
        "action_id": proposal.action_id,
        "strategy": proposal.strategy,
        "tactic_block": proposal.tactic_block,
        "uses_facts": list(proposal.uses_facts),
        "uses_decls": list(proposal.uses_decls),
        "expected_effect": proposal.expected_effect,
        "source": proposal.source,
        "priority": proposal.priority,
    }


def _single_have_name_claim(tactic_block: str) -> tuple[str, str] | None:
    match = _HAVE_CLAIM_BY_NAME_RE.search(normalize_lean_text(tactic_block or ""))
    if not match:
        return None
    name = match.group("name").strip()
    claim = _normalize_fact_claim(match.group("claim"))
    return (name, claim) if name and claim else None


def _claim_repair_body_from_payload(payload: dict[str, Any]) -> tuple[str, list[str], list[str]]:
    uses_facts = _json_string_list(payload.get("uses_facts", payload.get("from", [])))
    uses_decls = _json_string_list(payload.get("uses_decls", []))
    for key in ("tactic", "tactic_body", "tactic_block"):
        raw = normalize_lean_text(str(payload.get(key) or "")).strip()
        if not raw:
            continue
        if re.match(r"^\s*have\s+[A-Za-z_][A-Za-z0-9_']*\b", raw):
            parsed = _split_whole_have_tactic_lines(raw)
            if parsed is None:
                continue
            body = "\n".join(parsed[1]).strip()
        else:
            body = raw
        if body:
            return body, uses_facts, uses_decls
    return "", uses_facts, uses_decls


def _proposal_from_claim_repair_response(
    text: str,
    *,
    original: ProofActionProposal,
    fact_name: str,
    claim: str,
) -> ProofActionProposal | None:
    payload = _load_llm_json(text)
    body, uses_facts, uses_decls = _claim_repair_body_from_payload(payload)
    if not body:
        return None
    tactic_block = f"have {fact_name} : {claim} := by\n{_indent_tactic_body(body)}"
    return replace(
        original,
        action_id=f"{original.action_id}_claim_repair_1",
        strategy=f"{original.strategy}_claim_repair",
        tactic_block=tactic_block,
        uses_facts=uses_facts or list(original.uses_facts),
        uses_decls=uses_decls,
        expected_effect="repair the current fact-plan claim after Lean rejected its tactic",
    )


def _claim_repair_error_payload(check: ProofActionCheckResult) -> dict[str, Any]:
    return {
        "error_type": check.error_type,
        "error_message": truncate(str(check.error_message or ""), 700),
        "stderr_excerpt": truncate(str(check.stderr_excerpt or ""), 900),
        "error_snippet": truncate(str(check.error_snippet or ""), 500),
        "goals_excerpt": truncate(str(check.goals_excerpt or ""), 900),
    }


def _build_claim_repair_prompt(
    *,
    proof_context: ProofContext,
    node: ProofSearchNode,
    proposal: ProofActionProposal,
    check: ProofActionCheckResult,
    fact_name: str,
    claim: str,
    blocked_obligations: list[dict[str, Any]],
    search_mode: str,
) -> str:
    payload = {
        "task": "repair_current_fact_plan_claim_only",
        "instructions": [
            "Return JSON only.",
            "Repair only the current `have` claim. Do not change the fact name or claim.",
            "Do not include previous proof-prefix lines, theorem declarations, imports, sorry, admit, or axiom.",
            "Prefer returning a tactic body for the `by` block. If returning a full `have`, it will be stripped and rewrapped with the original fact name and claim.",
            "Use only listed local facts. Do not use blocked declarations or schema/problem metadata as proof facts.",
            "The repaired block will be spliced as: `have <fact_name> : <claim> := by\\n  <your tactic body>` after the accepted proof prefix.",
        ],
        "search_mode": search_mode,
        "target": truncate(str(proof_context.target_formula or ""), 1000),
        "current_have": {
            "fact_name": fact_name,
            "claim": claim,
            "failed_tactic_block": truncate(proposal.tactic_block, 1400),
            "uses_facts": list(proposal.uses_facts),
            "uses_decls": list(proposal.uses_decls),
        },
        "lean_error": _claim_repair_error_payload(check),
        "accepted_proof_prefix": truncate(node.proof_prefix, 1600),
        "local_facts": list(_local_fact_summaries(proof_context, node)[:40]),
        "active_goals": truncate(str(check.goals_excerpt or node.goals_excerpt or ""), 1000),
        "blocked_obligations": list(blocked_obligations[:10]),
        "output_schema": {
            "tactic": "Lean tactic body only, without the surrounding `have ... := by`",
            "uses_facts": ["local_fact_name"],
            "uses_decls": [],
        },
    }
    prompt = (
        "You are repairing one Lean fact-plan claim after Lean rejected the previous tactic.\n"
        "The repair must target the same claim only; do not regenerate the whole plan.\n\n"
        f"Repair payload:\n```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```"
    )
    if len(prompt) <= MAX_CLAIM_REPAIR_PROMPT_CHARS:
        return prompt
    payload["accepted_proof_prefix"] = truncate(node.proof_prefix, 800)
    payload["local_facts"] = payload["local_facts"][:24]
    payload["active_goals"] = truncate(str(check.goals_excerpt or node.goals_excerpt or ""), 600)
    payload["current_have"]["failed_tactic_block"] = truncate(proposal.tactic_block, 800)
    prompt = (
        "You are repairing one Lean fact-plan claim after Lean rejected the previous tactic.\n"
        "The repair must target the same claim only; do not regenerate the whole plan.\n\n"
        f"Repair payload:\n```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```"
    )
    return prompt[: MAX_CLAIM_REPAIR_PROMPT_CHARS - 80] + "\n...TRUNCATED_CLAIM_REPAIR_PROMPT..."


def _tactic_with_facts(head: str, facts: list[str]) -> str:
    clean = [fact for fact in facts if fact]
    return f"{head} [{', '.join(clean)}]" if clean else head


def _looks_like_nonzero_fact(fact_name: str) -> bool:
    lowered = fact_name.lower()
    return "den" in lowered or lowered.endswith("_ne") or lowered.endswith("_ne_zero") or "nonzero" in lowered


def _proposal_from_fact_plan_item(
    item: dict[str, Any],
    *,
    call_index: int,
    idx: int,
) -> ProofActionProposal | None:
    claim = normalize_lean_text(str(item.get("claim") or "")).strip()
    if not claim:
        return None
    fact_name = _lean_ident(item.get("name"), fallback=f"h_plan_{call_index}_{idx}")
    uses_facts = _json_string_list(item.get("from", []))
    tactic = normalize_lean_text(str(item.get("tactic") or "")).strip()
    if re.match(r"^\s*have\s+[A-Za-z_][A-Za-z0-9_']*\b", tactic):
        tactic_block = _normalize_have_tactic_block(tactic)
    elif tactic:
        tactic_body = _indent_tactic_body(tactic)
        tactic_block = f"have {fact_name} : {claim} := by\n{tactic_body}"
    else:
        nonzero_facts = [fact for fact in uses_facts if _looks_like_nonzero_fact(fact)]
        algebra_facts = [fact for fact in uses_facts if fact not in set(nonzero_facts)] or uses_facts
        tactic_lines: list[str] = []
        if "/" in claim and nonzero_facts:
            tactic_lines.append(f"field_simp [{', '.join(nonzero_facts)}] at *")
        tactic_lines.append(_tactic_with_facts("nlinarith", algebra_facts))
        tactic_body = _indent_tactic_body("\n".join(tactic_lines))
        tactic_block = f"have {fact_name} : {claim} := by\n{tactic_body}"
    return ProofActionProposal(
        action_id=str(item.get("action_id") or f"llm_plan_{call_index}_{idx}"),
        strategy=str(item.get("strategy") or "target_fact_plan_have"),
        tactic_block=tactic_block,
        uses_facts=uses_facts,
        uses_decls=_json_string_list(item.get("uses_decls", [])),
        expected_effect=str(item.get("expected_effect") or "target proof fact-plan step"),
        source="llm",
        priority=float(item["priority"]) if item.get("priority") is not None else 0.8,
    )


def _proposals_from_fact_plan_payload(
    payload: dict[str, Any],
    *,
    call_index: int,
    limit: int,
) -> list[ProofActionProposal]:
    fact_plan = payload.get("fact_plan", [])
    if not isinstance(fact_plan, list):
        return []
    proposals: list[ProofActionProposal] = []
    for idx, item in enumerate(fact_plan, start=1):
        if len(proposals) >= limit:
            break
        if not isinstance(item, dict):
            continue
        proposal = _proposal_from_fact_plan_item(item, call_index=call_index, idx=idx)
        if proposal is not None:
            for split_proposal in _split_embedded_have_proposals(proposal):
                if len(proposals) >= limit:
                    break
                proposals.append(split_proposal)
    close = normalize_lean_text(str(payload.get("close") or "")).strip()
    if close and len(proposals) < limit:
        proposals.append(
            ProofActionProposal(
                action_id=str(payload.get("close_action_id") or f"llm_plan_{call_index}_close"),
                strategy="target_fact_plan_close",
                tactic_block=close,
                uses_facts=_json_string_list(payload.get("close_uses_facts", [])),
                uses_decls=[],
                expected_effect="close theorem target from accepted fact-plan facts",
                source="llm",
                priority=1.0,
            )
        )
    return proposals


def _parse_llm_action_bundle(
    text: str,
    *,
    call_index: int,
    limit: int,
) -> tuple[list[ProofActionProposal], dict[str, list[ProofActionProposal]]]:
    payload = _load_llm_json(text)
    if isinstance(payload.get("fact_plan"), list):
        fact_plan_len = len(payload.get("fact_plan", []))
        plan_actions = _proposals_from_fact_plan_payload(
            payload,
            call_index=call_index,
            limit=min(MAX_FACT_PLAN_ACTIONS, max(limit, fact_plan_len + 1)),
        )
        if not plan_actions:
            return [], {}
        return [plan_actions[0]], {plan_actions[0].action_id: plan_actions[1:]}
    proposals_raw = payload.get("proposals", [])
    if isinstance(proposals_raw, list):
        return _proposals_from_raw(proposals_raw, call_index=call_index, limit=limit), {}
    return [], {}


def _append_tactic(prefix: str, tactic_block: str) -> str:
    parts = [normalize_lean_text(prefix).strip(), normalize_lean_text(tactic_block).strip()]
    return "\n".join(part for part in parts if part)


def _resolve_probe_timeout_s(cfg: Any, search_cfg: LLMGuidedSearchConfig) -> int | None:
    requested = search_cfg.probe_timeout_s
    lean_timeout = getattr(getattr(cfg, "lean", None), "timeout_s", None)
    if requested is None:
        return int(lean_timeout) if lean_timeout is not None else None
    if lean_timeout is not None:
        return min(int(requested), int(lean_timeout))
    return int(requested)


def _wall_clock_exhausted(start_time: float, limit_s: int | None) -> bool:
    return limit_s is not None and time.monotonic() - start_time >= limit_s


def _probe_cache_key(proof_context: ProofContext, trial_prefix: str) -> str:
    payload = "\n\n".join(
        [
            normalize_lean_text(proof_context.lean_header),
            normalize_lean_text(proof_context.theorem_decl),
            normalize_lean_text(trial_prefix),
        ]
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def _fact_names_from_tactic(tactic_block: str) -> list[str]:
    return [match.group(1) for match in _HAVE_FACT_RE.finditer(tactic_block or "")]


def _normalize_fact_claim(text: str) -> str:
    return normalize_lean_text(text).replace(" != ", " ≠ ").strip()


def _fact_claims_from_tactic(tactic_block: str) -> list[str]:
    claims: list[str] = []
    for match in _HAVE_CLAIM_RE.finditer(tactic_block or ""):
        claim = _normalize_fact_claim(match.group("claim"))
        if claim:
            claims.append(claim)
    return list(dict.fromkeys(claims))


def _fact_claims_by_name_from_tactic(tactic_block: str) -> dict[str, str]:
    claims: dict[str, str] = {}
    for match in _HAVE_CLAIM_BY_NAME_RE.finditer(tactic_block or ""):
        name = match.group("name").strip()
        claim = _normalize_fact_claim(match.group("claim"))
        if name and claim:
            claims[name] = claim
    return claims


def _fact_types_from_binder_text(text: str) -> dict[str, str]:
    cleaned = normalize_lean_text(text or "").strip()
    if not cleaned or ":" not in cleaned:
        return {}
    names_part, type_part = cleaned.split(":", 1)
    type_text = type_part.strip()
    if not type_text:
        return {}
    names = re.findall(r"\b[A-Za-z_][A-Za-z0-9_']*\b", names_part)
    return {name: type_text for name in names}


def _local_fact_types_from_context(proof_context: ProofContext) -> dict[str, str]:
    fact_types: dict[str, str] = {}
    for chunk in [*proof_context.local_binders, *proof_context.allowed_local_facts]:
        fact_types.update(_fact_types_from_binder_text(chunk))
    return fact_types


def _function_valued_symbols_from_types(fact_types: dict[str, str]) -> set[str]:
    out: set[str] = set()
    for name, type_text in fact_types.items():
        text = normalize_lean_text(type_text or "").strip()
        if ("->" in text or "→" in text) and not text.startswith(("forall ", "∀")):
            out.add(name)
    return out


def _application_argument_expr(arg: str, local_fact_types: dict[str, str]) -> str:
    value = normalize_lean_text(arg or "").strip()
    value = value[1:-1].strip() if value.startswith("(") and value.endswith(")") else value
    if re.fullmatch(r"\d+(?:\.\d+)?", value):
        return f"({value} : Real)"
    if _normalized_claim_key(local_fact_types.get(value)) == "Real":
        return value
    if _IDENT_RE.match(value) and local_fact_types.get(value):
        return f"{value}.val"
    return value


def _repair_function_value_applications(
    text: str,
    *,
    function_symbols: set[str],
    local_fact_types: dict[str, str],
) -> tuple[str, bool]:
    repaired = normalize_lean_text(text or "")
    changed = False
    for symbol in sorted(function_symbols, key=len, reverse=True):
        escaped = re.escape(symbol)

        def repl_parenthesized(match: re.Match[str]) -> str:
            arg = _application_argument_expr(match.group("arg"), local_fact_types)
            return f"({symbol} {arg}).val"

        def repl_call(match: re.Match[str]) -> str:
            arg = _application_argument_expr(match.group("arg"), local_fact_types)
            return f"({symbol} {arg}).val"

        for pattern in (
            rf"\({escaped}\.val\s+(?P<arg>[A-Za-z_][A-Za-z0-9_']*|\d+(?:\.\d+)?|\([^()]+\))\)\.val",
            rf"\b{escaped}\.val\s*\(\s*(?P<arg>[A-Za-z_][A-Za-z0-9_']*|\d+(?:\.\d+)?|[^()]+?)\s*\)",
            rf"\b{escaped}\.val\s+(?P<arg>[A-Za-z_][A-Za-z0-9_']*|\d+(?:\.\d+)?)",
        ):
            next_repaired = re.sub(pattern, repl_parenthesized if pattern.startswith(rf"\({escaped}") else repl_call, repaired)
            changed = changed or next_repaired != repaired
            repaired = next_repaired
    return repaired, changed


def _repair_proposal_function_value_applications(
    proposal: ProofActionProposal,
    *,
    proof_context: ProofContext,
    node: ProofSearchNode,
) -> tuple[ProofActionProposal, bool]:
    fact_types = _local_fact_types_from_context(proof_context)
    fact_types.update(node.local_fact_types)
    function_symbols = _function_valued_symbols_from_types(fact_types)
    if not function_symbols:
        return proposal, False
    repaired_block, changed = _repair_function_value_applications(
        proposal.tactic_block,
        function_symbols=function_symbols,
        local_fact_types=fact_types,
    )
    if not changed:
        return proposal, False
    return (
        replace(
            proposal,
            tactic_block=repaired_block,
            expected_effect=(
                (proposal.expected_effect or "")
                + " [deterministically repaired function-valued quantity `.val` application]"
            ).strip(),
        ),
        True,
    )


def _local_fact_summaries(proof_context: ProofContext, node: ProofSearchNode) -> list[str]:
    fact_types = _local_fact_types_from_context(proof_context)
    fact_types.update(node.local_fact_types)
    summaries: list[str] = []
    for fact in node.local_facts:
        if ":" in fact:
            summaries.append(fact)
            continue
        claim = fact_types.get(fact)
        summaries.append(f"{fact} : {claim}" if claim else fact)
    return list(dict.fromkeys(summaries))


def _branching_constructor_disallowed(proposal: ProofActionProposal) -> bool:
    block = normalize_lean_text(proposal.tactic_block or "")
    if proposal.strategy == "split_conjunction":
        return True
    lines = block.splitlines()
    for index, line in enumerate(lines):
        if not _CONSTRUCTOR_LINE_RE.match(line):
            continue
        indent = len(line) - len(line.lstrip())
        if indent <= 0:
            return True
        for previous in reversed(lines[:index]):
            if not previous.strip():
                continue
            previous_indent = len(previous) - len(previous.lstrip())
            if previous_indent < indent:
                if _HAVE_BY_LINE_RE.match(previous):
                    break
                return True
        else:
            return True
    return False


def _action_shape(proposal: ProofActionProposal) -> str:
    block = normalize_lean_text(proposal.tactic_block or "").strip()
    block = _HAVE_NAME_SHAPE_RE.sub(r"\1_\2", block)
    block = re.sub(r"\s+", " ", block)
    return f"{proposal.strategy}:{block}"


def _failed_action_shape_key(node: ProofSearchNode, proposal: ProofActionProposal) -> str:
    prefix_hash = sha256(normalize_lean_text(node.proof_prefix or "").encode("utf-8")).hexdigest()
    return f"{prefix_hash}:{_action_shape(proposal)}"


def _side_condition_denominator_from_action(proposal: ProofActionProposal) -> str | None:
    if proposal.strategy not in {
        "prove_side_condition",
        "missing_side_condition",
        "missing_side_condition_unavailable",
    }:
        return None
    expected = proposal.expected_effect or ""
    match = _SIDE_CONDITION_EXPECTED_RE.search(expected)
    if match:
        denom = normalize_side_condition_expression(match.group("denom"))
        return denom or None
    match = _SIDE_CONDITION_CLAIM_RE.search(proposal.tactic_block or "")
    if match:
        denom = normalize_side_condition_expression(match.group("denom"))
        return denom or None
    return None


def _covered_obligation_ids_from_action(
    *,
    proof_context: ProofContext,
    remaining_obligations: list[str],
    proposal: ProofActionProposal,
    new_fact_names: list[str],
) -> list[str]:
    """Conservatively mark obligations covered by a Lean-checked action.

    We only credit an LLM action for an obligation when it introduces the
    expected replay fact and the tactic block contains the formal claim or uses
    the required verified declaration. Schema metadata alone is deliberately not
    treated as proof evidence here.
    """
    by_id = {item.obligation_id: item for item in proof_context.obligation_replay_items}
    block = normalize_lean_text(proposal.tactic_block or "")
    uses_decls = set(proposal.uses_decls or [])
    new_fact_set = set(new_fact_names)
    covered: list[str] = []
    for obligation_id in remaining_obligations:
        item = by_id.get(obligation_id)
        if item is None or item.produced_fact_name not in new_fact_set:
            continue
        formal_claim = normalize_lean_text(item.formal_claim or "").strip()
        if formal_claim and formal_claim != "True" and formal_claim in block:
            covered.append(obligation_id)
            continue
        if item.must_use and (item.must_use in uses_decls or item.must_use in block):
            covered.append(obligation_id)
    return covered


def _meaningful_progress(
    *,
    node: ProofSearchNode,
    check: ProofActionCheckResult,
    new_fact_names: list[str],
    new_fact_claims: list[str],
    covered_obligation_ids: list[str],
    allow_new_fact_alias: bool = False,
) -> bool:
    if check.status == "closed":
        return True
    if allow_new_fact_alias and any(fact not in node.local_facts for fact in new_fact_names):
        return True
    if any(claim not in node.local_fact_claims for claim in new_fact_claims):
        return True
    if new_fact_names and not new_fact_claims and any(fact not in node.local_facts for fact in new_fact_names):
        return True
    if covered_obligation_ids:
        return True
    current_goals = normalize_lean_text(check.goals_excerpt or "").strip()
    previous_goals = normalize_lean_text(node.goals_excerpt or "").strip()
    if current_goals and previous_goals:
        return current_goals != previous_goals
    # Without a comparable previous goal snapshot, keep the action and let Lean
    # plus later budget limits decide. This avoids pruning correct first-step
    # simplifications only because the probe did not expose enough detail.
    return True


def _action_payload(
    *,
    proof_context: ProofContext,
    proposal: ProofActionProposal,
    check: ProofActionCheckResult,
    accepted: bool,
    parent_node_id: str | None = None,
) -> dict[str, Any]:
    check_payload = check.to_dict()
    for key in ("error_line", "error_col", "error_snippet", "probe_full_proof_body"):
        if check_payload.get(key) is None:
            check_payload.pop(key, None)
    return {
        "sample_id": proof_context.sample_id,
        "candidate_id": proof_context.candidate_id,
        "accepted": accepted,
        "source": proposal.source,
        "uses_facts": list(proposal.uses_facts),
        "uses_decls": list(proposal.uses_decls),
        "expected_effect": proposal.expected_effect,
        "priority": proposal.priority,
        "parent_node_id": parent_node_id,
        **check_payload,
    }


def _guard_rejection(
    proposal: ProofActionProposal,
    reasons: Iterable[str],
) -> ProofActionCheckResult:
    message = ";".join(sorted(set(reasons)))
    return ProofActionCheckResult(
        action_id=proposal.action_id,
        strategy=proposal.strategy,
        tactic_block=proposal.tactic_block,
        status="invalid",
        error_type="action_guard_failed",
        error_message=message,
        stderr_excerpt=message,
        goals_excerpt=None,
    )


def _missing_side_condition_check(proposal: ProofActionProposal) -> ProofActionCheckResult:
    error_type = (
        "missing_side_condition_unavailable"
        if proposal.strategy == "missing_side_condition_unavailable"
        else "missing_side_condition"
    )
    return ProofActionCheckResult(
        action_id=proposal.action_id,
        strategy=proposal.strategy,
        tactic_block=proposal.tactic_block,
        status="invalid",
        error_type=error_type,
        error_message=proposal.expected_effect,
        stderr_excerpt=proposal.expected_effect,
        goals_excerpt=None,
    )


def _proof_context_hash(proof_context: ProofContext) -> str:
    payload = json.dumps(
        {
            "theorem_decl": normalize_lean_text(proof_context.theorem_decl),
            "local_binders": list(proof_context.local_binders),
            "local_hypotheses": list(proof_context.local_hypotheses),
            "allowed_local_facts": list(proof_context.allowed_local_facts),
            "added_physical_assumptions": list(proof_context.added_physical_assumptions),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def _pre_search_physical_positive_augmentation(
    *,
    proof_context: ProofContext,
    lean_runner: Any,
    search_cfg: LLMGuidedSearchConfig,
    local_facts: list[str],
    local_fact_types: dict[str, str],
    augmentation_checks: list[dict[str, Any]],
) -> tuple[ProofContext, list[str], dict[str, str], str | None]:
    """Apply typed physical positivity assumptions once before search nodes run."""

    if not (
        search_cfg.allow_physical_positive_hypothesis_augmentation
        and search_cfg.deterministic_side_conditions_first
    ):
        return proof_context, local_facts, local_fact_types, None

    node = ProofSearchNode(
        node_id="pre_search_physical_positive_augmentation",
        parent_id=None,
        depth=0,
        proof_prefix="",
        local_facts=list(dict.fromkeys(local_facts)),
        local_fact_types=dict(local_fact_types),
    )
    proposals = propose_side_condition_actions(
        proof_context,
        _local_fact_summaries(proof_context, node),
        known_denominators=[],
    )
    seen_denominators: set[str] = set()
    last_error: str | None = None

    for proposal in proposals:
        if proposal.strategy != "missing_side_condition":
            continue
        denominator = _side_condition_denominator_from_action(proposal)
        denominator_key = normalize_side_condition_expression(denominator or "")
        if denominator_key and denominator_key in seen_denominators:
            continue
        if denominator_key:
            seen_denominators.add(denominator_key)

        before_context = proof_context
        before_hash = _proof_context_hash(before_context)
        before_added_names = {
            str(item.get("name") or "").strip()
            for item in before_context.added_physical_assumptions
            if str(item.get("name") or "").strip()
        }
        augment_proposal = ProofActionProposal(
            action_id=f"pre_search_augment_physical_positive_hypotheses_{len(augmentation_checks) + 1}",
            strategy="augment_physical_positive_hypotheses",
            tactic_block="",
            uses_facts=[],
            uses_decls=[],
            expected_effect=proposal.expected_effect,
            source="deterministic",
            priority=0.0,
        )
        augmentation = augment_context_for_missing_side_condition(
            context=before_context,
            proposal=proposal,
            positive_types=search_cfg.physical_positive_types,
            max_added=search_cfg.max_added_positive_hypotheses,
            lean_runner=lean_runner,
            require_compile=search_cfg.require_augmented_theorem_compile,
        )
        augmentation.check.action_id = augment_proposal.action_id
        after_hash = _proof_context_hash(augmentation.context)
        added_items = [
            item
            for item in augmentation.context.added_physical_assumptions
            if str(item.get("name") or "").strip()
            and str(item.get("name") or "").strip() not in before_added_names
        ]
        new_names = [
            str(item.get("name") or "").strip()
            for item in added_items
            if str(item.get("name") or "").strip()
        ]
        made_context_change = before_hash != after_hash and bool(new_names)
        if augmentation.check.status == "context_augmented" and not made_context_change:
            augmentation.check = replace(
                augmentation.check,
                status="invalid",
                error_type="no_context_change",
                error_message="physical positivity augmentation changed no theorem context or local facts",
                stderr_excerpt=None,
            )
        accepted = augmentation.check.status == "context_augmented" and made_context_change
        payload = _action_payload(
            proof_context=before_context,
            proposal=augment_proposal,
            check=augmentation.check,
            accepted=accepted,
            parent_node_id=None,
        )
        payload["phase"] = "pre_search"
        payload["search_node_action"] = False
        payload["side_condition_denominator"] = denominator
        payload["theorem_hash_before"] = before_hash
        payload["theorem_hash_after"] = after_hash
        payload["added_physical_assumptions"] = list(augmentation.context.added_physical_assumptions)
        payload["new_local_facts"] = list(new_names) if accepted else []
        payload["compile_pass"] = bool((augmentation.compile_result or {}).get("compile_pass", True))
        payload["compile_result"] = {
            key: value
            for key, value in (augmentation.compile_result or {}).items()
            if key
            in {
                "compile_pass",
                "syntax_ok",
                "elaboration_ok",
                "error_type",
                "backend_used",
                "route_reason",
                "route_fallback_used",
                "sub_error_type",
                "error_message",
                "stderr_excerpt",
            }
        }
        augmentation_checks.append(payload)
        if not accepted:
            last_error = augmentation.check.error_message or augmentation.check.error_type
            continue

        proof_context = augmentation.context
        local_facts = list(dict.fromkeys([*local_facts, *new_names]))
        local_fact_types = dict(local_fact_types)
        for item in added_items:
            name = str(item.get("name") or "").strip()
            expression = str(item.get("expression") or "").strip()
            if name and expression:
                local_fact_types[name] = expression
        last_error = None

    return proof_context, local_facts, local_fact_types, last_error


def _run_universal_fact_instantiations(
    *,
    proof_context: ProofContext,
    lean_runner: Any,
    prefix: str,
    root_goals_excerpt: str | None,
    local_facts: list[str],
    local_fact_types: dict[str, str],
    accepted_actions: list[dict[str, Any]],
    rejected_actions: list[dict[str, Any]],
    probe_checks: int,
    max_probe_checks: int,
    timeout_s: int | None,
) -> tuple[str, str | None, list[str], dict[str, str], int, str | None]:
    node = ProofSearchNode(
        node_id="universal_instantiation_root",
        parent_id=None,
        depth=0,
        proof_prefix=prefix,
        local_facts=list(dict.fromkeys(local_facts)),
        local_fact_types=dict(local_fact_types),
        goals_excerpt=root_goals_excerpt,
    )
    proposals = _universal_fact_instantiation_proposals(proof_context=proof_context, node=node)
    stop_reason: str | None = None
    for proposal in proposals:
        if probe_checks >= max_probe_checks:
            stop_reason = "max_probe_checks_exhausted"
            break
        dynamic_context = replace(
            proof_context,
            allowed_local_facts=list(dict.fromkeys([*proof_context.allowed_local_facts, *local_facts])),
            local_hypotheses=list(dict.fromkeys([*proof_context.local_hypotheses, *local_facts])),
        )
        ok, reasons = validate_action_proposal(proposal, dynamic_context)
        if not ok:
            rejected_actions.append(
                _action_payload(
                    proof_context=proof_context,
                    proposal=proposal,
                    check=_guard_rejection(proposal, reasons),
                    accepted=False,
                    parent_node_id=None,
                )
            )
            continue
        check, trial_prefix = _probe_action(
            proof_context=proof_context,
            lean_runner=lean_runner,
            node=node,
            proposal=proposal,
            timeout_s=timeout_s,
        )
        probe_checks += 1
        accepted, check, acceptance_metadata = _acceptance_from_probe(proposal, check)
        payload = _action_payload(
            proof_context=proof_context,
            proposal=proposal,
            check=check,
            accepted=accepted,
            parent_node_id=None,
        )
        payload.update(acceptance_metadata)
        payload["deterministic_context_instantiation"] = True
        payload["probe_checks_used"] = probe_checks
        payload["proposed_local_facts"] = _fact_names_from_tactic(proposal.tactic_block)
        payload["proposed_local_fact_claims"] = _fact_claims_from_tactic(proposal.tactic_block)
        if not accepted:
            rejected_actions.append(payload)
            continue
        accepted_actions.append(payload)
        prefix = trial_prefix
        root_goals_excerpt = check.goals_excerpt or root_goals_excerpt
        new_fact_names = _fact_names_from_tactic(proposal.tactic_block)
        local_facts = list(dict.fromkeys([*local_facts, *new_fact_names]))
        local_fact_types = dict(local_fact_types)
        local_fact_types.update(_fact_claims_by_name_from_tactic(proposal.tactic_block))
        node = replace(
            node,
            proof_prefix=prefix,
            local_facts=list(dict.fromkeys([*node.local_facts, *new_fact_names])),
            local_fact_types=dict(local_fact_types),
            goals_excerpt=root_goals_excerpt,
        )
    return prefix, root_goals_excerpt, local_facts, local_fact_types, probe_checks, stop_reason


def _probe_action(
    *,
    proof_context: ProofContext,
    lean_runner: Any,
    node: ProofSearchNode,
    proposal: ProofActionProposal,
    timeout_s: int | None,
    trial_prefix: str | None = None,
) -> tuple[ProofActionCheckResult, str]:
    trial_prefix = trial_prefix if trial_prefix is not None else _append_tactic(
        node.proof_prefix,
        proposal.tactic_block,
    )
    result = lean_runner.probe_proof_prefix(
        lean_header=proof_context.lean_header,
        theorem_decl=proof_context.theorem_decl,
        proof_prefix=trial_prefix,
        timeout_s=timeout_s,
    )
    return (
        ProofActionCheckResult(
            action_id=proposal.action_id,
            strategy=proposal.strategy,
            tactic_block=proposal.tactic_block,
            status=result.status,
            error_type=result.error_type,
            error_message=result.error_message,
            stderr_excerpt=result.stderr_excerpt,
            goals_excerpt=result.goals_excerpt,
            error_line=result.error_line,
            error_col=result.error_col,
            error_snippet=result.error_snippet,
            probe_full_proof_body=result.probe_full_proof_body,
            unsolved_goal_count=result.unsolved_goal_count,
        ),
        trial_prefix,
    )


def _cached_probe_check(
    *,
    proposal: ProofActionProposal,
    cached: ProofActionCheckResult,
) -> ProofActionCheckResult:
    return replace(
        cached,
        action_id=proposal.action_id,
        strategy=proposal.strategy,
        tactic_block=proposal.tactic_block,
    )


def _invalid_probe_check(
    *,
    proposal: ProofActionProposal,
    error_type: str,
    error_message: str,
    goals_excerpt: str | None = None,
) -> ProofActionCheckResult:
    return ProofActionCheckResult(
        action_id=proposal.action_id,
        strategy=proposal.strategy,
        tactic_block=proposal.tactic_block,
        status="invalid",
        error_type=error_type,
        error_message=error_message,
        stderr_excerpt=error_message,
        goals_excerpt=goals_excerpt,
    )


def _goals_excerpt_mentions_local_fact(goals_excerpt: str | None, fact_name: str) -> bool:
    if not goals_excerpt or not fact_name:
        return False
    for block in normalize_lean_text(goals_excerpt).split("unsolved goals"):
        for raw_line in block.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("⊢"):
                break
            if ":" in line and re.search(rf"\b{re.escape(fact_name)}\b", line):
                return True
    return False


def _have_progress_validation_failure(
    proposal: ProofActionProposal,
    check: ProofActionCheckResult,
) -> tuple[str, str] | None:
    """Reject progress from a `have` whose proof block is still open.

    Lean reports both a failed inner `have` proof and the outer theorem goal as
    `unsolved goals`. Treating that as ordinary progress leaks an unproved fact
    into the search state. A successful fact-producing `have` should leave only
    the expected outer goal, and the declared fact should be visible in that
    remaining goal context.
    """
    if check.status != "progress":
        return None
    fact_names = _fact_names_from_tactic(proposal.tactic_block)
    if not fact_names:
        return None
    goal_count = check.unsolved_goal_count
    # Older test doubles may not provide this field. Real Lean probes always do.
    if goal_count is None:
        return None
    if goal_count != 1:
        return (
            "have_subgoal_unresolved",
            (
                "fact-producing have action left unresolved subgoals; "
                f"expected exactly one remaining theorem goal, got {goal_count}"
            ),
        )
    missing = [
        fact_name
        for fact_name in fact_names
        if not _goals_excerpt_mentions_local_fact(check.goals_excerpt, fact_name)
    ]
    if missing:
        return (
            "have_fact_not_in_remaining_context",
            (
                "fact-producing have action did not expose its declared fact "
                f"in the remaining goal context: {', '.join(missing)}"
            ),
        )
    return None


def _acceptance_from_probe(
    proposal: ProofActionProposal,
    check: ProofActionCheckResult,
) -> tuple[bool, ProofActionCheckResult, dict[str, Any]]:
    accepted = check.status in {"progress", "closed"}
    metadata: dict[str, Any] = {}
    if not accepted:
        return False, check, metadata
    failure = _have_progress_validation_failure(proposal, check)
    if failure is None:
        return True, check, metadata
    error_type, error_message = failure
    metadata["raw_probe_status"] = check.status
    metadata["raw_probe_error_type"] = check.error_type
    metadata["have_progress_validation"] = {
        "error_type": error_type,
        "error_message": error_message,
        "unsolved_goal_count": check.unsolved_goal_count,
    }
    return (
        False,
        replace(
            check,
            status="invalid",
            error_type=error_type,
            error_message=error_message,
            stderr_excerpt=error_message,
        ),
        metadata,
    )


def _is_tactic_no_goals(check: ProofActionCheckResult) -> bool:
    text = "\n".join(
        part
        for part in [
            check.error_type or "",
            check.error_message or "",
            check.stderr_excerpt or "",
            check.error_snippet or "",
        ]
        if part
    ).lower()
    return check.error_type == "tactic_no_goals" or "no goals to be solved" in text


def _attempt_tactic_no_goals_repairs(
    *,
    proof_context: ProofContext,
    lean_runner: Any,
    node: ProofSearchNode,
    proposal: ProofActionProposal,
    original_check: ProofActionCheckResult,
    dynamic_context: ProofContext,
    timeout_s: int | None,
    probe_cache: dict[str, ProofActionCheckResult],
    seen_probe_prefixes: set[str],
    seen_action_blocks: set[str],
    probe_checks: int,
    max_probe_checks: int,
    parent_node_id: str | None,
) -> dict[str, Any]:
    repairs = _tactic_no_goals_repair_proposals(proposal) if _is_tactic_no_goals(original_check) else []
    result: dict[str, Any] = {
        "attempted_action_ids": [repair.action_id for repair, _ in repairs],
        "accepted": None,
        "rejected_payloads": [],
        "probe_checks": probe_checks,
        "stop_reason": None,
    }
    for repair, metadata in repairs:
        pending_actions = list(metadata.pop("_pending_actions", []))
        ok, reasons = validate_action_proposal(repair, dynamic_context)
        if not ok:
            repair_check = _guard_rejection(repair, reasons)
            repair_trial_prefix = _append_tactic(node.proof_prefix, repair.tactic_block)
            cache_hit = False
        else:
            repeated = repair.tactic_block in seen_action_blocks
            seen_action_blocks.add(repair.tactic_block)
            repair_trial_prefix = _append_tactic(node.proof_prefix, repair.tactic_block)
            if repair_trial_prefix in seen_probe_prefixes:
                repair_check = _invalid_probe_check(
                    proposal=repair,
                    error_type="duplicate_probe_prefix",
                    error_message="exact proof prefix already checked in this search",
                    goals_excerpt=node.goals_excerpt,
                )
                cache_hit = True
            elif result["probe_checks"] >= max_probe_checks:
                result["stop_reason"] = "max_probe_checks_exhausted"
                break
            else:
                repair_key = _probe_cache_key(proof_context, repair_trial_prefix)
                if repair_key in probe_cache:
                    repair_check = _cached_probe_check(proposal=repair, cached=probe_cache[repair_key])
                    cache_hit = True
                else:
                    repair_check, repair_trial_prefix = _probe_action(
                        proof_context=proof_context,
                        lean_runner=lean_runner,
                        node=node,
                        proposal=repair,
                        timeout_s=timeout_s,
                        trial_prefix=repair_trial_prefix,
                    )
                    result["probe_checks"] += 1
                    probe_cache[repair_key] = replace(repair_check)
                    cache_hit = False
                seen_probe_prefixes.add(repair_trial_prefix)
            metadata = {**metadata, "repair_repeated_tactic_block": repeated}

        accepted, repair_check, acceptance_metadata = _acceptance_from_probe(repair, repair_check)
        metadata = {**metadata, **acceptance_metadata}
        if accepted:
            result["accepted"] = {
                "proposal": repair,
                "check": repair_check,
                "trial_prefix": repair_trial_prefix,
                "cache_hit": cache_hit,
                "metadata": metadata,
                "pending_actions": pending_actions,
            }
            return result

        payload = _action_payload(
            proof_context=proof_context,
            proposal=repair,
            check=repair_check,
            accepted=False,
            parent_node_id=parent_node_id,
        )
        payload.update(metadata)
        payload["repair_of"] = proposal.action_id
        payload["cache_hit"] = cache_hit
        payload["probe_checks_used"] = result["probe_checks"]
        payload["proposed_local_facts"] = _fact_names_from_tactic(repair.tactic_block)
        payload["proposed_local_fact_claims"] = _fact_claims_from_tactic(repair.tactic_block)
        payload["new_local_facts"] = []
        payload["new_local_fact_claims"] = []
        payload["covered_obligations"] = []
        payload["remaining_obligations_after"] = list(node.remaining_obligations)
        payload["probe_full_proof_body"] = repair_trial_prefix
        result["rejected_payloads"].append(payload)
    return result


def _check_text(check: ProofActionCheckResult) -> str:
    return "\n".join(
        part
        for part in [
            check.error_type or "",
            check.error_message or "",
            check.stderr_excerpt or "",
            check.error_snippet or "",
        ]
        if part
    ).lower()


def _is_rewrite_failed(check: ProofActionCheckResult) -> bool:
    text = _check_text(check)
    return "rewrite failed" in text or "pattern not found" in text


def _is_linarith_failed(check: ProofActionCheckResult) -> bool:
    text = _check_text(check)
    return "linarith failed" in text or "nlinarith failed" in text or "failed to solve" in text


def _nonzero_fact_names(proof_context: ProofContext, node: ProofSearchNode) -> list[str]:
    fact_types = _local_fact_types_from_context(proof_context)
    fact_types.update(node.local_fact_types)
    out: list[str] = []
    for fact in node.local_facts:
        type_text = normalize_lean_text(fact_types.get(fact) or "")
        if _looks_like_nonzero_fact(fact) or "≠ 0" in type_text or "!= 0" in type_text:
            out.append(fact)
    return list(dict.fromkeys(out))


def _deterministic_action_repair_proposals(
    *,
    proof_context: ProofContext,
    node: ProofSearchNode,
    proposal: ProofActionProposal,
    check: ProofActionCheckResult,
) -> list[tuple[ProofActionProposal, dict[str, Any]]]:
    repairs: list[tuple[ProofActionProposal, dict[str, Any]]] = []
    parsed = _single_have_name_claim(proposal.tactic_block)
    if parsed is not None:
        fact_name, claim = parsed
        facts = list(dict.fromkeys([fact for fact in proposal.uses_facts if fact]))
        nonzero_facts = _nonzero_fact_names(proof_context, node)
        if "/" in claim and "nlinarith" in proposal.tactic_block and nonzero_facts and _is_linarith_failed(check):
            tactic_lines = [
                f"field_simp [{', '.join(nonzero_facts)}] at *",
                _tactic_with_facts("nlinarith", facts),
            ]
            tactic_body = _indent_tactic_body("\n".join(tactic_lines))
            tactic_block = f"have {fact_name} : {claim} := by\n{tactic_body}"
            repairs.append(
                (
                    replace(
                        proposal,
                        action_id=f"{proposal.action_id}_repair_fraction_field_simp",
                        strategy=f"{proposal.strategy}_deterministic_repair",
                        tactic_block=tactic_block,
                        expected_effect="repair fractional claim by clearing known nonzero denominators before nlinarith",
                    ),
                    {"repair_kind": "fraction_field_simp_then_nlinarith"},
                )
            )
        if _is_rewrite_failed(check) and facts:
            for idx, tactic in enumerate(
                [
                    _tactic_with_facts("linarith", facts),
                    _tactic_with_facts("nlinarith", facts),
                    f"simpa using {facts[0]}",
                ],
                start=1,
            ):
                repairs.append(
                    (
                        replace(
                            proposal,
                            action_id=f"{proposal.action_id}_repair_rw_{idx}",
                            strategy=f"{proposal.strategy}_deterministic_repair",
                            tactic_block=f"have {fact_name} : {claim} := by\n{_indent_tactic_body(tactic)}",
                            expected_effect="repair rewrite failure with algebraic/simpa fallback",
                        ),
                        {"repair_kind": "rewrite_failed_algebra_or_simpa", "repair_variant_index": idx},
                    )
                )
    component_close = _component_close_proposal(proof_context, node)
    if component_close is not None and (
        proposal.strategy in {"close_goal", "target_fact_plan_close"}
        or "type mismatch" in _check_text(check)
    ):
        repairs.append(
            (
                replace(
                    component_close,
                    action_id=f"{proposal.action_id}_repair_component_close",
                    expected_effect="repair failed close action by closing target conjunction from matching component facts",
                ),
                {"repair_kind": "component_conjunction_close"},
            )
        )
    return repairs


def _attempt_deterministic_action_repairs(
    *,
    proof_context: ProofContext,
    lean_runner: Any,
    node: ProofSearchNode,
    proposal: ProofActionProposal,
    original_check: ProofActionCheckResult,
    dynamic_context: ProofContext,
    timeout_s: int | None,
    probe_cache: dict[str, ProofActionCheckResult],
    seen_probe_prefixes: set[str],
    seen_action_blocks: set[str],
    probe_checks: int,
    max_probe_checks: int,
    parent_node_id: str | None,
) -> dict[str, Any]:
    repairs = _deterministic_action_repair_proposals(
        proof_context=proof_context,
        node=node,
        proposal=proposal,
        check=original_check,
    )
    result: dict[str, Any] = {
        "attempted_action_ids": [repair.action_id for repair, _ in repairs],
        "accepted": None,
        "rejected_payloads": [],
        "probe_checks": probe_checks,
        "stop_reason": None,
    }
    for repair, metadata in repairs:
        ok, reasons = validate_action_proposal(repair, dynamic_context)
        if not ok:
            repair_check = _guard_rejection(repair, reasons)
            repair_trial_prefix = _append_tactic(node.proof_prefix, repair.tactic_block)
            cache_hit = False
        else:
            repeated = repair.tactic_block in seen_action_blocks
            seen_action_blocks.add(repair.tactic_block)
            repair_trial_prefix = _append_tactic(node.proof_prefix, repair.tactic_block)
            if repair_trial_prefix in seen_probe_prefixes:
                repair_check = _invalid_probe_check(
                    proposal=repair,
                    error_type="duplicate_probe_prefix",
                    error_message="exact proof prefix already checked in this search",
                    goals_excerpt=node.goals_excerpt,
                )
                cache_hit = True
            elif result["probe_checks"] >= max_probe_checks:
                result["stop_reason"] = "max_probe_checks_exhausted"
                break
            else:
                repair_key = _probe_cache_key(proof_context, repair_trial_prefix)
                if repair_key in probe_cache:
                    repair_check = _cached_probe_check(proposal=repair, cached=probe_cache[repair_key])
                    cache_hit = True
                else:
                    repair_check, repair_trial_prefix = _probe_action(
                        proof_context=proof_context,
                        lean_runner=lean_runner,
                        node=node,
                        proposal=repair,
                        timeout_s=timeout_s,
                        trial_prefix=repair_trial_prefix,
                    )
                    result["probe_checks"] += 1
                    probe_cache[repair_key] = replace(repair_check)
                    cache_hit = False
                seen_probe_prefixes.add(repair_trial_prefix)
            metadata = {**metadata, "repair_repeated_tactic_block": repeated}

        accepted, repair_check, acceptance_metadata = _acceptance_from_probe(repair, repair_check)
        metadata = {**metadata, **acceptance_metadata}
        if accepted:
            result["accepted"] = {
                "proposal": repair,
                "check": repair_check,
                "trial_prefix": repair_trial_prefix,
                "cache_hit": cache_hit,
                "metadata": metadata,
            }
            return result

        payload = _action_payload(
            proof_context=proof_context,
            proposal=repair,
            check=repair_check,
            accepted=False,
            parent_node_id=parent_node_id,
        )
        payload.update(metadata)
        payload["repair_of"] = proposal.action_id
        payload["cache_hit"] = cache_hit
        payload["probe_checks_used"] = result["probe_checks"]
        payload["proposed_local_facts"] = _fact_names_from_tactic(repair.tactic_block)
        payload["proposed_local_fact_claims"] = _fact_claims_from_tactic(repair.tactic_block)
        payload["new_local_facts"] = []
        payload["new_local_fact_claims"] = []
        payload["covered_obligations"] = []
        payload["remaining_obligations_after"] = list(node.remaining_obligations)
        payload["probe_full_proof_body"] = repair_trial_prefix
        result["rejected_payloads"].append(payload)
    return result


def _is_fact_plan_have_action(proposal: ProofActionProposal) -> bool:
    return proposal.source == "llm" and proposal.strategy.startswith("target_fact_plan_have")


def _claim_repair_prompt_summary(
    *,
    proof_context: ProofContext,
    node: ProofSearchNode,
    prompt: str,
    llm_call_index: int,
    proposal: ProofActionProposal,
    check: ProofActionCheckResult,
    fact_name: str,
    claim: str,
    search_mode: str,
) -> dict[str, Any]:
    return {
        "sample_id": proof_context.sample_id,
        "candidate_id": proof_context.candidate_id,
        "llm_call_index": llm_call_index,
        "prompt_type": "claim_level_repair",
        "node_id": node.node_id,
        "depth": node.depth,
        "failed_action_id": proposal.action_id,
        "failed_strategy": proposal.strategy,
        "fact_name": fact_name,
        "claim": claim,
        "search_mode": search_mode,
        "error_type": check.error_type,
        "error_message": truncate(str(check.error_message or ""), 500),
        "stderr_excerpt": truncate(str(check.stderr_excerpt or ""), 700),
        "prompt_chars": len(prompt),
        "proof_prefix_excerpt": truncate(node.proof_prefix, 800),
        "local_facts": list(_local_fact_summaries(proof_context, node)[:40]),
        "prompt_excerpt": truncate(prompt, 1600),
    }


def _attempt_claim_level_llm_repair(
    *,
    proof_context: ProofContext,
    lean_runner: Any,
    llm_client: Any,
    node: ProofSearchNode,
    proposal: ProofActionProposal,
    original_check: ProofActionCheckResult,
    dynamic_context: ProofContext,
    timeout_s: int | None,
    probe_cache: dict[str, ProofActionCheckResult],
    seen_probe_prefixes: set[str],
    seen_action_blocks: set[str],
    probe_checks: int,
    max_probe_checks: int,
    parent_node_id: str | None,
    blocked_obligations: list[dict[str, Any]],
    search_mode: str,
    llm_call_index: int,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "attempted": False,
        "accepted": None,
        "rejected_payloads": [],
        "probe_checks": probe_checks,
        "stop_reason": None,
        "prompt_summary": None,
    }
    parsed = _single_have_name_claim(proposal.tactic_block)
    if not _is_fact_plan_have_action(proposal) or parsed is None:
        return result
    fact_name, claim = parsed
    prompt = _build_claim_repair_prompt(
        proof_context=proof_context,
        node=node,
        proposal=proposal,
        check=original_check,
        fact_name=fact_name,
        claim=claim,
        blocked_obligations=blocked_obligations,
        search_mode=search_mode,
    )
    result["attempted"] = True
    result["prompt_summary"] = _claim_repair_prompt_summary(
        proof_context=proof_context,
        node=node,
        prompt=prompt,
        llm_call_index=llm_call_index,
        proposal=proposal,
        check=original_check,
        fact_name=fact_name,
        claim=claim,
        search_mode=search_mode,
    )
    try:
        repair = _proposal_from_claim_repair_response(
            _call_llm(llm_client, prompt),
            original=proposal,
            fact_name=fact_name,
            claim=claim,
        )
    except Exception as exc:
        repair = None
        parse_error = f"claim_repair_parse_failed:{type(exc).__name__}:{exc}"
    else:
        parse_error = "claim_repair_empty_or_invalid_json" if repair is None else None
    if repair is None:
        parse_proposal = replace(
            proposal,
            action_id=f"{proposal.action_id}_claim_repair_1",
            strategy=f"{proposal.strategy}_claim_repair",
            tactic_block="",
            expected_effect="repair the current fact-plan claim after Lean rejected its tactic",
        )
        repair_check = _invalid_probe_check(
            proposal=parse_proposal,
            error_type="claim_repair_parse_failed",
            error_message=parse_error or "claim_repair_parse_failed",
            goals_excerpt=original_check.goals_excerpt,
        )
        payload = _action_payload(
            proof_context=proof_context,
            proposal=parse_proposal,
            check=repair_check,
            accepted=False,
            parent_node_id=parent_node_id,
        )
        payload["repair_of"] = proposal.action_id
        payload["repair_kind"] = "claim_level_llm_repair"
        payload["lean_error"] = _claim_repair_error_payload(original_check)
        payload["new_local_facts"] = []
        payload["new_local_fact_claims"] = []
        payload["covered_obligations"] = []
        payload["remaining_obligations_after"] = list(node.remaining_obligations)
        result["rejected_payloads"].append(payload)
        return result

    metadata = {
        "repair_of": proposal.action_id,
        "repair_kind": "claim_level_llm_repair",
        "lean_error": _claim_repair_error_payload(original_check),
    }
    ok, reasons = validate_action_proposal(repair, dynamic_context)
    if not ok:
        repair_check = _guard_rejection(repair, reasons)
        repair_trial_prefix = _append_tactic(node.proof_prefix, repair.tactic_block)
        cache_hit = False
    else:
        repeated = repair.tactic_block in seen_action_blocks
        seen_action_blocks.add(repair.tactic_block)
        repair_trial_prefix = _append_tactic(node.proof_prefix, repair.tactic_block)
        if repair_trial_prefix in seen_probe_prefixes:
            repair_check = _invalid_probe_check(
                proposal=repair,
                error_type="duplicate_probe_prefix",
                error_message="exact proof prefix already checked in this search",
                goals_excerpt=node.goals_excerpt,
            )
            cache_hit = True
        elif result["probe_checks"] >= max_probe_checks:
            result["stop_reason"] = "max_probe_checks_exhausted"
            return result
        else:
            repair_key = _probe_cache_key(proof_context, repair_trial_prefix)
            if repair_key in probe_cache:
                repair_check = _cached_probe_check(proposal=repair, cached=probe_cache[repair_key])
                cache_hit = True
            else:
                repair_check, repair_trial_prefix = _probe_action(
                    proof_context=proof_context,
                    lean_runner=lean_runner,
                    node=node,
                    proposal=repair,
                    timeout_s=timeout_s,
                    trial_prefix=repair_trial_prefix,
                )
                result["probe_checks"] += 1
                probe_cache[repair_key] = replace(repair_check)
                cache_hit = False
            seen_probe_prefixes.add(repair_trial_prefix)
        metadata["repair_repeated_tactic_block"] = repeated

    accepted, repair_check, acceptance_metadata = _acceptance_from_probe(repair, repair_check)
    metadata = {**metadata, **acceptance_metadata}
    if accepted:
        result["accepted"] = {
            "proposal": repair,
            "check": repair_check,
            "trial_prefix": repair_trial_prefix,
            "cache_hit": cache_hit,
            "metadata": metadata,
        }
        return result

    if _is_tactic_no_goals(repair_check):
        nested_repair = _attempt_tactic_no_goals_repairs(
            proof_context=proof_context,
            lean_runner=lean_runner,
            node=node,
            proposal=repair,
            original_check=repair_check,
            dynamic_context=dynamic_context,
            timeout_s=timeout_s,
            probe_cache=probe_cache,
            seen_probe_prefixes=seen_probe_prefixes,
            seen_action_blocks=seen_action_blocks,
            probe_checks=result["probe_checks"],
            max_probe_checks=max_probe_checks,
            parent_node_id=parent_node_id,
        )
        result["probe_checks"] = int(nested_repair.get("probe_checks", result["probe_checks"]))
        result["rejected_payloads"].extend(nested_repair.get("rejected_payloads") or [])
        if nested_repair.get("stop_reason"):
            result["stop_reason"] = str(nested_repair["stop_reason"])
            return result
        accepted_nested = nested_repair.get("accepted")
        if accepted_nested:
            nested_metadata = {
                **metadata,
                **(accepted_nested.get("metadata") or {}),
                "claim_repair_no_goals_repaired": True,
                "claim_repair_action_id": repair.action_id,
            }
            result["accepted"] = {
                "proposal": accepted_nested["proposal"],
                "check": accepted_nested["check"],
                "trial_prefix": accepted_nested["trial_prefix"],
                "cache_hit": accepted_nested["cache_hit"],
                "metadata": nested_metadata,
                "pending_actions": accepted_nested.get("pending_actions") or [],
            }
            return result

    payload = _action_payload(
        proof_context=proof_context,
        proposal=repair,
        check=repair_check,
        accepted=False,
        parent_node_id=parent_node_id,
    )
    payload.update(metadata)
    payload["cache_hit"] = cache_hit
    payload["probe_checks_used"] = result["probe_checks"]
    payload["proposed_local_facts"] = _fact_names_from_tactic(repair.tactic_block)
    payload["proposed_local_fact_claims"] = _fact_claims_from_tactic(repair.tactic_block)
    payload["new_local_facts"] = []
    payload["new_local_fact_claims"] = []
    payload["covered_obligations"] = []
    payload["remaining_obligations_after"] = list(node.remaining_obligations)
    payload["probe_full_proof_body"] = repair_trial_prefix
    result["rejected_payloads"].append(payload)
    return result


def _final_replay_ok(
    *,
    proof_context: ProofContext,
    lean_runner: Any,
    proof_body: str,
) -> bool:
    if not hasattr(lean_runner, "verify_proof"):
        return False
    with tempfile.TemporaryDirectory(prefix="pipeline_final_replay_") as tmp:
        result = lean_runner.verify_proof(
            sample_id=proof_context.sample_id,
            candidate_id=proof_context.candidate_id,
            lean_header=proof_context.lean_header,
            theorem_decl=proof_context.theorem_decl,
            proof_body=proof_body,
            run_dir=Path(tmp),
        )
    if isinstance(result, dict):
        return bool(result.get("strict_pass") or result.get("proof_success"))
    return bool(getattr(result, "strict_pass", False) or getattr(result, "proof_success", False))


def _remaining_after_replay(proof_context: ProofContext, covered: set[str]) -> list[str]:
    blocked_ids = {item.obligation_id for item in proof_context.obligation_replay_blocked if item.obligation_id}
    all_ids = [item.obligation_id for item in proof_context.obligation_replay_items]
    return [item for item in all_ids if item not in covered and item not in blocked_ids]


def _obligation_payloads_by_id(proof_context: ProofContext) -> dict[str, dict[str, Any]]:
    payloads: dict[str, dict[str, Any]] = {}
    for item in [*proof_context.obligation_replay_items, *proof_context.obligation_replay_blocked]:
        if not item.obligation_id:
            continue
        payloads[item.obligation_id] = {
            "obligation_id": item.obligation_id,
            "kind": item.kind,
            "from_hypothesis": item.from_hypothesis,
            "must_use": item.must_use,
            "formal_claim": item.formal_claim,
            "produced_fact_name": item.produced_fact_name,
            "replay_status": item.replay_status,
            "error": item.error,
        }
    return payloads


def _remaining_obligation_payloads(proof_context: ProofContext, obligation_ids: list[str]) -> list[dict[str, Any]]:
    by_id = _obligation_payloads_by_id(proof_context)
    return [dict(by_id.get(oid, {"obligation_id": oid})) for oid in obligation_ids]


def _blocked_obligation_payloads(proof_context: ProofContext) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    by_id = _obligation_payloads_by_id(proof_context)
    for item in proof_context.obligation_replay_blocked:
        if not item.obligation_id:
            continue
        payload = dict(by_id.get(item.obligation_id, {"obligation_id": item.obligation_id}))
        payload["reason"] = payload.get("error") or "obligation_blocked"
        payloads.append(payload)
    return payloads


def _search_mode_for_node(node: ProofSearchNode) -> str:
    if node.remaining_obligations:
        return OBLIGATION_GUIDED_SEARCH
    return TARGET_PROOF_FROM_AVAILABLE_FACTS


def _allowed_decls_for_prompt_summary(
    proof_context: ProofContext,
    remaining_obligations: list[dict[str, Any]],
    *,
    include_decl_candidates: bool = False,
) -> list[str]:
    required = list(
        dict.fromkeys(
            str(row.get("must_use") or "").strip()
            for row in remaining_obligations
            if str(row.get("must_use") or "").strip()
        )
    )
    if required:
        allowed = set(proof_context.allowed_verified_decls)
        required_allowed = [decl for decl in required if decl in allowed]
        if include_decl_candidates:
            extras = [decl for decl in proof_context.allowed_verified_decls if decl not in set(required_allowed)]
            return [*required_allowed, *extras]
        return required_allowed
    return []


def _score_child(
    *,
    parent: ProofSearchNode,
    proposal: ProofActionProposal,
    check: ProofActionCheckResult,
    repeated: bool,
) -> float:
    score = parent.score
    score += float(proposal.priority or 0.0)
    if proposal.uses_decls:
        score += 0.25
    if check.status == "closed":
        score += 5.0
    elif check.status == "progress":
        score += 0.5
    if repeated:
        score -= 0.5
    score -= min(len(proposal.tactic_block), 1200) / 4000.0
    return score


def _prompt_summary(
    *,
    proof_context: ProofContext,
    node: ProofSearchNode,
    prompt: str,
    llm_call_index: int,
    remaining_obligations: list[dict[str, Any]],
    blocked_obligations: list[dict[str, Any]],
    search_mode: str,
    failed_action_count: int,
    include_decl_candidates: bool = False,
) -> dict[str, Any]:
    return {
        "sample_id": proof_context.sample_id,
        "candidate_id": proof_context.candidate_id,
        "llm_call_index": llm_call_index,
        "node_id": node.node_id,
        "depth": node.depth,
        "prompt_chars": len(prompt),
        "target_excerpt": truncate(str(proof_context.target_formula or ""), 500),
        "active_goals_excerpt": truncate(str(node.goals_excerpt or ""), 800),
        "proof_prefix_excerpt": truncate(node.proof_prefix, 800),
        "local_facts": list(_local_fact_summaries(proof_context, node)[:40]),
        "search_mode": search_mode,
        "remaining_obligations": list(remaining_obligations[:20]),
        "blocked_obligations": list(blocked_obligations[:20]),
        "allowed_decls": list(
            _allowed_decls_for_prompt_summary(
                proof_context,
                remaining_obligations,
                include_decl_candidates=include_decl_candidates,
            )[:40]
        ),
        "decl_candidate_mode": bool(include_decl_candidates),
        "failed_action_count": failed_action_count,
        "prompt_excerpt": truncate(prompt, 1600),
        "omitted_context": [
            "full_retrieval_context",
            "full_problem_ir",
            "full_structured_mechlib_context",
            "full_theorem_corpus",
            "full_previous_proof_attempts",
        ],
    }


def run_llm_guided_search(
    *,
    proof_context: ProofContext,
    lean_runner: Any,
    llm_client: Any,
    cfg: Any,
) -> ProofSearchTrace:
    """Run a conservative MechCopilot-style certified proof search loop.

    This is intentionally a first-pass best-first controller: every candidate action is
    guarded, probed by Lean, and only `progress` / `closed` actions are allowed into the
    proof trace.  The final `closed` prefix is replayed through `verify_proof` before success.
    """
    search_cfg = _search_cfg(cfg)
    setattr(proof_context, "max_action_chars", search_cfg.max_action_chars)
    timeout_s = _resolve_probe_timeout_s(cfg, search_cfg)
    start_time = time.monotonic()

    accepted_actions: list[dict[str, Any]] = []
    rejected_actions: list[dict[str, Any]] = []
    augmentation_checks: list[dict[str, Any]] = []
    covered_obligations: set[str] = set()
    prefix = ""
    local_facts = list(dict.fromkeys([*proof_context.allowed_local_facts, *proof_context.local_hypotheses]))
    local_fact_types = _local_fact_types_from_context(proof_context)
    strategy_prompt_summaries: list[dict[str, Any]] = []
    replay_failure_tags: set[str] = set()
    last_error: str | None = None
    probe_checks = 0
    root_goals_excerpt: str | None = None
    search_stop_reason: str | None = None

    structural_prelude = _structural_prelude_plan(proof_context)
    if structural_prelude is not None:
        if probe_checks >= search_cfg.max_probe_checks:
            search_stop_reason = "max_probe_checks_exhausted"
        else:
            proposal = ProofActionProposal(
                action_id="deterministic_structural_prelude_1",
                strategy="structural_prelude",
                tactic_block=structural_prelude.tactic_block,
                uses_facts=[],
                uses_decls=[],
                expected_effect="enter theorem-level forall/implication binders before proof search",
                source="deterministic",
                priority=1.0,
            )
            prelude_node = ProofSearchNode(
                node_id="structural_prelude_root",
                parent_id=None,
                depth=0,
                proof_prefix=prefix,
                local_facts=list(dict.fromkeys(local_facts)),
                local_fact_types=dict(local_fact_types),
            )
            check, trial_prefix = _probe_action(
                proof_context=proof_context,
                lean_runner=lean_runner,
                node=prelude_node,
                proposal=proposal,
                timeout_s=timeout_s,
            )
            probe_checks += 1
            accepted, check, acceptance_metadata = _acceptance_from_probe(proposal, check)
            payload = _action_payload(
                proof_context=proof_context,
                proposal=proposal,
                check=check,
                accepted=accepted,
                parent_node_id=None,
            )
            payload.update(acceptance_metadata)
            payload["structural_prelude"] = True
            payload["introduced_locals"] = list(structural_prelude.introduced_facts)
            payload["introduced_local_types"] = dict(structural_prelude.introduced_fact_types)
            payload["probe_checks_used"] = probe_checks
            if accepted:
                accepted_actions.append(payload)
                prefix = trial_prefix
                root_goals_excerpt = check.goals_excerpt
                local_facts.extend(structural_prelude.introduced_facts)
                local_fact_types.update(structural_prelude.introduced_fact_types)
                if check.status == "closed":
                    replay_ok = (
                        not search_cfg.final_replay_required
                        or _final_replay_ok(
                            proof_context=proof_context,
                            lean_runner=lean_runner,
                            proof_body=prefix,
                        )
                    )
                    if replay_ok:
                        return ProofSearchTrace(
                            sample_id=proof_context.sample_id,
                            candidate_id=proof_context.candidate_id,
                            nodes_expanded=0,
                            llm_calls=0,
                            probe_checks=probe_checks,
                            accepted_actions=accepted_actions,
                            rejected_actions=rejected_actions,
                            final_proof_body=prefix,
                            search_status="success",
                            failure_reason=None,
                            search_mode=TARGET_PROOF_FROM_AVAILABLE_FACTS,
                            blocked_obligations=_blocked_obligation_payloads(proof_context),
                            search_elapsed_s=round(time.monotonic() - start_time, 3),
                            strategy_prompt_summaries=strategy_prompt_summaries,
                            physical_assumption_augmented=bool(proof_context.added_physical_assumptions),
                            added_physical_assumptions=list(proof_context.added_physical_assumptions),
                            augmentation_checks=augmentation_checks,
                            base_theorem_decl=proof_context.base_theorem_decl,
                            augmented_theorem_decl=proof_context.theorem_decl
                            if proof_context.added_physical_assumptions
                            else None,
                        )
            else:
                rejected_actions.append(payload)
                last_error = check.error_message or check.error_type or check.stderr_excerpt

    if (
        search_stop_reason is None
        and search_cfg.deterministic_obligation_replay_first
        and proof_context.obligation_replay_items
    ):
        replay = run_deterministic_obligation_replay_with_probe(
            context=proof_context,
            lean_runner=lean_runner,
            timeout_s=timeout_s,
            proof_prefix=prefix,
        )
        accepted_actions.extend(replay.trace.accepted_actions)
        rejected_actions.extend(replay.trace.rejected_actions)
        probe_checks += len(replay.trace.accepted_actions) + len(replay.trace.rejected_actions)
        prefix = replay.replay_result.proof_prefix
        if replay.replay_result.action_checks:
            root_goals_excerpt = replay.replay_result.action_checks[-1].goals_excerpt or root_goals_excerpt
        replay_failure_tags = set(replay.replay_result.failure_tags)
        if replay_failure_tags:
            last_error = ";".join(sorted(replay_failure_tags))
        if replay.replay_result.blocked_items:
            proof_context = replace(
                proof_context,
                obligation_replay_blocked=list(
                    {
                        item.obligation_id: item
                        for item in [
                            *proof_context.obligation_replay_blocked,
                            *replay.replay_result.blocked_items,
                        ]
                    }.values()
                ),
            )
        covered_obligations.update(item.obligation_id for item in replay.replay_result.replayed_items)
        for item in replay.replay_result.replayed_items:
            local_facts.append(item.produced_fact_name)
            if item.produced_fact_name and item.formal_claim:
                local_fact_types[item.produced_fact_name] = item.formal_claim

    if search_stop_reason is None:
        (
            prefix,
            root_goals_excerpt,
            local_facts,
            local_fact_types,
            probe_checks,
            instantiation_stop_reason,
        ) = _run_universal_fact_instantiations(
            proof_context=proof_context,
            lean_runner=lean_runner,
            prefix=prefix,
            root_goals_excerpt=root_goals_excerpt,
            local_facts=local_facts,
            local_fact_types=local_fact_types,
            accepted_actions=accepted_actions,
            rejected_actions=rejected_actions,
            probe_checks=probe_checks,
            max_probe_checks=search_cfg.max_probe_checks,
            timeout_s=timeout_s,
        )
        if instantiation_stop_reason:
            search_stop_reason = instantiation_stop_reason

    if search_stop_reason is None:
        proof_context, local_facts, local_fact_types, augmentation_error = (
            _pre_search_physical_positive_augmentation(
                proof_context=proof_context,
                lean_runner=lean_runner,
                search_cfg=search_cfg,
                local_facts=local_facts,
                local_fact_types=local_fact_types,
                augmentation_checks=augmentation_checks,
            )
        )
        if augmentation_error:
            last_error = augmentation_error

    root = ProofSearchNode(
        node_id="root",
        parent_id=None,
        depth=0,
        proof_prefix=prefix,
        local_facts=list(dict.fromkeys(local_facts)),
        local_fact_claims=[],
        local_fact_types=dict(local_fact_types),
        remaining_obligations=_remaining_after_replay(proof_context, covered_obligations),
        goals_excerpt=root_goals_excerpt,
        side_condition_denominators=[],
        score=0.0,
    )
    blocked_obligations = _blocked_obligation_payloads(proof_context)
    last_search_mode = _search_mode_for_node(root)
    queue: list[ProofSearchNode] = [root]
    nodes_expanded = 0
    llm_calls = 0
    seen_action_blocks: set[str] = set()
    failed_action_shapes: set[str] = set()
    controller = LLMStrategyController()
    probe_cache: dict[str, ProofActionCheckResult] = {}
    seen_probe_prefixes: set[str] = set()
    no_progress_nodes = 0
    if probe_checks >= search_cfg.max_probe_checks:
        search_stop_reason = "max_probe_checks_exhausted"

    while queue and nodes_expanded < search_cfg.max_nodes and search_stop_reason is None:
        if _wall_clock_exhausted(start_time, search_cfg.max_wall_clock_s_per_sample):
            search_stop_reason = "wall_clock_budget_exhausted"
            break
        node = queue.pop(0)
        nodes_expanded += 1
        node_made_progress = False
        if node.depth > search_cfg.max_depth:
            continue

        current_search_mode = _search_mode_for_node(node)
        last_search_mode = current_search_mode
        plan_remainders: dict[str, list[ProofActionProposal]] = {}
        deterministic_proposals: list[ProofActionProposal] = []
        if node.planned_actions:
            deterministic_proposals.append(node.planned_actions[0])
            plan_remainders[node.planned_actions[0].action_id] = list(node.planned_actions[1:])
        else:
            component_close = _component_close_proposal(proof_context, node)
            if component_close is not None:
                deterministic_proposals.append(component_close)
            else:
                equation_chain = _equation_chain_synthesis_proposal(proof_context, node)
                if equation_chain is not None:
                    deterministic_proposals.append(equation_chain)
                else:
                    sqrt_direct = _sqrt_square_solve_proposal(proof_context, node)
                    if sqrt_direct is not None:
                        deterministic_proposals.append(sqrt_direct)
                    else:
                        log_exp = _log_exp_solve_proposal(proof_context, node)
                        if log_exp is not None:
                            deterministic_proposals.append(log_exp)
                        else:
                            capstan_ratio = _capstan_mass_ratio_proposal(proof_context, node)
                            if capstan_ratio is not None:
                                deterministic_proposals.append(capstan_ratio)
            if not deterministic_proposals and search_cfg.deterministic_side_conditions_first:
                deterministic_proposals.extend(
                    propose_side_condition_actions(
                        proof_context,
                        [
                            *_local_fact_summaries(proof_context, node),
                            *node.local_fact_claims,
                        ],
                        known_denominators=node.side_condition_denominators,
                    )
                )

        llm_proposals: list[ProofActionProposal] = []
        if not deterministic_proposals and llm_calls < search_cfg.max_llm_calls:
            if _wall_clock_exhausted(start_time, search_cfg.max_wall_clock_s_per_sample):
                search_stop_reason = "wall_clock_budget_exhausted"
                break
            remaining_payload = (
                []
                if current_search_mode == TARGET_PROOF_FROM_AVAILABLE_FACTS
                else _remaining_obligation_payloads(proof_context, node.remaining_obligations)
            )
            failed_slice = rejected_actions[-search_cfg.max_failed_actions_kept :]
            include_decl_candidates = False
            prompt = controller.build_prompt(
                proof_context=proof_context,
                local_facts=_local_fact_summaries(proof_context, node),
                remaining_obligations=remaining_payload,
                blocked_obligations=blocked_obligations,
                proof_prefix_summary=truncate(node.proof_prefix, 1200),
                last_error=last_error,
                failed_actions=failed_slice,
                active_goals=node.goals_excerpt,
                include_decl_candidates=include_decl_candidates,
                search_mode=current_search_mode,
            )
            llm_calls += 1
            strategy_prompt_summaries.append(
                _prompt_summary(
                    proof_context=proof_context,
                    node=node,
                    prompt=prompt,
                    llm_call_index=llm_calls,
                    remaining_obligations=remaining_payload,
                    blocked_obligations=blocked_obligations,
                    search_mode=current_search_mode,
                    failed_action_count=len(failed_slice),
                    include_decl_candidates=include_decl_candidates,
                )
            )
            try:
                llm_proposals, llm_plan_remainders = _parse_llm_action_bundle(
                    _call_llm(llm_client, prompt),
                    call_index=llm_calls,
                    limit=search_cfg.proposals_per_call,
                )
                plan_remainders.update(llm_plan_remainders)
            except Exception as exc:
                last_error = f"llm_strategy_parse_failed: {type(exc).__name__}: {exc}"
                llm_proposals = []

        proposals = [*deterministic_proposals, *llm_proposals]
        for proposal in proposals:
            if _wall_clock_exhausted(start_time, search_cfg.max_wall_clock_s_per_sample):
                search_stop_reason = "wall_clock_budget_exhausted"
                break
            if proposal.strategy in {"missing_side_condition", "missing_side_condition_unavailable"}:
                check = _missing_side_condition_check(proposal)
                payload = _action_payload(
                    proof_context=proof_context,
                    proposal=proposal,
                    check=check,
                    accepted=False,
                    parent_node_id=node.node_id,
                )
                rejected_actions.append(payload)
                last_error = check.error_message
                continue

            if _llm_conjunction_close_disallowed(proof_context, proposal):
                component_close = _component_close_proposal(proof_context, node)
                if component_close is None:
                    missing_components = _missing_target_component_claims(proof_context, node)
                    check = _invalid_probe_check(
                        proposal=proposal,
                        error_type="target_component_facts_missing",
                        error_message=(
                            "manual LLM conjunction close is disabled; missing component facts: "
                            + "; ".join(missing_components[:6])
                        ),
                        goals_excerpt=node.goals_excerpt,
                    )
                    payload = _action_payload(
                        proof_context=proof_context,
                        proposal=proposal,
                        check=check,
                        accepted=False,
                        parent_node_id=node.node_id,
                    )
                    payload["missing_target_components"] = list(missing_components)
                    payload["action_shape"] = _action_shape(proposal)
                    rejected_actions.append(payload)
                    failed_action_shapes.add(_failed_action_shape_key(node, proposal))
                    last_error = check.error_message
                    continue
                proposal = replace(
                    component_close,
                    action_id=f"{proposal.action_id}_deterministic_component_close",
                    expected_effect=(
                        "replace LLM conjunction close with deterministic target-component exact"
                    ),
                )

            proposal, function_value_application_repaired = _repair_proposal_function_value_applications(
                proposal,
                proof_context=proof_context,
                node=node,
            )
            shape_key = _failed_action_shape_key(node, proposal)
            if proposal.source == "llm" and _branching_constructor_disallowed(proposal):
                check = _invalid_probe_check(
                    proposal=proposal,
                    error_type="branching_constructor_disallowed_linear_prefix",
                    error_message="linear prefix search cannot safely replay constructor/split_conjunction actions",
                    goals_excerpt=node.goals_excerpt,
                )
                payload = _action_payload(
                    proof_context=proof_context,
                    proposal=proposal,
                    check=check,
                    accepted=False,
                    parent_node_id=node.node_id,
                )
                payload["action_shape"] = _action_shape(proposal)
                payload["function_value_application_repaired"] = function_value_application_repaired
                rejected_actions.append(payload)
                failed_action_shapes.add(shape_key)
                last_error = check.error_message
                continue

            if proposal.source == "llm" and shape_key in failed_action_shapes:
                check = _invalid_probe_check(
                    proposal=proposal,
                    error_type="repeated_failed_action_shape",
                    error_message="same action shape already failed at this proof prefix",
                    goals_excerpt=node.goals_excerpt,
                )
                payload = _action_payload(
                    proof_context=proof_context,
                    proposal=proposal,
                    check=check,
                    accepted=False,
                    parent_node_id=node.node_id,
                )
                payload["action_shape"] = _action_shape(proposal)
                payload["cache_hit"] = True
                payload["function_value_application_repaired"] = function_value_application_repaired
                rejected_actions.append(payload)
                last_error = check.error_message
                continue

            dynamic_context = replace(
                proof_context,
                allowed_verified_decls=[]
                if current_search_mode == TARGET_PROOF_FROM_AVAILABLE_FACTS
                else list(proof_context.allowed_verified_decls),
                allowed_local_facts=list(dict.fromkeys([*proof_context.allowed_local_facts, *node.local_facts])),
                local_hypotheses=list(dict.fromkeys([*proof_context.local_hypotheses, *node.local_facts])),
            )
            setattr(dynamic_context, "max_action_chars", search_cfg.max_action_chars)
            ok, reasons = validate_action_proposal(proposal, dynamic_context)
            if not ok:
                check = _guard_rejection(proposal, reasons)
                rejected_actions.append(
                    _action_payload(
                        proof_context=proof_context,
                        proposal=proposal,
                        check=check,
                        accepted=False,
                        parent_node_id=node.node_id,
                    )
                )
                if proposal.source == "llm":
                    failed_action_shapes.add(shape_key)
                last_error = check.error_message
                continue

            repeated = proposal.tactic_block in seen_action_blocks
            seen_action_blocks.add(proposal.tactic_block)
            plan_remainder_after_action = list(plan_remainders.get(proposal.action_id, []))
            trial_prefix = _append_tactic(node.proof_prefix, proposal.tactic_block)
            if trial_prefix in seen_probe_prefixes:
                check = _invalid_probe_check(
                    proposal=proposal,
                    error_type="duplicate_probe_prefix",
                    error_message="exact proof prefix already checked in this search",
                    goals_excerpt=node.goals_excerpt,
                )
                payload = _action_payload(
                    proof_context=proof_context,
                    proposal=proposal,
                    check=check,
                    accepted=False,
                    parent_node_id=node.node_id,
                )
                payload["cache_hit"] = True
                rejected_actions.append(payload)
                if proposal.source == "llm":
                    failed_action_shapes.add(shape_key)
                last_error = check.error_message
                continue
            if probe_checks >= search_cfg.max_probe_checks:
                search_stop_reason = "max_probe_checks_exhausted"
                break
            probe_key = _probe_cache_key(proof_context, trial_prefix)
            if probe_key in probe_cache:
                check = _cached_probe_check(proposal=proposal, cached=probe_cache[probe_key])
                cache_hit = True
            else:
                check, trial_prefix = _probe_action(
                    proof_context=proof_context,
                    lean_runner=lean_runner,
                    node=node,
                    proposal=proposal,
                    timeout_s=timeout_s,
                    trial_prefix=trial_prefix,
                )
                probe_checks += 1
                probe_cache[probe_key] = replace(check)
                cache_hit = False
            seen_probe_prefixes.add(trial_prefix)
            accepted, check, acceptance_metadata = _acceptance_from_probe(proposal, check)
            proposed_fact_names = _fact_names_from_tactic(proposal.tactic_block)
            proposed_fact_claims = _fact_claims_from_tactic(proposal.tactic_block)
            new_fact_names = list(proposed_fact_names) if accepted else []
            new_fact_claims = list(proposed_fact_claims) if accepted else []
            covered_now = (
                _covered_obligation_ids_from_action(
                    proof_context=proof_context,
                    remaining_obligations=node.remaining_obligations,
                    proposal=proposal,
                    new_fact_names=new_fact_names,
                )
                if accepted
                else []
            )
            remaining_after_action = [oid for oid in node.remaining_obligations if oid not in set(covered_now)]
            side_condition_denominator = _side_condition_denominator_from_action(proposal)
            payload = _action_payload(
                proof_context=proof_context,
                proposal=proposal,
                check=check,
                accepted=accepted,
                parent_node_id=node.node_id,
            )
            payload.update(acceptance_metadata)
            payload["cache_hit"] = cache_hit
            payload["probe_checks_used"] = probe_checks
            payload["proposed_local_facts"] = list(proposed_fact_names)
            payload["proposed_local_fact_claims"] = list(proposed_fact_claims)
            payload["new_local_facts"] = list(new_fact_names)
            payload["new_local_fact_claims"] = list(new_fact_claims)
            payload["covered_obligations"] = list(covered_now)
            payload["remaining_obligations_after"] = list(remaining_after_action)
            payload["side_condition_denominator"] = side_condition_denominator
            payload["function_value_application_repaired"] = function_value_application_repaired
            if not accepted:
                repair_result = _attempt_tactic_no_goals_repairs(
                    proof_context=proof_context,
                    lean_runner=lean_runner,
                    node=node,
                    proposal=proposal,
                    original_check=check,
                    dynamic_context=dynamic_context,
                    timeout_s=timeout_s,
                    probe_cache=probe_cache,
                    seen_probe_prefixes=seen_probe_prefixes,
                    seen_action_blocks=seen_action_blocks,
                    probe_checks=probe_checks,
                    max_probe_checks=search_cfg.max_probe_checks,
                    parent_node_id=node.node_id,
                )
                probe_checks = int(repair_result["probe_checks"])
                if repair_result.get("stop_reason"):
                    search_stop_reason = str(repair_result["stop_reason"])
                attempted_repair_ids = list(repair_result.get("attempted_action_ids") or [])
                if attempted_repair_ids:
                    payload["repair_attempted"] = True
                    payload["repair_action_ids"] = attempted_repair_ids
                    payload["repair_strategy"] = "drop_trailing_tactics_on_no_goals"
                accepted_repair = repair_result.get("accepted")
                if accepted_repair:
                    payload["repair_accepted_action_id"] = accepted_repair["proposal"].action_id
                    payload.setdefault("probe_full_proof_body", trial_prefix)
                    rejected_actions.append(payload)
                    rejected_actions.extend(repair_result.get("rejected_payloads") or [])
                    repair_pending_actions = list(accepted_repair.get("pending_actions") or [])
                    plan_remainder_after_action = [*repair_pending_actions, *plan_remainder_after_action]
                    proposal = accepted_repair["proposal"]
                    check = accepted_repair["check"]
                    trial_prefix = accepted_repair["trial_prefix"]
                    cache_hit = bool(accepted_repair["cache_hit"])
                    accepted = True
                    proposed_fact_names = _fact_names_from_tactic(proposal.tactic_block)
                    proposed_fact_claims = _fact_claims_from_tactic(proposal.tactic_block)
                    new_fact_names = list(proposed_fact_names)
                    new_fact_claims = list(proposed_fact_claims)
                    covered_now = _covered_obligation_ids_from_action(
                        proof_context=proof_context,
                        remaining_obligations=node.remaining_obligations,
                        proposal=proposal,
                        new_fact_names=new_fact_names,
                    )
                    remaining_after_action = [
                        oid for oid in node.remaining_obligations if oid not in set(covered_now)
                    ]
                    side_condition_denominator = _side_condition_denominator_from_action(proposal)
                    payload = _action_payload(
                        proof_context=proof_context,
                        proposal=proposal,
                        check=check,
                        accepted=True,
                        parent_node_id=node.node_id,
                    )
                    payload.update(accepted_repair.get("metadata") or {})
                    payload["repair_of"] = accepted_repair["proposal"].action_id.rsplit(
                        "_repair_no_goals_", 1
                    )[0]
                    payload["cache_hit"] = cache_hit
                    payload["probe_checks_used"] = probe_checks
                    payload["proposed_local_facts"] = list(proposed_fact_names)
                    payload["proposed_local_fact_claims"] = list(proposed_fact_claims)
                    payload["new_local_facts"] = list(new_fact_names)
                    payload["new_local_fact_claims"] = list(new_fact_claims)
                    payload["covered_obligations"] = list(covered_now)
                    payload["remaining_obligations_after"] = list(remaining_after_action)
                    payload["side_condition_denominator"] = side_condition_denominator
                    payload["repair_replanned_from_prefix"] = True
                else:
                    deterministic_repair_result = _attempt_deterministic_action_repairs(
                        proof_context=proof_context,
                        lean_runner=lean_runner,
                        node=node,
                        proposal=proposal,
                        original_check=check,
                        dynamic_context=dynamic_context,
                        timeout_s=timeout_s,
                        probe_cache=probe_cache,
                        seen_probe_prefixes=seen_probe_prefixes,
                        seen_action_blocks=seen_action_blocks,
                        probe_checks=probe_checks,
                        max_probe_checks=search_cfg.max_probe_checks,
                        parent_node_id=node.node_id,
                    )
                    probe_checks = int(deterministic_repair_result.get("probe_checks", probe_checks))
                    if deterministic_repair_result.get("stop_reason"):
                        search_stop_reason = str(deterministic_repair_result["stop_reason"])
                    attempted_deterministic_repair_ids = list(
                        deterministic_repair_result.get("attempted_action_ids") or []
                    )
                    if attempted_deterministic_repair_ids:
                        payload["deterministic_repair_attempted"] = True
                        payload["deterministic_repair_action_ids"] = attempted_deterministic_repair_ids
                    accepted_deterministic_repair = deterministic_repair_result.get("accepted")
                    if accepted_deterministic_repair:
                        payload["deterministic_repair_accepted_action_id"] = accepted_deterministic_repair[
                            "proposal"
                        ].action_id
                        payload.setdefault("probe_full_proof_body", trial_prefix)
                        rejected_actions.append(payload)
                        rejected_actions.extend(repair_result.get("rejected_payloads") or [])
                        rejected_actions.extend(deterministic_repair_result.get("rejected_payloads") or [])
                        plan_remainder_after_action = []
                        proposal = accepted_deterministic_repair["proposal"]
                        check = accepted_deterministic_repair["check"]
                        trial_prefix = accepted_deterministic_repair["trial_prefix"]
                        cache_hit = bool(accepted_deterministic_repair["cache_hit"])
                        accepted = True
                        proposed_fact_names = _fact_names_from_tactic(proposal.tactic_block)
                        proposed_fact_claims = _fact_claims_from_tactic(proposal.tactic_block)
                        new_fact_names = list(proposed_fact_names)
                        new_fact_claims = list(proposed_fact_claims)
                        covered_now = _covered_obligation_ids_from_action(
                            proof_context=proof_context,
                            remaining_obligations=node.remaining_obligations,
                            proposal=proposal,
                            new_fact_names=new_fact_names,
                        )
                        remaining_after_action = [
                            oid for oid in node.remaining_obligations if oid not in set(covered_now)
                        ]
                        side_condition_denominator = _side_condition_denominator_from_action(proposal)
                        payload = _action_payload(
                            proof_context=proof_context,
                            proposal=proposal,
                            check=check,
                            accepted=True,
                            parent_node_id=node.node_id,
                        )
                        payload.update(accepted_deterministic_repair.get("metadata") or {})
                        payload["cache_hit"] = cache_hit
                        payload["probe_checks_used"] = probe_checks
                        payload["proposed_local_facts"] = list(proposed_fact_names)
                        payload["proposed_local_fact_claims"] = list(proposed_fact_claims)
                        payload["new_local_facts"] = list(new_fact_names)
                        payload["new_local_fact_claims"] = list(new_fact_claims)
                        payload["covered_obligations"] = list(covered_now)
                        payload["remaining_obligations_after"] = list(remaining_after_action)
                        payload["side_condition_denominator"] = side_condition_denominator
                        payload["repair_replanned_from_prefix"] = True
                        payload["deterministic_repair_of"] = accepted_deterministic_repair[
                            "proposal"
                        ].action_id
                    if accepted:
                        pass
                    elif search_stop_reason is not None:
                        payload.setdefault("probe_full_proof_body", trial_prefix)
                        rejected_actions.append(payload)
                        rejected_actions.extend(repair_result.get("rejected_payloads") or [])
                        rejected_actions.extend(deterministic_repair_result.get("rejected_payloads") or [])
                        break
                    claim_repair_result: dict[str, Any] = {"attempted": False}
                    if (
                        not accepted
                        and search_stop_reason is None
                        and _is_fact_plan_have_action(proposal)
                        and llm_calls < search_cfg.max_llm_calls
                    ):
                        llm_calls += 1
                        claim_repair_result = _attempt_claim_level_llm_repair(
                            proof_context=proof_context,
                            lean_runner=lean_runner,
                            llm_client=llm_client,
                            node=node,
                            proposal=proposal,
                            original_check=check,
                            dynamic_context=dynamic_context,
                            timeout_s=timeout_s,
                            probe_cache=probe_cache,
                            seen_probe_prefixes=seen_probe_prefixes,
                            seen_action_blocks=seen_action_blocks,
                            probe_checks=probe_checks,
                            max_probe_checks=search_cfg.max_probe_checks,
                            parent_node_id=node.node_id,
                            blocked_obligations=blocked_obligations,
                            search_mode=current_search_mode,
                            llm_call_index=llm_calls,
                        )
                        if claim_repair_result.get("prompt_summary"):
                            strategy_prompt_summaries.append(claim_repair_result["prompt_summary"])
                        probe_checks = int(claim_repair_result.get("probe_checks", probe_checks))
                        if claim_repair_result.get("stop_reason"):
                            search_stop_reason = str(claim_repair_result["stop_reason"])
                        if claim_repair_result.get("attempted"):
                            payload["claim_repair_attempted"] = True
                            payload["claim_repair_llm_call_index"] = llm_calls
                            payload["claim_repair_strategy"] = "claim_level_llm_repair"

                    accepted_claim_repair = claim_repair_result.get("accepted")
                    if accepted_claim_repair:
                        payload["claim_repair_accepted_action_id"] = accepted_claim_repair["proposal"].action_id
                        payload.setdefault("probe_full_proof_body", trial_prefix)
                        rejected_actions.append(payload)
                        rejected_actions.extend(repair_result.get("rejected_payloads") or [])
                        rejected_actions.extend(deterministic_repair_result.get("rejected_payloads") or [])
                        rejected_actions.extend(claim_repair_result.get("rejected_payloads") or [])
                        plan_remainder_after_action = []
                        proposal = accepted_claim_repair["proposal"]
                        check = accepted_claim_repair["check"]
                        trial_prefix = accepted_claim_repair["trial_prefix"]
                        cache_hit = bool(accepted_claim_repair["cache_hit"])
                        accepted = True
                        proposed_fact_names = _fact_names_from_tactic(proposal.tactic_block)
                        proposed_fact_claims = _fact_claims_from_tactic(proposal.tactic_block)
                        new_fact_names = list(proposed_fact_names)
                        new_fact_claims = list(proposed_fact_claims)
                        covered_now = _covered_obligation_ids_from_action(
                            proof_context=proof_context,
                            remaining_obligations=node.remaining_obligations,
                            proposal=proposal,
                            new_fact_names=new_fact_names,
                        )
                        remaining_after_action = [
                            oid for oid in node.remaining_obligations if oid not in set(covered_now)
                        ]
                        side_condition_denominator = _side_condition_denominator_from_action(proposal)
                        payload = _action_payload(
                            proof_context=proof_context,
                            proposal=proposal,
                            check=check,
                            accepted=True,
                            parent_node_id=node.node_id,
                        )
                        payload.update(accepted_claim_repair.get("metadata") or {})
                        payload["cache_hit"] = cache_hit
                        payload["probe_checks_used"] = probe_checks
                        payload["proposed_local_facts"] = list(proposed_fact_names)
                        payload["proposed_local_fact_claims"] = list(proposed_fact_claims)
                        payload["new_local_facts"] = list(new_fact_names)
                        payload["new_local_fact_claims"] = list(new_fact_claims)
                        payload["covered_obligations"] = list(covered_now)
                        payload["remaining_obligations_after"] = list(remaining_after_action)
                        payload["side_condition_denominator"] = side_condition_denominator
                        payload["repair_replanned_from_prefix"] = True
                    elif not accepted and (
                        attempted_repair_ids
                        or attempted_deterministic_repair_ids
                        or claim_repair_result.get("attempted")
                    ):
                        payload.setdefault("probe_full_proof_body", trial_prefix)
                        rejected_actions.append(payload)
                        rejected_actions.extend(repair_result.get("rejected_payloads") or [])
                        rejected_actions.extend(deterministic_repair_result.get("rejected_payloads") or [])
                        rejected_actions.extend(claim_repair_result.get("rejected_payloads") or [])
                        if proposal.source == "llm":
                            failed_action_shapes.add(shape_key)
                        last_error = check.error_message or check.error_type or check.stderr_excerpt
                        if search_stop_reason is not None:
                            break
                        continue
            if not accepted:
                payload.setdefault("probe_full_proof_body", trial_prefix)
                rejected_actions.append(payload)
                if proposal.source == "llm":
                    failed_action_shapes.add(shape_key)
                last_error = check.error_message or check.error_type or check.stderr_excerpt
                if (
                    proposal.strategy == "prove_side_condition"
                    and current_search_mode == TARGET_PROOF_FROM_AVAILABLE_FACTS
                    and side_condition_denominator
                    and len(queue) + nodes_expanded < search_cfg.max_nodes
                ):
                    queue.insert(
                        0,
                        ProofSearchNode(
                            node_id=f"node_{nodes_expanded}_{len(rejected_actions)}_side_condition_blocked",
                            parent_id=node.node_id,
                            depth=node.depth + 1,
                            proof_prefix=node.proof_prefix,
                            local_facts=list(node.local_facts),
                            local_fact_claims=list(node.local_fact_claims),
                            local_fact_types=dict(node.local_fact_types),
                            remaining_obligations=list(node.remaining_obligations),
                            goals_excerpt=check.goals_excerpt or node.goals_excerpt,
                            side_condition_denominators=list(
                                dict.fromkeys([*node.side_condition_denominators, side_condition_denominator])
                            ),
                            last_action_id=proposal.action_id,
                            score=node.score - 0.1,
                        ),
                    )
                continue
            if not _meaningful_progress(
                node=node,
                check=check,
                new_fact_names=new_fact_names,
                new_fact_claims=new_fact_claims,
                covered_obligation_ids=covered_now,
                allow_new_fact_alias=bool(payload.get("repair_kind")),
            ):
                no_progress_check = _invalid_probe_check(
                    proposal=proposal,
                    error_type="no_meaningful_progress",
                    error_message="Lean accepted the prefix, but it added no fact, covered no obligation, and left goals unchanged",
                    goals_excerpt=check.goals_excerpt,
                )
                no_progress_payload = _action_payload(
                    proof_context=proof_context,
                    proposal=proposal,
                    check=no_progress_check,
                    accepted=False,
                    parent_node_id=node.node_id,
                )
                no_progress_payload["raw_probe_status"] = check.status
                no_progress_payload["cache_hit"] = cache_hit
                no_progress_payload["probe_checks_used"] = probe_checks
                no_progress_payload["proposed_local_facts"] = list(proposed_fact_names)
                no_progress_payload["proposed_local_fact_claims"] = list(proposed_fact_claims)
                no_progress_payload["new_local_facts"] = []
                no_progress_payload["new_local_fact_claims"] = []
                no_progress_payload["covered_obligations"] = []
                no_progress_payload["remaining_obligations_after"] = list(node.remaining_obligations)
                no_progress_payload["side_condition_denominator"] = side_condition_denominator
                no_progress_payload["probe_full_proof_body"] = trial_prefix
                rejected_actions.append(no_progress_payload)
                if proposal.source == "llm":
                    failed_action_shapes.add(shape_key)
                last_error = no_progress_check.error_message
                continue

            accepted_actions.append(payload)
            node_made_progress = True
            covered_obligations.update(covered_now)
            new_facts = list(dict.fromkeys([*node.local_facts, *new_fact_names]))
            new_fact_claims_all = list(dict.fromkeys([*node.local_fact_claims, *new_fact_claims]))
            new_fact_types = dict(node.local_fact_types)
            new_fact_types.update(_fact_claims_by_name_from_tactic(proposal.tactic_block))
            new_side_condition_denominators = list(node.side_condition_denominators)
            if proposal.strategy == "prove_side_condition" and side_condition_denominator:
                new_side_condition_denominators = list(
                    dict.fromkeys([*new_side_condition_denominators, side_condition_denominator])
                )
            child = ProofSearchNode(
                node_id=f"node_{nodes_expanded}_{len(accepted_actions)}",
                parent_id=node.node_id,
                depth=node.depth + 1,
                proof_prefix=trial_prefix,
                local_facts=new_facts,
                local_fact_claims=new_fact_claims_all,
                local_fact_types=new_fact_types,
                remaining_obligations=remaining_after_action,
                goals_excerpt=check.goals_excerpt,
                side_condition_denominators=new_side_condition_denominators,
                planned_actions=plan_remainder_after_action,
                last_action_id=proposal.action_id,
                score=_score_child(parent=node, proposal=proposal, check=check, repeated=repeated),
            )

            if check.status == "closed":
                if not search_cfg.final_replay_required or _final_replay_ok(
                    proof_context=proof_context,
                    lean_runner=lean_runner,
                    proof_body=trial_prefix,
                ):
                    return ProofSearchTrace(
                        sample_id=proof_context.sample_id,
                        candidate_id=proof_context.candidate_id,
                        nodes_expanded=nodes_expanded,
                        llm_calls=llm_calls,
                        probe_checks=probe_checks,
                        accepted_actions=accepted_actions,
                        rejected_actions=rejected_actions,
                        final_proof_body=trial_prefix,
                        search_status="success",
                        failure_reason=None,
                        search_mode=last_search_mode,
                        blocked_obligations=blocked_obligations,
                        search_elapsed_s=round(time.monotonic() - start_time, 3),
                        strategy_prompt_summaries=strategy_prompt_summaries,
                        physical_assumption_augmented=bool(proof_context.added_physical_assumptions),
                        added_physical_assumptions=list(proof_context.added_physical_assumptions),
                        augmentation_checks=augmentation_checks,
                        base_theorem_decl=proof_context.base_theorem_decl,
                        augmented_theorem_decl=proof_context.theorem_decl
                        if proof_context.added_physical_assumptions
                        else None,
                    )
                replay_check = ProofActionCheckResult(
                    action_id=f"{proposal.action_id}_final_replay",
                    strategy="final_replay",
                    tactic_block=trial_prefix,
                    status="invalid",
                    error_type="final_replay_failed",
                    error_message="probe closed but final verify_proof did not pass",
                    stderr_excerpt=None,
                    goals_excerpt=None,
                )
                rejected_actions.append(
                    _action_payload(
                        proof_context=proof_context,
                        proposal=proposal,
                        check=replay_check,
                        accepted=False,
                        parent_node_id=node.node_id,
                    )
                )
                if proposal.source == "llm":
                    failed_action_shapes.add(shape_key)
                last_error = replay_check.error_message
                continue

            if child.depth <= search_cfg.max_depth and len(queue) + nodes_expanded < search_cfg.max_nodes:
                queue.append(child)
                queue.sort(key=lambda n: n.score, reverse=True)

        if search_stop_reason is not None:
            break
        if node_made_progress:
            no_progress_nodes = 0
        else:
            no_progress_nodes += 1
            if no_progress_nodes >= search_cfg.max_no_progress_nodes:
                search_stop_reason = "max_no_progress_nodes_exhausted"
                break

    if search_stop_reason is not None:
        reason = search_stop_reason
    elif blocked_obligations and last_search_mode == TARGET_PROOF_FROM_AVAILABLE_FACTS and llm_calls > 0:
        reason = "target_proof_failed_after_blocked_obligations"
    elif "missing_proof_friendly_extractor" in replay_failure_tags and llm_calls > 0:
        reason = "proof_action_synthesis_failed_after_preflight"
    elif "missing_proof_friendly_extractor" in replay_failure_tags:
        reason = "missing_proof_friendly_extractor"
    elif nodes_expanded >= search_cfg.max_nodes:
        reason = "max_nodes_exhausted"
    elif llm_calls >= search_cfg.max_llm_calls:
        reason = "max_llm_calls_exhausted"
    elif not queue:
        reason = "search_queue_exhausted"
    else:
        reason = "search_failed"
    return ProofSearchTrace(
        sample_id=proof_context.sample_id,
        candidate_id=proof_context.candidate_id,
        nodes_expanded=nodes_expanded,
        llm_calls=llm_calls,
        probe_checks=probe_checks,
        accepted_actions=accepted_actions,
        rejected_actions=rejected_actions,
        final_proof_body=None,
        search_status="failed",
        failure_reason=truncate(reason, 240),
        search_mode=last_search_mode,
        blocked_obligations=blocked_obligations,
        search_elapsed_s=round(time.monotonic() - start_time, 3),
        strategy_prompt_summaries=strategy_prompt_summaries,
        physical_assumption_augmented=bool(proof_context.added_physical_assumptions),
        added_physical_assumptions=list(proof_context.added_physical_assumptions),
        augmentation_checks=augmentation_checks,
        base_theorem_decl=proof_context.base_theorem_decl,
        augmented_theorem_decl=proof_context.theorem_decl if proof_context.added_physical_assumptions else None,
    )


def trace_to_dict(trace: ProofSearchTrace) -> dict[str, Any]:
    return asdict(trace)
