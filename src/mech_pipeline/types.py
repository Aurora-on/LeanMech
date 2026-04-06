from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class CanonicalSample:
    sample_id: str
    source: str
    problem_text: str
    options: list[str] = field(default_factory=list)
    gold_answer: str | None = None
    image_b64: str | None = None
    image_path: str | None = None
    image_description: str | None = None
    category: str | None = None
    subfield: str | None = None
    reasoning_type: str | None = None
    skip_reason: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GroundingResult:
    sample_id: str
    model_id: str | None
    problem_ir: dict[str, Any] | None
    parse_ok: bool
    raw_response: str
    error: str | None
    vision_fallback: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StatementCandidate:
    sample_id: str
    candidate_id: str
    lean_header: str
    theorem_decl: str
    assumptions: list[str] = field(default_factory=list)
    plan: str | None = None
    parse_ok: bool = False
    raw_response: str = ""
    error: str | None = None
    round_index: int = 0
    source_round_index: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CompileCheckResult:
    sample_id: str
    candidate_id: str
    compile_pass: bool
    syntax_ok: bool
    elaboration_ok: bool
    error_type: str | None
    stderr_digest: str
    log_path: str | None
    backend_used: str | None = None
    route_reason: str | None = None
    route_fallback_used: bool = False
    round_index: int = 0
    stderr_excerpt: str | None = None
    error_line: int | None = None
    error_message: str | None = None
    error_snippet: str | None = None
    sub_error_type: str | None = None
    failure_tags: list[str] = field(default_factory=list)
    failure_summary: str | None = None
    failure_details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SemanticRankResult:
    sample_id: str
    selected_candidate_id: str | None
    selected_theorem_decl: str | None
    semantic_pass: bool
    ranking: list[dict[str, Any]]
    selected_backend: str | None = None
    selected_route_reason: str | None = None
    selected_route_fallback_used: bool = False
    error: str | None = None
    round_index: int = 0
    retry_triggered: bool = False
    retry_reason: str | None = None
    retry_feedback_summary: str | None = None
    sub_error_type: str | None = None
    failure_tags: list[str] = field(default_factory=list)
    failure_summary: str | None = None
    failure_details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProofAttemptResult:
    sample_id: str
    attempt_index: int
    proof_body: str
    parse_ok: bool
    raw_response: str
    compile_pass: bool
    strict_pass: bool
    error_type: str | None
    stderr_digest: str
    log_path: str | None
    plan: str | None = None
    backend_used: str | None = None
    route_reason: str | None = None
    route_fallback_used: bool = False
    sub_error_type: str | None = None
    failure_tags: list[str] = field(default_factory=list)
    failure_summary: str | None = None
    failure_details: dict[str, Any] = field(default_factory=dict)
    proof_body_excerpt: str | None = None
    stderr_excerpt: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProofCheckResult:
    sample_id: str
    proof_success: bool
    attempts_used: int
    selected_candidate_id: str | None
    error_type: str | None
    final_log_path: str | None
    backend_used: str | None = None
    round_index: int = 0
    sub_error_type: str | None = None
    failure_tags: list[str] = field(default_factory=list)
    failure_summary: str | None = None
    failure_details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SampleRunSummary:
    sample_id: str
    grounding_ok: bool
    statement_generation_ok: bool
    compile_ok: bool
    semantic_ok: bool
    proof_ok: bool
    end_to_end_ok: bool
    final_error_type: str | None
    notes: str | None = None
    final_round_index: int = 0
    feedback_loop_used: bool = False
    sub_error_type: str | None = None
    failure_summary: str | None = None
    failure_details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ModelResponse:
    text: str
    raw: Any = None
    usage: dict[str, Any] = field(default_factory=dict)
