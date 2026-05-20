from __future__ import annotations

from mech_pipeline.modules.e_proof_context import build_proof_context
from mech_pipeline.types import (
    ControlledSketchStep,
    EvidenceBinding,
    HypothesisProvenance,
    TheoremSkeletonCandidate,
)


NEWTON_EXTRACTOR = "MechLib.Dynamics.NewtonLaw.NewtonSecondLaw.to_value_equation"
NEWTON_EXTRACTOR_STMT = (
    "theorem to_value_equation {m : MechLib.SI.Mass} {a : MechLib.SI.Acceleration} "
    "{F : MechLib.SI.Force} (h : NewtonSecondLaw m a F) : F.val = m.val * a.val"
)
BAD_NEWTON_DECL = "MechLib.Dynamics.Verified.Dynamics.newton_second_law"
BAD_NEWTON_STMT = "theorem newton_second_law (m : Mass) (a : Acceleration) : F_of m a = m * a"
ACCEL_EXTRACTOR = "MechLib.Kinematics.PointMotion.acceleration_value_eq_deriv_of_velocity_value"
ACCEL_EXTRACTOR_STMT = (
    "theorem acceleration_value_eq_deriv_of_velocity_value {v : ScalarVelocityField} "
    "{a : MechLib.Mechanics.Kinematics.ScalarAccelerationField} {f f' : Real -> Real} "
    "(hvf : forall t, (v t).val = f t) (hf : forall t, HasDerivAt f (f' t) t) "
    "(ha : AccelerationDerivativeRelation v a) : forall t, (a t).val = f' t"
)


def _candidate() -> TheoremSkeletonCandidate:
    binding_ok = EvidenceBinding(
        binding_id="b1",
        model_instance_id="mi1",
        planning_schema="law.dynamics.newton_second_law",
        verified_decl=NEWTON_EXTRACTOR,
        decl_statement=NEWTON_EXTRACTOR_STMT,
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
                "verified_decl": NEWTON_EXTRACTOR,
                "model_instance_id": "mi1",
                "decl_statement": NEWTON_EXTRACTOR_STMT,
            }
        ],
        verified_decls=[NEWTON_EXTRACTOR],
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


def test_build_proof_context_target_formula_keeps_forall_binder_type() -> None:
    candidate = _candidate()
    candidate.theorem_decl = (
        "theorem c_forall (hvel : forall t0 : Real, t0 = t0) : "
        "forall t0 : Real, t0 = t0"
    )

    context = build_proof_context(
        sample_id="s_forall",
        problem_ir={},
        selected_candidate=candidate,
        mechlib_context=None,
    )

    assert context.target_formula == "forall t0 : Real, t0 = t0"


def test_build_proof_context_uses_target_spec_when_theorem_target_missing() -> None:
    candidate = _candidate()
    candidate.theorem_decl = "theorem c_without_target"
    candidate.target_spec = {
        "lean_formula": "forall t0 : Real, 0 <= t0 -> t0 <= 4 -> (v t0).val = 6 * t0 - 2"
    }

    context = build_proof_context(
        sample_id="s_forall",
        problem_ir={},
        selected_candidate=candidate,
        mechlib_context=None,
    )

    assert context.target_formula == "forall t0 : Real, 0 <= t0 -> t0 <= 4 -> (v t0).val = 6 * t0 - 2"


def test_build_proof_context_reads_problem_ir_target_dict_without_dict_string() -> None:
    candidate = _candidate()
    candidate.theorem_decl = "theorem c_without_target"
    candidate.target_spec = {}

    context = build_proof_context(
        sample_id="s_problem_target",
        problem_ir={"target": {"lean": "forall t0 : Real, (v t0).val = t0"}},
        selected_candidate=candidate,
        mechlib_context=None,
    )

    assert context.target_formula == "forall t0 : Real, (v t0).val = t0"
    assert "{" not in context.target_formula


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
    assert replay.must_use == NEWTON_EXTRACTOR
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


