from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

HYPOTHESIS_PROVENANCE_ROLES = (
    "problem_fact",
    "coordinate_convention",
    "local_definition",
    "model_instance",
    "explicit_gap_law",
    "target",
    "law_application_equation",
    "algebra_elimination",
    "unknown",
)

HYPOTHESIS_PROVENANCE_SOURCE_TYPES = (
    "problem_text",
    "diagram",
    "problem_ir",
    "model_ir",
    "law_schema",
    "problem_schema",
    "verified_decl",
    "llm_generated",
    "gap",
)

EVIDENCE_BINDING_STATUSES = (
    "ok",
    "gap_schema_only",
    "decl_not_found",
    "signature_mismatch",
    "lean_check_failed",
    "corpus_unavailable",
)

CONTROLLED_SKETCH_STEP_KINDS = (
    "law_to_equation",
    "constraint_to_equation",
)

STATEMENT_GENERATION_MODES = ("legacy_candidate", "minimal_skeleton")
CONTROLLED_SKETCH_STATUSES = ("ok", "blocked_by_evidence_gap", "invalid")
FAILURE_ROUTE_STAGES = ("A2", "EvidenceBinder", "Sketch", "B", "C", "D", "none")


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
class HypothesisProvenance:
    name: str
    lean: str
    role: str
    source_type: str
    allowed_in_hypotheses: bool
    source_id: str | None = None
    notes: str | None = None
    proof_fact_allowed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ModelInterfaceInstantiation:
    instantiation_id: str
    kind: str
    formal_claim: str
    source_model_instance: str | None = None
    interface_name: str | None = None
    parameter_role: str | None = None
    introduced_variable: dict[str, Any] | None = None
    source_type: str = "model_ir"
    modeling_basis: list[str] = field(default_factory=list)
    verified_constructor: str | None = None
    proof_fact_allowed: bool = False
    binding_status: str = "explicit_model_gap"
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class QuantityTypeAnnotation:
    symbol: str
    semantic_role: str = ""
    unit_or_dimension: str = ""
    lean_type: str = "Real"
    confidence: float = 0.0
    evidence_text: str = ""
    reasoning_note: str = ""
    source_type: str = "llm"
    supported: bool = True
    status: str = "ok"
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FunctionFormulaIR:
    formula_id: str = "target_formula_1"
    formula_kind: str = "scalar_relation"
    function_symbol: str = ""
    function_type: str = ""
    allow_time_domain_coercion: bool = False
    bound_variables: list[dict[str, Any]] = field(default_factory=list)
    domain_conditions: list[str] = field(default_factory=list)
    lhs: str = ""
    relation: str = "="
    rhs: str = ""
    lean_formula: str = ""
    source_text: str = ""
    parse_ok: bool = True
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CanonicalTarget:
    target_id: str = "target_1"
    target_kind: str = "unknown_or_ambiguous"
    target_variables: list[str] = field(default_factory=list)
    lean_formula: str = ""
    secondary_formulas: list[str] = field(default_factory=list)
    function_formula_ir: list[FunctionFormulaIR] = field(default_factory=list)
    requires_closed_form: bool = False
    source_text: str = ""
    confidence: float = 0.0
    parse_ok: bool = False
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ModelInstance:
    instance_id: str
    kind: str
    natural_language: str
    entities: list[Any] = field(default_factory=list)
    variables: dict[str, Any] = field(default_factory=dict)
    parameters: dict[str, Any] = field(default_factory=dict)
    coordinate_convention: str | None = None
    planning_schema_id: str | None = None
    expected_claim: str | None = None
    hypothesis_form: str | None = None
    interface_instantiations: list[ModelInterfaceInstantiation] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ModelIR:
    sample_id: str
    objects: list[Any] = field(default_factory=list)
    variables: dict[str, Any] = field(default_factory=dict)
    givens: list[Any] = field(default_factory=list)
    coordinate_system: dict[str, Any] = field(default_factory=dict)
    reference_frame: str | None = None
    local_definitions: list[HypothesisProvenance] = field(default_factory=list)
    model_instances: list[ModelInstance] = field(default_factory=list)
    interface_instantiations: list[ModelInterfaceInstantiation] = field(default_factory=list)
    quantity_annotations: list[QuantityTypeAnnotation] = field(default_factory=list)
    canonical_target: CanonicalTarget | None = None
    target: dict[str, Any] = field(default_factory=dict)
    target_spec: dict[str, Any] = field(default_factory=dict)
    forbidden_as_assumption: list[str] = field(default_factory=list)
    source_problem_ir_hash: str | None = None
    raw_response: str | None = None
    parse_ok: bool = False
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FailureRoute:
    sample_id: str
    round_index: int
    retry_reason: str | None
    start_stage: str
    route_tags: list[str] = field(default_factory=list)
    affected_candidates: list[str] = field(default_factory=list)
    feedback_payload: dict[str, Any] = field(default_factory=dict)
    rerun_downstream_from: str | None = None
    generation_mode: str | None = None
    failed_stage: str | None = None
    responsible_stage: str | None = None
    failure_tags: list[str] = field(default_factory=list)
    failure_summary: str | None = None
    rerun_from_stage: str | None = None
    artifacts_reused: list[str] = field(default_factory=list)
    artifacts_invalidated: list[str] = field(default_factory=list)
    revision_failed_kept_previous: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvidenceBinding:
    binding_id: str
    model_instance_id: str
    planning_schema: str | None = None
    verified_decl: str | None = None
    decl_statement: str | None = None
    decl_status: str | None = None
    trust_level: str | None = None
    callable_by_llm: bool | None = None
    required_imports: list[str] = field(default_factory=list)
    lean_check_pass: bool | None = None
    proof_fact_allowed: bool = False
    binding_status: str = "decl_not_found"
    expected_claim: str | None = None
    slot_order: list[str] = field(default_factory=list)
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ControlledSketchStep:
    step_id: str
    kind: str
    claim: str
    formal_claim: str | None = None
    source_model_instance: str | None = None
    planning_schema: str | None = None
    verified_decl: str | None = None
    binding_status: str | None = None
    expected_claim: str | None = None
    proof_fact_allowed: bool = False
    allowed_solvers: list[str] = field(default_factory=list)
    required_hypotheses: list[str] = field(default_factory=list)
    produces: str | None = None
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AlgebraObligation:
    obligation_id: str
    claim: str
    formal_claim: str
    required_equations: list[str] = field(default_factory=list)
    target_variables: list[str] = field(default_factory=list)
    allowed_solvers: list[str] = field(default_factory=list)
    produces: str | None = None
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BlockedLawStep:
    step_id: str
    source_model_instance: str | None = None
    planning_schema: str | None = None
    expected_claim: str | None = None
    verified_decl: str | None = None
    binding_status: str = "gap_schema_only"
    proof_fact_allowed: bool = False
    required_imports: list[str] = field(default_factory=list)
    reason: str | None = None
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SketchVariant:
    variant_id: str
    baseline_id: str = "canonical"
    variant_policy: str = "verified_only"
    target_form_policy: str = "algebra_obligation"
    hypothesis_policy: str = "minimal_numeric"
    law_policy: str = "all_verified"
    gap_policy: str = "block"
    obligation_policy: str = "law_plus_algebra"
    repair_directives: list[str] = field(default_factory=list)
    proof_steps: list[ControlledSketchStep] = field(default_factory=list)
    algebra_obligation: AlgebraObligation | None = None
    blocked_law_steps: list[BlockedLawStep] = field(default_factory=list)
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "variant_id": self.variant_id,
            "baseline_id": self.baseline_id,
            "variant_policy": self.variant_policy,
            "target_form_policy": self.target_form_policy,
            "hypothesis_policy": self.hypothesis_policy,
            "law_policy": self.law_policy,
            "gap_policy": self.gap_policy,
            "obligation_policy": self.obligation_policy,
            "repair_directives": list(self.repair_directives),
            "proof_steps": [step.to_dict() for step in self.proof_steps],
            "algebra_obligation": self.algebra_obligation.to_dict() if self.algebra_obligation else None,
            "blocked_law_steps": [step.to_dict() for step in self.blocked_law_steps],
            "notes": self.notes,
        }


