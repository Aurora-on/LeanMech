from __future__ import annotations

import json
from pathlib import Path

from mech_pipeline.cli import main
from mech_pipeline.knowledge.mechlib_structured import StructuredMechLibContext
from mech_pipeline.model.base import ModelClient
from mech_pipeline.modules.sketch_builder import (
    ModuleControlledSketch,
    _synthesized_kinematic_interface_instantiations,
    controlled_sketch_stage_row,
)
from mech_pipeline.types import (
    CanonicalTarget,
    EvidenceBinding,
    FunctionFormulaIR,
    HypothesisProvenance,
    ModelIR,
    ModelInstance,
    ModelResponse,
    QuantityTypeAnnotation,
)


class StaticSketchClient(ModelClient):
    def __init__(self, payload: str) -> None:
        self.model_id = "static-sketch"
        self.supports_vision = False
        self.payload = payload

    def generate_text(self, prompt: str, **kwargs) -> ModelResponse:
        _ = (prompt, kwargs)
        return ModelResponse(text=self.payload)

    def generate_multimodal(self, prompt: str, images_b64: list[str], **kwargs) -> ModelResponse:
        _ = (prompt, images_b64, kwargs)
        return ModelResponse(text=self.payload)


def _prompt(tmp_path: Path) -> Path:
    path = tmp_path / "controlled_sketch.txt"
    path.write_text("__TASK_CONTROLLED_SKETCH__", encoding="utf-8")
    return path


def _context() -> StructuredMechLibContext:
    return StructuredMechLibContext(
        modeling_context={
            "matched_topics": ["Kinematics"],
            "concepts": [],
            "law_schemas": [
                {
                    "id": "law.kinematics.constant_speed",
                    "corpus_type": "law_schema",
                    "proof_fact_allowed": False,
                }
            ],
            "problem_schemas": [],
            "aliases": [],
        },
        proof_context={
            "verified_decls": [
                {
                    "fq_name": "MechLib.Kinematics.constant_speed_relation",
                    "status": "verified",
                    "trust_level": "core",
                    "callable_by_llm": True,
                    "proof_fact_allowed": True,
                }
            ],
            "required_imports": ["import MechLib"],
            "proof_hints": [],
            "proof_style_examples": [],
        },
    )


def _model_ir() -> ModelIR:
    return ModelIR(
        sample_id="s1",
        givens=[
            HypothesisProvenance(
                name="h_v",
                lean="v = 10",
                role="problem_fact",
                source_type="problem_ir",
                source_id="known_quantities.v",
                allowed_in_hypotheses=True,
            )
        ],
        model_instances=[
            ModelInstance(
                instance_id="mi1",
                kind="constant_speed_kinematics",
                natural_language="Use constant speed displacement.",
                planning_schema_id="law.kinematics.constant_speed",
                expected_claim="s = v * t",
            )
        ],
        target={"symbol": "s", "description": "displacement"},
        forbidden_as_assumption=["target displacement s"],
        parse_ok=True,
    )


def _ok_binding() -> EvidenceBinding:
    return EvidenceBinding(
        binding_id="b1",
        model_instance_id="mi1",
        planning_schema="law.kinematics.constant_speed",
        verified_decl="MechLib.Kinematics.constant_speed_relation",
        proof_fact_allowed=True,
        binding_status="ok",
        expected_claim="s = v * t",
    )


def _gap_binding() -> EvidenceBinding:
    return EvidenceBinding(
        binding_id="b_gap",
        model_instance_id="mi1",
        planning_schema="law.kinematics.constant_speed",
        verified_decl=None,
        proof_fact_allowed=False,
        binding_status="gap_schema_only",
        expected_claim="s = v * t",
    )


