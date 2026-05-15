from pathlib import Path
from types import SimpleNamespace

from mech_pipeline.config import PipelineConfig
from mech_pipeline.modules.solution_renderer import ModuleSolutionRenderer
from mech_pipeline.orchestrator import process_sample
from mech_pipeline.types import (
    CompileCheckResult,
    GroundingResult,
    ProofAttemptResult,
    ProofCheckResult,
    SemanticRankResult,
    TheoremSkeletonCandidate,
)


STAGE_FILES = (
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
    "proof_search_trace.jsonl",
    "proof_action_checks.jsonl",
    "proof_strategy_prompts.jsonl",
    "proof_dependency_audit.jsonl",
    "solution_trace.jsonl",
    "natural_solution.jsonl",
    "solution_render_audit.jsonl",
    "sample_summary.jsonl",
)


class StubA:
    def run(self, sample):
        return GroundingResult(sample.sample_id, "mock", {"goal_statement": "求静摩擦系数"}, True, "{}", None)


class StubB:
    def run(self, grounding, **_kwargs):
        return [
            TheoremSkeletonCandidate(
                sample_id=grounding.sample_id,
                candidate_id="c1",
                lean_header="import MechLib",
                theorem_decl="theorem t : mu_s.val = F_start.val / W.val := by",
                parse_ok=True,
                raw_response="{}",
                proof_obligations=[
                    {
                        "step_id": "sk1",
                        "kind": "law_to_equation",
                        "formal_claim": "F_start.val = mu_s.val * W.val",
                        "binding_status": "ok",
                        "proof_fact_allowed": True,
                        "verified_decl": "MechLib.Friction.staticFrictionMax",
                    }
                ],
            )
        ]


class StubC:
    lean_runner = None

    def run(self, sample_id, candidates, run_dir):
        return [
            CompileCheckResult(
                sample_id=sample_id,
                candidate_id=candidates[0].candidate_id,
                compile_pass=True,
                syntax_ok=True,
                elaboration_ok=True,
                error_type=None,
                stderr_digest="",
                log_path=None,
            )
        ]


class StubD:
    def __init__(self, semantic_pass=True):
        self.semantic_pass = semantic_pass

    def run(self, grounding, candidates, compile_checks, problem_text, mechlib_context):
        return SemanticRankResult(
            sample_id=grounding.sample_id,
            selected_candidate_id="c1",
            selected_theorem_decl=candidates[0].theorem_decl,
            semantic_pass=self.semantic_pass,
            ranking=[{"candidate_id": "c1", "semantic_pass": self.semantic_pass}],
            error=None if self.semantic_pass else "semantic_drift",
        )


class StubE:
    def run(self, grounding, selected_candidate, run_dir: Path, mechlib_context: str = "(none)"):
        attempt = ProofAttemptResult(
            sample_id=grounding.sample_id,
            attempt_index=0,
            proof_body="linarith",
            parse_ok=True,
            raw_response="",
            compile_pass=True,
            strict_pass=True,
            error_type=None,
            stderr_digest="",
            log_path=None,
            proof_mode="legacy_full_proof",
        )
        check = ProofCheckResult(
            sample_id=grounding.sample_id,
            proof_success=True,
            attempts_used=1,
            selected_candidate_id=selected_candidate.candidate_id,
            error_type=None,
            final_log_path=None,
            proof_mode="legacy_full_proof",
        )
        return [attempt], check


def _cfg():
    cfg = PipelineConfig()
    cfg.statement.generation_mode = "legacy_candidate"
    cfg.statement.feedback_loop_enabled = False
    cfg.knowledge.enabled = False
    cfg.solution_renderer.natural_language_enabled = False
    return cfg


def _run_process(tmp_path, semantic_pass=True):
    cfg = _cfg()

    def build_worker_modules(_cfg, _prompt_dir):
        return (
            StubA(),
            None,
            None,
            StubB(),
            StubC(),
            StubD(semantic_pass),
            StubE(),
            ModuleSolutionRenderer(config=cfg.solution_renderer),
        )

    return process_sample(
        cfg=cfg,
        sample=SimpleNamespace(sample_id="s1", problem_text="求静摩擦系数", image_description=None, skip_reason=None),
        run_dir=tmp_path,
        prompt_dir=tmp_path,
        inject_set=set(),
        retriever=None,
        preflight_ok=True,
        preflight_error=None,
        preflight_message="ok",
        stage_row_files=STAGE_FILES,
        build_worker_modules=build_worker_modules,
        build_revision_feedback=lambda **_kwargs: "",
    )


def test_orchestrator_writes_solution_rows_after_proof_success(tmp_path):
    result = _run_process(tmp_path, semantic_pass=True)
    rows = result["stage_rows"]
    assert rows["solution_trace.jsonl"]
    assert rows["natural_solution.jsonl"]
    assert rows["solution_render_audit.jsonl"]
    assert rows["natural_solution.jsonl"][0]["proof_status"] == "legacy_verified_no_audit"


def test_orchestrator_writes_partial_solution_after_proof_skipped(tmp_path):
    result = _run_process(tmp_path, semantic_pass=False)
    rows = result["stage_rows"]
    assert rows["natural_solution.jsonl"]
    assert rows["natural_solution.jsonl"][0]["proof_status"] == "proof_skipped_due_to_semantic_fail"
    assert "只展示" in rows["natural_solution.jsonl"][0]["natural_solution"]
