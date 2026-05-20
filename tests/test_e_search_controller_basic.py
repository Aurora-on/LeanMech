from __future__ import annotations

import json

from mech_pipeline.adapters.lean_runner import classify_proof_probe_result
from mech_pipeline.config import PipelineConfig
from mech_pipeline.modules.e_search_controller import (
    _component_close_proposal,
    _indent_tactic_body,
    _target_components,
    run_llm_guided_search,
)
from mech_pipeline.types import ProofActionCheckResult, ProofContext, ProofObligationReplayItem, ProofSearchNode


class FakeLLM:
    def __init__(self, proposals: list[dict[str, object]]) -> None:
        self.proposals = proposals
        self.calls = 0
        self.prompts: list[str] = []

    def generate_text(self, prompt: str):
        self.calls += 1
        self.prompts.append(prompt)

        class Response:
            text = json.dumps({"proposals": self.proposals})

        return Response()


class PayloadFakeLLM:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.calls = 0
        self.prompts: list[str] = []

    def generate_text(self, prompt: str):
        self.calls += 1
        self.prompts.append(prompt)

        class Response:
            text = json.dumps(self.payload)

        return Response()


class SequentialPayloadFakeLLM:
    def __init__(self, payloads: list[dict[str, object]]) -> None:
        self.payloads = list(payloads)
        self.calls = 0
        self.prompts: list[str] = []

    def generate_text(self, prompt: str):
        self.calls += 1
        self.prompts.append(prompt)
        payload = self.payloads[min(self.calls - 1, len(self.payloads) - 1)]

        class Response:
            text = json.dumps(payload)

        return Response()


class SequentialFakeLLM:
    def __init__(self, proposal_batches: list[list[dict[str, object]]]) -> None:
        self.proposal_batches = proposal_batches
        self.calls = 0
        self.prompts: list[str] = []

    def generate_text(self, prompt: str):
        self.calls += 1
        self.prompts.append(prompt)
        batch = self.proposal_batches[min(self.calls - 1, len(self.proposal_batches) - 1)]

        class Response:
            text = json.dumps({"proposals": batch})

        return Response()


class FakeLeanRunner:
    def __init__(self, *, closed_token: str = "close_goal", progress_token: str = "progress_action") -> None:
        self.closed_token = closed_token
        self.progress_token = progress_token
        self.probes: list[str] = []
        self.timeouts: list[int | None] = []
        self.verify_calls: list[str] = []
        self.compile_calls: list[str] = []

    def compile_statement(self, *, sample_id, candidate_id, lean_header, theorem_decl, run_dir):
        _ = (sample_id, candidate_id, lean_header, run_dir)
        self.compile_calls.append(theorem_decl)
        return {"compile_pass": True, "syntax_ok": True, "elaboration_ok": True}

    def probe_proof_prefix(self, *, lean_header, theorem_decl, proof_prefix, timeout_s=None):
        _ = (lean_header, theorem_decl)
        self.probes.append(proof_prefix)
        self.timeouts.append(timeout_s)
        if self.closed_token in proof_prefix:
            return ProofActionCheckResult(
                action_id="probe",
                strategy="probe_proof_prefix",
                tactic_block=proof_prefix,
                status="closed",
            )
        if self.progress_token in proof_prefix:
            return ProofActionCheckResult(
                action_id="probe",
                strategy="probe_proof_prefix",
                tactic_block=proof_prefix,
                status="progress",
                goals_excerpt="unsolved goals",
            )
        return ProofActionCheckResult(
            action_id="probe",
            strategy="probe_proof_prefix",
            tactic_block=proof_prefix,
            status="invalid",
            error_type="symbol_hallucination",
            error_message="unknown identifier",
            error_line=12,
            error_col=6,
            error_snippet="/tmp/probe.lean:12:6: error: unknown identifier",
        )

    def verify_proof(self, *, sample_id, candidate_id, lean_header, theorem_decl, proof_body, run_dir):
        _ = (sample_id, candidate_id, lean_header, theorem_decl, run_dir)
        self.verify_calls.append(proof_body)
        return {"strict_pass": True}


class NoGoalsRepairLeanRunner(FakeLeanRunner):
    def probe_proof_prefix(self, *, lean_header, theorem_decl, proof_prefix, timeout_s=None):
        _ = (lean_header, theorem_decl)
        self.probes.append(proof_prefix)
        self.timeouts.append(timeout_s)
        if "exact h_final" in proof_prefix:
            return ProofActionCheckResult(
                action_id="probe",
                strategy="probe_proof_prefix",
                tactic_block=proof_prefix,
                status="closed",
            )
        if "have h_final" in proof_prefix:
            h_final_block = proof_prefix.split("have h_final", 1)[1]
            if "ring_nf" in h_final_block or "simp" in h_final_block:
                return ProofActionCheckResult(
                    action_id="probe",
                    strategy="probe_proof_prefix",
                    tactic_block=proof_prefix,
                    status="invalid",
                    error_type="tactic_no_goals",
                    error_message="No goals to be solved",
                    stderr_excerpt="error: No goals to be solved",
                )
            if "exact h_one" in h_final_block:
                return ProofActionCheckResult(
                    action_id="probe",
                    strategy="probe_proof_prefix",
                    tactic_block=proof_prefix,
                    status="progress",
                    goals_excerpt="unsolved goals",
                )
        if "have h_one" in proof_prefix:
            return ProofActionCheckResult(
                action_id="probe",
                strategy="probe_proof_prefix",
                tactic_block=proof_prefix,
                status="progress",
                goals_excerpt="unsolved goals",
            )
        return super().probe_proof_prefix(
            lean_header=lean_header,
            theorem_decl=theorem_decl,
            proof_prefix=proof_prefix,
            timeout_s=timeout_s,
        )


class ClaimRepairLeanRunner(FakeLeanRunner):
    def probe_proof_prefix(self, *, lean_header, theorem_decl, proof_prefix, timeout_s=None):
        _ = (lean_header, theorem_decl)
        self.probes.append(proof_prefix)
        self.timeouts.append(timeout_s)
        if "exact h_final" in proof_prefix:
            return ProofActionCheckResult(
                action_id="probe",
                strategy="probe_proof_prefix",
                tactic_block=proof_prefix,
                status="closed",
            )
        if "have h_final" in proof_prefix:
            h_final_block = proof_prefix.split("have h_final", 1)[1]
            if "bad_fact" in h_final_block:
                return ProofActionCheckResult(
                    action_id="probe",
                    strategy="probe_proof_prefix",
                    tactic_block=proof_prefix,
                    status="invalid",
                    error_type="type_mismatch",
                    error_message="Type mismatch: bad_fact has type False but expected True",
                    stderr_excerpt="error: Type mismatch: bad_fact has type False but expected True",
                    goals_excerpt="unsolved goals\nh_one : True\n⊢ True",
                )
            if "exact h_one" in h_final_block:
                return ProofActionCheckResult(
                    action_id="probe",
                    strategy="probe_proof_prefix",
                    tactic_block=proof_prefix,
                    status="progress",
                    goals_excerpt="unsolved goals",
                )
        if "have h_one" in proof_prefix:
            return ProofActionCheckResult(
                action_id="probe",
                strategy="probe_proof_prefix",
                tactic_block=proof_prefix,
                status="progress",
                goals_excerpt="unsolved goals",
            )
        return super().probe_proof_prefix(
            lean_header=lean_header,
            theorem_decl=theorem_decl,
            proof_prefix=proof_prefix,
            timeout_s=timeout_s,
        )


class ErrorCategoryWithGoalsLeanRunner(FakeLeanRunner):
    def probe_proof_prefix(self, *, lean_header, theorem_decl, proof_prefix, timeout_s=None):
        _ = (lean_header, theorem_decl, timeout_s)
        self.probes.append(proof_prefix)
        return classify_proof_probe_result(
            ok=False,
            stdout="",
            stderr="""
/tmp/pipeline_proof_probe.lean:31:19: error(lean.unknownIdentifier): Unknown identifier `missing_h`
/tmp/pipeline_proof_probe.lean:29:53: error: unsolved goals
h : True
⊢ True
""",
            tactic_block=proof_prefix,
            probe_full_proof_body=proof_prefix,
        )