def test_build_proof_context_exposes_only_real_theorem_hypotheses_as_local_facts() -> None:
    candidate = TheoremSkeletonCandidate(
        sample_id="ch2_q2_like",
        candidate_id="c1",
        lean_header="import MechLib",
        theorem_decl=(
            "theorem c1 "
            "(m : Mass) (Fnet1 Fnet2 N1 Fc1 : Force) (L1 r1 : Length) "
            "(x : Real -> Real) "
            "(def_radial_projection_1 : r1.val = L1.val) "
            "(h_net_force_along_case1 : Fnet1.val = Fc1.val + N1.val) "
            "(h_equil1 : Fnet1.val = 0) : "
            "L1.val = r1.val"
        ),
        parse_ok=True,
        hypothesis_provenance=[
            HypothesisProvenance(
                name="def_radial_projection",
                lean="r.val = L.val",
                role="model_interface",
                source_type="model_ir",
                source_id="projection_relation",
                allowed_in_hypotheses=True,
            ),
            HypothesisProvenance(
                name="h_mi1_net_force_along_case1",
                lean="Fnet1.val = Fc1.val + N1.val",
                role="model_interface",
                source_type="controlled_sketch",
                source_id="mi1",
                allowed_in_hypotheses=True,
            ),
        ],
        model_predicate_bindings=[
            {"name": "h_mi2_normal_reaction", "proposition": "N1.val = m.val"}
        ],
    )

    context = build_proof_context(
        sample_id="ch2_q2_like",
        problem_ir={},
        selected_candidate=candidate,
        mechlib_context=None,
    )

    assert "def_radial_projection_1" in context.allowed_local_facts
    assert "h_net_force_along_case1" in context.allowed_local_facts
    assert "h_equil1" in context.allowed_local_facts
    assert "m" not in context.allowed_local_facts
    assert "Fnet1" not in context.allowed_local_facts
    assert "x" not in context.allowed_local_facts
    assert "def_radial_projection" not in context.allowed_local_facts
    assert "h_mi1_net_force_along_case1" not in context.allowed_local_facts
    assert "h_mi2_normal_reaction" not in context.allowed_local_facts


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


def test_build_proof_context_repairs_bad_obligation_decl_from_model_predicate_binding() -> None:
    candidate = _candidate()
    candidate.proof_obligations[0].verified_decl = BAD_NEWTON_DECL
    candidate.evidence_bindings.insert(
        0,
        EvidenceBinding(
            binding_id="b_bad",
            model_instance_id="mi1",
            planning_schema="law.dynamics.newton_second_law",
            verified_decl=BAD_NEWTON_DECL,
            decl_statement=BAD_NEWTON_STMT,
            decl_status="verified",
            trust_level="core",
            callable_by_llm=True,
            required_imports=[],
            lean_check_pass=True,
            proof_fact_allowed=True,
            binding_status="ok",
            expected_claim="Fnet.val = m.val * a.val",
        ),
    )

    context = build_proof_context(sample_id="s1", problem_ir={}, selected_candidate=candidate, mechlib_context=None)

    assert len(context.obligation_replay_items) == 1
    replay = context.obligation_replay_items[0]
    assert replay.obligation_id == "sk_mi1"
    assert replay.from_hypothesis == "glider_law"
    assert replay.must_use == NEWTON_EXTRACTOR
    assert all(item.must_use != BAD_NEWTON_DECL for item in context.obligation_replay_items)


