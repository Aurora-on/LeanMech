from __future__ import annotations

import json
from pathlib import Path

from mech_pipeline.adapters.lean_runner import LeanRunner
from mech_pipeline.llm_schemas import ProofPayload
from mech_pipeline.prompting import load_template, render_template
from mech_pipeline.response_parser import ResponseParseError, parse_json_model
from mech_pipeline.types import GroundingResult, ProofAttemptResult, ProofCheckResult, StatementCandidate
from mech_pipeline.utils import (
    normalize_lean_text,
    sanitize_problem_ir_for_llm,
)

DEFAULT_GENERATE_PROMPT = """__TASK_E_GENERATE_PROOF__
You are a Lean4 proof generator.
Given a theorem declaration, produce a Lean proof body that can pass Lean checking.

Output JSON only:
{"proof_body":"...", "strategy":"...", "used_facts":["..."]}

Rules:
1) Output only proof body (do not repeat theorem declaration).
2) Never use sorry/admit/axiom.
3) Prefer robust tactics: simp, norm_num, ring, linarith, nlinarith, field_simp, aesop.
4) If needed, decompose into subgoals with have/constructor and then close goals.
5) Use retrieved MechLib snippets as references for tactic style and lemma naming only.
6) Do not copy irrelevant lemmas; stay strictly aligned with theorem goal.

Theorem:
{{theorem_decl}}

ProblemIR:
{{problem_ir_json}}

Retrieved MechLib context:
{{mechlib_context}}
"""

DEFAULT_REPAIR_PROMPT = """__TASK_E_REPAIR_PROOF__
You are a Lean4 proof repair assistant.
Given the previous proof and Lean error, produce a minimally changed fixed proof body.

Output JSON only:
{"proof_body":"...", "strategy":"...", "used_facts":["..."]}

Rules:
1) Output only proof body (do not repeat theorem declaration).
2) Never use sorry/admit/axiom.
3) Repair should directly address the provided Lean error.
4) Prefer small edits over rewriting everything.
5) Use retrieved MechLib snippets as references for tactic style and lemma naming only.

Theorem:
{{theorem_decl}}

ProblemIR:
{{problem_ir_json}}

Previous proof:
{{previous_proof}}

Previous Lean error:
{{previous_error}}

Retrieved MechLib context:
{{mechlib_context}}
"""
FALLBACK_TACTICS = ["rfl", "simp", "aesop", "linarith", "ring"]


class ModuleE:
    def __init__(
        self,
        model_client,
        lean_runner: LeanRunner,
        prompt_generate_path: Path,
        prompt_repair_path: Path,
        max_attempts: int,
    ) -> None:
        self.model_client = model_client
        self.lean_runner = lean_runner
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
                ),
            )

        safe_ir = sanitize_problem_ir_for_llm(grounding.problem_ir or {})
        problem_ir_json = json.dumps(safe_ir, ensure_ascii=False, indent=2)
        attempts: list[ProofAttemptResult] = []
        previous_proof = ""
        previous_error = ""
        final_error = "proof_search_failure"
        final_log_path: str | None = None

        for idx in range(1, self.max_attempts + 1):
            if idx == 1:
                prompt = render_template(
                    self.prompt_generate,
                    {
                        "theorem_decl": selected_candidate.theorem_decl,
                        "problem_ir_json": problem_ir_json,
                        "mechlib_context": mechlib_context or "(none)",
                    },
                )
            else:
                prompt = render_template(
                    self.prompt_repair,
                    {
                        "theorem_decl": selected_candidate.theorem_decl,
                        "problem_ir_json": problem_ir_json,
                        "previous_proof": previous_proof,
                        "previous_error": previous_error,
                        "mechlib_context": mechlib_context or "(none)",
                    },
                )

            raw = ""
            parse_ok = False
            proof_body = ""
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
                except ResponseParseError:
                    parse_ok = False
            if not proof_body:
                proof_body = "trivial"
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
                    ),
                )

            previous_proof = proof_body
            previous_error = attempt.stderr_digest or attempt.error_type or "proof_search_failure"
            final_error = attempt.error_type or "proof_search_failure"

        # Deterministic tactic fallback after LLM attempts.
        for tactic in FALLBACK_TACTICS:
            idx = len(attempts) + 1
            verify = self.lean_runner.verify_proof(
                sample_id=grounding.sample_id,
                candidate_id=selected_candidate.candidate_id,
                lean_header=selected_candidate.lean_header,
                theorem_decl=selected_candidate.theorem_decl,
                proof_body=tactic,
                run_dir=run_dir,
            )
            error_type = str(verify["error_type"]) if verify["error_type"] else None
            if error_type and error_type in {"invalid_lean_syntax", "elaboration_failure"}:
                error_type = "proof_search_failure"

            attempt = ProofAttemptResult(
                sample_id=grounding.sample_id,
                attempt_index=idx,
                proof_body=tactic,
                parse_ok=True,
                raw_response=f"[fallback_tactic] {tactic}",
                compile_pass=bool(verify["compile_pass"]),
                strict_pass=bool(verify["strict_pass"]),
                error_type=error_type,
                stderr_digest=str(verify["stderr_digest"]),
                log_path=str(verify["log_path"]) if verify["log_path"] else None,
                backend_used=str(verify.get("backend_used") or ""),
                route_reason=str(verify.get("route_reason") or ""),
                route_fallback_used=bool(verify.get("route_fallback_used")),
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
                    ),
                )
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
            ),
        )
