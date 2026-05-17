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
    MixedV2DatasetAdapter,
    PhyxDatasetAdapter,
)
from mech_pipeline.archive import create_run_dir, write_outputs
from mech_pipeline.config import PipelineConfig, load_config, validate_config
from mech_pipeline.knowledge import MechLibRetriever
from mech_pipeline.model import build_model_client
from mech_pipeline.modules import (
    ModuleA,
    ModuleA2ModelIR,
    ModuleB,
    ModuleC,
    ModuleControlledSketch,
    ModuleD,
    ModuleE,
    ModuleF,
    ModuleSolutionRenderer,
)
from mech_pipeline.orchestrator import (
    execute_samples,
    new_stage_rows as _new_stage_rows,
)
from mech_pipeline.preproof_eval import run_preproof_eval
from mech_pipeline.rendering import (
    build_lean_export_files as _build_lean_export_files,
    build_revision_feedback as _build_revision_feedback,
    build_run_readme as _build_run_readme,
)
from mech_pipeline.types import SampleRunSummary
from mech_pipeline.utils import load_dotenv_if_present, to_row


STAGE_ROW_FILES = (
    "problem_ir.jsonl",
    "model_ir.jsonl",
    "structured_mechlib_context.jsonl",
    "evidence_bindings.jsonl",
    "controlled_sketch.jsonl",
    "sketch_audit.jsonl",
    "failure_routes.jsonl",
    "mechlib_retrieval.jsonl",
    "statement_candidates.jsonl",
    "theorem_skeleton_candidates.jsonl",
    "compile_checks.jsonl",
    "semantic_rank.jsonl",
    "proof_attempts.jsonl",
    "proof_checks.jsonl",
    "proof_search_trace.jsonl",
    "proof_action_checks.jsonl",
    "proof_strategy_prompts.jsonl",
    "proof_dependency_audit.jsonl",
    "solution_trace.jsonl",
    "natural_solution.jsonl",
    "solution_render_audit.jsonl",
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
    preproof = sub.add_parser("run-preproof-e", help="run E stage and downstream rendering from a preproof snapshot")
    preproof.add_argument("--preproof-dir", required=True, type=str)
    preproof.add_argument("--config", type=str, default=None, help="optional config override for E/F runtime")
    preproof.add_argument("--tag", type=str, default=None)
    preproof.add_argument("--sample-concurrency", type=int, default=None)
    preproof.add_argument("--limit", type=int, default=None)
    preproof.add_argument("--sample-id", action="append", default=None, help="repeatable sample id filter")
    preproof.add_argument("--api-key-env", type=str, default=None, help="override redacted snapshot api_key_env")
    preproof.add_argument("--output-dir", type=str, default=None)
    preproof.add_argument("--runs-dir", type=str, default=None)
    preproof.add_argument("--dry-run", action="store_true")
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
    if cfg.dataset.source == "mixed_v2":
        return MixedV2DatasetAdapter(
            bench_path=cfg.dataset.lean4phys.bench_path,
            archive_root=cfg.dataset.local_archive.root,
            category=cfg.dataset.lean4phys.category,
            level=cfg.dataset.lean4phys.level,
            sample_policy=cfg.dataset.sample_policy,
            limit=cfg.dataset.limit,
            seed=cfg.dataset.seed,
            single_image_only=cfg.dataset.single_image_only_for_mvp,
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
    module_a2 = ModuleA2ModelIR(model_client, prompt_dir / cfg.prompts.a2_model_ir)
    module_sketch = ModuleControlledSketch(model_client, prompt_dir / cfg.prompts.controlled_sketch)
    module_b = ModuleB(
        model_client,
        prompt_dir / cfg.prompts.b_generate_statements,
        revise_prompt_path=prompt_dir / cfg.prompts.b_revise_statements,
        minimal_prompt_path=prompt_dir / cfg.prompts.b_generate_minimal_skeleton,
        library_target=cfg.statement.library_target,
        b_minimal_llm_enabled=cfg.statement.b_minimal_llm_enabled,
        b_minimal_llm_on_retry=cfg.statement.b_minimal_llm_on_retry,
        compact_minimal_prompts=cfg.statement.compact_minimal_prompts,
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
        proof_config=cfg.proof,
    )
    module_solution_renderer = ModuleSolutionRenderer(
        model_client=model_client,
        prompt_path=prompt_dir / cfg.prompts.solution_renderer,
        config=cfg.solution_renderer,
    )
    return module_a, module_a2, module_sketch, module_b, module_c, module_d, module_e, module_solution_renderer


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
        "model_ir_success_rate": None,
        "evidence_binding_success_rate": None,
        "verified_binding_rate": None,
        "gap_schema_only_rate": None,
        "sketch_audit_pass_rate": None,
        "skeleton_generation_success_rate": None,
        "derived_equation_hypothesis_violation_rate": None,
        "schema_as_proof_fact_violation_rate": None,
        "explicit_gap_law_rate": None,
        "solution_render_success_rate": None,
        "solution_render_audit_pass_rate": None,
        "solution_final_answer_coverage_rate": None,
        "solution_law_step_coverage_rate": None,
        "solution_gap_disclosure_pass_rate": None,
        "solution_unsupported_formula_avg": None,
        "solution_verified_trace_rate": None,
        "solution_legacy_no_audit_rate": None,
        "solution_partial_or_failed_explanation_rate": None,
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
            enriched_corpus_enabled=cfg.knowledge.enriched_corpus_enabled,
            decl_corpus_path=Path(cfg.knowledge.decl_corpus_path),
            law_schema_corpus_path=Path(cfg.knowledge.law_schema_corpus_path),
            problem_schema_corpus_path=Path(cfg.knowledge.problem_schema_corpus_path),
            concept_corpus_path=Path(cfg.knowledge.concept_corpus_path),
            alias_map_path=Path(cfg.knowledge.alias_map_path),
            alignment_index_path=Path(cfg.knowledge.alignment_index_path),
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
            stage_rows=stage_rows,
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
    lean_decl_check_cache_stats = execution.get("lean_decl_check_cache_stats", {})
    if lean_decl_check_cache_stats:
        preflight_details["lean_decl_check_cache"] = lean_decl_check_cache_stats

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
        stage_rows=stage_rows,
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
                "lean_decl_check_cache": preflight_details.get("lean_decl_check_cache", {}),
            },
        },
        extra_text_files=lean_export_files,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    _configure_utf8_console()
    load_dotenv_if_present(Path.cwd() / ".env")
    args = parse_args(argv)
    if args.command == "run":
        return run_pipeline(args)
    if args.command == "run-preproof-e":
        return run_preproof_eval(
            preproof_dir=Path(args.preproof_dir),
            config_path=Path(args.config) if args.config else None,
            tag=args.tag,
            sample_concurrency=args.sample_concurrency,
            limit=args.limit,
            sample_ids=args.sample_id,
            api_key_env=args.api_key_env,
            output_dir=Path(args.output_dir) if args.output_dir else None,
            runs_dir=Path(args.runs_dir) if args.runs_dir else None,
            dry_run=args.dry_run,
            emit_console_line=_emit_console_line,
        )
    raise ValueError(f"unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
