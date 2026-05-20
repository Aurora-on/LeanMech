from __future__ import annotations

import re
from dataclasses import asdict, dataclass, is_dataclass
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
    depth = 0
    closer_for = {"(": ")", "{": "}", "[": "]"}
    stack: list[str] = []
    for index, char in enumerate(decl):
        if char in closer_for:
            stack.append(closer_for[char])
            depth += 1
            continue
        if stack and char == stack[-1]:
            stack.pop()
            depth = max(0, depth - 1)
            continue
        if char == ":" and depth == 0:
            if index + 1 < len(decl) and decl[index + 1] == "=":
                continue
            return decl[index + 1 :].strip() or None
    return None


def _first_target_text_from_payload(payload: object) -> str | None:
    data = _payload(payload)
    if not data:
        return None
    for key in (
        "lean_formula",
        "formal_formula",
        "target_formula",
        "expected_formula",
        "expected_form",
        "lean",
        "formula",
        "target",
    ):
        value = _stripped(data.get(key))
        if value:
            return value
    for key in ("formal_targets", "target_formulas", "targets", "expected_formulas", "secondary_formulas"):
        values = data.get(key)
        if isinstance(values, list):
            formulas = [_stripped(item) for item in values if _stripped(item)]
            if formulas:
                return " ∧ ".join(formulas)
    return None


def _target_formula_from_candidate_metadata(candidate: object) -> str | None:
    for attr in ("target_spec", "selected_target", "canonical_target"):
        value = getattr(candidate, attr, None)
        target = _first_target_text_from_payload(value)
        if target:
            return target
    return None


def _target_formula_from_problem_ir(problem_ir: dict[str, Any] | None) -> str | None:
    if not isinstance(problem_ir, dict):
        return None
    for key in ("canonical_target", "selected_target", "target_spec", "target", "unknown_target"):
        target = _first_target_text_from_payload(problem_ir.get(key))
        if target:
            return target
    return None


def _binder_chunks(theorem_decl: str) -> list[str]:
    decl = _decl_without_body(theorem_decl)
    return [chunk for _delim, chunk in _binder_chunks_with_delimiters(decl) if chunk.strip()]


def _binder_chunks_with_delimiters(text: str) -> list[tuple[str, str]]:
    chunks: list[tuple[str, str]] = []
    opener_to_closer = {"(": ")", "{": "}"}
    index = 0
    while index < len(text):
        opener = text[index]
        if opener not in opener_to_closer:
            index += 1
            continue
        closer = opener_to_closer[opener]
        depth = 1
        start = index + 1
        index += 1
        while index < len(text) and depth > 0:
            char = text[index]
            if char == opener:
                depth += 1
            elif char == closer:
                depth -= 1
            index += 1
        if depth == 0:
            chunk = text[start : index - 1].strip()
            if chunk:
                chunks.append((opener, chunk))
    return chunks


def _binder_names(chunk: str) -> list[str]:
    if ":" not in chunk:
        return []
    names, _type = chunk.split(":", 1)
    return [part.strip() for part in names.split() if part.strip() and part.strip() not in {"_", "{"}]


def _binder_type(chunk: str) -> str | None:
    if ":" not in chunk:
        return None
    _names, raw_type = chunk.split(":", 1)
    return _stripped(raw_type) or None


def _looks_like_hypothesis_name(name: str) -> bool:
    return name.startswith(("h", "given_", "assumption_", "law_", "constraint_"))


def _looks_like_proposition_type(type_text: str | None, binder_names: list[str]) -> bool:
    text = _stripped(type_text)
    if not text:
        return False
    if any(token in text for token in ("=", "≠", "≤", "≥")) or re.search(r"(?<!-)[<>]", text):
        return True
    if text.startswith(("forall ", "∀")):
        return True
    if any(marker in text for marker in _PREDICATE_PREMISE_MARKERS):
        return True
    if any(_looks_like_hypothesis_name(name) for name in binder_names) and text in {"True", "False"}:
        return True
    if any(_looks_like_hypothesis_name(name) for name in binder_names) and ("->" in text or "→" in text):
        return True
    return False


