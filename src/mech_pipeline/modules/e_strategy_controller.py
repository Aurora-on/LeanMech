from __future__ import annotations

import json
import re
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
    "equation_chain_synthesis",
    "log_exp_solve",
    "sqrt_square_solve",
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

Use the compact proof state's `search_mode` field.

When `search_mode` is `obligation_guided_search`, you may use only:
- listed local facts,
- listed proof obligations,
- listed verified declarations,
- listed algebra strategy cards,
- standard tactics: intro, intros, rcases, cases, constructor, rfl, simp, simp_all, rw, have, exact, apply, field_simp, ring_nf, linarith, nlinarith.

When `search_mode` is `target_proof_from_available_facts`:
- the required proof obligations are either already handled or blocked by preflight;
- blocked obligations are diagnostic context, not active tasks;
- do not try to use blocked declarations or any unlisted declaration;
- prove the theorem target from available local facts and accepted proof-prefix facts;
- prefer a short target-proof fact plan with algebraic `have` facts plus a final closing tactic.
- prefer equation-chain synthesis when several equations must be combined: propose one
  closed intermediate algebraic `have` at a time, then continue from the updated Lean
  context after that action is accepted.
- if `target_component_status` is present, generate `have` facts only for missing components;
  do not return `constructor`, `rcases`, `split`, `sorry`, or a manual `close` for conjunction targets.
- if `proof_target_classification` is `log_exp_solve`, first derive a log equation using
  `Real.log_exp`; do not try pure `nlinarith` before that.
- if `proof_target_classification` is `sqrt_square_solve`, first use an already available
  matching sqrt formula with `exact`/`simpa`; do not start with `nlinarith`.

Do not:
- assume or postulate new facts; `intro`/`rcases` may only decompose the current Lean goal or an already introduced local fact,
- modify the theorem statement,
- use sorry/admit/axiom,
- use declarations outside whitelist,
- use schema/problem metadata as proof facts.
- do not use top-level constructor or split goals in the linear prefix search; constructor/cases are allowed inside a local `have ... := by` block only when the block closes all generated subgoals.
- if extractor preflight blocked an obligation, do not keep trying that extractor shape.
- for function-valued quantities, write value projections only after function application: if `f : Real -> Quantity`, use `(f t).val`; never write `f.val t`, `f.val(t)`, or `(f.val t).val`.

Available strategy cards:
- derive_law_equation
- derive_model_equation
- prove_side_condition
- equation_chain_synthesis
- log_exp_solve
- sqrt_square_solve
- algebra_solve
- rewrite_forward
- rewrite_backward
- simp_normalize
- quantity_value_projection
- introduce_intermediate_have
- close_goal

Return JSON only. In `obligation_guided_search`, return local proof action proposals:

{"proposals":[{"strategy":"derive_model_equation","tactic_block":"have hT : T.val = m1.val * a.val := by\\n  linarith [hFnet1, h_mi1]","uses_facts":["hFnet1","h_mi1"],"uses_decls":[],"expected_effect":"derive a local equation from checked facts","priority":0.9}]}

In `target_proof_from_available_facts`, prefer a fact plan:

{"fact_plan":[{"name":"hTma","claim":"T.val = m1.val * a.val","from":["hFnet1","h_mi1"],"tactic":"nlinarith [hFnet1, h_mi1]"}],"close":"exact ⟨ha, hTfinal⟩"}

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
        "reason": _compact_text(row.get("reason"), 120),
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


def _top_level_token_index(text: str, token: str) -> int | None:
    if not token:
        return None
    closer_for = {"(": ")", "{": "}", "[": "]"}
    closers = set(closer_for.values())
    stack: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char in closer_for:
            stack.append(closer_for[char])
            index += 1
            continue
        if char in closers and stack and char == stack[-1]:
            stack.pop()
            index += 1
            continue
        if not stack and text.startswith(token, index):
            return index
        index += 1
    return None


def _top_level_split(text: str, token: str) -> tuple[str, str] | None:
    index = _top_level_token_index(text, token)
    if index is None:
        return None
    left = text[:index].strip()
    right = text[index + len(token) :].strip()
    return (left, right) if left and right else None


