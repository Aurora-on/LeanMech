from __future__ import annotations

import json
from types import SimpleNamespace
from pathlib import Path

from mech_pipeline.config import PipelineConfig
from mech_pipeline.cli import main
from mech_pipeline.orchestrator import process_sample
from mech_pipeline.rendering import build_revision_feedback
from mech_pipeline.types import (
    AlgebraObligation,
    CanonicalTarget,
    CompileCheckResult,
    ControlledSketch,
    GroundingResult,
    ModelIR,
    ProofCheckResult,
    SemanticRankResult,
    SketchAuditResult,
    TheoremSkeletonCandidate,
)


def _jsonl_rows(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_minimal_skeleton_run_archives_front_half_artifacts_and_summary(tmp_path: Path) -> None:
    archive_root = tmp_path / "archive"
    (archive_root / "output_description_part1").mkdir(parents=True)
    (archive_root / "output_description_part1" / "1-1.md").write_text(
        "A particle moves at constant speed v for time t. Find displacement s.",
        encoding="utf-8",
    )
    latest_dir = tmp_path / "latest"
    runs_dir = tmp_path / "runs"
    config_path = tmp_path / "minimal.yaml"
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
  model_id: mock-minimal
knowledge:
  enabled: false
lean:
  enabled: false
  preflight_enabled: false
statement:
  generation_mode: minimal_skeleton
  feedback_loop_enabled: false
output:
  output_dir: "{latest_dir.as_posix()}"
  runs_dir: "{runs_dir.as_posix()}"
  tag: "minimal-skeleton-stage6-smoke"
""",
        encoding="utf-8",
    )

    assert main(["run", "--config", str(config_path)]) == 0
    run_dirs = [path for path in runs_dir.iterdir() if path.is_dir()]
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]

    expected_jsonl = [
        "model_ir.jsonl",
        "structured_mechlib_context.jsonl",
        "evidence_bindings.jsonl",
        "controlled_sketch.jsonl",
        "sketch_audit.jsonl",
        "theorem_skeleton_candidates.jsonl",
    ]
    for name in expected_jsonl:
        assert (run_dir / name).exists()
        assert (latest_dir / name).exists()

    assert _jsonl_rows(run_dir / "model_ir.jsonl")[0]["parse_ok"] is True
    assert _jsonl_rows(run_dir / "structured_mechlib_context.jsonl")
    assert _jsonl_rows(run_dir / "evidence_bindings.jsonl")
    assert _jsonl_rows(run_dir / "controlled_sketch.jsonl")
    assert _jsonl_rows(run_dir / "sketch_audit.jsonl")
    skeleton_rows = _jsonl_rows(run_dir / "theorem_skeleton_candidates.jsonl")
    assert skeleton_rows and skeleton_rows[0]["generation_mode"] == "minimal_skeleton"

    metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    for key in (
        "model_ir_success_rate",
        "evidence_binding_success_rate",
        "verified_binding_rate",
        "gap_schema_only_rate",
        "sketch_audit_pass_rate",
        "skeleton_generation_success_rate",
        "derived_equation_hypothesis_violation_rate",
        "schema_as_proof_fact_violation_rate",
        "explicit_gap_law_rate",
    ):
        assert key in metrics

    analysis = (run_dir / "analysis.md").read_text(encoding="utf-8")
    readme = (run_dir / "README.md").read_text(encoding="utf-8")
    for text in (analysis, readme):
        assert "generation_mode: minimal_skeleton" in text
        assert "model_ir_ok:" in text
        assert "evidence_binding_count:" in text
        assert "verified_binding_count:" in text
        assert "gap_schema_only_count:" in text
        assert "sketch_audit_pass:" in text
        assert "forbidden_hypothesis_count:" in text
        assert "skeleton_candidate_count:" in text


def test_orchestrator_minimal_feedback_reruns_sketch_and_b(tmp_path: Path) -> None:
    cfg = PipelineConfig()
    cfg.statement.generation_mode = "minimal_skeleton"
    cfg.statement.feedback_loop_enabled = True
    cfg.statement.max_revision_rounds = 1
    cfg.statement.minimal_feedback_scope = "sketch_and_b"
    cfg.knowledge.enabled = False
    cfg.lean.enabled = False

    call_log: list[dict[str, object]] = []

    class StubA:
        def run(self, sample) -> GroundingResult:
            return GroundingResult(
                sample_id=sample.sample_id,
                model_id="stub-a",
                problem_ir={
                    "unknown_target": {"symbol": "a", "description": "acceleration"},
                    "known_quantities": [{"symbol": "F"}, {"symbol": "m"}],
                    "physical_laws": ["NewtonSecondLaw"],
                },
                parse_ok=True,
                raw_response="",
                error=None,
            )

    class StubA2:
        def run(self, **kwargs) -> ModelIR:
            return ModelIR(
                sample_id=kwargs["sample_id"],
                variables={"F": {"type": "force"}, "m": {"type": "mass"}, "a": {"type": "acceleration"}},
                canonical_target=CanonicalTarget(
                    target_kind="closed_form",
                    target_variables=["a"],
                    lean_formula="a = F / m",
                    source_text="acceleration target",
                    confidence=0.9,
                    parse_ok=True,
                ),
                target={"symbol": "a", "lean": "a.val = F.val / m.val"},
                parse_ok=True,
            )

    class StubSketch:
        def run(self, **kwargs) -> ControlledSketch:
            call_log.append(
                {
                    "module": "sketch",
                    "round_index": kwargs.get("round_index"),
                    "revision_feedback": kwargs.get("revision_feedback"),
                    "previous_sketch": kwargs.get("previous_sketch"),
                    "previous_candidates_count": len(kwargs.get("previous_candidates") or []),
                }
            )
            return ControlledSketch(
                sample_id=kwargs["sample_id"],
                status="ok",
                algebra_obligation=AlgebraObligation(
                    obligation_id=f"alg_{kwargs.get('round_index')}",
                    claim="target",
                    formal_claim="a.val = F.val / m.val",
                    target_variables=["a"],
                ),
                parse_ok=True,
            )

    class StubB:
        def run(self, grounding: GroundingResult, **kwargs):
            round_index = int(kwargs.get("round_index", 0))
            call_log.append(
                {
                    "module": "b",
                    "round_index": round_index,
                    "revision_feedback": kwargs.get("revision_feedback"),
                    "previous_candidates_count": len(kwargs.get("previous_candidates") or []),
                    "sketch_obligation": getattr(kwargs.get("controlled_sketch").algebra_obligation, "obligation_id", None),
                }
            )
            return [
                TheoremSkeletonCandidate(
                    sample_id=grounding.sample_id,
                    candidate_id="c1",
                    lean_header="import MechLib",
                    theorem_decl=f"theorem round_{round_index}_c1 (F : Force) (m : Mass) (a : Acceleration) : a.val = F.val / m.val",
                    parse_ok=True,
                    round_index=round_index,
                    source_round_index=(round_index - 1) if round_index > 0 else None,
                    skeleton_audit=SketchAuditResult(sample_id=grounding.sample_id, audit_pass=True),
                )
            ]

    class StubC:
        def run(self, sample_id: str, candidates, run_dir: Path):
            _ = run_dir
            return [
                CompileCheckResult(sample_id, candidate.candidate_id, True, True, True, None, "", None)
                for candidate in candidates
            ]

    class StubD:
        def run(self, grounding: GroundingResult, candidates, compile_checks, problem_text=None, mechlib_context="(none)"):
            _ = (grounding, compile_checks, problem_text, mechlib_context)
            round_index = candidates[0].round_index
            return SemanticRankResult(
                sample_id=candidates[0].sample_id,
                selected_candidate_id="c1",
                selected_theorem_decl=candidates[0].theorem_decl,
                semantic_pass=round_index > 0,
                ranking=[
                    {
                        "candidate_id": "c1",
                        "semantic_score": 0.2 if round_index == 0 else 0.9,
                        "semantic_pass": round_index > 0,
                        "semantic_reason": "target mismatch" if round_index == 0 else "aligned",
                        "semantic_rank_score": 0.2 if round_index == 0 else 0.9,
                    }
                ],
                error=None if round_index > 0 else "semantic_drift",
            )

    class StubE:
        def run(self, grounding: GroundingResult, selected_candidate, run_dir: Path, mechlib_context: str = "(none)"):
            _ = (grounding, run_dir, mechlib_context)
            return [], ProofCheckResult(
                sample_id=selected_candidate.sample_id,
                proof_success=False,
                attempts_used=0,
                selected_candidate_id=selected_candidate.candidate_id,
                error_type="proof_search_skipped_in_stub",
                final_log_path=None,
            )

    def build_worker_modules(_cfg, _prompt_dir):
        return StubA(), StubA2(), StubSketch(), StubB(), StubC(), StubD(), StubE()

    result = process_sample(
        cfg=cfg,
        sample=SimpleNamespace(
            sample_id="minimal-feedback-1",
            problem_text="Given force and mass, find acceleration.",
            image_description=None,
            skip_reason=None,
        ),
        run_dir=tmp_path,
        prompt_dir=tmp_path,
        inject_set=set(),
        retriever=None,
        preflight_ok=True,
        preflight_error=None,
        preflight_message="skip",
        stage_row_files=(
            "problem_ir.jsonl",
            "model_ir.jsonl",
            "structured_mechlib_context.jsonl",
            "evidence_bindings.jsonl",
            "controlled_sketch.jsonl",
            "sketch_audit.jsonl",
            "mechlib_retrieval.jsonl",
            "statement_candidates.jsonl",
            "theorem_skeleton_candidates.jsonl",
            "compile_checks.jsonl",
            "semantic_rank.jsonl",
            "proof_attempts.jsonl",
            "proof_checks.jsonl",
            "sample_summary.jsonl",
        ),
        build_worker_modules=build_worker_modules,
        build_revision_feedback=build_revision_feedback,
    )

    sketch_calls = [row for row in call_log if row["module"] == "sketch"]
    b_calls = [row for row in call_log if row["module"] == "b"]
    assert [row["round_index"] for row in sketch_calls] == [0, 1]
    assert [row["round_index"] for row in b_calls] == [0, 1]
    assert sketch_calls[1]["previous_sketch"] is not None
    assert sketch_calls[1]["previous_candidates_count"] == 1
    assert b_calls[1]["previous_candidates_count"] == 1
    assert '"retry_reason": "semantic_fail"' in str(b_calls[1]["revision_feedback"])
    assert b_calls[1]["sketch_obligation"] == "alg_1"

    rows = result["stage_rows"]
    assert [row["round_index"] for row in rows["controlled_sketch.jsonl"]] == [0, 1]
    assert [row["round_index"] for row in rows["sketch_audit.jsonl"]] == [0, 1]
    assert {row["round_index"] for row in rows["statement_candidates.jsonl"]} == {0, 1}
    assert len(rows["statement_candidates.jsonl"]) == 2
    assert len(rows["semantic_rank.jsonl"]) == 2
    assert result["summary"].feedback_loop_used is True
    assert result["summary"].final_round_index == 1
