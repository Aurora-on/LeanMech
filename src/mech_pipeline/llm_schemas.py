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


class StatementCandidatesPayload(BasePayloadModel):
    candidates: list[StatementCandidatePayload] = Field(default_factory=list)


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


class ProofPayload(BasePayloadModel):
    proof_body: str = ""
    strategy: str = ""
    used_facts: list[str] = Field(default_factory=list)
    subgoals: list[str] = Field(default_factory=list)
    fix_notes: list[str] = Field(default_factory=list)
    plan: str | None = None
