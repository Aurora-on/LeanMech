from __future__ import annotations

import json
from pathlib import Path

from mech_pipeline.cli import main


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def _preproof_eval_config(path: Path, *, runs_dir: Path, latest_dir: Path) -> None:
    path.write_text(
        f"""
model:
  provider: mock
  model_id: mock-mechanics-v1
lean:
  enabled: false
  preflight_enabled: false
proof:
  max_attempts: 1
output:
  runs_dir: "{runs_dir.as_posix()}"
  output_dir: "{latest_dir.as_posix()}"
runtime:
  sample_concurrency: 1
""",
        encoding="utf-8",
    )


def test_run_preproof_e_dry_run_restores_selected_snapshot_rows(tmp_path: Path) -> None:
    preproof_dir = tmp_path / "preproof"
    artifacts_dir = preproof_dir / "artifacts"
    sample_id = "s-preproof-1"
    theorem_decl = "theorem s_preproof_1_c1 (x : Real) (hx : x = 1) : x = 1"
    candidate = {
        "sample_id": sample_id,
        "candidate_id": "c1",
        "lean_header": "import Mathlib",
        "theorem_decl": theorem_decl,
        "assumptions": ["x = 1"],
        "parse_ok": True,
        "round_index": 0,
        "generation_mode": "minimal_skeleton",
        "skeleton_audit": {"sample_id": sample_id, "audit_pass": True, "failure_tags": []},
        "proof_obligations": [],
        "verified_decls": [],
    }
    compile_row = {
        "sample_id": sample_id,
        "candidate_id": "c1",
        "compile_pass": True,
        "syntax_ok": True,
        "elaboration_ok": True,
        "error_type": None,
        "stderr_digest": "",
        "log_path": None,
        "backend_used": "mechlib",
        "round_index": 0,
    }
    semantic_row = {
        "sample_id": sample_id,
        "selected_candidate_id": "c1",
        "selected_theorem_decl": theorem_decl,
        "semantic_pass": True,
        "ranking": [{"candidate_id": "c1", "semantic_pass": True}],
        "selected_backend": "mechlib",
        "round_index": 0,
    }
    problem_row = {
        "sample_id": sample_id,
        "model_id": "mock",
        "problem_ir": {"goal_statement": "Prove x = 1 from hx.", "physical_laws": []},
        "parse_ok": True,
        "raw_response": "{}",
        "error": None,
    }

    _write_jsonl(
        preproof_dir / "eligible_samples.jsonl",
        [{"sample_id": sample_id, "preproof_eligible": True, "selected_candidate_id": "c1", "round_index": 0}],
    )
    _write_jsonl(preproof_dir / "selected_candidates.jsonl", [candidate])
    _write_jsonl(preproof_dir / "selected_compile_checks.jsonl", [compile_row])
    _write_jsonl(preproof_dir / "selected_semantic_rank.jsonl", [semantic_row])
    _write_jsonl(artifacts_dir / "problem_ir.jsonl", [problem_row])
    _write_jsonl(artifacts_dir / "model_ir.jsonl", [{"sample_id": sample_id, "parse_ok": True}])
    _write_jsonl(artifacts_dir / "controlled_sketch.jsonl", [{"sample_id": sample_id, "status": "ok"}])
    _write_jsonl(artifacts_dir / "sketch_audit.jsonl", [{"sample_id": sample_id, "audit_pass": True}])

    config_path = tmp_path / "preproof_eval.yaml"
    _preproof_eval_config(config_path, runs_dir=tmp_path / "runs", latest_dir=tmp_path / "latest")

    rc = main(
        [
            "run-preproof-e",
            "--preproof-dir",
            preproof_dir.as_posix(),
            "--config",
            config_path.as_posix(),
            "--tag",
            "dry-run-test",
            "--dry-run",
        ]
    )

    assert rc == 0
    run_dirs = sorted((tmp_path / "runs").glob("*_dry-run-test"))
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]
    proof_check = json.loads((run_dir / "proof_checks.jsonl").read_text(encoding="utf-8").strip())
    assert proof_check["error_type"] == "dry_run_skipped"
    statement_row = json.loads((run_dir / "statement_candidates.jsonl").read_text(encoding="utf-8").strip())
    assert statement_row["theorem_decl"] == theorem_decl
    manifest = json.loads((run_dir / "preproof_eval_manifest.json").read_text(encoding="utf-8"))
    assert manifest["stage_boundary"].startswith("A-D restored")


