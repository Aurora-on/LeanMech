from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, TypedDict

from mech_pipeline.config import PipelineConfig
from mech_pipeline.knowledge import MechLibRetriever
from mech_pipeline.types import (
    CompileCheckResult,
    GroundingResult,
    ProofCheckResult,
    SampleRunSummary,
    SemanticRankResult,
    StatementCandidate,
)
from mech_pipeline.utils import to_row


class ProcessSampleResult(TypedDict):
    stage_rows: dict[str, list[dict[str, object]]]
    grounding_rows: list[GroundingResult]
    compile_rows: list[CompileCheckResult]
    semantic_rows: list[SemanticRankResult]
    proof_rows: list[ProofCheckResult]
    summary: SampleRunSummary


class ExecutionResult(TypedDict):
    stage_rows: dict[str, list[dict[str, object]]]
    grounding_rows: list[GroundingResult]
    compile_rows: list[CompileCheckResult]
    semantic_rows: list[SemanticRankResult]
    proof_rows: list[ProofCheckResult]
    summaries: list[SampleRunSummary]
    sample_concurrency: int


def new_stage_rows(stage_row_files: tuple[str, ...]) -> dict[str, list[dict[str, object]]]:
    return {name: [] for name in stage_row_files}


def process_sample(
    *,
    cfg: PipelineConfig,
    sample,
    run_dir: Path,
    prompt_dir: Path,
    inject_set: set[str],
    retriever: MechLibRetriever | None,
    preflight_ok: bool,
    preflight_error: str | None,
    preflight_message: str,
    stage_row_files: tuple[str, ...],
    build_worker_modules: Callable[[PipelineConfig, Path], tuple[Any, Any, Any, Any, Any]],
    build_revision_feedback: Callable[..., str],
) -> ProcessSampleResult:
    stage_rows = new_stage_rows(stage_row_files)
    grounding_rows: list[GroundingResult] = []
    compile_rows: list[CompileCheckResult] = []
    semantic_rows: list[SemanticRankResult] = []
    proof_rows: list[ProofCheckResult] = []

    if sample.skip_reason:
        return {
            "stage_rows": stage_rows,
            "grounding_rows": grounding_rows,
            "compile_rows": compile_rows,
            "semantic_rows": semantic_rows,
            "proof_rows": proof_rows,
            "summary": SampleRunSummary(
                sample_id=sample.sample_id,
                grounding_ok=False,
                statement_generation_ok=False,
                compile_ok=False,
                semantic_ok=False,
                proof_ok=False,
                end_to_end_ok=False,
                final_error_type=sample.skip_reason,
                notes="dataset skip",
                final_round_index=0,
                feedback_loop_used=False,
                sub_error_type=sample.skip_reason,
                failure_summary="Sample skipped by dataset adapter.",
                failure_details={"skip_reason": sample.skip_reason},
            ),
        }

    if not preflight_ok:
        return {
            "stage_rows": stage_rows,
            "grounding_rows": grounding_rows,
            "compile_rows": compile_rows,
            "semantic_rows": semantic_rows,
            "proof_rows": proof_rows,
            "summary": SampleRunSummary(
                sample_id=sample.sample_id,
                grounding_ok=False,
                statement_generation_ok=False,
                compile_ok=False,
                semantic_ok=False,
                proof_ok=False,
                end_to_end_ok=False,
                final_error_type=preflight_error,
                notes=preflight_message,
                final_round_index=0,
                feedback_loop_used=False,
                sub_error_type=preflight_error,
                failure_summary=preflight_message,
                failure_details={"preflight_error": preflight_error, "preflight_message": preflight_message},
            ),
        }

    module_a, module_b, module_c, module_d, module_e = build_worker_modules(cfg, prompt_dir)

    def _run_statement_round(
        *,
        round_index: int,
        grounding: GroundingResult,
        mechlib_context: str,
        revision_feedback: str = "(none)",
        previous_candidates: list[StatementCandidate] | None = None,
    ) -> tuple[list[StatementCandidate], list[CompileCheckResult], SemanticRankResult]:
        b_context = mechlib_context if "B" in inject_set else "(none)"
        candidates = module_b.run(
            grounding,
            mechlib_context=b_context,
            revision_feedback=revision_feedback,
            round_index=round_index,
            previous_candidates=previous_candidates,
        )
        stage_rows["statement_candidates.jsonl"].extend(to_row(c) for c in candidates)

        compile_results = module_c.run(sample.sample_id, candidates, run_dir=run_dir)
        for row in compile_results:
            row.round_index = round_index
        compile_rows.extend(compile_results)
        stage_rows["compile_checks.jsonl"].extend(to_row(r) for r in compile_results)

        d_context = mechlib_context if "D" in inject_set else "(none)"
        semantic = module_d.run(
            grounding=grounding,
            candidates=candidates,
            compile_checks=compile_results,
            problem_text=sample.problem_text,
            mechlib_context=d_context,
        )
        semantic.round_index = round_index
        return candidates, compile_results, semantic

    grounding = module_a.run(sample)
    grounding_rows.append(grounding)
    stage_rows["problem_ir.jsonl"].append(to_row(grounding))

    mechlib_items: list[dict[str, object]] = []
    summary_items: list[dict[str, object]] = []
    mechlib_pack: dict[str, object] = {
        "import_hints": [],
        "law_matched_items": [],
        "proof_style_examples": [],
        "domain_from_a": [],
        "selected_tags": [],
        "summary_items_count": 0,
        "source_items_count": 0,
        "final_context_chars": 0,
    }
    mechlib_context = "(none)"
    if retriever and grounding.parse_ok and cfg.statement.with_mechlib_context:
        domain_pack = retriever.build_domain_context(
            problem_text=sample.problem_text,
            problem_ir=grounding.problem_ir,
            top_k=cfg.knowledge.top_k,
        )
        raw_source_items = domain_pack.get("source_items")
        if isinstance(raw_source_items, list):
            mechlib_items = [x for x in raw_source_items if isinstance(x, dict)]
        raw_summary_items = domain_pack.get("summary_items")
        if isinstance(raw_summary_items, list):
            summary_items = [x for x in raw_summary_items if isinstance(x, dict)]
        mechlib_pack = {
            "import_hints": domain_pack.get("import_hints", []),
            "law_matched_items": domain_pack.get("law_matched_items", []),
            "proof_style_examples": domain_pack.get("proof_style_examples", []),
            "domain_from_a": domain_pack.get("domain_from_a", []),
            "selected_tags": domain_pack.get("selected_tags", []),
            "summary_items_count": int(domain_pack.get("summary_items_count", len(summary_items))),
            "source_items_count": int(domain_pack.get("source_items_count", len(mechlib_items))),
            "final_context_chars": int(domain_pack.get("final_context_chars", 0)),
        }
        mechlib_context = str(domain_pack.get("context_text") or "(none)")

    stage_rows["mechlib_retrieval.jsonl"].append(
        {
            "sample_id": sample.sample_id,
            "enabled": bool(retriever and cfg.statement.with_mechlib_context),
            "retrieved_count": int(mechlib_pack.get("summary_items_count", 0))
            + int(mechlib_pack.get("source_items_count", 0)),
            "domain_from_a": mechlib_pack.get("domain_from_a", []),
            "selected_tags": mechlib_pack.get("selected_tags", []),
            "summary_items_count": mechlib_pack.get("summary_items_count", 0),
            "source_items_count": mechlib_pack.get("source_items_count", 0),
            "final_context_chars": mechlib_pack.get("final_context_chars", 0),
            "items": mechlib_items,
            "summary_items": summary_items,
            "import_hints": mechlib_pack.get("import_hints", []),
            "law_matched_items": mechlib_pack.get("law_matched_items", []),
            "proof_style_examples": mechlib_pack.get("proof_style_examples", []),
            "retrieval_context": mechlib_context,
        }
    )

    if not grounding.parse_ok:
        summary = SampleRunSummary(
            sample_id=sample.sample_id,
            grounding_ok=False,
            statement_generation_ok=False,
            compile_ok=False,
            semantic_ok=False,
            proof_ok=False,
            end_to_end_ok=False,
            final_error_type=grounding.error or "visual_grounding_failure",
            notes="module A failed",
            final_round_index=0,
            feedback_loop_used=False,
            sub_error_type=grounding.error or "visual_grounding_failure",
            failure_summary=grounding.error or "module A failed",
            failure_details={"grounding_error": grounding.error, "parse_ok": grounding.parse_ok},
        )
        return {
            "stage_rows": stage_rows,
            "grounding_rows": grounding_rows,
            "compile_rows": compile_rows,
            "semantic_rows": semantic_rows,
            "proof_rows": proof_rows,
            "summary": summary,
        }

    feedback_loop_used = False
    final_round_index = 0
    max_revision_rounds = cfg.statement.max_revision_rounds if cfg.statement.feedback_loop_enabled else 0
    current_round_index = 0
    revision_feedback = "(none)"
    previous_candidates: list[StatementCandidate] | None = None

    while True:
        candidates, compile_results, semantic = _run_statement_round(
            round_index=current_round_index,
            grounding=grounding,
            mechlib_context=mechlib_context,
            revision_feedback=revision_feedback,
            previous_candidates=previous_candidates,
        )

        retry_reason: str | None = None
        if current_round_index < max_revision_rounds:
            if not any(r.compile_pass for r in compile_results):
                retry_reason = "no_compile_pass"
            elif not semantic.semantic_pass:
                retry_reason = "semantic_fail"

        if retry_reason:
            feedback_loop_used = True
            semantic.retry_triggered = True
            semantic.retry_reason = retry_reason
            semantic.retry_feedback_summary = build_revision_feedback(
                retry_reason=retry_reason,
                candidates=candidates,
                compile_results=compile_results,
                semantic=semantic,
            )
        else:
            semantic.retry_triggered = False
            semantic.retry_reason = None
            semantic.retry_feedback_summary = None

        semantic_rows.append(semantic)
        stage_rows["semantic_rank.jsonl"].append(to_row(semantic))

        if not retry_reason:
            final_round_index = current_round_index
            break

        previous_candidates = candidates
        revision_feedback = semantic.retry_feedback_summary or "(none)"
        current_round_index += 1

    statement_generation_ok = len(candidates) > 0
    compile_ok = any(r.compile_pass for r in compile_results)
    selected_candidate = None
    if semantic.selected_candidate_id:
        selected_candidate = next((c for c in candidates if c.candidate_id == semantic.selected_candidate_id), None)

    e_context = mechlib_context if "E" in inject_set else "(none)"
    if not semantic.semantic_pass:
        proof_attempts = []
        proof_check = ProofCheckResult(
            sample_id=grounding.sample_id,
            proof_success=False,
            attempts_used=0,
            selected_candidate_id=semantic.selected_candidate_id,
            error_type="proof_skipped_due_to_semantic_fail",
            final_log_path=None,
            backend_used=semantic.selected_backend,
            round_index=final_round_index,
            sub_error_type="proof_skipped_due_to_semantic_fail",
            failure_tags=["proof_skipped_due_to_semantic_fail"],
            failure_summary="Proof stage skipped because semantic ranking failed.",
            failure_details={
                "semantic_error_type": semantic.error,
                "semantic_sub_error_type": semantic.sub_error_type,
                "semantic_failure_summary": semantic.failure_summary,
            },
        )
    else:
        proof_attempts, proof_check = module_e.run(
            grounding=grounding,
            selected_candidate=selected_candidate,
            run_dir=run_dir,
            mechlib_context=e_context,
        )
        proof_check.round_index = final_round_index

    proof_rows.append(proof_check)
    stage_rows["proof_attempts.jsonl"].extend(to_row(a) for a in proof_attempts)
    stage_rows["proof_checks.jsonl"].append(to_row(proof_check))

    end_to_end = (
        grounding.parse_ok
        and statement_generation_ok
        and compile_ok
        and semantic.semantic_pass
        and proof_check.proof_success
    )
    final_error: str | None = None
    final_sub_error: str | None = None
    final_failure_summary: str | None = None
    final_failure_details: dict[str, object] = {}
    if not end_to_end:
        compile_error = next((r.error_type for r in compile_results if not r.compile_pass), None)
        compile_failure_row = next((r for r in compile_results if not r.compile_pass), None)
        if not grounding.parse_ok:
            final_error = grounding.error or "visual_grounding_failure"
            final_sub_error = grounding.error or "visual_grounding_failure"
            final_failure_summary = grounding.error or "module A failed"
            final_failure_details = {"grounding_error": grounding.error, "parse_ok": grounding.parse_ok}
        elif not statement_generation_ok:
            final_error = "statement_generation_parse_failed"
            final_sub_error = "statement_generation_parse_failed"
            final_failure_summary = "Statement generation did not produce any usable candidates."
            final_failure_details = {"candidate_count": len(candidates)}
        elif not compile_ok:
            final_error = compile_error or "elaboration_failure"
            final_sub_error = compile_failure_row.sub_error_type if compile_failure_row else None
            final_failure_summary = compile_failure_row.failure_summary if compile_failure_row else None
            final_failure_details = compile_failure_row.failure_details if compile_failure_row else {}
        elif not semantic.semantic_pass:
            final_error = semantic.error or "semantic_drift"
            final_sub_error = semantic.sub_error_type
            final_failure_summary = semantic.failure_summary
            final_failure_details = semantic.failure_details
        else:
            final_error = proof_check.error_type or "proof_search_failure"
            final_sub_error = proof_check.sub_error_type
            final_failure_summary = proof_check.failure_summary
            final_failure_details = proof_check.failure_details

    summary = SampleRunSummary(
        sample_id=sample.sample_id,
        grounding_ok=grounding.parse_ok,
        statement_generation_ok=statement_generation_ok,
        compile_ok=compile_ok,
        semantic_ok=semantic.semantic_pass,
        proof_ok=proof_check.proof_success,
        end_to_end_ok=end_to_end,
        final_error_type=final_error,
        notes=None,
        final_round_index=final_round_index,
        feedback_loop_used=feedback_loop_used,
        sub_error_type=final_sub_error,
        failure_summary=final_failure_summary,
        failure_details=final_failure_details,
    )
    return {
        "stage_rows": stage_rows,
        "grounding_rows": grounding_rows,
        "compile_rows": compile_rows,
        "semantic_rows": semantic_rows,
        "proof_rows": proof_rows,
        "summary": summary,
    }


