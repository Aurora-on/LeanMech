from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from mech_pipeline.knowledge.mechlib_structured import StructuredMechLibContext
from mech_pipeline.prompting import load_template, render_template
from mech_pipeline.prompt_views import compact_problem_ir, compact_structured_context
from mech_pipeline.quantity_types import (
    SUPPORTED_SI_QUANTITY_TYPES,
    is_function_quantity_lean_type,
    normalize_quantity_lean_type,
)
from mech_pipeline.response_parser import ResponseParseError, parse_json_model
from mech_pipeline.types import (
    CanonicalTarget,
    FunctionFormulaIR,
    HypothesisProvenance,
    ModelIR,
    ModelInstance,
    ModelInterfaceInstantiation,
    QuantityTypeAnnotation,
)
from mech_pipeline.utils import is_tautological_equality, normalize_lean_text, redact_leakage_text

DEFAULT_PROMPT = """__TASK_A2_BUILD_MODEL_IR__
You are a controlled mechanics ModelIR builder.
Output JSON only.

Rules:
1. Do not generate Lean theorem declarations.
2. Do not generate proofs or proof scripts.
3. Do not treat law-application results, derived relations, algebra elimination results, or final answers as givens.
4. Separate facts into: given_fact, model_instance, local_definition, coordinate_convention, target, derived_relation.
5. For each model instance, provide kind, natural_language, expected_claim, planning_schema_hint, entities, variables, parameters, and confidence.
6. Use interface_instantiations for local modeling interfaces such as net force, effective torque, constraint velocity, or sign convention equations.
7. interface_instantiations must use Lean-like value-level equations, e.g. Fnet = T or Fnet = m * g - T; do not use fake MechLib names.
8. The target may contain the requested final formula if the problem asks for one, but it must stay in target/forbidden_as_assumption, never in givens.
9. If unsure, lower confidence and leave planning_schema_hint empty. Do not invent verified declarations.
10. forbidden_as_assumption must include the target/goal and any derived or algebraic result that should not be assumed.
11. For every variable, output quantity_annotations using the problem statement, units, and definitions. Do not infer from symbol spelling alone.
12. Use only existing MechLib.SI quantity types. For angles use PhysAngle, not Angle. If no existing SI type fits, use Real with low confidence and explain why.
13. If a quantity is a scalar function of time, prefer MechLib's native Real-time fields: MechLib.Mechanics.Kinematics.ScalarTrajectory for position/length, MechLib.Mechanics.Kinematics.ScalarVelocityField for speed, and MechLib.Mechanics.Kinematics.ScalarAccelerationField for acceleration. For other time-dependent quantities, use Real -> <QuantityType>, not Time -> <QuantityType>. Do not put .val in bound-variable names.
14. Output exactly one canonical_target. It is the only target B may use. It may be a closed-form equation, a pointwise function relation, a derivative/ODE relation, a component relation, or a property; do not force a closed form unless the problem asks for one.
15. If the problem asks for multiple required outputs, put the primary requested formula in canonical_target.lean_formula and the other required formulas in canonical_target.secondary_formulas. Do not drop requested outputs.
16. Never use no-information tautologies such as x = x, v t = v t, a.val = a.val, or forall t, f t = f t as target or modeling equations.
17. For function-valued targets, also fill canonical_target.function_formula_ir. B will trust this structure rather than infer function semantics from strings.
18. Use target_kind values: closed_form, closed_form_value, relation, component_relation, pointwise_function_relation, derivative_relation, ode_relation, existence_or_property, unknown_or_ambiguous. Use formula_kind values: scalar_relation, pointwise_relation, evaluation_relation, derivative_relation, ode_relation, component_relation, property. If the function target cannot be expressed in Lean-like first-order syntax, set parse_ok=false and explain error.
19. Do not pack multiple propositions into one field with commas. Use separate givens/local_definitions/model_instances, or use ∧ only when it is intentionally one proposition. If expected_claim is explanatory natural language, keep formal equations in interface_instantiations instead of mixing prose and final derived formulas.
20. Do not cast numeric Real values into SI quantity types, e.g. never output ((1 : Real) : Speed) or ((1 : Real) : Acceleration). Ordinary algebraic formulas should stay value-level.
21. For function-valued targets, prefer a Real chart time variable in function_formula_ir, e.g. t0 : Real. Numeric evaluation facts such as v 0 = v0 are allowed only when they are explicit givens/local definitions from the problem; B will normalize them to value-level pointwise form.
22. Every formula involving a function-valued quantity must be pointwise. For x : MechLib.Mechanics.Kinematics.ScalarTrajectory, write forall t0 : Real, (x t0).val = ...; for M : PhysAngle -> Torque, write forall phi0 : PhysAngle, (M phi0).val = .... Never write x = ..., M = 4 * phi, v_rope = R * omega, or omega * R unless both function quantities are applied to the same bound variable.
23. Mathlib/MechLib does not provide Real.atan2 in the current pipeline. If a direction angle would require atan2, either express it through component relations such as cos/sin constraints or set canonical_target.parse_ok=false with a clear error. Do not output Real.atan2.
24. If the problem gives an angle in degrees, make that explicit in quantity_annotations.unit_or_dimension/evidence_text and use radians at value level, e.g. beta.val = 30 * Real.pi / 180, not beta.val = 30.

Return this JSON shape:
{
  "objects": [],
  "variables": {},
  "quantity_annotations": [
    {
      "symbol": "m",
      "semantic_role": "mass of the block",
      "unit_or_dimension": "kg",
      "lean_type": "Mass",
      "confidence": 0.95,
      "evidence_text": "the problem states mass m",
      "reasoning_note": "kg identifies mass"
    }
  ],
  "canonical_target": {
    "target_id": "target_1",
    "target_kind": "closed_form | closed_form_value | relation | component_relation | pointwise_function_relation | derivative_relation | ode_relation | existence_or_property | unknown_or_ambiguous",
    "target_variables": ["a"],
    "lean_formula": "a = (m2 * g) / (m1 + m2)",
    "secondary_formulas": [],
    "function_formula_ir": [
      {
        "formula_id": "target_formula_1",
        "formula_kind": "scalar_relation",
        "function_symbol": "",
        "function_type": "",
        "allow_time_domain_coercion": false,
        "bound_variables": [],
        "domain_conditions": [],
        "lhs": "a",
        "relation": "=",
        "rhs": "(m2 * g) / (m1 + m2)",
        "lean_formula": "a = (m2 * g) / (m1 + m2)",
        "source_text": "problem asks for acceleration",
        "parse_ok": true,
        "error": null
      }
    ],
    "requires_closed_form": false,
    "source_text": "problem asks for the acceleration",
    "confidence": 0.85,
    "parse_ok": true,
    "error": null
  },
  "givens": [{"name":"...", "lean":"...", "role":"given_fact", "source_type":"problem_ir", "source_id":"...", "allowed_in_hypotheses":true, "notes":""}],
  "coordinate_system": {},
  "reference_frame": "",
  "local_definitions": [],
  "model_instances": [
    {
      "instance_id":"mi1",
      "kind":"...",
      "natural_language":"...",
      "entities":[],
      "variables":{},
      "parameters":{},
      "coordinate_convention":"",
      "planning_schema_hint":"",
      "expected_claim":"",
      "hypothesis_form":"",
      "interface_instantiations": [
        {
          "instantiation_id": "net_force_mi1",
          "kind": "net_force_balance",
          "formal_claim": "Fnet = T",
          "source_model_instance": "mi1",
          "interface_name": "net_force",
          "introduced_variable": {"name": "Fnet", "lean_type": "Force"},
          "binding_status": "explicit_model_gap",
          "proof_fact_allowed": false,
          "notes": "Local modeling interface; not a verified MechLib declaration."
        }
      ],
      "provenance":{},
      "confidence":0.0
    }
  ],
  "interface_instantiations": [],
  "target": {},
  "target_spec": {},
  "forbidden_as_assumption": []
}

Problem text:
{{problem_text}}

ProblemIR:
{{problem_ir_json}}

Structured MechLib context:
{{structured_context_json}}

Image description:
{{image_description}}

Supported MechLib.SI quantity types:
{{supported_si_quantity_types}}

Revision feedback:
{{revision_feedback}}
"""

