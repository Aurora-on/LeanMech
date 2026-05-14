from __future__ import annotations

import json
import re
import tempfile
import time
from collections.abc import Iterable
from dataclasses import asdict, replace
from hashlib import sha256
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
    covered_obligation_ids: list[str],
) -> bool:
    if check.status == "closed":
        return True
    if any(fact not in node.local_facts for fact in new_fact_names):
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
    timeout_s = _resolve_probe_timeout_s(cfg, search_cfg)
    start_time = time.monotonic()

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
        probe_checks = len(replay.trace.accepted_actions) + len(replay.trace.rejected_actions)
        prefix = replay.replay_result.proof_prefix
        covered_obligations.update(item.obligation_id for item in replay.replay_result.replayed_items)
        for item in replay.replay_result.replayed_items:
            local_facts.append(item.produced_fact_name)
    else:
        probe_checks = 0

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
    probe_cache: dict[str, ProofActionCheckResult] = {}
    seen_probe_prefixes: set[str] = set()
    no_progress_nodes = 0
    search_stop_reason: str | None = None
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

        deterministic_proposals: list[ProofActionProposal] = []
        if search_cfg.deterministic_side_conditions_first:
            deterministic_proposals.extend(propose_side_condition_actions(proof_context, node.local_facts))

        llm_proposals: list[ProofActionProposal] = []
        if llm_calls < search_cfg.max_llm_calls:
            if _wall_clock_exhausted(start_time, search_cfg.max_wall_clock_s_per_sample):
                search_stop_reason = "wall_clock_budget_exhausted"
                break
            remaining_payload = _remaining_obligation_payloads(proof_context, node.remaining_obligations)
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
            if _wall_clock_exhausted(start_time, search_cfg.max_wall_clock_s_per_sample):
                search_stop_reason = "wall_clock_budget_exhausted"
                break
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
                        node_made_progress = True
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
                                goals_excerpt=node.goals_excerpt,
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
            accepted = check.status in {"progress", "closed"}
            new_fact_names = _fact_names_from_tactic(proposal.tactic_block)
            covered_now = _covered_obligation_ids_from_action(
                proof_context=proof_context,
                remaining_obligations=node.remaining_obligations,
                proposal=proposal,
                new_fact_names=new_fact_names,
            )
            remaining_after_action = [oid for oid in node.remaining_obligations if oid not in set(covered_now)]
            payload = _action_payload(
                proof_context=proof_context,
                proposal=proposal,
                check=check,
                accepted=accepted,
                parent_node_id=node.node_id,
            )
            payload["cache_hit"] = cache_hit
            payload["probe_checks_used"] = probe_checks
            payload["new_local_facts"] = list(new_fact_names)
            payload["covered_obligations"] = list(covered_now)
            payload["remaining_obligations_after"] = list(remaining_after_action)
            if not accepted:
                rejected_actions.append(payload)
                last_error = check.error_message or check.error_type or check.stderr_excerpt
                continue
            if not _meaningful_progress(
                node=node,
                check=check,
                new_fact_names=new_fact_names,
                covered_obligation_ids=covered_now,
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
                no_progress_payload["new_local_facts"] = list(new_fact_names)
                no_progress_payload["covered_obligations"] = list(covered_now)
                no_progress_payload["remaining_obligations_after"] = list(remaining_after_action)
                rejected_actions.append(no_progress_payload)
                last_error = no_progress_check.error_message
                continue

            accepted_actions.append(payload)
            node_made_progress = True
            covered_obligations.update(covered_now)
            new_facts = list(dict.fromkeys([*node.local_facts, *new_fact_names]))
            child = ProofSearchNode(
                node_id=f"node_{nodes_expanded}_{len(accepted_actions)}",
                parent_id=node.node_id,
                depth=node.depth + 1,
                proof_prefix=trial_prefix,
                local_facts=new_facts,
                remaining_obligations=remaining_after_action,
                goals_excerpt=check.goals_excerpt,
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
