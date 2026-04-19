from __future__ import annotations

import json
import os
import textwrap
from pathlib import Path

from mech_pipeline.config import PipelineConfig
from mech_pipeline.types import CompileCheckResult, SampleRunSummary, SemanticRankResult, StatementCandidate
from mech_pipeline.utils import normalize_lean_text, safe_stem, truncate


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


def _final_round_by_sample(summaries: list[SampleRunSummary]) -> dict[str, int]:
    return {s.sample_id: int(s.final_round_index) for s in summaries}


def build_revision_feedback(
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
            "supporting_facts": candidate.supporting_facts,
            "fact_sources": candidate.fact_sources,
            "library_symbols_used": candidate.library_symbols_used,
            "grounding_explanation": candidate.grounding_explanation,
            "unsupported_claims": candidate.unsupported_claims,
            "compile_pass": bool(compile_row.compile_pass) if compile_row else False,
            "error_type": compile_row.error_type if compile_row else "compile_not_run",
            "sub_error_type": compile_row.sub_error_type if compile_row else None,
            "failure_tags": list(compile_row.failure_tags) if compile_row else [],
            "failure_summary": compile_row.failure_summary if compile_row else None,
            "stderr_digest": compile_row.stderr_digest if compile_row else "",
            "stderr_excerpt": compile_row.stderr_excerpt if compile_row else None,
            "backend_used": compile_row.backend_used if compile_row else None,
            "route_reason": compile_row.route_reason if compile_row else None,
            "route_fallback_used": bool(compile_row.route_fallback_used) if compile_row else False,
            "error_line": compile_row.error_line if compile_row else None,
            "error_message": compile_row.error_message if compile_row else None,
            "error_snippet": compile_row.error_snippet if compile_row else None,
        }
        semantic_row = ranking_map.get(candidate.candidate_id)
        if semantic_row is not None:
            row.update(
                {
                    "semantic_score": semantic_row.get("semantic_score"),
                    "semantic_pass": semantic_row.get("semantic_pass"),
                    "semantic_sub_error_type": semantic_row.get("sub_error_type"),
                    "semantic_failure_tags": semantic_row.get("failure_tags"),
                    "semantic_failure_summary": semantic_row.get("failure_summary"),
                    "semantic_reason": semantic_row.get("semantic_reason"),
                    "back_translation_text": semantic_row.get("back_translation_text"),
                    "mismatch_fields": semantic_row.get("mismatch_fields"),
                    "missing_or_incorrect_translations": semantic_row.get("missing_or_incorrect_translations"),
                    "suggested_fix_direction": semantic_row.get("suggested_fix_direction"),
                    "hard_gate_reasons": semantic_row.get("hard_gate_reasons"),
                    "semantic_rank_score": semantic_row.get("semantic_rank_score"),
                    "library_grounding_score": semantic_row.get("library_grounding_score"),
                    "grounded_library_symbols": semantic_row.get("grounded_library_symbols"),
                    "grounding_gap_summary": semantic_row.get("grounding_gap_summary"),
                    "direct_translation": semantic_row.get("direct_translation"),
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

    mathlib_dir: Path | None = None
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
        detected_mathlib_dir = packages_dir / "mathlib"
        detected_mathlib_config = _detect_lake_config(detected_mathlib_dir)
        if detected_mathlib_dir.exists() and detected_mathlib_config:
            mathlib_dir = detected_mathlib_dir
            manifest_packages.append(
                {
                    "type": "path",
                    "scope": "",
                    "name": "mathlib",
                    "manifestFile": "lake-manifest.json",
                    "inherited": True,
                    "dir": _lean_export_relpath(export_root, mathlib_dir.resolve()),
                    "configFile": detected_mathlib_config,
                }
            )
        transitive_manifest_path = detected_mathlib_dir / "lake-manifest.json"
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
        elif detected_mathlib_dir.exists():
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

    lakefile_lines = [
        'name = "RunArtifacts"',
        'version = "0.1.0"',
        'defaultTargets = ["RunArtifacts"]',
        "",
        "[[require]]",
        'name = "MechLib"',
        f'path = "{_lean_export_relpath(export_root, mechlib_dir)}"',
        "",
    ]
    if mathlib_dir is not None:
        lakefile_lines.extend(
            [
                "[[require]]",
                'name = "mathlib"',
                f'path = "{_lean_export_relpath(export_root, mathlib_dir)}"',
                "",
            ]
        )
    lakefile_lines.extend(
        [
            "[[lean_lib]]",
            'name = "RunArtifacts"',
            'srcDir = "."',
            "",
        ]
    )

    files["lean_exports/lean-toolchain"] = toolchain + "\n"
    files["lean_exports/lakefile.toml"] = "\n".join(lakefile_lines)
    files["lean_exports/RunArtifacts.lean"] = "namespace RunArtifacts\n\nend RunArtifacts\n"
    if packages_dir.exists():
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
            parts.extend(["", f"{decl} := by", "  sorry"])
            if final_error:
                parts.extend(["", "/- Unverified artifact summary", f"{final_error}", "-/"])
            if proof_body:
                parts.extend(["", "/- Last attempted proof body", proof_body, "-/"])
    else:
        parts.extend(["", "/- No selected theorem declaration was available for this sample. -/"])
    return "\n".join(parts).rstrip() + "\n"


def build_lean_export_files(
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

    semantic_map = {(str(row.get("sample_id") or ""), _as_int(row.get("round_index"), 0)): row for row in semantic_rows}
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

        selected_candidate_id = str((proof_row or {}).get("selected_candidate_id") or (semantic_row or {}).get("selected_candidate_id") or "")
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


def build_run_readme(
    samples,
    stage_rows: dict[str, list[dict[str, object]]],
    summaries: list[SampleRunSummary],
    metrics: dict[str, object],
    run_dir: Path,
    sample_concurrency: int = 1,
    run_metadata: dict[str, object] | None = None,
) -> str:
    candidate_rows = stage_rows.get("statement_candidates.jsonl", [])
    compile_rows = stage_rows.get("compile_checks.jsonl", [])
    semantic_rows = stage_rows.get("semantic_rank.jsonl", [])
    proof_attempt_rows = stage_rows.get("proof_attempts.jsonl", [])
    proof_rows = stage_rows.get("proof_checks.jsonl", [])
    compile_sub_counter: dict[str, int] = {}
    for row in compile_rows:
        sub_error = str(row.get("sub_error_type") or "").strip()
        if not sub_error:
            continue
        compile_sub_counter[sub_error] = compile_sub_counter.get(sub_error, 0) + 1
    proof_sub_counter: dict[str, int] = {}
    for row in proof_rows:
        sub_error = str(row.get("sub_error_type") or "").strip()
        if not sub_error:
            continue
        proof_sub_counter[sub_error] = proof_sub_counter.get(sub_error, 0) + 1
    environment_health = str((run_metadata or {}).get("environment_health") or "unknown")
    environment_warnings = (run_metadata or {}).get("environment_warnings") if isinstance(run_metadata, dict) else []
    if not isinstance(environment_warnings, list):
        environment_warnings = []
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
        f"- statement_mechlib_usage_rate: {metrics.get('statement_mechlib_usage_rate', 0)}",
        f"- selected_statement_mechlib_usage_rate: {metrics.get('selected_statement_mechlib_usage_rate', 0)}",
        f"- proof_mechlib_usage_rate: {metrics.get('proof_mechlib_usage_rate', 0)}",
        f"- library_grounded_selection_rate: {metrics.get('library_grounded_selection_rate', 0)}",
        f"- feedback_loop_used_rate: {metrics.get('feedback_loop_used_rate', 0)}",
        f"- sample_concurrency: {sample_concurrency}",
        f"- environment_health: {environment_health}",
        f"- environment_warnings_count: {len(environment_warnings)}",
        "",
        "## MechLib Adoption",
        "",
        "- definition:",
        "  - mechlib_header_rate = ratio of statement candidates whose header includes `import MechLib`",
        "  - mechlib_compile_pass_rate = ratio of compile checks that pass on MechLib backend",
        "  - selected_mechlib_candidate_rate = ratio of D-selected candidates that used MechLib backend",
        "  - statement_mechlib_usage_rate = ratio of final-round statement candidates that explicitly cite retrieved library symbols",
        "  - selected_statement_mechlib_usage_rate = ratio of D-selected candidates with explicit retrieved-library support",
        "  - proof_mechlib_usage_rate = ratio of final proof attempts whose proof plan/body references retrieved theorem names or symbols",
        "  - library_grounded_selection_rate = ratio of D selections that are explicitly library-backed or receive positive library grounding score",
        "",
        "## Runtime Diagnostics",
        "",
        f"- compile_invalid_decl_shape_count: {compile_sub_counter.get('invalid_decl_shape', 0)}",
        f"- compile_empty_stderr_timeout_count: {compile_sub_counter.get('empty_stderr_timeout', 0)}",
        f"- compile_timeout_after_warning_count: {compile_sub_counter.get('timeout_after_warning', 0)}",
        f"- compile_timeout_or_tooling_block_count: {compile_sub_counter.get('timeout_or_tooling_block', 0)}",
        f"- proof_empty_stderr_timeout_count: {proof_sub_counter.get('empty_stderr_timeout', 0)}",
        f"- proof_timeout_after_warning_count: {proof_sub_counter.get('timeout_after_warning', 0)}",
        f"- proof_timeout_or_tooling_block_count: {proof_sub_counter.get('timeout_or_tooling_block', 0)}",
        "",
        "## Sample Details",
    ]
    for sid, sample in sample_map.items():
        summary = summary_map.get(sid)
        lines.extend([f"### {sid}", "", "**Problem**", "", "```text", sample.problem_text[:4000], "```", "", "**Lean Candidates**", ""])
        lines.append(f"- feedback_loop_used: {summary.feedback_loop_used if summary else None}")
        lines.append(f"- final_round_index: {final_round_map.get(sid, 0)}")
        round_candidates_map = candidates_by_sid_round.get(sid, {})
        round_compile_map = compile_by_sid_round.get(sid, {})
        round_semantic_map = semantic_by_sid_round.get(sid, {})
        round_ids = sorted(set(round_candidates_map) | set(round_compile_map) | set(round_semantic_map))
        for round_index in round_ids:
            lines.extend(["", f"**Round {round_index}**", ""])
            sample_candidates = round_candidates_map.get(round_index, [])
            mechlib_count = sum(1 for c in sample_candidates if "import MechLib" in str(c.get("lean_header") or ""))
            physlean_count = sum(1 for c in sample_candidates if "import PhysLean" in str(c.get("lean_header") or ""))
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
                    f"fallback={comp.get('route_fallback_used') if comp else None}"
                )
                lines.append("```lean")
                lines.append(str(c.get("lean_header", "import PhysLean")).strip())
                lines.append("")
                lines.append(str(c.get("theorem_decl", "")).strip())
                lines.append("```")
                lines.append(f"  - plan: {truncate(str(c.get('plan') or ''), 240)}")
                lines.append(f"  - supporting_facts: {truncate(json.dumps(c.get('supporting_facts', []), ensure_ascii=False), 240)}")
                lines.append(f"  - fact_sources: {truncate(json.dumps(c.get('fact_sources', []), ensure_ascii=False), 240)}")
                lines.append(f"  - library_symbols_used: {truncate(json.dumps(c.get('library_symbols_used', []), ensure_ascii=False), 240)}")
                lines.append(f"  - unsupported_claims: {truncate(json.dumps(c.get('unsupported_claims', []), ensure_ascii=False), 240)}")

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
                    lines.append(f"- retry_feedback_summary: {truncate(str(semantic.get('retry_feedback_summary') or ''), 800)}")
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
                        f"library_grounding={item.get('library_grounding_score')} "
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
                    lines.append(
                        f"  - grounded_library_symbols={item.get('grounded_library_symbols')} "
                        f"unsupported_claims={item.get('unsupported_claims')} "
                        f"grounding_gap_summary={truncate(str(item.get('grounding_gap_summary') or ''), 240)}"
                    )

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
                    f"fallback={a.get('route_fallback_used')}"
                )
                lines.append(f"  - stderr_digest: {truncate(str(a.get('stderr_digest') or ''), 240)}")
                lines.append(f"  - plan: {truncate(str(a.get('plan') or ''), 240)}")
                lines.append(f"  - proof_plan: {truncate(str(a.get('proof_plan') or ''), 240)}")
                lines.append(f"  - theorems_to_apply: {truncate(json.dumps(a.get('theorems_to_apply', []), ensure_ascii=False), 240)}")
                lines.append(f"  - givens_to_use: {truncate(json.dumps(a.get('givens_to_use', []), ensure_ascii=False), 240)}")
                lines.append(f"  - intermediate_claims: {truncate(json.dumps(a.get('intermediate_claims', []), ensure_ascii=False), 240)}")
                lines.append(f"  - plan_grounding_ok: {a.get('plan_grounding_ok')}")
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