ROLE_MAP = {
    "given_fact": "problem_fact",
    "problem_fact": "problem_fact",
    "model_instance": "model_instance",
    "local_definition": "local_definition",
    "coordinate_convention": "coordinate_convention",
    "target": "target",
    "derived_relation": "algebra_elimination",
    "law_application_equation": "law_application_equation",
    "algebra_elimination": "algebra_elimination",
}


class _BasePayload(BaseModel):
    model_config = ConfigDict(extra="ignore")


class _ProvenancePayload(_BasePayload):
    name: str = ""
    lean: str = ""
    role: str = "unknown"
    source_type: str = "problem_ir"
    source_id: str | None = None
    allowed_in_hypotheses: bool = False
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


class _QuantityAnnotationPayload(_BasePayload):
    symbol: str = ""
    semantic_role: str = ""
    unit_or_dimension: str = ""
    lean_type: str = "Real"
    confidence: float = 0.0
    evidence_text: str = ""
    reasoning_note: str = ""
    source_type: str = "llm"
    notes: str | None = None


class _FunctionFormulaPayload(_BasePayload):
    formula_id: str = ""
    formula_kind: str = "scalar_relation"
    function_symbol: str = ""
    function_type: str = ""
    allow_time_domain_coercion: bool = False
    bound_variables: list[dict[str, Any]] = Field(default_factory=list)
    domain_conditions: list[str] = Field(default_factory=list)
    lhs: str = ""
    relation: str = "="
    rhs: str = ""
    lean_formula: str = ""
    source_text: str = ""
    parse_ok: bool = True
    error: str | None = None


class _CanonicalTargetPayload(_BasePayload):
    target_id: str = "target_1"
    target_kind: str = "unknown_or_ambiguous"
    target_variables: list[str] = Field(default_factory=list)
    lean_formula: str = ""
    secondary_formulas: list[str] = Field(default_factory=list)
    function_formula_ir: list[_FunctionFormulaPayload] = Field(default_factory=list)
    requires_closed_form: bool = False
    source_text: str = ""
    confidence: float = 0.0
    parse_ok: bool = False
    error: str | None = None


class _ModelInstancePayload(_BasePayload):
    instance_id: str = ""
    kind: str = ""
    natural_language: str = ""
    entities: list[Any] = Field(default_factory=list)
    variables: dict[str, Any] = Field(default_factory=dict)
    parameters: dict[str, Any] = Field(default_factory=dict)
    coordinate_convention: str | None = None
    planning_schema_id: str | None = None
    planning_schema_hint: str | None = None
    expected_claim: str | None = None
    hypothesis_form: str | None = None
    interface_instantiations: list[_InterfaceInstantiationPayload] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 0.0


class _ModelIRPayload(_BasePayload):
    objects: list[Any] = Field(default_factory=list)
    variables: dict[str, Any] = Field(default_factory=dict)
    quantity_annotations: list[_QuantityAnnotationPayload] = Field(default_factory=list)
    canonical_target: _CanonicalTargetPayload | None = None
    givens: list[_ProvenancePayload] = Field(default_factory=list)
    coordinate_system: dict[str, Any] = Field(default_factory=dict)
    reference_frame: str | None = None
    local_definitions: list[_ProvenancePayload] = Field(default_factory=list)
    model_instances: list[_ModelInstancePayload] = Field(default_factory=list)
    interface_instantiations: list[_InterfaceInstantiationPayload] = Field(default_factory=list)
    target: dict[str, Any] = Field(default_factory=dict)
    target_spec: dict[str, Any] = Field(default_factory=dict)
    forbidden_as_assumption: list[Any] = Field(default_factory=list)


