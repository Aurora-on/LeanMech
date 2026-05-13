from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path

from mech_pipeline.config import PipelineConfig
from mech_pipeline.orchestrator import process_sample
from mech_pipeline.rendering import build_revision_feedback
from mech_pipeline.types import (
    CanonicalTarget,
    CompileCheckResult,
    ControlledSketch,
    GroundingResult,
    ModelIR,
    ModelInstance,
    ProofCheckResult,
    SemanticRankResult,
    SketchAuditResult,
    TheoremSkeletonCandidate,
)


def test_minimal_routed_stage_retries_from_evidence_binder(tmp_path: Path) -> None:
    cfg = PipelineConfig()
    cfg.statement.generation_mode = "minimal_skeleton"
    cfg.statement.feedback_loop_enabled = True
    cfg.statement.max_revision_rounds = 1
    cfg.statement.minimal_feedback_scope = "routed_stage"
    cfg.knowledge.enabled = False
    cfg.knowledge.lean_check_decls = False
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
            call_log.append({"module": "a2", "feedback": kwargs.get("revision_feedback")})
            return ModelIR(
                sample_id=kwargs["sample_id"],
                model_instances=[
                    ModelInstance(
                        instance_id="mi1",
                        kind="newton_second_law_1d",
                        natural_language="apply Newton's second law",
                        expected_claim="F.val = m.val * a.val",
                    )
                ],
                canonical_target=CanonicalTarget(
                    target_kind="closed_form",
                    target_variables=["a"],
                    lean_formula="a.val = F.val / m.val",
                    parse_ok=True,
                ),
                parse_ok=True,
            )

    class StubSketch:
        def run(self, **kwargs) -> ControlledSketch:
            call_log.append(
                {
                    "module": "sketch",
                    "round_index": kwargs.get("round_index"),
                    "evidence_count": len(kwargs.get("evidence_bindings") or []),
                    "feedback": kwargs.get("revision_feedback"),
                }
            )
            return ControlledSketch(sample_id=kwargs["sample_id"], status="ok", parse_ok=True)

    class StubB:
        def run(self, grounding: GroundingResult, **kwargs):
            round_index = int(kwargs.get("round_index", 0))
            call_log.append(
                {
                    "module": "b",
                    "round_index": round_index,
                    "evidence_count": len(kwargs.get("evidence_bindings") or []),
                    "feedback": kwargs.get("revision_feedback"),
                }
            )
            return [
                TheoremSkeletonCandidate(
                    sample_id=grounding.sample_id,
                    candidate_id="c1",
                    lean_header="import MechLib",
                    theorem_decl="theorem c1 : True",
                    parse_ok=True,
                    round_index=round_index,
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
                        "semantic_pass": round_index > 0,
                        "failure_tags": [] if round_index > 0 else ["no_extractor_decl"],
                        "semantic_score": 0.9 if round_index > 0 else 0.2,
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
            sample_id="minimal-routed-evidence",
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
            "failure_routes.jsonl",
            "proof_attempts.jsonl",
            "proof_checks.jsonl",
            "sample_summary.jsonl",
        ),
        build_worker_modules=build_worker_modules,
        build_revision_feedback=build_revision_feedback,
    )

    rows = result["stage_rows"]
    route = rows["failure_routes.jsonl"][0]
    assert route["responsible_stage"] == "EvidenceBinder"
    assert route["rerun_from_stage"] == "EvidenceBinder"
    assert "ModelIR" in route["artifacts_reused"]
    assert "EvidenceBindings" in route["artifacts_invalidated"]
    assert "no_extractor_decl" in route["failure_tags"]

    assert len([row for row in call_log if row["module"] == "a2"]) == 1
    assert [row["round_index"] for row in rows["controlled_sketch.jsonl"]] == [0, 1]
    assert len(rows["model_ir.jsonl"]) == 1
    assert any(row.get("round_index") == 1 for row in rows["evidence_bindings.jsonl"])
    assert result["summary"].feedback_loop_used is True
    assert result["summary"].final_round_index == 1
