from __future__ import annotations

from pathlib import Path

import pytest

from mech_pipeline.config import DEFAULT_LOCAL_ARCHIVE_ROOT, MAX_SAMPLE_CONCURRENCY, load_config


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
    assert cfg.runtime.sample_concurrency == 1
    assert cfg.dataset.local_archive.root == "X:/not_used"


def test_load_config_uses_relaxed_default_lean_timeout(tmp_path: Path) -> None:
    config_path = tmp_path / "cfg.yaml"
    config_path.write_text(
        """
dataset:
  source: local_archive
  limit: 1
  local_archive:
    root: "X:/not_used"
    mode: text_only
model:
  provider: mock
lean:
  enabled: true
  preflight_enabled: false
""",
        encoding="utf-8",
    )
    cfg = load_config(config_path)
    assert cfg.lean.timeout_s == 120


def test_load_config_rejects_invalid_sample_concurrency(tmp_path: Path) -> None:
    config_path = tmp_path / "cfg.yaml"
    config_path.write_text(
        """
dataset:
  source: local_archive
  limit: 1
  local_archive:
    root: "X:/not_used"
    mode: text_only
model:
  provider: mock
lean:
  enabled: false
  preflight_enabled: false
runtime:
  sample_concurrency: 0
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="runtime.sample_concurrency must be >= 1"):
        load_config(config_path)


def test_load_config_accepts_sample_concurrency_at_upper_bound(tmp_path: Path) -> None:
    config_path = tmp_path / "cfg.yaml"
    config_path.write_text(
        f"""
dataset:
  source: local_archive
  limit: 1
  local_archive:
    root: "X:/not_used"
    mode: text_only
model:
  provider: mock
lean:
  enabled: false
  preflight_enabled: false
runtime:
  sample_concurrency: {MAX_SAMPLE_CONCURRENCY}
""",
        encoding="utf-8",
    )
    cfg = load_config(config_path)
    assert cfg.runtime.sample_concurrency == MAX_SAMPLE_CONCURRENCY


def test_load_config_rejects_sample_concurrency_above_upper_bound(tmp_path: Path) -> None:
    config_path = tmp_path / "cfg.yaml"
    config_path.write_text(
        f"""
dataset:
  source: local_archive
  limit: 1
  local_archive:
    root: "X:/not_used"
    mode: text_only
model:
  provider: mock
lean:
  enabled: false
  preflight_enabled: false
runtime:
  sample_concurrency: {MAX_SAMPLE_CONCURRENCY + 1}
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match=rf"runtime.sample_concurrency must be <= {MAX_SAMPLE_CONCURRENCY}"):
        load_config(config_path)


def test_load_config_accepts_utf8_sig_with_bom(tmp_path: Path) -> None:
    config_path = tmp_path / "cfg.yaml"
    config_path.write_bytes(
        (
            "\ufeff"
            "dataset:\n"
            "  source: local_archive\n"
            "  limit: 1\n"
            "  local_archive:\n"
            '    root: "X:/archive"\n'
            "    mode: text_only\n"
            "model:\n"
            "  provider: mock\n"
            "lean:\n"
            "  enabled: false\n"
            "  preflight_enabled: false\n"
        ).encode("utf-8")
    )
    cfg = load_config(config_path)
    assert cfg.dataset.local_archive.root == "X:/archive"


def test_load_config_rejects_likely_mojibake_path_text(tmp_path: Path) -> None:
    config_path = tmp_path / "cfg.yaml"
    config_path.write_text(
        """
dataset:
  source: local_archive
  limit: 1
  local_archive:
    root: "F:/AI4Mechanics/鏁版嵁闆?褰掓。"
    mode: text_only
model:
  provider: mock
lean:
  enabled: false
  preflight_enabled: false
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="contains likely mojibake"):
        load_config(config_path)


def test_load_config_uses_ascii_default_archive_root(tmp_path: Path) -> None:
    config_path = tmp_path / "cfg.yaml"
    config_path.write_text(
        """
dataset:
  source: lean4phys
  limit: 1
model:
  provider: mock
lean:
  enabled: false
  preflight_enabled: false
""",
        encoding="utf-8",
    )
    cfg = load_config(config_path)
    assert cfg.dataset.local_archive.root == DEFAULT_LOCAL_ARCHIVE_ROOT
