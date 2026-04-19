from __future__ import annotations

import argparse
from pathlib import Path

from mech_pipeline.archive import create_run_dir, write_outputs
from mech_pipeline.cli import (
    STAGE_ROW_FILES,
    _build_dataset,
    _build_lean_runner,
    _build_run_readme,
    _build_worker_modules,
    _build_lean_export_files,
    _build_revision_feedback,
    _configure_utf8_console,
    _emit_console_line,
    _empty_metrics_with_error,
    _new_stage_rows,
    _redact_secrets,
)
from mech_pipeline.config import PipelineConfig, load_config, validate_config
from mech_pipeline.modules import ModuleF
from mech_pipeline.orchestrator import execute_samples
from mech_pipeline.types import SampleRunSummary
from mech_pipeline.utils import to_row
from mech_pipeline.adapters import DataSourceUnavailableError


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="mech-baseline-ablate-no-mechlib",
        description="Run the pipeline with MechLib retrieval context disabled",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run full pipeline without MechLib retrieval context")
    run.add_argument("--config", required=True, type=str)
    run.add_argument("--limit", type=int, default=None)
    run.add_argument("--tag", type=str, default=None)
    run.add_argument("--sample-concurrency", type=int, default=None)
    run.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def _apply_no_mechlib_context_ablation(cfg: PipelineConfig) -> PipelineConfig:
    # This ablation removes retrieved MechLib context from prompts while leaving the
    # rest of the pipeline intact, so the comparison isolates retrieval/help text.
    cfg.knowledge.enabled = False
    cfg.knowledge.inject_modules = []
    cfg.statement.with_mechlib_context = False
    return cfg


def _append_ablation_suffix(tag: str | None) -> str:
    base = (tag or "baseline-v1").strip() or "baseline-v1"
    return f"{base}-ablate-no-mechlib"


def run_pipeline(args: argparse.Namespace) -> int:
    cfg = load_config(Path(args.config))
    if args.limit is not None:
        cfg.dataset.limit = args.limit
    cfg.output.tag = args.tag or _append_ablation_suffix(cfg.output.tag)
    if args.sample_concurrency is not None:
        cfg.runtime.sample_concurrency = args.sample_concurrency
    cfg = _apply_no_mechlib_context_ablation(cfg)
    validate_config(cfg)

    run_dir = create_run_dir(Path(cfg.output.runs_dir), cfg.output.tag)
    latest_dir = Path(cfg.output.output_dir)
    _emit_console_line(f"run_dir={run_dir}")
    _emit_console_line(f"latest_dir={latest_dir}")
    _emit_console_line("ablation=no_mechlib_context")

    stage_rows = _new_stage_rows(STAGE_ROW_FILES)

    try:
        samples = _build_dataset(cfg).load()
    except DataSourceUnavailableError as exc:
        metrics = _empty_metrics_with_error("data_source_unavailable")
        analysis = f"# Baseline V1 Analysis\n\n- dataset error: {exc}\n"
        write_outputs(
            run_dir=run_dir,
            latest_dir=latest_dir,
            stage_rows=stage_rows,
            metrics=metrics,
            analysis_md=analysis,
            run_readme_md="# Run README\n\nDry-run mode.\n",
            config_payload={
                "resolved_config": _redact_secrets(cfg.to_dict()),
                "run_error": str(exc),
                "ablation": {"disable_mechlib_context": True},
            },
        )
        return 1

    if args.dry_run:
        dry_summaries: list[SampleRunSummary] = []
        for sample in samples:
            dry_summaries.append(
                SampleRunSummary(
                    sample_id=sample.sample_id,
                    grounding_ok=False,
                    statement_generation_ok=False,
                    compile_ok=False,
                    semantic_ok=False,
                    proof_ok=False,
                    end_to_end_ok=False,
                    final_error_type="dry_run_skipped",
                    notes="dry-run mode",
                    sub_error_type="dry_run_skipped",
                    failure_summary="Pipeline execution skipped in dry-run mode.",
                    failure_details={"dry_run": True},
                )
            )
        module_f = ModuleF()
        metrics, analysis = module_f.build(
            summaries=dry_summaries,
            statement_rows=[],
            grounding_rows=[],
            compile_rows=[],
            semantic_rows=[],
            proof_rows=[],
        )
        stage_rows["sample_summary.jsonl"] = [to_row(s) for s in dry_summaries]
        write_outputs(
            run_dir=run_dir,
            latest_dir=latest_dir,
            stage_rows=stage_rows,
            metrics=metrics,
            analysis_md=analysis,
            run_readme_md="# Run README\n\nDry-run mode.\n",
            config_payload={
                "resolved_config": _redact_secrets(cfg.to_dict()),
                "dry_run": True,
                "ablation": {"disable_mechlib_context": True},
            },
        )
        return 0

    prompt_dir = Path(cfg.prompts.dir)
    module_f = ModuleF()
    preflight_runner = _build_lean_runner(cfg)

    preflight_ok = True
    preflight_error: str | None = None
    preflight_message = "skip"
    if cfg.lean.enabled and cfg.lean.preflight_enabled:
        preflight_ok, preflight_error, preflight_message = preflight_runner.preflight()
        _emit_console_line(f"lean_preflight={preflight_ok}, message={preflight_message}")

    execution = execute_samples(
        cfg=cfg,
        samples=samples,
        run_dir=run_dir,
        prompt_dir=prompt_dir,
        inject_set=set(),
        retriever=None,
        preflight_ok=preflight_ok,
        preflight_error=preflight_error,
        preflight_message=preflight_message,
        stage_row_files=STAGE_ROW_FILES,
        emit_console_line=_emit_console_line,
        build_worker_modules=_build_worker_modules,
        build_revision_feedback=_build_revision_feedback,
    )

    stage_rows = execution["stage_rows"]
    grounding_rows = execution["grounding_rows"]
    compile_rows = execution["compile_rows"]
    semantic_rows = execution["semantic_rows"]
    proof_rows = execution["proof_rows"]
    summaries = execution["summaries"]
    sample_concurrency = execution["sample_concurrency"]

    metrics, analysis = module_f.build(
        summaries=summaries,
        statement_rows=stage_rows["statement_candidates.jsonl"],
        grounding_rows=grounding_rows,
        compile_rows=compile_rows,
        semantic_rows=semantic_rows,
        proof_rows=proof_rows,
    )
    run_readme = _build_run_readme(
        samples=samples,
        stage_rows=stage_rows,
        summaries=summaries,
        metrics=metrics,
        run_dir=run_dir,
        sample_concurrency=sample_concurrency,
    )
    lean_export_files = _build_lean_export_files(
        cfg=cfg,
        samples=samples,
        stage_rows=stage_rows,
        summaries=summaries,
        run_dir=run_dir,
    )
    write_outputs(
        run_dir=run_dir,
        latest_dir=latest_dir,
        stage_rows=stage_rows,
        metrics=metrics,
        analysis_md=analysis,
        run_readme_md=run_readme,
        config_payload={
            "resolved_config": _redact_secrets(cfg.to_dict()),
            "preflight": {
                "ok": preflight_ok,
                "error_type": preflight_error,
                "message": preflight_message,
            },
            "ablation": {"disable_mechlib_context": True},
        },
        extra_text_files=lean_export_files,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    _configure_utf8_console()
    args = parse_args(argv)
    if args.command == "run":
        return run_pipeline(args)
    raise ValueError(f"unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
