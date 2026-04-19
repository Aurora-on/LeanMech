from __future__ import annotations

import copy
import json
import time
from collections import Counter
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, TypedDict

from mech_pipeline.adapters.lean_runner import LeanRunner
from mech_pipeline.config import PipelineConfig
from mech_pipeline.modules import ModuleA, ModuleC, ModuleD, ModuleZDirectFormalize
from mech_pipeline.rendering import _build_lean_export_workspace_files, _render_problem_lean_file
from mech_pipeline.types import (
    CompileCheckResult,
    DirectFormalizationResult,
    GroundingResult,
    SampleRunSummary,
    SemanticRankResult,
    StatementCandidate,
)
from mech_pipeline.utils import safe_stem, to_row


DIRECT_SAMPLE_TIMEOUT_S = 900
DIRECT_STAGE_ROW_FILES = (
    "problem_ir.jsonl",
    "direct_formalization.jsonl",
    "compile_checks.jsonl",
    "semantic_rank.jsonl",
    "sample_summary.jsonl",
)
DIRECT_BASELINE_LEAN_HEADER = "\n".join(["import PhysLean", "open PhysLean"])


class DirectProcessSampleResult(TypedDict):
    stage_rows: dict[str, list[dict[str, object]]]
    grounding_rows: list[GroundingResult]
    direct_rows: list[DirectFormalizationResult]
    compile_rows: list[CompileCheckResult]
    semantic_rows: list[SemanticRankResult]
    summary: SampleRunSummary


class DirectExecutionResult(TypedDict):
    stage_rows: dict[str, list[dict[str, object]]]
    grounding_rows: list[GroundingResult]
    direct_rows: list[DirectFormalizationResult]
    compile_rows: list[CompileCheckResult]
    semantic_rows: list[SemanticRankResult]
    summaries: list[SampleRunSummary]
    sample_concurrency: int


def new_stage_rows(stage_row_files: tuple[str, ...]) -> dict[str, list[dict[str, object]]]:
    return {name: [] for name in stage_row_files}


def build_direct_worker_modules(
    *,
    cfg: PipelineConfig,
    prompt_dir: Path,
    build_model_client: Callable[[Any], Any],
) -> tuple[ModuleA, ModuleZDirectFormalize, ModuleC, ModuleD]:
    model_client = build_model_client(cfg.model)
    lean_runner = LeanRunner(
        physlean_dir=Path(cfg.lean.physlean_dir),
        mechlib_dir=Path(cfg.lean.mechlib_dir),
        timeout_s=cfg.lean.timeout_s,
        strict_blocklist=cfg.lean.strict_blocklist,
        lean_header=cfg.lean.lean_header,
        enabled=cfg.lean.enabled,
        route_policy=cfg.lean.route_policy,
        default_backend=cfg.lean.default_backend,
        route_fallback=cfg.lean.route_fallback,
    )
    module_a = ModuleA(model_client, cfg.model.model_id, prompt_dir / cfg.prompts.a_extract_ir)
    module_z = ModuleZDirectFormalize(
        model_client=model_client,
        prompt_path=prompt_dir / "Z_direct_formalize.txt",
        lean_header=DIRECT_BASELINE_LEAN_HEADER,
    )
    module_c = ModuleC(lean_runner)
    module_d = ModuleD(model_client, prompt_dir / cfg.prompts.d_semantic_rank, cfg.semantic.pass_threshold)
    return module_a, module_z, module_c, module_d


def _bounded_stage_cfg(cfg: PipelineConfig, started_at: float) -> PipelineConfig | None:
    elapsed = time.monotonic() - started_at
    remaining = int(DIRECT_SAMPLE_TIMEOUT_S - elapsed)
    if remaining <= 0:
        return None
    bounded = copy.deepcopy(cfg)
    bounded.model.timeout_s = max(1, remaining)
    bounded.lean.timeout_s = max(1, remaining)
    bounded.model.max_retries = 0
    return bounded


