from __future__ import annotations

import json

from mech_pipeline.types import (
    AlgebraObligation,
    ControlledSketch,
    ControlledSketchStep,
    EvidenceBinding,
    HypothesisProvenance,
    ModelIR,
    ModelInstance,
    ModelInterfaceInstantiation,
    SketchAuditResult,
    StatementCandidate,
    TheoremSkeletonCandidate,
)


def test_model_ir_and_sketch_types_are_json_serializable() -> None:
    provenance = HypothesisProvenance(
        name="h_force",
        lean="F = m * a",
        role="problem_fact",
        source_type="problem_ir",
        source_id="known_quantities.force",
        allowed_in_hypotheses=True,
        notes="Given by the problem text.",
    )
    model_instance = ModelInstance(
        instance_id="mi1",
        kind="newton_second_law_1d",
        natural_language="Apply one-dimensional Newton second law.",
        entities=["block"],
        variables={"F": "net force", "m": "mass", "a": "acceleration"},
        parameters={"axis": "x"},
        coordinate_convention="positive x is the direction of motion",
        planning_schema_id="law.newton.second.1d",
        expected_claim="F = m * a",
        hypothesis_form="h_force : F = m * a",
        interface_instantiations=[
            ModelInterfaceInstantiation(
                instantiation_id="net_force",
                kind="net_force_balance",
                formal_claim="Fnet = F",
                source_model_instance="mi1",
                introduced_variable={"name": "Fnet", "lean_type": "Force"},
                proof_fact_allowed=False,
                binding_status="explicit_model_gap",
            )
        ],
        provenance={"source_type": "problem_ir", "source_id": "physical_laws[0]"},
        confidence=0.92,
    )
    model_ir = ModelIR(
        sample_id="s1",
        objects=["block"],
        variables={"F": {"type": "Real"}, "m": {"type": "Real"}, "a": {"type": "Real"}},
        givens=[provenance],
        coordinate_system={"axis": "x"},
        reference_frame="ground",
        local_definitions=[provenance],
        model_instances=[model_instance],
        interface_instantiations=[
            ModelInterfaceInstantiation(
                instantiation_id="net_force_top",
                kind="net_force_balance",
                formal_claim="Fnet = F",
                source_model_instance="mi1",
                introduced_variable={"name": "Fnet", "lean_type": "Force"},
            )
        ],
        target={"lean": "a = F / m"},
        target_spec={"source": "problem_target"},
        forbidden_as_assumption=["a = F / m"],
        source_problem_ir_hash="sha256-demo",
        raw_response='{"parse_ok": true}',
        parse_ok=True,
    )
    binding = EvidenceBinding(
        binding_id="eb1",
        model_instance_id="mi1",
        planning_schema="law.newton.second.1d",
        verified_decl="MechLib.Dynamics.NewtonSecondLaw.newton_second_law_1d",
        decl_statement="theorem newton_second_law_1d ...",
        decl_status="verified",
        trust_level="core",
        callable_by_llm=True,
        required_imports=["import MechLib"],
        lean_check_pass=True,
        proof_fact_allowed=True,
        binding_status="ok",
        expected_claim="F = m * a",
    )
    step = ControlledSketchStep(
        step_id="sk1",
        kind="law_to_equation",
        claim="F = m * a",
        formal_claim="F = m * a",
        source_model_instance="mi1",
        planning_schema="law.newton.second.1d",
        verified_decl="MechLib.Dynamics.NewtonSecondLaw.newton_second_law_1d",
        proof_fact_allowed=True,
        allowed_solvers=["linarith", "ring"],
        required_hypotheses=["h_force"],
        produces="h_law",
    )
    sketch = ControlledSketch(sample_id="s1", status="ok", proof_steps=[step], parse_ok=True, raw_response="{}")
    sketch.model_interface_instantiations = list(model_ir.interface_instantiations)
    audit = SketchAuditResult(sample_id="s1", audit_pass=True, failure_tags=[], details={"checked": True})

    for payload in (model_ir.to_dict(), binding.to_dict(), sketch.to_dict(), audit.to_dict()):
        json.dumps(payload)


