from __future__ import annotations

from pathlib import Path

from mech_pipeline.config import load_config


def test_load_config_minimal(tmp_path: Path) -> None:
    config_path = tmp_path / "cfg.yaml"
    config_path.write_text(
        """
dataset:
  source: local_archive
  limit: 2
  local_archive:
    root: "X:/not_used"
    mode: text_only
model:
  provider: mock
lean:
  enabled: false
  preflight_enabled: false
""",
        encoding="utf-8",
    )
    cfg = load_config(config_path)
    assert cfg.dataset.source == "local_archive"
    assert cfg.dataset.limit == 2
    assert cfg.model.provider == "mock"
    assert cfg.lean.enabled is False