def _timeout_summary(
    *,
    sample_id: str,
    phase: str,
    started_at: float,
    grounding_ok: bool,
    direct_ok: bool,
    compile_ok: bool,
    semantic_ok: bool,
) -> SampleRunSummary:
    elapsed = round(time.monotonic() - started_at, 3)
    return SampleRunSummary(
        sample_id=sample_id,
        grounding_ok=grounding_ok,
        statement_generation_ok=direct_ok,
        compile_ok=compile_ok,
        semantic_ok=semantic_ok,
        proof_ok=False,
        end_to_end_ok=False,
        final_error_type="sample_timeout",
        notes="direct baseline",
        final_round_index=0,
        feedback_loop_used=False,
        sub_error_type=f"sample_timeout_{phase}",
        failure_summary=f"Sample exceeded {DIRECT_SAMPLE_TIMEOUT_S}s total budget during {phase}.",
        failure_details={"timeout_phase": phase, "elapsed_s": elapsed, "timeout_s": DIRECT_SAMPLE_TIMEOUT_S},
    )


def process_direct_sample(
    *,
    cfg: PipelineConfig,
    sample,
    run_dir: Path,
    prompt_dir: Path,
    preflight_ok: bool,
    preflight_error: str | None,
    preflight_message: str,
    stage_row_files: tuple[str, ...],
    build_model_client: Callable[[Any], Any],
) -> DirectProcessSampleResult:
    stage_rows = new_stage_rows(stage_row_files)
    grounding_rows: list[GroundingResult] = []
    direct_rows: list[DirectFormalizationResult] = []
    compile_rows: list[CompileCheckResult] = []
    semantic_rows: list[SemanticRankResult] = []
    started_at = time.monotonic()

    if sample.skip_reason:
        summary = SampleRunSummary(
            sample_id=sample.sample_id,
            grounding_ok=False,
            statement_generation_ok=False,
            compile_ok=False,
            semantic_ok=False,
            proof_ok=False,
            end_to_end_ok=False,
            final_error_type=sample.skip_reason,
            notes="dataset skip",
            sub_error_type=sample.skip_reason,
            failure_summary="Sample skipped by dataset adapter.",
            failure_details={"skip_reason": sample.skip_reason},
        )
        return {
            "stage_rows": stage_rows,
            "grounding_rows": grounding_rows,
            "direct_rows": direct_rows,
            "compile_rows": compile_rows,
            "semantic_rows": semantic_rows,
            "summary": summary,
        }

    if not preflight_ok:
        summary = SampleRunSummary(
            sample_id=sample.sample_id,
            grounding_ok=False,
            statement_generation_ok=False,
            compile_ok=False,
            semantic_ok=False,
            proof_ok=False,
            end_to_end_ok=False,
            final_error_type=preflight_error,
            notes=preflight_message,
            sub_error_type=preflight_error,
            failure_summary=preflight_message,
            failure_details={"preflight_error": preflight_error, "preflight_message": preflight_message},
        )
        return {
            "stage_rows": stage_rows,
            "grounding_rows": grounding_rows,
            "direct_rows": direct_rows,
            "compile_rows": compile_rows,
            "semantic_rows": semantic_rows,
            "summary": summary,
        }

    stage_cfg = _bounded_stage_cfg(cfg, started_at)
    if stage_cfg is None:
        summary = _timeout_summary(
            sample_id=sample.sample_id,
            phase="module_a",
            started_at=started_at,
            grounding_ok=False,
            direct_ok=False,
            compile_ok=False,
            semantic_ok=False,
        )
        return {
            "stage_rows": stage_rows,
            "grounding_rows": grounding_rows,
            "direct_rows": direct_rows,
            "compile_rows": compile_rows,
            "semantic_rows": semantic_rows,
            "summary": summary,
        }
    module_a, _, _, _ = build_direct_worker_modules(
        cfg=stage_cfg,
        prompt_dir=prompt_dir,
        build_model_client=build_model_client,
    )
    grounding = module_a.run(sample)
    grounding_rows.append(grounding)
    stage_rows["problem_ir.jsonl"].append(to_row(grounding))

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
            sub_error_type=grounding.error or "visual_grounding_failure",
            failure_summary=grounding.error or "module A failed",
            failure_details={"grounding_error": grounding.error},
        )
        return {
            "stage_rows": stage_rows,
            "grounding_rows": grounding_rows,
            "direct_rows": direct_rows,
            "compile_rows": compile_rows,
            "semantic_rows": semantic_rows,
            "summary": summary,
        }

    stage_cfg = _bounded_stage_cfg(cfg, started_at)
    if stage_cfg is None:
        summary = _timeout_summary(
            sample_id=sample.sample_id,
            phase="module_z",
            started_at=started_at,
            grounding_ok=True,
            direct_ok=False,
            compile_ok=False,
            semantic_ok=False,
        )
        return {
            "stage_rows": stage_rows,
            "grounding_rows": grounding_rows,
            "direct_rows": direct_rows,
            "compile_rows": compile_rows,
            "semantic_rows": semantic_rows,
            "summary": summary,
        }
    _, module_z, _, _ = build_direct_worker_modules(
        cfg=stage_cfg,
        prompt_dir=prompt_dir,
        build_model_client=build_model_client,
    )
    direct = module_z.run(sample)
    direct_rows.append(direct)
    stage_rows["direct_formalization.jsonl"].append(to_row(direct))

    if not direct.parse_ok:
        summary = SampleRunSummary(
            sample_id=sample.sample_id,
            grounding_ok=True,
            statement_generation_ok=False,
            compile_ok=False,
            semantic_ok=False,
            proof_ok=False,
            end_to_end_ok=False,
            final_error_type="direct_generation_parse_failed",
            notes="direct baseline generation failed",
            sub_error_type="direct_generation_parse_failed",
            failure_summary=direct.error or "direct generation parse failed",
            failure_details={"direct_error": direct.error},
        )
        return {
            "stage_rows": stage_rows,
            "grounding_rows": grounding_rows,
            "direct_rows": direct_rows,
            "compile_rows": compile_rows,
            "semantic_rows": semantic_rows,
            "summary": summary,
        }

    candidate = StatementCandidate(
        sample_id=sample.sample_id,
        candidate_id="direct",
        lean_header=direct.lean_header,
        theorem_decl=direct.theorem_decl,
        plan=direct.plan,
        parse_ok=direct.parse_ok,
        raw_response=direct.raw_response,
        error=direct.error,
    )

    stage_cfg = _bounded_stage_cfg(cfg, started_at)
    if stage_cfg is None:
        summary = _timeout_summary(
            sample_id=sample.sample_id,
            phase="module_c",
            started_at=started_at,
            grounding_ok=True,
            direct_ok=True,
            compile_ok=False,
            semantic_ok=False,
        )
        return {
            "stage_rows": stage_rows,
            "grounding_rows": grounding_rows,
            "direct_rows": direct_rows,
            "compile_rows": compile_rows,
            "semantic_rows": semantic_rows,
            "summary": summary,
        }
    _, _, module_c, _ = build_direct_worker_modules(
        cfg=stage_cfg,
        prompt_dir=prompt_dir,
        build_model_client=build_model_client,
    )
    compile_result = module_c.run(sample.sample_id, [candidate], run_dir=run_dir)[0]
    compile_rows.append(compile_result)
    stage_rows["compile_checks.jsonl"].append(to_row(compile_result))

    semantic: SemanticRankResult | None = None
    if compile_result.compile_pass:
        stage_cfg = _bounded_stage_cfg(cfg, started_at)
        if stage_cfg is None:
            summary = _timeout_summary(
                sample_id=sample.sample_id,
                phase="module_d",
                started_at=started_at,
                grounding_ok=True,
                direct_ok=True,
                compile_ok=True,
                semantic_ok=False,
            )
            return {
                "stage_rows": stage_rows,
                "grounding_rows": grounding_rows,
                "direct_rows": direct_rows,
                "compile_rows": compile_rows,
                "semantic_rows": semantic_rows,
                "summary": summary,
            }
        _, _, _, module_d = build_direct_worker_modules(
            cfg=stage_cfg,
            prompt_dir=prompt_dir,
            build_model_client=build_model_client,
        )
        semantic = module_d.run(
            grounding=grounding,
            candidates=[candidate],
            compile_checks=[compile_result],
            problem_text=sample.problem_text,
            mechlib_context="(none)",
        )
        semantic_rows.append(semantic)
        stage_rows["semantic_rank.jsonl"].append(to_row(semantic))

    semantic_ok = bool(semantic.semantic_pass) if semantic else False
    formalization_ok = grounding.parse_ok and direct.parse_ok and compile_result.compile_pass and semantic_ok

    final_error: str | None = None
    final_sub_error: str | None = None
    final_failure_summary: str | None = None
    final_failure_details: dict[str, object] = {}
    if not formalization_ok:
        if not direct.parse_ok:
            final_error = "direct_generation_parse_failed"
            final_sub_error = "direct_generation_parse_failed"
            final_failure_summary = direct.error
            final_failure_details = {"direct_error": direct.error}
        elif not compile_result.compile_pass:
            final_error = compile_result.error_type
            final_sub_error = compile_result.sub_error_type
            final_failure_summary = compile_result.failure_summary
            final_failure_details = compile_result.failure_details
        else:
            final_error = (semantic.error if semantic else None) or "semantic_drift"
            final_sub_error = semantic.sub_error_type if semantic else "semantic_drift"
            final_failure_summary = semantic.failure_summary if semantic else "semantic check not run"
            final_failure_details = semantic.failure_details if semantic else {}

    summary = SampleRunSummary(
        sample_id=sample.sample_id,
        grounding_ok=grounding.parse_ok,
        statement_generation_ok=direct.parse_ok,
        compile_ok=compile_result.compile_pass,
        semantic_ok=semantic_ok,
        proof_ok=semantic_ok,
        end_to_end_ok=formalization_ok,
        final_error_type=final_error,
        notes="direct baseline (compile+semantic only)",
        final_round_index=0,
        feedback_loop_used=False,
        sub_error_type=final_sub_error,
        failure_summary=final_failure_summary,
        failure_details=final_failure_details,
    )
    return {
        "stage_rows": stage_rows,
        "grounding_rows": grounding_rows,
        "direct_rows": direct_rows,
        "compile_rows": compile_rows,
        "semantic_rows": semantic_rows,
        "summary": summary,
    }