def execute_samples(
    *,
    cfg: PipelineConfig,
    samples,
    run_dir: Path,
    prompt_dir: Path,
    inject_set: set[str],
    retriever: MechLibRetriever | None,
    preflight_ok: bool,
    preflight_error: str | None,
    preflight_message: str,
    stage_row_files: tuple[str, ...],
    emit_console_line: Callable[[str], None],
    build_worker_modules: Callable[[PipelineConfig, Path], tuple[Any, Any, Any, Any, Any]],
    build_revision_feedback: Callable[..., str],
) -> ExecutionResult:
    stage_rows = new_stage_rows(stage_row_files)
    grounding_rows: list[GroundingResult] = []
    compile_rows: list[CompileCheckResult] = []
    semantic_rows: list[SemanticRankResult] = []
    proof_rows: list[ProofCheckResult] = []
    summaries: list[SampleRunSummary] = []
    total_samples = len(samples)
    sample_concurrency = min(cfg.runtime.sample_concurrency, total_samples) if total_samples else 1
    ordered_worker_results: list[ProcessSampleResult | None] = [None] * total_samples
    completed_samples = 0
    for idx, sample in enumerate(samples, start=1):
        emit_console_line(f"[{idx}/{total_samples}] sample={sample.sample_id}")
    emit_console_line(f"progress: 0/{total_samples} completed, sample_concurrency={sample_concurrency}")

    process_kwargs = {
        "cfg": cfg,
        "run_dir": run_dir,
        "prompt_dir": prompt_dir,
        "inject_set": inject_set,
        "retriever": retriever,
        "preflight_ok": preflight_ok,
        "preflight_error": preflight_error,
        "preflight_message": preflight_message,
        "stage_row_files": stage_row_files,
        "build_worker_modules": build_worker_modules,
        "build_revision_feedback": build_revision_feedback,
    }

    if sample_concurrency <= 1:
        for idx, sample in enumerate(samples):
            try:
                result = process_sample(sample=sample, **process_kwargs)
            except Exception:
                emit_console_line(f"progress: failed after {completed_samples}/{total_samples} completed, sample={sample.sample_id}")
                raise
            ordered_worker_results[idx] = result
            completed_samples += 1
            emit_console_line(f"progress: {completed_samples}/{total_samples} completed, sample={sample.sample_id}")
    else:
        futures: dict[Future[ProcessSampleResult], tuple[int, str]] = {}
        executor = ThreadPoolExecutor(max_workers=sample_concurrency, thread_name_prefix="sample")
        try:
            for idx, sample in enumerate(samples):
                future = executor.submit(process_sample, sample=sample, **process_kwargs)
                futures[future] = (idx, sample.sample_id)
            for future in as_completed(futures):
                idx, sample_id = futures[future]
                try:
                    result = future.result()
                except Exception:
                    emit_console_line(f"progress: failed after {completed_samples}/{total_samples} completed, sample={sample_id}")
                    executor.shutdown(wait=False, cancel_futures=True)
                    raise
                ordered_worker_results[idx] = result
                completed_samples += 1
                emit_console_line(f"progress: {completed_samples}/{total_samples} completed, sample={sample_id}")
        except Exception:
            executor.shutdown(wait=False, cancel_futures=True)
            raise
        else:
            executor.shutdown(wait=True)

    emit_console_line(f"progress: {completed_samples}/{total_samples} completed")

    worker_results = [result for result in ordered_worker_results if result is not None]
    for result in worker_results:
        result_stage_rows = result["stage_rows"]
        for name in stage_row_files:
            if name == "sample_summary.jsonl":
                continue
            stage_rows[name].extend(result_stage_rows.get(name, []))
        grounding_rows.extend(result["grounding_rows"])
        compile_rows.extend(result["compile_rows"])
        semantic_rows.extend(result["semantic_rows"])
        proof_rows.extend(result["proof_rows"])
        summaries.append(result["summary"])

    stage_rows["sample_summary.jsonl"] = [to_row(s) for s in summaries]
    return {
        "stage_rows": stage_rows,
        "grounding_rows": grounding_rows,
        "compile_rows": compile_rows,
        "semantic_rows": semantic_rows,
        "proof_rows": proof_rows,
        "summaries": summaries,
        "sample_concurrency": sample_concurrency,
    }
