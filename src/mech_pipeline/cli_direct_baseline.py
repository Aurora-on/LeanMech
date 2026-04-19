from __future__ import annotations

import argparse
from pathlib import Path

from mech_pipeline.adapters import DataSourceUnavailableError
from mech_pipeline.archive import create_run_dir, write_outputs
from mech_pipeline.cli import (
    _build_dataset,
    _build_lean_runner,
    _configure_utf8_console,
    _emit_console_line,
    _empty_metrics_with_error,
    _redact_secrets,
)
from mech_pipeline.config import load_config, validate_config
from mech_pipeline.direct_baseline import (
    DIRECT_SAMPLE_TIMEOUT_S,
    DIRECT_STAGE_ROW_FILES,
    build_direct_analysis,
    build_direct_lean_export_files,
    build_direct_metrics,
    build_direct_run_readme,
    execute_direct_samples,
)
from mech_pipeline.model import build_model_client


def _apply_physlean_only_baseline(cfg):
    cfg.lean.lean_header = "import PhysLean"
    cfg.lean.route_policy = "force_physlean"
    cfg.lean.default_backend = "physlean"
    cfg.statement.library_target = "physlean"
    cfg.statement.with_mechlib_context = False
    cfg.knowledge.enabled = False
    return cfg


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="mech-baseline-direct",
        description="Direct theorem autoformalization baseline",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run direct theorem baseline")
    run.add_argument("--config", required=True, type=str)
    run.add_argument("--limit", type=int, default=None)
    run.add_argument("--tag", type=str, default=None)
    run.add_argument("--sample-concurrency", type=int, default=None)
    run.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def run_pipeline(args: argparse.Namespace) -> int:
    cfg = load_config(Path(args.config))
    if args.limit is not None:
        cfg.dataset.limit = args.limit
    if args.tag:
        cfg.output.tag = args.tag
    if args.sample_concurrency is not None:
        cfg.runtime.sample_concurrency = args.sample_concurrency
    cfg = _apply_physlean_only_baseline(cfg)
    validate_config(cfg)

    run_dir = create_run_dir(Path(cfg.output.runs_dir), cfg.output.tag)
    latest_dir = Path(cfg.output.output_dir)
    _emit_console_line(f"run_dir={run_dir}")
    _emit_console_line(f"latest_dir={latest_dir}")
    _emit_console_line("baseline_type=direct_theorem_only")
    _emit_console_line("environment=physlean_only")

    stage_rows = {name: [] for name in DIRECT_STAGE_ROW_FILES}
    try:
        samples = _build_dataset(cfg).load()
    except DataSourceUnavailableError as exc:
        metrics = _empty_metrics_with_error("data_source_unavailable")
        analysis = f"# Direct Baseline Analysis\n\n- dataset error: {exc}\n"
        write_outputs(
            run_dir=run_dir,
            latest_dir=latest_dir,
            stage_rows=stage_rows,
            metrics=metrics,
            analysis_md=analysis,
            run_readme_md="# Direct Baseline README\n\nDataset load failed.\n",
            config_payload={"resolved_config": _redact_secrets(cfg.to_dict()), "run_error": str(exc)},
        )
        return 1

    if args.dry_run:
        write_outputs(
            run_dir=run_dir,
            latest_dir=latest_dir,
            stage_rows=stage_rows,
            metrics={
                "num_total_samples": len(samples),
                "sample_timeout_s": 600,
                "grounding_success_rate": 0.0,
                "direct_generation_success_rate": 0.0,
                "lean_compile_success_rate": 0.0,
                "semantic_consistency_pass_rate": 0.0,
                "formalization_success_rate": 0.0,
                "error_type_distribution": {"dry_run_skipped": len(samples)},
                "sample_timeout_s": DIRECT_SAMPLE_TIMEOUT_S,
            },
            analysis_md="# Direct Baseline Analysis\n\n- dry_run: true\n",
            run_readme_md="# Direct Baseline README\n\nDry-run mode.\n",
            config_payload={"resolved_config": _redact_secrets(cfg.to_dict()), "dry_run": True},
        )
        return 0

    prompt_dir = Path(cfg.prompts.dir)
    preflight_runner = _build_lean_runner(cfg)
    preflight_runner.mechlib_dir = None
    preflight_runner._mechlib_ready = False

    preflight_ok = True
    preflight_error: str | None = None
    preflight_message = "skip"
    if cfg.lean.enabled and cfg.lean.preflight_enabled:
        preflight_ok, preflight_error, preflight_message = preflight_runner.preflight()
        _emit_console_line(f"lean_preflight={preflight_ok}, message={preflight_message}")

    execution = execute_direct_samples(
        cfg=cfg,
        samples=samples,
        run_dir=run_dir,
        prompt_dir=prompt_dir,
        preflight_ok=preflight_ok,
        preflight_error=preflight_error,
        preflight_message=preflight_message,
        stage_row_files=DIRECT_STAGE_ROW_FILES,
        emit_console_line=_emit_console_line,
        build_model_client=build_model_client,
    )

    stage_rows = execution["stage_rows"]
    metrics = build_direct_metrics(
        summaries=execution["summaries"],
        direct_rows=execution["direct_rows"],
        compile_rows=execution["compile_rows"],
        semantic_rows=execution["semantic_rows"],
    )
    analysis = build_direct_analysis(metrics, execution["summaries"])
    run_readme = build_direct_run_readme(
        samples=samples,
        stage_rows=stage_rows,
        summaries=execution["summaries"],
        metrics=metrics,
        run_dir=run_dir,
        sample_concurrency=execution["sample_concurrency"],
    )
    lean_export_files = build_direct_lean_export_files(
        cfg=cfg,
        samples=samples,
        stage_rows=stage_rows,
        summaries=execution["summaries"],
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
                "baseline": {
                    "type": "direct_theorem_only",
                    "environment": "physlean_only",
                    "retrieval": False,
                    "feedback_loop": False,
                    "proof_stage": "skipped",
                    "sample_timeout_s": DIRECT_SAMPLE_TIMEOUT_S,
                },
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
