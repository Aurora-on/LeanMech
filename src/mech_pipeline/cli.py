from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from mech_pipeline.adapters import (
    DataSourceUnavailableError,
    Lean4PhysDatasetAdapter,
    LeanRunner,
    LocalArchiveDatasetAdapter,
    PhyxDatasetAdapter,
)
from mech_pipeline.archive import create_run_dir, write_outputs
from mech_pipeline.config import PipelineConfig, load_config, validate_config
from mech_pipeline.knowledge import MechLibRetriever
from mech_pipeline.model import build_model_client
from mech_pipeline.modules import ModuleA, ModuleB, ModuleC, ModuleD, ModuleE, ModuleF
from mech_pipeline.orchestrator import (
    execute_samples,
    new_stage_rows as _new_stage_rows,
)
from mech_pipeline.rendering import (
    build_lean_export_files as _build_lean_export_files,
    build_revision_feedback as _build_revision_feedback,
    build_run_readme as _build_run_readme,
)
from mech_pipeline.types import SampleRunSummary
from mech_pipeline.utils import to_row


STAGE_ROW_FILES = (
    "problem_ir.jsonl",
    "mechlib_retrieval.jsonl",
    "statement_candidates.jsonl",
    "compile_checks.jsonl",
    "semantic_rank.jsonl",
    "proof_attempts.jsonl",
    "proof_checks.jsonl",
    "sample_summary.jsonl",
)


def _configure_utf8_console() -> None:
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True, write_through=True)
    if sys.stderr is not None and hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True, write_through=True)
    if sys.stdin is not None and hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    if os.name != "nt":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleOutputCP(65001)
        kernel32.SetConsoleCP(65001)
    except Exception:
        pass


def _emit_console_line(message: str) -> None:
    print(message, flush=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="mech-baseline", description="Baseline V1 mechanics pipeline")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run full pipeline")
    run.add_argument("--config", required=True, type=str)
    run.add_argument("--limit", type=int, default=None)
    run.add_argument("--tag", type=str, default=None)
    run.add_argument("--sample-concurrency", type=int, default=None)
    run.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def _build_dataset(cfg: PipelineConfig):
    if cfg.dataset.source == "local_archive":
        return LocalArchiveDatasetAdapter(
            root_dir=cfg.dataset.local_archive.root,
            mode=cfg.dataset.local_archive.mode,
            limit=cfg.dataset.limit,
            single_image_only=cfg.dataset.single_image_only_for_mvp,
        )
    if cfg.dataset.source == "phyx":
        return PhyxDatasetAdapter(
            phyx_urls=cfg.dataset.phyx_urls,
            category=cfg.dataset.category,
            sample_policy=cfg.dataset.sample_policy,
            limit=cfg.dataset.limit,
            seed=cfg.dataset.seed,
        )
    return Lean4PhysDatasetAdapter(
        bench_path=cfg.dataset.lean4phys.bench_path,
        category=cfg.dataset.lean4phys.category,
        level=cfg.dataset.lean4phys.level,
        sample_policy=cfg.dataset.sample_policy,
        limit=cfg.dataset.limit,
        seed=cfg.dataset.seed,
    )