def execute_direct_samples(
    *,
    cfg: PipelineConfig,
    samples,
    run_dir: Path,
    prompt_dir: Path,
    preflight_ok: bool,
    preflight_error: str | None,
    preflight_message: str,
    stage_row_files: tuple[str, ...],
    emit_console_line: Callable[[str], None],
    build_model_client: Callable[[Any], Any],
) -> DirectExecutionResult:
    stage_rows = new_stage_rows(stage_row_files)
    grounding_rows: list[GroundingResult] = []
    direct_rows: list[DirectFormalizationResult] = []
    compile_rows: list[CompileCheckResult] = []
    semantic_rows: list[SemanticRankResult] = []
    summaries: list[SampleRunSummary] = []

    total_samples = len(samples)
    sample_concurrency = min(cfg.runtime.sample_concurrency, total_samples) if total_samples else 1
    ordered_results: list[DirectProcessSampleResult | None] = [None] * total_samples
    completed = 0

    for idx, sample in enumerate(samples, start=1):
        emit_console_line(f"[{idx}/{total_samples}] sample={sample.sample_id}")
    emit_console_line(f"progress: 0/{total_samples} completed, sample_concurrency={sample_concurrency}")

    kwargs = {
        "cfg": cfg,
        "run_dir": run_dir,
        "prompt_dir": prompt_dir,
        "preflight_ok": preflight_ok,
        "preflight_error": preflight_error,
        "preflight_message": preflight_message,
        "stage_row_files": stage_row_files,
        "build_model_client": build_model_client,
    }

    if total_samples == 0:
        emit_console_line("progress: 0/0 completed")
    elif sample_concurrency <= 1:
        for idx, sample in enumerate(samples):
            result = process_direct_sample(sample=sample, **kwargs)
            ordered_results[idx] = result
            completed += 1
            emit_console_line(f"progress: {completed}/{total_samples} completed, sample={sample.sample_id}")
    else:
        future_map: dict[Future[DirectProcessSampleResult], tuple[int, str]] = {}
        with ThreadPoolExecutor(max_workers=sample_concurrency) as executor:
            for idx, sample in enumerate(samples):
                future = executor.submit(process_direct_sample, sample=sample, **kwargs)
                future_map[future] = (idx, sample.sample_id)
            try:
                for future in as_completed(future_map):
                    idx, sample_id = future_map[future]
                    result = future.result()
                    ordered_results[idx] = result
                    completed += 1
                    emit_console_line(f"progress: {completed}/{total_samples} completed, sample={sample_id}")
            except Exception:
                for future in future_map:
                    future.cancel()
                raise

    if total_samples:
        emit_console_line(f"progress: {completed}/{total_samples} completed")

    for result in ordered_results:
        if result is None:
            continue
        for name, rows in result["stage_rows"].items():
            stage_rows[name].extend(rows)
        grounding_rows.extend(result["grounding_rows"])
        direct_rows.extend(result["direct_rows"])
        compile_rows.extend(result["compile_rows"])
        semantic_rows.extend(result["semantic_rows"])
        summaries.append(result["summary"])

    stage_rows["sample_summary.jsonl"] = [to_row(s) for s in summaries]
    return {
        "stage_rows": stage_rows,
        "grounding_rows": grounding_rows,
        "direct_rows": direct_rows,
        "compile_rows": compile_rows,
        "semantic_rows": semantic_rows,
        "summaries": summaries,
        "sample_concurrency": sample_concurrency,
    }


