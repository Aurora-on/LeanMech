from __future__ import annotations

import json
from pathlib import Path

from mech_pipeline.archive.writer import write_outputs


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_write_outputs_keeps_latest_lightweight(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    latest_dir = tmp_path / "latest"
    stage_rows = {
        "problem_ir.jsonl": [],
        "mechlib_retrieval.jsonl": [],
        "statement_candidates.jsonl": [],
        "compile_checks.jsonl": [],
        "semantic_rank.jsonl": [],
        "proof_attempts.jsonl": [],
        "proof_checks.jsonl": [],
        "sample_summary.jsonl": [],
    }

    extra_text_files = {
        ".pipeline1_tmp/compile/example.lean": "-- tmp\n",
        "lean_compile/example.log": "compile log\n",
        "lean_proof/example.log": "proof log\n",
        "lean_exports/index.json": "[]\n",
    }

    write_outputs(
        run_dir=run_dir,
        latest_dir=latest_dir,
        stage_rows=stage_rows,
        metrics={"num_total_samples": 0},
        analysis_md="# analysis\n",
        run_readme_md="# readme\n",
        config_payload={"k": "v"},
        extra_text_files=extra_text_files,
    )

    assert (run_dir / ".pipeline1_tmp" / "compile" / "example.lean").exists()
    assert (run_dir / "lean_compile" / "example.log").exists()
    assert (run_dir / "lean_proof" / "example.log").exists()
    assert (run_dir / "lean_exports" / "index.json").exists()

    assert not (latest_dir / ".pipeline1_tmp").exists()
    assert not (latest_dir / "lean_compile").exists()
    assert not (latest_dir / "lean_proof").exists()
    assert (latest_dir / "lean_exports" / "index.json").exists()
    assert _read_json(latest_dir / "metrics.json")["num_total_samples"] == 0
