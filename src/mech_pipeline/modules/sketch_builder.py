from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from mech_pipeline.knowledge.mechlib_structured import StructuredMechLibContext
from mech_pipeline.prompting import load_template, render_template
from mech_pipeline.prompt_views import (
    compact_candidate_for_feedback,
    compact_controlled_sketch,
    compact_evidence_bindings,
    compact_model_ir,
    compact_problem_ir,
    compact_structured_context,
)
from mech_pipeline.quantity_types import SUPPORTED_SI_QUANTITY_TYPES, is_function_quantity_lean_type
from mech_pipeline.response_parser import ResponseParseError, parse_json_model
from mech_pipeline.types import (
    AlgebraObligation,
    BlockedLawStep,
    ControlledSketch,
    ControlledSketchStep,
    EvidenceBinding,
    ModelIR,
    ModelInterfaceInstantiation,
    SketchVariant,
    StatementCandidate,
)
from mech_pipeline.utils import redact_leakage_text

PROOF_STEP_KINDS = {"law_to_equation", "constraint_to_equation"}
LEGACY_PROOF_KIND_MAP = {
    "law_application": "law_to_equation",
    "constraint_application": "constraint_to_equation",
}
DISCARDED_STEP_KINDS = {
    "definition_expansion",
    "algebra_elimination",
    "target_rewrite",
    "substitution",
    "positivity_or_domain",
}
SOLVER_INTERNAL_NAMES = {
    "h_combined",
    "h_combined_eq",
    "h_nonzero_sum",
    "h_accel_formula",
    "h_a_formula",
    "h_target",
}

DEFAULT_PROMPT = """__TASK_CONTROLLED_SKETCH__
You are a minimal mechanics proof-obligation sketch builder.
Output JSON only.

Goal:
Produce a minimal proof-obligation sketch. Do not write a full natural-language solution.

Hard rules:
1. Do not generate Lean theorem declarations.
2. Do not generate proofs or proof scripts.
3. proof_steps may contain only law_to_equation or constraint_to_equation.
4. proof_steps may use only EvidenceBindings with binding_status=ok, proof_fact_allowed=true, and verified_decl not empty.
5. proof_fact_allowed=false steps must not produce any h_xxx name and must not enter proof_steps.
6. Do not output positivity_or_domain, target_rewrite, definition_expansion, substitution, or intermediate algebra steps.
7. Do not output h_combined, h_nonzero_sum, h_accel_formula, h_target, or other solver-internal intermediate names.
8. If a law/model instance has no verified declaration, put it in blocked_law_steps.
9. If critical law instances are blocked, set status=blocked_by_evidence_gap and proof_steps=[].
10. algebra_obligation is optional and must be at most one final algebra target required by ProblemIR/ModelIR target.
11. Do not include formulas for variables outside the target.
12. model_interface_instantiations may record local modeling equations such as net force or torque composition. They are explicit model gaps, not proof steps.
13. On revision rounds, use Revision feedback and previous artifacts only to revise the minimal sketch. Do not rewrite ModelIR.
14. Never add a verified_decl unless it appears in EvidenceBindings with binding_status=ok and proof_fact_allowed=true.
15. Do not pack multiple propositions into one formal_claim with commas. Use separate proof_steps or a single intentional ∧ proposition.
16. Do not cast numeric Real values into SI quantity types, e.g. never output ((1 : Real) : Speed). Use value-level Real formulas for algebraic obligations.
17. Prefer pointwise formulas with a bound Real chart variable for function-valued quantities. Numeric applications such as v 0 are allowed only when they refer to explicit evaluation givens already present in ModelIR; do not invent them as derived proof steps.

Return this JSON shape:
{
  "status": "ok",
  "proof_steps": [
    {
      "step_id": "sk1",
      "kind": "law_to_equation",
      "claim": "short label only",
      "formal_claim": "s = v * t",
      "source_model_instance": "mi1",
      "planning_schema": "law.kinematics.constant_speed",
      "verified_decl": "MechLib.Kinematics.constant_speed_relation",
      "binding_status": "ok",
      "expected_claim": "s = v * t",
      "proof_fact_allowed": true,
      "required_hypotheses": ["h_v"],
      "produces": "h_law"
    }
  ],
  "algebra_obligation": {
    "obligation_id": "alg_target",
    "claim": "final target algebra only",
    "formal_claim": "s = 30",
    "required_equations": ["h_law", "h_v", "h_t"],
    "target_variables": ["s"],
    "allowed_solvers": ["ring", "linarith", "nlinarith"]
  },
  "blocked_law_steps": [],
  "model_interface_instantiations": []
}

Problem text:
{{problem_text}}

ProblemIR:
{{problem_ir_json}}

ModelIR:
{{model_ir_json}}

EvidenceBindings:
{{evidence_bindings_json}}

Structured MechLib context:
{{structured_context_json}}

Round index:
{{round_index}}

Revision feedback:
{{revision_feedback}}

Previous ControlledSketch:
{{previous_sketch_json}}

Previous B candidates:
{{previous_candidates_json}}
"""


