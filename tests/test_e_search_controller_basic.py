from __future__ import annotations

import json

from mech_pipeline.config import PipelineConfig
from mech_pipeline.modules.e_search_controller import run_llm_guided_search
from mech_pipeline.types import ProofActionCheckResult, ProofContext, ProofObligationReplayItem


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
    assert any(row["strategy"] == "augment_physical_positive_hypotheses" for row in trace.accepted_actions)
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


def test_search_controller_falls_back_to_llm_after_extractor_preflight_fails() -> None:
    cfg = _cfg(max_nodes=4, max_llm_calls=3)
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
        lean_runner=FakeLeanRunner(progress_token="not_present"),
        llm_client=llm,
        cfg=cfg,
    )

    assert llm.calls == 1
    assert trace.llm_calls == 1
    assert trace.failure_reason == "proof_action_synthesis_failed_after_preflight"
    assert trace.accepted_actions == []
    assert len(trace.rejected_actions) == 2
    assert trace.rejected_actions[0]["error_type"] == "symbol_hallucination"
    assert trace.rejected_actions[1]["error_type"] == "symbol_hallucination"
    assert trace.strategy_prompt_summaries[0]["decl_candidate_mode"] is True
    assert "MechLib.Newton.alternative_form" in trace.strategy_prompt_summaries[0]["allowed_decls"]
    assert '"error": "missing_proof_friendly_extractor"' in llm.prompts[0]


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
    assert any(row["strategy"] == "augment_physical_positive_hypotheses" for row in trace.rejected_actions)