def _problem_ir_hash(problem_ir: dict[str, Any] | None) -> str:
    payload = json.dumps(problem_ir or {}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _context_payload(context: StructuredMechLibContext | dict[str, Any] | None) -> dict[str, Any]:
    if context is None:
        return {}
    if isinstance(context, StructuredMechLibContext):
        return context.to_dict()
    return context


def _normalize_role(value: str) -> str:
    return ROLE_MAP.get((value or "").strip(), "unknown")


def _provenance_from_payload(payload: _ProvenancePayload) -> HypothesisProvenance:
    return HypothesisProvenance(
        name=payload.name,
        lean=_normalize_packed_formula_text(payload.lean),
        role=_normalize_role(payload.role),
        source_type=payload.source_type or "problem_ir",
        source_id=payload.source_id,
        allowed_in_hypotheses=bool(payload.allowed_in_hypotheses),
        notes=payload.notes,
    )


def _interface_instantiation_from_payload(
    payload: _InterfaceInstantiationPayload,
    index: int,
    source_instance: str | None = None,
) -> ModelInterfaceInstantiation:
    source_model_instance = (payload.source_model_instance or source_instance or "").strip() or None
    return ModelInterfaceInstantiation(
        instantiation_id=payload.instantiation_id.strip() or f"mii{index}",
        kind=payload.kind.strip() or "model_interface_instantiation",
        formal_claim=_normalize_packed_formula_text(payload.formal_claim),
        source_model_instance=source_model_instance,
        interface_name=(payload.interface_name or "").strip() or None,
        parameter_role=(payload.parameter_role or "").strip() or None,
        introduced_variable=dict(payload.introduced_variable or {}) or None,
        source_type=payload.source_type.strip() or "model_ir",
        modeling_basis=[str(item) for item in payload.modeling_basis],
        verified_constructor=(payload.verified_constructor or "").strip() or None,
        proof_fact_allowed=bool(payload.proof_fact_allowed),
        binding_status=payload.binding_status.strip() or "explicit_model_gap",
        notes=(payload.notes or "").strip() or None,
    )


def _quantity_annotation_from_payload(payload: _QuantityAnnotationPayload) -> QuantityTypeAnnotation | None:
    symbol = payload.symbol.strip()
    if not symbol:
        return None
    lean_type, supported, status = normalize_quantity_lean_type(payload.lean_type)
    confidence = max(0.0, min(1.0, float(payload.confidence)))
    notes = (payload.notes or "").strip() or None
    if status == "unsupported_si_type":
        notes = (
            f"Unsupported MechLib.SI quantity type requested: {payload.lean_type}. "
            "B must not generate this Lean type."
        )
    elif status == "unresolved":
        notes = notes or "Quantity type unresolved by A2; B should use Real."
    return QuantityTypeAnnotation(
        symbol=symbol,
        semantic_role=payload.semantic_role.strip(),
        unit_or_dimension=payload.unit_or_dimension.strip(),
        lean_type=lean_type,
        confidence=confidence,
        evidence_text=payload.evidence_text.strip(),
        reasoning_note=payload.reasoning_note.strip(),
        source_type=payload.source_type.strip() or "llm",
        supported=supported,
        status=status,
        notes=notes,
    )


TARGET_KINDS = {
    "closed_form",
    "closed_form_value",
    "relation",
    "component_relation",
    "pointwise_function_relation",
    "derivative_relation",
    "ode_relation",
    "existence_or_property",
    "unknown_or_ambiguous",
}
FUNCTION_TARGET_KINDS = {"pointwise_function_relation", "derivative_relation", "ode_relation"}

FUNCTION_FORMULA_KINDS = {
    "scalar_relation",
    "pointwise_relation",
    "evaluation_relation",
    "derivative_relation",
    "ode_relation",
    "component_relation",
    "property",
    "unknown",
}


INFORMAL_DERIVATIVE_PLACEHOLDER_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9]*_(?:dot|ddot)\b")


def _contains_informal_derivative_placeholder(text: object) -> bool:
    return bool(INFORMAL_DERIVATIVE_PLACEHOLDER_RE.search(str(text or "")))


def _has_formula_marker(text: object) -> bool:
    raw = str(text or "")
    return any(token in raw for token in ("=", "≠", "<", ">", "≤", "≥", "\\le", "\\ge", "∧", "∨", "forall", "∀", "Exists", "∃"))


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
            if "∫" in prefix or re.search(r"\b(?:integral|Integral)\b", prefix):
                continue
            return True
    return False


def _split_top_level_commas(text: object) -> list[str]:
    value = str(text or "")
    parts: list[str] = []
    start = 0
    depth = 0
    for idx, char in enumerate(value):
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            prefix = value[start:idx].strip()
            if prefix.startswith(("forall ", "∀")) and not any(
                marker in prefix for marker in ("=", "≠", "<", ">", "≤", "≥", "\\le", "\\ge", "∧", "∨")
            ):
                continue
            if "∫" in prefix or re.search(r"\b(?:integral|Integral)\b", prefix):
                continue
            parts.append(value[start:idx].strip())
            start = idx + 1
    parts.append(value[start:].strip())
    return [part for part in parts if part]


NATURAL_LANGUAGE_FORMULA_MARKERS = (
    " satisfies ",
    " hence ",
    " therefore ",
    " because ",
    " given ",
    " asked ",
    " requested ",
    " final ",
    " target ",
    " should ",
    " must ",
    " where ",
)


def _looks_like_symbolic_formula_segment(text: object) -> bool:
    value = normalize_lean_text(str(text or "")).strip()
    if not value or not _has_formula_marker(value):
        return False
    lowered = f" {value.lower()} "
    if any(marker in lowered for marker in NATURAL_LANGUAGE_FORMULA_MARKERS):
        return False
    lhs = re.split(r"=|≠|<|>|≤|≥|\\le|\\ge", value, maxsplit=1)[0]
    lhs_tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_']*", lhs)
    if len(lhs_tokens) >= 3 and not lhs.strip().startswith(("forall ", "∀", "Exists", "∃")):
        return False
    return True


def _normalize_packed_formula_text(text: object) -> str:
    value = normalize_lean_text(str(text or "")).strip()
    if not value or not _has_top_level_comma(value):
        return value
    parts = _split_top_level_commas(value)
    if len(parts) <= 1:
        return value
    if all(_looks_like_symbolic_formula_segment(part) for part in parts):
        return " ∧ ".join(parts)
    return value


def _contains_illegal_si_cast(text: object) -> bool:
    value = normalize_lean_text(str(text or ""))
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


def _function_symbols(quantity_annotations: list[QuantityTypeAnnotation]) -> set[str]:
    return {
        item.symbol
        for item in quantity_annotations
        if item.symbol and is_function_quantity_lean_type(item.lean_type)
    }


def _contains_numeric_function_application(text: object, function_symbols: set[str]) -> bool:
    if not function_symbols:
        return False
    value = normalize_lean_text(str(text or ""))
    for symbol in function_symbols:
        if re.search(rf"\b{re.escape(symbol)}\s+[-+]?(?:\d+(?:\.\d+)?|\(\s*\d+(?:\.\d+)?\s*:\s*Real\s*\))\b", value):
            return True
    return False


