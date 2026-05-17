from __future__ import annotations

import json
from pathlib import Path

from mech_pipeline.config import ProofConfig
from mech_pipeline.model.base import ModelClient
from mech_pipeline.modules.E_prover import ModuleE, _audit_context_with_blocked_obligations
from mech_pipeline.types import (
    GroundingResult,
    ModelResponse,
    ProofActionCheckResult,
    ProofContext,
    ProofObligationReplayItem,
    ProofSearchTrace,
    StatementCandidate,
    TheoremSkeletonCandidate,
)


class SequenceClient(ModelClient):
    def __init__(self, payloads: list[str]) -> None:
        self.model_id = "sequence"
        self.supports_vision = False
        self.payloads = payloads
        self.prompts: list[str] = []
        self.idx = 0

    def generate_text(self, prompt: str, **kwargs) -> ModelResponse:
        _ = kwargs
        self.prompts.append(prompt)
        payload = self.payloads[min(self.idx, len(self.payloads) - 1)]
        self.idx += 1
        return ModelResponse(text=payload)

    def generate_multimodal(self, prompt: str, images_b64: list[str], **kwargs) -> ModelResponse:
        _ = (prompt, images_b64, kwargs)
        return ModelResponse(text="{}")


class RoutingLeanRunner:
    timeout_s = 10

    def __init__(self, *, search_closes: bool = True, legacy_strict: bool = True) -> None:
        self.search_closes = search_closes
        self.legacy_strict = legacy_strict
        self.probes: list[str] = []
        self.verify_bodies: list[str] = []

    def probe_proof_prefix(self, *, lean_header, theorem_decl, proof_prefix, timeout_s=None):
        _ = (lean_header, theorem_decl, timeout_s)
        self.probes.append(proof_prefix)
        if self.search_closes and "exact h" in proof_prefix:
            return ProofActionCheckResult(
                action_id="probe",
                strategy="probe_proof_prefix",
                tactic_block=proof_prefix,
                status="closed",
            )
        return ProofActionCheckResult(
            action_id="probe",
            strategy="probe_proof_prefix",
            tactic_block=proof_prefix,
            status="invalid",
            error_type="tactic_failed",
        )

    def verify_proof(self, *, sample_id, candidate_id, lean_header, theorem_decl, proof_body, run_dir):
        _ = (sample_id, candidate_id, lean_header, theorem_decl, run_dir)
        self.verify_bodies.append(proof_body)
        return {
            "compile_pass": self.legacy_strict,
            "strict_pass": self.legacy_strict,
            "error_type": None if self.legacy_strict else "proof_search_failure",
            "stderr_digest": "" if self.legacy_strict else "failed",
            "log_path": None,
        }


def _prompt_files(tmp_path: Path) -> tuple[Path, Path, Path]:
    plan = tmp_path / "E_plan_proof.txt"
    gen = tmp_path / "E_generate_proof.txt"
    repair = tmp_path / "E_repair_proof.txt"
    plan.write_text("__TASK_E_PLAN_PROOF__\n{{theorem_decl}}\n{{problem_ir_json}}\n{{mechlib_context}}", encoding="utf-8")
    gen.write_text("__TASK_E_GENERATE_PROOF__\n{{theorem_decl}}\n{{problem_ir_json}}\n{{proof_plan_json}}\n{{mechlib_context}}", encoding="utf-8")
    repair.write_text("__TASK_E_REPAIR_PROOF__", encoding="utf-8")
    return plan, gen, repair


def _grounding() -> GroundingResult:
    return GroundingResult(
        sample_id="s1",
        model_id="m",
        problem_ir={},
        parse_ok=True,
        raw_response="",
        error=None,
    )


def _module(tmp_path: Path, client: SequenceClient, runner: RoutingLeanRunner, proof_config: ProofConfig) -> ModuleE:
    plan, gen, repair = _prompt_files(tmp_path)
    return ModuleE(
        model_client=client,
        lean_runner=runner,  # type: ignore[arg-type]
        prompt_plan_path=plan,
        prompt_generate_path=gen,
        prompt_repair_path=repair,
        max_attempts=1,
        proof_config=proof_config,
    )


def _search_payload() -> str:
    return json.dumps(
        {
            "proposals": [
                {
                    "strategy": "close_goal",
                    "tactic_block": "exact h",
                    "uses_facts": ["h"],
                    "uses_decls": [],
                    "priority": 1.0,
                }
            ]
        }
    )


def _legacy_plan_payload() -> str:
    return json.dumps(
        {
            "plan": "Use h.",
            "theorems_to_apply": [],
            "givens_to_use": ["h"],
            "intermediate_claims": [],
            "algebraic_cleanup_only": False,
        }
    )


def _legacy_proof_payload() -> str:
    return json.dumps({"proof_body": "exact h", "strategy": "use h"})


