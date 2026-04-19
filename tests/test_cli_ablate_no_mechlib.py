from mech_pipeline.cli_ablate_no_mechlib import (
    _append_ablation_suffix,
    _apply_no_mechlib_context_ablation,
)
from mech_pipeline.config import PipelineConfig


def test_apply_no_mechlib_context_ablation_disables_retrieval_context():
    cfg = PipelineConfig()
    cfg.knowledge.enabled = True
    cfg.knowledge.inject_modules = ["B", "D"]
    cfg.statement.with_mechlib_context = True

    out = _apply_no_mechlib_context_ablation(cfg)

    assert out.knowledge.enabled is False
    assert out.knowledge.inject_modules == []
    assert out.statement.with_mechlib_context is False


def test_append_ablation_suffix_uses_default_when_tag_missing():
    assert _append_ablation_suffix(None) == "baseline-v1-ablate-no-mechlib"
    assert _append_ablation_suffix("demo-run") == "demo-run-ablate-no-mechlib"
