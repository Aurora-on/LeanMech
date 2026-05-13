from __future__ import annotations

import json
import re
import tempfile
from collections.abc import Iterable
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from mech_pipeline.config import LLMGuidedSearchConfig, PipelineConfig
from mech_pipeline.modules.e_action_guard import validate_action_proposal
from mech_pipeline.modules.e_certified_replay import run_deterministic_obligation_replay_with_probe
from mech_pipeline.modules.e_physical_assumption_augmenter import augment_context_for_missing_side_condition
from mech_pipeline.modules.e_side_conditions import propose_side_condition_actions
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


def _parse_llm_proposals(text: str, *, call_index: int, limit: int) -> list[ProofActionProposal]:
    raw = normalize_lean_text(text).strip()
    if raw.startswith("```"):
        raw = raw.replace("```json", "").replace("```", "").strip()
    payload = json.loads(raw or "{}")
    proposals_raw = payload.get("proposals", [])
    if not isinstance(proposals_raw, list):
        return []
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
                uses_facts=[str(x) for x in item.get("uses_facts", []) if str(x)],
                uses_decls=[str(x) for x in item.get("uses_decls", []) if str(x)],
                expected_effect=item.get("expected_effect"),
                source="llm",
                priority=float(item["priority"]) if item.get("priority") is not None else None,
            )
        )
    return proposals


def _append_tactic(prefix: str, tactic_block: str) -> str:
    parts = [normalize_lean_text(prefix).strip(), normalize_lean_text(tactic_block).strip()]
    return "\n".join(part for part in parts if part)


def _fact_names_from_tactic(tactic_block: str) -> list[str]:
    return [match.group(1) for match in _HAVE_FACT_RE.finditer(tactic_block or "")]


def _action_payload(
    *,
    proof_context: ProofContext,
    proposal: ProofActionProposal,
    check: ProofActionCheckResult,
    accepted: bool,
    parent_node_id: str | None = None,
) -> dict[str, Any]:
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
        **check.to_dict(),
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
    return ProofActionCheckResult(
        action_id=proposal.action_id,
        strategy=proposal.strategy,
        tactic_block=proposal.tactic_block,
        status="invalid",
        error_type="missing_side_condition",
        error_message=proposal.expected_effect,
        stderr_excerpt=proposal.expected_effect,
        goals_excerpt=None,
    )