def build_direct_metrics(
    *,
    summaries: list[SampleRunSummary],
    direct_rows: list[DirectFormalizationResult],
    compile_rows: list[CompileCheckResult],
    semantic_rows: list[SemanticRankResult],
) -> dict[str, Any]:
    total = len(summaries)
    direct_success = sum(1 for row in direct_rows if row.parse_ok)
    grounding_success = sum(1 for row in summaries if row.grounding_ok)
    compile_total = len(compile_rows)
    compile_success = sum(1 for row in compile_rows if row.compile_pass)
    semantic_total = len(semantic_rows)
    semantic_success = sum(1 for row in semantic_rows if row.semantic_pass)
    formalization_success = sum(1 for row in summaries if row.end_to_end_ok)
    errors = Counter()
    for row in summaries:
        if row.final_error_type:
            errors[row.final_error_type] += 1

    def _rate(num: int, den: int) -> float:
        return round(num / den, 6) if den else 0.0

    return {
        "num_total_samples": total,
        "sample_timeout_s": DIRECT_SAMPLE_TIMEOUT_S,
        "grounding_success_rate": _rate(grounding_success, total),
        "direct_generation_success_rate": _rate(direct_success, total),
        "lean_compile_success_rate": _rate(compile_success, compile_total),
        "semantic_consistency_pass_rate": _rate(semantic_success, semantic_total),
        "formalization_success_rate": _rate(formalization_success, total),
        "error_type_distribution": dict(errors),
    }


