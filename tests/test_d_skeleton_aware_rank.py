from __future__ import annotations

from pathlib import Path

from mech_pipeline.model.base import ModelClient
from mech_pipeline.types import (
    CompileCheckResult,
    ControlledSketchStep,
    EvidenceBinding,
    GroundingResult,
    HypothesisProvenance,
    ModelResponse,
    SketchAuditResult,
    StatementCandidate,
    TheoremSkeletonCandidate,
)
from mech_pipeline.modules.D_semantic_rank import ModuleD


class FixedSemanticLLM(ModelClient):
    def __init__(self, payload: str) -> None:
        self.model_id = "fixed-semantic"
        self.supports_vision = False
        self.payload = payload

    def generate_text(self, prompt: str, **kwargs) -> ModelResponse:
        _ = (prompt, kwargs)
        return ModelResponse(text=self.payload)

    def generate_multimodal(self, prompt: str, images_b64: list[str], **kwargs) -> ModelResponse:
        _ = (images_b64,)
        return self.generate_text(prompt, **kwargs)


def _prompt(tmp_path: Path) -> Path:
    path = tmp_path / "D_semantic_rank.txt"
    path.write_text("__TASK_D_SEMANTIC_RANK__\n{{candidate_payload_json}}", encoding="utf-8")
    return path


def _grounding() -> GroundingResult:
    return GroundingResult(
        sample_id="s-skeleton",
        model_id="m",
        problem_ir={
            "unknown_target": {"symbol": "a", "description": "acceleration"},
            "known_quantities": [{"symbol": "T"}, {"symbol": "m"}],
            "physical_laws": ["NewtonSecondLaw"],
        },
        parse_ok=True,
        raw_response="",
        error=None,
    )


def _compile(cid: str = "c1") -> CompileCheckResult:
    return CompileCheckResult(
        sample_id="s-skeleton",
        candidate_id=cid,
        compile_pass=True,
        syntax_ok=True,
        elaboration_ok=True,
        error_type=None,
        stderr_digest="",
        log_path=None,
    )


def _binding(status: str = "ok", allowed: bool = True) -> EvidenceBinding:
    return EvidenceBinding(
        binding_id="b1",
        model_instance_id="mi1",
        verified_decl="MechLib.Dynamics.NewtonSecondLaw" if status == "ok" else None,
        decl_status="verified" if status == "ok" else None,
        trust_level="core" if status == "ok" else None,
        callable_by_llm=True if status == "ok" else None,
        lean_check_pass=True if status == "ok" else None,
        proof_fact_allowed=allowed,
        binding_status=status,
        expected_claim="T.val = m.val * a.val",
    )


def _obligation(status: str = "ok", allowed: bool = True) -> ControlledSketchStep:
    return ControlledSketchStep(
        step_id="step_newton",
        kind="law_to_equation",
        claim="Newton's second law",
        formal_claim="T.val = m.val * a.val",
        source_model_instance="mi1",
        planning_schema="newton_second_law_1d",
        verified_decl="MechLib.Dynamics.NewtonSecondLaw" if status == "ok" else None,
        binding_status=status,
        expected_claim="T.val = m.val * a.val",
        proof_fact_allowed=allowed,
        produces="h_newton",
    )


def _minimal_candidate(
    *,
    theorem_decl: str = "theorem c1 (T : Force) (m : Mass) (a : Acceleration) : a.val = T.val / m.val",
    proof_obligations: list[ControlledSketchStep] | None = None,
    evidence_bindings: list[EvidenceBinding] | None = None,
) -> TheoremSkeletonCandidate:
    return TheoremSkeletonCandidate(
        sample_id="s-skeleton",
        candidate_id="c1",
        lean_header="import MechLib",
        theorem_decl=theorem_decl,
        parse_ok=True,
        hypothesis_provenance=[
            HypothesisProvenance(
                name="hm",
                lean="0 < m.val",
                role="problem_fact",
                source_type="problem_text",
                allowed_in_hypotheses=True,
            )
        ],
        proof_obligations=proof_obligations if proof_obligations is not None else [_obligation()],
        evidence_bindings=evidence_bindings if evidence_bindings is not None else [_binding()],
        verified_decls=["MechLib.Dynamics.NewtonSecondLaw"],
        target_spec={
            "target_kind": "relation",
            "target_variables": ["a"],
            "lean_formula": "a.val = T.val / m.val",
            "parse_ok": True,
        },
        skeleton_audit=SketchAuditResult(sample_id="s-skeleton", audit_pass=True),
    )