@dataclass
class ControlledSketch:
    sample_id: str
    schema_version: int = 2
    status: str = "invalid"
    proof_steps: list[ControlledSketchStep] = field(default_factory=list)
    algebra_obligation: AlgebraObligation | None = None
    blocked_law_steps: list[BlockedLawStep] = field(default_factory=list)
    model_interface_instantiations: list[ModelInterfaceInstantiation] = field(default_factory=list)
    sketch_variants: list[SketchVariant] = field(default_factory=list)
    repair_directives: list[str] = field(default_factory=list)
    steps: list[ControlledSketchStep] = field(default_factory=list)
    gap_steps: list[ControlledSketchStep] = field(default_factory=list)
    parse_ok: bool = False
    raw_response: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "sample_id": self.sample_id,
            "schema_version": self.schema_version,
            "status": self.status,
            "proof_steps": [step.to_dict() for step in self.proof_steps],
            "algebra_obligation": self.algebra_obligation.to_dict() if self.algebra_obligation else None,
            "blocked_law_steps": [step.to_dict() for step in self.blocked_law_steps],
            "model_interface_instantiations": [
                item.to_dict() for item in self.model_interface_instantiations
            ],
            "sketch_variants": [variant.to_dict() for variant in self.sketch_variants],
            "repair_directives": list(self.repair_directives),
            "parse_ok": self.parse_ok,
            "raw_response": None if self.schema_version >= 2 and self.parse_ok else self.raw_response,
            "error": self.error,
        }
        if self.schema_version < 2 or self.steps:
            payload["steps"] = [step.to_dict() for step in self.steps]
        if self.schema_version < 2 or self.gap_steps:
            payload["gap_steps"] = [step.to_dict() for step in self.gap_steps]
        return payload