def _local_hypotheses_from_decl(theorem_decl: str) -> list[str]:
    names: list[str] = []
    for chunk in _binder_chunks(theorem_decl):
        if ":" not in chunk:
            continue
        binder_names = _binder_names(chunk)
        if _looks_like_proposition_type(_binder_type(chunk), binder_names):
            names.extend(binder_names)
    return _unique(names)


def _local_binder_types_from_decl(theorem_decl: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for chunk in _binder_chunks(theorem_decl):
        binder_type = _binder_type(chunk)
        if not binder_type:
            continue
        for name in _binder_names(chunk):
            out[name] = binder_type
    return out


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


def _proof_eligible_binding_groups_by_instance(evidence_bindings: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for binding in evidence_bindings:
        decl = _allowed_verified_decl_from_binding(binding)
        instance_id = _stripped(binding.get("model_instance_id"))
        if decl and instance_id:
            out.setdefault(instance_id, []).append(binding)
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


@dataclass(frozen=True)
class _ReplayDeclCandidate:
    must_use: str | None
    from_hypothesis: str | None
    decl_statement: str | None
    source: str


_PREDICATE_PREMISE_MARKERS = (
    "Law",
    "Relation",
    "Constraint",
    "Balance",
    "Predicate",
    "Residual",
    "Interface",
)

_DATA_TYPE_NAMES = {
    "Real",
    "Nat",
    "Int",
    "Rat",
    "Mass",
    "Force",
    "Acceleration",
    "Velocity",
    "Speed",
    "Length",
    "Time",
    "Torque",
    "MomentOfInertia",
    "AngularAcceleration",
    "AngularVelocity",
    "Momentum",
    "Energy",
    "Power",
    "SpringConstant",
    "Dimensionless",
    "PhysAngle",
}


def _decl_statement_by_decl_and_instance(evidence_bindings: list[dict[str, Any]]) -> dict[tuple[str, str], str]:
    out: dict[tuple[str, str], str] = {}
    for binding in evidence_bindings:
        decl = _stripped(binding.get("verified_decl"))
        instance_id = _stripped(binding.get("model_instance_id"))
        statement = _stripped(binding.get("decl_statement"))
        if decl and instance_id and statement:
            out.setdefault((decl, instance_id), statement)
    return out


def _decl_statement_by_decl(evidence_bindings: list[dict[str, Any]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for binding in evidence_bindings:
        decl = _stripped(binding.get("verified_decl"))
        statement = _stripped(binding.get("decl_statement"))
        if decl and statement:
            out.setdefault(decl, statement)
    return out


def _hypothesis_type_map(
    *,
    theorem_decl: str,
    hypothesis_provenance: list[dict[str, Any]],
    model_predicate_bindings: list[dict[str, Any]],
) -> dict[str, str]:
    out = _local_binder_types_from_decl(theorem_decl)
    for row in hypothesis_provenance:
        name = _stripped(row.get("name"))
        lean = _stripped(row.get("lean"))
        if name and lean:
            out[name] = lean
    for row in model_predicate_bindings:
        name = _stripped(row.get("name"))
        proposition = _stripped(row.get("proposition"))
        if name and proposition:
            out[name] = proposition
    return out


def _statement_binder_rows(statement: str) -> list[tuple[str, list[str], str]]:
    rows: list[tuple[str, list[str], str]] = []
    for delim, chunk in _binder_chunks_with_delimiters(normalize_lean_text(statement)):
        binder_type = _binder_type(chunk)
        if not binder_type:
            continue
        names = [
            name
            for name in _binder_names(chunk)
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_']*", name)
        ]
        if names:
            rows.append((delim, names, binder_type))
    return rows


def _lean_head(text: str) -> str | None:
    value = _stripped(text)
    if not value:
        return None
    if value.startswith(("forall ", "∀")):
        return "forall"
    match = re.match(r"[@]?([A-Za-z_][A-Za-z0-9_'.]*)", value)
    return match.group(1) if match else None


def _short_lean_name(name: str | None) -> str:
    return str(name or "").rsplit(".", 1)[-1]


def _looks_like_proof_premise_type(raw_type: str) -> bool:
    text = _stripped(raw_type)
    if not text:
        return False
    if text.startswith(("forall ", "∀")) or " = " in f" {text} " or "HasDerivAt" in text:
        return True
    head = _short_lean_name(_lean_head(text))
    if not head or head in _DATA_TYPE_NAMES:
        return False
    return head.startswith("Has") or any(marker in head for marker in _PREDICATE_PREMISE_MARKERS)


def _hypothesis_matches_premise(hypothesis_type: str, premise_type: str) -> bool:
    hyp = _stripped(hypothesis_type)
    premise = _stripped(premise_type)
    if not hyp or not premise:
        return False
    if hyp == premise:
        return True
    hyp_head = _lean_head(hyp)
    premise_head = _lean_head(premise)
    if hyp_head and premise_head and _short_lean_name(hyp_head) == _short_lean_name(premise_head):
        return True
    if hyp_head == "forall" and premise_head == "forall":
        return True
    return False


def _validate_replay_decl_candidate(
    candidate: _ReplayDeclCandidate,
    *,
    allowed: set[str],
    hypothesis_types: dict[str, str],
) -> str | None:
    must_use = _stripped(candidate.must_use)
    from_hypothesis = _stripped(candidate.from_hypothesis)
    if not must_use:
        return "missing_verified_extractor_decl"
    if must_use not in allowed:
        return "must_use_not_allowed_verified_decl"
    if not from_hypothesis:
        return "from_hypothesis_missing"
    hypothesis_type = hypothesis_types.get(from_hypothesis)
    if not hypothesis_type:
        return "from_hypothesis_not_in_theorem"
    statement = _stripped(candidate.decl_statement)
    if not statement:
        return "missing_proof_friendly_extractor"

    explicit_rows = [
        (index, names, raw_type)
        for index, (delim, names, raw_type) in enumerate(_statement_binder_rows(statement))
        if delim == "("
    ]
    proof_rows = [
        (index, names, raw_type)
        for index, names, raw_type in explicit_rows
        if _looks_like_proof_premise_type(raw_type)
    ]
    if not proof_rows:
        return "non_extractor_decl"

    matching = [
        (index, names, raw_type)
        for index, names, raw_type in proof_rows
        if _hypothesis_matches_premise(hypothesis_type, raw_type)
    ]
    if not matching:
        return "extractor_hypothesis_type_mismatch"

    match_index = matching[0][0]
    explicit_before = [row for row in explicit_rows if row[0] < match_index]
    proof_after = [row for row in proof_rows if row[0] > match_index]
    if explicit_before or proof_after:
        return "extractor_requires_additional_premises"
    return None


def _dedupe_candidates(candidates: list[_ReplayDeclCandidate]) -> list[_ReplayDeclCandidate]:
    out: list[_ReplayDeclCandidate] = []
    seen: set[tuple[str | None, str | None]] = set()
    for candidate in candidates:
        key = (_stripped(candidate.must_use) or None, _stripped(candidate.from_hypothesis) or None)
        if key in seen:
            continue
        seen.add(key)
        out.append(candidate)
    return out


def _best_replay_decl_candidate(
    candidates: list[_ReplayDeclCandidate],
    *,
    allowed: set[str],
    hypothesis_types: dict[str, str],
) -> tuple[_ReplayDeclCandidate | None, str | None]:
    checked: list[tuple[_ReplayDeclCandidate, str | None]] = [
        (candidate, _validate_replay_decl_candidate(candidate, allowed=allowed, hypothesis_types=hypothesis_types))
        for candidate in _dedupe_candidates(candidates)
    ]
    for candidate, error in checked:
        if error is None:
            return candidate, None
    for candidate, error in checked:
        if candidate.source == "model_predicate":
            return candidate, error
    if checked:
        return checked[0]
    return None, "missing_verified_extractor_decl"


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
    theorem_decl: str,
    proof_obligations: list[dict[str, Any]],
    evidence_bindings: list[dict[str, Any]],
    model_predicate_bindings: list[dict[str, Any]],
    hypothesis_provenance: list[dict[str, Any]],
    allowed_verified_decls: list[str],
) -> tuple[list[ProofObligationReplayItem], list[ProofObligationReplayItem]]:
    allowed = set(allowed_verified_decls)
    binding_by_instance = _proof_eligible_bindings_by_instance(evidence_bindings)
    binding_groups_by_instance = _proof_eligible_binding_groups_by_instance(evidence_bindings)
    predicate_by_instance = _model_predicate_by_instance(model_predicate_bindings)
    statement_by_decl = _decl_statement_by_decl(evidence_bindings)
    statement_by_decl_and_instance = _decl_statement_by_decl_and_instance(evidence_bindings)
    hypothesis_types = _hypothesis_type_map(
        theorem_decl=theorem_decl,
        hypothesis_provenance=hypothesis_provenance,
        model_predicate_bindings=model_predicate_bindings,
    )
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

        raw_must_use = (
            _stripped(obligation.get("must_use"))
            or _stripped(obligation.get("extractor_decl"))
            or _stripped(obligation.get("verified_decl"))
        )
        if not raw_must_use and source_model_instance:
            raw_must_use = _stripped(binding_by_instance.get(source_model_instance, {}).get("verified_decl")) or None

        formal_claim = (
            _stripped(obligation.get("formal_claim"))
            or _stripped(obligation.get("expected_claim"))
            or _stripped(obligation.get("claim"))
        )
        produced_fact_name = _stripped(obligation.get("produces")) or f"h_{obligation_id}"

        model_binding = predicate_by_instance.get(source_model_instance, {}) if source_model_instance else {}
        model_hypothesis = _stripped(model_binding.get("name")) or from_hypothesis
        model_decl = _stripped(model_binding.get("verified_decl"))
        candidates: list[_ReplayDeclCandidate] = []
        if raw_must_use or from_hypothesis:
            candidates.append(
                _ReplayDeclCandidate(
                    must_use=raw_must_use or None,
                    from_hypothesis=from_hypothesis or None,
                    decl_statement=(
                        _stripped(obligation.get("decl_statement"))
                        or statement_by_decl_and_instance.get((raw_must_use, source_model_instance), "")
                        or statement_by_decl.get(raw_must_use, "")
                    )
                    or None,
                    source="obligation",
                )
            )
        if model_binding and (model_decl or model_hypothesis):
            candidates.append(
                _ReplayDeclCandidate(
                    must_use=model_decl or None,
                    from_hypothesis=model_hypothesis or None,
                    decl_statement=(
                        _stripped(model_binding.get("decl_statement"))
                        or statement_by_decl_and_instance.get((model_decl, source_model_instance), "")
                        or statement_by_decl.get(model_decl, "")
                    )
                    or None,
                    source="model_predicate",
                )
            )
        if source_model_instance:
            for binding in binding_groups_by_instance.get(source_model_instance, []):
                decl = _stripped(binding.get("verified_decl"))
                candidates.append(
                    _ReplayDeclCandidate(
                        must_use=decl or None,
                        from_hypothesis=model_hypothesis or from_hypothesis or None,
                        decl_statement=_stripped(binding.get("decl_statement")) or statement_by_decl.get(decl, "") or None,
                        source="evidence_binding",
                    )
                )

        error: str | None = None
        selected_candidate: _ReplayDeclCandidate | None = None
        if not formal_claim:
            error = "missing_formal_claim"
        else:
            selected_candidate, error = _best_replay_decl_candidate(
                candidates,
                allowed=allowed,
                hypothesis_types=hypothesis_types,
            )

        must_use = selected_candidate.must_use if selected_candidate and not error else None
        from_hypothesis = selected_candidate.from_hypothesis if selected_candidate else (from_hypothesis or None)

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
        theorem_decl=theorem_decl,
        proof_obligations=proof_obligations,
        evidence_bindings=evidence_bindings,
        model_predicate_bindings=model_predicate_bindings,
        hypothesis_provenance=hypothesis_provenance,
        allowed_verified_decls=allowed_verified_decls,
    )

    local_hypotheses = _local_hypotheses_from_decl(theorem_decl)

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
        or _target_formula_from_candidate_metadata(selected_candidate)
        or _target_formula_from_problem_ir(problem_ir)
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
