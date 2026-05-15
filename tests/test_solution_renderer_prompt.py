from pathlib import Path

from mech_pipeline.modules.solution_renderer import build_solution_renderer_prompt
from mech_pipeline.types import SolutionTrace


def test_solution_renderer_prompt_constraints_and_compact_payload():
    template = Path("prompts/F_solution_renderer.md").read_text(encoding="utf-8")
    trace = SolutionTrace(
        sample_id="s1",
        candidate_id="c1",
        proof_status="proof_failed",
        target_formal="x = y",
        target_display="x = y",
        source_status={"final_proof_body": "SECRET_FULL_PROOF"},
    )
    prompt = build_solution_renderer_prompt(solution_trace=trace, template=template, max_chars=8000)
    assert "不要新增公式" in prompt
    assert "proof_status" in prompt
    assert "返回 JSON" in prompt
    assert "完整 Lean proof" in prompt
    assert "完整 MechLib context" in prompt
    assert "SECRET_FULL_PROOF" not in prompt
