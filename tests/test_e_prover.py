from __future__ import annotations

from pathlib import Path

from mech_pipeline.model.base import ModelClient
from mech_pipeline.modules.E_prover import ModuleE
from mech_pipeline.types import GroundingResult, ModelResponse, StatementCandidate


class StaticProofClient(ModelClient):
    def __init__(self, payload: str) -> None:
        self.model_id = "static-e"
        self.supports_vision = False
        self._payload = payload

    def generate_text(self, prompt: str, **kwargs) -> ModelResponse:
        _ = (prompt, kwargs)
        return ModelResponse(text=self._payload)

    def generate_multimodal(self, prompt: str, images_b64: list[str], **kwargs) -> ModelResponse:
        _ = (prompt, images_b64, kwargs)
        return ModelResponse(text=self._payload)


class RecordingLeanRunner:
    def __init__(self) -> None:
        self.proof_bodies: list[str] = []

    def verify_proof(
        self,
        *,
        sample_id: str,
        candidate_id: str,
        lean_header: str,
        theorem_decl: str,
        proof_body: str,
        run_dir: Path,
    ) -> dict[str, object]:
        _ = (sample_id, candidate_id, lean_header, theorem_decl, run_dir)
        self.proof_bodies.append(proof_body)
        return {
            "compile_pass": False,
            "strict_pass": False,
            "error_type": "proof_search_failure",
            "stderr_digest": "failed",
            "log_path": None,
        }


def _grounding() -> GroundingResult:
    return GroundingResult(
        sample_id="s1",
        model_id="m",
        problem_ir={"unknown_target": {"symbol": "a"}},
        parse_ok=True,
        raw_response="",
        error=None,
    )


def _candidate() -> StatementCandidate:
    return StatementCandidate(
        sample_id="s1",
        candidate_id="c1",
        lean_header="import MechLib",
        theorem_decl="theorem t (F m a : Real) (hm : m ≠ 0) (h : F = m * a) : a = F / m",
        assumptions=[],
    )


def test_e_prover_does_not_inject_trivial_placeholder_when_response_is_unparseable(tmp_path: Path) -> None:
    prompt_generate = tmp_path / "E_generate_proof.txt"
    prompt_repair = tmp_path / "E_repair_proof.txt"
    prompt_generate.write_text("__TASK_E_GENERATE_PROOF__", encoding="utf-8")
    prompt_repair.write_text("__TASK_E_REPAIR_PROOF__", encoding="utf-8")
    runner = RecordingLeanRunner()
    module = ModuleE(
        model_client=StaticProofClient("not-json"),
        lean_runner=runner,
        prompt_generate_path=prompt_generate,
        prompt_repair_path=prompt_repair,
        max_attempts=2,
    )

    attempts, check = module.run(_grounding(), _candidate(), tmp_path)

    assert len(attempts) == 2
    assert attempts[0].proof_body == ""
    assert attempts[0].error_type == "proof_response_parse_failed"
    assert attempts[1].proof_body == ""
    assert runner.proof_bodies == []
    assert check.proof_success is False
    assert check.attempts_used == 2
    assert attempts[0].sub_error_type == "proof_response_parse_failed"
    assert attempts[0].failure_summary is not None
    assert attempts[0].stderr_excerpt is not None


def test_e_prover_does_not_run_bare_tactic_fallbacks_after_failed_llm_attempts(tmp_path: Path) -> None:
    prompt_generate = tmp_path / "E_generate_proof.txt"
    prompt_repair = tmp_path / "E_repair_proof.txt"
    prompt_generate.write_text("__TASK_E_GENERATE_PROOF__", encoding="utf-8")
    prompt_repair.write_text("__TASK_E_REPAIR_PROOF__", encoding="utf-8")
    runner = RecordingLeanRunner()
    module = ModuleE(
        model_client=StaticProofClient('{"proof_body":"by\\n  have h1 : F = m * a := h\\n  exact by linarith","strategy":"test"}'),
        lean_runner=runner,
        prompt_generate_path=prompt_generate,
        prompt_repair_path=prompt_repair,
        max_attempts=2,
    )

    attempts, check = module.run(_grounding(), _candidate(), tmp_path)

    assert len(attempts) == 2
    assert runner.proof_bodies == [attempts[0].proof_body, attempts[1].proof_body]
    assert all(body not in {"rfl", "simp", "aesop", "linarith", "ring", "trivial"} for body in runner.proof_bodies)
    assert check.proof_success is False
    assert check.attempts_used == 2
    assert check.sub_error_type == "wrong_tactic_strategy"


class RewritingLeanRunner(RecordingLeanRunner):
    def verify_proof(
        self,
        *,
        sample_id: str,
        candidate_id: str,
        lean_header: str,
        theorem_decl: str,
        proof_body: str,
        run_dir: Path,
    ) -> dict[str, object]:
        _ = (sample_id, candidate_id, lean_header, theorem_decl, run_dir)
        self.proof_bodies.append(proof_body)
        return {
            "compile_pass": False,
            "strict_pass": False,
            "error_type": "proof_search_failure",
            "stderr_digest": "rewrite tactic failed, did not find instance of the pattern in the target expression",
            "log_path": None,
            "error_line": 12,
            "error_message": "rewrite tactic failed",
            "error_snippet": "rewrite tactic failed",
            "stderr_excerpt": "rewrite tactic failed",
        }


def test_e_prover_captures_structured_proof_failure_details(tmp_path: Path) -> None:
    prompt_generate = tmp_path / "E_generate_proof.txt"
    prompt_repair = tmp_path / "E_repair_proof.txt"
    prompt_generate.write_text("__TASK_E_GENERATE_PROOF__", encoding="utf-8")
    prompt_repair.write_text("__TASK_E_REPAIR_PROOF__", encoding="utf-8")
    runner = RewritingLeanRunner()
    module = ModuleE(
        model_client=StaticProofClient('{"proof_body":"by\\n  rw [h]\\n  ring","strategy":"rewrite"}'),
        lean_runner=runner,
        prompt_generate_path=prompt_generate,
        prompt_repair_path=prompt_repair,
        max_attempts=1,
    )

    attempts, check = module.run(_grounding(), _candidate(), tmp_path)

    assert len(attempts) == 1
    assert attempts[0].sub_error_type == "algebraic_rewrite_missing"
    assert attempts[0].proof_body_excerpt is not None
    assert attempts[0].failure_details["error_line"] == 12
    assert check.sub_error_type == "algebraic_rewrite_missing"
    assert check.failure_summary is not None
