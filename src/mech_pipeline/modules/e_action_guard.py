from __future__ import annotations

import re

from mech_pipeline.types import ProofActionProposal, ProofContext
from mech_pipeline.utils import normalize_lean_text

DEFAULT_MAX_ACTION_CHARS = 1200
ALLOWED_TACTIC_HEADS = {
    "have",
    "exact",
    "apply",
    "rw",
    "simp",
    "simp_all",
    "simpa",
    "constructor",
    "field_simp",
    "ring",
    "ring_nf",
    "linarith",
    "nlinarith",
    "norm_num",
    "positivity",
    "aesop",
}
FORBIDDEN_TOKENS = {
    "sorry": "forbidden_sorry",
    "admit": "forbidden_admit",
    "axiom": "forbidden_axiom",
    "set_option": "forbidden_set_option",
}
METADATA_TOKEN_RE = re.compile(r"(^|\s)(law|problem|concept)\.", re.IGNORECASE)


def _line_head(line: str) -> str:
    stripped = line.strip()
    if not stripped:
        return ""
    if stripped in {"by", "·"}:
        return stripped
    return re.split(r"\s|\[|\{|\(", stripped, maxsplit=1)[0]


def _contains_forbidden(text: str) -> list[str]:
    lowered = text.lower()
    tags: list[str] = []
    for token, tag in FORBIDDEN_TOKENS.items():
        if re.search(rf"\b{re.escape(token)}\b", lowered):
            tags.append(tag)
    return tags


def _mechlib_decl_refs(text: str) -> list[str]:
    return sorted(set(re.findall(r"\bMechLib(?:\.[A-Za-z_][A-Za-z0-9_']*)+", text)))


def _looks_like_natural_language(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    head = _line_head(stripped)
    if head in ALLOWED_TACTIC_HEADS or head in {"by", "·"}:
        return False
    if stripped.startswith(("_ =", "|", "<;>", "·")):
        return False
    return True


def validate_action_proposal(
    proposal: ProofActionProposal,
    proof_context: ProofContext,
) -> tuple[bool, list[str]]:
    tactic_block = normalize_lean_text(proposal.tactic_block or "")
    reasons: list[str] = []
    max_action_chars = int(getattr(proof_context, "max_action_chars", DEFAULT_MAX_ACTION_CHARS))

    if not tactic_block.strip():
        reasons.append("empty_tactic_block")
    if len(tactic_block) > max_action_chars:
        reasons.append("action_too_long")

    reasons.extend(_contains_forbidden(tactic_block))

    if re.search(r"^\s*(theorem|lemma|def|instance|class|structure|inductive|import|open)\b", tactic_block, re.MULTILINE):
        reasons.append("modifies_or_extents_environment")
    if re.search(r"^\s*(theorem|lemma)\b", tactic_block, re.MULTILINE):
        reasons.append("modifies_theorem_statement")

    if "?" in tactic_block or re.search(r"\b(todo|placeholder|fill in|by exact \?)\b", tactic_block, re.IGNORECASE):
        reasons.append("placeholder_or_hole")

    for line in tactic_block.splitlines():
        if _looks_like_natural_language(line):
            reasons.append("disallowed_tactic_or_natural_language")
            break

    allowed_decls = set(proof_context.allowed_verified_decls)
    used_decls = set(proposal.uses_decls) | set(_mechlib_decl_refs(tactic_block))
    for decl in sorted(used_decls):
        if decl.startswith("MechLib.") and decl not in allowed_decls:
            reasons.append("unauthorized_mechlib_decl")
            break

    metadata_text = " ".join([tactic_block, *proposal.uses_decls, *proposal.uses_facts])
    if "schema" in metadata_text.lower() or METADATA_TOKEN_RE.search(metadata_text):
        reasons.append("schema_or_metadata_used_as_proof_fact")

    allowed_facts = set(proof_context.allowed_local_facts) | set(proof_context.local_hypotheses)
    for fact in proposal.uses_facts:
        if fact and fact not in allowed_facts:
            reasons.append("unknown_or_unproved_local_fact")
            break

    if re.search(r"\b(assume|intro|introduce|postulate)\b", tactic_block):
        reasons.append("introduces_new_assumption")

    return (not reasons, sorted(set(reasons)))
