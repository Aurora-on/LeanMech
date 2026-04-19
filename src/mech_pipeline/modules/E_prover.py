from __future__ import annotations

import json
from pathlib import Path
import re

from mech_pipeline.adapters.lean_runner import LeanRunner
from mech_pipeline.llm_schemas import ProofPayload, ProofPlanPayload
from mech_pipeline.prompting import load_template, render_template
from mech_pipeline.response_parser import ResponseParseError, parse_json_model
from mech_pipeline.types import GroundingResult, ProofAttemptResult, ProofCheckResult, StatementCandidate
from mech_pipeline.utils import (
    normalize_lean_text,
    sanitize_problem_ir_for_llm,
)

DEFAULT_PLAN_PROMPT = """__TASK_E_PLAN_PROOF__
You are a Lean4 proof planner.
Before writing Lean code, decide which givens and retrieved theorems should structure the proof.

Output JSON only:
{
  "plan":"...",
  "theorems_to_apply":["..."],
  "givens_to_use":["..."],
  "intermediate_claims":["..."],
  "algebraic_cleanup_only": false
}

Rules:
1) Do not output Lean proof code.
2) For mechanics law questions, identify theorem applications first and leave algebra for the final cleanup.
3) Use retrieved MechLib context as theorem/style evidence only when relevant.
4) If the problem is purely algebraic or unit conversion, set `algebraic_cleanup_only=true`.

Theorem:
{{theorem_decl}}

ProblemIR:
{{problem_ir_json}}

Retrieved MechLib context:
{{mechlib_context}}
"""

DEFAULT_GENERATE_PROMPT = """__TASK_E_GENERATE_PROOF__
You are a Lean4 proof generator.
Given a theorem declaration and a theorem-level proof plan, produce a Lean proof body that can pass Lean checking.

Output JSON only:
{"proof_body":"...", "strategy":"...", "plan":"...", "used_facts":["..."]}

Rules:
1) Output only proof body (do not repeat theorem declaration).
2) Never use sorry/admit/axiom.
3) Do not output a bare one-line tactic such as `rfl`, `simp`, `aesop`, `linarith`, or `ring`.
4) Every proof must use the theorem assumptions or derive intermediate facts with `have`, `calc`, `rw`, `constructor`, or `simpa`.
5) Build the proof around the supplied theorem-level plan.
6) For mechanics law questions, establish theorem application first, then do algebraic cleanup.
7) Use retrieved MechLib snippets as references for tactic style and lemma naming only.
8) Do not copy irrelevant lemmas; stay strictly aligned with theorem goal.

Theorem:
{{theorem_decl}}

ProblemIR:
{{problem_ir_json}}

Proof plan:
{{proof_plan_json}}

Retrieved MechLib context:
{{mechlib_context}}
"""

DEFAULT_REPAIR_PROMPT = """__TASK_E_REPAIR_PROOF__
You are a Lean4 proof repair assistant.
Given the theorem-level plan, previous proof, and Lean error, produce a minimally changed fixed proof body.

Output JSON only:
{"proof_body":"...", "strategy":"...", "plan":"...", "used_facts":["..."]}

Rules:
1) Output only proof body (do not repeat theorem declaration).
2) Never use sorry/admit/axiom.
3) Repair should directly address the provided Lean error.
4) Do not output a bare one-line tactic such as `rfl`, `simp`, `aesop`, `linarith`, or `ring`.
5) Prefer small edits over rewriting everything.
6) Use theorem assumptions or explicit intermediate facts; do not replace the proof with a placeholder tactic.
7) Preserve the theorem-level plan unless the Lean error shows that the plan itself is wrong.
8) Use retrieved MechLib snippets as references for tactic style and lemma naming only.

Theorem:
{{theorem_decl}}

ProblemIR:
{{problem_ir_json}}

Proof plan:
{{proof_plan_json}}

Previous proof:
{{previous_proof}}

Previous Lean error:
{{previous_error}}

Retrieved MechLib context:
{{mechlib_context}}
"""