def _contains_bare_function_quantity_formula(text: object, function_symbols: set[str]) -> bool:
    if not function_symbols:
        return False
    value = normalize_lean_text(str(text or "")).strip()
    if not value or not _has_formula_marker(value):
        return False
    if not _looks_like_symbolic_formula_segment(value) and not value.lstrip().startswith(("forall ", "∀", "Exists", "∃")):
        return False
    for symbol in sorted(function_symbols, key=len, reverse=True):
        pattern = re.compile(rf"(?<![A-Za-z0-9_.]){re.escape(symbol)}(?![A-Za-z0-9_'])")
        for match in pattern.finditer(value):
            before = value[: match.start()]
            after = value[match.end() :]
            if re.search(r"(?:forall|∀|fun)\s*$", before):
                continue
            if re.match(r"\s*=\s*fun\b", after):
                continue
            if re.match(r"\s+(?:[-+]?\d|[A-Za-z_][A-Za-z0-9_']*|\([^)]*\)|⟨[^⟩]*⟩)", after):
                continue
            return True
    return False


def _model_ir_formula_contract_error(
    label: str,
    value: object,
    *,
    function_symbols: set[str],
    allow_top_level_comma: bool = False,
) -> str | None:
    text = _normalize_packed_formula_text(value)
    if not text:
        return None
    if _contains_informal_derivative_placeholder(text):
        return f"model_ir_informal_derivative_placeholder:{label}"
    if (
        not allow_top_level_comma
        and _has_formula_marker(text)
        and _has_top_level_comma(text)
        and _looks_like_symbolic_formula_segment(text)
    ):
        return f"model_ir_multi_formula_field:{label}"
    if _contains_illegal_si_cast(text):
        return f"model_ir_illegal_si_cast:{label}"
    if _contains_bare_function_quantity_formula(text, function_symbols):
        return f"model_ir_function_quantity_not_pointwise:{label}"
    return None


def _drop_invalid_local_definitions(model_ir: ModelIR) -> list[str]:
    function_symbols = _function_symbols(model_ir.quantity_annotations)
    kept: list[HypothesisProvenance] = []
    dropped: list[str] = []
    for item in model_ir.local_definitions:
        error = _model_ir_formula_contract_error(
            f"local_definitions.{item.name or 'unnamed'}",
            item.lean,
            function_symbols=function_symbols,
        )
        if error:
            dropped.append(error)
            continue
        kept.append(item)
    if dropped:
        model_ir.local_definitions = kept
    return dropped


def _can_drop_invalid_modeling_formula(error: str | None) -> bool:
    if not error:
        return False
    # Illegal SI casts usually indicate that a typed quantity and a Real term
    # were conflated. Keep those as hard failures so B does not receive a
    # misleading typed model. Other model-instance/interface planning formulas
    # are auxiliary evidence for later stages; if one is malformed, drop that
    # auxiliary claim and keep a valid canonical target moving downstream.
    return not error.startswith("model_ir_illegal_si_cast:")


def _drop_invalid_modeling_formula_fields(model_ir: ModelIR) -> list[str]:
    function_symbols = _function_symbols(model_ir.quantity_annotations)
    dropped: list[str] = []

    kept_top_level_interfaces: list[ModelInterfaceInstantiation] = []
    for item in model_ir.interface_instantiations:
        error = _model_ir_formula_contract_error(
            f"interface_instantiations.{item.instantiation_id}",
            item.formal_claim,
            function_symbols=function_symbols,
        )
        if error and _can_drop_invalid_modeling_formula(error):
            dropped.append(error)
            continue
        kept_top_level_interfaces.append(item)
    model_ir.interface_instantiations = kept_top_level_interfaces

    for instance in model_ir.model_instances:
        error = _model_ir_formula_contract_error(
            f"model_instances.{instance.instance_id}.expected_claim",
            instance.expected_claim,
            function_symbols=function_symbols,
        )
        if error and _can_drop_invalid_modeling_formula(error):
            dropped.append(error)
            instance.expected_claim = None

        kept_instance_interfaces: list[ModelInterfaceInstantiation] = []
        for item in instance.interface_instantiations:
            error = _model_ir_formula_contract_error(
                f"model_instances.{instance.instance_id}.interface_instantiations.{item.instantiation_id}",
                item.formal_claim,
                function_symbols=function_symbols,
            )
            if error and _can_drop_invalid_modeling_formula(error):
                dropped.append(error)
                continue
            kept_instance_interfaces.append(item)
        instance.interface_instantiations = kept_instance_interfaces

    return dropped


def _collect_model_ir_contract_error(model_ir: ModelIR) -> str | None:
    function_symbols = _function_symbols(model_ir.quantity_annotations)
    for collection_name, candidates in (
        ("variables", list((model_ir.variables or {}).keys()) if isinstance(model_ir.variables, dict) else []),
        ("quantity_annotations", [item.symbol for item in model_ir.quantity_annotations]),
    ):
        for item in candidates:
            if _contains_informal_derivative_placeholder(item):
                return f"model_ir_informal_derivative_placeholder:{collection_name}.{item}"

    for collection_name, items in (
        ("givens", model_ir.givens),
        ("local_definitions", model_ir.local_definitions),
    ):
        for item in items:
            error = _model_ir_formula_contract_error(
                f"{collection_name}.{item.name or 'unnamed'}",
                item.lean,
                function_symbols=function_symbols,
            )
            if error:
                return error
    for item in model_ir.interface_instantiations:
        error = _model_ir_formula_contract_error(
            f"interface_instantiations.{item.instantiation_id}",
            item.formal_claim,
            function_symbols=function_symbols,
        )
        if error:
            return error
    for instance in model_ir.model_instances:
        error = _model_ir_formula_contract_error(
            f"model_instances.{instance.instance_id}.expected_claim",
            instance.expected_claim,
            function_symbols=function_symbols,
        )
        if error:
            return error
        for item in instance.interface_instantiations:
            error = _model_ir_formula_contract_error(
                f"model_instances.{instance.instance_id}.interface_instantiations.{item.instantiation_id}",
                item.formal_claim,
                function_symbols=function_symbols,
            )
            if error:
                return error
    target = model_ir.canonical_target
    if target is not None:
        for label, value in (
            ("canonical_target.lean_formula", target.lean_formula),
            *(
                (f"canonical_target.secondary_formulas.{index}", formula)
                for index, formula in enumerate(target.secondary_formulas, start=1)
            ),
        ):
            error = _model_ir_formula_contract_error(
                label,
                value,
                function_symbols=function_symbols,
                allow_top_level_comma=False,
            )
            if error:
                return error
        for item in target.function_formula_ir:
            if item.parse_ok is False:
                continue
            for label, value in (
                (f"canonical_target.function_formula_ir.{item.formula_id or 'unnamed'}.lhs", item.lhs),
                (f"canonical_target.function_formula_ir.{item.formula_id or 'unnamed'}.rhs", item.rhs),
                (f"canonical_target.function_formula_ir.{item.formula_id or 'unnamed'}.lean_formula", item.lean_formula),
            ):
                error = _model_ir_formula_contract_error(
                    label,
                    value,
                    function_symbols=function_symbols,
                )
                if error:
                    return error
    return None


