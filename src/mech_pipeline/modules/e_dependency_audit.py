from __future__ import annotations

import re
import hashlib

from mech_pipeline.types import ProofContext, ProofDependencyAudit
from mech_pipeline.utils import normalize_lean_text

_SCHEMA_METADATA_RE = re.compile(r"(^|\s)(law|problem|concept)\.", re.IGNORECASE)


def _contains_schema_metadata(proof_body: str) -> bool:
    lowered = proof_body.lower()
    return "schema" in lowered or bool(_SCHEMA_METADATA_RE.search(proof_body))


def _required_decl_items(proof_context: ProofContext) -> list[str]:
    return sorted(
        {
            item.must_use
            for item in proof_context.obligation_replay_items
            if item.must_use and str(item.must_use).strip()
        }
    )


def _required_obligation_ids(proof_context: ProofContext) -> list[str]:
    return [item.obligation_id for item in proof_context.obligation_replay_items if item.obligation_id]


def _contains_lean_identifier(text: str, identifier: str | None) -> bool:
    name = normalize_lean_text(identifier or "").strip()
    if not name:
        return False
    pattern = rf"(?<![A-Za-z0-9_']){re.escape(name)}(?![A-Za-z0-9_'])"
    return bool(re.search(pattern, text))


def _covered_obligation_ids(proof_context: ProofContext, proof_body: str) -> list[str]:
    body = normalize_lean_text(proof_body or "")
    covered: list[str] = []
    for item in proof_context.obligation_replay_items:
        if not _contains_lean_identifier(body, item.produced_fact_name):
            continue
        if item.must_use and not _contains_lean_identifier(body, item.must_use):
            continue
        covered.append(item.obligation_id)
    return covered


def _used_required_decls(required: list[str], proof_body: str) -> list[str]:
    body = normalize_lean_text(proof_body or "")
    return sorted({decl for decl in required if _contains_lean_identifier(body, decl)})


def _uses_gap_law(proof_context: ProofContext, proof_body: str) -> bool:
    body = normalize_lean_text(proof_body or "")
    if proof_context.gap_laws or proof_context.explicit_model_gaps:
        return True
    return "explicit_gap_law" in body or "gap_law" in body


def _hash_decl(value: str | None) -> str | None:
    text = normalize_lean_text(value or "").strip()
    if not text:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def audit_proof_dependencies(
    *,
    proof_context: ProofContext,
    proof_body: str,
    final_replay_pass: bool,
) -> ProofDependencyAudit:
    """Classify whether a checked proof is actually supported by verified MechLib facts."""
    required_decls = _required_decl_items(proof_context)
    required_obligations = _required_obligation_ids(proof_context)
    used_decls = _used_required_decls(required_decls, proof_body)
    covered = _covered_obligation_ids(proof_context, proof_body)
    missing_decls = [decl for decl in required_decls if decl not in set(used_decls)]
    missing_obligations = [oid for oid in required_obligations if oid not in set(covered)]
    schema_metadata_used = _contains_schema_metadata(proof_body or "")
    gap_laws_used = _uses_gap_law(proof_context, proof_body)
    algebra_only = bool(final_replay_pass and required_decls and not used_decls)

    if not final_replay_pass or schema_metadata_used:
        classification = "proof_failed"
    elif gap_laws_used:
        classification = "gap_assisted_success"
    elif required_decls and not used_decls:
        classification = "algebra_only_success"
    elif not missing_decls and not missing_obligations:
        classification = "fully_mechlib_verified"
    elif used_decls or covered:
        classification = "partial_mechlib_verified"
    else:
        classification = "algebra_only_success"

    return ProofDependencyAudit(
        sample_id=proof_context.sample_id,
        candidate_id=proof_context.candidate_id,
        proof_success=bool(final_replay_pass),
        used_verified_decls=used_decls,
        required_verified_decls=required_decls,
        missing_required_decls=missing_decls,
        covered_obligations=covered,
        missing_obligations=missing_obligations,
        gap_assisted=gap_laws_used,
        fully_mechlib_verified=classification == "fully_mechlib_verified",
        classification=classification,
        schema_metadata_in_proof_body=schema_metadata_used,
        algebra_only=classification == "algebra_only_success" or algebra_only,
        gap_laws_used=gap_laws_used,
        physical_assumption_augmented=bool(proof_context.added_physical_assumptions),
        added_assumptions=list(proof_context.added_physical_assumptions),
        base_theorem_decl_hash=_hash_decl(proof_context.base_theorem_decl or proof_context.theorem_decl),
        augmented_theorem_decl_hash=_hash_decl(proof_context.theorem_decl)
        if proof_context.added_physical_assumptions
        else None,
    )