def _build_lean_runner(cfg: PipelineConfig) -> LeanRunner:
    return LeanRunner(
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


def _build_worker_modules(cfg: PipelineConfig, prompt_dir: Path):
    model_client = build_model_client(cfg.model)
    lean_runner = _build_lean_runner(cfg)
    module_a = ModuleA(model_client, cfg.model.model_id, prompt_dir / cfg.prompts.a_extract_ir)
    module_b = ModuleB(
        model_client,
        prompt_dir / cfg.prompts.b_generate_statements,
        revise_prompt_path=prompt_dir / cfg.prompts.b_revise_statements,
        library_target=cfg.statement.library_target,
    )
    module_c = ModuleC(lean_runner)
    module_d = ModuleD(model_client, prompt_dir / cfg.prompts.d_semantic_rank, cfg.semantic.pass_threshold)
    module_e = ModuleE(
        model_client=model_client,
        lean_runner=lean_runner,
        prompt_plan_path=prompt_dir / cfg.prompts.e_plan_proof,
        prompt_generate_path=prompt_dir / cfg.prompts.e_generate_proof,
        prompt_repair_path=prompt_dir / cfg.prompts.e_repair_proof,
        max_attempts=cfg.proof.max_attempts,
    )
    return module_a, module_b, module_c, module_d, module_e


def _empty_metrics_with_error(error_type: str) -> dict[str, object]:
    return {
        "num_total_samples": 0,
        "grounding_success_rate": 0.0,
        "statement_generation_success_rate": 0.0,
        "lean_compile_success_rate": 0.0,
        "semantic_consistency_pass_rate": 0.0,
        "proof_success_rate": 0.0,
        "end_to_end_verified_solve_rate": 0.0,
        "mechlib_header_rate": 0.0,
        "mechlib_compile_pass_rate": 0.0,
        "selected_mechlib_candidate_rate": 0.0,
        "feedback_loop_used_rate": 0.0,
        "error_type_distribution": {error_type: 1},
    }


def _redact_secrets(value):
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            lk = str(k).lower()
            if "api_key" in lk or lk.endswith("token") or "secret" in lk:
                out[k] = "***REDACTED***" if v else v
            else:
                out[k] = _redact_secrets(v)
        return out
    if isinstance(value, list):
        return [_redact_secrets(v) for v in value]
    return value


def run_pipeline(args: argparse.Namespace) -> int:
    cfg = load_config(Path(args.config))
    if args.limit is not None:
        cfg.dataset.limit = args.limit
    if args.tag:
        cfg.output.tag = args.tag
    if args.sample_concurrency is not None:
        cfg.runtime.sample_concurrency = args.sample_concurrency
    validate_config(cfg)

    run_dir = create_run_dir(Path(cfg.output.runs_dir), cfg.output.tag)
    latest_dir = Path(cfg.output.output_dir)
    _emit_console_line(f"run_dir={run_dir}")
    _emit_console_line(f"latest_dir={latest_dir}")

    stage_rows = _new_stage_rows(STAGE_ROW_FILES)

    retriever: MechLibRetriever | None = None
    if cfg.knowledge.enabled:
        retriever = MechLibRetriever(
            mechlib_dir=Path(cfg.knowledge.mechlib_dir),
            scope=cfg.knowledge.scope,
            top_k=cfg.knowledge.top_k,
            cache_path=Path(cfg.knowledge.cache_path),
            context_source=cfg.knowledge.context_source,
            summary_corpus_path=Path(cfg.knowledge.summary_corpus_path),
            summary_injection_mode=cfg.knowledge.summary_injection_mode,
            always_include_core_tags=cfg.knowledge.always_include_core_tags,
        )
    inject_set = {m.strip().upper() for m in cfg.knowledge.inject_modules}

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
            config_payload={"resolved_config": _redact_secrets(cfg.to_dict()), "run_error": str(exc)},
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
            config_payload={"resolved_config": _redact_secrets(cfg.to_dict()), "dry_run": True},
        )
        return 0

    prompt_dir = Path(cfg.prompts.dir)
    module_f = ModuleF()
    preflight_runner = _build_lean_runner(cfg)

    preflight_ok = True
    preflight_error: str | None = None
    preflight_message = "skip"
    preflight_details: dict[str, object] = {
        "ok": True,
        "error_type": None,
        "message": "skip",
        "environment_health": "clean",
        "environment_warnings": [],
    }
    if cfg.lean.enabled and cfg.lean.preflight_enabled:
        preflight_details = preflight_runner.preflight_details()
        preflight_ok = bool(preflight_details["ok"])
        preflight_error = str(preflight_details["error_type"]) if preflight_details.get("error_type") else None
        preflight_message = str(preflight_details["message"])
        _emit_console_line(f"lean_preflight={preflight_ok}, message={preflight_message}")
        _emit_console_line(
            f"environment_health={preflight_details.get('environment_health')}, warnings={len(preflight_details.get('environment_warnings') or [])}"
        )

    execution = execute_samples(
        cfg=cfg,
        samples=samples,
        run_dir=run_dir,
        prompt_dir=prompt_dir,
        inject_set=inject_set,
        retriever=retriever,
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
        retrieval_rows=stage_rows["mechlib_retrieval.jsonl"],
        proof_attempt_rows=stage_rows["proof_attempts.jsonl"],
        run_metadata=preflight_details,
    )
    run_readme = _build_run_readme(
        samples=samples,
        stage_rows=stage_rows,
        summaries=summaries,
        metrics=metrics,
        run_dir=run_dir,
        sample_concurrency=sample_concurrency,
        run_metadata=preflight_details,
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
                "environment_health": preflight_details.get("environment_health"),
                "environment_warnings": preflight_details.get("environment_warnings"),
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
