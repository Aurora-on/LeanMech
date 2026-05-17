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
from mech_pipeline.modules.e_side_conditions import normalize_side_condition_expression, propose_side_condition_actions
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
_CONSTRUCTOR_LINE_RE = re.compile(r"(?m)^\s*constructor\b")
_SIDE_CONDITION_EXPECTED_RE = re.compile(
    r"(?:prove denominator nonzero:|missing_side_condition: denominator)\s*"
    r"(?P<denom>.*?)(?:\s+requires positivity facts for|$)"
)
_SIDE_CONDITION_CLAIM_RE = re.compile(
    r"^\s*have\s+[A-Za-z_][A-Za-z0-9_']*\s*:\s*(?P<denom>.*?)\s*≠\s*0\s*:=\s*by\b",
    re.MULTILINE,
)
OBLIGATION_GUIDED_SEARCH = "obligation_guided_search"
TARGET_PROOF_FROM_AVAILABLE_FACTS = "target_proof_from_available_facts"
MAX_FACT_PLAN_ACTIONS = 12
MAX_CLAIM_REPAIR_PROMPT_CHARS = 7000


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
    return proposal.strategy == "split_conjunction" or bool(_CONSTRUCTOR_LINE_RE.search(block))


def _action_shape(proposal: ProofActionProposal) -> str:
    block = normalize_lean_text(proposal.tactic_block or "").strip()
    block = _HAVE_NAME_SHAPE_RE.sub(r"\1_\2", block)
    block = re.sub(r"\s+", " ", block)
    return f"{proposal.strategy}:{block}"


def _failed_action_shape_key(node: ProofSearchNode, proposal: ProofActionProposal) -> str:
    prefix_hash = sha256(normalize_lean_text(node.proof_prefix or "").encode("utf-8")).hexdigest()
    return f"{prefix_hash}:{_action_shape(proposal)}"


def _side_condition_denominator_from_action(proposal: ProofActionProposal) -> str | None:
    if proposal.strategy not in {"prove_side_condition", "missing_side_condition"}:
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
            error_line=result.error_line,
            error_col=result.error_col,
            error_snippet=result.error_snippet,
            probe_full_proof_body=result.probe_full_proof_body,
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

        accepted = repair_check.status in {"progress", "closed"}
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

    accepted = repair_check.status in {"progress", "closed"}
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
    else:
        probe_checks = 0

    root = ProofSearchNode(
        node_id="root",
        parent_id=None,
        depth=0,
        proof_prefix=prefix,
        local_facts=list(dict.fromkeys(local_facts)),
        local_fact_claims=[],
        local_fact_types=dict(local_fact_types),
        remaining_obligations=_remaining_after_replay(proof_context, covered_obligations),
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

        current_search_mode = _search_mode_for_node(node)
        last_search_mode = current_search_mode
        plan_remainders: dict[str, list[ProofActionProposal]] = {}
        deterministic_proposals: list[ProofActionProposal] = []
        if node.planned_actions:
            deterministic_proposals.append(node.planned_actions[0])
            plan_remainders[node.planned_actions[0].action_id] = list(node.planned_actions[1:])
        elif search_cfg.deterministic_side_conditions_first:
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
                        new_local_fact_types = dict(node.local_fact_types)
                        for item in proof_context.added_physical_assumptions:
                            name = str(item.get("name") or "").strip()
                            claim = str(item.get("claim") or item.get("proposition") or item.get("type") or "").strip()
                            if name and claim:
                                new_local_fact_types[name] = claim
                        queue.insert(
                            0,
                            ProofSearchNode(
                                node_id=f"node_{nodes_expanded}_{len(accepted_actions)}_phys_pos",
                                parent_id=node.node_id,
                                depth=node.depth + 1,
                                proof_prefix=node.proof_prefix,
                                local_facts=new_local_facts,
                                local_fact_claims=list(node.local_fact_claims),
                                local_fact_types=new_local_fact_types,
                                remaining_obligations=list(node.remaining_obligations),
                                goals_excerpt=node.goals_excerpt,
                                side_condition_denominators=list(node.side_condition_denominators),
                                planned_actions=list(plan_remainders.get(augment_proposal.action_id, [])),
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
            accepted = check.status in {"progress", "closed"}
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
            payload["cache_hit"] = cache_hit
            payload["probe_checks_used"] = probe_checks
            payload["proposed_local_facts"] = list(proposed_fact_names)
            payload["proposed_local_fact_claims"] = list(proposed_fact_claims)
            payload["new_local_facts"] = list(new_fact_names)
            payload["new_local_fact_claims"] = list(new_fact_claims)
            payload["covered_obligations"] = list(covered_now)
            payload["remaining_obligations_after"] = list(remaining_after_action)
            payload["side_condition_denominator"] = side_condition_denominator
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
                    claim_repair_result: dict[str, Any] = {"attempted": False}
                    if (
                        search_stop_reason is None
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
                    elif attempted_repair_ids or claim_repair_result.get("attempted"):
                        payload.setdefault("probe_full_proof_body", trial_prefix)
                        rejected_actions.append(payload)
                        rejected_actions.extend(repair_result.get("rejected_payloads") or [])
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