def test_controlled_sketch_builds_canonical_variants_from_feedback(tmp_path: Path) -> None:
    payload = json.dumps(
        {
            "status": "ok",
            "proof_steps": [
                {
                    "step_id": "sk1",
                    "kind": "law_to_equation",
                    "claim": "constant speed relation",
                    "formal_claim": "s = v * t",
                    "source_model_instance": "mi1",
                    "planning_schema": "law.kinematics.constant_speed",
                    "verified_decl": "MechLib.Kinematics.constant_speed_relation",
                    "binding_status": "ok",
                    "expected_claim": "s = v * t",
                    "proof_fact_allowed": True,
                    "produces": "h_law",
                }
            ],
            "algebra_obligation": {
                "obligation_id": "alg_target",
                "claim": "final target",
                "formal_claim": "s = v * t",
                "required_equations": ["h_law"],
                "target_variables": ["s"],
            },
            "blocked_law_steps": [],
        }
    )
    feedback = json.dumps(
        {
            "retry_reason": "no_compile_pass",
            "candidate_count": 4,
            "candidates": [
                {
                    "candidate_id": "c1",
                    "generation_blocked_reason": "missing_typed_target_formula",
                    "unsupported_claims": ["duplicate_skeleton_shape:c1"],
                    "error_type": "unknown_identifier",
                    "stderr_digest": "unknown constant bad_symbol",
                }
            ],
        }
    )
    module = ModuleControlledSketch(StaticSketchClient(payload), _prompt(tmp_path))

    sketch = module.run(
        sample_id="s1",
        problem_text="A particle moves with constant speed.",
        problem_ir={},
        model_ir=_model_ir(),
        evidence_bindings=[_ok_binding()],
        structured_mechlib_context=_context(),
        revision_feedback=feedback,
        round_index=1,
    )

    assert sketch.parse_ok is True
    assert {"compile_oriented", "target_missing", "avoid_duplicate_shape"}.issubset(set(sketch.repair_directives))
    assert [variant.variant_id for variant in sketch.sketch_variants] == [
        "v1_verified_only",
        "v2_explicit_gap_allowed",
        "v3_implicit_relation",
        "v4_compile_oriented",
    ]
    assert sketch.sketch_variants[0].target_form_policy == "forbidden_target"
    assert sketch.sketch_variants[3].variant_policy == "compile_oriented"


def _two_law_model_ir() -> ModelIR:
    return ModelIR(
        sample_id="atwood",
        givens=[
            HypothesisProvenance(
                name="h_m1",
                lean="0 < m1",
                role="problem_fact",
                source_type="problem_ir",
                allowed_in_hypotheses=True,
            )
        ],
        model_instances=[
            ModelInstance(
                instance_id="mi1",
                kind="newton_second_law_1d",
                natural_language="Newton law for m1.",
                planning_schema_id="law.newton",
                expected_claim="T = m1 * a",
            ),
            ModelInstance(
                instance_id="mi2",
                kind="newton_second_law_1d",
                natural_language="Newton law for m2.",
                planning_schema_id="law.newton",
                expected_claim="m2 * g - T = m2 * a",
            ),
        ],
        target={"symbol": "a", "description": "acceleration"},
        parse_ok=True,
    )


def _binding(instance_id: str, expected_claim: str) -> EvidenceBinding:
    return EvidenceBinding(
        binding_id=f"{instance_id}_binding",
        model_instance_id=instance_id,
        planning_schema="law.newton",
        verified_decl=f"MechLib.Test.{instance_id}",
        proof_fact_allowed=True,
        binding_status="ok",
        expected_claim=expected_claim,
    )