def _matching_close_index(text: str, open_index: int) -> int | None:
    if open_index >= len(text) or text[open_index] not in "({[":
        return None
    opener = text[open_index]
    closer = {"(": ")", "{": "}", "[": "]"}[opener]
    depth = 1
    for index in range(open_index + 1, len(text)):
        char = text[index]
        if char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return index
    return None


def _strip_outer_parens(text: str) -> str:
    value = str(text or "").strip()
    while value.startswith("(") and value.endswith(")"):
        close_index = _matching_close_index(value, 0)
        if close_index != len(value) - 1:
            break
        value = value[1:-1].strip()
    return value


def _drop_forall_prefix(text: str) -> str:
    value = _strip_outer_parens(text)
    while value.startswith("forall ") or value.startswith("∀"):
        rest = value[len("forall ") :].strip() if value.startswith("forall ") else value[1:].strip()
        comma = _top_level_token_index(rest, ",")
        if comma is None:
            break
        value = rest[comma + 1 :].strip()
    return value


def _drop_implication_prefix(text: str) -> str:
    value = _strip_outer_parens(text)
    while True:
        split = _top_level_split(value, "->") or _top_level_split(value, "→")
        if split is None:
            return value
        _premise, value = split


def _split_top_level_conjunctions(text: str) -> list[str]:
    value = _strip_outer_parens(text)
    split = _top_level_split(value, "∧")
    if split is None:
        return [value] if value else []
    left, right = split
    return _split_top_level_conjunctions(left) + _split_top_level_conjunctions(right)


def _target_components(target: object) -> list[str]:
    text = str(target or "").strip()
    if not text or "∧" not in text:
        return []
    core = _drop_implication_prefix(_drop_forall_prefix(text))
    parts = [part for part in _split_top_level_conjunctions(core) if part]
    return parts if len(parts) > 1 else []


def _normalized_claim_key(text: object) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip())


