from __future__ import annotations

from mech_pipeline.modules.e_proof_context import build_proof_context
from mech_pipeline.types import (
    ControlledSketchStep,
    EvidenceBinding,
    HypothesisProvenance,
    TheoremSkeletonCandidate,
)


def _candidate() -> TheoremSkeletonCandidate:
    binding_ok = EvidenceBinding(
        binding_id="b1",
        model_instance_id="mi1",
        planning_schema="law.dynamics.newton_second_law",
        verified_decl="MechLib.Dynamics.NewtonLaw.NewtonSecondLaw.to_value_equation",
        decl_statement="theorem to_value_equation ...",
        decl_status="verified",
        trust_level="core",
        callable_by_llm=True,
        required_imports=["import MechLib.Dynamics.NewtonLaw"],
        lean_check_pass=True,
        proof_fact_allowed=True,
        binding_status="ok",
        expected_claim="Fnet.val = m.val * a.val",
    )
    binding_gap = EvidenceBinding(
        binding_id="b2",
        model_instance_id="mi_gap",
        planning_schema="law.schema_only",
        verified_decl="MechLib.SchemaOnly.fake",
        decl_status="schema",
        callable_by_llm=False,
        proof_fact_allowed=False,
        binding_status="gap_schema_only",
        expected_claim="schema-only claim",
    )
    obligation = ControlledSketchStep(
        step_id="sk_mi1",
        kind="law_to_equation",
        claim="Newton second law gives value equation",
        formal_claim="Fnet.val = m.val * a.val",
        source_model_instance="mi1",
        planning_schema="law.dynamics.newton_second_law",
        binding_status="ok",
        proof_fact_allowed=True,
        produces="h_newton_value",
    )
    blocked_obligation = ControlledSketchStep(
        step_id="sk_gap",
        kind="law_to_equation",
        claim="Schema-only law",
        formal_claim="schema-only claim",
        source_model_instance="mi_gap",
        planning_schema="law.schema_only",
        binding_status="gap_schema_only",
        proof_fact_allowed=False,
        produces="h_gap",
    )
    return TheoremSkeletonCandidate(
        sample_id="s1",
        candidate_id="c1",
        lean_header="import MechLib",
        theorem_decl=(
            "theorem c1 (m : Mass) (a : Acceleration) (Fnet : Force) "
            "(glider_law : MechLib.Dynamics.NewtonLaw.NewtonSecondLaw m a Fnet) : "
            "Fnet.val = m.val * a.val"
        ),
        parse_ok=True,
        hypothesis_provenance=[
            HypothesisProvenance(
                name="glider_law",
                lean="MechLib.Dynamics.NewtonLaw.NewtonSecondLaw m a Fnet",
                role="model_instance",
                source_type="verified_decl",
                source_id="mi1",
                allowed_in_hypotheses=True,
                proof_fact_allowed=True,
            )
        ],
        evidence_bindings=[binding_ok, binding_gap],
        proof_obligations=[obligation, blocked_obligation],
        model_predicate_bindings=[
            {
                "name": "glider_law",
                "proposition": "MechLib.Dynamics.NewtonLaw.NewtonSecondLaw m a Fnet",
                "verified_decl": "MechLib.Dynamics.NewtonLaw.NewtonSecondLaw",
                "model_instance_id": "mi1",
            }
        ],
        verified_decls=["MechLib.Dynamics.NewtonLaw.NewtonSecondLaw.to_value_equation"],
        gap_laws=[{"source_model_instance": "mi_gap", "binding_status": "gap_schema_only"}],
        explicit_model_gaps=[{"source_model_instance": "mi_gap", "proof_fact_allowed": False}],
    )


def test_build_proof_context_reads_minimal_skeleton_obligations() -> None:
    context = build_proof_context(
        sample_id="s1",
        problem_ir={"target": {"lean": "Fnet.val = m.val * a.val"}},
        selected_candidate=_candidate(),
        mechlib_context="verified context",
    )
    assert context.skeleton_mode is True
    assert len(context.proof_obligations) == 2
    assert context.target_formula == "Fnet.val = m.val * a.val"
    assert "glider_law" in context.local_hypotheses


def test_build_proof_context_extracts_allowed_verified_decls_without_schema_gaps() -> None:
    context = build_proof_context(
        sample_id="s1",
        problem_ir={},
        selected_candidate=_candidate(),
        mechlib_context=None,
    )
    assert context.allowed_verified_decls == [
        "MechLib.Dynamics.NewtonLaw.NewtonSecondLaw.to_value_equation"
    ]
    assert all("SchemaOnly" not in decl for decl in context.allowed_verified_decls)


def test_build_proof_context_maps_source_model_to_hypothesis_and_extractor() -> None:
    context = build_proof_context(
        sample_id="s1",
        problem_ir={},
        selected_candidate=_candidate(),
        mechlib_context=None,
    )
    assert len(context.obligation_replay_items) == 1
    replay = context.obligation_replay_items[0]
    assert replay.obligation_id == "sk_mi1"
    assert replay.from_hypothesis == "glider_law"
    assert replay.must_use == "MechLib.Dynamics.NewtonLaw.NewtonSecondLaw.to_value_equation"
    assert replay.formal_claim == "Fnet.val = m.val * a.val"
    assert replay.produced_fact_name == "h_newton_value"
    assert replay.replay_status == "pending"


def test_build_proof_context_does_not_expose_pending_obligation_output_as_fact() -> None:
    context = build_proof_context(
        sample_id="s1",
        problem_ir={},
        selected_candidate=_candidate(),
        mechlib_context=None,
    )

    assert "glider_law" in context.allowed_local_facts
    assert "h_newton_value" not in context.allowed_local_facts


def test_build_proof_context_blocks_schema_only_obligation() -> None:
    context = build_proof_context(
        sample_id="s1",
        problem_ir={},
        selected_candidate=_candidate(),
        mechlib_context=None,
    )
    assert len(context.obligation_replay_blocked) == 1
    blocked = context.obligation_replay_blocked[0]
    assert blocked.obligation_id == "sk_gap"
    assert blocked.replay_status == "blocked"
    assert blocked.error in {"missing_verified_extractor_decl", "must_use_not_allowed_verified_decl"}