def test_theorem_skeleton_candidate_is_statement_candidate_compatible() -> None:
    provenance = HypothesisProvenance(
        name="h_mass",
        lean="m != 0",
        role="problem_fact",
        source_type="problem_text",
        allowed_in_hypotheses=True,
    )
    binding = EvidenceBinding(
        binding_id="eb1",
        model_instance_id="mi1",
        verified_decl="MechLib.Dynamics.NewtonSecondLaw.newton_second_law_1d",
        decl_status="verified",
        callable_by_llm=True,
        required_imports=["import MechLib"],
        lean_check_pass=True,
        proof_fact_allowed=True,
        binding_status="ok",
    )
    obligation = ControlledSketchStep(
        step_id="sk1",
        kind="law_to_equation",
        claim="F = m * a",
        formal_claim="F = m * a",
        verified_decl="MechLib.Dynamics.NewtonSecondLaw.newton_second_law_1d",
        binding_status="ok",
        proof_fact_allowed=True,
        required_hypotheses=["h_force", "h_mass"],
    )
    algebra = AlgebraObligation(
        obligation_id="alg_target",
        claim="solve for acceleration",
        formal_claim="a = F / m",
        required_equations=["sk1", "h_mass"],
        target_variables=["a"],
    )
    sketch = ControlledSketch(sample_id="s1", status="ok", proof_steps=[obligation], algebra_obligation=algebra, parse_ok=True)
    interface_gap = ModelInterfaceInstantiation(
        instantiation_id="net_force_top",
        kind="net_force_balance",
        formal_claim="Fnet = F",
        source_model_instance="mi1",
        introduced_variable={"name": "Fnet", "lean_type": "Force"},
    )
    audit = SketchAuditResult(sample_id="s1", audit_pass=True)
    candidate = TheoremSkeletonCandidate(
        sample_id="s1",
        candidate_id="c1",
        lean_header="import MechLib",
        theorem_decl="theorem c1 (F m a : Real) (hm : m != 0) (h : F = m * a) : a = F / m",
        assumptions=["hm : m != 0", "h : F = m * a"],
        plan="Use Newton second law, then solve for acceleration.",
        supporting_facts=["Newton second law in one dimension."],
        fact_sources=["problem", "mechlib:newton_second_law_1d"],
        library_symbols_used=["newton_second_law_1d"],
        grounding_explanation="The law is bound to a verified declaration.",
        unsupported_claims=[],
        parse_ok=True,
        raw_response="{}",
        round_index=0,
        hypothesis_provenance=[provenance],
        model_ir_digest="sha256-demo",
        evidence_bindings=[binding],
        controlled_sketch=sketch,
        proof_obligations=[obligation],
        selected_laws=["newton_second_law_1d"],
        verified_decls=["MechLib.Dynamics.NewtonSecondLaw.newton_second_law_1d"],
        gap_laws=[],
        skeleton_audit=audit,
        model_interface_instantiations=[interface_gap],
        explicit_model_gaps=[{"source_id": "net_force_top", "proof_fact_allowed": False}],
        target_spec={"source": "problem_target"},
    )

    assert isinstance(candidate, StatementCandidate)
    assert candidate.generation_mode == "minimal_skeleton"
    assert candidate.candidate_id == "c1"
    assert candidate.theorem_decl.startswith("theorem c1")
    payload = candidate.to_dict()
    assert payload["candidate_id"] == "c1"
    assert payload["generation_mode"] == "minimal_skeleton"
    assert payload["hypothesis_provenance"][0]["role"] == "problem_fact"
    assert payload["model_interface_instantiations"][0]["instantiation_id"] == "net_force_top"
    json.dumps(payload)