def test_run_preproof_e_skips_locked_preproof_samples(tmp_path: Path) -> None:
    preproof_dir = tmp_path / "preproof"
    artifacts_dir = preproof_dir / "artifacts"
    unlocked = "s-unlocked"
    locked = "s-locked"

    candidates = []
    compile_rows = []
    semantic_rows = []
    problem_rows = []
    for sample_id in [unlocked, locked]:
        theorem_decl = f"theorem {sample_id.replace('-', '_')}_c1 : True"
        candidates.append(
            {
                "sample_id": sample_id,
                "candidate_id": "c1",
                "lean_header": "import Mathlib",
                "theorem_decl": theorem_decl,
                "parse_ok": True,
                "round_index": 0,
                "generation_mode": "minimal_skeleton",
                "skeleton_audit": {"sample_id": sample_id, "audit_pass": True, "failure_tags": []},
                "proof_obligations": [],
                "verified_decls": [],
            }
        )
        compile_rows.append(
            {
                "sample_id": sample_id,
                "candidate_id": "c1",
                "compile_pass": True,
                "syntax_ok": True,
                "elaboration_ok": True,
                "error_type": None,
                "stderr_digest": "",
                "log_path": None,
                "backend_used": "mechlib",
                "round_index": 0,
            }
        )
        semantic_rows.append(
            {
                "sample_id": sample_id,
                "selected_candidate_id": "c1",
                "selected_theorem_decl": theorem_decl,
                "semantic_pass": True,
                "ranking": [{"candidate_id": "c1", "semantic_pass": True}],
                "selected_backend": "mechlib",
                "round_index": 0,
            }
        )
        problem_rows.append(
            {
                "sample_id": sample_id,
                "model_id": "mock",
                "problem_ir": {"goal_statement": sample_id, "physical_laws": []},
                "parse_ok": True,
                "raw_response": "{}",
                "error": None,
            }
        )

    _write_jsonl(
        preproof_dir / "eligible_samples.jsonl",
        [
            {"sample_id": unlocked, "preproof_eligible": True, "selected_candidate_id": "c1", "round_index": 0},
            {"sample_id": locked, "preproof_eligible": True, "selected_candidate_id": "c1", "round_index": 0},
        ],
    )
    _write_jsonl(preproof_dir / "selected_candidates.jsonl", candidates)
    _write_jsonl(preproof_dir / "selected_compile_checks.jsonl", compile_rows)
    _write_jsonl(preproof_dir / "selected_semantic_rank.jsonl", semantic_rows)
    _write_jsonl(artifacts_dir / "problem_ir.jsonl", problem_rows)
    _write_jsonl(artifacts_dir / "model_ir.jsonl", [{"sample_id": unlocked}, {"sample_id": locked}])
    _write_jsonl(artifacts_dir / "controlled_sketch.jsonl", [{"sample_id": unlocked}, {"sample_id": locked}])
    _write_jsonl(artifacts_dir / "sketch_audit.jsonl", [{"sample_id": unlocked}, {"sample_id": locked}])
    (preproof_dir / "locked_preproof_excludes.json").write_text(
        json.dumps({"locked_sample_ids": [locked]}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    config_path = tmp_path / "preproof_eval.yaml"
    _preproof_eval_config(config_path, runs_dir=tmp_path / "runs", latest_dir=tmp_path / "latest")

    rc = main(
        [
            "run-preproof-e",
            "--preproof-dir",
            preproof_dir.as_posix(),
            "--config",
            config_path.as_posix(),
            "--tag",
            "locked-skip-test",
            "--dry-run",
        ]
    )

    assert rc == 0
    run_dir = sorted((tmp_path / "runs").glob("*_locked-skip-test"))[0]
    proof_checks = [
        json.loads(line)
        for line in (run_dir / "proof_checks.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    manifest = json.loads((run_dir / "preproof_eval_manifest.json").read_text(encoding="utf-8"))

    assert [row["sample_id"] for row in proof_checks] == [unlocked]
    assert manifest["sample_ids"] == [unlocked]
    assert manifest["locked_excluded_sample_ids"] == [locked]