def _target_variables_from_formula(formula: str) -> list[str]:
    variables: list[str] = []
    seen: set[str] = set()
    for part in re.split(r"\s*(?:∧|\\land|\band\b)\s*", formula or ""):
        lhs = part.split("=", 1)[0].strip() if "=" in part else part.strip()
        match = re.match(r"\(?\s*([A-Za-z_][A-Za-z0-9_']*)", lhs)
        if not match:
            continue
        token = match.group(1)
        if token in {"forall", "fun", "Exists"} or token in seen:
            continue
        seen.add(token)
        variables.append(token)
    return variables


def _target_variables_from_payloads(*payloads: object) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()

    def add(value: object) -> None:
        text = str(value or "").strip()
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_']*", text) and text not in seen:
            seen.add(text)
            out.append(text)

    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        for key in ("symbol", "name", "target_variable", "variable"):
            add(payload.get(key))
        for key in ("variables", "target_variables", "symbols", "component_symbols"):
            value = payload.get(key)
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        add(item.get("symbol") or item.get("name") or item.get("variable"))
                    else:
                        add(item)
    return out


def _rewrite_real_time_bound_variable_text(text: object, real_time_names: set[str]) -> str:
    value = normalize_lean_text(str(text or "")).strip()
    if not value or not real_time_names:
        return value
    for name in sorted(real_time_names, key=len, reverse=True):
        escaped = re.escape(name)
        value = re.sub(rf"\b{escaped}\.val\b", name, value)
        value = re.sub(rf"(\b(?:forall|∀)\s+{escaped}\s*:\s*)Time\b", r"\1Real", value)
        value = re.sub(rf"(\bfun\s+{escaped}\s*:\s*)Time\b", r"\1Real", value)
    return value


def _normalize_function_bound_variables(raw_items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], set[str]]:
    normalized_items: list[dict[str, Any]] = []
    real_time_names: set[str] = set()
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        name = str(row.get("name") or row.get("symbol") or row.get("variable") or "").strip()
        requested = str(row.get("lean_type") or row.get("type") or row.get("domain") or "").strip()
        lean_type, supported, _status = normalize_quantity_lean_type(requested or "Real")
        if supported and lean_type == "Time":
            row["lean_type"] = "Real"
            for key in ("type", "domain"):
                if key in row:
                    row[key] = "Real"
            if name:
                real_time_names.add(name)
        elif supported and requested:
            row["lean_type"] = lean_type
        normalized_items.append(row)
    return normalized_items, real_time_names


def _function_formula_from_payload(payload: _FunctionFormulaPayload, index: int) -> FunctionFormulaIR:
    formula_kind = payload.formula_kind.strip() or "unknown"
    if formula_kind not in FUNCTION_FORMULA_KINDS:
        formula_kind = "unknown"
    relation = payload.relation.strip() or "="
    if relation not in {"=", "≠", "<", ">", "≤", "≥", "\\le", "\\ge"}:
        relation = "="
    bound_variables, real_time_names = _normalize_function_bound_variables(
        [dict(item) for item in payload.bound_variables if isinstance(item, dict)]
    )
    lean_formula = _normalize_packed_formula_text(
        _rewrite_real_time_bound_variable_text(payload.lean_formula, real_time_names)
    )
    lhs = _normalize_packed_formula_text(_rewrite_real_time_bound_variable_text(payload.lhs, real_time_names))
    rhs = _normalize_packed_formula_text(_rewrite_real_time_bound_variable_text(payload.rhs, real_time_names))
    if not lean_formula and lhs and rhs:
        lean_formula = f"{lhs} {relation} {rhs}"
    tautological = bool(lean_formula and is_tautological_equality(lean_formula))
    parse_ok = bool(payload.parse_ok and lean_formula and not tautological)
    error = (payload.error or None) if not parse_ok else None
    if tautological:
        error = "tautological_function_formula"
    return FunctionFormulaIR(
        formula_id=payload.formula_id.strip() or f"target_formula_{index}",
        formula_kind=formula_kind,
        function_symbol=payload.function_symbol.strip(),
        function_type=payload.function_type.strip(),
        allow_time_domain_coercion=bool(payload.allow_time_domain_coercion),
        bound_variables=bound_variables,
        domain_conditions=[
            _rewrite_real_time_bound_variable_text(item, real_time_names)
            for item in payload.domain_conditions
            if str(item or "").strip()
        ],
        lhs=lhs,
        relation=relation,
        rhs=rhs,
        lean_formula=lean_formula,
        source_text=payload.source_text.strip(),
        parse_ok=parse_ok,
        error=error,
    )


FORMULA_SCALAR_KEYS = (
    "lean_formula",
    "lean",
    "formal_claim",
    "formula",
    "target_form",
    "expected_formula",
    "requested_formula",
    "typed_target_formula",
    "primary_goal",
    "secondary_goal",
)

FORMULA_LIST_KEYS = (
    "secondary_formulas",
    "required_secondary_formulas",
    "formal_targets",
    "targets",
    "target_formulas",
    "expected_formulas",
    "requested_formula_candidates",
    "primary_target_formulas",
    "component_targets",
    "components",
)


def _formula_candidates_from_payload(payload: object) -> list[str]:
    if not isinstance(payload, dict):
        return []
    formulas: list[str] = []
    for key in FORMULA_SCALAR_KEYS:
        text = _normalize_packed_formula_text(payload.get(key))
        if text and _has_formula_marker(text):
            formulas.append(text)
    for key in FORMULA_LIST_KEYS:
        value = payload.get(key)
        if not isinstance(value, list):
            continue
        for item in value:
            if isinstance(item, dict):
                nested = _formula_candidates_from_payload(item)
            else:
                text = _normalize_packed_formula_text(item)
                nested = [text] if text and _has_formula_marker(text) else []
            formulas.extend(nested)
    out: list[str] = []
    seen: set[str] = set()
    for formula in formulas:
        key = re.sub(r"\s+", "", formula)
        if not formula or key in seen:
            continue
        seen.add(key)
        out.append(formula)
    return out