class _BasePayload(BaseModel):
    model_config = ConfigDict(extra="ignore")


class _StepPayload(_BasePayload):
    step_id: str = ""
    kind: str = ""
    claim: str = ""
    formal_claim: str | None = None
    gap_reason: str | None = None
    model_instance_id: str | None = None
    source_model_instance: str | None = None
    planning_schema: str | None = None
    verified_decl: str | None = None
    binding_status: str | None = None
    expected_claim: str | None = None
    proof_fact_allowed: bool = False
    allowed_solvers: list[str] = Field(default_factory=list)
    required_hypotheses: list[str] = Field(default_factory=list)
    produces: str | None = None
    notes: str | None = None


class _AlgebraPayload(_BasePayload):
    obligation_id: str = ""
    claim: str = ""
    formal_claim: str = ""
    required_equations: list[str] = Field(default_factory=list)
    target_variables: list[str] = Field(default_factory=list)
    allowed_solvers: list[str] = Field(default_factory=list)
    produces: str | None = None
    notes: str | None = None


class _BlockedPayload(_BasePayload):
    step_id: str = ""
    source_model_instance: str | None = None
    model_instance_id: str | None = None
    planning_schema: str | None = None
    expected_claim: str | None = None
    verified_decl: str | None = None
    binding_status: str = "gap_schema_only"
    proof_fact_allowed: bool = False
    required_imports: list[str] = Field(default_factory=list)
    reason: str | None = None
    notes: str | None = None


class _InterfaceInstantiationPayload(_BasePayload):
    instantiation_id: str = ""
    kind: str = ""
    formal_claim: str = ""
    source_model_instance: str | None = None
    interface_name: str | None = None
    parameter_role: str | None = None
    introduced_variable: dict[str, Any] | None = None
    source_type: str = "model_ir"
    modeling_basis: list[str] = Field(default_factory=list)
    verified_constructor: str | None = None
    proof_fact_allowed: bool = False
    binding_status: str = "explicit_model_gap"
    notes: str | None = None


class _SketchPayload(_BasePayload):
    status: str = ""
    proof_steps: list[_StepPayload] = Field(default_factory=list)
    algebra_obligation: _AlgebraPayload | None = None
    blocked_law_steps: list[_BlockedPayload] = Field(default_factory=list)
    model_interface_instantiations: list[_InterfaceInstantiationPayload] = Field(default_factory=list)
    steps: list[_StepPayload] = Field(default_factory=list)
    gap_steps: list[_StepPayload] = Field(default_factory=list)


def _context_payload(context: StructuredMechLibContext | dict[str, Any] | None) -> dict[str, Any]:
    if context is None:
        return {}
    if isinstance(context, StructuredMechLibContext):
        return context.to_dict()
    return context


def _candidate_payload(candidate: StatementCandidate) -> dict[str, Any]:
    return compact_candidate_for_feedback(candidate)


def _feedback_repair_directives(revision_feedback: str | None) -> list[str]:
    text = str(revision_feedback or "").strip()
    if not text or text == "(none)":
        return []
    directives: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        if value and value not in seen:
            seen.add(value)
            directives.append(value)

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    retry_reason = str(payload.get("retry_reason") or "").strip()
    if retry_reason == "no_compile_pass":
        add("compile_oriented")
    elif retry_reason == "semantic_fail":
        add("semantic_repair")

    candidates = payload.get("candidates")
    if isinstance(candidates, list):
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            generation_blocked = str(candidate.get("generation_blocked_reason") or "").strip()
            if generation_blocked:
                add(generation_blocked)
                if generation_blocked == "missing_typed_target_formula":
                    add("target_missing")
            unsupported = candidate.get("unsupported_claims")
            unsupported_text = json.dumps(unsupported, ensure_ascii=False) if isinstance(unsupported, (list, dict)) else str(unsupported or "")
            lower_unsupported = unsupported_text.lower()
            if "missing_typed_target_formula" in lower_unsupported:
                add("target_missing")
            if "duplicate_skeleton_shape" in lower_unsupported:
                add("avoid_duplicate_shape")
            if "candidate_count_below_requested" in lower_unsupported:
                add("increase_variant_diversity")
            if "unknown" in str(candidate.get("error_type") or "").lower() or "unknown" in str(candidate.get("stderr_digest") or "").lower():
                add("compile_oriented")
            failure_text = " ".join(
                str(candidate.get(key) or "")
                for key in ("semantic_sub_error_type", "semantic_failure_tags", "mismatch_fields", "hard_gate_reasons")
            ).lower()
            if "target" in failure_text:
                add("target_repair")
            if "law" in failure_text:
                add("law_selection_repair")
    return directives


