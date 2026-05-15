from pathlib import Path
from types import SimpleNamespace

from mech_pipeline.rendering import build_run_readme
from mech_pipeline.types import SampleRunSummary


def test_run_readme_includes_natural_solution_summary_and_truncates(tmp_path: Path):
    long_solution = "最终答案 μ_s = F_start / W。\n" + ("详细说明。" * 500)
    readme = build_run_readme(
        samples=[SimpleNamespace(sample_id="s1", problem_text="求静摩擦系数", meta={}, skip_reason=None)],
        stage_rows={
            "statement_candidates.jsonl": [],
            "compile_checks.jsonl": [],
            "semantic_rank.jsonl": [],
            "proof_attempts.jsonl": [],
            "proof_checks.jsonl": [{"sample_id": "s1", "proof_success": True, "selected_candidate_id": "c1"}],
            "natural_solution.jsonl": [
                {
                    "sample_id": "s1",
                    "render_success": True,
                    "proof_status": "legacy_verified_no_audit",
                    "render_audit_pass": True,
                    "natural_solution": long_solution,
                }
            ],
            "solution_render_audit.jsonl": [{"sample_id": "s1", "audit_pass": True, "failure_tags": []}],
        },
        summaries=[
            SampleRunSummary(
                sample_id="s1",
                grounding_ok=True,
                statement_generation_ok=True,
                compile_ok=True,
                semantic_ok=True,
                proof_ok=True,
                end_to_end_ok=True,
                final_error_type=None,
            )
        ],
        metrics={
            "num_total_samples": 1,
            "solution_render_success_rate": 1.0,
            "solution_render_audit_pass_rate": 1.0,
        },
        run_dir=tmp_path,
    )
    assert "**Natural Solution**" in readme
    assert "proof_status: legacy_verified_no_audit" in readme
    assert "render_audit_pass: True" in readme
    assert "..." in readme