class StructuralPreludeLeanRunner(FakeLeanRunner):
    def probe_proof_prefix(self, *, lean_header, theorem_decl, proof_prefix, timeout_s=None):
        _ = (lean_header, theorem_decl)
        self.probes.append(proof_prefix)
        self.timeouts.append(timeout_s)
        if proof_prefix.strip() == "intro t0":
            return ProofActionCheckResult(
                action_id="probe",
                strategy="probe_proof_prefix",
                tactic_block=proof_prefix,
                status="progress",
                goals_excerpt="unsolved goals\nt0 : Real\n⊢ t0 = t0",
            )
        if "exact hvel t0" in proof_prefix:
            return ProofActionCheckResult(
                action_id="probe",
                strategy="probe_proof_prefix",
                tactic_block=proof_prefix,
                status="closed" if proof_prefix.strip().startswith("intro t0") else "invalid",
                error_type=None if proof_prefix.strip().startswith("intro t0") else "symbol_hallucination",
                error_message=None if proof_prefix.strip().startswith("intro t0") else "Unknown identifier `t0`",
            )
        return super().probe_proof_prefix(
            lean_header=lean_header,
            theorem_decl=theorem_decl,
            proof_prefix=proof_prefix,
            timeout_s=timeout_s,
        )


class StructuralDomainLeanRunner(FakeLeanRunner):
    def probe_proof_prefix(self, *, lean_header, theorem_decl, proof_prefix, timeout_s=None):
        _ = (lean_header, theorem_decl)
        self.probes.append(proof_prefix)
        self.timeouts.append(timeout_s)
        prelude = "intro hdom\nrcases hdom with ⟨h0, h1⟩"
        if proof_prefix.strip() == prelude:
            return ProofActionCheckResult(
                action_id="probe",
                strategy="probe_proof_prefix",
                tactic_block=proof_prefix,
                status="progress",
                goals_excerpt="unsolved goals\nh0 : 0 <= t0\nh1 : t0 <= 4\n⊢ True",
            )
        if "exact trivial" in proof_prefix and prelude in proof_prefix:
            return ProofActionCheckResult(
                action_id="probe",
                strategy="probe_proof_prefix",
                tactic_block=proof_prefix,
                status="closed",
            )
        return super().probe_proof_prefix(
            lean_header=lean_header,
            theorem_decl=theorem_decl,
            proof_prefix=proof_prefix,
            timeout_s=timeout_s,
        )


class UniversalInstantiationLeanRunner(FakeLeanRunner):
    def probe_proof_prefix(self, *, lean_header, theorem_decl, proof_prefix, timeout_s=None):
        _ = (lean_header, theorem_decl)
        self.probes.append(proof_prefix)
        self.timeouts.append(timeout_s)
        prelude = "intro t0\nintro hdom\nrcases hdom with ⟨h0, h1⟩"
        if proof_prefix.strip() == prelude:
            return ProofActionCheckResult(
                action_id="probe",
                strategy="probe_proof_prefix",
                tactic_block=proof_prefix,
                status="progress",
                goals_excerpt="unsolved goals\nt0 : Real\nh0 : 0 <= t0\nh1 : t0 <= 4\n⊢ (v t0).val = 6 * t0 - 2",
            )
        if "exact h_inst_hvel" in proof_prefix:
            return ProofActionCheckResult(
                action_id="probe",
                strategy="probe_proof_prefix",
                tactic_block=proof_prefix,
                status="closed",
            )
        if "have h_inst_hvel" in proof_prefix:
            return ProofActionCheckResult(
                action_id="probe",
                strategy="probe_proof_prefix",
                tactic_block=proof_prefix,
                status="progress",
                goals_excerpt="unsolved goals\nh_inst_hvel : (v t0).val = 6 * t0 - 2",
            )
        return super().probe_proof_prefix(
            lean_header=lean_header,
            theorem_decl=theorem_decl,
            proof_prefix=proof_prefix,
            timeout_s=timeout_s,
        )


class TimeTargetInstantiationLeanRunner(FakeLeanRunner):
    def probe_proof_prefix(self, *, lean_header, theorem_decl, proof_prefix, timeout_s=None):
        _ = (lean_header, theorem_decl)
        self.probes.append(proof_prefix)
        self.timeouts.append(timeout_s)
        if "hglobal k" in proof_prefix:
            raise AssertionError("universal instantiator must not instantiate time forall with k")
        if proof_prefix.strip() == "intro hcond":
            return ProofActionCheckResult(
                action_id="probe",
                strategy="probe_proof_prefix",
                tactic_block=proof_prefix,
                status="progress",
                goals_excerpt=(
                    "unsolved goals\n"
                    "k : Real\n"
                    "t_half : Time\n"
                    "hcond : k > 0\n"
                    "⊢ (omega t_half.val).val <= 0"
                ),
                unsolved_goal_count=1,
            )
        if "exact h_inst_hglobal" in proof_prefix:
            return ProofActionCheckResult(
                action_id="probe",
                strategy="probe_proof_prefix",
                tactic_block=proof_prefix,
                status="closed",
                unsolved_goal_count=0,
            )
        if "have h_inst_hglobal" in proof_prefix and "hglobal t_half.val" in proof_prefix:
            return ProofActionCheckResult(
                action_id="probe",
                strategy="probe_proof_prefix",
                tactic_block=proof_prefix,
                status="progress",
                goals_excerpt=(
                    "unsolved goals\n"
                    "h_inst_hglobal : (omega t_half.val).val <= 0\n"
                    "⊢ (omega t_half.val).val <= 0"
                ),
                unsolved_goal_count=1,
            )
        return super().probe_proof_prefix(
            lean_header=lean_header,
            theorem_decl=theorem_decl,
            proof_prefix=proof_prefix,
            timeout_s=timeout_s,
        )


class NoPhantomT0InstantiationLeanRunner(FakeLeanRunner):
    def probe_proof_prefix(self, *, lean_header, theorem_decl, proof_prefix, timeout_s=None):
        _ = (lean_header, theorem_decl)
        self.probes.append(proof_prefix)
        self.timeouts.append(timeout_s)
        if "hglobal t0" in proof_prefix:
            raise AssertionError("universal instantiator must not use t0 unless it is introduced")
        if proof_prefix.strip() == "intro hcond":
            return ProofActionCheckResult(
                action_id="probe",
                strategy="probe_proof_prefix",
                tactic_block=proof_prefix,
                status="progress",
                goals_excerpt=(
                    "unsolved goals\n"
                    "k : Real\n"
                    "hglobal : forall (t0 : Real), (omega t0).val <= 0\n"
                    "hcond : k > 0\n"
                    "⊢ True"
                ),
                unsolved_goal_count=1,
            )
        return super().probe_proof_prefix(
            lean_header=lean_header,
            theorem_decl=theorem_decl,
            proof_prefix=proof_prefix,
            timeout_s=timeout_s,
        )


class DeterministicRepairLeanRunner(FakeLeanRunner):
    def probe_proof_prefix(self, *, lean_header, theorem_decl, proof_prefix, timeout_s=None):
        _ = (lean_header, theorem_decl)
        self.probes.append(proof_prefix)
        self.timeouts.append(timeout_s)
        if "field_simp [hden] at *" in proof_prefix:
            return ProofActionCheckResult(
                action_id="probe",
                strategy="probe_proof_prefix",
                tactic_block=proof_prefix,
                status="progress",
                goals_excerpt="unsolved goals",
            )
        if "nlinarith [h_eq]" in proof_prefix:
            return ProofActionCheckResult(
                action_id="probe",
                strategy="probe_proof_prefix",
                tactic_block=proof_prefix,
                status="invalid",
                error_type="nlinarith_failed",
                error_message="nlinarith failed to solve",
                stderr_excerpt="error: nlinarith failed to solve",
            )
        if "linarith [h_eq]" in proof_prefix:
            return ProofActionCheckResult(
                action_id="probe",
                strategy="probe_proof_prefix",
                tactic_block=proof_prefix,
                status="progress",
                goals_excerpt="unsolved goals",
            )
        if "rw [h_eq]" in proof_prefix:
            return ProofActionCheckResult(
                action_id="probe",
                strategy="probe_proof_prefix",
                tactic_block=proof_prefix,
                status="invalid",
                error_type="rewrite_failed",
                error_message="rewrite failed, pattern not found",
                stderr_excerpt="error: rewrite failed, pattern not found",
            )
        return super().probe_proof_prefix(
            lean_header=lean_header,
            theorem_decl=theorem_decl,
            proof_prefix=proof_prefix,
            timeout_s=timeout_s,
        )