def _variant_algebra_for_policy(
    baseline: ControlledSketch,
    target_form_policy: str,
) -> AlgebraObligation | None:
    if target_form_policy in {"proof_obligation_conjunction", "law_only"}:
        return None
    return baseline.algebra_obligation


def _build_sketch_variants(
    baseline: ControlledSketch,
    *,
    repair_directives: list[str],
) -> list[SketchVariant]:
    proof_steps = list(baseline.proof_steps)
    blocked_steps = list(baseline.blocked_law_steps)
    target_missing = "target_missing" in repair_directives or "missing_typed_target_formula" in repair_directives
    compile_oriented = "compile_oriented" in repair_directives
    variants = [
        SketchVariant(
            variant_id="v1_verified_only",
            variant_policy="verified_only",
            target_form_policy="forbidden_target" if target_missing else "algebra_obligation",
            hypothesis_policy="minimal_numeric",
            law_policy="all_verified",
            gap_policy="block",
            obligation_policy="law_plus_algebra",
            repair_directives=list(repair_directives),
            proof_steps=proof_steps,
            algebra_obligation=_variant_algebra_for_policy(
                baseline,
                "forbidden_target" if target_missing else "algebra_obligation",
            ),
            blocked_law_steps=blocked_steps,
            notes="Canonical verified-only baseline variant.",
        ),
        SketchVariant(
            variant_id="v2_explicit_gap_allowed",
            variant_policy="explicit_gap_allowed",
            target_form_policy="forbidden_target" if target_missing else "algebra_obligation",
            hypothesis_policy="numeric_plus_explicit_gaps",
            law_policy="verified_plus_gap",
            gap_policy="explicit_gap_law",
            obligation_policy="law_plus_algebra",
            repair_directives=list(repair_directives),
            proof_steps=proof_steps,
            algebra_obligation=_variant_algebra_for_policy(
                baseline,
                "forbidden_target" if target_missing else "algebra_obligation",
            ),
            blocked_law_steps=blocked_steps,
            notes="Allows audited explicit model gaps when configured by B.",
        ),
        SketchVariant(
            variant_id="v3_implicit_relation",
            variant_policy="implicit_relation",
            target_form_policy="proof_obligation_conjunction",
            hypothesis_policy="minimal_numeric",
            law_policy="all_verified",
            gap_policy="block",
            obligation_policy="law_only",
            repair_directives=list(repair_directives),
            proof_steps=proof_steps,
            algebra_obligation=None,
            blocked_law_steps=blocked_steps,
            notes="States the verified relation obligations as the target when final target form is unstable.",
        ),
        SketchVariant(
            variant_id="v4_compile_oriented",
            variant_policy="compile_oriented",
            target_form_policy="model_target_then_forbidden" if compile_oriented or target_missing else "model_target",
            hypothesis_policy="minimal_numeric",
            law_policy="first_verified",
            gap_policy="block",
            obligation_policy="law_only" if compile_oriented else "law_plus_algebra",
            repair_directives=list(repair_directives),
            proof_steps=proof_steps[:1] if proof_steps else [],
            algebra_obligation=None if compile_oriented else baseline.algebra_obligation,
            blocked_law_steps=blocked_steps,
            notes="Minimal compile-oriented variant used on feedback rounds.",
        ),
    ]
    return variants


def _clean(text: object) -> str:
    return " ".join(str(text or "").strip().split())


def _compact(text: object) -> str:
    return re.sub(r"\s+", "", str(text or "").strip().lower())


def _target_symbols(model_ir: ModelIR, problem_ir: dict[str, Any] | None) -> set[str]:
    out: set[str] = set()
    target = model_ir.target or {}
    if isinstance(target, dict):
        for key in ("symbol", "name"):
            value = str(target.get(key) or "").strip()
            if value and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_']*", value):
                out.add(value)
        for key in ("variables", "target_variables", "symbols"):
            value = target.get(key)
            if isinstance(value, list):
                for item in value:
                    token = str(item or "").strip()
                    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_']*", token):
                        out.add(token)
        for key in ("components", "component_symbols"):
            value = target.get(key)
            if isinstance(value, list):
                for item in value:
                    token = str(item or "").strip()
                    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_']*", token):
                        out.add(token)
        lean = str(target.get("lean") or "").strip()
        lhs = lean.split("=", 1)[0].strip() if "=" in lean else ""
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_']*", lhs):
            out.add(lhs)
    unknown = (problem_ir or {}).get("unknown_target")
    if isinstance(unknown, dict):
        value = str(unknown.get("symbol") or "").strip()
        if value and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_']*", value):
            out.add(value)
        extra = unknown.get("extra_targets")
        if isinstance(extra, list):
            for item in extra:
                if isinstance(item, dict):
                    token = str(item.get("symbol") or "").strip()
                    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_']*", token):
                        out.add(token)
    return out


