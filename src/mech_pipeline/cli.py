from __future__ import annotations

import argparse
import json
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
from mech_pipeline.config import PipelineConfig, load_config
from mech_pipeline.knowledge import MechLibRetriever
from mech_pipeline.model import build_model_client
from mech_pipeline.modules import ModuleA, ModuleB, ModuleC, ModuleD, ModuleE, ModuleF
from mech_pipeline.types import SampleRunSummary
from mech_pipeline.utils import to_row, truncate


def _configure_utf8_console() -> None:
    os.environ.setdefault("PYTHONUTF8", "1")
    if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if sys.stderr is not None and hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
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
        # Keep the pipeline runnable even if console CP update is blocked.
        pass


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="mech-baseline",
        description="Baseline V1 mechanics pipeline",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run full pipeline")
    run.add_argument("--config", required=True, type=str)
    run.add_argument("--limit", type=int, default=None)
    run.add_argument("--tag", type=str, default=None)
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


def _empty_metrics_with_error(error_type: str) -> dict[str, object]:
    return {
        "num_total_samples": 0,
        "grounding_success_rate": 0.0,
        "statement_generation_success_rate": 0.0,
        "lean_compile_success_rate": 0.0,
        "semantic_consistency_pass_rate": 0.0,
        "proof_success_rate": 0.0,
        "end_to_end_verified_solve_rate": 0.0,
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


def _as_int(value: object, default: int = 0) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return default
    return default


def _as_row_list(value: object | None) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    out: list[dict[str, object]] = []
    for item in value:
        if isinstance(item, dict):
            out.append(item)
    return out


def _build_run_readme(
    samples,
    stage_rows: dict[str, list[dict[str, object]]],
    summaries: list[SampleRunSummary],
    metrics: dict[str, object],
    run_dir: Path,
) -> str:
    candidate_rows = stage_rows.get("statement_candidates.jsonl", [])
    compile_rows = stage_rows.get("compile_checks.jsonl", [])
    semantic_rows = stage_rows.get("semantic_rank.jsonl", [])
    proof_attempt_rows = stage_rows.get("proof_attempts.jsonl", [])
    proof_rows = stage_rows.get("proof_checks.jsonl", [])
    retrieval_rows = stage_rows.get("mechlib_retrieval.jsonl", [])
    sample_map = {s.sample_id: s for s in samples}
    summary_map = {s.sample_id: s for s in summaries}
    compile_by_sid: dict[str, list[dict[str, object]]] = {}
    for row in compile_rows:
        compile_by_sid.setdefault(str(row["sample_id"]), []).append(row)
    candidates_by_sid: dict[str, list[dict[str, object]]] = {}
    for row in candidate_rows:
        candidates_by_sid.setdefault(str(row["sample_id"]), []).append(row)
    semantic_map = {str(r["sample_id"]): r for r in semantic_rows}
    proof_attempts_by_sid: dict[str, list[dict[str, object]]] = {}
    for row in proof_attempt_rows:
        proof_attempts_by_sid.setdefault(str(row["sample_id"]), []).append(row)
    for sid in proof_attempts_by_sid:
        proof_attempts_by_sid[sid].sort(key=lambda x: _as_int(x.get("attempt_index"), 0))
    proof_map = {str(r["sample_id"]): r for r in proof_rows}
    retrieval_map = {str(r["sample_id"]): r for r in retrieval_rows}

    lines = [
        "# Run README",
        "",
        f"- run_dir: `{run_dir.as_posix()}`",
        f"- total_samples: {metrics.get('num_total_samples', 0)}",
        f"- grounding_success_rate: {metrics.get('grounding_success_rate', 0)}",
        f"- statement_generation_success_rate: {metrics.get('statement_generation_success_rate', 0)}",
        f"- lean_compile_success_rate: {metrics.get('lean_compile_success_rate', 0)}",
        f"- semantic_consistency_pass_rate: {metrics.get('semantic_consistency_pass_rate', 0)}",
        f"- proof_success_rate: {metrics.get('proof_success_rate', 0)}",
        f"- end_to_end_verified_solve_rate: {metrics.get('end_to_end_verified_solve_rate', 0)}",
        "",
        "## Sample Details",
    ]
    for sid, sample in sample_map.items():
        summary = summary_map.get(sid)
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
                "**Lean Candidates**",
                "",
            ]
        )
        retrieval = retrieval_map.get(sid)
        lines.extend(["**MechLib Retrieval**", ""])
        if not retrieval:
            lines.append("- retrieval: None")
        else:
            lines.append(f"- retrieval_enabled: {retrieval.get('enabled')}")
            lines.append(f"- retrieved_count: {retrieval.get('retrieved_count')}")
            context_preview = truncate(str(retrieval.get("retrieval_context") or ""), 1200)
            lines.append(f"- retrieval_context_preview: {context_preview}")
            for item in _as_row_list(retrieval.get("items")):
                lines.append(
                    "- item "
                    f"module={item.get('module')} "
                    f"symbol={item.get('symbol_name')} "
                    f"kind={item.get('kind')} "
                    f"score={item.get('score')} "
                    f"law_tags={item.get('law_tags')}"
                )
                lines.append(f"  - signature: {truncate(str(item.get('declaration_signature') or ''), 240)}")

        lines.extend(["", "**Lean Candidates**", ""])
        for c in candidates_by_sid.get(sid, []):
            cid = str(c.get("candidate_id"))
            comp = next((x for x in compile_by_sid.get(sid, []) if str(x.get("candidate_id")) == cid), None)
            lines.append(
                f"- `{cid}` compile_pass={comp.get('compile_pass') if comp else None}, "
                f"error={comp.get('error_type') if comp else None}, "
                f"backend={comp.get('backend_used') if comp else None}, "
                f"route={comp.get('route_reason') if comp else None}, "
                f"fallback={comp.get('route_fallback_used') if comp else None}, "
                f"log={comp.get('log_path') if comp else None}"
            )
            lines.append("```lean")
            lines.append(str(c.get("lean_header", "import PhysLean")).strip())
            lines.append("")
            lines.append(str(c.get("theorem_decl", "")).strip())
            lines.append("```")

        semantic = semantic_map.get(sid)
        lines.extend(["", "**Semantic Ranking**", ""])
        if not semantic:
            lines.append("- semantic result: None")
        else:
            lines.append(f"- selected_candidate_id: {semantic.get('selected_candidate_id')}")
            lines.append(f"- semantic_pass: {semantic.get('semantic_pass')}")
            lines.append(f"- semantic_error: {semantic.get('error')}")
            ranking = _as_row_list(semantic.get("ranking"))
            for item in ranking:
                lines.append(
                    "- rank_item "
                    f"candidate={item.get('candidate_id')} "
                    f"score={item.get('semantic_score')} "
                    f"score_rule={item.get('semantic_score_rule')} "
                    f"score_llm={item.get('semantic_score_llm')} "
                    f"trivial_goal={item.get('trivial_goal')} "
                    f"target={item.get('target_match')} "
                    f"known={item.get('known_quantity_coverage')} "
                    f"law={item.get('law_match')} "
                    f"unit={item.get('unit_consistency')} "
                    f"assumption={item.get('assumption_consistency')} "
                    f"pass={item.get('semantic_pass')}"
                )
                back_translation = truncate(str(item.get("back_translation_text") or ""), 240)
                reason = truncate(str(item.get("semantic_reason") or ""), 240)
                lines.append(
                    f"  - semantic_source={item.get('semantic_source')} "
                    f"semantic_pass_llm={item.get('semantic_pass_llm')} "
                    f"hard_gate_pass={item.get('hard_gate_pass')} "
                    f"hard_gate_reasons={item.get('hard_gate_reasons')} "
                    f"llm_error={item.get('semantic_llm_error')}"
                )
                lines.append(f"  - back_translation: {back_translation}")
                lines.append(f"  - reason: {reason}")

        lines.extend(["", "**Proof Attempts**", ""])
        attempts = proof_attempts_by_sid.get(sid, [])
        if not attempts:
            lines.append("- proof attempts: None")
        else:
            for a in attempts:
                lines.append(
                    f"- attempt={a.get('attempt_index')} parse_ok={a.get('parse_ok')} "
                    f"compile_pass={a.get('compile_pass')} strict_pass={a.get('strict_pass')} "
                    f"error={a.get('error_type')} "
                    f"backend={a.get('backend_used')} "
                    f"route={a.get('route_reason')} "
                    f"fallback={a.get('route_fallback_used')} "
                    f"log={a.get('log_path')}"
                )
                lines.append(f"  - stderr_digest: {truncate(str(a.get('stderr_digest') or ''), 240)}")
                lines.append("```lean")
                lines.append(str(a.get("proof_body", "")).strip())
                lines.append("```")

        proof = proof_map.get(sid)
        lines.extend(
            [
                "",
                "**Proof Final Check**",
                "",
                f"- selected_candidate_id: {proof.get('selected_candidate_id') if proof else None}",
                f"- proof_success: {proof.get('proof_success') if proof else None}",
                f"- attempts_used: {proof.get('attempts_used') if proof else None}",
                f"- proof_error_type: {proof.get('error_type') if proof else None}",
                f"- proof_backend_used: {proof.get('backend_used') if proof else None}",
                f"- final_log_path: {proof.get('final_log_path') if proof else None}",
                "",
                "**Result**",
                "",
                f"- grounding_ok: {summary.grounding_ok if summary else None}",
                f"- statement_generation_ok: {summary.statement_generation_ok if summary else None}",
                f"- compile_ok: {summary.compile_ok if summary else None}",
                f"- semantic_ok: {summary.semantic_ok if summary else None}",
                f"- proof_ok: {summary.proof_ok if summary else None}",
                f"- end_to_end_ok: {summary.end_to_end_ok if summary else None}",
                f"- final_error_type: {summary.final_error_type if summary else None}",
                "",
            ]
        )
    return "\n".join(lines) + "\n"