def test_controlled_sketch_uses_verified_binding_for_law_step(tmp_path: Path) -> None:
    payload = json.dumps(
        {
            "proof_steps": [
                {
                    "step_id": "sk1",
                    "kind": "law_to_equation",
                    "claim": "constant speed law",
                    "formal_claim": "s = v * t",
                    "source_model_instance": "mi1",
                    "planning_schema": "law.kinematics.constant_speed",
                    "verified_decl": "MechLib.Kinematics.constant_speed_relation",
                    "binding_status": "ok",
                    "expected_claim": "s = v * t",
                    "proof_fact_allowed": True,
                    "allowed_solvers": ["simp", "linarith"],
                    "required_hypotheses": ["h_v"],
                    "produces": "h_law",
                }
            ],
            "blocked_law_steps": [],
        }
    )
    module = ModuleControlledSketch(StaticSketchClient(payload), _prompt(tmp_path))

    sketch = module.run(
        sample_id="s1",
        problem_text="A particle moves at constant speed.",
        problem_ir={},
        model_ir=_model_ir(),
        evidence_bindings=[_ok_binding()],
        structured_mechlib_context=_context(),
    )

    assert sketch.parse_ok is True
    assert sketch.status == "ok"
    assert sketch.proof_steps[0].kind == "law_to_equation"
    assert sketch.proof_steps[0].verified_decl == "MechLib.Kinematics.constant_speed_relation"
    assert sketch.proof_steps[0].proof_fact_allowed is True
    assert sketch.proof_steps[0].formal_claim == "s = v * t"
    json.dumps(controlled_sketch_stage_row("s1", sketch))


def test_controlled_sketch_blocks_packed_comma_expected_claim_from_auto_step(tmp_path: Path) -> None:
    payload = json.dumps({"proof_steps": [], "blocked_law_steps": []})
    module = ModuleControlledSketch(StaticSketchClient(payload), _prompt(tmp_path))

    sketch = module.run(
        sample_id="s1",
        problem_text="A compound initial condition is described.",
        problem_ir={},
        model_ir=_model_ir(),
        evidence_bindings=[
            EvidenceBinding(
                binding_id="b_bad",
                model_instance_id="mi1",
                planning_schema="law.kinematics.constant_speed",
                verified_decl="MechLib.Kinematics.constant_speed_relation",
                proof_fact_allowed=True,
                binding_status="ok",
                expected_claim="omega_i = 0, v_i = u, v_G = u",
            )
        ],
        structured_mechlib_context=_context(),
    )

    assert sketch.parse_ok is True
    assert sketch.status == "blocked_by_evidence_gap"
    assert sketch.proof_steps == []
    assert sketch.blocked_law_steps
    assert sketch.blocked_law_steps[0].verified_decl == "MechLib.Kinematics.constant_speed_relation"
    assert sketch.blocked_law_steps[0].binding_status == "verified_decl_uninstantiated"
    assert sketch.blocked_law_steps[0].reason == "Proof-eligible binding does not provide a single valid Lean-like expected_claim."


def test_controlled_sketch_blocks_invalid_llm_proof_step_formula(tmp_path: Path) -> None:
    payload = json.dumps(
        {
            "proof_steps": [
                {
                    "step_id": "sk_bad",
                    "kind": "law_to_equation",
                    "formal_claim": "omega_i = 0, v_i = u, v_G = u",
                    "source_model_instance": "mi1",
                    "binding_status": "ok",
                    "proof_fact_allowed": True,
                    "produces": "h_bad",
                }
            ]
        }
    )
    module = ModuleControlledSketch(StaticSketchClient(payload), _prompt(tmp_path))

    sketch = module.run(
        sample_id="s1",
        problem_text="A compound initial condition is described.",
        problem_ir={},
        model_ir=_model_ir(),
        evidence_bindings=[_ok_binding()],
        structured_mechlib_context=_context(),
    )

    assert sketch.parse_ok is True
    assert sketch.status == "ok"
    assert len(sketch.proof_steps) == 1
    assert sketch.proof_steps[0].formal_claim == "s = v * t"
    assert sketch.blocked_law_steps == []
    assert all(step.formal_claim != "omega_i = 0, v_i = u, v_G = u" for step in sketch.proof_steps)