def _mentions_target(formal_claim: str, target_symbols: set[str]) -> bool:
    if not target_symbols:
        return True
    tokens = set(re.findall(r"[A-Za-z_][A-Za-z0-9_']*", formal_claim or ""))
    return bool(tokens.intersection(target_symbols))


def _has_top_level_comma(text: object) -> bool:
    value = str(text or "")
    depth = 0
    for idx, char in enumerate(value):
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            prefix = value[:idx].strip()
            if prefix.startswith(("forall ", "∀")) and not any(
                marker in prefix for marker in ("=", "≠", "<", ">", "≤", "≥", "\\le", "\\ge", "∧", "∨")
            ):
                continue
            return True
    return False


def _contains_illegal_si_cast(text: object) -> bool:
    value = _clean(text)
    if not value:
        return False
    quantity_type_pattern = "|".join(re.escape(name) for name in sorted(SUPPORTED_SI_QUANTITY_TYPES, key=len, reverse=True))
    if not quantity_type_pattern:
        return False
    return bool(
        re.search(
            rf":\s*Real[^\n,;]*\)\s*:\s*(?:MechLib\.SI\.)?(?:{quantity_type_pattern})\s*\)",
            value,
        )
    )


def _function_symbols(model_ir: ModelIR) -> set[str]:
    return {
        item.symbol
        for item in getattr(model_ir, "quantity_annotations", []) or []
        if item.symbol and is_function_quantity_lean_type(item.lean_type)
    }


def _contains_numeric_function_application(text: object, function_symbols: set[str]) -> bool:
    if not function_symbols:
        return False
    value = _clean(text)
    for symbol in function_symbols:
        if re.search(rf"\b{re.escape(symbol)}\s+[-+]?(?:\d+(?:\.\d+)?|\(\s*\d+(?:\.\d+)?\s*:\s*Real\s*\))\b", value):
            return True
    return False


def _is_lean_like_formula(text: object) -> bool:
    value = _clean(text)
    if not value:
        return False
    lower = value.lower()
    if any(marker in lower for marker in (" from ", " using ", " obtain ", " gives ", " derive ", " because ")):
        return False
    if len(value.split()) > 18:
        return False
    if _has_top_level_comma(value):
        return False
    if _contains_illegal_si_cast(value):
        return False
    return any(token in value for token in ("=", "≠", "<", ">", "≤", "≥", "\\le", "\\ge", "∧", "∨"))


def _candidate_formal_claim(payload: _StepPayload) -> str:
    for value in (payload.formal_claim, payload.expected_claim, payload.claim):
        text = _clean(value)
        if _is_lean_like_formula(text):
            return text
    return ""


def _binding_maps(bindings: list[EvidenceBinding]) -> dict[str, EvidenceBinding]:
    by_instance: dict[str, EvidenceBinding] = {}
    for binding in bindings:
        if binding.binding_status == "ok" and binding.proof_fact_allowed and binding.verified_decl:
            by_instance.setdefault(binding.model_instance_id, binding)
    return by_instance


def _first_binding_by_instance(bindings: list[EvidenceBinding]) -> dict[str, EvidenceBinding]:
    by_instance: dict[str, EvidenceBinding] = {}
    for binding in bindings:
        by_instance.setdefault(binding.model_instance_id, binding)
    return by_instance


def _interface_instantiation_from_payload(
    payload: _InterfaceInstantiationPayload,
    index: int,
) -> ModelInterfaceInstantiation | None:
    formal_claim = _clean(payload.formal_claim)
    if not formal_claim:
        return None
    return ModelInterfaceInstantiation(
        instantiation_id=_clean(payload.instantiation_id) or f"mii{index}",
        kind=_clean(payload.kind) or "model_interface_instantiation",
        formal_claim=formal_claim,
        source_model_instance=_clean(payload.source_model_instance) or None,
        interface_name=_clean(payload.interface_name) or None,
        parameter_role=_clean(payload.parameter_role) or None,
        introduced_variable=dict(payload.introduced_variable or {}) or None,
        source_type=_clean(payload.source_type) or "model_ir",
        modeling_basis=[str(item) for item in payload.modeling_basis],
        verified_constructor=_clean(payload.verified_constructor) or None,
        proof_fact_allowed=bool(payload.proof_fact_allowed),
        binding_status=_clean(payload.binding_status) or "explicit_model_gap",
        notes=_clean(payload.notes) or None,
    )


