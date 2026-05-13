from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class BasePayloadModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class ProblemIRPayload(BasePayloadModel):
    objects: Any = Field(default_factory=list)
    known_quantities: Any = Field(default_factory=list)
    unknown_target: Any = Field(default_factory=dict)
    units: Any = Field(default_factory=list)
    constraints: Any = Field(default_factory=list)
    relations: Any = Field(default_factory=list)
    physical_laws: Any = Field(default_factory=list)
    assumptions: Any = Field(default_factory=list)
    diagram_information: Any = Field(default_factory=list)
    goal_statement: Any = ""
    coordinate_system: Any = None
    reference_frame: Any = None
    simplifications: Any = Field(default_factory=list)
    symbol_table: Any = Field(default_factory=dict)


class StatementCandidatePayload(BasePayloadModel):
    candidate_id: str | None = None
    lean_header: str | None = None
    theorem_decl: str | None = None
    assumptions: list[Any] = Field(default_factory=list)
    plan: str | None = None
    supporting_facts: list[Any] = Field(default_factory=list)
    fact_sources: list[Any] = Field(default_factory=list)
    library_symbols_used: list[Any] = Field(default_factory=list)
    grounding_explanation: str | None = None


class StatementCandidatesPayload(BasePayloadModel):
    candidates: list[StatementCandidatePayload] = Field(default_factory=list)


class HypothesisProvenancePayload(BasePayloadModel):
    name: str | None = None
    lean: str | None = None
    role: str | None = None
    source_type: str | None = None
    source_id: str | None = None
    allowed_in_hypotheses: bool | int | str | None = None
    notes: str | None = None
    proof_fact_allowed: bool | int | str | None = None


class ControlledSketchStepPayload(BasePayloadModel):
    step_id: str | None = None
    kind: str | None = None
    claim: str | None = None
    formal_claim: str | None = None
    source_model_instance: str | None = None
    planning_schema: str | None = None
    verified_decl: str | None = None
    binding_status: str | None = None
    expected_claim: str | None = None
    proof_fact_allowed: bool | int | str | None = None
    allowed_solvers: list[Any] = Field(default_factory=list)
    required_hypotheses: list[Any] = Field(default_factory=list)
    produces: str | None = None
    notes: str | None = None


class TheoremSkeletonCandidatePayload(StatementCandidatePayload):
    theorem_name_hint: str | None = None
    variant_id: str | None = None
    variant_policy: str | None = None
    target_form_policy: str | None = None
    hypothesis_policy: str | None = None
    law_policy: str | None = None
    gap_policy: str | None = None
    obligation_policy: str | None = None
    repair_directives: list[Any] = Field(default_factory=list)
    selected_givens: list[Any] = Field(default_factory=list)
    selected_model_instances: list[Any] = Field(default_factory=list)
    selected_target: Any = Field(default_factory=dict)
    hypothesis_provenance: list[HypothesisProvenancePayload] = Field(default_factory=list)
    selected_laws: list[Any] = Field(default_factory=list)
    verified_decls: list[Any] = Field(default_factory=list)
    gap_laws: list[Any] = Field(default_factory=list)
    proof_obligations: list[ControlledSketchStepPayload] = Field(default_factory=list)
    controlled_sketch_steps_used: list[Any] = Field(default_factory=list)
    unsupported_claims: list[Any] = Field(default_factory=list)
    skeleton_audit: Any = Field(default_factory=dict)


class TheoremSkeletonCandidatesPayload(BasePayloadModel):
    candidates: list[TheoremSkeletonCandidatePayload] = Field(default_factory=list)


class SemanticRankItemPayload(BasePayloadModel):
    candidate_id: str
    back_translation: str | None = None
    natural_language_statement: str | None = None
    translation: str | None = None
    semantic_score: float | int | str | None = None
    consistency_score: float | int | str | None = None
    semantic_pass: bool | int | str | None = None
    reason: str | None = None
    semantic_analysis: str | None = None
    comparison: str | None = None
    failure_summary: str | None = None
    failure_tags: Any = Field(default_factory=list)
    mismatch_fields: Any = Field(default_factory=list)
    missing_or_incorrect_translations: Any = Field(default_factory=list)
    suggested_fix_direction: str | None = None
    target_relation: str | None = None
    sub_error_type: str | None = None


class SemanticRankPayload(BasePayloadModel):
    results: list[SemanticRankItemPayload] | None = None
    ranking: list[SemanticRankItemPayload] | None = None
    candidates: list[SemanticRankItemPayload] | None = None
    items: list[SemanticRankItemPayload] | None = None
    candidate_id: str | None = None
    back_translation: str | None = None
    natural_language_statement: str | None = None
    translation: str | None = None
    semantic_score: float | int | str | None = None
    consistency_score: float | int | str | None = None
    semantic_pass: bool | int | str | None = None
    reason: str | None = None
    semantic_analysis: str | None = None
    comparison: str | None = None
    failure_summary: str | None = None
    failure_tags: Any = Field(default_factory=list)
    mismatch_fields: Any = Field(default_factory=list)
    missing_or_incorrect_translations: Any = Field(default_factory=list)
    suggested_fix_direction: str | None = None
    target_relation: str | None = None
    sub_error_type: str | None = None


class ProofPayload(BasePayloadModel):
    proof_body: str = ""
    strategy: str = ""
    used_facts: list[str] = Field(default_factory=list)
    subgoals: list[str] = Field(default_factory=list)
    fix_notes: list[str] = Field(default_factory=list)
    plan: str | None = None


class ProofPlanPayload(BasePayloadModel):
    plan: str | None = None
    theorems_to_apply: list[str] = Field(default_factory=list)
    givens_to_use: list[str] = Field(default_factory=list)
    intermediate_claims: list[str] = Field(default_factory=list)
    algebraic_cleanup_only: bool = False
    used_facts: list[str] = Field(default_factory=list)


class DirectFormalizationPayload(BasePayloadModel):
    theorem_decl: str = ""
    proof_body: str | None = None
    plan: str | None = None
    used_facts: list[str] = Field(default_factory=list)