def test_minimal_skeleton_uses_proof_obligations_for_law_semantics(tmp_path: Path) -> None:
    payload = """
    {
      "results": [
        {
          "candidate_id": "c1",
          "back_translation": "The theorem lacks Newton's law in the theorem text.",
          "semantic_score": 0.2,
          "semantic_pass": false,
          "failure_tags": ["law_drift"],
          "reason": "The Newton equation is not in the theorem declaration."
        }
      ]
    }
    """
    mod = ModuleD(model_client=FixedSemanticLLM(payload), prompt_path=_prompt(tmp_path), pass_threshold=0.7)

    rank = mod.run(
        _grounding(),
        [_minimal_candidate()],
        [_compile()],
        problem_text="Given tension and mass, find acceleration using Newton's second law.",
    )
    row = rank.ranking[0]

    assert rank.semantic_pass is True
    assert row["semantic_pass"] is True
    assert row["proof_obligation_coverage_score"] == 1.0
    assert row["evidence_binding_score"] > 0.0
    assert row["skeleton_semantic_score"] >= 0.7
    assert "T.val = m.val * a.val" not in row["theorem_decl"].split(":", 1)[0]


def test_minimal_skeleton_flags_derived_equation_hypothesis(tmp_path: Path) -> None:
    payload = """
    {"results":[{"candidate_id":"c1","semantic_score":0.95,"semantic_pass":true,"target_relation":"exact","reason":"aligned"}]}
    """
    mod = ModuleD(model_client=FixedSemanticLLM(payload), prompt_path=_prompt(tmp_path), pass_threshold=0.7)
    candidate = _minimal_candidate(
        theorem_decl=(
            "theorem c1 (T : Force) (m : Mass) (a : Acceleration) "
            "(h_newton : T.val = m.val * a.val) : a.val = T.val / m.val"
        )
    )

    rank = mod.run(_grounding(), [candidate], [_compile()], problem_text="Find acceleration.")
    row = rank.ranking[0]

    assert row["semantic_pass"] is False
    assert "derived_equation_hypothesis_violation" in row["skeleton_hard_gate_reasons"]
    assert "derived_equation_hypothesis_violation" in row["failure_tags"]


def test_minimal_skeleton_marks_gap_obligation_without_target_mismatch(tmp_path: Path) -> None:
    mod = ModuleD(model_client=None, prompt_path=_prompt(tmp_path), pass_threshold=0.7)
    candidate = _minimal_candidate(
        proof_obligations=[_obligation(status="gap_schema_only", allowed=False)],
        evidence_bindings=[_binding(status="gap_schema_only", allowed=False)],
    )
    candidate.gap_laws = [{"source_model_instance": "mi1", "binding_status": "gap_schema_only"}]
    candidate.gap_schema_only = True

    rank = mod.run(_grounding(), [candidate], [_compile()], problem_text="Find acceleration.")
    row = rank.ranking[0]

    assert row["semantic_pass"] is False
    assert "proof_obligation_gap_violation" in row["failure_tags"] or "evidence_gap" in row["failure_tags"]
    assert "target_mismatch" not in row["hard_gate_reasons"]
    assert row["gap_penalty"] > 0.0


def test_pragmatic_target_skeleton_needs_strong_target_match(tmp_path: Path) -> None:
    payload = """
    {"results":[{"candidate_id":"c1","semantic_score":0.95,"semantic_pass":true,"target_relation":"exact","reason":"aligned"}]}
    """
    mod = ModuleD(model_client=FixedSemanticLLM(payload), prompt_path=_prompt(tmp_path), pass_threshold=0.7)
    candidate = _minimal_candidate(
        theorem_decl="theorem c1 (v : Speed) : v.val = 1",
        proof_obligations=[],
        evidence_bindings=[],
    )
    candidate.grounding_status = "pragmatic_target_skeleton"
    candidate.target_spec = {
        "target_kind": "closed_form",
        "target_variables": ["v"],
        "lean_formula": "v.val = 1",
        "parse_ok": True,
    }

    rank = mod.run(_grounding(), [candidate], [_compile()], problem_text="Find acceleration.")
    row = rank.ranking[0]

    assert row["semantic_pass"] is False
    assert "pragmatic_target_symbol_mismatch" in row["hard_gate_reasons"]


