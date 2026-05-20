from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from mech_pipeline.types import (
    ProofActionCheckResult,
    ProofActionProposal,
    ProofContext,
    ProofObligationReplayItem,
)
from mech_pipeline.utils import normalize_lean_text

REPLAYABLE_OBLIGATION_KINDS = {"law_to_equation", "constraint_to_equation"}
REPLAY_FAILURE_TAGS = {
    "obligation_replay_failed",
    "extractor_decl_mismatch",
    "formal_claim_shape_mismatch",
    "from_hypothesis_missing",
    "from_hypothesis_not_in_theorem",
    "missing_proof_friendly_extractor",
    "non_extractor_decl",
    "extractor_hypothesis_type_mismatch",
    "extractor_requires_additional_premises",
}
EXTRACTOR_PREFLIGHT_FAILURES = {
    "symbol_hallucination",
    "type_mismatch",
    "wrong_api_shape",
    "proof_elaboration_error",
    "namespace_or_import_issue",
}

ActionChecker = Callable[[ProofContext, str, ProofActionProposal], ProofActionCheckResult]


@dataclass
class ObligationReplayResult:
    sample_id: str
    candidate_id: str
    proof_prefix: str = ""
    replay_status: str = "not_started"
    replayed_items: list[ProofObligationReplayItem] = field(default_factory=list)
    blocked_items: list[ProofObligationReplayItem] = field(default_factory=list)
    proposals: list[ProofActionProposal] = field(default_factory=list)
    action_checks: list[ProofActionCheckResult] = field(default_factory=list)
    failure_tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "sample_id": self.sample_id,
            "candidate_id": self.candidate_id,
            "proof_prefix": self.proof_prefix,
            "replay_status": self.replay_status,
            "replayed_items": [item.to_dict() for item in self.replayed_items],
            "blocked_items": [item.to_dict() for item in self.blocked_items],
            "proposals": [proposal.to_dict() for proposal in self.proposals],
            "action_checks": [check.to_dict() for check in self.action_checks],
            "failure_tags": list(self.failure_tags),
        }


def _strip(value: object) -> str:
    return normalize_lean_text(str(value or "")).strip()


def _lean_ident(value: str, fallback: str) -> str:
    raw = _strip(value)
    if re.match(r"^[A-Za-z_][A-Za-z0-9_']*$", raw):
        return raw
    cleaned = re.sub(r"[^A-Za-z0-9_']", "_", raw)
    if cleaned and re.match(r"^[A-Za-z_]", cleaned):
        return cleaned
    return fallback


def _safe_formal_claim(claim: str) -> bool:
    text = _strip(claim)
    if not text:
        return False
    lowered = text.lower()
    blocked_tokens = ("theorem ", "lemma ", "axiom ", "constant ", "opaque ", ":=", " by ", "sorry", "admit")
    return not any(token in lowered for token in blocked_tokens)


def _append_prefix(prefix: str, tactic_block: str) -> str:
    prefix = prefix.rstrip()
    block = tactic_block.rstrip()
    if not prefix:
        return block
    return f"{prefix}\n{block}"


def _default_unchecked_result(proposal: ProofActionProposal) -> ProofActionCheckResult:
    return ProofActionCheckResult(
        action_id=proposal.action_id,
        strategy=proposal.strategy,
        tactic_block=proposal.tactic_block,
        status="invalid",
        error_type="lean_checker_missing",
        error_message="No Lean action checker was provided for obligation replay.",
        goals_excerpt="not_checked_by_lean",
    )