def test_controlled_sketch_keeps_two_verified_law_steps_and_one_algebra_obligation(tmp_path: Path) -> None:
    payload = json.dumps(
        {
            "steps": [
                {
                    "step_id": "sk_m1",
                    "kind": "law_application",
                    "claim": "Newton law for m1 gives T = m1 * a.",
                    "formal_claim": "T = m1 * a",
                    "source_model_instance": "mi1",
                    "planning_schema": "law.newton",
                    "binding_status": "ok",
                    "proof_fact_allowed": True,
                    "produces": "h_m1_eq",
                },
                {
                    "step_id": "sk_m2",
                    "kind": "law_application",
                    "claim": "Newton law for m2 gives m2 * g - T = m2 * a.",
                    "formal_claim": "m2 * g - T = m2 * a",
                    "source_model_instance": "mi2",
                    "planning_schema": "law.newton",
                    "binding_status": "ok",
                    "proof_fact_allowed": True,
                    "produces": "h_m2_eq",
                },
                {
                    "step_id": "h_combined",
                    "kind": "target_rewrite",
                    "claim": "combine the equations",
                    "formal_claim": "m2 * g = (m1 + m2) * a",
                    "produces": "h_combined",
                },
            ],
            "algebra_obligation": {
                "obligation_id": "alg_target",
                "claim": "solve for a",
                "formal_claim": "a = (m2 * g) / (m1 + m2)",
                "required_equations": ["h_m1_eq", "h_m2_eq"],
                "target_variables": ["a"],
                "allowed_solvers": ["ring", "nlinarith"],
            },
        }
    )
    module = ModuleControlledSketch(StaticSketchClient(payload), _prompt(tmp_path))

    sketch = module.run(
        sample_id="atwood",
        problem_text="Atwood-style problem.",
        problem_ir={},
        model_ir=_two_law_model_ir(),
        evidence_bindings=[
            _binding("mi1", "T = m1 * a"),
            _binding("mi2", "m2 * g - T = m2 * a"),
        ],
        structured_mechlib_context=_context(),
    )

    assert sketch.parse_ok is True
    assert sketch.status == "ok"
    assert [step.kind for step in sketch.proof_steps] == ["law_to_equation", "law_to_equation"]
    assert len(sketch.proof_steps) == 2
    assert sketch.algebra_obligation is not None
    dumped = json.dumps(sketch.to_dict())
    assert "h_combined" not in dumped
    assert "h_nonzero_sum" not in dumped
    assert "h_accel_formula" not in dumped
    assert "h_target" not in dumped


def test_controlled_sketch_marks_unbound_law_as_gap(tmp_path: Path) -> None:
    payload = json.dumps(
        {
            "proof_steps": [
                {
                    "step_id": "sk1",
                    "kind": "law_to_equation",
                    "claim": "s = v * t",
                    "formal_claim": "s = v * t",
                    "source_model_instance": "mi1",
                    "planning_schema": "law.kinematics.constant_speed",
                    "verified_decl": "MechLib.Kinematics.invented",
                    "binding_status": "ok",
                    "expected_claim": "s = v * t",
                    "proof_fact_allowed": True,
                }
            ],
            "blocked_law_steps": [],
        }
    )
    module = ModuleControlledSketch(StaticSketchClient(payload), _prompt(tmp_path))

    sketch = module.run(
        sample_id="s1",
        problem_text="A particle moves at constant speed.",
        problem_ir={},
        model_ir=_model_ir(),
        evidence_bindings=[_gap_binding()],
        structured_mechlib_context=_context(),
    )

    assert sketch.parse_ok is True
    assert sketch.status == "blocked_by_evidence_gap"
    assert sketch.proof_steps == []
    assert sketch.blocked_law_steps[0].binding_status == "gap_schema_only"
    assert sketch.blocked_law_steps[0].proof_fact_allowed is False