def _probe_action(
    *,
    proof_context: ProofContext,
    lean_runner: Any,
    node: ProofSearchNode,
    proposal: ProofActionProposal,
    timeout_s: int | None,
) -> tuple[ProofActionCheckResult, str]:
    trial_prefix = _append_tactic(node.proof_prefix, proposal.tactic_block)
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
        ),
        trial_prefix,
    )


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
    all_ids = [item.obligation_id for item in proof_context.obligation_replay_items]
    return [item for item in all_ids if item not in covered]


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
    failed_action_count: int,
) -> dict[str, Any]:
    return {
        "sample_id": proof_context.sample_id,
        "candidate_id": proof_context.candidate_id,
        "llm_call_index": llm_call_index,
        "node_id": node.node_id,
        "depth": node.depth,
        "prompt_chars": len(prompt),
        "target_excerpt": truncate(str(proof_context.target_formula or ""), 500),
        "proof_prefix_excerpt": truncate(node.proof_prefix, 800),
        "local_facts": list(node.local_facts[:40]),
        "remaining_obligations": list(remaining_obligations[:20]),
        "allowed_decls": list(proof_context.allowed_verified_decls[:40]),
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
    timeout_s = getattr(getattr(cfg, "lean", None), "timeout_s", None)
    if timeout_s is not None:
        timeout_s = min(int(timeout_s), 60)

    accepted_actions: list[dict[str, Any]] = []
    rejected_actions: list[dict[str, Any]] = []
    augmentation_checks: list[dict[str, Any]] = []
    covered_obligations: set[str] = set()
    prefix = ""
    local_facts = list(dict.fromkeys([*proof_context.allowed_local_facts, *proof_context.local_hypotheses]))

    if search_cfg.deterministic_obligation_replay_first and proof_context.obligation_replay_items:
        replay = run_deterministic_obligation_replay_with_probe(
            context=proof_context,
            lean_runner=lean_runner,
            timeout_s=timeout_s,
        )
        accepted_actions.extend(replay.trace.accepted_actions)
        rejected_actions.extend(replay.trace.rejected_actions)
        prefix = replay.replay_result.proof_prefix
        covered_obligations.update(item.obligation_id for item in replay.replay_result.replayed_items)
        for item in replay.replay_result.replayed_items:
            local_facts.append(item.produced_fact_name)

    root = ProofSearchNode(
        node_id="root",
        parent_id=None,
        depth=0,
        proof_prefix=prefix,
        local_facts=list(dict.fromkeys(local_facts)),
        remaining_obligations=_remaining_after_replay(proof_context, covered_obligations),
        score=0.0,
    )
    queue: list[ProofSearchNode] = [root]
    nodes_expanded = 0
    llm_calls = 0
    seen_action_blocks: set[str] = set()
    last_error: str | None = None
    controller = LLMStrategyController()
    strategy_prompt_summaries: list[dict[str, Any]] = []

    while queue and nodes_expanded < search_cfg.max_nodes:
        node = queue.pop(0)
        nodes_expanded += 1
        if node.depth > search_cfg.max_depth:
            continue

        deterministic_proposals: list[ProofActionProposal] = []
        if search_cfg.deterministic_side_conditions_first:
            deterministic_proposals.extend(propose_side_condition_actions(proof_context, node.local_facts))

        llm_proposals: list[ProofActionProposal] = []
        if llm_calls < search_cfg.max_llm_calls:
            remaining_payload = [
                {"obligation_id": oid}
                for oid in node.remaining_obligations
            ]
            failed_slice = rejected_actions[-search_cfg.max_failed_actions_kept :]
            prompt = controller.build_prompt(
                proof_context=proof_context,
                local_facts=node.local_facts,
                remaining_obligations=remaining_payload,
                proof_prefix_summary=truncate(node.proof_prefix, 1200),
                last_error=last_error,
                failed_actions=failed_slice,
            )
            llm_calls += 1
            strategy_prompt_summaries.append(
                _prompt_summary(
                    proof_context=proof_context,
                    node=node,
                    prompt=prompt,
                    llm_call_index=llm_calls,
                    remaining_obligations=remaining_payload,
                    failed_action_count=len(failed_slice),
                )
            )
            try:
                llm_proposals = _parse_llm_proposals(
                    _call_llm(llm_client, prompt),
                    call_index=llm_calls,
                    limit=search_cfg.proposals_per_call,
                )
            except Exception as exc:
                last_error = f"llm_strategy_parse_failed: {type(exc).__name__}: {exc}"
                llm_proposals = []

        proposals = [*deterministic_proposals, *llm_proposals]
        for proposal in proposals:
            if proposal.strategy == "missing_side_condition":
                if search_cfg.allow_physical_positive_hypothesis_augmentation:
                    augment_proposal = ProofActionProposal(
                        action_id=f"augment_physical_positive_hypotheses_{nodes_expanded}",
                        strategy="augment_physical_positive_hypotheses",
                        tactic_block="",
                        uses_facts=[],
                        uses_decls=[],
                        expected_effect=proposal.expected_effect,
                        source="deterministic",
                        priority=0.6,
                    )
                    augmentation = augment_context_for_missing_side_condition(
                        context=proof_context,
                        proposal=proposal,
                        positive_types=search_cfg.physical_positive_types,
                        max_added=search_cfg.max_added_positive_hypotheses,
                        lean_runner=lean_runner,
                        require_compile=search_cfg.require_augmented_theorem_compile,
                    )
                    augmentation.check.action_id = augment_proposal.action_id
                    payload = _action_payload(
                        proof_context=proof_context,
                        proposal=augment_proposal,
                        check=augmentation.check,
                        accepted=augmentation.check.status in {"progress", "closed"}
                        and bool(augmentation.context.added_physical_assumptions),
                        parent_node_id=node.node_id,
                    )
                    payload["added_physical_assumptions"] = list(augmentation.context.added_physical_assumptions)
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
                    if bool(payload["accepted"]):
                        proof_context = augmentation.context
                        accepted_actions.append(payload)
                        new_local_facts = list(
                            dict.fromkeys(
                                [
                                    *node.local_facts,
                                    *(item["name"] for item in proof_context.added_physical_assumptions),
                                ]
                            )
                        )
                        queue.insert(
                            0,
                            ProofSearchNode(
                                node_id=f"node_{nodes_expanded}_{len(accepted_actions)}_phys_pos",
                                parent_id=node.node_id,
                                depth=node.depth + 1,
                                proof_prefix=node.proof_prefix,
                                local_facts=new_local_facts,
                                remaining_obligations=list(node.remaining_obligations),
                                last_action_id=augment_proposal.action_id,
                                score=node.score + float(augment_proposal.priority or 0.0),
                            ),
                        )
                        last_error = None
                        break
                    rejected_actions.append(payload)
                    last_error = augmentation.check.error_message or augmentation.check.error_type
                    continue

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

            dynamic_context = replace(
                proof_context,
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
                last_error = check.error_message
                continue

            repeated = proposal.tactic_block in seen_action_blocks
            seen_action_blocks.add(proposal.tactic_block)
            check, trial_prefix = _probe_action(
                proof_context=proof_context,
                lean_runner=lean_runner,
                node=node,
                proposal=proposal,
                timeout_s=timeout_s,
            )
            accepted = check.status in {"progress", "closed"}
            payload = _action_payload(
                proof_context=proof_context,
                proposal=proposal,
                check=check,
                accepted=accepted,
                parent_node_id=node.node_id,
            )
            if not accepted:
                rejected_actions.append(payload)
                last_error = check.error_message or check.error_type or check.stderr_excerpt
                continue

            accepted_actions.append(payload)
            new_facts = list(dict.fromkeys([*node.local_facts, *_fact_names_from_tactic(proposal.tactic_block)]))
            child = ProofSearchNode(
                node_id=f"node_{nodes_expanded}_{len(accepted_actions)}",
                parent_id=node.node_id,
                depth=node.depth + 1,
                proof_prefix=trial_prefix,
                local_facts=new_facts,
                remaining_obligations=list(node.remaining_obligations),
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
                        accepted_actions=accepted_actions,
                        rejected_actions=rejected_actions,
                        final_proof_body=trial_prefix,
                        search_status="success",
                        failure_reason=None,
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
                last_error = replay_check.error_message
                continue

            if child.depth <= search_cfg.max_depth and len(queue) + nodes_expanded < search_cfg.max_nodes:
                queue.append(child)
                queue.sort(key=lambda n: n.score, reverse=True)

    if nodes_expanded >= search_cfg.max_nodes:
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
        accepted_actions=accepted_actions,
        rejected_actions=rejected_actions,
        final_proof_body=None,
        search_status="failed",
        failure_reason=truncate(reason, 240),
        strategy_prompt_summaries=strategy_prompt_summaries,
        physical_assumption_augmented=bool(proof_context.added_physical_assumptions),
        added_physical_assumptions=list(proof_context.added_physical_assumptions),
        augmentation_checks=augmentation_checks,
        base_theorem_decl=proof_context.base_theorem_decl,
        augmented_theorem_decl=proof_context.theorem_decl if proof_context.added_physical_assumptions else None,
    )


def trace_to_dict(trace: ProofSearchTrace) -> dict[str, Any]:
    return asdict(trace)
