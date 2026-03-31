from __future__ import annotations

import argparse
import json
import os
import sys
import textwrap
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
from mech_pipeline.types import (
    CompileCheckResult,
    ProofCheckResult,
    SampleRunSummary,
    SemanticRankResult,
    StatementCandidate,
)
from mech_pipeline.utils import normalize_lean_text, safe_stem, to_row, truncate


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


def _row_round_index(row: object) -> int:
    if isinstance(row, dict):
        return _as_int(row.get("round_index"), 0)
    return _as_int(getattr(row, "round_index", 0), 0)


def _final_round_by_sample(summaries: list[SampleRunSummary]) -> dict[str, int]:
    return {s.sample_id: int(s.final_round_index) for s in summaries}


def _truncate_json(value: object, limit: int = 1200) -> str:
    return truncate(json.dumps(value, ensure_ascii=False, indent=2), limit)


def _build_revision_feedback(
    *,
    retry_reason: str,
    candidates: list[StatementCandidate],
    compile_results: list[CompileCheckResult],
    semantic: SemanticRankResult,
) -> str:
    compile_map = {row.candidate_id: row for row in compile_results}
    ranking_map = {
        str(item.get("candidate_id")): item
        for item in semantic.ranking
        if isinstance(item, dict) and str(item.get("candidate_id") or "").strip()
    }
    feedback_rows: list[dict[str, object]] = []
    compile_pass_count = sum(1 for row in compile_results if row.compile_pass)
    for candidate in candidates:
        compile_row = compile_map.get(candidate.candidate_id)
        row: dict[str, object] = {
            "candidate_id": candidate.candidate_id,
            "theorem_decl": candidate.theorem_decl,
            "plan": candidate.plan,
            "compile_pass": bool(compile_row.compile_pass) if compile_row else False,
            "error_type": compile_row.error_type if compile_row else "compile_not_run",
            "stderr_digest": compile_row.stderr_digest if compile_row else "",
            "backend_used": compile_row.backend_used if compile_row else None,
            "route_reason": compile_row.route_reason if compile_row else None,
            "route_fallback_used": bool(compile_row.route_fallback_used) if compile_row else False,
        }
        semantic_row = ranking_map.get(candidate.candidate_id)
        if semantic_row is not None:
            row.update(
                {
                    "semantic_score": semantic_row.get("semantic_score"),
                    "semantic_pass": semantic_row.get("semantic_pass"),
                    "semantic_reason": semantic_row.get("semantic_reason"),
                    "back_translation_text": semantic_row.get("back_translation_text"),
                    "hard_gate_reasons": semantic_row.get("hard_gate_reasons"),
                    "semantic_rank_score": semantic_row.get("semantic_rank_score"),
                }
            )
        elif not row["compile_pass"]:
            row["semantic_note"] = "semantic_not_evaluated_due_to_compile_fail"
        else:
            row["semantic_note"] = "semantic_not_evaluated"
        feedback_rows.append(row)

    payload = {
        "retry_reason": retry_reason,
        "compile_pass_count": compile_pass_count,
        "semantic_pass": semantic.semantic_pass,
        "selected_candidate_id": semantic.selected_candidate_id,
        "candidates": feedback_rows,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _lean_export_relpath(start: Path, target: Path) -> str:
    return os.path.relpath(target, start).replace("\\", "/")


def _detect_lake_config(package_dir: Path) -> str | None:
    if (package_dir / "lakefile.toml").exists():
        return "lakefile.toml"
    if (package_dir / "lakefile.lean").exists():
        return "lakefile.lean"
    return None


def _is_valid_lake_name(name: str) -> bool:
    if not name or not name[0].isalpha():
        return False
    return all(ch.isalnum() or ch == "_" for ch in name)


def _lean_declaration_only(text: str) -> str:
    out = str(text or "").strip()
    if out.startswith("```"):
        out = out.replace("```lean", "").replace("```", "").strip()
    if ":=" in out:
        out = out.split(":=", 1)[0].rstrip()
    if out.endswith(" by"):
        out = out[:-3].rstrip()
    return normalize_lean_text(out)


def _prepare_proof_body(text: str) -> str:
    out = str(text or "").strip()
    if out.startswith("```"):
        out = out.replace("```lean", "").replace("```", "").strip()
    out = out.replace("\r\n", "\n")
    if out.startswith("by\n"):
        out = out[3:]
    elif out.startswith("by "):
        out = out[3:].lstrip()
    elif out == "by":
        out = ""
    out = textwrap.dedent(normalize_lean_text(out)).strip("\n")
    return out


def _indent_lean(text: str, spaces: int = 2) -> str:
    prefix = " " * spaces
    return "\n".join(prefix + line if line.strip() else prefix for line in text.splitlines())


def _build_lean_export_workspace_files(*, cfg: PipelineConfig, export_root: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    mechlib_dir = Path(cfg.lean.mechlib_dir).resolve()
    physlean_dir = Path(cfg.lean.physlean_dir).resolve()
    packages_dir = physlean_dir / ".lake" / "packages"
    toolchain_path = mechlib_dir / "lean-toolchain"
    if not toolchain_path.exists():
        toolchain_path = physlean_dir / "lean-toolchain"

    readme_lines = [
        "# Lean Exports",
        "",
        "Open this `lean_exports/` folder as a Lean workspace.",
        "Files under `problems/` are generated one-per-sample artifacts from the pipeline run.",
        "",
        f"- mechlib_dir: `{mechlib_dir.as_posix()}`",
        f"- physlean_dir: `{physlean_dir.as_posix()}`",
    ]

    if not mechlib_dir.exists():
        readme_lines.extend(["", "- workspace_status: skipped", "  MechLib directory was not found."])
        files["lean_exports/README.md"] = "\n".join(readme_lines) + "\n"
        return files

    toolchain = "leanprover/lean4:v4.26.0"
    if toolchain_path.exists():
        toolchain = toolchain_path.read_text(encoding="utf-8", errors="replace").strip() or toolchain

    lakefile = "\n".join(
        [
            'name = "RunArtifacts"',
            'version = "0.1.0"',
            'defaultTargets = ["RunArtifacts"]',
            "",
            "[[require]]",
            'name = "MechLib"',
            f'path = "{_lean_export_relpath(export_root, mechlib_dir)}"',
            "",
            "[[lean_lib]]",
            'name = "RunArtifacts"',
            'srcDir = "."',
            "",
        ]
    )

    files["lean_exports/lean-toolchain"] = toolchain + "\n"
    files["lean_exports/lakefile.toml"] = lakefile
    files["lean_exports/RunArtifacts.lean"] = "namespace RunArtifacts\n\nend RunArtifacts\n"

    manifest_packages: list[dict[str, object]] = [
        {
            "type": "path",
            "scope": "",
            "name": "MechLib",
            "manifestFile": "lake-manifest.json",
            "inherited": False,
            "dir": _lean_export_relpath(export_root, mechlib_dir),
            "configFile": "lakefile.toml",
        }
    ]
    if packages_dir.exists():
        mathlib_dir = packages_dir / "mathlib"
        mathlib_config = _detect_lake_config(mathlib_dir)
        if mathlib_dir.exists() and mathlib_config:
            manifest_packages.append(
                {
                    "type": "path",
                    "scope": "",
                    "name": "mathlib",
                    "manifestFile": "lake-manifest.json",
                    "inherited": True,
                    "dir": _lean_export_relpath(export_root, mathlib_dir.resolve()),
                    "configFile": mathlib_config,
                }
            )
        transitive_manifest_path = mathlib_dir / "lake-manifest.json"
        added_names = {str(pkg.get("name") or "") for pkg in manifest_packages}
        if transitive_manifest_path.exists():
            transitive_manifest = json.loads(transitive_manifest_path.read_text(encoding="utf-8"))
            for pkg in transitive_manifest.get("packages", []):
                if not isinstance(pkg, dict):
                    continue
                name = str(pkg.get("name") or "").strip()
                if not _is_valid_lake_name(name) or name in added_names:
                    continue
                package_dir = packages_dir / name
                config_file = _detect_lake_config(package_dir)
                if not package_dir.exists() or not config_file:
                    continue
                manifest_packages.append(
                    {
                        "type": "path",
                        "scope": "",
                        "name": name,
                        "manifestFile": "lake-manifest.json",
                        "inherited": True,
                        "dir": _lean_export_relpath(export_root, package_dir.resolve()),
                        "configFile": config_file,
                    }
                )
                added_names.add(name)
        elif mathlib_dir.exists():
            for package_dir in sorted(packages_dir.iterdir(), key=lambda p: p.name.lower()):
                if not package_dir.is_dir():
                    continue
                name = package_dir.name
                if not _is_valid_lake_name(name) or name in added_names:
                    continue
                config_file = _detect_lake_config(package_dir)
                if not config_file:
                    continue
                manifest_packages.append(
                    {
                        "type": "path",
                        "scope": "",
                        "name": name,
                        "manifestFile": "lake-manifest.json",
                        "inherited": True,
                        "dir": _lean_export_relpath(export_root, package_dir.resolve()),
                        "configFile": config_file,
                    }
                )
                added_names.add(name)
        manifest = {
            "version": "1.1.0",
            "packagesDir": ".lake/packages",
            "packages": manifest_packages,
            "name": "RunArtifacts",
            "lakeDir": ".lake",
        }
        files["lean_exports/lake-manifest.json"] = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
        readme_lines.extend(["", "- workspace_status: ready", "- manifest_mode: local_path_dependencies"])
    else:
        readme_lines.extend(["", "- workspace_status: partial", "  PhysLean package cache was not found, so no manifest was generated."])
    files["lean_exports/README.md"] = "\n".join(readme_lines) + "\n"
    return files


def _render_problem_lean_file(
    *,
    sample,
    summary: SampleRunSummary | None,
    candidate_row: dict[str, object] | None,
    semantic_row: dict[str, object] | None,
    proof_row: dict[str, object] | None,
    attempt_row: dict[str, object] | None,
) -> str:
    sample_name = str(sample.meta.get("name") or sample.sample_id)
    header = normalize_lean_text(str((candidate_row or {}).get("lean_header") or "import MechLib")).strip()
    theorem_decl = ""
    if candidate_row and candidate_row.get("theorem_decl"):
        theorem_decl = str(candidate_row["theorem_decl"])
    elif semantic_row and semantic_row.get("selected_theorem_decl"):
        theorem_decl = str(semantic_row["selected_theorem_decl"])
    decl = _lean_declaration_only(theorem_decl)

    proof_ok = bool((proof_row or {}).get("proof_success"))
    attempts_used = _as_int((proof_row or {}).get("attempts_used"), 0)
    final_error = str((proof_row or {}).get("error_type") or (summary.final_error_type if summary else "") or "").strip()
    proof_body = _prepare_proof_body(str((attempt_row or {}).get("proof_body") or ""))
    selected_candidate_id = str(
        (proof_row or {}).get("selected_candidate_id")
        or (semantic_row or {}).get("selected_candidate_id")
        or (candidate_row or {}).get("candidate_id")
        or ""
    )

    artifact_status = "verified" if proof_ok and proof_body else "selected_statement_unverified"
    comment_lines = [
        "Generated by mech_pipeline.",
        f"sample_id: {sample.sample_id}",
        f"sample_name: {sample_name}",
        f"artifact_status: {artifact_status}",
        f"final_round_index: {summary.final_round_index if summary else 0}",
        f"selected_candidate_id: {selected_candidate_id or 'none'}",
        f"semantic_ok: {summary.semantic_ok if summary else None}",
        f"proof_ok: {summary.proof_ok if summary else None}",
        f"attempts_used: {attempts_used}",
        f"final_error_type: {final_error or 'none'}",
        f"final_log_path: {str((proof_row or {}).get('final_log_path') or '') or 'none'}",
    ]

    parts = ["/-", *comment_lines, "-/"]
    if header:
        parts.extend(["", header])

    if decl:
        if proof_ok and proof_body:
            parts.extend(["", f"{decl} := by", _indent_lean(proof_body)])
        else:
            parts.extend(
                [
                    "",
                    f"{decl} := by",
                    "  sorry",
                ]
            )
            if final_error:
                parts.extend(["", "/- Unverified artifact summary", f"{final_error}", "-/"])
            if proof_body:
                parts.extend(["", "/- Last attempted proof body", proof_body, "-/"])
    else:
        parts.extend(["", "/- No selected theorem declaration was available for this sample. -/"])
    return "\n".join(parts).rstrip() + "\n"


def _build_lean_export_files(
    *,
    cfg: PipelineConfig,
    samples,
    stage_rows: dict[str, list[dict[str, object]]],
    summaries: list[SampleRunSummary],
    run_dir: Path,
) -> dict[str, str]:
    export_root = run_dir / "lean_exports"
    files = _build_lean_export_workspace_files(cfg=cfg, export_root=export_root)

    summary_map = {row.sample_id: row for row in summaries}
    final_round_map = _final_round_by_sample(summaries)
    candidate_rows = stage_rows.get("statement_candidates.jsonl", [])
    semantic_rows = stage_rows.get("semantic_rank.jsonl", [])
    proof_rows = stage_rows.get("proof_checks.jsonl", [])
    proof_attempt_rows = stage_rows.get("proof_attempts.jsonl", [])

    candidate_map: dict[tuple[str, int, str], dict[str, object]] = {}
    candidates_by_sid_round: dict[tuple[str, int], list[dict[str, object]]] = {}
    for row in candidate_rows:
        sid = str(row.get("sample_id") or "")
        round_index = _as_int(row.get("round_index"), 0)
        cid = str(row.get("candidate_id") or "")
        candidate_map[(sid, round_index, cid)] = row
        candidates_by_sid_round.setdefault((sid, round_index), []).append(row)

    semantic_map = {
        (str(row.get("sample_id") or ""), _as_int(row.get("round_index"), 0)): row for row in semantic_rows
    }
    proof_map = {str(row.get("sample_id") or ""): row for row in proof_rows}
    attempts_by_sid: dict[str, list[dict[str, object]]] = {}
    for row in proof_attempt_rows:
        attempts_by_sid.setdefault(str(row.get("sample_id") or ""), []).append(row)
    for sid in attempts_by_sid:
        attempts_by_sid[sid].sort(key=lambda x: _as_int(x.get("attempt_index"), 0))

    index_rows: list[dict[str, object]] = []
    for sample in samples:
        sid = sample.sample_id
        summary = summary_map.get(sid)
        final_round = final_round_map.get(sid, 0)
        semantic_row = semantic_map.get((sid, final_round))
        proof_row = proof_map.get(sid)

        selected_candidate_id = str(
            (proof_row or {}).get("selected_candidate_id")
            or (semantic_row or {}).get("selected_candidate_id")
            or ""
        )
        candidate_row = candidate_map.get((sid, final_round, selected_candidate_id))
        if candidate_row is None:
            fallback_rows = sorted(
                candidates_by_sid_round.get((sid, final_round), []),
                key=lambda row: str(row.get("candidate_id") or ""),
            )
            candidate_row = fallback_rows[0] if fallback_rows else None

        attempts = attempts_by_sid.get(sid, [])
        attempt_row = next((row for row in reversed(attempts) if bool(row.get("strict_pass"))), None)
        if attempt_row is None and attempts:
            attempt_row = attempts[-1]

        file_name = safe_stem(str(sample.meta.get("name") or sample.sample_id)) + ".lean"
        rel_path = f"lean_exports/problems/{file_name}"
        files[rel_path] = _render_problem_lean_file(
            sample=sample,
            summary=summary,
            candidate_row=candidate_row,
            semantic_row=semantic_row,
            proof_row=proof_row,
            attempt_row=attempt_row,
        )
        index_rows.append(
            {
                "sample_id": sid,
                "sample_name": str(sample.meta.get("name") or sample.sample_id),
                "file": rel_path,
                "final_round_index": final_round,
                "selected_candidate_id": selected_candidate_id or None,
                "semantic_ok": summary.semantic_ok if summary else None,
                "proof_ok": summary.proof_ok if summary else None,
                "final_error_type": summary.final_error_type if summary else None,
            }
        )

    files["lean_exports/index.json"] = json.dumps(index_rows, ensure_ascii=False, indent=2) + "\n"
    return files


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
    final_round_map = _final_round_by_sample(summaries)
    compile_by_sid_round: dict[str, dict[int, list[dict[str, object]]]] = {}
    for row in compile_rows:
        sid = str(row["sample_id"])
        round_index = _as_int(row.get("round_index"), 0)
        compile_by_sid_round.setdefault(sid, {}).setdefault(round_index, []).append(row)
    candidates_by_sid_round: dict[str, dict[int, list[dict[str, object]]]] = {}
    for row in candidate_rows:
        sid = str(row["sample_id"])
        round_index = _as_int(row.get("round_index"), 0)
        candidates_by_sid_round.setdefault(sid, {}).setdefault(round_index, []).append(row)
    semantic_by_sid_round: dict[str, dict[int, dict[str, object]]] = {}
    for row in semantic_rows:
        sid = str(row["sample_id"])
        round_index = _as_int(row.get("round_index"), 0)
        semantic_by_sid_round.setdefault(sid, {})[round_index] = row
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
        f"- lean_exports_dir: `{(run_dir / 'lean_exports').as_posix()}`",
        f"- total_samples: {metrics.get('num_total_samples', 0)}",
        f"- grounding_success_rate: {metrics.get('grounding_success_rate', 0)}",
        f"- statement_generation_success_rate: {metrics.get('statement_generation_success_rate', 0)}",
        f"- lean_compile_success_rate: {metrics.get('lean_compile_success_rate', 0)}",
        f"- semantic_consistency_pass_rate: {metrics.get('semantic_consistency_pass_rate', 0)}",
        f"- proof_success_rate: {metrics.get('proof_success_rate', 0)}",
        f"- end_to_end_verified_solve_rate: {metrics.get('end_to_end_verified_solve_rate', 0)}",
        f"- mechlib_header_rate: {metrics.get('mechlib_header_rate', 0)}",
        f"- mechlib_compile_pass_rate: {metrics.get('mechlib_compile_pass_rate', 0)}",
        f"- selected_mechlib_candidate_rate: {metrics.get('selected_mechlib_candidate_rate', 0)}",
        f"- feedback_loop_used_rate: {metrics.get('feedback_loop_used_rate', 0)}",
        "",
        "## MechLib Adoption",
        "",
        "- definition:",
        "  - mechlib_header_rate = ratio of statement candidates whose header includes `import MechLib`",
        "  - mechlib_compile_pass_rate = ratio of compile checks that pass on MechLib backend",
        "  - selected_mechlib_candidate_rate = ratio of D-selected candidates that used MechLib backend",
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
            lines.append(f"- domain_from_a: {retrieval.get('domain_from_a')}")
            lines.append(f"- selected_tags: {retrieval.get('selected_tags')}")
            lines.append(f"- summary_items_count: {retrieval.get('summary_items_count')}")
            lines.append(f"- source_items_count: {retrieval.get('source_items_count')}")
            lines.append(f"- final_context_chars: {retrieval.get('final_context_chars')}")
            lines.append(f"- import_hints: {retrieval.get('import_hints')}")
            lines.append(f"- proof_style_examples: {retrieval.get('proof_style_examples')}")
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
        lines.append(f"- feedback_loop_used: {summary.feedback_loop_used if summary else None}")
        lines.append(f"- final_round_index: {final_round_map.get(sid, 0)}")
        round_candidates_map = candidates_by_sid_round.get(sid, {})
        round_compile_map = compile_by_sid_round.get(sid, {})
        round_semantic_map = semantic_by_sid_round.get(sid, {})
        round_ids = sorted(set(round_candidates_map) | set(round_compile_map) | set(round_semantic_map))
        for round_index in round_ids:
            lines.extend(["", f"**Round {round_index}**", ""])
            sample_candidates = round_candidates_map.get(round_index, [])
            mechlib_count = sum(
                1 for c in sample_candidates if "import MechLib" in str(c.get("lean_header") or "")
            )
            physlean_count = sum(
                1 for c in sample_candidates if "import PhysLean" in str(c.get("lean_header") or "")
            )
            lines.append(
                f"- backend_distribution: mechlib_headers={mechlib_count}, physlean_headers={physlean_count}, total={len(sample_candidates)}"
            )
            compile_round = round_compile_map.get(round_index, [])
            for c in sample_candidates:
                cid = str(c.get("candidate_id"))
                comp = next((x for x in compile_round if str(x.get("candidate_id")) == cid), None)
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
                lines.append(f"  - plan: {truncate(str(c.get('plan') or ''), 240)}")

            semantic = round_semantic_map.get(round_index)
            lines.extend(["", "**Semantic Ranking**", ""])
            if not semantic:
                lines.append("- semantic result: None")
            else:
                lines.append(f"- selected_candidate_id: {semantic.get('selected_candidate_id')}")
                lines.append(f"- selected_backend: {semantic.get('selected_backend')}")
                lines.append(f"- selected_route_reason: {semantic.get('selected_route_reason')}")
                lines.append(f"- selected_route_fallback_used: {semantic.get('selected_route_fallback_used')}")
                lines.append(f"- semantic_pass: {semantic.get('semantic_pass')}")
                lines.append(f"- semantic_error: {semantic.get('error')}")
                lines.append(f"- retry_triggered: {semantic.get('retry_triggered')}")
                lines.append(f"- retry_reason: {semantic.get('retry_reason')}")
                if semantic.get("retry_feedback_summary"):
                    lines.append(
                        f"- retry_feedback_summary: {truncate(str(semantic.get('retry_feedback_summary') or ''), 800)}"
                    )
                ranking = _as_row_list(semantic.get("ranking"))
                for item in ranking:
                    lines.append(
                        "- rank_item "
                        f"candidate={item.get('candidate_id')} "
                        f"score={item.get('semantic_score')} "
                        f"rank_score={item.get('semantic_rank_score')} "
                        f"score_rule={item.get('semantic_score_rule')} "
                        f"score_llm={item.get('semantic_score_llm')} "
                        f"trivial_goal={item.get('trivial_goal')} "
                        f"target={item.get('target_match')} "
                        f"known={item.get('known_quantity_coverage')} "
                        f"law={item.get('law_match')} "
                        f"unit={item.get('unit_consistency')} "
                        f"assumption={item.get('assumption_consistency')} "
                        f"backend={item.get('backend_used')} "
                        f"route={item.get('route_reason')} "
                        f"fallback={item.get('route_fallback_used')} "
                        f"backend_bias={item.get('backend_bias')} "
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
                lines.append(f"  - plan: {truncate(str(a.get('plan') or ''), 240)}")
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

    model_client = build_model_client(cfg.model)
    prompt_dir = Path(cfg.prompts.dir)
    module_a = ModuleA(model_client, cfg.model.model_id, prompt_dir / cfg.prompts.a_extract_ir)
    module_b = ModuleB(
        model_client,
        prompt_dir / cfg.prompts.b_generate_statements,
        revise_prompt_path=prompt_dir / cfg.prompts.b_revise_statements,
        library_target=cfg.statement.library_target,
    )
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

    def _run_statement_round(
        *,
        round_index: int,
        grounding,
        sample,
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
                    final_round_index=0,
                    feedback_loop_used=False,
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
                    final_round_index=0,
                    feedback_loop_used=False,
                )
            )
            continue

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
                    final_round_index=0,
                    feedback_loop_used=False,
                )
            )
            continue

        feedback_loop_used = False
        final_round_index = 0
        retry_reason: str | None = None

        candidates, compile_results, semantic = _run_statement_round(
            round_index=0,
            grounding=grounding,
            sample=sample,
            mechlib_context=mechlib_context,
        )
        semantic.retry_triggered = False
        semantic.retry_reason = None
        semantic.retry_feedback_summary = None

        if cfg.statement.feedback_loop_enabled and cfg.statement.max_revision_rounds > 0:
            if not any(r.compile_pass for r in compile_results):
                retry_reason = "no_compile_pass"
            elif not semantic.semantic_pass:
                retry_reason = "semantic_fail"

        if retry_reason:
            feedback_loop_used = True
            semantic.retry_triggered = True
            semantic.retry_reason = retry_reason
            semantic.retry_feedback_summary = _build_revision_feedback(
                retry_reason=retry_reason,
                candidates=candidates,
                compile_results=compile_results,
                semantic=semantic,
            )
            semantic_rows.append(semantic)
            stage_rows["semantic_rank.jsonl"].append(to_row(semantic))
            final_round_index = 1
            candidates, compile_results, semantic = _run_statement_round(
                round_index=1,
                grounding=grounding,
                sample=sample,
                mechlib_context=mechlib_context,
                revision_feedback=semantic.retry_feedback_summary,
                previous_candidates=candidates,
            )
            semantic.retry_triggered = False
            semantic.retry_reason = None
            semantic.retry_feedback_summary = None
        semantic_rows.append(semantic)
        stage_rows["semantic_rank.jsonl"].append(to_row(semantic))

        statement_generation_ok = len(candidates) == 4
        compile_ok = any(r.compile_pass for r in compile_results)

        selected_candidate = None
        if semantic.selected_candidate_id:
            selected_candidate = next(
                (c for c in candidates if c.candidate_id == semantic.selected_candidate_id),
                None,
            )

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
        if not end_to_end:
            compile_error = next((r.error_type for r in compile_results if not r.compile_pass), None)
            if not grounding.parse_ok:
                final_error = grounding.error or "visual_grounding_failure"
            elif not statement_generation_ok:
                final_error = "statement_generation_parse_failed"
            elif not compile_ok:
                final_error = compile_error or "elaboration_failure"
            elif not semantic.semantic_pass:
                final_error = semantic.error or "semantic_drift"
            else:
                final_error = proof_check.error_type or "proof_search_failure"

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
                final_round_index=final_round_index,
                feedback_loop_used=feedback_loop_used,
            )
        )

    stage_rows["sample_summary.jsonl"] = [to_row(s) for s in summaries]
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