def run_pipeline(args: argparse.Namespace) -> int:
    cfg = load_config(Path(args.config))
    if args.limit is not None:
        cfg.dataset.limit = args.limit
    if args.tag:
        cfg.output.tag = args.tag

    run_dir = create_run_dir(Path(cfg.output.runs_dir), cfg.output.tag)
    latest_dir = Path(cfg.output.output_dir)
    print(f"run_dir={run_dir}")
    print(f"latest_dir={latest_dir}")

    stage_rows: dict[str, list[dict[str, object]]] = {
        "problem_ir.jsonl": [],
        "mechlib_retrieval.jsonl": [],
        "statement_candidates.jsonl": [],
        "compile_checks.jsonl": [],
        "semantic_rank.jsonl": [],
        "proof_attempts.jsonl": [],
        "proof_checks.jsonl": [],
        "sample_summary.jsonl": [],
    }

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
                )
            )
        module_f = ModuleF()
        metrics, analysis = module_f.build(
            summaries=dry_summaries,
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

    model_client = build_model_client(cfg.model)
    prompt_dir = Path(cfg.prompts.dir)
    module_a = ModuleA(model_client, cfg.model.model_id, prompt_dir / cfg.prompts.a_extract_ir)
    module_b = ModuleB(model_client, prompt_dir / cfg.prompts.b_generate_statements)
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
    module_c = ModuleC(lean_runner)
    module_d = ModuleD(model_client, prompt_dir / cfg.prompts.d_semantic_rank, cfg.semantic.pass_threshold)
    module_e = ModuleE(
        model_client=model_client,
        lean_runner=lean_runner,
        prompt_generate_path=prompt_dir / cfg.prompts.e_generate_proof,
        prompt_repair_path=prompt_dir / cfg.prompts.e_repair_proof,
        max_attempts=cfg.proof.max_attempts,
    )
    module_f = ModuleF()

    retriever: MechLibRetriever | None = None
    if cfg.knowledge.enabled:
        retriever = MechLibRetriever(
            mechlib_dir=Path(cfg.knowledge.mechlib_dir),
            scope=cfg.knowledge.scope,
            top_k=cfg.knowledge.top_k,
            cache_path=Path(cfg.knowledge.cache_path),
        )
    inject_set = {m.strip().upper() for m in cfg.knowledge.inject_modules}

    preflight_ok = True
    preflight_error: str | None = None
    preflight_message = "skip"
    if cfg.lean.enabled and cfg.lean.preflight_enabled:
        preflight_ok, preflight_error, preflight_message = lean_runner.preflight()
        print(f"lean_preflight={preflight_ok}, message={preflight_message}")

    grounding_rows = []
    compile_rows = []
    semantic_rows = []
    proof_rows = []
    summaries: list[SampleRunSummary] = []

    for idx, sample in enumerate(samples, start=1):
        print(f"[{idx}/{len(samples)}] sample={sample.sample_id}")
        if sample.skip_reason:
            summaries.append(
                SampleRunSummary(
                    sample_id=sample.sample_id,
                    grounding_ok=False,
                    statement_generation_ok=False,
                    compile_ok=False,
                    semantic_ok=False,
                    proof_ok=False,
                    end_to_end_ok=False,
                    final_error_type=sample.skip_reason,
                    notes="dataset skip",
                )
            )
            continue

        if not preflight_ok:
            summaries.append(
                SampleRunSummary(
                    sample_id=sample.sample_id,
                    grounding_ok=False,
                    statement_generation_ok=False,
                    compile_ok=False,
                    semantic_ok=False,
                    proof_ok=False,
                    end_to_end_ok=False,
                    final_error_type=preflight_error,
                    notes=preflight_message,
                )
            )
            continue

        grounding = module_a.run(sample)
        grounding_rows.append(grounding)
        stage_rows["problem_ir.jsonl"].append(to_row(grounding))

        mechlib_items: list[dict[str, object]] = []
        mechlib_context = "(none)"
        if retriever and grounding.parse_ok:
            mechlib_items = retriever.retrieve(
                problem_text=sample.problem_text,
                problem_ir=grounding.problem_ir,
                top_k=cfg.knowledge.top_k,
            )
            mechlib_context = retriever.render_context(mechlib_items)
        stage_rows["mechlib_retrieval.jsonl"].append(
            {
                "sample_id": sample.sample_id,
                "enabled": bool(retriever),
                "retrieved_count": len(mechlib_items),
                "items": mechlib_items,
                "retrieval_context": mechlib_context,
            }
        )

        if not grounding.parse_ok:
            grounding_error = grounding.error or "visual_grounding_failure"
            summaries.append(
                SampleRunSummary(
                    sample_id=sample.sample_id,
                    grounding_ok=False,
                    statement_generation_ok=False,
                    compile_ok=False,
                    semantic_ok=False,
                    proof_ok=False,
                    end_to_end_ok=False,
                    final_error_type=grounding_error,
                    notes="module A failed",
                )
            )
            continue

        b_context = mechlib_context if "B" in inject_set else "(none)"
        candidates = module_b.run(grounding, mechlib_context=b_context)
        stage_rows["statement_candidates.jsonl"].extend(to_row(c) for c in candidates)
        statement_generation_ok = len(candidates) == 4

        compile_results = module_c.run(sample.sample_id, candidates, run_dir=run_dir)
        compile_rows.extend(compile_results)
        stage_rows["compile_checks.jsonl"].extend(to_row(r) for r in compile_results)
        compile_ok = any(r.compile_pass for r in compile_results)

        d_context = mechlib_context if "D" in inject_set else "(none)"
        semantic = module_d.run(
            grounding=grounding,
            candidates=candidates,
            compile_checks=compile_results,
            problem_text=sample.problem_text,
            mechlib_context=d_context,
        )
        semantic_rows.append(semantic)
        stage_rows["semantic_rank.jsonl"].append(to_row(semantic))

        selected_candidate = None
        if semantic.selected_candidate_id:
            selected_candidate = next(
                (c for c in candidates if c.candidate_id == semantic.selected_candidate_id),
                None,
            )

        e_context = mechlib_context if "E" in inject_set else "(none)"
        proof_attempts, proof_check = module_e.run(
            grounding=grounding,
            selected_candidate=selected_candidate,
            run_dir=run_dir,
            mechlib_context=e_context,
        )
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
        if not end_to_end:
            final_error = (
                proof_check.error_type
                or semantic.error
                or next((r.error_type for r in compile_results if not r.compile_pass), None)
                or grounding.error
                or "proof_search_failure"
            )

        summaries.append(
            SampleRunSummary(
                sample_id=sample.sample_id,
                grounding_ok=grounding.parse_ok,
                statement_generation_ok=statement_generation_ok,
                compile_ok=compile_ok,
                semantic_ok=semantic.semantic_pass,
                proof_ok=proof_check.proof_success,
                end_to_end_ok=end_to_end,
                final_error_type=final_error,
                notes=None,
            )
        )

    stage_rows["sample_summary.jsonl"] = [to_row(s) for s in summaries]
    metrics, analysis = module_f.build(
        summaries=summaries,
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
        },
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
