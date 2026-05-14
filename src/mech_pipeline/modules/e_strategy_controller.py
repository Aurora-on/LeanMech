from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mech_pipeline.prompting import load_template, render_template
from mech_pipeline.modules.e_algebra_strategy import available_algebra_strategy_cards
from mech_pipeline.types import ProofContext
from mech_pipeline.utils import truncate

STRATEGY_CARDS = [
    "derive_law_equation",
    "derive_model_equation",
    "prove_side_condition",
    "algebra_solve",
    "rewrite_forward",
    "rewrite_backward",
    "simp_normalize",
    "quantity_value_projection",
    "introduce_intermediate_have",
    "close_goal",
]

DEFAULT_STRATEGY_CONTROLLER_PROMPT = """You are a Lean proof strategy controller.

Your task is to propose the next proof action, not a complete proof.

You may use only:
- listed local facts,
- listed proof obligations,
- listed verified declarations,
- listed algebra strategy cards,
- standard tactics: simp, simp_all, rw, have, exact, apply, field_simp, ring_nf, linarith, nlinarith.

Do not:
- introduce new assumptions,
- modify the theorem statement,
- use sorry/admit/axiom,
- use declarations outside whitelist,
- use schema/problem metadata as proof facts.
- do not use constructor or split goals in the linear prefix search; close conjunctions with exact ⟨..., ...⟩ only when all components are already available.
- if a prior extractor preflight failed, do not assume `must_use from_hypothesis` is the only call shape; propose one local action using the listed facts and allowed declaration candidates.

Available strategy cards:
- derive_law_equation
- derive_model_equation
- prove_side_condition
- algebra_solve
- rewrite_forward
- rewrite_backward
- simp_normalize
- quantity_value_projection
- introduce_intermediate_have
- close_goal

Return JSON only:

{"proposals":[{"strategy":"derive_model_equation","tactic_block":"have hT : T.val = m1.val * a.val := by\\n  linarith [hFnet1, h_mi1]","uses_facts":["hFnet1","h_mi1"],"uses_decls":[],"expected_effect":"derive a local equation from checked facts","priority":0.9}]}

Compact proof state:

```json
{{proof_state_json}}
```
"""

MAX_PROMPT_CHARS = 8000
MAX_TARGET_CHARS = 1200
MAX_PREFIX_CHARS = 1200
MAX_ERROR_CHARS = 800
MAX_FACTS = 40
MAX_DECLS = 40
MAX_OBLIGATIONS = 20
MAX_FAILED_ACTIONS = 10
MAX_ITEM_CHARS = 300


def _compact_text(value: object, limit: int = MAX_ITEM_CHARS) -> str:
    return truncate(str(value or "").strip(), limit)


def _compact_list(values: list[Any], *, limit: int, item_chars: int = MAX_ITEM_CHARS) -> list[str]:
    out: list[str] = []
    for item in values[:limit]:
        text = _compact_text(item, item_chars)
        if text:
            out.append(text)
    omitted = len(values) - len(values[:limit])
    if omitted > 0:
        out.append(f"... omitted {omitted} items ...")
    return out


def _compact_obligation(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "obligation_id": _compact_text(row.get("obligation_id"), 120),
        "kind": _compact_text(row.get("kind"), 80),
        "from_hypothesis": _compact_text(row.get("from_hypothesis"), 160),
        "formal_claim": _compact_text(row.get("formal_claim"), 500),
        "produced_fact_name": _compact_text(row.get("produced_fact_name"), 120),
        "must_use": _compact_text(row.get("must_use"), 240),
        "replay_status": _compact_text(row.get("replay_status"), 80),
        "error": _compact_text(row.get("error"), 120),
    }