def _first_formula_from_payload(payload: object) -> str:
    formulas = _formula_candidates_from_payload(payload)
    if formulas:
        return " ∧ ".join(formulas) if len(formulas) > 1 else formulas[0]
    return ""


def _secondary_formulas_from_payloads(primary_formula: str, *payloads: object) -> list[str]:
    primary_key = re.sub(r"\s+", "", primary_formula or "")
    out: list[str] = []
    seen: set[str] = {primary_key} if primary_key else set()
    for payload in payloads:
        for formula in _formula_candidates_from_payload(payload):
            key = re.sub(r"\s+", "", formula)
            if not key or key in seen or is_tautological_equality(formula):
                continue
            seen.add(key)
            out.append(formula)
    return out


def _first_formula_from_forbidden(items: list[str], target_variables: list[str]) -> str:
    target_set = set(target_variables)
    for item in items:
        text = normalize_lean_text(str(item or "")).strip()
        if not text or not _has_formula_marker(text):
            continue
        if " as " in text:
            text = text.split(" as ", 1)[0].strip()
        lhs = text.split("=", 1)[0].strip() if "=" in text else text
        lhs_token = re.match(r"([A-Za-z_][A-Za-z0-9_']*)", lhs)
        if target_set and lhs_token and lhs_token.group(1) not in target_set:
            continue
        return text
    return ""


def _canonical_target_from_payload(
    payload: _CanonicalTargetPayload | None,
    *,
    target: dict[str, Any],
    target_spec: dict[str, Any],
    problem_ir: dict[str, Any] | None,
    forbidden_as_assumption: list[str],
) -> CanonicalTarget:
    if payload is not None:
        target_kind = payload.target_kind.strip() or "unknown_or_ambiguous"
        if target_kind not in TARGET_KINDS:
            target_kind = "unknown_or_ambiguous"
        formula = _normalize_packed_formula_text(payload.lean_formula)
        function_formula_ir = [
            _function_formula_from_payload(item, index)
            for index, item in enumerate(payload.function_formula_ir, start=1)
        ]
        real_time_bound_names = {
            str(bound.get("name") or bound.get("symbol") or bound.get("variable") or "").strip()
            for row in function_formula_ir
            for bound in row.bound_variables
            if str(bound.get("lean_type") or bound.get("type") or bound.get("domain") or "").strip() == "Real"
        }
        formula = _rewrite_real_time_bound_variable_text(formula, {name for name in real_time_bound_names if name})
        secondary_formulas = _secondary_formulas_from_payloads(
            formula,
            {"secondary_formulas": list(payload.secondary_formulas)},
            target_spec,
            target,
        )
        tautological_target = bool(formula and is_tautological_equality(formula))
        bad_function_formula = next((item for item in function_formula_ir if not item.parse_ok), None)
        function_target_requires_valid_ir = target_kind in FUNCTION_TARGET_KINDS or any(
            item.formula_kind in {"pointwise_relation", "derivative_relation", "ode_relation"}
            for item in function_formula_ir
        )
        parse_ok = bool(
            payload.parse_ok
            and formula
            and not tautological_target
            and (bad_function_formula is None or not function_target_requires_valid_ir)
        )
        error = (payload.error or None) if not parse_ok else None
        if tautological_target:
            error = "tautological_canonical_target"
        elif bad_function_formula is not None and function_target_requires_valid_ir:
            error = bad_function_formula.error or "invalid_function_formula_ir"
        return CanonicalTarget(
            target_id=payload.target_id.strip() or "target_1",
            target_kind=target_kind,
            target_variables=[str(item).strip() for item in payload.target_variables if str(item).strip()],
            lean_formula=formula,
            secondary_formulas=secondary_formulas,
            function_formula_ir=function_formula_ir,
            requires_closed_form=bool(payload.requires_closed_form),
            source_text=payload.source_text.strip(),
            confidence=max(0.0, min(1.0, float(payload.confidence))),
            parse_ok=parse_ok,
            error=error,
        )

    ir = problem_ir or {}
    unknown_target = ir.get("unknown_target") if isinstance(ir.get("unknown_target"), dict) else {}
    variables = _target_variables_from_payloads(target, target_spec, unknown_target)
    candidates: list[str] = []
    for payload_obj in (target_spec, target, unknown_target):
        candidates.extend(_formula_candidates_from_payload(payload_obj))
    forbidden_formula = _first_formula_from_forbidden(forbidden_as_assumption, variables)
    if forbidden_formula:
        candidates.append(forbidden_formula)
    formula = ""
    secondary_formulas: list[str] = []
    saw_tautology = False
    seen_formula_keys: set[str] = set()
    for candidate in candidates:
        candidate = normalize_lean_text(candidate).strip()
        if not candidate:
            continue
        key = re.sub(r"\s+", "", candidate)
        if key in seen_formula_keys:
            continue
        seen_formula_keys.add(key)
        if is_tautological_equality(candidate):
            saw_tautology = True
            continue
        if not formula:
            formula = candidate
        else:
            secondary_formulas.append(candidate)
    if formula and not variables:
        variables = _target_variables_from_formula(formula)
    source_text = " ".join(
        str(value).strip()
        for value in (
            target.get("description") if isinstance(target, dict) else "",
            target_spec.get("description") if isinstance(target_spec, dict) else "",
            unknown_target.get("description") if isinstance(unknown_target, dict) else "",
            ir.get("goal_statement"),
        )
        if str(value or "").strip()
    )
    if formula:
        kind = "component_relation" if "∧" in formula or "\\land" in formula else "relation"
        if any(marker in source_text.lower() for marker in ("find", "determine", "calculate", "solve for")):
            kind = "closed_form" if "=" in formula else kind
        return CanonicalTarget(
            target_id="target_1",
            target_kind=kind,
            target_variables=variables,
            lean_formula=formula,
            secondary_formulas=secondary_formulas,
            function_formula_ir=[],
            requires_closed_form=kind == "closed_form",
            source_text=source_text,
            confidence=0.55,
            parse_ok=True,
            error=None,
        )
    if saw_tautology:
        return CanonicalTarget(
            target_id="target_1",
            target_kind="unknown_or_ambiguous",
            target_variables=variables,
            lean_formula="",
            secondary_formulas=[],
            function_formula_ir=[],
            requires_closed_form=False,
            source_text=source_text,
            confidence=0.0,
            parse_ok=False,
            error="tautological_canonical_target",
        )
    return CanonicalTarget(
        target_id="target_1",
        target_kind="unknown_or_ambiguous",
        target_variables=variables,
        lean_formula="",
        secondary_formulas=[],
        function_formula_ir=[],
        requires_closed_form=False,
        source_text=source_text,
        confidence=0.0,
        parse_ok=False,
        error="missing_canonical_target_formula",
    )