def _cfg(*, max_nodes: int = 4, max_llm_calls: int = 1) -> PipelineConfig:
    cfg = PipelineConfig()
    cfg.proof.llm_guided_search.max_nodes = max_nodes
    cfg.proof.llm_guided_search.max_depth = 4
    cfg.proof.llm_guided_search.max_llm_calls = max_llm_calls
    cfg.proof.llm_guided_search.proposals_per_call = 3
    cfg.proof.llm_guided_search.deterministic_obligation_replay_first = False
    cfg.proof.llm_guided_search.deterministic_side_conditions_first = False
    return cfg


def _context() -> ProofContext:
    return ProofContext(
        sample_id="s1",
        candidate_id="c1",
        theorem_decl="theorem c1 (h : True) : True",
        lean_header="import Mathlib",
        target_formula="True",
        local_binders=["h : True"],
        allowed_local_facts=["h"],
        local_hypotheses=["h"],
    )


def test_search_controller_enters_forall_context_before_llm() -> None:
    cfg = _cfg(max_nodes=3, max_llm_calls=1)
    context = ProofContext(
        sample_id="s_forall",
        candidate_id="c_forall",
        theorem_decl="theorem c_forall (hvel : forall t0 : Real, t0 = t0) : forall t0 : Real, t0 = t0",
        lean_header="import Mathlib",
        target_formula="forall t0 : Real, t0 = t0",
        local_binders=["hvel : forall t0 : Real, t0 = t0"],
        allowed_local_facts=["hvel"],
        local_hypotheses=["hvel"],
    )
    llm = FakeLLM(
        [
            {
                "strategy": "close_goal",
                "tactic_block": "exact hvel t0",
                "uses_facts": ["hvel"],
                "uses_decls": [],
            }
        ]
    )
    runner = StructuralPreludeLeanRunner()

    trace = run_llm_guided_search(
        proof_context=context,
        lean_runner=runner,
        llm_client=llm,
        cfg=cfg,
    )

    assert runner.probes[0].strip() == "intro t0"
    assert trace.search_status == "success"
    assert trace.final_proof_body and trace.final_proof_body.startswith("intro t0")
    assert trace.accepted_actions[0]["strategy"] == "structural_prelude"
    assert trace.accepted_actions[0]["introduced_locals"] == ["t0"]
    assert '"target": "forall t0 : Real, t0 = t0"' in llm.prompts[0]
    assert '"target": "Real,' not in llm.prompts[0]
    assert '"t0 : Real"' in llm.prompts[0]


def test_search_controller_enters_implication_domain_context_before_llm() -> None:
    cfg = _cfg(max_nodes=3, max_llm_calls=1)
    context = ProofContext(
        sample_id="s_domain",
        candidate_id="c_domain",
        theorem_decl="theorem c_domain (t0 : Real) : 0 <= t0 ∧ t0 <= 4 -> True",
        lean_header="import Mathlib",
        target_formula="0 <= t0 ∧ t0 <= 4 -> True",
        local_binders=["t0 : Real"],
    )
    llm = FakeLLM(
        [
            {
                "strategy": "close_goal",
                "tactic_block": "exact trivial",
                "uses_facts": [],
                "uses_decls": [],
            }
        ]
    )
    runner = StructuralDomainLeanRunner(closed_token="not_present", progress_token="not_present")

    trace = run_llm_guided_search(
        proof_context=context,
        lean_runner=runner,
        llm_client=llm,
        cfg=cfg,
    )

    assert runner.probes[0].strip() == "intro hdom\nrcases hdom with ⟨h0, h1⟩"
    assert trace.search_status == "success"
    assert trace.final_proof_body and trace.final_proof_body.startswith("intro hdom")
    assert trace.accepted_actions[0]["introduced_locals"] == ["h0", "h1"]
    assert '"h0 : 0 <= t0"' in llm.prompts[0]
    assert '"h1 : t0 <= 4"' in llm.prompts[0]


def test_search_controller_instantiates_universal_hypotheses_after_structural_prelude() -> None:
    cfg = _cfg(max_nodes=3, max_llm_calls=1)
    context = ProofContext(
        sample_id="s_universal",
        candidate_id="c_universal",
        theorem_decl=(
            "theorem c_universal "
            "(hvel : forall t0 : Real, 0 <= t0 -> t0 <= 4 -> (v t0).val = 6 * t0 - 2) : "
            "forall t0 : Real, 0 <= t0 ∧ t0 <= 4 -> (v t0).val = 6 * t0 - 2"
        ),
        lean_header="import Mathlib",
        target_formula="forall t0 : Real, 0 <= t0 ∧ t0 <= 4 -> (v t0).val = 6 * t0 - 2",
        local_binders=["hvel : forall t0 : Real, 0 <= t0 -> t0 <= 4 -> (v t0).val = 6 * t0 - 2"],
        allowed_local_facts=["hvel"],
        local_hypotheses=["hvel"],
    )
    llm = FakeLLM(
        [
            {
                "strategy": "close_goal",
                "tactic_block": "exact h_inst_hvel",
                "uses_facts": ["h_inst_hvel"],
                "uses_decls": [],
            }
        ]
    )

    trace = run_llm_guided_search(
        proof_context=context,
        lean_runner=UniversalInstantiationLeanRunner(closed_token="not_present", progress_token="not_present"),
        llm_client=llm,
        cfg=cfg,
    )

    assert trace.search_status == "success"
    assert any(row["strategy"] == "instantiate_universal_fact" for row in trace.accepted_actions)
    instantiation = [row for row in trace.accepted_actions if row["strategy"] == "instantiate_universal_fact"][0]
    assert "exact hvel t0 h0 h1" in instantiation["tactic_block"]
    assert '"h_inst_hvel : (v t0).val = 6 * t0 - 2"' in llm.prompts[0]


def test_component_planner_flattens_nested_conjunction_and_generates_exact() -> None:
    context = ProofContext(
        sample_id="s_components",
        candidate_id="c_components",
        theorem_decl="theorem c_components (hA : A) (hB : B) (hC : C) (hD : D) : A ∧ B ∧ C ∧ D",
        lean_header="import Mathlib",
        target_formula="A ∧ B ∧ C ∧ D",
        local_binders=["hA : A", "hB : B", "hC : C", "hD : D"],
        allowed_local_facts=["hA", "hB", "hC", "hD"],
        local_hypotheses=["hA", "hB", "hC", "hD"],
    )
    node = ProofSearchNode(
        node_id="root",
        parent_id=None,
        depth=0,
        proof_prefix="",
        local_facts=["hA", "hB", "hC", "hD"],
        local_fact_types={},
    )

    proposal = _component_close_proposal(context, node)

    assert _target_components(context) == ["A", "B", "C", "D"]
    assert proposal is not None
    assert proposal.strategy == "close_target_components"
    assert proposal.tactic_block == "exact ⟨hA, hB, hC, hD⟩"


def test_search_controller_rejects_llm_manual_conjunction_close_when_components_missing() -> None:
    cfg = _cfg(max_nodes=1, max_llm_calls=1)
    cfg.proof.llm_guided_search.deterministic_obligation_replay_first = False
    cfg.proof.llm_guided_search.deterministic_side_conditions_first = False
    context = ProofContext(
        sample_id="s_components_missing",
        candidate_id="c_components_missing",
        theorem_decl="theorem c_components_missing (hA : A) : A ∧ B ∧ C ∧ D",
        lean_header="import Mathlib",
        target_formula="A ∧ B ∧ C ∧ D",
        local_binders=["hA : A"],
        allowed_local_facts=["hA"],
        local_hypotheses=["hA"],
    )
    llm = FakeLLM(
        [
            {
                "strategy": "target_fact_plan_close",
                "tactic_block": "constructor\n· exact hA\n· constructor\n  · sorry\n  · constructor\n    · sorry\n    · sorry",
                "uses_facts": ["hA"],
                "uses_decls": [],
            }
        ]
    )

    trace = run_llm_guided_search(
        proof_context=context,
        lean_runner=FakeLeanRunner(closed_token="not_present", progress_token="not_present"),
        llm_client=llm,
        cfg=cfg,
    )

    assert trace.rejected_actions
    assert trace.rejected_actions[0]["error_type"] == "target_component_facts_missing"
    assert "B" in trace.rejected_actions[0]["missing_target_components"]
    assert trace.rejected_actions[0]["error_type"] != "branching_constructor_disallowed_linear_prefix"