def test_controlled_sketch_all_gap_bindings_are_blocked_without_proof_steps(tmp_path: Path) -> None:
    payload = json.dumps(
        {
            "proof_steps": [
                {
                    "step_id": "sk_m1",
                    "kind": "law_to_equation",
                    "formal_claim": "T = m1 * a",
                    "source_model_instance": "mi1",
                    "proof_fact_allowed": False,
                },
                {
                    "step_id": "sk_m2",
                    "kind": "law_to_equation",
                    "formal_claim": "m2 * g - T = m2 * a",
                    "source_model_instance": "mi2",
                    "proof_fact_allowed": False,
                },
            ]
        }
    )
    module = ModuleControlledSketch(StaticSketchClient(payload), _prompt(tmp_path))

    sketch = module.run(
        sample_id="atwood",
        problem_text="Atwood-style problem.",
        problem_ir={},
        model_ir=_two_law_model_ir(),
        evidence_bindings=[
            EvidenceBinding(
                binding_id="gap1",
                model_instance_id="mi1",
                planning_schema="law.newton",
                binding_status="gap_schema_only",
                proof_fact_allowed=False,
                expected_claim="T = m1 * a",
            ),
            EvidenceBinding(
                binding_id="gap2",
                model_instance_id="mi2",
                planning_schema="law.newton",
                binding_status="gap_schema_only",
                proof_fact_allowed=False,
                expected_claim="m2 * g - T = m2 * a",
            ),
        ],
        structured_mechlib_context=_context(),
    )

    assert sketch.status == "blocked_by_evidence_gap"
    assert sketch.proof_steps == []
    assert sketch.algebra_obligation is None
    assert {step.source_model_instance for step in sketch.blocked_law_steps} == {"mi1", "mi2"}


def test_controlled_sketch_accepts_explanatory_gap_step_objects(tmp_path: Path) -> None:
    payload = json.dumps(
        {
            "steps": [],
            "gap_steps": [
                {
                    "step_id": "gap1",
                    "gap_reason": "No verified declaration was bound for this model instance.",
                }
            ],
        }
    )
    module = ModuleControlledSketch(StaticSketchClient(payload), _prompt(tmp_path))

    sketch = module.run(
        sample_id="s1",
        problem_text="A particle moves at constant speed.",
        problem_ir={},
        model_ir=_model_ir(),
        evidence_bindings=[_gap_binding()],
        structured_mechlib_context=_context(),
    )

    assert sketch.parse_ok is True
    assert sketch.status == "blocked_by_evidence_gap"
    assert sketch.proof_steps == []
    assert sketch.blocked_law_steps[0].step_id == "gap1"
    assert sketch.blocked_law_steps[0].source_model_instance == "mi1"
    assert sketch.blocked_law_steps[0].planning_schema == "law.kinematics.constant_speed"
    assert sketch.blocked_law_steps[0].expected_claim == "s = v * t"
    assert sketch.blocked_law_steps[0].binding_status == "gap_schema_only"
    assert sketch.blocked_law_steps[0].proof_fact_allowed is False


def test_controlled_sketch_synthesizes_function_kinematic_derivative_interfaces(tmp_path: Path) -> None:
    payload = json.dumps({"status": "ok", "proof_steps": [], "blocked_law_steps": []})
    module = ModuleControlledSketch(StaticSketchClient(payload), _prompt(tmp_path))
    model_ir = ModelIR(
        sample_id="function-kinematics",
        quantity_annotations=[
            QuantityTypeAnnotation("x", semantic_role="position over time", lean_type="Time -> Length", confidence=0.95),
            QuantityTypeAnnotation("v", semantic_role="velocity over time", lean_type="Time -> Speed", confidence=0.95),
            QuantityTypeAnnotation("a", semantic_role="acceleration over time", lean_type="Time -> Acceleration", confidence=0.95),
        ],
        canonical_target=CanonicalTarget(
            target_kind="pointwise_function_relation",
            target_variables=["a"],
            lean_formula="forall t0 : Real, (a t0).val = deriv (fun s : Real => (v s).val) t0",
            parse_ok=True,
        ),
        model_instances=[
            ModelInstance(
                instance_id="mi_motion",
                kind="function_kinematics",
                natural_language="Use kinematic derivative bridges.",
                expected_claim="v = deriv x and a = deriv v",
                confidence=0.8,
            )
        ],
        parse_ok=True,
    )

    sketch = module.run(
        sample_id="function-kinematics",
        problem_text="Given x(t), find velocity and acceleration.",
        problem_ir={},
        model_ir=model_ir,
        evidence_bindings=[],
        structured_mechlib_context=_context(),
    )

    claims = {row.formal_claim for row in sketch.model_interface_instantiations}
    assert "forall t0 : Real, (v t0).val = deriv (fun u : Real => (x u).val) t0" in claims
    assert "forall t0 : Real, (a t0).val = deriv (fun u : Real => (v u).val) t0" in claims
    assert all(row.binding_status == "explicit_model_gap" for row in sketch.model_interface_instantiations)
    assert all(row.proof_fact_allowed is False for row in sketch.model_interface_instantiations)