def _model_instance_from_payload(payload: _ModelInstancePayload, index: int) -> ModelInstance:
    instance_id = payload.instance_id.strip() or f"mi{index}"
    return ModelInstance(
        instance_id=instance_id,
        kind=payload.kind.strip(),
        natural_language=payload.natural_language.strip(),
        entities=list(payload.entities),
        variables=dict(payload.variables),
        parameters=dict(payload.parameters),
        coordinate_convention=payload.coordinate_convention,
        planning_schema_id=(payload.planning_schema_id or payload.planning_schema_hint or None),
        expected_claim=_normalize_packed_formula_text(payload.expected_claim),
        hypothesis_form=payload.hypothesis_form,
        interface_instantiations=[
            _interface_instantiation_from_payload(item, sub_index, source_instance=instance_id)
            for sub_index, item in enumerate(payload.interface_instantiations, start=1)
            if item.formal_claim.strip()
        ],
        provenance=dict(payload.provenance),
        confidence=float(payload.confidence),
    )


def _forbidden_item_to_text(item: Any) -> str:
    if item is None:
        return ""
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, (int, float, bool)):
        return str(item).strip()
    if isinstance(item, dict):
        ordered_keys = (
            "name",
            "lean",
            "claim",
            "expected_claim",
            "description",
            "statement",
            "notes",
            "reason",
            "role",
            "source_id",
        )
        parts: list[str] = []
        for key in ordered_keys:
            value = item.get(key)
            if value is None:
                continue
            text = _forbidden_item_to_text(value)
            if text:
                parts.append(text)
        if not parts:
            for key, value in sorted(item.items(), key=lambda pair: str(pair[0])):
                text = _forbidden_item_to_text(value)
                if text:
                    parts.append(f"{key}: {text}")
        return " | ".join(parts).strip()
    if isinstance(item, list):
        return " | ".join(text for text in (_forbidden_item_to_text(value) for value in item) if text).strip()
    return str(item).strip()