def test_universal_instantiator_does_not_use_arbitrary_real_constant_as_time() -> None:
    cfg = _cfg(max_nodes=3, max_llm_calls=1)
    context = ProofContext(
        sample_id="s_time_target",
        candidate_id="c_time_target",
        theorem_decl=(
            "theorem c_time_target "
            "(k : Real) (t_half : Time) "
            "(omega : Real -> AngularVelocity) "
            "(hglobal : forall t0 : Real, (omega t0).val <= 0) : "
            "k > 0 -> (omega t_half.val).val <= 0"
        ),
        lean_header="import Mathlib\nimport MechLib",
        target_formula="k > 0 -> (omega t_half.val).val <= 0",
        local_binders=[
            "k : Real",
            "t_half : Time",
            "omega : Real -> AngularVelocity",
            "hglobal : forall t0 : Real, (omega t0).val <= 0",
        ],
        allowed_local_facts=["hglobal"],
        local_hypotheses=["hglobal"],
    )
    llm = FakeLLM(
        [
            {
                "strategy": "close_goal",
                "tactic_block": "exact h_inst_hglobal",
                "uses_facts": ["h_inst_hglobal"],
                "uses_decls": [],
            }
        ]
    )
    runner = TimeTargetInstantiationLeanRunner(closed_token="not_present", progress_token="not_present")

    trace = run_llm_guided_search(
        proof_context=context,
        lean_runner=runner,
        llm_client=llm,
        cfg=cfg,
    )

    assert trace.search_status == "success"
    instantiation = [row for row in trace.accepted_actions if row["strategy"] == "instantiate_universal_fact"][0]
    assert "hglobal t_half.val" in instantiation["tactic_block"]
    assert "hglobal k" not in "\n".join(runner.probes)


def test_universal_instantiator_does_not_use_t0_from_goal_local_context() -> None:
    cfg = _cfg(max_nodes=1, max_llm_calls=0)
    context = ProofContext(
        sample_id="s_no_phantom_t0",
        candidate_id="c_no_phantom_t0",
        theorem_decl=(
            "theorem c_no_phantom_t0 "
            "(k : Real) (omega : Real -> AngularVelocity) "
            "(hglobal : forall t0 : Real, (omega t0).val <= 0) : "
            "k > 0 -> True"
        ),
        lean_header="import Mathlib\nimport MechLib",
        target_formula="k > 0 -> True",
        local_binders=[
            "k : Real",
            "omega : Real -> AngularVelocity",
            "hglobal : forall t0 : Real, (omega t0).val <= 0",
        ],
        allowed_local_facts=["hglobal"],
        local_hypotheses=["hglobal"],
    )
    runner = NoPhantomT0InstantiationLeanRunner(closed_token="not_present", progress_token="not_present")

    trace = run_llm_guided_search(
        proof_context=context,
        lean_runner=runner,
        llm_client=FakeLLM([]),
        cfg=cfg,
    )

    assert not any(row["strategy"] == "instantiate_universal_fact" for row in trace.accepted_actions)
    assert "hglobal t0" not in "\n".join(runner.probes)


def test_claim_repair_tactic_body_indents_single_line_nested_have() -> None:
    body = """nlinarith [given_mass_relation]
have hmb_ne : m_B.val ≠ 0 := by
linarith [h_m_B_pos]
apply (mul_right_cancel₀ hmb_ne)"""

    assert _indent_tactic_body(body) == (
        "  nlinarith [given_mass_relation]\n"
        "  have hmb_ne : m_B.val ≠ 0 := by\n"
        "    linarith [h_m_B_pos]\n"
        "  apply (mul_right_cancel₀ hmb_ne)"
    )


def test_search_controller_repairs_fraction_claim_with_field_simp_before_llm_repair() -> None:
    context = ProofContext(
        sample_id="s_fraction_repair",
        candidate_id="c_fraction_repair",
        theorem_decl="theorem c_fraction_repair (h_eq : True) (hden : y ≠ 0) : True",
        lean_header="import Mathlib",
        target_formula="True",
        local_binders=["h_eq : True", "hden : y ≠ 0"],
        allowed_local_facts=["h_eq", "hden"],
        local_hypotheses=["h_eq", "hden"],
    )
    llm = FakeLLM(
        [
            {
                "strategy": "introduce_intermediate_have",
                "tactic_block": "have h_frac : x / y = z := by\n  nlinarith [h_eq]",
                "uses_facts": ["h_eq"],
                "uses_decls": [],
            }
        ]
    )

    trace = run_llm_guided_search(
        proof_context=context,
        lean_runner=DeterministicRepairLeanRunner(progress_token="not_present"),
        llm_client=llm,
        cfg=_cfg(max_nodes=2, max_llm_calls=1),
    )

    assert llm.calls == 1
    assert any(row.get("repair_kind") == "fraction_field_simp_then_nlinarith" for row in trace.accepted_actions)
    assert "field_simp [hden] at *" in trace.accepted_actions[0]["tactic_block"]


def test_search_controller_repairs_rewrite_failure_with_linarith_before_llm_repair() -> None:
    context = ProofContext(
        sample_id="s_rw_repair",
        candidate_id="c_rw_repair",
        theorem_decl="theorem c_rw_repair (h_eq : True) : True",
        lean_header="import Mathlib",
        target_formula="True",
        local_binders=["h_eq : True"],
        allowed_local_facts=["h_eq"],
        local_hypotheses=["h_eq"],
    )
    llm = FakeLLM(
        [
            {
                "strategy": "introduce_intermediate_have",
                "tactic_block": "have h_rw : True := by\n  rw [h_eq]",
                "uses_facts": ["h_eq"],
                "uses_decls": [],
            }
        ]
    )

    trace = run_llm_guided_search(
        proof_context=context,
        lean_runner=DeterministicRepairLeanRunner(progress_token="not_present"),
        llm_client=llm,
        cfg=_cfg(max_nodes=2, max_llm_calls=1),
    )

    assert any(row.get("repair_kind") == "rewrite_failed_algebra_or_simpa" for row in trace.accepted_actions)
    assert "linarith [h_eq]" in trace.accepted_actions[0]["tactic_block"]


def test_search_controller_accepts_valid_progress_action_into_node() -> None:
    llm = FakeLLM(
        [
            {
                "strategy": "introduce_intermediate_have",
                "tactic_block": "have progress_action : True := by\n  exact h",
                "uses_facts": ["h"],
                "uses_decls": [],
                "priority": 0.7,
            }
        ]
    )
    runner = FakeLeanRunner(progress_token="progress_action")

    trace = run_llm_guided_search(
        proof_context=_context(),
        lean_runner=runner,
        llm_client=llm,
        cfg=_cfg(max_nodes=2, max_llm_calls=1),
    )

    assert trace.accepted_actions
    assert trace.accepted_actions[0]["status"] == "progress"
    assert trace.nodes_expanded <= 2
    assert trace.probe_checks == 1


def test_search_controller_prompt_uses_active_goal_and_full_local_fact_claims() -> None:
    llm = SequentialFakeLLM(
        [
            [
                {
                    "strategy": "introduce_intermediate_have",
                    "tactic_block": "have h_one : True := by\n  exact h",
                    "uses_facts": ["h"],
                    "uses_decls": [],
                    "priority": 0.7,
                }
            ],
            [],
        ]
    )
    runner = FakeLeanRunner(progress_token="h_one")

    trace = run_llm_guided_search(
        proof_context=_context(),
        lean_runner=runner,
        llm_client=llm,
        cfg=_cfg(max_nodes=2, max_llm_calls=2),
    )

    assert trace.accepted_actions
    assert llm.calls == 2
    assert '"active_goals": "unsolved goals"' in llm.prompts[1]
    assert "h : True" in llm.prompts[1]
    assert "h_one : True" in llm.prompts[1]


def test_search_controller_rejects_invalid_probe_action() -> None:
    llm = FakeLLM(
        [
            {
                "strategy": "close_goal",
                "tactic_block": "exact missing_h",
                "uses_facts": [],
                "uses_decls": [],
                "priority": 0.5,
            }
        ]
    )
    runner = FakeLeanRunner()

    trace = run_llm_guided_search(
        proof_context=_context(),
        lean_runner=runner,
        llm_client=llm,
        cfg=_cfg(max_nodes=2, max_llm_calls=1),
    )

    assert trace.rejected_actions
    assert trace.rejected_actions[0]["status"] == "invalid"
    assert trace.rejected_actions[0]["probe_full_proof_body"] == "exact missing_h"
    assert trace.rejected_actions[0]["error_line"] == 12
    assert trace.rejected_actions[0]["error_col"] == 6
    assert trace.accepted_actions == []


