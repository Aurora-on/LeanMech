from __future__ import annotations

from mech_pipeline.knowledge.mechlib_structured import StructuredMechLibContext
from mech_pipeline.modules.A2_model_ir import SchemaPlanner
from mech_pipeline.types import ModelIR, ModelInstance


def test_schema_planner_fills_planning_schema_from_structured_context() -> None:
    context = StructuredMechLibContext(
        modeling_context={
            "matched_topics": ["Kinematics"],
            "concepts": [],
            "law_schemas": [
                {
                    "schema_id": "law.kinematics.constant_speed",
                    "corpus_type": "law_schema",
                    "topic": "constant speed displacement",
                    "statement_text": "Displacement equals speed times time.",
                    "proof_fact_allowed": False,
                }
            ],
            "problem_schemas": [],
            "aliases": [],
        },
        proof_context={"verified_decls": [], "required_imports": [], "proof_hints": [], "proof_style_examples": []},
    )
    model_ir = ModelIR(
        sample_id="s1",
        model_instances=[
            ModelInstance(
                instance_id="mi1",
                kind="constant_speed_kinematics",
                natural_language="Use constant speed displacement relation.",
                variables={"s": "displacement", "v": "speed", "t": "time"},
                expected_claim="s = v * t",
                confidence=0.9,
            )
        ],
        target={"symbol": "s", "description": "displacement"},
        forbidden_as_assumption=["target displacement s"],
        parse_ok=True,
    )

    out = SchemaPlanner(context).apply(model_ir)

    assert out.model_instances[0].planning_schema_id == "law.kinematics.constant_speed"
    assert not hasattr(out.model_instances[0], "verified_decl")


def test_schema_planner_does_not_replace_existing_schema_id() -> None:
    context = StructuredMechLibContext(
        modeling_context={
            "matched_topics": [],
            "concepts": [],
            "law_schemas": [{"schema_id": "law.other", "statement_text": "other"}],
            "problem_schemas": [],
            "aliases": [],
        },
        proof_context={"verified_decls": [], "required_imports": [], "proof_hints": [], "proof_style_examples": []},
    )
    model_ir = ModelIR(
        sample_id="s1",
        model_instances=[
            ModelInstance(
                instance_id="mi1",
                kind="constant_speed_kinematics",
                natural_language="Use constant speed displacement relation.",
                planning_schema_id="law.kinematics.constant_speed",
                expected_claim="s = v * t",
            )
        ],
        parse_ok=True,
    )

    out = SchemaPlanner(context).apply(model_ir)

    assert out.model_instances[0].planning_schema_id == "law.kinematics.constant_speed"