@dataclass
class SketchAuditResult:
    sample_id: str
    audit_pass: bool
    failure_tags: list[str] = field(default_factory=list)
    failure_summary: str | None = None
    target_leakage: bool = False
    candidate_answer_leakage: bool = False
    raw_law_equation_in_hypotheses: bool = False
    algebra_result_in_hypotheses: bool = False
    schema_used_as_proof_fact: bool = False
    unbound_verified_decl: bool = False
    missing_provenance: bool = False
    details: dict[str, Any] = field(default_factory=dict)

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
    supporting_facts: list[str] = field(default_factory=list)
    fact_sources: list[str] = field(default_factory=list)
    library_symbols_used: list[str] = field(default_factory=list)
    grounding_explanation: str | None = None
    unsupported_claims: list[str] = field(default_factory=list)
    verified_decl_refs: list[dict[str, Any]] = field(default_factory=list)
    schema_refs: list[dict[str, Any]] = field(default_factory=list)
    alias_refs: list[dict[str, Any]] = field(default_factory=list)
    grounding_status: str | None = None
    gap_schema_only: bool = False
    parse_ok: bool = False
    raw_response: str = ""
    error: str | None = None
    round_index: int = 0
    source_round_index: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TheoremSkeletonCandidate(StatementCandidate):
    generation_mode: str = "minimal_skeleton"
    grounding_level: str | None = None
    variant_id: str | None = None
    variant_policy: str | None = None
    target_form_policy: str | None = None
    hypothesis_policy: str | None = None
    law_policy: str | None = None
    gap_policy: str | None = None
    obligation_policy: str | None = None
    repair_directives: list[str] = field(default_factory=list)
    hypothesis_provenance: list[HypothesisProvenance] = field(default_factory=list)
    model_ir_digest: str | None = None
    evidence_bindings: list[EvidenceBinding] = field(default_factory=list)
    controlled_sketch: ControlledSketch | None = None
    proof_obligations: list[ControlledSketchStep] = field(default_factory=list)
    controlled_sketch_steps_used: list[str] = field(default_factory=list)
    selected_laws: list[str] = field(default_factory=list)
    verified_decls: list[str] = field(default_factory=list)
    gap_laws: list[dict[str, Any]] = field(default_factory=list)
    fully_mechlib_verified: bool = False
    skeleton_audit: SketchAuditResult | None = None
    typed_binders: list[dict[str, Any]] = field(default_factory=list)
    model_predicate_bindings: list[dict[str, Any]] = field(default_factory=list)
    model_interface_instantiations: list[ModelInterfaceInstantiation] = field(default_factory=list)
    explicit_model_gaps: list[dict[str, Any]] = field(default_factory=list)
    target_spec: dict[str, Any] = field(default_factory=dict)
    excluded_hypotheses: list[dict[str, Any]] = field(default_factory=list)
    generation_blocked_reason: str | None = None
    ignored_llm_theorem_decl: str | None = None
    formula_normalization_trace: list[dict[str, Any]] = field(default_factory=list)


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
    proof_plan: str | None = None
    theorems_to_apply: list[str] = field(default_factory=list)
    givens_to_use: list[str] = field(default_factory=list)
    intermediate_claims: list[str] = field(default_factory=list)
    plan_grounding_ok: bool | None = None
    proof_search_trace: dict[str, Any] | None = None
    proof_action_checks: list[dict[str, Any]] = field(default_factory=list)
    proof_strategy_prompts: list[dict[str, Any]] = field(default_factory=list)
    dependency_audit: dict[str, Any] | None = None
    proof_mode: str | None = None
    fallback_to_legacy_full_proof: bool = False
    fully_mechlib_verified: bool | None = None
    physical_assumption_augmented: bool = False
    added_physical_assumptions: list[dict[str, Any]] = field(default_factory=list)
    augmented_theorem_success: bool = False

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
    proof_mode: str | None = None
    fallback_to_legacy_full_proof: bool = False
    proof_search_trace: dict[str, Any] | None = None
    dependency_audit: dict[str, Any] | None = None
    fully_mechlib_verified: bool | None = None
    physical_assumption_augmented: bool = False
    added_physical_assumptions: list[dict[str, Any]] = field(default_factory=list)
    augmented_theorem_success: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProofObligationReplayItem:
    obligation_id: str
    kind: str
    from_hypothesis: str | None
    must_use: str | None
    formal_claim: str
    produced_fact_name: str
    tactic_block: str | None = None
    replay_status: str = "pending"
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProofActionProposal:
    action_id: str
    strategy: str
    tactic_block: str
    uses_facts: list[str] = field(default_factory=list)
    uses_decls: list[str] = field(default_factory=list)
    expected_effect: str | None = None
    source: str = "llm"
    priority: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProofActionCheckResult:
    action_id: str
    strategy: str
    tactic_block: str
    status: str
    error_type: str | None = None
    error_message: str | None = None
    stderr_excerpt: str | None = None
    goals_excerpt: str | None = None
    error_line: int | None = None
    error_col: int | None = None
    error_snippet: str | None = None
    probe_full_proof_body: str | None = None
    unsolved_goal_count: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProofSearchNode:
    node_id: str
    parent_id: str | None
    depth: int
    proof_prefix: str
    local_facts: list[str] = field(default_factory=list)
    local_fact_claims: list[str] = field(default_factory=list)
    local_fact_types: dict[str, str] = field(default_factory=dict)
    remaining_obligations: list[str] = field(default_factory=list)
    goals_excerpt: str | None = None
    side_condition_denominators: list[str] = field(default_factory=list)
    planned_actions: list[ProofActionProposal] = field(default_factory=list)
    last_action_id: str | None = None
    score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProofSearchTrace:
    sample_id: str
    candidate_id: str
    nodes_expanded: int = 0
    llm_calls: int = 0
    probe_checks: int = 0
    accepted_actions: list[dict[str, Any]] = field(default_factory=list)
    rejected_actions: list[dict[str, Any]] = field(default_factory=list)
    final_proof_body: str | None = None
    search_status: str = "not_started"
    failure_reason: str | None = None
    search_mode: str | None = None
    blocked_obligations: list[dict[str, Any]] = field(default_factory=list)
    search_elapsed_s: float | None = None
    strategy_prompt_summaries: list[dict[str, Any]] = field(default_factory=list)
    physical_assumption_augmented: bool = False
    added_physical_assumptions: list[dict[str, Any]] = field(default_factory=list)
    augmentation_checks: list[dict[str, Any]] = field(default_factory=list)
    base_theorem_decl: str | None = None
    augmented_theorem_decl: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProofDependencyAudit:
    sample_id: str
    candidate_id: str
    proof_success: bool
    used_verified_decls: list[str] = field(default_factory=list)
    required_verified_decls: list[str] = field(default_factory=list)
    missing_required_decls: list[str] = field(default_factory=list)
    covered_obligations: list[str] = field(default_factory=list)
    missing_obligations: list[str] = field(default_factory=list)
    gap_assisted: bool = False
    fully_mechlib_verified: bool = False
    classification: str = "not_checked"
    schema_metadata_in_proof_body: bool = False
    algebra_only: bool = False
    gap_laws_used: bool = False
    physical_assumption_augmented: bool = False
    added_assumptions: list[dict[str, Any]] = field(default_factory=list)
    base_theorem_decl_hash: str | None = None
    augmented_theorem_decl_hash: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SolutionFormula:
    formula_id: str
    formal_formula: str
    display_formula: str | None = None
    source: str | None = None
    verified: bool = False
    provenance: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SolutionStep:
    step_id: str
    kind: str
    title: str
    text_intent: str | None = None
    formal_formula: str | None = None
    display_formula: str | None = None
    input_formulas: list[SolutionFormula] = field(default_factory=list)
    output_formulas: list[SolutionFormula] = field(default_factory=list)
    source_artifacts: list[str] = field(default_factory=list)
    proof_obligation_id: str | None = None
    verified_decl: str | None = None
    proof_action_id: str | None = None
    verified: bool = False
    gap_assisted: bool = False
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SolutionTrace:
    sample_id: str
    candidate_id: str | None
    proof_status: str
    target_formal: str | None
    target_display: str | None
    steps: list[SolutionStep] = field(default_factory=list)
    final_answers: list[SolutionFormula] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    source_status: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SolutionRenderAudit:
    sample_id: str
    candidate_id: str | None
    render_success: bool
    audit_pass: bool
    failure_tags: list[str] = field(default_factory=list)
    failure_summary: str | None = None
    formula_coverage_pass: bool = False
    law_step_coverage_pass: bool = False
    unsupported_formula_count: int = 0
    gap_disclosure_pass: bool = True
    proof_status_disclosure_pass: bool = True
    target_match_pass: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SolutionRenderResult:
    sample_id: str
    candidate_id: str | None
    render_success: bool
    proof_status: str
    solution_trace: SolutionTrace | None
    natural_solution: str | None
    render_audit: SolutionRenderAudit | None
    raw_llm_response: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProofContext:
    sample_id: str
    candidate_id: str
    theorem_decl: str
    lean_header: str
    base_theorem_decl: str | None = None
    target_formula: str | None = None
    local_binders: list[str] = field(default_factory=list)
    local_hypotheses: list[str] = field(default_factory=list)
    typed_binders: list[dict[str, Any]] = field(default_factory=list)
    hypothesis_provenance: list[dict[str, Any]] = field(default_factory=list)
    proof_obligations: list[dict[str, Any]] = field(default_factory=list)
    allowed_verified_decls: list[str] = field(default_factory=list)
    allowed_local_facts: list[str] = field(default_factory=list)
    gap_laws: list[dict[str, Any]] = field(default_factory=list)
    model_predicate_bindings: list[dict[str, Any]] = field(default_factory=list)
    explicit_model_gaps: list[dict[str, Any]] = field(default_factory=list)
    skeleton_mode: bool = False
    obligation_replay_items: list[ProofObligationReplayItem] = field(default_factory=list)
    obligation_replay_blocked: list[ProofObligationReplayItem] = field(default_factory=list)
    mechlib_context_excerpt: str | None = None
    added_physical_assumptions: list[dict[str, Any]] = field(default_factory=list)
    augmentation_status: str | None = None
    augmentation_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DirectFormalizationResult:
    sample_id: str
    lean_header: str
    theorem_decl: str
    proof_body: str
    parse_ok: bool
    raw_response: str
    error: str | None
    plan: str | None = None
    used_facts: list[str] = field(default_factory=list)

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