def test_search_controller_closed_action_triggers_final_replay() -> None:
    llm = FakeLLM(
        [
            {
                "strategy": "close_goal",
                "tactic_block": "exact close_goal",
                "uses_facts": [],
                "uses_decls": [],
                "priority": 1.0,
            }
        ]
    )
    runner = FakeLeanRunner(closed_token="close_goal")

    trace = run_llm_guided_search(
        proof_context=_context(),
        lean_runner=runner,
        llm_client=llm,
        cfg=_cfg(max_nodes=2, max_llm_calls=1),
    )

    assert trace.search_status == "success"
    assert trace.final_proof_body == "exact close_goal"
    assert runner.verify_calls == ["exact close_goal"]


def test_search_controller_respects_max_nodes() -> None:
    llm = FakeLLM(
        [
            {
                "strategy": "introduce_intermediate_have",
                "tactic_block": "have progress_action : True := by\n  exact h",
                "uses_facts": ["h"],
                "uses_decls": [],
                "priority": 0.7,
            }
        ]
    )

    trace = run_llm_guided_search(
        proof_context=_context(),
        lean_runner=FakeLeanRunner(progress_token="progress_action"),
        llm_client=llm,
        cfg=_cfg(max_nodes=1, max_llm_calls=1),
    )

    assert trace.nodes_expanded <= 1
    assert trace.failure_reason == "max_nodes_exhausted"


def test_search_controller_respects_max_llm_calls() -> None:
    llm = FakeLLM([])

    trace = run_llm_guided_search(
        proof_context=_context(),
        lean_runner=FakeLeanRunner(),
        llm_client=llm,
        cfg=_cfg(max_nodes=5, max_llm_calls=0),
    )

    assert llm.calls == 0
    assert trace.llm_calls == 0
    assert trace.failure_reason == "max_llm_calls_exhausted"


def test_search_controller_augments_typed_physical_positive_assumption_before_side_condition() -> None:
    cfg = _cfg(max_nodes=4, max_llm_calls=0)
    cfg.proof.llm_guided_search.deterministic_side_conditions_first = True
    context = ProofContext(
        sample_id="s1",
        candidate_id="c1",
        theorem_decl="theorem c1 (m : Mass) (F : Force) (a : Acceleration) : a.val = F.val / m.val",
        lean_header="import MechLib",
        target_formula="a.val = F.val / m.val",
        local_binders=["m : Mass", "F : Force", "a : Acceleration"],
        typed_binders=[{"symbol": "m", "lean_type": "Mass"}],
        allowed_local_facts=[],
        local_hypotheses=[],
    )
    runner = FakeLeanRunner(progress_token="hden")

    trace = run_llm_guided_search(
        proof_context=context,
        lean_runner=runner,
        llm_client=FakeLLM([]),
        cfg=cfg,
    )

    assert trace.physical_assumption_augmented is True
    assert trace.added_physical_assumptions[0]["name"] == "h_m_pos"
    assert "(h_m_pos : 0 < m.val)" in (trace.augmented_theorem_decl or "")
    assert runner.compile_calls and "(h_m_pos : 0 < m.val)" in runner.compile_calls[0]
    assert not any(row["strategy"] == "augment_physical_positive_hypotheses" for row in trace.accepted_actions)
    assert len(trace.augmentation_checks) == 1
    assert trace.augmentation_checks[0]["strategy"] == "augment_physical_positive_hypotheses"
    assert trace.augmentation_checks[0]["status"] == "context_augmented"
    assert trace.augmentation_checks[0]["accepted"] is True
    assert trace.augmentation_checks[0]["phase"] == "pre_search"
    assert trace.augmentation_checks[0]["search_node_action"] is False
    assert any("hden" in probe for probe in runner.probes)


def test_search_controller_uses_configured_probe_timeout() -> None:
    llm = FakeLLM(
        [
            {
                "strategy": "introduce_intermediate_have",
                "tactic_block": "have progress_action : True := by\n  exact h",
                "uses_facts": ["h"],
                "uses_decls": [],
            }
        ]
    )
    runner = FakeLeanRunner(progress_token="progress_action")
    cfg = _cfg(max_nodes=2, max_llm_calls=1)
    cfg.lean.timeout_s = 240
    cfg.proof.llm_guided_search.probe_timeout_s = 120

    run_llm_guided_search(
        proof_context=_context(),
        lean_runner=runner,
        llm_client=llm,
        cfg=cfg,
    )

    assert runner.timeouts == [120]


def test_search_controller_stops_after_max_probe_checks() -> None:
    llm = FakeLLM(
        [
            {
                "strategy": "introduce_intermediate_have",
                "tactic_block": "have progress_action : True := by\n  exact h",
                "uses_facts": ["h"],
                "uses_decls": [],
            },
            {
                "strategy": "introduce_intermediate_have",
                "tactic_block": "have progress_action_2 : True := by\n  exact h",
                "uses_facts": ["h"],
                "uses_decls": [],
            },
        ]
    )
    cfg = _cfg(max_nodes=4, max_llm_calls=1)
    cfg.proof.llm_guided_search.max_probe_checks = 1

    trace = run_llm_guided_search(
        proof_context=_context(),
        lean_runner=FakeLeanRunner(progress_token="progress_action"),
        llm_client=llm,
        cfg=cfg,
    )

    assert trace.probe_checks == 1
    assert trace.failure_reason == "max_probe_checks_exhausted"


def test_search_controller_rejects_duplicate_probe_prefix_without_second_lean_call() -> None:
    llm = FakeLLM(
        [
            {
                "action_id": "p1",
                "strategy": "introduce_intermediate_have",
                "tactic_block": "have progress_action : True := by\n  exact h",
                "uses_facts": ["h"],
                "uses_decls": [],
            },
            {
                "action_id": "p2",
                "strategy": "introduce_intermediate_have",
                "tactic_block": "have progress_action : True := by\n  exact h",
                "uses_facts": ["h"],
                "uses_decls": [],
            },
        ]
    )
    runner = FakeLeanRunner(progress_token="progress_action")

    trace = run_llm_guided_search(
        proof_context=_context(),
        lean_runner=runner,
        llm_client=llm,
        cfg=_cfg(max_nodes=2, max_llm_calls=1),
    )

    assert len(runner.probes) == 1
    assert any(row["error_type"] == "duplicate_probe_prefix" for row in trace.rejected_actions)


def test_search_controller_rejects_branching_constructor_in_linear_prefix_without_probe() -> None:
    llm = FakeLLM(
        [
            {
                "action_id": "split",
                "strategy": "split_conjunction",
                "tactic_block": "constructor",
                "uses_facts": [],
                "uses_decls": [],
            }
        ]
    )
    runner = FakeLeanRunner()

    trace = run_llm_guided_search(
        proof_context=_context(),
        lean_runner=runner,
        llm_client=llm,
        cfg=_cfg(max_nodes=2, max_llm_calls=1),
    )

    assert runner.probes == []
    assert trace.rejected_actions[0]["error_type"] == "branching_constructor_disallowed_linear_prefix"


def test_search_controller_allows_constructor_inside_local_have_block() -> None:
    llm = FakeLLM(
        [
            {
                "action_id": "local_pair",
                "strategy": "introduce_intermediate_have",
                "tactic_block": "have h_pair : True ∧ True := by\n  constructor\n  · exact h\n  · exact h",
                "uses_facts": ["h"],
                "uses_decls": [],
            }
        ]
    )
    runner = FakeLeanRunner(progress_token="h_pair")

    trace = run_llm_guided_search(
        proof_context=_context(),
        lean_runner=runner,
        llm_client=llm,
        cfg=_cfg(max_nodes=2, max_llm_calls=1),
    )

    assert runner.probes
    assert trace.accepted_actions[0]["strategy"] == "introduce_intermediate_have"
    assert trace.accepted_actions[0]["new_local_facts"] == ["h_pair"]


def test_search_controller_repairs_function_valued_quantity_val_application_before_probe() -> None:
    context = ProofContext(
        sample_id="s_function_val",
        candidate_id="c_function_val",
        theorem_decl="theorem c_function_val (m : Real -> Mass) (t_eval90 : Time) (h : True) : True",
        lean_header="import MechLib",
        target_formula="True",
        local_binders=["m : Real -> Mass", "t_eval90 : Time", "h : True"],
        allowed_local_facts=["h"],
        local_hypotheses=["h"],
    )
    llm = FakeLLM(
        [
            {
                "strategy": "introduce_intermediate_have",
                "tactic_block": "have h_mass90 : m.val t_eval90 = 100 := by\n  exact h",
                "uses_facts": ["h"],
                "uses_decls": [],
            }
        ]
    )
    runner = FakeLeanRunner(progress_token="(m t_eval90.val).val = 100")

    trace = run_llm_guided_search(
        proof_context=context,
        lean_runner=runner,
        llm_client=llm,
        cfg=_cfg(max_nodes=2, max_llm_calls=1),
    )

    assert "(m t_eval90.val).val = 100" in runner.probes[0]
    assert trace.accepted_actions[0]["function_value_application_repaired"] is True
    assert trace.accepted_actions[0]["new_local_facts"] == ["h_mass90"]


