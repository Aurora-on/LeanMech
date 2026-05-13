from __future__ import annotations

from pathlib import Path

import pytest

from mech_pipeline.config import load_config


def test_minimal_config_defaults_to_minimal_skeleton(tmp_path: Path) -> None:
    config_path = tmp_path / "default.yaml"
    config_path.write_text(
        """
dataset:
  source: local_archive
  limit: 1
  local_archive:
    root: "../archive"
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

    assert cfg.statement.generation_mode == "minimal_skeleton"
    assert cfg.statement.allow_explicit_gap_laws is True
    assert cfg.statement.forbid_derived_equation_hypotheses is True
    assert cfg.statement.require_hypothesis_provenance is True
    assert cfg.statement.require_evidence_binding is True
    assert cfg.statement.max_model_ir_candidates == 2
    assert cfg.statement.max_sketch_steps == 12
    assert cfg.statement.minimal_feedback_scope == "routed_stage"
    assert cfg.statement.b_minimal_llm_enabled is False
    assert cfg.statement.b_minimal_llm_on_retry is True
    assert cfg.statement.compact_minimal_prompts is True
    assert cfg.knowledge.structured_context_enabled is True
    assert cfg.knowledge.evidence_top_k == 8
    assert cfg.knowledge.lean_check_decls is True


def test_smoke_minimal_skeleton_config_loads(capsys: pytest.CaptureFixture[str]) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    config_path = repo_root / "configs" / "smoke_minimal_skeleton.yaml"

    cfg = load_config(config_path)
    print(f"generation_mode={cfg.statement.generation_mode}")

    captured = capsys.readouterr()
    assert "generation_mode=minimal_skeleton" in captured.out
    assert cfg.statement.generation_mode == "minimal_skeleton"
    assert cfg.statement.max_model_ir_candidates == 2
    assert cfg.statement.max_sketch_steps == 12
    assert cfg.statement.minimal_feedback_scope == "routed_stage"
    assert cfg.statement.b_minimal_llm_enabled is False
    assert cfg.statement.b_minimal_llm_on_retry is True
    assert cfg.statement.compact_minimal_prompts is True
    assert cfg.knowledge.structured_context_enabled is True
    assert cfg.knowledge.evidence_top_k == 8
    assert cfg.knowledge.lean_check_decls is True


def test_invalid_generation_mode_is_rejected(tmp_path: Path) -> None:
    config_path = tmp_path / "bad.yaml"
    config_path.write_text(
        """
dataset:
  source: local_archive
  limit: 1
  local_archive:
    root: "../archive"
    mode: text_only
model:
  provider: mock
lean:
  enabled: false
  preflight_enabled: false
statement:
  generation_mode: unsupported_mode
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="statement.generation_mode"):
        load_config(config_path)


def test_minimal_skeleton_positive_limits_are_validated(tmp_path: Path) -> None:
    config_path = tmp_path / "bad_limit.yaml"
    config_path.write_text(
        """
dataset:
  source: local_archive
  limit: 1
  local_archive:
    root: "../archive"
    mode: text_only
model:
  provider: mock
lean:
  enabled: false
  preflight_enabled: false
knowledge:
  evidence_top_k: 0
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="knowledge.evidence_top_k must be > 0"):
        load_config(config_path)


def test_invalid_minimal_feedback_scope_is_rejected(tmp_path: Path) -> None:
    config_path = tmp_path / "bad_scope.yaml"
    config_path.write_text(
        """
dataset:
  source: local_archive
  limit: 1
  local_archive:
    root: "../archive"
    mode: text_only
model:
  provider: mock
lean:
  enabled: false
  preflight_enabled: false
statement:
  generation_mode: minimal_skeleton
  minimal_feedback_scope: rerun_everything
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="statement.minimal_feedback_scope"):
        load_config(config_path)