def _unique(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _relevant_allowed_decls(proof_context: ProofContext, obligations: list[dict[str, Any]]) -> list[str]:
    allowed = set(proof_context.allowed_verified_decls)
    required = _unique(
        [
            str(row.get("must_use") or "").strip()
            for row in obligations
            if str(row.get("must_use") or "").strip()
        ]
    )
    if required:
        return [decl for decl in required if decl in allowed]
    return list(proof_context.allowed_verified_decls)


def _allowed_decl_candidates(proof_context: ProofContext, required_decls: list[str]) -> list[str]:
    required = [decl for decl in required_decls if decl]
    extras = [decl for decl in proof_context.allowed_verified_decls if decl not in set(required)]
    return _unique([*required, *extras])


def _compact_failed_action(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "action_id": _compact_text(row.get("action_id"), 120),
        "strategy": _compact_text(row.get("strategy"), 120),
        "error_type": _compact_text(row.get("error_type"), 120),
        "error_message": _compact_text(row.get("error_message"), 300),
        "stderr_excerpt": _compact_text(row.get("stderr_excerpt"), 400),
    }


def compact_proof_state_payload(
    *,
    proof_context: ProofContext,
    local_facts: list[str] | None = None,
    remaining_obligations: list[dict[str, Any]] | None = None,
    proof_prefix_summary: str | None = None,
    last_error: str | None = None,
    failed_actions: list[dict[str, Any]] | None = None,
    active_goals: str | None = None,
    include_decl_candidates: bool = False,
) -> dict[str, Any]:
    obligations = remaining_obligations
    if obligations is None:
        obligations = [
            {
                "obligation_id": item.obligation_id,
                "kind": item.kind,
                "from_hypothesis": item.from_hypothesis,
                "formal_claim": item.formal_claim,
                "produced_fact_name": item.produced_fact_name,
                "must_use": item.must_use,
                "replay_status": item.replay_status,
                "error": item.error,
            }
            for item in proof_context.obligation_replay_items
        ]
    facts = list(local_facts) if local_facts is not None else list(proof_context.allowed_local_facts)
    compact_obligations = [_compact_obligation(row) for row in obligations[:MAX_OBLIGATIONS]]
    if len(obligations) > MAX_OBLIGATIONS:
        compact_obligations.append({"omitted": len(obligations) - MAX_OBLIGATIONS})
    required_decls = _relevant_allowed_decls(proof_context, compact_obligations)
    allowed_decls = (
        _allowed_decl_candidates(proof_context, required_decls)
        if include_decl_candidates
        else required_decls
    )
    return {
        "target": _compact_text(proof_context.target_formula, MAX_TARGET_CHARS),
        "active_goals": _compact_text(active_goals, MAX_TARGET_CHARS),
        "proof_prefix_summary": _compact_text(proof_prefix_summary, MAX_PREFIX_CHARS),
        "local_facts": _compact_list(facts, limit=MAX_FACTS),
        "remaining_obligations": compact_obligations,
        "required_decls": _compact_list(required_decls, limit=MAX_DECLS, item_chars=240),
        "allowed_decls": _compact_list(allowed_decls, limit=MAX_DECLS, item_chars=240),
        "decl_candidate_mode": bool(include_decl_candidates),
        "available_strategy_cards": list(STRATEGY_CARDS),
        "available_algebra_strategy_cards": available_algebra_strategy_cards(proof_context, facts),
        "last_error": _compact_text(last_error, MAX_ERROR_CHARS),
        "failed_actions": [_compact_failed_action(row) for row in list(failed_actions or [])[:MAX_FAILED_ACTIONS]],
    }


class LLMStrategyController:
    def __init__(self, prompt_path: Path | None = None) -> None:
        self.prompt_template = (
            load_template(prompt_path, DEFAULT_STRATEGY_CONTROLLER_PROMPT)
            if prompt_path is not None
            else DEFAULT_STRATEGY_CONTROLLER_PROMPT
        )

    def build_prompt(
        self,
        *,
        proof_context: ProofContext,
        local_facts: list[str] | None = None,
        remaining_obligations: list[dict[str, Any]] | None = None,
        proof_prefix_summary: str | None = None,
        last_error: str | None = None,
        failed_actions: list[dict[str, Any]] | None = None,
        active_goals: str | None = None,
        include_decl_candidates: bool = False,
    ) -> str:
        payload = compact_proof_state_payload(
            proof_context=proof_context,
            local_facts=local_facts,
            remaining_obligations=remaining_obligations,
            proof_prefix_summary=proof_prefix_summary,
            last_error=last_error,
            failed_actions=failed_actions,
            active_goals=active_goals,
            include_decl_candidates=include_decl_candidates,
        )
        prompt = render_template(
            self.prompt_template,
            {"proof_state_json": json.dumps(payload, ensure_ascii=False, indent=2)},
        )
        if len(prompt) <= MAX_PROMPT_CHARS:
            return prompt
        payload["failed_actions"] = []
        payload["local_facts"] = payload["local_facts"][:20]
        payload["allowed_decls"] = payload["allowed_decls"][:20]
        payload["required_decls"] = payload["required_decls"][:20]
        payload["target"] = _compact_text(payload.get("target"), 700)
        payload["active_goals"] = _compact_text(payload.get("active_goals"), 700)
        payload["proof_prefix_summary"] = _compact_text(payload.get("proof_prefix_summary"), 700)
        prompt = render_template(
            self.prompt_template,
            {"proof_state_json": json.dumps(payload, ensure_ascii=False, indent=2)},
        )
        if len(prompt) <= MAX_PROMPT_CHARS:
            return prompt
        return prompt[: MAX_PROMPT_CHARS - 80] + "\n...TRUNCATED_COMPACT_PROMPT..."