def _normalize_forbidden_as_assumption(items: list[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = _forbidden_item_to_text(item)
        if not text:
            continue
        key = " ".join(text.lower().split())
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _contains_forbidden_lean_artifact(payload: dict[str, Any]) -> bool:
    text = json.dumps(payload, ensure_ascii=False).lower()
    return "theorem " in text or ":= by" in text or "begin\n" in text


def _target_text(target: dict[str, Any], problem_ir: dict[str, Any] | None) -> str:
    if target:
        pieces = [str(v) for v in target.values() if str(v).strip()]
        if pieces:
            return " ".join(pieces)
    ir = problem_ir or {}
    unknown = ir.get("unknown_target")
    if isinstance(unknown, dict):
        pieces = [str(unknown.get("symbol") or ""), str(unknown.get("description") or "")]
        text = " ".join(x for x in pieces if x.strip())
        if text:
            return text
    return str(ir.get("goal_statement") or "").strip()


def _target_match_texts(target: dict[str, Any], problem_ir: dict[str, Any] | None) -> list[str]:
    texts: list[str] = []
    for payload in (target, (problem_ir or {}).get("unknown_target")):
        if not isinstance(payload, dict):
            continue
        for key in ("symbol", "name", "description", "goal", "lean", "expected_form"):
            value = payload.get(key)
            if value is not None and str(value).strip():
                texts.append(str(value).strip())
        extra = payload.get("extra_targets")
        if isinstance(extra, list):
            for item in extra:
                if not isinstance(item, dict):
                    continue
                for key in ("symbol", "name", "description"):
                    value = item.get(key)
                    if value is not None and str(value).strip():
                        texts.append(str(value).strip())
    goal = str((problem_ir or {}).get("goal_statement") or "").strip()
    if goal:
        texts.append(goal)
    out: list[str] = []
    seen: set[str] = set()
    for text in texts:
        key = " ".join(text.lower().split())
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _forbidden_contains_target(forbidden: list[str], target: dict[str, Any], problem_ir: dict[str, Any] | None) -> bool:
    target_text = _target_text(target, problem_ir).lower()
    target_refs = _target_match_texts(target, problem_ir)
    if not target_text and not target_refs:
        return False
    compact_target = " ".join(target_text.split())
    target_tokens = _tokens(compact_target)
    ref_tokens = [_tokens(text) for text in target_refs]
    symbol_refs = [
        str(value).strip().lower()
        for payload in (target, (problem_ir or {}).get("unknown_target"))
        if isinstance(payload, dict)
        for value in (payload.get("symbol"), payload.get("name"))
        if value is not None and str(value).strip()
    ]
    for item in forbidden:
        text = " ".join(str(item or "").lower().split())
        if not text:
            continue
        if compact_target and (compact_target in text or text in compact_target):
            return True
        if any(ref and ref in text for ref in symbol_refs):
            return True
        if target_tokens and target_tokens.issubset(_tokens(text)):
            return True
        item_tokens = _tokens(text)
        for tokens in ref_tokens:
            if not tokens:
                continue
            overlap = len(tokens.intersection(item_tokens))
            if overlap >= min(3, len(tokens)):
                return True
    return False


def _schema_rows(context: StructuredMechLibContext | dict[str, Any] | None) -> list[dict[str, Any]]:
    payload = _context_payload(context)
    modeling = payload.get("modeling_context", {}) if isinstance(payload, dict) else {}
    rows: list[dict[str, Any]] = []
    for key in ("law_schemas", "problem_schemas"):
        value = modeling.get(key, []) if isinstance(modeling, dict) else []
        if isinstance(value, list):
            rows.extend(row for row in value if isinstance(row, dict))
    return rows


def _tokens(text: str) -> set[str]:
    return {tok.lower() for tok in re.findall(r"[A-Za-z_][A-Za-z0-9_']*", text or "") if len(tok) > 1}


class SchemaPlanner:
    def __init__(self, structured_mechlib_context: StructuredMechLibContext | dict[str, Any] | None) -> None:
        self.schema_rows = _schema_rows(structured_mechlib_context)

    def apply(self, model_ir: ModelIR) -> ModelIR:
        schema_ids = {str(row.get("schema_id") or row.get("id") or "").strip() for row in self.schema_rows}
        for instance in model_ir.model_instances:
            current = (instance.planning_schema_id or "").strip()
            if current:
                continue
            match = self._best_schema_for_instance(instance)
            if match:
                instance.planning_schema_id = match
        return model_ir

    def _best_schema_for_instance(self, instance: ModelInstance) -> str | None:
        instance_text = "\n".join(
            [
                instance.kind,
                instance.natural_language,
                instance.expected_claim or "",
                instance.planning_schema_id or "",
                " ".join(str(x) for x in instance.entities),
                " ".join(str(x) for x in instance.variables.values()),
            ]
        )
        instance_tokens = _tokens(instance_text)
        best_score = 0
        best_id: str | None = None
        for row in self.schema_rows:
            schema_id = str(row.get("schema_id") or row.get("id") or "").strip()
            if not schema_id:
                continue
            schema_text = json.dumps(row, ensure_ascii=False)
            score = len(instance_tokens.intersection(_tokens(schema_text)))
            if instance.planning_schema_id and instance.planning_schema_id == schema_id:
                score += 100
            if score > best_score:
                best_score = score
                best_id = schema_id
        return best_id if best_score > 0 else None


class ModuleA2ModelIR:
    def __init__(self, model_client, prompt_path: Path) -> None:
        self.model_client = model_client
        self.template = load_template(prompt_path, DEFAULT_PROMPT)

    def run(
        self,
        *,
        sample_id: str,
        problem_text: str,
        problem_ir: dict[str, Any] | None,
        structured_mechlib_context: StructuredMechLibContext | dict[str, Any] | None = None,
        image_description: str | None = None,
        revision_feedback: str = "(none)",
    ) -> ModelIR:
        safe_problem_text = redact_leakage_text(problem_text or "")
        context_payload = compact_structured_context(_context_payload(structured_mechlib_context))
        prompt = render_template(
            self.template,
            {
                "problem_text": safe_problem_text,
                "problem_ir_json": json.dumps(compact_problem_ir(problem_ir), ensure_ascii=False, indent=2),
                "structured_context_json": json.dumps(context_payload, ensure_ascii=False, indent=2),
                "image_description": image_description or "",
                "supported_si_quantity_types": ", ".join(sorted(SUPPORTED_SI_QUANTITY_TYPES)),
                "revision_feedback": revision_feedback or "(none)",
            },
        )

        raw = ""
        try:
            raw = self.model_client.generate_text(prompt).text
        except Exception as exc:
            return ModelIR(
                sample_id=sample_id,
                source_problem_ir_hash=_problem_ir_hash(problem_ir),
                raw_response=raw,
                parse_ok=False,
                error=f"model_ir_generation_exception:{type(exc).__name__}: {exc}",
            )

        try:
            parsed = parse_json_model(raw, _ModelIRPayload)
            raw_payload = parsed.model_dump()
        except ResponseParseError as exc:
            return ModelIR(
                sample_id=sample_id,
                source_problem_ir_hash=_problem_ir_hash(problem_ir),
                raw_response=raw,
                parse_ok=False,
                error=f"model_ir_parse_failed:{exc}",
            )

        if _contains_forbidden_lean_artifact(raw_payload):
            return ModelIR(
                sample_id=sample_id,
                source_problem_ir_hash=_problem_ir_hash(problem_ir),
                raw_response=raw,
                parse_ok=False,
                error="model_ir_contains_lean_theorem_or_proof",
            )

        instances = [
            _model_instance_from_payload(item, idx)
            for idx, item in enumerate(parsed.model_instances, start=1)
            if item.kind.strip() or item.natural_language.strip() or item.expected_claim
        ]
        quantity_annotations = [
            annotation
            for annotation in (
                _quantity_annotation_from_payload(item) for item in parsed.quantity_annotations
            )
            if annotation is not None
        ]
        forbidden = _normalize_forbidden_as_assumption(list(parsed.forbidden_as_assumption))
        if not instances:
            return ModelIR(
                sample_id=sample_id,
                source_problem_ir_hash=_problem_ir_hash(problem_ir),
                raw_response=raw,
                parse_ok=False,
                error="model_ir_missing_model_instances",
            )
        canonical_target = _canonical_target_from_payload(
            parsed.canonical_target,
            target=dict(parsed.target),
            target_spec=dict(parsed.target_spec),
            problem_ir=problem_ir,
            forbidden_as_assumption=forbidden,
        )
        if not _forbidden_contains_target(forbidden, parsed.target, problem_ir):
            if canonical_target.parse_ok and str(canonical_target.lean_formula or "").strip():
                forbidden.append(f"target|{canonical_target.lean_formula}")
            else:
                return ModelIR(
                    sample_id=sample_id,
                    source_problem_ir_hash=_problem_ir_hash(problem_ir),
                    raw_response=raw,
                    parse_ok=False,
                    error="model_ir_forbidden_as_assumption_missing_target",
                )

        model_ir = ModelIR(
            sample_id=sample_id,
            objects=list(parsed.objects),
            variables=dict(parsed.variables),
            givens=[_provenance_from_payload(item) for item in parsed.givens],
            coordinate_system=dict(parsed.coordinate_system),
            reference_frame=parsed.reference_frame,
            local_definitions=[_provenance_from_payload(item) for item in parsed.local_definitions],
            model_instances=instances,
            interface_instantiations=[
                _interface_instantiation_from_payload(item, idx)
                for idx, item in enumerate(parsed.interface_instantiations, start=1)
                if item.formal_claim.strip()
            ],
            quantity_annotations=quantity_annotations,
            canonical_target=canonical_target,
            target=dict(parsed.target),
            target_spec=dict(parsed.target_spec),
            forbidden_as_assumption=forbidden,
            source_problem_ir_hash=_problem_ir_hash(problem_ir),
            raw_response=raw,
            parse_ok=True,
            error=None,
        )
        dropped_local_definition_errors = _drop_invalid_local_definitions(model_ir)
        if dropped_local_definition_errors:
            model_ir.error = "dropped_invalid_local_definitions:" + ";".join(dropped_local_definition_errors)
        dropped_modeling_formula_errors = _drop_invalid_modeling_formula_fields(model_ir)
        if dropped_modeling_formula_errors:
            prefix = (model_ir.error + ";") if model_ir.error else ""
            model_ir.error = prefix + "dropped_invalid_modeling_formulas:" + ";".join(
                dropped_modeling_formula_errors
            )
        contract_error = _collect_model_ir_contract_error(model_ir)
        if contract_error:
            model_ir.parse_ok = False
            model_ir.error = contract_error
        return SchemaPlanner(structured_mechlib_context).apply(model_ir)