def test_search_controller_rejects_repeated_failed_action_shape_without_second_probe() -> None:
    llm = FakeLLM(
        [
            {
                "action_id": "p1",
                "strategy": "introduce_intermediate_have",
                "tactic_block": "have h_one : True := by\n  exact missing_h",
                "uses_facts": [],
                "uses_decls": [],
            },
            {
                "action_id": "p2",
                "strategy": "introduce_intermediate_have",
                "tactic_block": "have h_two : True := by\n  exact missing_h",
                "uses_facts": [],
                "uses_decls": [],
            },
        ]
    )
    runner = FakeLeanRunner(progress_token="not_present")

    trace = run_llm_guided_search(
        proof_context=_context(),
        lean_runner=runner,
        llm_client=llm,
        cfg=_cfg(max_nodes=2, max_llm_calls=1),
    )

    assert len(runner.probes) == 1
    assert any(row["error_type"] == "repeated_failed_action_shape" for row in trace.rejected_actions)


def test_search_controller_rejects_no_progress_with_unchanged_goals() -> None:
    llm = FakeLLM(
        [
            {
                "strategy": "algebra",
                "tactic_block": "simp",
                "uses_facts": [],
                "uses_decls": [],
            }
        ]
    )
    runner = FakeLeanRunner(progress_token="simp")

    trace = run_llm_guided_search(
        proof_context=_context(),
        lean_runner=runner,
        llm_client=llm,
        cfg=_cfg(max_nodes=4, max_llm_calls=2),
    )

    assert len(runner.probes) == 2
    assert any(row["error_type"] == "no_meaningful_progress" for row in trace.rejected_actions)


def test_search_controller_rejects_duplicate_claim_with_different_fact_name() -> None:
    llm = SequentialFakeLLM(
        [
            [
                {
                    "strategy": "introduce_intermediate_have",
                    "tactic_block": "have h_one : True := by\n  exact h",
                    "uses_facts": ["h"],
                    "uses_decls": [],
                }
            ],
            [
                {
                    "strategy": "introduce_intermediate_have",
                    "tactic_block": "have h_two : True := by\n  exact h",
                    "uses_facts": ["h"],
                    "uses_decls": [],
                }
            ],
        ]
    )
    runner = FakeLeanRunner(progress_token="have h_")

    trace = run_llm_guided_search(
        proof_context=_context(),
        lean_runner=runner,
        llm_client=llm,
        cfg=_cfg(max_nodes=4, max_llm_calls=2),
    )

    assert len(trace.accepted_actions) == 1
    assert trace.accepted_actions[0]["new_local_fact_claims"] == ["True"]
    assert any(row["error_type"] == "no_meaningful_progress" for row in trace.rejected_actions)


def test_search_controller_does_not_repeat_same_side_condition_denominator() -> None:
    cfg = _cfg(max_nodes=4, max_llm_calls=0)
    cfg.proof.llm_guided_search.deterministic_side_conditions_first = True
    context = ProofContext(
        sample_id="s1",
        candidate_id="c1",
        theorem_decl="theorem c1 (a y : Real) (h_a_pos : 0 < a.val) : y = y / (2 * a.val)",
        lean_header="import Mathlib",
        target_formula="y = y / (2 * a.val)",
        local_binders=["h_a_pos : 0 < a.val"],
        allowed_local_facts=["h_a_pos"],
        local_hypotheses=["h_a_pos"],
    )
    runner = FakeLeanRunner(progress_token="hden")

    trace = run_llm_guided_search(
        proof_context=context,
        lean_runner=runner,
        llm_client=FakeLLM([]),
        cfg=cfg,
    )

    side_condition_actions = [
        row for row in trace.accepted_actions if row["strategy"] == "prove_side_condition"
    ]
    assert len(side_condition_actions) == 1
    assert side_condition_actions[0]["side_condition_denominator"] == "2 * a.val"
    assert len(runner.probes) == 1


def test_search_controller_closes_conjunction_target_from_matching_component_facts() -> None:
    context = ProofContext(
        sample_id="s_components",
        candidate_id="c_components",
        theorem_decl="theorem c_components (x y : Real) (hx : x = x) (hy : y = y) : x = x ∧ y = y",
        lean_header="import Mathlib",
        target_formula="x = x ∧ y = y",
        local_binders=["x y : Real", "hx : x = x", "hy : y = y"],
        allowed_local_facts=["hx", "hy"],
        local_hypotheses=["hx", "hy"],
    )

    trace = run_llm_guided_search(
        proof_context=context,
        lean_runner=FakeLeanRunner(closed_token="exact ⟨hx, hy⟩", progress_token="not_present"),
        llm_client=FakeLLM([]),
        cfg=_cfg(max_nodes=2, max_llm_calls=0),
    )

    assert trace.search_status == "success"
    assert trace.accepted_actions[0]["strategy"] == "close_target_components"
    assert trace.final_proof_body == "exact ⟨hx, hy⟩"


def test_search_controller_defers_llm_when_deterministic_side_condition_is_available() -> None:
    cfg = _cfg(max_nodes=1, max_llm_calls=1)
    cfg.proof.llm_guided_search.deterministic_side_conditions_first = True
    context = ProofContext(
        sample_id="s1",
        candidate_id="c1",
        theorem_decl="theorem c1 (a y : Real) (h_a_pos : 0 < a.val) : y = y / (2 * a.val)",
        lean_header="import Mathlib",
        target_formula="y = y / (2 * a.val)",
        local_binders=["h_a_pos : 0 < a.val"],
        allowed_local_facts=["h_a_pos"],
        local_hypotheses=["h_a_pos"],
    )
    llm = FakeLLM(
        [
            {
                "strategy": "close_goal",
                "tactic_block": "exact close_goal",
                "uses_facts": [],
                "uses_decls": [],
            }
        ]
    )

    trace = run_llm_guided_search(
        proof_context=context,
        lean_runner=FakeLeanRunner(progress_token="hden"),
        llm_client=llm,
        cfg=cfg,
    )

    assert llm.calls == 0
    assert trace.llm_calls == 0
    assert any(row["strategy"] == "prove_side_condition" for row in trace.accepted_actions)


def test_search_controller_marks_obligation_covered_by_llm_action() -> None:
    context = _context()
    context.allowed_verified_decls = ["MechLib.Newton.second_law"]
    context.obligation_replay_items = [
        ProofObligationReplayItem(
            obligation_id="obl_newton",
            kind="law_to_equation",
            from_hypothesis=None,
            must_use="MechLib.Newton.second_law",
            formal_claim="True",
            produced_fact_name="h_newton",
        )
    ]
    llm = FakeLLM(
        [
            {
                "strategy": "introduce_intermediate_have",
                "tactic_block": "have h_newton : True := by\n  exact h",
                "uses_facts": ["h"],
                "uses_decls": ["MechLib.Newton.second_law"],
            }
        ]
    )

    trace = run_llm_guided_search(
        proof_context=context,
        lean_runner=FakeLeanRunner(progress_token="h_newton"),
        llm_client=llm,
        cfg=_cfg(max_nodes=2, max_llm_calls=1),
    )

    assert trace.accepted_actions[0]["covered_obligations"] == ["obl_newton"]
    assert trace.accepted_actions[0]["remaining_obligations_after"] == []


def test_search_controller_does_not_credit_rejected_action_facts_or_obligations() -> None:
    context = _context()
    context.allowed_verified_decls = ["MechLib.Newton.second_law"]
    context.obligation_replay_items = [
        ProofObligationReplayItem(
            obligation_id="obl_newton",
            kind="law_to_equation",
            from_hypothesis=None,
            must_use="MechLib.Newton.second_law",
            formal_claim="True",
            produced_fact_name="h_newton",
        )
    ]
    llm = FakeLLM(
        [
            {
                "strategy": "introduce_intermediate_have",
                "tactic_block": "have h_newton : True := by\n  exact h",
                "uses_facts": ["h"],
                "uses_decls": ["MechLib.Newton.second_law"],
            }
        ]
    )

    trace = run_llm_guided_search(
        proof_context=context,
        lean_runner=FakeLeanRunner(progress_token="not_present"),
        llm_client=llm,
        cfg=_cfg(max_nodes=2, max_llm_calls=1),
    )

    rejected = trace.rejected_actions[0]
    assert rejected["accepted"] is False
    assert rejected["proposed_local_facts"] == ["h_newton"]
    assert rejected["new_local_facts"] == []
    assert rejected["covered_obligations"] == []
    assert rejected["remaining_obligations_after"] == ["obl_newton"]