_PROOF_DECIMAL_PATTERN = re.compile(r"(?<![A-Za-z0-9_])-?\d+\.\d+(?![A-Za-z0-9_])")


def _excerpt(text: str, limit: int = 240) -> str | None:
    out = normalize_lean_text(str(text or "").strip())
    return out[:limit] if out else None


def _proof_failure_tags(*values: object) -> list[str]:
    tags: list[str] = []
    seen: set[str] = set()
    for value in values:
        if isinstance(value, str):
            candidates = [value]
        elif isinstance(value, list):
            candidates = [str(item) for item in value]
        else:
            candidates = []
        for item in candidates:
            tag = str(item).strip().lower().replace(" ", "_")
            if not tag or tag in seen:
                continue
            seen.add(tag)
            tags.append(tag)
    return tags


def _context_refs(mechlib_context: str) -> set[str]:
    refs: set[str] = set()
    for pattern in (r"theorem_name=([A-Za-z_][A-Za-z0-9_']*)", r"symbol=([A-Za-z_][A-Za-z0-9_']*)"):
        for match in re.finditer(pattern, mechlib_context or ""):
            refs.add(match.group(1))
    return refs


def _normalize_string_list(value: object) -> list[str]:
    if isinstance(value, str):
        text = normalize_lean_text(value.strip())
        return [text] if text else []
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = normalize_lean_text(str(item or "").strip())
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _plan_grounding_ok(
    *,
    theorem_names: list[str],
    algebraic_cleanup_only: bool,
    grounding: GroundingResult,
    mechlib_context: str,
) -> bool:
    refs = _context_refs(mechlib_context)
    if theorem_names:
        return all(name in refs for name in theorem_names)
    laws = grounding.problem_ir.get("physical_laws") if isinstance(grounding.problem_ir, dict) else None
    has_law_problem = isinstance(laws, list) and bool(laws)
    if has_law_problem and algebraic_cleanup_only:
        return False
    return True


def _classify_proof_sub_error(error_type: str | None, stderr_digest: str, proof_body: str) -> str | None:
    et = str(error_type or "").strip()
    text = str(stderr_digest or "").lower()
    proof_text = str(proof_body or "")
    if et == "proof_generation_failure":
        return "proof_generation_failure"
    if et == "proof_response_parse_failed":
        return "proof_response_parse_failed"
    if et == "proof_skipped_due_to_semantic_fail":
        return "proof_skipped_due_to_semantic_fail"
    if "rewrite tactic failed" in text or "did not find instance of the pattern" in text:
        return "algebraic_rewrite_missing"
    if "unsolved goals" in text:
        return "missing_intermediate_fact"
    if "type mismatch" in text or "application type mismatch" in text:
        return "goal_shape_mismatch"
    if _PROOF_DECIMAL_PATTERN.search(proof_text):
        return "numeric_normalization_needed"
    if et == "proof_search_failure":
        return "wrong_tactic_strategy"
    return None


def _build_proof_failure_summary(error_type: str | None, stderr_digest: str) -> str | None:
    excerpt = _excerpt(stderr_digest)
    if excerpt:
        return excerpt
    et = str(error_type or "").strip()
    if et:
        return et.replace("_", " ")
    return None