def test_coordinate_orientation_sign_equivalence_is_warning_not_blocker(tmp_path: Path) -> None:
    payload = """
    {
      "results": [
        {
          "candidate_id": "c1",
          "semantic_score": 0.9,
          "semantic_pass": false,
          "target_relation": "equivalent",
          "reason": "The target is equivalent: the leftward paper motion is absorbed into a coordinate orientation choice.",
          "failure_summary": "Only a sign convention choice is implicit.",
          "failure_tags": ["sign_convention_choice"],
          "mismatch_fields": ["sign"]
        }
      ]
    }
    """
    mod = ModuleD(model_client=FixedSemanticLLM(payload), prompt_path=_prompt(tmp_path), pass_threshold=0.7)
    grounding = GroundingResult(
        sample_id="s-skeleton",
        model_id="m",
        problem_ir={
            "unknown_target": {"symbol": "y_p", "description": "trajectory on a left-moving paper"},
            "known_quantities": [{"symbol": "a"}, {"symbol": "k"}, {"symbol": "beta"}, {"symbol": "v_c"}],
            "physical_laws": ["Kinematics"],
        },
        parse_ok=True,
        raw_response="",
        error=None,
    )
    candidate = TheoremSkeletonCandidate(
        sample_id="s-skeleton",
        candidate_id="c1",
        lean_header="import MechLib",
        theorem_decl=(
            "theorem c1 (a k beta v_c : Real) (x_p y_p : Real -> Real) : "
            "forall t : Real, y_p t = a * Real.cos ((k / v_c) * x_p t + beta)"
        ),
        parse_ok=True,
        generation_mode="minimal_skeleton",
        grounding_status="partial_mechlib_with_model_gaps",
        target_spec={
            "target_kind": "pointwise_function_relation",
            "target_variables": ["x_p", "y_p", "a", "k", "beta", "v_c"],
            "lean_formula": "forall t : Real, y_p t = a * Real.cos ((k / v_c) * x_p t + beta)",
            "parse_ok": True,
        },
        skeleton_audit=SketchAuditResult(sample_id="s-skeleton", audit_pass=True),
    )

    rank = mod.run(grounding, [candidate], [_compile()], problem_text="Find the trace on a left-moving paper.")
    row = rank.ranking[0]

    assert row["semantic_pass"] is True
    assert row["target_relation"] == "equivalent"
    assert "pragmatic_target_low_match" not in row["hard_gate_reasons"]
    assert row["sub_error_type"] is None


def test_legacy_candidate_keeps_old_semantic_payload(tmp_path: Path) -> None:
    mod = ModuleD(model_client=None, prompt_path=_prompt(tmp_path), pass_threshold=0.2)
    candidate = StatementCandidate(
        sample_id="s-skeleton",
        candidate_id="c1",
        lean_header="import Physlib",
        theorem_decl="theorem c1 (T m a : Real) : a = T / m",
        parse_ok=True,
    )

    rank = mod.run(_grounding(), [candidate], [_compile()], problem_text="Find acceleration.")
    row = rank.ranking[0]

    assert row["generation_mode"] is None
    assert "skeleton_semantic_score" not in row
    assert "proof_obligation_coverage_score" not in row


def test_minimal_skeleton_ranking_item_contains_skeleton_scores(tmp_path: Path) -> None:
    mod = ModuleD(model_client=None, prompt_path=_prompt(tmp_path), pass_threshold=0.2)

    rank = mod.run(_grounding(), [_minimal_candidate()], [_compile()], problem_text="Find acceleration.")
    row = rank.ranking[0]

    assert "skeleton_semantic_score" in row
    assert "target_match_score" in row
    assert "hypothesis_minimality_score" in row
    assert "proof_obligation_coverage_score" in row
    assert "evidence_binding_score" in row
    assert "gap_penalty" in row
    assert "proof_obligation_summary" in row
    assert "model_predicate_binding_summary" in row
    assert "gap_summary" in row
