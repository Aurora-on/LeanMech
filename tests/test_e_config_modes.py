from __future__ import annotations

from pathlib import Path

from mech_pipeline.config import PipelineConfig, load_config, select_proof_execution_mode
from mech_pipeline.types import StatementCandidate, TheoremSkeletonCandidate


def test_old_config_still_loads_and_defaults_to_auto(tmp_path: Path) -> None:
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
proof:
  max_attempts: 3
""",
        encoding="utf-8",
    )
    cfg = load_config(config_path)
    assert cfg.proof.max_attempts == 3
    assert cfg.proof.mode == "auto"
    assert cfg.proof.legacy_fallback_enabled is False
    assert cfg.proof.llm_guided_search.enabled is True
    assert cfg.proof.llm_guided_search.max_nodes == 80
    assert cfg.proof.llm_guided_search.probe_timeout_s == 120
    assert cfg.proof.llm_guided_search.max_probe_checks == 80
    assert cfg.proof.llm_guided_search.max_no_progress_nodes == 12
    assert cfg.proof.llm_guided_search.max_wall_clock_s_per_sample == 1800


def test_default_proof_mode_is_auto() -> None:
    cfg = PipelineConfig()
    assert cfg.proof.mode == "auto"


def test_auto_routes_minimal_skeleton_candidate_to_llm_guided_search() -> None:
    cfg = PipelineConfig()
    candidate = TheoremSkeletonCandidate(
        sample_id="s1",
        candidate_id="c1",
        lean_header="import MechLib",
        theorem_decl="theorem c1 : True",
    )
    assert select_proof_execution_mode(cfg.proof, candidate) == "llm_guided_search"


def test_auto_routes_legacy_candidate_to_legacy_full_proof() -> None:
    cfg = PipelineConfig()
    candidate = StatementCandidate(
        sample_id="s1",
        candidate_id="c1",
        lean_header="import MechLib",
        theorem_decl="theorem c1 : True",
    )
    assert select_proof_execution_mode(cfg.proof, candidate) == "legacy_full_proof"