class ProofObligationReplayer:
    """Deterministically replay proof-eligible law/constraint obligations.

    The replayer never invents a law fact from schema metadata. It only uses
    `ProofContext.obligation_replay_items` whose `must_use` declaration is in
    `ProofContext.allowed_verified_decls`.
    """

    def __init__(self, action_checker: ActionChecker | None = None) -> None:
        self.action_checker = action_checker

    def replay(self, context: ProofContext, proof_prefix: str = "") -> ObligationReplayResult:
        prefix = proof_prefix.rstrip()
        result = ObligationReplayResult(
            sample_id=context.sample_id,
            candidate_id=context.candidate_id,
            proof_prefix=prefix,
            replay_status="not_started",
        )

        for blocked in context.obligation_replay_blocked:
            normalized = self._blocked_item(blocked, self._normalize_failure(blocked.error))
            result.blocked_items.append(normalized)
            if normalized.error:
                result.failure_tags.append(normalized.error)

        for item in context.obligation_replay_items:
            validation_error = self._validation_error(item, context)
            if validation_error is not None:
                blocked = self._blocked_item(item, validation_error)
                result.blocked_items.append(blocked)
                result.failure_tags.append(validation_error)
                continue

            accepted = False
            last_error: str | None = None
            for proposal in self._proposals_for_item(item):
                result.proposals.append(proposal)
                trial_prefix = _append_prefix(prefix, proposal.tactic_block)
                check = (
                    self.action_checker(context, trial_prefix, proposal)
                    if self.action_checker is not None
                    else _default_unchecked_result(proposal)
                )
                result.action_checks.append(check)
                if check.status in {"progress", "closed"}:
                    prefix = trial_prefix
                    replayed = ProofObligationReplayItem(
                        obligation_id=item.obligation_id,
                        kind=item.kind,
                        from_hypothesis=item.from_hypothesis,
                        must_use=item.must_use,
                        formal_claim=item.formal_claim,
                        produced_fact_name=item.produced_fact_name,
                        tactic_block=proposal.tactic_block,
                        replay_status="replayed",
                        error=None,
                    )
                    result.replayed_items.append(replayed)
                    accepted = True
                    break
                last_error = check.error_type or check.error_message or "obligation_replay_failed"
                if proposal.strategy == "deterministic_exact_extractor" and self._is_extractor_preflight_failure(check):
                    last_error = "missing_proof_friendly_extractor"
                    break

            if not accepted:
                failure = self._normalize_failure(last_error)
                result.blocked_items.append(self._blocked_item(item, failure))
                result.failure_tags.append(failure)

        result.proof_prefix = prefix
        result.failure_tags = sorted(set(tag for tag in result.failure_tags if tag))
        if result.blocked_items and result.replayed_items:
            result.replay_status = "partial"
        elif result.blocked_items:
            result.replay_status = "blocked"
        elif result.replayed_items:
            result.replay_status = "ok"
        else:
            result.replay_status = "empty"
        return result

    def _validation_error(self, item: ProofObligationReplayItem, context: ProofContext) -> str | None:
        if item.kind not in REPLAYABLE_OBLIGATION_KINDS:
            return "obligation_replay_failed"
        if not _strip(item.from_hypothesis):
            return "from_hypothesis_missing"
        if not _strip(item.must_use):
            return "extractor_decl_mismatch"
        if item.must_use not in set(context.allowed_verified_decls):
            return "extractor_decl_mismatch"
        if not _safe_formal_claim(item.formal_claim):
            return "formal_claim_shape_mismatch"
        if not _strip(item.produced_fact_name):
            return "formal_claim_shape_mismatch"
        return None

    def _proposals_for_item(self, item: ProofObligationReplayItem) -> list[ProofActionProposal]:
        fact_name = _lean_ident(item.produced_fact_name, f"h_{item.obligation_id}")
        claim = _strip(item.formal_claim)
        must_use = _strip(item.must_use)
        hyp = _strip(item.from_hypothesis)
        templates = [
            (
                "deterministic_exact_extractor",
                f"have {fact_name} : {claim} := by\n  exact {must_use} {hyp}",
                "apply verified extractor exactly",
            ),
            (
                "deterministic_simpa_using_extractor",
                f"have {fact_name} : {claim} := by\n  simpa using {must_use} {hyp}",
                "apply verified extractor with simpa cleanup",
            ),
            (
                "deterministic_infer_extractor_claim",
                f"have {fact_name} := {must_use} {hyp}",
                "let Lean infer extractor result type",
            ),
            (
                "deterministic_simpa_decl_using_hypothesis",
                f"have {fact_name} : {claim} := by\n  simpa [{must_use}] using {hyp}",
                "rewrite hypothesis by verified extractor declaration",
            ),
        ]
        return [
            ProofActionProposal(
                action_id=f"{item.obligation_id}_{idx}",
                strategy=strategy,
                tactic_block=block,
                uses_facts=[hyp],
                uses_decls=[must_use],
                expected_effect=effect,
                source="deterministic",
                priority=float(len(templates) - idx + 1),
            )
            for idx, (strategy, block, effect) in enumerate(templates, start=1)
        ]

    def _blocked_item(self, item: ProofObligationReplayItem, error: str) -> ProofObligationReplayItem:
        return ProofObligationReplayItem(
            obligation_id=item.obligation_id,
            kind=item.kind,
            from_hypothesis=item.from_hypothesis,
            must_use=item.must_use,
            formal_claim=item.formal_claim,
            produced_fact_name=item.produced_fact_name,
            tactic_block=item.tactic_block,
            replay_status="blocked",
            error=error,
        )

    def _is_extractor_preflight_failure(self, check: ProofActionCheckResult) -> bool:
        return check.status == "invalid" and (check.error_type in EXTRACTOR_PREFLIGHT_FAILURES)

    def _normalize_failure(self, error: str | None) -> str:
        if error in REPLAY_FAILURE_TAGS:
            return error
        if error in {"missing_verified_extractor_decl", "must_use_not_allowed_verified_decl"}:
            return "extractor_decl_mismatch"
        if error in {"symbol_hallucination", "type_mismatch", "wrong_api_shape", "proof_elaboration_error"}:
            return "missing_proof_friendly_extractor"
        if error == "missing_formal_claim":
            return "formal_claim_shape_mismatch"
        return "obligation_replay_failed"
