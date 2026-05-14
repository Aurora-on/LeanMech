from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from mech_pipeline import orchestrator
from mech_pipeline.config import PipelineConfig
from mech_pipeline.types import SampleRunSummary


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_execute_samples_flushes_completed_sample_rows_incrementally(tmp_path: Path, monkeypatch) -> None:
    def fake_process_sample(*, sample, **_kwargs):
        return {
            "stage_rows": {
                "proof_attempts.jsonl": [{"sample_id": sample.sample_id, "attempt_index": 1}],
                "proof_checks.jsonl": [{"sample_id": sample.sample_id, "proof_success": False}],
                "sample_summary.jsonl": [],
            },
            "grounding_rows": [],
            "compile_rows": [],
            "semantic_rows": [],
            "proof_rows": [],
            "summary": SampleRunSummary(
                sample_id=sample.sample_id,
                grounding_ok=True,
                statement_generation_ok=True,
                compile_ok=True,
                semantic_ok=True,
                proof_ok=False,
                end_to_end_ok=False,
                final_error_type="proof_search_failure",
            ),
        }

    monkeypatch.setattr(orchestrator, "process_sample", fake_process_sample)

    cfg = PipelineConfig()
    cfg.runtime.sample_concurrency = 1
    result = orchestrator.execute_samples(
        cfg=cfg,
        samples=[
            SimpleNamespace(sample_id="s1", skip_reason=None),
            SimpleNamespace(sample_id="s2", skip_reason=None),
        ],
        run_dir=tmp_path,
        prompt_dir=tmp_path,
        inject_set=set(),
        retriever=None,
        preflight_ok=True,
        preflight_error=None,
        preflight_message="ok",
        stage_row_files=("proof_attempts.jsonl", "proof_checks.jsonl", "sample_summary.jsonl"),
        emit_console_line=lambda _line: None,
        build_worker_modules=lambda _cfg, _prompt_dir: (),
        build_revision_feedback=lambda **_kwargs: "",
    )

    assert [row["sample_id"] for row in _read_jsonl(tmp_path / "proof_attempts.jsonl")] == ["s1", "s2"]
    assert [row["sample_id"] for row in _read_jsonl(tmp_path / "proof_checks.jsonl")] == ["s1", "s2"]
    assert [row["sample_id"] for row in _read_jsonl(tmp_path / "sample_summary.jsonl")] == ["s1", "s2"]
    assert [row["sample_id"] for row in result["stage_rows"]["proof_attempts.jsonl"]] == ["s1", "s2"]