def test_minimal_skeleton_candidate_routes_to_llm_guided_search(tmp_path: Path) -> None:
    proof_config = ProofConfig(mode="auto")
    client = SequenceClient([_search_payload()])
    runner = RoutingLeanRunner(search_closes=True)
    module = _module(tmp_path, client, runner, proof_config)
    candidate = TheoremSkeletonCandidate(
        sample_id="s1",
        candidate_id="c1",
        lean_header="import Mathlib",
        theorem_decl="theorem t (h : True) : True",
    )

    attempts, check = module.run(_grounding(), candidate, tmp_path)

    assert attempts[0].proof_mode == "llm_guided_search"
    assert check.proof_mode == "llm_guided_search"
    assert check.proof_success is True
    assert runner.probes
    assert "__TASK_E_PLAN_PROOF__" not in client.prompts[0]


def test_legacy_candidate_routes_to_legacy_full_proof(tmp_path: Path) -> None:
    proof_config = ProofConfig(mode="auto")
    client = SequenceClient([_legacy_plan_payload(), _legacy_proof_payload()])
    runner = RoutingLeanRunner()
    module = _module(tmp_path, client, runner, proof_config)
    candidate = StatementCandidate(
        sample_id="s1",
        candidate_id="c1",
        lean_header="import Mathlib",
        theorem_decl="theorem t (h : True) : True",
    )

    attempts, check = module.run(_grounding(), candidate, tmp_path)

    assert attempts[0].proof_mode == "legacy_full_proof"
    assert check.proof_mode == "legacy_full_proof"
    assert check.proof_success is True
    assert "__TASK_E_PLAN_PROOF__" in client.prompts[0]


def test_llm_guided_search_failure_does_not_fallback_by_default(tmp_path: Path) -> None:
    proof_config = ProofConfig(mode="auto")
    client = SequenceClient([json.dumps({"proposals": []})])
    runner = RoutingLeanRunner(search_closes=False)
    module = _module(tmp_path, client, runner, proof_config)
    candidate = TheoremSkeletonCandidate(
        sample_id="s1",
        candidate_id="c1",
        lean_header="import Mathlib",
        theorem_decl="theorem t (h : True) : True",
    )

    attempts, check = module.run(_grounding(), candidate, tmp_path)

    assert len(attempts) == 1
    assert attempts[0].proof_mode == "llm_guided_search"
    assert attempts[0].fallback_to_legacy_full_proof is False
    assert check.fallback_to_legacy_full_proof is False
    assert check.proof_mode == "llm_guided_search"
    assert check.proof_success is False
    assert "__TASK_E_PLAN_PROOF__" not in "".join(client.prompts)


def test_llm_guided_search_failure_marks_explicit_legacy_fallback(tmp_path: Path) -> None:
    proof_config = ProofConfig(mode="auto", legacy_fallback_enabled=True)
    client = SequenceClient([
        json.dumps({"proposals": []}),
        _legacy_plan_payload(),
        _legacy_proof_payload(),
    ])
    runner = RoutingLeanRunner(search_closes=False)
    module = _module(tmp_path, client, runner, proof_config)
    candidate = TheoremSkeletonCandidate(
        sample_id="s1",
        candidate_id="c1",
        lean_header="import Mathlib",
        theorem_decl="theorem t (h : True) : True",
    )

    attempts, check = module.run(_grounding(), candidate, tmp_path)

    assert attempts[0].proof_mode == "llm_guided_search"
    assert attempts[-1].fallback_to_legacy_full_proof is True
    assert check.fallback_to_legacy_full_proof is True
    assert check.proof_mode == "legacy_full_proof"
    assert check.fully_mechlib_verified is False


def test_audit_context_moves_trace_blocked_obligations_out_of_required_items() -> None:
    context = ProofContext(
        sample_id="s1",
        candidate_id="c1",
        theorem_decl="theorem t : True",
        lean_header="import Mathlib",
        obligation_replay_items=[
            ProofObligationReplayItem(
                obligation_id="obl_bad",
                kind="law_to_equation",
                from_hypothesis=None,
                must_use="MechLib.Bad.Extractor",
                formal_claim="x = y",
                produced_fact_name="h_bad",
            )
        ],
    )
    trace = ProofSearchTrace(
        sample_id="s1",
        candidate_id="c1",
        blocked_obligations=[
            {
                "obligation_id": "obl_bad",
                "reason": "missing_proof_friendly_extractor",
            }
        ],
    )

    audit_context = _audit_context_with_blocked_obligations(context, trace)

    assert audit_context.obligation_replay_items == []
    assert [item.obligation_id for item in audit_context.obligation_replay_blocked] == ["obl_bad"]
    assert audit_context.obligation_replay_blocked[0].error == "missing_proof_friendly_extractor"
