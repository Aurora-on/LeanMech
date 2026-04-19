from __future__ import annotations

import json
from pathlib import Path

import mech_pipeline.direct_baseline as direct_baseline
from mech_pipeline.cli_direct_baseline import main


def _write_archive(archive_root: Path, sample_count: int = 1) -> None:
    (archive_root / "output_description_part1").mkdir(parents=True, exist_ok=True)
    for idx in range(1, sample_count + 1):
        (archive_root / "output_description_part1" / f"1-{idx}.md").write_text(
            f"A {idx} kg block is pushed by a force. Find its acceleration.",
            encoding="utf-8",
        )


def _write_config(tmp_path: Path, *, tag: str, limit: int = 1) -> tuple[Path, Path]:
    archive_root = tmp_path / "archive"
    _write_archive(archive_root, sample_count=limit)
    config_path = tmp_path / f"{tag}.yaml"
    output_latest = tmp_path / "latest"
    runs_dir = tmp_path / "runs"
    config_path.write_text(
        f"""
dataset:
  source: local_archive
  limit: {limit}
  local_archive:
    root: "{archive_root.as_posix()}"
    mode: text_only
model:
  provider: mock
  model_id: mock-direct
knowledge:
  enabled: false
lean:
  enabled: false
  preflight_enabled: false
  lean_header: "import MechLib"
statement:
  with_mechlib_context: false
  feedback_loop_enabled: false
  max_revision_rounds: 0
output:
  output_dir: "{output_latest.as_posix()}"
  runs_dir: "{runs_dir.as_posix()}"
  tag: "{tag}"
runtime:
  sample_concurrency: 1
""",
        encoding="utf-8",
    )
    return config_path, output_latest


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_cli_direct_baseline_smoke(tmp_path: Path, capsys) -> None:
    config_path, output_latest = _write_config(tmp_path, tag="test-direct-baseline")

    code = main(["run", "--config", str(config_path)])
    captured = capsys.readouterr()

    assert code == 0
    assert (output_latest / "metrics.json").exists()
    assert (output_latest / "analysis.md").exists()
    assert (output_latest / "README.md").exists()
    assert (output_latest / "direct_formalization.jsonl").exists()
    assert (output_latest / "compile_checks.jsonl").exists()
    assert (output_latest / "semantic_rank.jsonl").exists()
    assert (output_latest / "sample_summary.jsonl").exists()
    assert (output_latest / "lean_exports" / "index.json").exists()
    assert not (output_latest / "statement_candidates.jsonl").exists()
    assert not (output_latest / "proof_attempts.jsonl").exists()
    assert not (output_latest / "proof_checks.jsonl").exists()

    rows = _read_jsonl(output_latest / "direct_formalization.jsonl")
    assert len(rows) == 1
    assert rows[0]["parse_ok"] is True
    assert rows[0]["theorem_decl"].startswith("theorem")
    assert rows[0]["lean_header"] == "import PhysLean\nopen PhysLean"
    readme_text = (output_latest / "README.md").read_text(encoding="utf-8")
    analysis_text = (output_latest / "analysis.md").read_text(encoding="utf-8")
    config_payload = json.loads((output_latest / "config.json").read_text(encoding="utf-8"))
    assert "environment: physlean_only" in readme_text
    assert "environment: physlean_only" in analysis_text
    assert "MechLib environment" not in readme_text
    assert config_payload["resolved_config"]["lean"]["lean_header"] == "import PhysLean"
    assert config_payload["resolved_config"]["lean"]["route_policy"] == "force_physlean"
    assert config_payload["resolved_config"]["lean"]["default_backend"] == "physlean"
    assert config_payload["resolved_config"]["statement"]["library_target"] == "physlean"
    assert config_payload["baseline"]["environment"] == "physlean_only"
    assert "progress: 0/1 completed, sample_concurrency=1" in captured.out
    assert "progress: 1/1 completed, sample=archive-1-1" in captured.out


def test_cli_direct_baseline_timeout(tmp_path: Path, monkeypatch) -> None:
    config_path, output_latest = _write_config(tmp_path, tag="test-direct-baseline-timeout")
    monkeypatch.setattr(direct_baseline, "DIRECT_SAMPLE_TIMEOUT_S", 0)

    code = main(["run", "--config", str(config_path)])

    assert code == 0
    rows = _read_jsonl(output_latest / "sample_summary.jsonl")
    assert len(rows) == 1
    assert rows[0]["final_error_type"] == "sample_timeout"
    assert rows[0]["sub_error_type"] == "sample_timeout_module_a"
