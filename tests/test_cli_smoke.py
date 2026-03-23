from __future__ import annotations

from pathlib import Path

from mech_pipeline.cli import main


def test_cli_smoke_local_text(tmp_path: Path) -> None:
    archive_root = tmp_path / "archive"
    (archive_root / "output_description_part1").mkdir(parents=True, exist_ok=True)
    (archive_root / "output_description_part1" / "1-1.md").write_text(
        "题目：质量为1kg的小球，受力F=1N，求加速度。",
        encoding="utf-8",
    )

    config_path = tmp_path / "cfg.yaml"
    output_latest = tmp_path / "latest"
    runs_dir = tmp_path / "runs"
    config_path.write_text(
        f"""
dataset:
  source: local_archive
  limit: 1
  local_archive:
    root: "{archive_root.as_posix()}"
    mode: text_only
model:
  provider: mock
  model_id: mock-test
lean:
  enabled: false
  preflight_enabled: false
output:
  output_dir: "{output_latest.as_posix()}"
  runs_dir: "{runs_dir.as_posix()}"
  tag: "test-run"
""",
        encoding="utf-8",
    )

    code = main(["run", "--config", str(config_path)])
    assert code == 0
    assert (output_latest / "metrics.json").exists()
    assert (output_latest / "analysis.md").exists()
    assert (output_latest / "sample_summary.jsonl").exists()