def test_build_proof_context_blocks_non_extractor_decl_without_must_use() -> None:
    candidate = _candidate()
    candidate.proof_obligations = [
        ControlledSketchStep(
            step_id="sk_bad",
            kind="law_to_equation",
            claim="bad Newton binding",
            formal_claim="Fnet.val = m.val * a.val",
            source_model_instance="mi_bad",
            planning_schema="law.dynamics.newton_second_law",
            verified_decl=BAD_NEWTON_DECL,
            binding_status="ok",
            proof_fact_allowed=True,
            required_hypotheses=["bad_law"],
            produces="h_bad",
        )
    ]
    candidate.evidence_bindings = [
        EvidenceBinding(
            binding_id="b_bad",
            model_instance_id="mi_bad",
            planning_schema="law.dynamics.newton_second_law",
            verified_decl=BAD_NEWTON_DECL,
            decl_statement=BAD_NEWTON_STMT,
            decl_status="verified",
            trust_level="core",
            callable_by_llm=True,
            lean_check_pass=True,
            proof_fact_allowed=True,
            binding_status="ok",
            expected_claim="Fnet.val = m.val * a.val",
        )
    ]
    candidate.model_predicate_bindings = []
    candidate.theorem_decl = (
        "theorem c1 (m : Mass) (a : Acceleration) (Fnet : Force) "
        "(bad_law : MechLib.Dynamics.NewtonLaw.NewtonSecondLaw m a Fnet) : "
        "Fnet.val = m.val * a.val"
    )

    context = build_proof_context(sample_id="s1", problem_ir={}, selected_candidate=candidate, mechlib_context=None)

    assert context.obligation_replay_items == []
    assert len(context.obligation_replay_blocked) == 1
    blocked = context.obligation_replay_blocked[0]
    assert blocked.obligation_id == "sk_bad"
    assert blocked.must_use is None
    assert blocked.error == "non_extractor_decl"


def test_build_proof_context_blocks_bridge_that_needs_additional_premises() -> None:
    binding = EvidenceBinding(
        binding_id="b_accel",
        model_instance_id="mi1",
        planning_schema="law.kinematics.acceleration_derivative",
        verified_decl=ACCEL_EXTRACTOR,
        decl_statement=ACCEL_EXTRACTOR_STMT,
        decl_status="verified",
        trust_level="core",
        callable_by_llm=True,
        lean_check_pass=True,
        proof_fact_allowed=True,
        binding_status="ok",
        expected_claim="AccelerationDerivativeRelation vx ax",
    )
    obligation = ControlledSketchStep(
        step_id="sk_accel",
        kind="law_to_equation",
        claim="acceleration derivative bridge",
        formal_claim="forall t0 : Real, (ax t0).val = 0.5",
        source_model_instance="mi1",
        planning_schema="law.kinematics.acceleration_derivative",
        verified_decl=ACCEL_EXTRACTOR,
        binding_status="ok",
        proof_fact_allowed=True,
        required_hypotheses=["mi1_law"],
        produces="h_ax_formula",
    )
    candidate = TheoremSkeletonCandidate(
        sample_id="s_accel",
        candidate_id="c_accel",
        lean_header="import MechLib",
        theorem_decl=(
            "theorem c_accel (vx : MechLib.Mechanics.Kinematics.ScalarVelocityField) "
            "(ax : MechLib.Mechanics.Kinematics.ScalarAccelerationField) "
            "(mi1_law : MechLib.Kinematics.PointMotion.AccelerationDerivativeRelation vx ax) : "
            "forall t0 : Real, (ax t0).val = 0.5"
        ),
        parse_ok=True,
        evidence_bindings=[binding],
        proof_obligations=[obligation],
        model_predicate_bindings=[
            {
                "name": "mi1_law",
                "proposition": "MechLib.Kinematics.PointMotion.AccelerationDerivativeRelation vx ax",
                "verified_decl": ACCEL_EXTRACTOR,
                "model_instance_id": "mi1",
                "decl_statement": ACCEL_EXTRACTOR_STMT,
            }
        ],
        verified_decls=[ACCEL_EXTRACTOR],
    )

    context = build_proof_context(sample_id="s_accel", problem_ir={}, selected_candidate=candidate, mechlib_context=None)

    assert context.obligation_replay_items == []
    assert len(context.obligation_replay_blocked) == 1
    blocked = context.obligation_replay_blocked[0]
    assert blocked.from_hypothesis == "mi1_law"
    assert blocked.must_use is None
    assert blocked.error == "extractor_requires_additional_premises"