def _instance_expected_claims(model_ir: ModelIR) -> dict[str, str]:
    return {
        instance.instance_id: str(instance.expected_claim or "").strip()
        for instance in model_ir.model_instances
        if instance.instance_id
    }


def _instance_planning_schemas(model_ir: ModelIR) -> dict[str, str]:
    return {
        instance.instance_id: str(instance.planning_schema_id or "").strip()
        for instance in model_ir.model_instances
        if instance.instance_id and str(instance.planning_schema_id or "").strip()
    }


class SketchCanonicalizer:
    def __init__(
        self,
        *,
        sample_id: str,
        model_ir: ModelIR,
        evidence_bindings: list[EvidenceBinding],
        problem_ir: dict[str, Any] | None = None,
    ) -> None:
        self.sample_id = sample_id
        self.model_ir = model_ir
        self.problem_ir = problem_ir or {}
        self.eligible_bindings = _binding_maps(evidence_bindings)
        self.first_bindings = _first_binding_by_instance(evidence_bindings)
        self.expected_claims = _instance_expected_claims(model_ir)
        self.planning_schemas = _instance_planning_schemas(model_ir)
        self.target_symbols = _target_symbols(model_ir, problem_ir)
        self.function_symbols = _function_symbols(model_ir)
        self._blocked_by_instance: dict[str, BlockedLawStep] = {}
        self._blocked_produces: set[str] = set()

    def _is_valid_proof_formula(self, text: object) -> bool:
        return _is_lean_like_formula(text)

    def canonicalize(self, payload: _SketchPayload, raw_response: str | None = None) -> ControlledSketch:
        proof_steps: list[ControlledSketchStep] = []
        old_step_payloads = [*payload.proof_steps, *payload.steps]
        for index, step_payload in enumerate(old_step_payloads, start=1):
            step = self._canonical_step(step_payload, index)
            if step is not None:
                proof_steps.append(step)
        proof_steps = self._add_missing_verified_steps(proof_steps)

        for index, blocked_payload in enumerate(payload.blocked_law_steps, start=1):
            self._record_blocked_payload(blocked_payload, index)
        for index, gap_payload in enumerate(payload.gap_steps, start=1):
            self._record_gap_payload(gap_payload, index)
        for instance_id, expected_claim in self.expected_claims.items():
            if instance_id not in self.eligible_bindings and instance_id not in self._blocked_by_instance:
                self._record_blocked_instance(
                    instance_id=instance_id,
                    step_id=f"blocked_{len(self._blocked_by_instance) + 1}",
                    expected_claim=expected_claim,
                    reason="No proof-eligible verified declaration is bound to this model instance.",
                )

        algebra_obligation = self._canonical_algebra(payload, proof_steps)
        if self._blocked_by_instance and not proof_steps:
            algebra_obligation = None
        status = "ok"
        if self._blocked_by_instance and not proof_steps:
            status = "blocked_by_evidence_gap"
        if algebra_obligation is None and self._algebra_depends_on_blocked(payload):
            status = "blocked_by_evidence_gap"
        return ControlledSketch(
            sample_id=self.sample_id,
            schema_version=2,
            status=status,
            proof_steps=proof_steps,
            algebra_obligation=algebra_obligation,
            blocked_law_steps=list(self._blocked_by_instance.values()),
            model_interface_instantiations=self._canonical_interface_instantiations(payload),
            parse_ok=True,
            raw_response=raw_response,
        )

    def _canonical_interface_instantiations(self, payload: _SketchPayload) -> list[ModelInterfaceInstantiation]:
        out: list[ModelInterfaceInstantiation] = []
        seen: set[str] = set()

        def add(item: ModelInterfaceInstantiation | None) -> None:
            if item is None:
                return
            key = f"{item.instantiation_id}:{item.source_model_instance}:{item.formal_claim}"
            if key in seen:
                return
            seen.add(key)
            out.append(item)

        for item in getattr(self.model_ir, "interface_instantiations", []) or []:
            add(item if isinstance(item, ModelInterfaceInstantiation) else None)
        for instance in self.model_ir.model_instances:
            for item in getattr(instance, "interface_instantiations", []) or []:
                if isinstance(item, ModelInterfaceInstantiation) and not item.source_model_instance:
                    item.source_model_instance = instance.instance_id
                add(item if isinstance(item, ModelInterfaceInstantiation) else None)
        for index, item in enumerate(payload.model_interface_instantiations, start=1):
            add(_interface_instantiation_from_payload(item, index))
        return out

    def _add_missing_verified_steps(self, proof_steps: list[ControlledSketchStep]) -> list[ControlledSketchStep]:
        produced_instances = {step.source_model_instance for step in proof_steps if step.source_model_instance}
        out = list(proof_steps)
        for instance_id, binding in self.eligible_bindings.items():
            if instance_id in produced_instances:
                continue
            formal_claim = _clean(binding.expected_claim) or self.expected_claims.get(instance_id, "")
            if not self._is_valid_proof_formula(formal_claim):
                self._record_blocked_instance(
                    instance_id=instance_id,
                    step_id=f"blocked_{len(self._blocked_by_instance) + 1}",
                    expected_claim=formal_claim,
                    reason="Proof-eligible binding does not provide a single valid Lean-like expected_claim.",
                )
                continue
            planning_schema = binding.planning_schema or self.planning_schemas.get(instance_id)
            lower = " ".join([instance_id, str(planning_schema or ""), str(binding.expected_claim or "")]).lower()
            kind = "constraint_to_equation" if "constraint" in lower else "law_to_equation"
            step_id = f"sk_{instance_id}"
            out.append(
                ControlledSketchStep(
                    step_id=step_id,
                    kind=kind,
                    claim=formal_claim,
                    formal_claim=formal_claim,
                    source_model_instance=instance_id,
                    planning_schema=planning_schema,
                    verified_decl=binding.verified_decl,
                    binding_status="ok",
                    expected_claim=formal_claim,
                    proof_fact_allowed=True,
                    required_hypotheses=[],
                    produces=f"h_{instance_id}",
                    notes="Synthesized from proof-eligible EvidenceBinding because the LLM sketch omitted a minimal formal step.",
                )
            )
        return out

    def _canonical_step(self, payload: _StepPayload, index: int) -> ControlledSketchStep | None:
        raw_kind = _clean(payload.kind)
        if raw_kind in DISCARDED_STEP_KINDS:
            if payload.produces:
                self._blocked_produces.add(str(payload.produces))
            return None
        kind = LEGACY_PROOF_KIND_MAP.get(raw_kind, raw_kind)
        if kind not in PROOF_STEP_KINDS:
            return None
        source_model_instance = _clean(payload.source_model_instance or payload.model_instance_id) or None
        if not source_model_instance:
            return None
        binding = self.eligible_bindings.get(source_model_instance)
        if binding is None:
            self._record_blocked_instance(
                instance_id=source_model_instance,
                step_id=payload.step_id or f"blocked_{index}",
                expected_claim=payload.expected_claim or self.expected_claims.get(source_model_instance),
                reason="Step has no proof-eligible verified declaration.",
                produces=payload.produces,
            )
            return None
        formal_claim = _candidate_formal_claim(payload)
        if not formal_claim or not self._is_valid_proof_formula(formal_claim):
            binding_claim = _clean(binding.expected_claim) or self.expected_claims.get(source_model_instance, "")
            if not self._is_valid_proof_formula(binding_claim):
                self._record_blocked_instance(
                    instance_id=source_model_instance,
                    step_id=payload.step_id or f"blocked_{index}",
                    expected_claim=payload.expected_claim or self.expected_claims.get(source_model_instance),
                    reason="Proof step formal_claim is not a single valid Lean-like formula.",
                    produces=payload.produces,
                )
            return None
        produces = _clean(payload.produces) or f"h_{payload.step_id or index}"
        if produces in SOLVER_INTERNAL_NAMES:
            return None
        return ControlledSketchStep(
            step_id=_clean(payload.step_id) or f"sk{index}",
            kind=kind,
            claim=_clean(payload.claim) or formal_claim,
            formal_claim=formal_claim,
            source_model_instance=source_model_instance,
            planning_schema=_clean(payload.planning_schema) or binding.planning_schema,
            verified_decl=binding.verified_decl,
            binding_status="ok",
            expected_claim=_clean(payload.expected_claim) or binding.expected_claim,
            proof_fact_allowed=True,
            allowed_solvers=[str(x) for x in payload.allowed_solvers],
            required_hypotheses=[str(x) for x in payload.required_hypotheses],
            produces=produces,
            notes=payload.notes,
        )

    def _record_blocked_instance(
        self,
        *,
        instance_id: str,
        step_id: str,
        expected_claim: str | None,
        reason: str,
        produces: str | None = None,
    ) -> None:
        if produces:
            self._blocked_produces.add(produces)
        if instance_id in self._blocked_by_instance:
            return
        binding = self.first_bindings.get(instance_id)
        binding_status = (binding.binding_status if binding else "gap_schema_only") or "gap_schema_only"
        if binding is not None and binding.binding_status == "ok" and binding.proof_fact_allowed and binding.verified_decl:
            binding_status = "verified_decl_uninstantiated"
        self._blocked_by_instance[instance_id] = BlockedLawStep(
            step_id=step_id,
            source_model_instance=instance_id,
            planning_schema=(binding.planning_schema if binding else None) or self.planning_schemas.get(instance_id),
            expected_claim=expected_claim or (binding.expected_claim if binding else None),
            verified_decl=binding.verified_decl if binding else None,
            binding_status=binding_status,
            proof_fact_allowed=False,
            required_imports=list(binding.required_imports) if binding else [],
            reason=reason,
            notes=binding.notes if binding else None,
        )

    def _record_blocked_payload(self, payload: _BlockedPayload, index: int) -> None:
        instance_id = _clean(payload.source_model_instance or payload.model_instance_id)
        if not instance_id:
            return
        if instance_id in self.eligible_bindings:
            return
        self._record_blocked_instance(
            instance_id=instance_id,
            step_id=_clean(payload.step_id) or f"blocked_{index}",
            expected_claim=payload.expected_claim,
            reason=payload.reason or payload.notes or "Blocked law step has no proof-eligible verified declaration.",
        )

    def _record_gap_payload(self, payload: _StepPayload, index: int) -> None:
        instance_id = _clean(payload.source_model_instance or payload.model_instance_id)
        if not instance_id:
            remaining = [key for key in self.expected_claims if key not in self.eligible_bindings]
            instance_id = remaining[0] if remaining else ""
        if not instance_id:
            return
        if instance_id in self.eligible_bindings:
            return
        self._record_blocked_instance(
            instance_id=instance_id,
            step_id=_clean(payload.step_id) or f"blocked_gap_{index}",
            expected_claim=payload.expected_claim or self.expected_claims.get(instance_id),
            reason=payload.gap_reason or payload.notes or "Gap step has no proof-eligible verified declaration.",
            produces=payload.produces,
        )

    def _legacy_algebra_payloads(self, payload: _SketchPayload) -> list[_StepPayload]:
        return [
            step
            for step in payload.steps
            if _clean(step.kind) in {"algebra_elimination", "target_rewrite", "substitution"}
        ]

    def _known_required_equation_names(self, proof_steps: list[ControlledSketchStep]) -> set[str]:
        names: set[str] = set()
        for step in proof_steps:
            if step.step_id:
                names.add(step.step_id)
            if step.produces:
                names.add(step.produces)
        for hyp in [*self.model_ir.givens, *self.model_ir.local_definitions]:
            name = getattr(hyp, "name", None)
            if name:
                names.add(str(name))
            elif isinstance(hyp, dict) and hyp.get("name"):
                names.add(str(hyp["name"]))
        return names

    def _normalize_required_equations(
        self,
        required_equations: list[str],
        proof_steps: list[ControlledSketchStep],
    ) -> list[str] | None:
        if any(str(req) in self._blocked_produces for req in required_equations):
            return None
        known = self._known_required_equation_names(proof_steps)
        out: list[str] = []
        seen: set[str] = set()
        for raw in required_equations:
            req = str(raw or "").strip()
            if not req or req in SOLVER_INTERNAL_NAMES:
                continue
            if req.startswith("h_") and req not in known:
                continue
            if req not in seen:
                seen.add(req)
                out.append(req)
        return out

    def _canonical_algebra(self, payload: _SketchPayload, proof_steps: list[ControlledSketchStep]) -> AlgebraObligation | None:
        if payload.algebra_obligation is not None:
            algebra = payload.algebra_obligation
            formal_claim = _clean(algebra.formal_claim)
            if not self._is_valid_proof_formula(formal_claim) or not _mentions_target(formal_claim, self.target_symbols):
                return None
            required = self._normalize_required_equations(
                [str(x) for x in algebra.required_equations],
                proof_steps,
            )
            if required is None:
                return None
            return AlgebraObligation(
                obligation_id=_clean(algebra.obligation_id) or "alg_target",
                claim=_clean(algebra.claim) or formal_claim,
                formal_claim=formal_claim,
                required_equations=required,
                target_variables=[str(x) for x in algebra.target_variables] or sorted(self.target_symbols),
                allowed_solvers=[str(x) for x in algebra.allowed_solvers],
                produces=algebra.produces,
                notes=algebra.notes,
            )
        for step in reversed(self._legacy_algebra_payloads(payload)):
            formal_claim = _candidate_formal_claim(step)
            if not formal_claim or not self._is_valid_proof_formula(formal_claim) or not _mentions_target(formal_claim, self.target_symbols):
                continue
            required = [str(x) for x in step.required_hypotheses]
            normalized_required = self._normalize_required_equations(required, proof_steps)
            if normalized_required is None:
                return None
            return AlgebraObligation(
                obligation_id=_clean(step.step_id) or "alg_target",
                claim=_clean(step.claim) or formal_claim,
                formal_claim=formal_claim,
                required_equations=normalized_required,
                target_variables=sorted(self.target_symbols),
                allowed_solvers=[str(x) for x in step.allowed_solvers],
                produces=step.produces,
                notes=step.notes,
            )
        return None

    def _algebra_depends_on_blocked(self, payload: _SketchPayload) -> bool:
        if payload.algebra_obligation is not None:
            return any(req in self._blocked_produces for req in payload.algebra_obligation.required_equations)
        for step in self._legacy_algebra_payloads(payload):
            if any(str(req) in self._blocked_produces for req in step.required_hypotheses):
                return True
        return False