def _fact_claim_map(local_facts: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for fact in local_facts:
        if ":" not in fact:
            continue
        name, claim = fact.split(":", 1)
        name = name.strip()
        claim = claim.strip()
        if name and claim:
            out.setdefault(_normalized_claim_key(claim), name)
    return out


def _target_component_status(target: object, local_facts: list[str]) -> list[dict[str, str | int | None]]:
    components = _target_components(target)
    if not components:
        return []
    facts = _fact_claim_map(local_facts)
    status: list[dict[str, str | int | None]] = []
    for index, component in enumerate(components, start=1):
        status.append(
            {
                "index": index,
                "claim": component,
                "matched_fact": facts.get(_normalized_claim_key(component)),
            }
        )
    return status


def _proof_target_classification(target: object, local_facts: list[str]) -> str | None:
    target_text = str(target or "")
    if "Real.log" in target_text and any("Real.exp" in str(fact or "") for fact in local_facts):
        return "log_exp_solve"
    if "Real.sqrt" in target_text and any("Real.sqrt" in str(fact or "") for fact in local_facts):
        return "sqrt_square_solve"
    return None


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
    blocked_obligations: list[dict[str, Any]] | None = None,
    proof_prefix_summary: str | None = None,
    last_error: str | None = None,
    failed_actions: list[dict[str, Any]] | None = None,
    active_goals: str | None = None,
    include_decl_candidates: bool = False,
    search_mode: str | None = None,
) -> dict[str, Any]:
    mode = search_mode or "obligation_guided_search"
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
    blocked = blocked_obligations
    if blocked is None:
        blocked = [
            {
                "obligation_id": item.obligation_id,
                "kind": item.kind,
                "from_hypothesis": item.from_hypothesis,
                "formal_claim": item.formal_claim,
                "produced_fact_name": item.produced_fact_name,
                "must_use": item.must_use,
                "replay_status": item.replay_status,
                "error": item.error,
                "reason": item.error,
            }
            for item in proof_context.obligation_replay_blocked
        ]
    facts = list(local_facts) if local_facts is not None else list(proof_context.allowed_local_facts)
    if mode == "target_proof_from_available_facts":
        obligations = []
    compact_obligations = [_compact_obligation(row) for row in obligations[:MAX_OBLIGATIONS]]
    if len(obligations) > MAX_OBLIGATIONS:
        compact_obligations.append({"omitted": len(obligations) - MAX_OBLIGATIONS})
    compact_blocked = [_compact_obligation(row) for row in blocked[:MAX_OBLIGATIONS]]
    if len(blocked) > MAX_OBLIGATIONS:
        compact_blocked.append({"omitted": len(blocked) - MAX_OBLIGATIONS})
    if mode == "target_proof_from_available_facts":
        required_decls: list[str] = []
        allowed_decls: list[str] = []
        strategy_cards = [
            "equation_chain_synthesis",
            "algebra_solve",
            "rewrite_forward",
            "rewrite_backward",
            "simp_normalize",
            "introduce_intermediate_have",
            "close_goal",
        ]
        mode_instruction = (
            "Required proof obligations are not active. Prove the target from available "
            "local facts and accepted proof-prefix facts; do not use blocked declarations. "
            "When equations must be combined, propose one closed intermediate algebraic "
            "have at a time and continue from the updated Lean context."
        )
    else:
        required_decls = _relevant_allowed_decls(proof_context, compact_obligations)
        allowed_decls = (
            _allowed_decl_candidates(proof_context, required_decls)
            if include_decl_candidates
            else required_decls
        )
        strategy_cards = list(STRATEGY_CARDS)
        mode_instruction = "Propose the next Lean-checked action for the active proof obligations."
    component_status = _target_component_status(proof_context.target_formula, facts)
    target_classification = _proof_target_classification(proof_context.target_formula, facts)
    if target_classification == "log_exp_solve" and "log_exp_solve" not in strategy_cards:
        strategy_cards = ["log_exp_solve", *strategy_cards]
    if target_classification == "sqrt_square_solve" and "sqrt_square_solve" not in strategy_cards:
        strategy_cards = ["sqrt_square_solve", *strategy_cards]
    return {
        "search_mode": mode,
        "proof_target_classification": target_classification,
        "mode_instruction": mode_instruction,
        "target": _compact_text(proof_context.target_formula, MAX_TARGET_CHARS),
        "target_components": _compact_list(_target_components(proof_context.target_formula), limit=8, item_chars=400),
        "target_component_status": component_status[:8],
        "missing_target_components": [
            item for item in component_status[:8] if not item.get("matched_fact")
        ],
        "active_goals": _compact_text(active_goals, MAX_TARGET_CHARS),
        "proof_prefix_summary": _compact_text(proof_prefix_summary, MAX_PREFIX_CHARS),
        "local_facts": _compact_list(facts, limit=MAX_FACTS),
        "remaining_obligations": compact_obligations,
        "blocked_obligations": compact_blocked,
        "required_decls": _compact_list(required_decls, limit=MAX_DECLS, item_chars=240),
        "allowed_decls": _compact_list(allowed_decls, limit=MAX_DECLS, item_chars=240),
        "decl_candidate_mode": bool(include_decl_candidates),
        "available_strategy_cards": strategy_cards,
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
        blocked_obligations: list[dict[str, Any]] | None = None,
        proof_prefix_summary: str | None = None,
        last_error: str | None = None,
        failed_actions: list[dict[str, Any]] | None = None,
        active_goals: str | None = None,
        include_decl_candidates: bool = False,
        search_mode: str | None = None,
    ) -> str:
        payload = compact_proof_state_payload(
            proof_context=proof_context,
            local_facts=local_facts,
            remaining_obligations=remaining_obligations,
            blocked_obligations=blocked_obligations,
            proof_prefix_summary=proof_prefix_summary,
            last_error=last_error,
            failed_actions=failed_actions,
            active_goals=active_goals,
            include_decl_candidates=include_decl_candidates,
            search_mode=search_mode,
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
        payload["blocked_obligations"] = payload["blocked_obligations"][:10]
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