class IncompleteHaveLeanRunner(FakeLeanRunner):
    def probe_proof_prefix(self, *, lean_header, theorem_decl, proof_prefix, timeout_s=None):
        _ = (lean_header, theorem_decl, timeout_s)
        self.probes.append(proof_prefix)
        return ProofActionCheckResult(
            action_id="probe",
            strategy="probe_proof_prefix",
            tactic_block=proof_prefix,
            status="progress",
            error_type="unsolved_goals",
            error_message="unsolved goals",
            stderr_excerpt=(
                "/tmp/probe.lean:12:20: error: unsolved goals\n"
                "h : True\n"
                "⊢ False\n"
                "/tmp/probe.lean:10:39: error: unsolved goals\n"
                "h h_bad : True\n"
                "⊢ True"
            ),
            goals_excerpt=(
                "unsolved goals\n"
                "h : True\n"
                "⊢ False\n"
                "unsolved goals\n"
                "h h_bad : True\n"
                "⊢ True"
            ),
            unsolved_goal_count=2,
        )


def test_search_controller_rejects_unfinished_have_as_fact() -> None:
    llm = FakeLLM(
        [
            {
                "strategy": "introduce_intermediate_have",
                "tactic_block": "have h_bad : False := by\n  simp_all",
                "uses_facts": ["h"],
                "uses_decls": [],
            }
        ]
    )

    trace = run_llm_guided_search(
        proof_context=_context(),
        lean_runner=IncompleteHaveLeanRunner(),
        llm_client=llm,
        cfg=_cfg(max_nodes=2, max_llm_calls=1),
    )

    assert trace.accepted_actions == []
    rejected = trace.rejected_actions[0]
    assert rejected["accepted"] is False
    assert rejected["error_type"] == "have_subgoal_unresolved"
    assert rejected["proposed_local_facts"] == ["h_bad"]
    assert rejected["new_local_facts"] == []


def test_search_controller_does_not_create_fact_from_error_category_probe() -> None:
    llm = FakeLLM(
        [
            {
                "strategy": "introduce_intermediate_have",
                "tactic_block": "have h_bad : True := by\n  exact missing_h",
                "uses_facts": [],
                "uses_decls": [],
            }
        ]
    )
    runner = ErrorCategoryWithGoalsLeanRunner()

    trace = run_llm_guided_search(
        proof_context=_context(),
        lean_runner=runner,
        llm_client=llm,
        cfg=_cfg(max_nodes=2, max_llm_calls=1),
    )

    assert trace.accepted_actions == []
    assert len(trace.rejected_actions) == 1
    rejected = trace.rejected_actions[0]
    assert rejected["status"] == "invalid"
    assert rejected["error_type"] == "symbol_hallucination"
    assert rejected["proposed_local_facts"] == ["h_bad"]
    assert rejected["new_local_facts"] == []
    assert rejected["new_local_fact_claims"] == []


def test_search_controller_blocks_failed_preflight_and_runs_target_fact_plan() -> None:
    cfg = _cfg(max_nodes=4, max_llm_calls=1)
    cfg.proof.llm_guided_search.deterministic_obligation_replay_first = True
    context = _context()
    context.allowed_verified_decls = ["MechLib.Newton.second_law", "MechLib.Newton.alternative_form"]
    context.obligation_replay_items = [
        ProofObligationReplayItem(
            obligation_id="obl_newton",
            kind="law_to_equation",
            from_hypothesis="h",
            must_use="MechLib.Newton.second_law",
            formal_claim="True",
            produced_fact_name="h_newton",
        )
    ]
    llm = PayloadFakeLLM(
        {
            "fact_plan": [
                {
                    "name": "h_done",
                    "claim": "True",
                    "from": ["h"],
                    "tactic": "exact h",
                }
            ],
            "close": "exact h_done",
        }
    )

    trace = run_llm_guided_search(
        proof_context=context,
        lean_runner=FakeLeanRunner(closed_token="exact h_done", progress_token="h_done"),
        llm_client=llm,
        cfg=cfg,
    )

    assert llm.calls == 1
    assert trace.llm_calls == 1
    assert trace.search_status == "success"
    assert trace.search_mode == "target_proof_from_available_facts"
    assert trace.blocked_obligations
    assert trace.blocked_obligations[0]["obligation_id"] == "obl_newton"
    assert trace.blocked_obligations[0]["reason"] == "missing_proof_friendly_extractor"
    assert trace.strategy_prompt_summaries[0]["search_mode"] == "target_proof_from_available_facts"
    assert trace.strategy_prompt_summaries[0]["remaining_obligations"] == []
    assert trace.strategy_prompt_summaries[0]["blocked_obligations"][0]["reason"] == "missing_proof_friendly_extractor"
    assert trace.strategy_prompt_summaries[0]["allowed_decls"] == []
    assert trace.strategy_prompt_summaries[0]["decl_candidate_mode"] is False
    assert "MechLib.Newton.alternative_form" not in llm.prompts[0]
    assert '"remaining_obligations": []' in llm.prompts[0]
    assert '"search_mode": "target_proof_from_available_facts"' in llm.prompts[0]
    assert "blocked_obligations" in llm.prompts[0]
    assert [row["strategy"] for row in trace.accepted_actions] == [
        "target_fact_plan_have",
        "target_fact_plan_close",
    ]
    assert trace.rejected_actions[0]["error_type"] == "symbol_hallucination"


def test_search_controller_sequences_target_fact_plan_without_extra_llm_calls() -> None:
    cfg = _cfg(max_nodes=4, max_llm_calls=1)
    context = _context()
    llm = PayloadFakeLLM(
        {
            "fact_plan": [
                {
                    "name": "h_one",
                    "claim": "True",
                    "from": ["h"],
                    "tactic": "exact h",
                },
                {
                    "name": "h_two",
                    "claim": "True = True",
                    "from": ["h_one"],
                    "tactic": " exact rfl",
                },
            ],
            "close": "exact h_two",
        }
    )

    trace = run_llm_guided_search(
        proof_context=context,
        lean_runner=FakeLeanRunner(closed_token="exact h_two", progress_token="h_"),
        llm_client=llm,
        cfg=cfg,
    )

    assert llm.calls == 1
    assert trace.search_status == "success"
    assert [row["strategy"] for row in trace.accepted_actions] == [
        "target_fact_plan_have",
        "target_fact_plan_have",
        "target_fact_plan_close",
    ]
    assert "h_one" in trace.accepted_actions[1]["uses_facts"]
    assert "\n   exact rfl" not in trace.accepted_actions[1]["tactic_block"]


def test_search_controller_accepts_fact_plan_item_with_full_have_tactic() -> None:
    cfg = _cfg(max_nodes=3, max_llm_calls=1)
    llm = PayloadFakeLLM(
        {
            "fact_plan": [
                {
                    "name": "h_one",
                    "claim": "True",
                    "from": ["h"],
                    "tactic": "have h_one : True := by\nexact h",
                }
            ],
            "close": "exact h_one",
        }
    )

    trace = run_llm_guided_search(
        proof_context=_context(),
        lean_runner=FakeLeanRunner(closed_token="exact h_one", progress_token="h_one"),
        llm_client=llm,
        cfg=cfg,
    )

    assert trace.search_status == "success"
    assert trace.accepted_actions[0]["tactic_block"] == "have h_one : True := by\n  exact h"


def test_search_controller_splits_overpacked_fact_plan_have_blocks() -> None:
    cfg = _cfg(max_nodes=6, max_llm_calls=1)
    llm = PayloadFakeLLM(
        {
            "fact_plan": [
                {
                    "name": "h_one",
                    "claim": "True",
                    "from": ["h"],
                    "tactic": "have h_one : True := by\nexact h\nhave h_two : True = True := by\nexact rfl",
                }
            ],
            "close": "exact h_two",
        }
    )

    trace = run_llm_guided_search(
        proof_context=_context(),
        lean_runner=FakeLeanRunner(closed_token="exact h_two", progress_token="have h_one"),
        llm_client=llm,
        cfg=cfg,
    )

    assert trace.search_status == "success"
    assert [row["action_id"] for row in trace.accepted_actions] == [
        "llm_plan_1_1",
        "llm_plan_1_1_split_2",
        "llm_plan_1_close",
    ]
    assert trace.accepted_actions[1]["strategy"] == "target_fact_plan_have_split_have"
    assert trace.accepted_actions[1]["tactic_block"] == "have h_two : True = True := by\n  exact rfl"