class ModuleControlledSketch:
    def __init__(self, model_client, prompt_path: Path) -> None:
        self.model_client = model_client
        self.template = load_template(prompt_path, DEFAULT_PROMPT)

    def run(
        self,
        *,
        sample_id: str,
        problem_text: str,
        problem_ir: dict[str, Any] | None,
        model_ir: ModelIR,
        evidence_bindings: list[EvidenceBinding],
        structured_mechlib_context: StructuredMechLibContext | dict[str, Any] | None,
        revision_feedback: str = "(none)",
        previous_sketch: ControlledSketch | None = None,
        previous_candidates: list[StatementCandidate] | None = None,
        round_index: int = 0,
    ) -> ControlledSketch:
        prompt = render_template(
            self.template,
            {
                "problem_text": redact_leakage_text(problem_text or ""),
                "problem_ir_json": json.dumps(compact_problem_ir(problem_ir), ensure_ascii=False, indent=2),
                "model_ir_json": json.dumps(compact_model_ir(model_ir), ensure_ascii=False, indent=2),
                "evidence_bindings_json": json.dumps(
                    compact_evidence_bindings(evidence_bindings),
                    ensure_ascii=False,
                    indent=2,
                ),
                "structured_context_json": json.dumps(
                    compact_structured_context(_context_payload(structured_mechlib_context)),
                    ensure_ascii=False,
                    indent=2,
                ),
                "round_index": str(round_index),
                "revision_feedback": revision_feedback or "(none)",
                "previous_sketch_json": json.dumps(
                    compact_controlled_sketch(previous_sketch) if previous_sketch is not None else {},
                    ensure_ascii=False,
                    indent=2,
                ),
                "previous_candidates_json": json.dumps(
                    [_candidate_payload(candidate) for candidate in (previous_candidates or [])],
                    ensure_ascii=False,
                    indent=2,
                ),
            },
        )

        raw = ""
        try:
            raw = self.model_client.generate_text(prompt).text
        except Exception as exc:
            return ControlledSketch(
                sample_id=sample_id,
                schema_version=2,
                status="invalid",
                parse_ok=False,
                raw_response=raw,
                error=f"controlled_sketch_generation_exception:{type(exc).__name__}: {exc}",
            )

        try:
            parsed = parse_json_model(raw, _SketchPayload)
        except ResponseParseError as exc:
            return ControlledSketch(
                sample_id=sample_id,
                schema_version=2,
                status="invalid",
                parse_ok=False,
                raw_response=raw,
                error=f"controlled_sketch_parse_failed:{exc}",
            )

        sketch = SketchCanonicalizer(
            sample_id=sample_id,
            model_ir=model_ir,
            evidence_bindings=evidence_bindings,
            problem_ir=problem_ir,
        ).canonicalize(parsed, raw_response=raw)
        if parsed.status in {"blocked_by_evidence_gap", "invalid"} and sketch.status == "ok" and not sketch.proof_steps:
            sketch.status = parsed.status
        repair_directives = _feedback_repair_directives(revision_feedback)
        sketch.repair_directives = repair_directives
        sketch.sketch_variants = _build_sketch_variants(sketch, repair_directives=repair_directives)
        return sketch


def controlled_sketch_stage_row(sample_id: str, sketch: ControlledSketch, round_index: int | None = None) -> dict[str, Any]:
    row = {"sample_id": sample_id, **sketch.to_dict()}
    if round_index is not None:
        row["round_index"] = round_index
    return row
