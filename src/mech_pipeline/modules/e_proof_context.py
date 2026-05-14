from __future__ import annotations

import re
from dataclasses import asdict, is_dataclass
from typing import Any

from mech_pipeline.types import (
    ProofContext,
    ProofObligationReplayItem,
    StatementCandidate,
    TheoremSkeletonCandidate,
)
from mech_pipeline.utils import normalize_lean_text, truncate


def _payload(value: object) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "to_dict"):
        raw = value.to_dict()  # type: ignore[no-any-return, attr-defined]
        return dict(raw) if isinstance(raw, dict) else {}
    if is_dataclass(value):
        return asdict(value)
    return {}


def _payload_list(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [_payload(item) for item in value if _payload(item)]


def _stripped(value: object) -> str:
    return normalize_lean_text(str(value or "")).strip()


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y"}
    return bool(value)


def _unique(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = value.strip()
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _decl_without_body(theorem_decl: str) -> str:
    decl = normalize_lean_text(theorem_decl)
    if ":=" in decl:
        decl = decl.split(":=", 1)[0]
    if decl.rstrip().endswith(" by"):
        decl = decl.rstrip()[:-3]
    return decl.strip()


def _target_formula(theorem_decl: str) -> str | None:
    decl = _decl_without_body(theorem_decl)
    if " : " not in decl:
        return None
    return decl.rsplit(" : ", 1)[1].strip() or None


def _binder_chunks(theorem_decl: str) -> list[str]:
    decl = _decl_without_body(theorem_decl)
    return [chunk.strip() for chunk in re.findall(r"\(([^()]*)\)", decl) if chunk.strip()]


def _binder_names(chunk: str) -> list[str]:
    if ":" not in chunk:
        return []
    names, _type = chunk.split(":", 1)
    return [part.strip() for part in names.split() if part.strip() and part.strip() not in {"_", "{"}]


def _looks_like_hypothesis_name(name: str) -> bool:
    return name.startswith(("h", "given_", "assumption_", "law_", "constraint_"))


def _local_hypotheses_from_decl(theorem_decl: str) -> list[str]:
    names: list[str] = []
    for chunk in _binder_chunks(theorem_decl):
        if ":" not in chunk:
            continue
        binder_names = _binder_names(chunk)
        if any(_looks_like_hypothesis_name(name) for name in binder_names):
            names.extend(binder_names)
    return _unique(names)


def _allowed_verified_decl_from_binding(binding: dict[str, Any]) -> str | None:
    verified_decl = _stripped(binding.get("verified_decl"))
    if not verified_decl:
        return None
    if _stripped(binding.get("binding_status")) != "ok":
        return None
    if _stripped(binding.get("decl_status")) != "verified":
        return None
    if not _as_bool(binding.get("proof_fact_allowed")):
        return None
    if binding.get("callable_by_llm") is False:
        return None
    if binding.get("lean_check_pass") is False:
        return None
    return verified_decl


def _proof_eligible_bindings_by_instance(evidence_bindings: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for binding in evidence_bindings:
        decl = _allowed_verified_decl_from_binding(binding)
        instance_id = _stripped(binding.get("model_instance_id"))
        if decl and instance_id and instance_id not in out:
            out[instance_id] = binding
    return out


def _allowed_verified_decls(
    *,
    evidence_bindings: list[dict[str, Any]],
    proof_obligations: list[dict[str, Any]],
    candidate_verified_decls: list[str],
) -> list[str]:
    decls = [_allowed_verified_decl_from_binding(binding) or "" for binding in evidence_bindings]
    for obligation in proof_obligations:
        if _stripped(obligation.get("binding_status")) != "ok":
            continue
        if not _as_bool(obligation.get("proof_fact_allowed")):
            continue
        for key in ("must_use", "extractor_decl", "verified_decl"):
            decl = _stripped(obligation.get(key))
            if decl:
                decls.append(decl)
    if not evidence_bindings:
        decls.extend(candidate_verified_decls)
    return _unique([decl for decl in decls if decl])


def _model_predicate_by_instance(model_predicate_bindings: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in model_predicate_bindings:
        instance_id = _stripped(row.get("model_instance_id") or row.get("source_model_instance"))
        if instance_id and instance_id not in out:
            out[instance_id] = row
    return out


def _first_required_hypothesis(obligation: dict[str, Any]) -> str | None:
    required = obligation.get("required_hypotheses")
    if isinstance(required, list):
        for item in required:
            value = _stripped(item)
            if value:
                return value
    return None


def _build_replay_items(
    *,
    proof_obligations: list[dict[str, Any]],
    evidence_bindings: list[dict[str, Any]],
    model_predicate_bindings: list[dict[str, Any]],
    allowed_verified_decls: list[str],
) -> tuple[list[ProofObligationReplayItem], list[ProofObligationReplayItem]]:
    allowed = set(allowed_verified_decls)
    binding_by_instance = _proof_eligible_bindings_by_instance(evidence_bindings)
    predicate_by_instance = _model_predicate_by_instance(model_predicate_bindings)
    pending: list[ProofObligationReplayItem] = []
    blocked: list[ProofObligationReplayItem] = []

    for index, obligation in enumerate(proof_obligations, start=1):
        obligation_id = _stripped(obligation.get("obligation_id") or obligation.get("step_id")) or f"po{index}"
        kind = _stripped(obligation.get("kind")) or "proof_obligation"
        source_model_instance = _stripped(obligation.get("source_model_instance"))

        from_hypothesis = (
            _stripped(obligation.get("from_hypothesis"))
            or _stripped(obligation.get("source_hypothesis"))
            or _first_required_hypothesis(obligation)
        )
        if not from_hypothesis and source_model_instance:
            from_hypothesis = _stripped(predicate_by_instance.get(source_model_instance, {}).get("name")) or None

        must_use = (
            _stripped(obligation.get("must_use"))
            or _stripped(obligation.get("extractor_decl"))
            or _stripped(obligation.get("verified_decl"))
        )
        if not must_use and source_model_instance:
            must_use = _stripped(binding_by_instance.get(source_model_instance, {}).get("verified_decl")) or None

        formal_claim = (
            _stripped(obligation.get("formal_claim"))
            or _stripped(obligation.get("expected_claim"))
            or _stripped(obligation.get("claim"))
        )
        produced_fact_name = _stripped(obligation.get("produces")) or f"h_{obligation_id}"

        error: str | None = None
        if not formal_claim:
            error = "missing_formal_claim"
        elif not must_use:
            error = "missing_verified_extractor_decl"
        elif must_use not in allowed:
            error = "must_use_not_allowed_verified_decl"

        item = ProofObligationReplayItem(
            obligation_id=obligation_id,
            kind=kind,
            from_hypothesis=from_hypothesis,
            must_use=must_use,
            formal_claim=formal_claim,
            produced_fact_name=produced_fact_name,
            tactic_block=None,
            replay_status="blocked" if error else "pending",
            error=error,
        )
        if error:
            blocked.append(item)
        else:
            pending.append(item)

    return pending, blocked


def build_proof_context(
    *,
    sample_id: str,
    problem_ir: dict[str, Any],
    selected_candidate: StatementCandidate | TheoremSkeletonCandidate,
    mechlib_context: str | None,
) -> ProofContext:
    theorem_decl = str(selected_candidate.theorem_decl or "")
    evidence_bindings = _payload_list(getattr(selected_candidate, "evidence_bindings", []))
    proof_obligations = _payload_list(getattr(selected_candidate, "proof_obligations", []))
    model_predicate_bindings = _payload_list(getattr(selected_candidate, "model_predicate_bindings", []))
    explicit_model_gaps = _payload_list(getattr(selected_candidate, "explicit_model_gaps", []))
    gap_laws = _payload_list(getattr(selected_candidate, "gap_laws", []))
    hypothesis_provenance = _payload_list(getattr(selected_candidate, "hypothesis_provenance", []))
    typed_binders = _payload_list(getattr(selected_candidate, "typed_binders", []))
    candidate_verified_decls = [
        _stripped(item) for item in getattr(selected_candidate, "verified_decls", []) if _stripped(item)
    ]
    allowed_verified_decls = _allowed_verified_decls(
        evidence_bindings=evidence_bindings,
        proof_obligations=proof_obligations,
        candidate_verified_decls=candidate_verified_decls,
    )
    replay_items, blocked_items = _build_replay_items(
        proof_obligations=proof_obligations,
        evidence_bindings=evidence_bindings,
        model_predicate_bindings=model_predicate_bindings,
        allowed_verified_decls=allowed_verified_decls,
    )

    local_hypotheses = _local_hypotheses_from_decl(theorem_decl)
    for row in hypothesis_provenance:
        name = _stripped(row.get("name"))
        if name and _as_bool(row.get("allowed_in_hypotheses", True)):
            local_hypotheses.append(name)
    for row in model_predicate_bindings:
        name = _stripped(row.get("name"))
        if name:
            local_hypotheses.append(name)

    skeleton_mode = (
        str(getattr(selected_candidate, "generation_mode", "") or "") == "minimal_skeleton"
        or bool(getattr(selected_candidate, "skeleton_mode", False))
        or isinstance(selected_candidate, TheoremSkeletonCandidate)
    )

    return ProofContext(
        sample_id=sample_id,
        candidate_id=selected_candidate.candidate_id,
        theorem_decl=theorem_decl,
        lean_header=selected_candidate.lean_header,
        base_theorem_decl=theorem_decl,
        target_formula=_target_formula(theorem_decl)
        or _stripped((problem_ir or {}).get("target"))
        or None,
        local_binders=_binder_chunks(theorem_decl),
        local_hypotheses=_unique(local_hypotheses),
        typed_binders=typed_binders,
        hypothesis_provenance=hypothesis_provenance,
        proof_obligations=proof_obligations,
        allowed_verified_decls=allowed_verified_decls,
        allowed_local_facts=_unique(local_hypotheses),
        gap_laws=gap_laws,
        model_predicate_bindings=model_predicate_bindings,
        explicit_model_gaps=explicit_model_gaps,
        skeleton_mode=skeleton_mode,
        obligation_replay_items=replay_items,
        obligation_replay_blocked=blocked_items,
        mechlib_context_excerpt=truncate(normalize_lean_text(mechlib_context or ""), 800) if mechlib_context else None,
    )