def test_search_controller_repairs_fact_plan_tactic_no_goals_without_dropping_prefix() -> None:
    cfg = _cfg(max_nodes=8, max_llm_calls=1)
    llm = SequentialPayloadFakeLLM(
        [
            {
                "fact_plan": [
                    {
                        "name": "h_one",
                        "claim": "True",
                        "from": ["h"],
                        "tactic": "exact h",
                    },
                    {
                        "name": "h_final",
                        "claim": "True",
                        "from": ["h_one"],
                        "tactic": "exact h_one; simp; ring_nf",
                    },
                ],
                "close": "exact h_final",
            },
        ]
    )
    runner = NoGoalsRepairLeanRunner()

    trace = run_llm_guided_search(
        proof_context=_context(),
        lean_runner=runner,
        llm_client=llm,
        cfg=cfg,
    )

    assert llm.calls == 1
    assert trace.search_status == "success"
    assert [row["strategy"] for row in trace.accepted_actions] == [
        "target_fact_plan_have",
        "target_fact_plan_have_repair_no_goals",
        "target_fact_plan_close",
    ]
    repair = trace.accepted_actions[1]
    assert repair["repair_of"] == "llm_plan_1_2"
    assert repair["repair_replanned_from_prefix"] is True
    assert repair["tactic_block"] == "have h_final : True := by\n  exact h_one"
    assert repair["new_local_facts"] == ["h_final"]
    assert trace.accepted_actions[2]["action_id"] == "llm_plan_1_close"
    assert trace.accepted_actions[2]["tactic_block"] == "exact h_final"
    assert "have h_one : True := by\n  exact h" in trace.final_proof_body
    assert "have h_final : True := by\n  exact h_one" in trace.final_proof_body
    original_failure = next(row for row in trace.rejected_actions if row["action_id"] == "llm_plan_1_2")
    assert original_failure["repair_attempted"] is True
    assert original_failure["repair_accepted_action_id"] == "llm_plan_1_2_repair_no_goals_1"
    rejected_repair = next(
        row for row in trace.rejected_actions if row["action_id"] == "llm_plan_1_2_repair_no_goals_2"
    )
    assert rejected_repair["error_type"] == "tactic_no_goals"


def test_search_controller_claim_level_repair_uses_error_and_replans_from_prefix() -> None:
    cfg = _cfg(max_nodes=8, max_llm_calls=3)
    llm = SequentialPayloadFakeLLM(
        [
            {
                "fact_plan": [
                    {
                        "name": "h_one",
                        "claim": "True",
                        "from": ["h"],
                        "tactic": "exact h",
                    },
                    {
                        "name": "h_final",
                        "claim": "True",
                        "from": ["h_one"],
                        "tactic": "exact bad_fact",
                    },
                ],
                "close": "exact h_final",
            },
            {
                "tactic_block": "have h_final : True := by\nexact h_one",
                "uses_facts": ["h_one"],
                "uses_decls": [],
            },
            {
                "proposals": [
                    {
                        "strategy": "target_fact_plan_close",
                        "tactic_block": "exact h_final",
                        "uses_facts": ["h_final"],
                    }
                ]
            },
        ]
    )
    runner = ClaimRepairLeanRunner()

    trace = run_llm_guided_search(
        proof_context=_context(),
        lean_runner=runner,
        llm_client=llm,
        cfg=cfg,
    )

    assert llm.calls == 3
    assert trace.search_status == "success"
    assert [row["strategy"] for row in trace.accepted_actions] == [
        "target_fact_plan_have",
        "target_fact_plan_have_claim_repair",
        "target_fact_plan_close",
    ]
    repair = trace.accepted_actions[1]
    assert repair["repair_of"] == "llm_plan_1_2"
    assert repair["repair_kind"] == "claim_level_llm_repair"
    assert repair["repair_replanned_from_prefix"] is True
    assert repair["tactic_block"] == "have h_final : True := by\n  exact h_one"
    assert "have h_final : True := by\n  have h_final" not in trace.final_proof_body
    assert "have h_one : True := by\n  exact h" in trace.final_proof_body
    assert "have h_final : True := by\n  exact h_one" in trace.final_proof_body
    original_failure = next(row for row in trace.rejected_actions if row["action_id"] == "llm_plan_1_2")
    assert original_failure["claim_repair_attempted"] is True
    assert original_failure["claim_repair_accepted_action_id"] == "llm_plan_1_2_claim_repair_1"
    assert "Type mismatch" in llm.prompts[1]
    assert "repair_current_fact_plan_claim_only" in llm.prompts[1]
    assert "failed_tactic_block" in llm.prompts[1]
    assert any(row.get("prompt_type") == "claim_level_repair" for row in trace.strategy_prompt_summaries)


def test_search_controller_rejects_mechlib_decl_in_target_mode() -> None:
    cfg = _cfg(max_nodes=1, max_llm_calls=1)
    context = _context()
    context.allowed_verified_decls = ["MechLib.Newton.second_law"]
    llm = FakeLLM(
        [
            {
                "strategy": "close_goal",
                "tactic_block": "exact MechLib.Newton.second_law",
                "uses_facts": ["h"],
                "uses_decls": ["MechLib.Newton.second_law"],
            }
        ]
    )

    trace = run_llm_guided_search(
        proof_context=context,
        lean_runner=FakeLeanRunner(progress_token="not_present"),
        llm_client=llm,
        cfg=cfg,
    )

    assert llm.calls == 1
    assert trace.search_mode == "target_proof_from_available_facts"
    assert trace.rejected_actions[0]["error_type"] == "action_guard_failed"
    assert "unauthorized_mechlib_decl" in trace.rejected_actions[0]["error_message"]


def test_search_controller_calls_llm_after_target_side_condition_probe_fails() -> None:
    cfg = _cfg(max_nodes=4, max_llm_calls=1)
    cfg.proof.llm_guided_search.deterministic_side_conditions_first = True
    context = _context()
    context.target_formula = "x.val / (m1.val + m2.val) = x.val"
    context.allowed_local_facts = [
        "h : True",
        "h_m1_pos : 0 < m1.val",
        "h_m2_pos : 0 < m2.val",
    ]
    context.local_hypotheses = ["h", "h_m1_pos", "h_m2_pos"]
    llm = FakeLLM(
        [
            {
                "strategy": "close_goal",
                "tactic_block": "exact h",
                "uses_facts": ["h"],
                "uses_decls": [],
            }
        ]
    )

    trace = run_llm_guided_search(
        proof_context=context,
        lean_runner=FakeLeanRunner(closed_token="exact h", progress_token="not_present"),
        llm_client=llm,
        cfg=cfg,
    )

    assert llm.calls == 1
    assert trace.search_status == "success"
    assert trace.search_mode == "target_proof_from_available_facts"
    assert trace.rejected_actions[0]["strategy"] == "prove_side_condition"
    assert trace.strategy_prompt_summaries[0]["remaining_obligations"] == []
    assert trace.strategy_prompt_summaries[0]["allowed_decls"] == []


def test_search_controller_does_not_augment_non_physical_missing_side_condition() -> None:
    cfg = _cfg(max_nodes=2, max_llm_calls=0)
    cfg.proof.llm_guided_search.deterministic_side_conditions_first = True
    context = ProofContext(
        sample_id="s1",
        candidate_id="c1",
        theorem_decl="theorem c1 (x : Real) : x = x / x.val",
        lean_header="import Mathlib",
        target_formula="x = x / x.val",
        local_binders=["x : Real"],
    )

    trace = run_llm_guided_search(
        proof_context=context,
        lean_runner=FakeLeanRunner(progress_token="hden"),
        llm_client=FakeLLM([]),
        cfg=cfg,
    )

    assert trace.physical_assumption_augmented is False
    assert trace.accepted_actions == []
    assert trace.rejected_actions and trace.rejected_actions[0]["strategy"] == "missing_side_condition"
    assert len(trace.augmentation_checks) == 1
    assert trace.augmentation_checks[0]["strategy"] == "augment_physical_positive_hypotheses"
    assert trace.augmentation_checks[0]["accepted"] is False
    assert trace.augmentation_checks[0]["error_type"] == "missing_term_not_typed_physical_quantity"
    assert trace.augmentation_checks[0]["search_node_action"] is False