def build_direct_analysis(metrics: dict[str, Any], summaries: list[SampleRunSummary]) -> str:
    lines = [
        "# Direct Baseline Analysis",
        "",
        "- baseline_type: direct theorem generation",
        "- environment: physlean_only",
        "- retrieval: disabled",
        "- evaluation: A grounding + C compile + D semantic",
        "- proof_stage: skipped",
        f"- sample_timeout_s: {metrics.get('sample_timeout_s')}",
        "",
        "## Metrics",
        "",
    ]
    for key in [
        "num_total_samples",
        "grounding_success_rate",
        "direct_generation_success_rate",
        "lean_compile_success_rate",
        "semantic_consistency_pass_rate",
        "formalization_success_rate",
    ]:
        lines.append(f"- {key}: {metrics.get(key)}")
    lines.extend(["", "## Error Distribution", ""])
    error_dist = metrics.get("error_type_distribution", {})
    if isinstance(error_dist, dict) and error_dist:
        for key, value in sorted(error_dist.items(), key=lambda kv: (-int(kv[1]), str(kv[0]))):
            lines.append(f"- {key}: {value}")
    else:
        lines.append("- none")
    failed = [s for s in summaries if not s.end_to_end_ok]
    if failed:
        lines.extend(["", "## Failed Samples", ""])
        for row in failed[:30]:
            lines.append(
                f"- {row.sample_id}: error={row.final_error_type}, sub_error={row.sub_error_type}, summary={row.failure_summary}"
            )
    return "\n".join(lines) + "\n"