def test_synthesized_kinematic_bridge_does_not_shadow_trajectory_symbol() -> None:
    model_ir = ModelIR(
        sample_id="arc-length-shadow",
        quantity_annotations=[
            QuantityTypeAnnotation("s", semantic_role="arc length trajectory", lean_type="Time -> Length", confidence=0.95),
            QuantityTypeAnnotation("v", semantic_role="speed field", lean_type="Time -> Speed", confidence=0.95),
        ],
        canonical_target=CanonicalTarget(
            target_kind="pointwise_function_relation",
            target_variables=["v"],
            lean_formula="forall t0 : Real, (v t0).val = deriv (fun u : Real => (s u).val) t0",
            parse_ok=True,
        ),
        model_instances=[
            ModelInstance(
                instance_id="mi_arc_length",
                kind="function_kinematics",
                natural_language="Use v = ds/dt.",
                expected_claim="v is the derivative of s",
            )
        ],
        parse_ok=True,
    )

    rows = _synthesized_kinematic_interface_instantiations(model_ir)
    claims = [row.formal_claim for row in rows]

    assert any("(v t0).val = deriv (fun u : Real => (s u).val) t0" in claim for claim in claims)
    assert all("(s s).val" not in claim for claim in claims)


def test_minimal_skeleton_cli_writes_sketch_and_audit_jsonl(tmp_path: Path) -> None:
    archive_root = tmp_path / "archive"
    (archive_root / "output_description_part1").mkdir(parents=True)
    (archive_root / "output_description_part1" / "1-1.md").write_text(
        "A particle moves at constant speed v for time t. Find displacement s.",
        encoding="utf-8",
    )
    output_latest = tmp_path / "latest"
    config_path = tmp_path / "minimal.yaml"
    config_path.write_text(
        f"""
dataset:
  source: local_archive
  limit: 1
  local_archive:
    root: "{archive_root.as_posix()}"
    mode: text_only
model:
  provider: mock
  model_id: mock-minimal
knowledge:
  enabled: false
lean:
  enabled: false
  preflight_enabled: false
statement:
  generation_mode: minimal_skeleton
  feedback_loop_enabled: false
output:
  output_dir: "{output_latest.as_posix()}"
  runs_dir: "{(tmp_path / 'runs').as_posix()}"
  tag: "minimal-skeleton-sketch-smoke"
""",
        encoding="utf-8",
    )

    code = main(["run", "--config", str(config_path)])

    assert code == 0
    sketch_rows = [
        json.loads(line)
        for line in (output_latest / "controlled_sketch.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    audit_rows = [
        json.loads(line)
        for line in (output_latest / "sketch_audit.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    binding_rows = [
        json.loads(line)
        for line in (output_latest / "evidence_bindings.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    statement_rows = [
        json.loads(line)
        for line in (output_latest / "statement_candidates.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    skeleton_rows = [
        json.loads(line)
        for line in (output_latest / "theorem_skeleton_candidates.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert sketch_rows and sketch_rows[0]["parse_ok"] is True
    assert sketch_rows[0]["status"] == "blocked_by_evidence_gap"
    assert sketch_rows[0]["blocked_law_steps"]
    assert "gap_steps" not in sketch_rows[0]
    assert audit_rows and audit_rows[0]["audit_pass"] is True
    assert binding_rows and binding_rows[0]["binding_status"] == "gap_schema_only"
    assert statement_rows and statement_rows[0]["generation_mode"] == "minimal_skeleton"
    assert statement_rows[0]["hypothesis_provenance"]
    assert statement_rows[0]["gap_laws"]
    assert "verified_decls" in statement_rows[0]
    assert skeleton_rows and skeleton_rows[0]["candidate_id"] == statement_rows[0]["candidate_id"]