class ModuleE:
    def __init__(
        self,
        model_client,
        lean_runner: LeanRunner,
        prompt_plan_path: Path,
        prompt_generate_path: Path,
        prompt_repair_path: Path,
        max_attempts: int,
    ) -> None:
        self.model_client = model_client
        self.lean_runner = lean_runner
        self.prompt_plan = load_template(prompt_plan_path, DEFAULT_PLAN_PROMPT)
        self.prompt_generate = load_template(prompt_generate_path, DEFAULT_GENERATE_PROMPT)
        self.prompt_repair = load_template(prompt_repair_path, DEFAULT_REPAIR_PROMPT)
        self.max_attempts = max_attempts

    def run(
        self,
        grounding: GroundingResult,
        selected_candidate: StatementCandidate | None,
        run_dir: Path,
        mechlib_context: str = "(none)",
    ) -> tuple[list[ProofAttemptResult], ProofCheckResult]:
        if selected_candidate is None:
            return (
                [],
                ProofCheckResult(
                    sample_id=grounding.sample_id,
                    proof_success=False,
                    attempts_used=0,
                    selected_candidate_id=None,
                    error_type="proof_search_failure",
                    final_log_path=None,
                    sub_error_type="proof_generation_failure",
                    failure_tags=["proof_generation_failure"],
                    failure_summary="No selected candidate was available for proof generation.",
                    failure_details={"selected_candidate_present": False},
                ),
            )

        safe_ir = sanitize_problem_ir_for_llm(grounding.problem_ir or {})
        problem_ir_json = json.dumps(safe_ir, ensure_ascii=False, indent=2)
        attempts: list[ProofAttemptResult] = []
        previous_proof = ""
        previous_error = ""
        final_error = "proof_search_failure"
        final_log_path: str | None = None

        proof_plan = ""
        theorems_to_apply: list[str] = []
        givens_to_use: list[str] = []
        intermediate_claims: list[str] = []
        algebraic_cleanup_only = False
        raw_plan = ""

        try:
            raw_plan = self.model_client.generate_text(
                render_template(
                    self.prompt_plan,
                    {
                        "theorem_decl": selected_candidate.theorem_decl,
                        "problem_ir_json": problem_ir_json,
                        "mechlib_context": mechlib_context or "(none)",
                    },
                )
            ).text
        except Exception as exc:
            previous_error = f"{type(exc).__name__}: {exc}"

        if raw_plan:
            try:
                parsed_plan = parse_json_model(raw_plan, ProofPlanPayload)
                proof_plan = normalize_lean_text(str(parsed_plan.plan or "").strip())
                theorems_to_apply = _normalize_string_list(parsed_plan.theorems_to_apply)
                givens_to_use = _normalize_string_list(parsed_plan.givens_to_use)
                intermediate_claims = _normalize_string_list(parsed_plan.intermediate_claims)
                algebraic_cleanup_only = bool(parsed_plan.algebraic_cleanup_only)
            except ResponseParseError:
                previous_error = previous_error or "proof_plan_parse_failed"
        else:
            previous_error = previous_error or "proof_plan_generation_failed"

        if not proof_plan and not theorems_to_apply and not givens_to_use and not intermediate_claims:
            error_type = "proof_response_parse_failed" if raw_plan else "proof_generation_failure"
            stderr_digest = previous_error or error_type
            sub_error_type = _classify_proof_sub_error(error_type, stderr_digest, "")
            attempt = ProofAttemptResult(
                sample_id=grounding.sample_id,
                attempt_index=1,
                proof_body="",
                plan=None,
                parse_ok=False,
                raw_response=raw_plan,
                compile_pass=False,
                strict_pass=False,
                error_type=error_type,
                stderr_digest=stderr_digest,
                log_path=None,
                sub_error_type=sub_error_type,
                failure_tags=_proof_failure_tags(error_type, "proof_plan_parse_failed"),
                failure_summary=_build_proof_failure_summary(error_type, stderr_digest),
                failure_details={
                    "planning_stage": "proof_plan",
                    "previous_error": previous_error or None,
                },
                proof_body_excerpt=None,
                stderr_excerpt=_excerpt(stderr_digest),
                proof_plan=None,
                theorems_to_apply=[],
                givens_to_use=[],
                intermediate_claims=[],
                plan_grounding_ok=None,
            )
            attempts.append(attempt)
            return (
                attempts,
                ProofCheckResult(
                    sample_id=grounding.sample_id,
                    proof_success=False,
                    attempts_used=1,
                    selected_candidate_id=selected_candidate.candidate_id,
                    error_type=attempt.error_type,
                    final_log_path=None,
                    sub_error_type=attempt.sub_error_type,
                    failure_tags=list(attempt.failure_tags),
                    failure_summary=attempt.failure_summary,
                    failure_details={
                        "planning_stage": "proof_plan",
                        "theorems_to_apply": [],
                        "givens_to_use": [],
                        "intermediate_claims": [],
                    },
                ),
            )

        proof_plan_json = json.dumps(
            {
                "plan": proof_plan,
                "theorems_to_apply": theorems_to_apply,
                "givens_to_use": givens_to_use,
                "intermediate_claims": intermediate_claims,
                "algebraic_cleanup_only": algebraic_cleanup_only,
            },
            ensure_ascii=False,
            indent=2,
        )
        plan_grounding_ok = _plan_grounding_ok(
            theorem_names=theorems_to_apply,
            algebraic_cleanup_only=algebraic_cleanup_only,
            grounding=grounding,
            mechlib_context=mechlib_context,
        )

        for idx in range(1, self.max_attempts + 1):
            if idx == 1:
                prompt = render_template(
                    self.prompt_generate,
                    {
                        "theorem_decl": selected_candidate.theorem_decl,
                        "problem_ir_json": problem_ir_json,
                        "proof_plan_json": proof_plan_json,
                        "mechlib_context": mechlib_context or "(none)",
                    },
                )
            else:
                prompt = render_template(
                    self.prompt_repair,
                    {
                        "theorem_decl": selected_candidate.theorem_decl,
                        "problem_ir_json": problem_ir_json,
                        "proof_plan_json": proof_plan_json,
                        "previous_proof": previous_proof,
                        "previous_error": previous_error,
                        "mechlib_context": mechlib_context or "(none)",
                    },
                )

            raw = ""
            parse_ok = False
            proof_body = ""
            attempt_plan: str | None = None
            try:
                resp = self.model_client.generate_text(prompt)
                raw = resp.text
            except Exception as exc:
                raw = ""
                previous_error = f"{type(exc).__name__}: {exc}"

            if raw:
                try:
                    parsed = parse_json_model(raw, ProofPayload)
                    parse_ok = True
                    proof_body = parsed.proof_body.strip()
                    attempt_plan = (parsed.plan or "").strip() or None
                except ResponseParseError:
                    parse_ok = False

            if not proof_body:
                error_type = "proof_response_parse_failed" if raw else "proof_generation_failure"
                stderr_digest = previous_error or error_type
                sub_error_type = _classify_proof_sub_error(error_type, stderr_digest, proof_body)
                attempt = ProofAttemptResult(
                    sample_id=grounding.sample_id,
                    attempt_index=idx,
                    proof_body="",
                    plan=attempt_plan,
                    parse_ok=parse_ok,
                    raw_response=raw,
                    compile_pass=False,
                    strict_pass=False,
                    error_type=error_type,
                    stderr_digest=stderr_digest,
                    log_path=None,
                    sub_error_type=sub_error_type,
                    failure_tags=_proof_failure_tags(error_type, sub_error_type),
                    failure_summary=_build_proof_failure_summary(error_type, stderr_digest),
                    failure_details={
                        "attempt_index": idx,
                        "previous_error": previous_error or None,
                        "proof_plan": proof_plan or None,
                    },
                    proof_body_excerpt=None,
                    stderr_excerpt=_excerpt(stderr_digest),
                    proof_plan=proof_plan or None,
                    theorems_to_apply=list(theorems_to_apply),
                    givens_to_use=list(givens_to_use),
                    intermediate_claims=list(intermediate_claims),
                    plan_grounding_ok=plan_grounding_ok,
                )
                attempts.append(attempt)
                previous_proof = ""
                previous_error = attempt.stderr_digest or attempt.error_type or "proof_search_failure"
                final_error = attempt.error_type or "proof_search_failure"
                continue

            proof_body = normalize_lean_text(proof_body)

            verify = self.lean_runner.verify_proof(
                sample_id=grounding.sample_id,
                candidate_id=selected_candidate.candidate_id,
                lean_header=selected_candidate.lean_header,
                theorem_decl=selected_candidate.theorem_decl,
                proof_body=proof_body,
                run_dir=run_dir,
            )
            error_type = str(verify["error_type"]) if verify["error_type"] else None
            if error_type and error_type in {"invalid_lean_syntax", "elaboration_failure"}:
                error_type = "proof_search_failure"

            attempt = ProofAttemptResult(
                sample_id=grounding.sample_id,
                attempt_index=idx,
                proof_body=proof_body,
                plan=attempt_plan,
                parse_ok=parse_ok,
                raw_response=raw,
                compile_pass=bool(verify["compile_pass"]),
                strict_pass=bool(verify["strict_pass"]),
                error_type=error_type,
                stderr_digest=str(verify["stderr_digest"]),
                log_path=str(verify["log_path"]) if verify["log_path"] else None,
                backend_used=str(verify.get("backend_used") or ""),
                route_reason=str(verify.get("route_reason") or ""),
                route_fallback_used=bool(verify.get("route_fallback_used")),
                sub_error_type=(
                    str(verify.get("sub_error_type") or "")
                    or _classify_proof_sub_error(error_type, str(verify["stderr_digest"]), proof_body)
                    or None
                ),
                failure_tags=_proof_failure_tags(
                    error_type,
                    str(verify.get("sub_error_type") or "")
                    or _classify_proof_sub_error(error_type, str(verify["stderr_digest"]), proof_body),
                ),
                failure_summary=(
                    str(verify.get("failure_summary") or "").strip()
                    or _build_proof_failure_summary(error_type, str(verify["stderr_digest"]))
                ),
                failure_details=(
                    dict(verify.get("failure_details"))
                    if isinstance(verify.get("failure_details"), dict)
                    else {
                        "error_line": verify.get("error_line"),
                        "error_message": verify.get("error_message"),
                        "error_snippet": verify.get("error_snippet"),
                        "stderr_excerpt": verify.get("stderr_excerpt"),
                    }
                ),
                proof_body_excerpt=_excerpt(proof_body),
                stderr_excerpt=_excerpt(str(verify["stderr_digest"])),
                proof_plan=proof_plan or None,
                theorems_to_apply=list(theorems_to_apply),
                givens_to_use=list(givens_to_use),
                intermediate_claims=list(intermediate_claims),
                plan_grounding_ok=plan_grounding_ok,
            )
            attempts.append(attempt)
            final_log_path = attempt.log_path

            if attempt.strict_pass:
                return (
                    attempts,
                    ProofCheckResult(
                        sample_id=grounding.sample_id,
                        proof_success=True,
                        attempts_used=idx,
                        selected_candidate_id=selected_candidate.candidate_id,
                        error_type=None,
                        final_log_path=final_log_path,
                        backend_used=attempt.backend_used,
                        sub_error_type=None,
                        failure_tags=[],
                        failure_summary=None,
                        failure_details={
                            "proof_plan": proof_plan or None,
                            "theorems_to_apply": list(theorems_to_apply),
                            "plan_grounding_ok": plan_grounding_ok,
                        },
                    ),
                )

            previous_proof = proof_body
            previous_error = attempt.stderr_digest or attempt.error_type or "proof_search_failure"
            final_error = attempt.error_type or "proof_search_failure"

        return (
            attempts,
            ProofCheckResult(
                sample_id=grounding.sample_id,
                proof_success=False,
                attempts_used=len(attempts),
                selected_candidate_id=selected_candidate.candidate_id,
                error_type=final_error,
                final_log_path=final_log_path,
                backend_used=(attempts[-1].backend_used if attempts else None),
                sub_error_type=(attempts[-1].sub_error_type if attempts else None),
                failure_tags=(attempts[-1].failure_tags if attempts else []),
                failure_summary=(attempts[-1].failure_summary if attempts else None),
                failure_details=(
                    attempts[-1].failure_details
                    if attempts
                    else {
                        "proof_plan": proof_plan or None,
                        "theorems_to_apply": list(theorems_to_apply),
                        "plan_grounding_ok": plan_grounding_ok,
                    }
                ),
            ),
        )