def build_direct_run_readme(
    *,
    samples,
    stage_rows: dict[str, list[dict[str, object]]],
    summaries: list[SampleRunSummary],
    metrics: dict[str, object],
    run_dir: Path,
    sample_concurrency: int,
) -> str:
    direct_map = {str(row.get("sample_id") or ""): row for row in stage_rows.get("direct_formalization.jsonl", [])}
    compile_map = {str(row.get("sample_id") or ""): row for row in stage_rows.get("compile_checks.jsonl", [])}
    semantic_map = {str(row.get("sample_id") or ""): row for row in stage_rows.get("semantic_rank.jsonl", [])}
    summary_map = {row.sample_id: row for row in summaries}

    lines = [
        "# Direct Baseline README",
        "",
        "- baseline_type: direct theorem generation",
        "- environment: physlean_only",
        f"- run_dir: `{run_dir.as_posix()}`",
        f"- lean_exports_dir: `{(run_dir / 'lean_exports').as_posix()}`",
        f"- total_samples: {metrics.get('num_total_samples', 0)}",
        f"- sample_timeout_s: {metrics.get('sample_timeout_s', DIRECT_SAMPLE_TIMEOUT_S)}",
        f"- grounding_success_rate: {metrics.get('grounding_success_rate', 0)}",
        f"- direct_generation_success_rate: {metrics.get('direct_generation_success_rate', 0)}",
        f"- lean_compile_success_rate: {metrics.get('lean_compile_success_rate', 0)}",
        f"- semantic_consistency_pass_rate: {metrics.get('semantic_consistency_pass_rate', 0)}",
        f"- formalization_success_rate: {metrics.get('formalization_success_rate', 0)}",
        f"- sample_concurrency: {sample_concurrency}",
        "",
        "## Sample Details",
        "",
    ]
    for sample in samples:
        sid = sample.sample_id
        summary = summary_map.get(sid)
        direct = direct_map.get(sid)
        compile_row = compile_map.get(sid)
        semantic_row = semantic_map.get(sid)
        lines.extend(
            [
                f"### {sid}",
                "",
                "**Problem**",
                "",
                "```text",
                sample.problem_text[:4000],
                "```",
                "",
                "**Direct Formalization**",
                "",
                f"- parse_ok: {direct.get('parse_ok') if direct else None}",
                f"- error: {direct.get('error') if direct else None}",
                f"- plan: {direct.get('plan') if direct else None}",
            ]
        )
        if direct and direct.get("theorem_decl"):
            lines.extend(
                ["```lean", str(direct.get("lean_header") or "").strip(), "", str(direct.get("theorem_decl") or "").strip(), "```"]
            )
        lines.extend(
            [
                "",
                "**Evaluation**",
                "",
                f"- compile_pass: {compile_row.get('compile_pass') if compile_row else None}",
                f"- compile_error: {compile_row.get('error_type') if compile_row else None}",
                f"- semantic_pass: {semantic_row.get('semantic_pass') if semantic_row else None}",
                f"- semantic_error: {semantic_row.get('error') if semantic_row else None}",
                "",
                "**Result**",
                "",
                f"- grounding_ok: {summary.grounding_ok if summary else None}",
                f"- direct_generation_ok: {summary.statement_generation_ok if summary else None}",
                f"- compile_ok: {summary.compile_ok if summary else None}",
                f"- semantic_ok: {summary.semantic_ok if summary else None}",
                f"- formalization_ok: {summary.end_to_end_ok if summary else None}",
                f"- final_error_type: {summary.final_error_type if summary else None}",
                "",
            ]
        )
    return "\n".join(lines) + "\n"


def build_direct_lean_export_files(
    *,
    cfg: PipelineConfig,
    samples,
    stage_rows: dict[str, list[dict[str, object]]],
    summaries: list[SampleRunSummary],
    run_dir: Path,
) -> dict[str, str]:
    export_root = run_dir / "lean_exports"
    files = _build_lean_export_workspace_files(cfg=cfg, export_root=export_root)
    direct_map = {str(row.get("sample_id") or ""): row for row in stage_rows.get("direct_formalization.jsonl", [])}
    semantic_map = {str(row.get("sample_id") or ""): row for row in stage_rows.get("semantic_rank.jsonl", [])}
    summary_map = {row.sample_id: row for row in summaries}
    index_rows: list[dict[str, object]] = []

    for sample in samples:
        sid = sample.sample_id
        direct = direct_map.get(sid)
        semantic = semantic_map.get(sid)
        summary = summary_map.get(sid)
        candidate_row = None
        if direct:
            candidate_row = {
                "candidate_id": "direct",
                "lean_header": direct.get("lean_header"),
                "theorem_decl": direct.get("theorem_decl"),
                "plan": direct.get("plan"),
            }
        file_name = safe_stem(str(sample.meta.get("name") or sample.sample_id)) + ".lean"
        rel_path = f"lean_exports/problems/{file_name}"
        files[rel_path] = _render_problem_lean_file(
            sample=sample,
            summary=summary,
            candidate_row=candidate_row,
            semantic_row=semantic,
            proof_row=None,
            attempt_row=None,
        )
        index_rows.append(
            {
                "sample_id": sid,
                "sample_name": str(sample.meta.get("name") or sample.sample_id),
                "file": rel_path,
                "selected_candidate_id": "direct" if direct else None,
                "semantic_ok": summary.semantic_ok if summary else None,
                "final_error_type": summary.final_error_type if summary else None,
            }
        )

    files["lean_exports/index.json"] = json.dumps(index_rows, ensure_ascii=False, indent=2) + "\n"
    return files
