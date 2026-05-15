from __future__ import annotations

import json
import re
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from mech_pipeline.prompting import load_template, render_template
from mech_pipeline.types import (
    SolutionFormula,
    SolutionRenderAudit,
    SolutionRenderResult,
    SolutionStep,
    SolutionTrace,
)
from mech_pipeline.utils import extract_json_object, truncate


DEFAULT_RENDER_PROMPT = """__TASK_F_SOLUTION_RENDERER__
你正在把一个结构化解题轨迹渲染成中文力学解题流程。
不要重新解题。不要新增公式。不要新增物理定律。不要修改最终答案。
不要隐藏 gap、partial、legacy/no-audit、proof_failed 状态。
只能使用 SolutionTrace 中的步骤、公式和验证状态。
不要输入或依赖完整 Lean proof、完整 MechLib context、完整 theorem corpus、完整 raw_response。
写成教材式中文解题过程：先设符号和正方向，再分对象受力分析并编号方程，最后联立消元。
不要写“目标公式：”“轨迹中给出”“按轨迹中的目标结果可得”“结构化 artifact”等内部流水线措辞。
不要用项目符号罗列 artifact；自然段和独立公式行优先。
如果 SolutionTrace 没有某个中间公式，不要补写该公式。

输出 JSON，格式必须是：
{
  "natural_solution": "...",
  "used_step_ids": ["..."],
  "mentioned_formulas": ["..."],
  "verification_note": "..."
}

SolutionTrace:
{{solution_trace_json}}
"""


SUCCESS_STATUSES = {
    "fully_mechlib_verified",
    "partial_mechlib_verified",
    "gap_assisted_success",
    "algebra_only_success",
    "legacy_verified_no_audit",
}


def _to_payload(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "to_dict"):
        payload = value.to_dict()
        return dict(payload) if isinstance(payload, dict) else None
    if is_dataclass(value):
        return asdict(value)
    return None


def _list_payload(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, list):
        out: list[dict[str, Any]] = []
        for item in value:
            payload = _to_payload(item)
            if payload is not None:
                out.append(payload)
        return out
    payload = _to_payload(value)
    return [payload] if payload is not None else []


def _str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            text = str(item).strip()
            if text:
                out.append(text)
        return out
    return [str(value)] if str(value).strip() else []


def _first_text(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _dedupe_dicts(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        marker = str(row.get(key) or row)
        if marker in seen:
            continue
        seen.add(marker)
        out.append(row)
    return out


def _sample_id_from_sources(*sources: dict[str, Any] | None) -> str:
    for source in sources:
        if not source:
            continue
        sid = str(source.get("sample_id") or "").strip()
        if sid:
            return sid
    return "unknown_sample"


def _candidate_id_from_sources(*sources: dict[str, Any] | None) -> str | None:
    for source in sources:
        if not source:
            continue
        cid = str(source.get("candidate_id") or source.get("selected_candidate_id") or "").strip()
        if cid:
            return cid
    return None


def _best_attempt(proof_attempt: Any) -> dict[str, Any] | None:
    attempts = _list_payload(proof_attempt)
    if not attempts:
        return None
    strict = [row for row in attempts if bool(row.get("strict_pass")) or bool(row.get("compile_pass"))]
    pool = strict or attempts
    return sorted(pool, key=lambda row: int(row.get("attempt_index") or 0))[-1]


def _coalesce_nested(source: dict[str, Any] | None, key: str) -> dict[str, Any] | None:
    if not source:
        return None
    return _to_payload(source.get(key))


def _target_from_candidate(candidate: dict[str, Any] | None, model_ir: dict[str, Any] | None = None) -> str | None:
    if candidate:
        target_spec = candidate.get("target_spec")
        if isinstance(target_spec, dict):
            primary = _first_text(
                target_spec.get("lean_formula"),
                target_spec.get("formal_formula"),
                target_spec.get("target_formula"),
                target_spec.get("target"),
            )
            formulas = [primary] if primary else []
            secondary_formulas = target_spec.get("secondary_formulas")
            for item in secondary_formulas if isinstance(secondary_formulas, list) else []:
                text = str(item or "").strip()
                if text:
                    formulas.append(text)
            if formulas:
                return " ∧ ".join(formulas)
        theorem_decl = str(candidate.get("theorem_decl") or "").strip()
        if theorem_decl:
            declaration = theorem_decl.split(":=", 1)[0].strip()
            if declaration.endswith(" by"):
                declaration = declaration[:-3].strip()
            if " : " in declaration:
                return declaration.rsplit(" : ", 1)[-1].strip()
            if ":" in declaration:
                return declaration.rsplit(":", 1)[-1].strip()
    if model_ir:
        canonical_target = model_ir.get("canonical_target")
        if isinstance(canonical_target, dict):
            text = _first_text(canonical_target.get("lean_formula"), canonical_target.get("source_text"))
            if text:
                return text
        target_spec = model_ir.get("target_spec")
        if isinstance(target_spec, dict):
            text = _first_text(target_spec.get("lean_formula"), target_spec.get("formal_formula"), target_spec.get("target"))
            if text:
                return text
    return None


def _split_conjunctions(formula: str | None) -> list[str]:
    if not formula:
        return []
    text = formula.strip()
    if not text:
        return []
    parts = re.split(r"\s+[∧&]\s+|\s+and\s+", text)
    out: list[str] = []
    for part in parts:
        stripped = part.strip()
        if _is_wrapped_by_outer_parens(stripped):
            stripped = stripped[1:-1].strip()
        if stripped:
            out.append(stripped)
    return out


def _is_wrapped_by_outer_parens(text: str) -> bool:
    if not (text.startswith("(") and text.endswith(")")):
        return False
    depth = 0
    for idx, char in enumerate(text):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0 and idx != len(text) - 1:
                return False
            if depth < 0:
                return False
    return depth == 0


def pretty_print_formula(formal: str) -> str:
    """Conservative formula display; never changes the stored formal formula."""
    try:
        text = str(formal or "").strip()
        if "∧" in text:
            return " 且 ".join(pretty_print_formula(part) for part in _split_conjunctions(text))
        replacements = {
            "m1.val": "m₁",
            "m2.val": "m₂",
            "m3.val": "m₃",
            "a.val": "a",
            "g.val": "g",
            "T.val": "T",
            "Fnet.val": "F_net",
            "F_start.val": "F_start",
            "W.val": "W",
            "mu_s.val": "μ_s",
            "mu_k.val": "μ_k",
        }
        for old, new in replacements.items():
            text = text.replace(old, new)
        text = re.sub(r"\b([A-Za-z][A-Za-z0-9_]*)\.val\b", r"\1", text)
        text = re.sub(r"\bm1\b", "m₁", text)
        text = re.sub(r"\bm2\b", "m₂", text)
        text = re.sub(r"\bm3\b", "m₃", text)
        text = re.sub(r"\s*\*\s*", " ", text)
        text = re.sub(r"\s*/\s*", " / ", text)
        text = re.sub(r"\s*=\s*", " = ", text)
        text = re.sub(r"\s+", " ", text)
        text = _format_display_fraction(text)
        text = _compact_common_products(text)
        return text.strip() or str(formal)
    except Exception:
        return str(formal)


def _strip_redundant_parens(text: str) -> str:
    stripped = str(text or "").strip()
    while _is_wrapped_by_outer_parens(stripped):
        stripped = stripped[1:-1].strip()
    return stripped


def _find_top_level_char(text: str, char: str) -> int:
    depth = 0
    for idx, value in enumerate(text):
        if value == "(":
            depth += 1
        elif value == ")":
            depth -= 1
        elif value == char and depth == 0:
            return idx
    return -1


def _format_display_fraction(text: str) -> str:
    if "=" not in text:
        return text
    lhs, rhs = text.split("=", 1)
    slash = _find_top_level_char(rhs, "/")
    if slash < 0:
        return text
    numerator = _strip_redundant_parens(rhs[:slash])
    denominator = _strip_redundant_parens(rhs[slash + 1 :])
    if not numerator or not denominator:
        return text
    return f"{lhs.strip()} = \\frac{{{numerator}}}{{{denominator}}}"


def _compact_common_products(text: str) -> str:
    replacements = {
        "m₁ m₂ g": "m₁m₂g",
        "m₂ g": "m₂g",
        "m₁ a": "m₁a",
        "m₂ a": "m₂a",
        "m₃ a": "m₃a",
        "(m₁ + m₂) a": "(m₁ + m₂)a",
        "(m₁ + m₂) * a": "(m₁ + m₂)a",
    }
    out = text
    for old, new in replacements.items():
        out = out.replace(old, new)
    return out


def _formula(formula_id: str, formal: str | None, *, source: str | None = None, verified: bool = False) -> SolutionFormula | None:
    if not formal or not str(formal).strip():
        return None
    text = str(formal).strip()
    return SolutionFormula(
        formula_id=formula_id,
        formal_formula=text,
        display_formula=pretty_print_formula(text),
        source=source,
        verified=verified,
        provenance=[source] if source else [],
    )


def _trace_from_payload(source: dict[str, Any] | None) -> dict[str, Any] | None:
    if not source:
        return None
    trace = _coalesce_nested(source, "proof_search_trace")
    if trace:
        return trace
    if source.get("accepted_actions") is not None or source.get("rejected_actions") is not None:
        return source
    return None


def _audit_from_payload(source: dict[str, Any] | None) -> dict[str, Any] | None:
    if not source:
        return None
    audit = _coalesce_nested(source, "dependency_audit")
    if audit:
        return audit
    if source.get("classification") or source.get("covered_obligations") is not None:
        return source
    return None


def _proof_status(
    *,
    proof_check: dict[str, Any] | None,
    proof_attempt: dict[str, Any] | None,
    dependency_audit: dict[str, Any] | None,
) -> str:
    if dependency_audit and str(dependency_audit.get("classification") or "").strip():
        return str(dependency_audit["classification"]).strip()
    proof_success = bool((proof_check or {}).get("proof_success"))
    proof_mode = str(
        (proof_check or {}).get("proof_mode")
        or (proof_attempt or {}).get("proof_mode")
        or ""
    )
    fallback = bool((proof_check or {}).get("fallback_to_legacy_full_proof") or (proof_attempt or {}).get("fallback_to_legacy_full_proof"))
    if proof_success and (proof_mode == "legacy_full_proof" or fallback or not proof_mode):
        return "legacy_verified_no_audit"
    error_type = str((proof_check or {}).get("error_type") or (proof_check or {}).get("sub_error_type") or "")
    if not proof_success and error_type == "proof_skipped_due_to_semantic_fail":
        return "proof_skipped_due_to_semantic_fail"
    if proof_check is not None and not proof_success:
        return "proof_failed"
    return "not_checked"


def _controlled_sketch_payload(controlled_sketch: dict[str, Any] | None, theorem_candidate: dict[str, Any] | None) -> dict[str, Any] | None:
    if controlled_sketch:
        return controlled_sketch
    embedded = _coalesce_nested(theorem_candidate, "controlled_sketch")
    return embedded


def collect_solution_evidence(
    *,
    problem_ir: dict | None,
    model_ir: dict | None,
    controlled_sketch: dict | None,
    theorem_candidate: dict | None,
    proof_attempt: dict | None,
    proof_check: dict | None,
    proof_search_trace: dict | None,
    dependency_audit: dict | None,
) -> dict[str, Any]:
    """Normalize post-E artifacts into a compact evidence bundle for rendering."""
    problem_payload = _to_payload(problem_ir)
    model_payload = _to_payload(model_ir)
    candidate_payload = _to_payload(theorem_candidate)
    attempt_payload = _best_attempt(proof_attempt)
    check_payload = _to_payload(proof_check)
    explicit_trace = _to_payload(proof_search_trace)
    explicit_audit = _to_payload(dependency_audit)

    trace_payload = explicit_trace or _trace_from_payload(check_payload) or _trace_from_payload(attempt_payload)
    audit_payload = explicit_audit or _audit_from_payload(check_payload) or _audit_from_payload(attempt_payload)
    sketch_payload = _controlled_sketch_payload(_to_payload(controlled_sketch), candidate_payload)

    proof_steps: list[dict[str, Any]] = []
    blocked_steps: list[dict[str, Any]] = []
    algebra_obligation: dict[str, Any] | None = None
    model_interface_instantiations: list[dict[str, Any]] = []
    if sketch_payload:
        proof_steps.extend(_list_payload(sketch_payload.get("proof_steps")))
        proof_steps.extend(_list_payload(sketch_payload.get("steps")))
        blocked_steps.extend(_list_payload(sketch_payload.get("blocked_law_steps")))
        blocked_steps.extend(_list_payload(sketch_payload.get("gap_steps")))
        algebra_obligation = _to_payload(sketch_payload.get("algebra_obligation"))
        model_interface_instantiations.extend(_list_payload(sketch_payload.get("model_interface_instantiations")))
        for variant in _list_payload(sketch_payload.get("sketch_variants")):
            proof_steps.extend(_list_payload(variant.get("proof_steps")))
            blocked_steps.extend(_list_payload(variant.get("blocked_law_steps")))
            if algebra_obligation is None:
                algebra_obligation = _to_payload(variant.get("algebra_obligation"))
    proof_steps = _dedupe_dicts(proof_steps, "step_id")
    blocked_steps = _dedupe_dicts(blocked_steps, "step_id")

    proof_obligations = _list_payload((candidate_payload or {}).get("proof_obligations")) or list(proof_steps)
    hypothesis_provenance = _list_payload((candidate_payload or {}).get("hypothesis_provenance"))
    candidate_instantiations = _list_payload((candidate_payload or {}).get("model_interface_instantiations"))
    model_instantiations = _list_payload((model_payload or {}).get("interface_instantiations"))
    model_interface_instantiations.extend(candidate_instantiations)
    model_interface_instantiations.extend(model_instantiations)

    target = _target_from_candidate(candidate_payload, model_payload)
    accepted_actions = _list_payload((trace_payload or {}).get("accepted_actions"))
    rejected_actions = _list_payload((trace_payload or {}).get("rejected_actions"))
    final_proof_body = _first_text(
        (trace_payload or {}).get("final_proof_body"),
        (attempt_payload or {}).get("proof_body"),
        (attempt_payload or {}).get("proof_body_excerpt"),
    )
    final_answers: list[dict[str, Any]] = []
    for idx, part in enumerate(_split_conjunctions(target), start=1):
        final_answers.append(
            {
                "formula_id": f"final_answer_{idx}",
                "formal_formula": part,
                "display_formula": pretty_print_formula(part),
                "source": "theorem_target",
            }
        )

    proof_status = _proof_status(
        proof_check=check_payload,
        proof_attempt=attempt_payload,
        dependency_audit=audit_payload,
    )
    sample_id = _sample_id_from_sources(
        check_payload,
        attempt_payload,
        candidate_payload,
        sketch_payload,
        model_payload,
        problem_payload,
    )
    candidate_id = _candidate_id_from_sources(check_payload, attempt_payload, candidate_payload, trace_payload, audit_payload)
    proof_mode = _first_text((check_payload or {}).get("proof_mode"), (attempt_payload or {}).get("proof_mode"))
    warnings: list[str] = []
    if not trace_payload:
        warnings.append("proof_search_trace_missing_or_empty")
    if not audit_payload:
        warnings.append("dependency_audit_missing_or_empty")
    if proof_status == "legacy_verified_no_audit":
        warnings.append("legacy_proof_success_without_dependency_audit")
    if proof_status in {"proof_failed", "proof_skipped_due_to_semantic_fail", "not_checked"}:
        warnings.append(f"non_verified_solution_status:{proof_status}")

    return {
        "sample_id": sample_id,
        "candidate_id": candidate_id,
        "problem_ir": problem_payload,
        "model_ir": model_payload,
        "proof_success": bool((check_payload or {}).get("proof_success")),
        "proof_mode": proof_mode,
        "proof_status": proof_status,
        "target": target,
        "controlled_sketch_steps": proof_steps,
        "model_interface_instantiations": _dedupe_dicts(model_interface_instantiations, "instantiation_id"),
        "algebra_obligation": algebra_obligation,
        "proof_obligations": proof_obligations,
        "accepted_actions": accepted_actions,
        "rejected_actions": rejected_actions,
        "dependency_audit": audit_payload,
        "final_proof_body": final_proof_body,
        "hypothesis_provenance": hypothesis_provenance,
        "gap_laws": _list_payload((candidate_payload or {}).get("gap_laws")),
        "explicit_model_gaps": _list_payload((candidate_payload or {}).get("explicit_model_gaps")),
        "blocked_law_steps": blocked_steps,
        "final_answers": final_answers,
        "warnings": warnings,
        "source_status": {
            "problem_ir_present": problem_payload is not None,
            "model_ir_present": model_payload is not None,
            "controlled_sketch_present": sketch_payload is not None,
            "theorem_candidate_present": candidate_payload is not None,
            "proof_attempt_present": attempt_payload is not None,
            "proof_check_present": check_payload is not None,
            "proof_search_trace_present": trace_payload is not None,
            "dependency_audit_present": audit_payload is not None,
        },
    }


def _covered_obligation_ids(dependency_audit: dict[str, Any] | None) -> set[str]:
    if not dependency_audit:
        return set()
    covered = set(_str_list(dependency_audit.get("covered_obligations")))
    for item in _list_payload(dependency_audit.get("covered_obligation_details")):
        sid = str(item.get("obligation_id") or item.get("step_id") or "").strip()
        if sid:
            covered.add(sid)
    return covered


def _accepted_action_markers(actions: list[dict[str, Any]]) -> set[str]:
    markers: set[str] = set()
    for action in actions:
        for key in ("action_id", "proof_obligation_id", "obligation_id", "step_id"):
            text = str(action.get(key) or "").strip()
            if text:
                markers.add(text)
        for key in ("uses_decls", "uses_facts", "produces", "produced_facts"):
            markers.update(_str_list(action.get(key)))
        tactic = str(action.get("tactic_block") or action.get("proof_prefix") or "")
        for token in re.findall(r"[A-Za-z_][A-Za-z0-9_'.]*", tactic):
            markers.add(token)
    return markers


def _is_blocked_step(step: dict[str, Any], blocked: list[dict[str, Any]]) -> bool:
    sid = str(step.get("step_id") or "").strip()
    if sid and any(str(item.get("step_id") or "").strip() == sid for item in blocked):
        return True
    status = str(step.get("binding_status") or "").strip()
    if status and status != "ok":
        return True
    if bool(step.get("gap_assisted")) or bool(step.get("gap_schema_only")):
        return True
    return False


def _law_step_verified(
    step: dict[str, Any],
    *,
    proof_status: str,
    covered_ids: set[str],
    action_markers: set[str],
    blocked_steps: list[dict[str, Any]],
) -> bool:
    if _is_blocked_step(step, blocked_steps):
        return False
    step_id = str(step.get("step_id") or "").strip()
    verified_decl = str(step.get("verified_decl") or "").strip()
    if not bool(step.get("proof_fact_allowed")):
        return False
    if str(step.get("binding_status") or "") != "ok":
        return False
    if not verified_decl:
        return False
    if step_id and step_id in covered_ids:
        return True
    if verified_decl in action_markers or verified_decl.rsplit(".", 1)[-1] in action_markers:
        return True
    if step_id and step_id in action_markers:
        return True
    return proof_status == "legacy_verified_no_audit"


def _canon_formula_for_pattern(text: str | None) -> str:
    value = str(text or "").strip().lower()
    replacements = {
        ".val": "",
        "₁": "1",
        "₂": "2",
        "₃": "3",
        "×": "*",
        "·": "*",
        " ": "",
    }
    for old, new in replacements.items():
        value = value.replace(old, new)
    value = value.replace("\\frac{", "(").replace("}{", ")/(").replace("}", ")")
    value = value.replace("*", "")
    return value


def _trace_has_formula(formulas: list[str], expected: str) -> bool:
    expected_canon = _canon_formula_for_pattern(expected)
    return any(_canon_formula_for_pattern(formula) == expected_canon for formula in formulas)


def _final_answer_has_shape(final_answers: list[SolutionFormula], lhs: str, required_tokens: list[str]) -> bool:
    for formula in final_answers:
        canon = _canon_formula_for_pattern(formula.formal_formula)
        if not canon.startswith(f"{lhs}="):
            continue
        if all(token in canon for token in required_tokens):
            return True
    return False


def _has_positive_mass_assumptions(actions: list[dict[str, Any]]) -> bool:
    variables: set[str] = set()
    for action in actions:
        for assumption in _list_payload(action.get("added_physical_assumptions")):
            expression = _canon_formula_for_pattern(assumption.get("expression"))
            variable = str(assumption.get("variable") or "").strip()
            if expression in {"0<m1", "m1>0"} or variable == "m1":
                variables.add("m1")
            if expression in {"0<m2", "m2>0"} or variable == "m2":
                variables.add("m2")
    return {"m1", "m2"}.issubset(variables)


def _has_denominator_nonzero_action(actions: list[dict[str, Any]]) -> bool:
    for action in actions:
        claims = _str_list(action.get("new_local_fact_claims")) + _str_list(action.get("proposed_local_fact_claims"))
        if any(_canon_formula_for_pattern(claim) in {"m1+m2≠0", "m1+m2/=0"} for claim in claims):
            return True
        tactic = str(action.get("tactic_block") or "")
        if "m1.val + m2.val ≠ 0" in tactic or "m1 + m2 ≠ 0" in tactic:
            return True
    return False


def _two_body_linear_algebra_step(
    *,
    steps: list[SolutionStep],
    final_answers: list[SolutionFormula],
    proof_status: str,
    accepted_actions: list[dict[str, Any]],
) -> SolutionStep | None:
    law_formulas = [
        formula
        for step in steps
        if step.kind == "law_application"
        for formula in (step.formal_formula, step.display_formula)
        if formula
    ]
    if not _trace_has_formula(law_formulas, "T = m1 * a"):
        return None
    if not _trace_has_formula(law_formulas, "m2 * g - T = m2 * a"):
        return None
    if not _final_answer_has_shape(final_answers, "a", ["m2g", "m1+m2"]):
        return None
    if not _final_answer_has_shape(final_answers, "t", ["m1m2g", "m1+m2"]):
        return None

    verified = proof_status in SUCCESS_STATUSES
    formulas = [
        SolutionFormula(
            formula_id="two_body_substitution",
            formal_formula="m2 * g - m1 * a = m2 * a",
            display_formula="m₂g - m₁a = m₂a",
            source="deterministic_algebra_from_solution_trace",
            verified=verified,
            provenance=["law_step:T=m1*a", "law_step:m2*g-T=m2*a"],
        ),
        SolutionFormula(
            formula_id="two_body_collect_terms",
            formal_formula="m2 * g = (m1 + m2) * a",
            display_formula="m₂g = (m₁ + m₂)a",
            source="deterministic_algebra_from_solution_trace",
            verified=verified,
            provenance=["two_body_substitution"],
        ),
    ]
    input_formulas = [
        SolutionFormula(
            formula_id="two_body_mass_positive_m1",
            formal_formula="0 < m1",
            display_formula="0 < m₁",
            source="ProofSearchTrace.accepted_actions",
            verified=verified,
            provenance=["physical_positive_hypothesis_augmentation"],
        ),
        SolutionFormula(
            formula_id="two_body_mass_positive_m2",
            formal_formula="0 < m2",
            display_formula="0 < m₂",
            source="ProofSearchTrace.accepted_actions",
            verified=verified,
            provenance=["physical_positive_hypothesis_augmentation"],
        ),
    ] if _has_positive_mass_assumptions(accepted_actions) else []
    if _has_denominator_nonzero_action(accepted_actions):
        formulas.append(
            SolutionFormula(
                formula_id="two_body_denominator_nonzero",
                formal_formula="m1 + m2 ≠ 0",
                display_formula="m₁ + m₂ ≠ 0",
                source="ProofSearchTrace.accepted_actions",
                verified=verified,
                provenance=["side_condition:m1.val+m2.val"],
            )
        )

    return SolutionStep(
        step_id="algebra_elimination_two_body_linear_1",
        kind="algebra_elimination",
        title="联立方程求解",
        text_intent="由 T = m₁a 与 m₂g - T = m₂a 消元求解 a 和 T。",
        input_formulas=input_formulas,
        output_formulas=formulas,
        source_artifacts=[
            "SolutionTrace.law_application",
            "ProofSearchTrace.accepted_actions",
            "TheoremSkeletonCandidate.target_spec",
        ],
        verified=verified,
        gap_assisted=proof_status not in SUCCESS_STATUSES,
        notes="deterministic_two_body_linear_system",
    )


def _modeling_step(evidence: dict[str, Any]) -> SolutionStep | None:
    model_ir = evidence.get("model_ir") if isinstance(evidence.get("model_ir"), dict) else {}
    instances = _list_payload(model_ir.get("model_instances") if model_ir else None)
    interface_instantiations = _list_payload(evidence.get("model_interface_instantiations"))
    provenance = _list_payload(evidence.get("hypothesis_provenance"))
    formulas: list[SolutionFormula] = []
    for idx, item in enumerate(interface_instantiations, start=1):
        formal = _first_text(item.get("formal_claim"), item.get("hypothesis_form"), item.get("expected_claim"))
        formula = _formula(f"model_relation_{idx}", formal, source="model_interface_instantiation", verified=False)
        if formula:
            formulas.append(formula)
    for idx, item in enumerate(provenance, start=1):
        if str(item.get("role") or "") not in {"local_definition", "coordinate_convention", "model_instance"}:
            continue
        formula = _formula(f"model_provenance_{idx}", _first_text(item.get("lean")), source="hypothesis_provenance", verified=False)
        if formula:
            formulas.append(formula)
    if not instances and not formulas:
        return None
    descriptions = []
    for item in instances[:4]:
        text = _first_text(item.get("natural_language"), item.get("kind"), item.get("instance_id"))
        if text:
            descriptions.append(text)
    text_intent = "; ".join(descriptions) if descriptions else "根据 ModelIR 建立对象、变量、约束和局部定义。"
    return SolutionStep(
        step_id="modeling_1",
        kind="modeling",
        title="建立力学模型",
        text_intent=text_intent,
        output_formulas=formulas,
        source_artifacts=["ModelIR", "TheoremSkeletonCandidate.hypothesis_provenance"],
        verified=False,
    )


def build_solution_trace(evidence: dict[str, Any]) -> SolutionTrace:
    sample_id = str(evidence.get("sample_id") or "unknown_sample")
    candidate_id = evidence.get("candidate_id")
    proof_status = str(evidence.get("proof_status") or "not_checked")
    target = _first_text(evidence.get("target"))
    steps: list[SolutionStep] = []

    problem_ir = evidence.get("problem_ir") if isinstance(evidence.get("problem_ir"), dict) else {}
    target_display = pretty_print_formula(target) if target else None
    goal = _first_text(
        problem_ir.get("goal_statement") if problem_ir else None,
        json.dumps(problem_ir.get("unknown_target"), ensure_ascii=False) if problem_ir and problem_ir.get("unknown_target") else None,
        target_display,
    )
    if problem_ir or target:
        steps.append(
            SolutionStep(
                step_id="problem_understanding_1",
                kind="problem_understanding",
                title="题意与目标",
                text_intent=f"要求解的目标是 {goal}。" if goal else "识别题目目标和符号。",
                formal_formula=target,
                display_formula=target_display,
                source_artifacts=["ProblemIR", "CanonicalTarget", "TheoremSkeletonCandidate"],
                verified=False,
            )
        )

    modeling = _modeling_step(evidence)
    if modeling is not None:
        steps.append(modeling)

    blocked_steps = _list_payload(evidence.get("blocked_law_steps"))
    covered_ids = _covered_obligation_ids(evidence.get("dependency_audit"))
    action_markers = _accepted_action_markers(_list_payload(evidence.get("accepted_actions")))
    for idx, step in enumerate(_list_payload(evidence.get("controlled_sketch_steps")) or _list_payload(evidence.get("proof_obligations")), start=1):
        if str(step.get("kind") or "") not in {"law_to_equation", "constraint_to_equation"}:
            continue
        formal = _first_text(step.get("formal_claim"), step.get("produces"), step.get("expected_claim"))
        verified = _law_step_verified(
            step,
            proof_status=proof_status,
            covered_ids=covered_ids,
            action_markers=action_markers,
            blocked_steps=blocked_steps,
        )
        formula = _formula(f"law_step_{idx}_formula", formal, source="ControlledSketch", verified=verified)
        title = "应用物理定律" if step.get("kind") == "law_to_equation" else "应用约束关系"
        verified_decl = _first_text(step.get("verified_decl"))
        notes = None
        if _is_blocked_step(step, blocked_steps):
            notes = "blocked_or_gap_law_step_not_verified"
        elif proof_status == "legacy_verified_no_audit" and verified:
            notes = "legacy proof passed, but no dependency audit is available"
        steps.append(
            SolutionStep(
                step_id=str(step.get("step_id") or f"law_step_{idx}"),
                kind="law_application",
                title=title,
                text_intent=_first_text(step.get("claim"), step.get("notes")),
                formal_formula=formal,
                display_formula=pretty_print_formula(formal) if formal else None,
                output_formulas=[formula] if formula else [],
                source_artifacts=["ControlledSketch", "TheoremSkeletonCandidate.proof_obligations"],
                proof_obligation_id=str(step.get("step_id") or "") or None,
                verified_decl=verified_decl,
                verified=verified,
                gap_assisted=notes == "blocked_or_gap_law_step_not_verified",
                notes=notes,
            )
        )

    final_proof_body = str(evidence.get("final_proof_body") or "")
    accepted_actions = _list_payload(evidence.get("accepted_actions"))
    if any(token in final_proof_body for token in ("h_static_chain", "calc", "rw", "linarith", "nlinarith")) or accepted_actions:
        steps.append(
            SolutionStep(
                step_id="definition_merge_1",
                kind="definition_merge",
                title="合并建模关系",
                text_intent="根据已接受的证明动作或最终 proof body 中的重写/计算步骤，合并局部定义和建模关系。",
                source_artifacts=["ProofSearchTrace.accepted_actions", "ProofAttemptResult.proof_body"],
                verified=proof_status in SUCCESS_STATUSES,
            )
        )

    algebra = evidence.get("algebra_obligation") if isinstance(evidence.get("algebra_obligation"), dict) else None
    algebra_formula = None
    if algebra:
        algebra_formula = _first_text(algebra.get("formal_claim"), algebra.get("produces"), algebra.get("claim"))
    if algebra or any(token in final_proof_body for token in ("linarith", "nlinarith", "ring", "omega")):
        formula = _formula("algebra_obligation_formula", algebra_formula, source="ControlledSketch.algebra_obligation", verified=proof_status in SUCCESS_STATUSES)
        steps.append(
            SolutionStep(
                step_id=str((algebra or {}).get("obligation_id") or "algebra_elimination_1"),
                kind="algebra_elimination",
                title="联立方程求解",
                text_intent=_first_text((algebra or {}).get("claim"), "对前述关系进行代数消元并推出目标式。"),
                formal_formula=algebra_formula,
                display_formula=pretty_print_formula(algebra_formula) if algebra_formula else None,
                input_formulas=[],
                output_formulas=[formula] if formula else [],
                source_artifacts=["ControlledSketch.algebra_obligation", "ProofSearchTrace.accepted_actions", "TheoremSkeletonCandidate.target_spec"],
                proof_obligation_id=str((algebra or {}).get("obligation_id") or "") or None,
                verified=proof_status in SUCCESS_STATUSES,
            )
        )

    final_answers: list[SolutionFormula] = []
    verified_final = proof_status in SUCCESS_STATUSES
    for row in _list_payload(evidence.get("final_answers")):
        formula = _formula(
            str(row.get("formula_id") or f"final_answer_{len(final_answers) + 1}"),
            _first_text(row.get("formal_formula"), row.get("display_formula")),
            source=str(row.get("source") or "theorem_target"),
            verified=verified_final,
        )
        if formula:
            final_answers.append(formula)
    if not final_answers and target:
        for idx, part in enumerate(_split_conjunctions(target), start=1):
            formula = _formula(f"final_answer_{idx}", part, source="theorem_target", verified=verified_final)
            if formula:
                final_answers.append(formula)

    if not any(step.notes == "deterministic_two_body_linear_system" for step in steps):
        algebra_step = _two_body_linear_algebra_step(
            steps=steps,
            final_answers=final_answers,
            proof_status=proof_status,
            accepted_actions=accepted_actions,
        )
        if algebra_step is not None:
            steps.append(algebra_step)

    return SolutionTrace(
        sample_id=sample_id,
        candidate_id=str(candidate_id) if candidate_id is not None else None,
        proof_status=proof_status,
        target_formal=target,
        target_display=target_display,
        steps=steps,
        final_answers=final_answers,
        warnings=_str_list(evidence.get("warnings")),
        source_status=dict(evidence.get("source_status") or {}),
    )


def _trace_prompt_payload(solution_trace: SolutionTrace, *, max_steps: int) -> dict[str, Any]:
    payload = solution_trace.to_dict()
    payload["steps"] = payload.get("steps", [])[:max_steps]
    for step in payload["steps"]:
        step.pop("notes", None)
    payload["source_status"] = {
        key: value
        for key, value in dict(payload.get("source_status") or {}).items()
        if isinstance(value, bool)
    }
    return payload


def build_solution_renderer_prompt(
    *,
    solution_trace: SolutionTrace,
    template: str | None = None,
    max_steps: int = 24,
    max_chars: int = 8000,
) -> str:
    compact = _trace_prompt_payload(solution_trace, max_steps=max_steps)
    trace_json = json.dumps(compact, ensure_ascii=False, indent=2)
    prompt = render_template(template or DEFAULT_RENDER_PROMPT, {"solution_trace_json": trace_json})
    if len(prompt) > max_chars:
        prompt = prompt[: max_chars - 160] + "\n\n[TRUNCATED: SolutionTrace compact payload exceeded prompt budget]\n"
    return prompt


def _status_disclosure(proof_status: str) -> str:
    if proof_status == "fully_mechlib_verified":
        return "上述物理定律应用和代数推导均已由 Lean 验证。"
    if proof_status == "legacy_verified_no_audit":
        return "本题 Lean proof 已通过，但当前缺少 dependency audit，不能确认所有物理步骤均由 MechLib verified declaration 覆盖。"
    if proof_status == "gap_assisted_success":
        return "其中部分建模关系依赖 gap law，不能计为 fully MechLib verified。"
    if proof_status == "proof_failed":
        return "当前形式化证明未通过，因此以下只展示已构造的建模和计划步骤，不作为最终 verified solution。"
    if proof_status == "proof_skipped_due_to_semantic_fail":
        return "当前证明阶段因语义检查失败被跳过，因此以下只展示已构造的建模和计划步骤，不作为最终 verified solution。"
    if proof_status == "partial_mechlib_verified":
        return "当前只有部分物理步骤被 MechLib 依赖审计覆盖，未覆盖步骤不能视为 fully MechLib verified。"
    if proof_status == "algebra_only_success":
        return "当前 proof 主要验证了代数目标，但缺少必要的 MechLib verified declaration 覆盖，不能计为 fully MechLib verified。"
    return f"当前 proof_status={proof_status}，不能视为 fully MechLib verified。"


def _step_formula_displays(step: SolutionStep, formula_ids: set[str] | None = None) -> list[str]:
    out: list[str] = []
    for formula in step.output_formulas:
        if formula_ids is not None and formula.formula_id not in formula_ids:
            continue
        text = formula.display_formula or formula.formal_formula
        if text:
            out.append(text)
    return out


def _find_two_body_algebra_step(solution_trace: SolutionTrace) -> SolutionStep | None:
    for step in solution_trace.steps:
        if step.kind != "algebra_elimination":
            continue
        if step.notes == "deterministic_two_body_linear_system":
            return step
    return None


def _render_textbook_two_body_solution(solution_trace: SolutionTrace) -> str | None:
    algebra_step = _find_two_body_algebra_step(solution_trace)
    if algebra_step is None:
        return None
    final_displays = [formula.display_formula or formula.formal_formula for formula in solution_trace.final_answers]
    if len(final_displays) < 2:
        return None

    substitution = _step_formula_displays(algebra_step, {"two_body_substitution"})
    collected = _step_formula_displays(algebra_step, {"two_body_collect_terms"})
    denominator = _step_formula_displays(algebra_step, {"two_body_denominator_nonzero"})
    if not substitution or not collected:
        return None

    a_formula = next((text for text in final_displays if _canon_formula_for_pattern(text).startswith("a=")), final_displays[0])
    t_formula = next((text for text in final_displays if _canon_formula_for_pattern(text).startswith("t=")), final_displays[-1])

    lines = [
        "设小车质量为 m₁，悬挂物质量为 m₂，系统共同加速度为 a，绳中张力为 T。取小车运动方向和悬挂物向下方向为正方向。",
        "",
        "对小车进行受力分析，水平方向合力为绳的张力 T。对小车应用牛顿第二定律，得到",
        "",
        "T = m₁a。        (1)",
        "",
        "对悬挂物进行受力分析，取向下为正方向，其合力为 m₂g - T。对悬挂物应用牛顿第二定律，得到",
        "",
        "m₂g - T = m₂a。  (2)",
        "",
        "由 (1) 和 (2) 联立，代入 T = m₁a，有",
        "",
        f"{substitution[0]},",
        "",
        "即",
        "",
        f"{collected[0]}。",
        "",
    ]
    if denominator:
        lines.extend([
            f"由于 m₁ 和 m₂ 均为正，{denominator[0]}，因此",
            "",
        ])
    lines.extend([
        f"{a_formula}。",
        "",
        "再代回 T = m₁a，得到",
        "",
        f"{t_formula}。",
        "",
        "所以",
        "",
        f"{a_formula},",
        f"{t_formula}。",
        "",
        _status_disclosure(solution_trace.proof_status),
    ])
    if solution_trace.warnings and solution_trace.proof_status != "fully_mechlib_verified":
        lines.append("结构化警告：" + "; ".join(solution_trace.warnings))
    return "\n".join(lines)


def render_deterministic_solution(solution_trace: SolutionTrace) -> str:
    textbook = _render_textbook_two_body_solution(solution_trace)
    if textbook:
        return textbook

    lines: list[str] = []
    lines.append("1. 题意与符号说明")
    if solution_trace.target_display:
        lines.append(f"目标公式：{solution_trace.target_display}")
    else:
        lines.append("目标公式未能从结构化 artifact 中可靠提取。")
    lines.append("")
    lines.append("2. 建模与物理定律应用")
    for step in solution_trace.steps:
        if step.kind not in {"modeling", "law_application", "definition_merge"}:
            continue
        status = "已验证" if step.verified else "未验证"
        detail = step.display_formula or step.text_intent or step.title
        decl = f"；verified_decl={step.verified_decl}" if step.verified_decl else ""
        lines.append(f"- [{status}] {step.title}: {detail}{decl}")
    lines.append("")
    lines.append("3. 联立方程/代数求解")
    algebra_steps = [step for step in solution_trace.steps if step.kind == "algebra_elimination"]
    if algebra_steps:
        for step in algebra_steps:
            status = "已验证" if step.verified else "未验证"
            detail = step.display_formula or step.text_intent or step.title
            lines.append(f"- [{status}] {detail}")
    else:
        lines.append("- 未发现结构化 algebra_obligation；不补写额外代数步骤。")
    lines.append("")
    lines.append("4. 最终答案")
    if solution_trace.final_answers:
        for formula in solution_trace.final_answers:
            status = "已验证" if formula.verified else "未验证"
            lines.append(f"- [{status}] {formula.display_formula or formula.formal_formula}")
    else:
        lines.append("- 未能从 theorem target 提取最终答案。")
    lines.append("")
    lines.append("5. 形式化验证说明")
    lines.append(_status_disclosure(solution_trace.proof_status))
    if solution_trace.warnings:
        lines.append("结构化警告：" + "; ".join(solution_trace.warnings))
    return "\n".join(lines)


def _normalize_formula(text: str | None) -> str:
    if text is None:
        return ""
    return re.sub(r"\s+", "", str(text)).strip().lower()


def _formula_mentions(formula: SolutionFormula) -> list[str]:
    out = [formula.formal_formula, formula.display_formula or ""]
    lhs = formula.display_formula or formula.formal_formula
    if "=" in lhs:
        out.append(lhs.split("=", 1)[0].strip())
    return [item for item in out if item]


def _final_answer_mentions(formula: SolutionFormula) -> list[str]:
    return [item for item in [formula.formal_formula, formula.display_formula or ""] if item]


def _contains_token(text: str, token: str | None) -> bool:
    if not token:
        return False
    return token in text or _normalize_formula(token) in _normalize_formula(text)


def _all_trace_formula_text(solution_trace: SolutionTrace) -> set[str]:
    texts: set[str] = set()
    for value in (solution_trace.target_formal, solution_trace.target_display):
        if value:
            texts.add(_normalize_formula(value))
    for formula in solution_trace.final_answers:
        for item in _formula_mentions(formula):
            texts.add(_normalize_formula(item))
    for step in solution_trace.steps:
        for value in (step.formal_formula, step.display_formula):
            if value:
                texts.add(_normalize_formula(value))
        for formula in list(step.input_formulas) + list(step.output_formulas):
            for item in _formula_mentions(formula):
                texts.add(_normalize_formula(item))
    return {item for item in texts if item}


def _extract_formula_like_lines(text: str) -> list[str]:
    out: list[str] = []
    for line in text.splitlines():
        for segment in re.split(r"[。；;，,]", line):
            stripped = segment.strip()
            if not stripped or "verified_decl=" in stripped or "proof_status" in stripped:
                continue
            if "=" in stripped and re.search(r"[A-Za-z0-9_μ₀₁₂₃₄₅₆₇₈₉]", stripped):
                out.append(stripped)
            elif "/" in stripped and re.search(
                r"[A-Za-z_μ₀₁₂₃₄₅₆₇₈₉][A-Za-z0-9_μ₀₁₂₃₄₅₆₇₈₉ ]*/[ A-Za-z0-9_μ₀₁₂₃₄₅₆₇₈₉]*[A-Za-z_μ₀₁₂₃₄₅₆₇₈₉]",
                stripped,
            ):
                out.append(stripped)
    return out


def _unsupported_formula_count(solution_trace: SolutionTrace, natural_solution: str) -> int:
    allowed = _all_trace_formula_text(solution_trace)
    count = 0
    for line in _extract_formula_like_lines(natural_solution):
        normalized = _normalize_formula(line)
        if any(token and token in normalized for token in allowed):
            continue
        count += 1
    return count


def audit_rendered_solution(
    *,
    solution_trace: SolutionTrace,
    natural_solution: str,
    llm_payload: dict[str, Any],
) -> SolutionRenderAudit:
    text = str(natural_solution or "")
    failure_tags: list[str] = []
    final_answers = list(solution_trace.final_answers)
    if final_answers:
        final_coverage = all(
            any(_contains_token(text, mention) for mention in _final_answer_mentions(formula))
            for formula in final_answers
        )
    else:
        final_coverage = True
    if not final_coverage:
        failure_tags.append("final_answer_missing")

    verified_laws = [step for step in solution_trace.steps if step.kind == "law_application" and step.verified]
    if verified_laws:
        law_coverage = all(
            any(
                _contains_token(text, token)
                for token in (
                    step.title,
                    step.display_formula,
                    step.formal_formula,
                    step.verified_decl,
                    step.verified_decl.rsplit(".", 1)[-1] if step.verified_decl else None,
                )
            )
            for step in verified_laws
        )
    else:
        law_coverage = True
    if not law_coverage:
        failure_tags.append("verified_law_step_missing")

    unsupported_count = _unsupported_formula_count(solution_trace, text)
    if unsupported_count > 0:
        failure_tags.append("unsupported_formula")

    status = solution_trace.proof_status
    lowered = text.lower()
    needs_gap_disclosure = any(token in status for token in ("gap", "partial", "algebra_only"))
    gap_disclosure = True
    if needs_gap_disclosure:
        gap_disclosure = any(token in lowered for token in ("gap", "partial", "未完全", "部分", "缺少", "不能计为"))
        if not gap_disclosure:
            failure_tags.append("gap_or_partial_not_disclosed")

    proof_status_disclosure = True
    if status == "legacy_verified_no_audit":
        proof_status_disclosure = ("dependency audit" in lowered or "依赖审计" in text or "缺少" in text) and (
            "不能确认" in text or "不能计为" in text or "缺少" in text
        )
        if not proof_status_disclosure:
            failure_tags.append("legacy_no_audit_not_disclosed")
        if "fully_mechlib_verified" in lowered or ("均已由 Lean 验证" in text and "缺少" not in text):
            failure_tags.append("legacy_no_audit_overclaimed")
            proof_status_disclosure = False
    elif status in {"proof_failed", "proof_skipped_due_to_semantic_fail", "not_checked"}:
        proof_status_disclosure = any(token in text for token in ("未通过", "被跳过", "未验证", "只展示", "不能视为"))
        if "已由 Lean 验证" in text or "Lean proof 已通过" in text:
            proof_status_disclosure = False
            failure_tags.append("failed_proof_overclaimed")
        if not proof_status_disclosure:
            failure_tags.append("proof_failure_not_disclosed")
    elif status == "fully_mechlib_verified":
        proof_status_disclosure = "Lean" in text or "验证" in text
        if not proof_status_disclosure:
            failure_tags.append("verified_status_not_disclosed")

    target_match = final_coverage
    render_success = bool(text.strip())
    if not render_success:
        failure_tags.append("empty_natural_solution")

    audit_pass = render_success and final_coverage and law_coverage and unsupported_count == 0 and gap_disclosure and proof_status_disclosure and target_match
    return SolutionRenderAudit(
        sample_id=solution_trace.sample_id,
        candidate_id=solution_trace.candidate_id,
        render_success=render_success,
        audit_pass=audit_pass,
        failure_tags=failure_tags,
        failure_summary="; ".join(failure_tags) if failure_tags else None,
        formula_coverage_pass=final_coverage,
        law_step_coverage_pass=law_coverage,
        unsupported_formula_count=unsupported_count,
        gap_disclosure_pass=gap_disclosure,
        proof_status_disclosure_pass=proof_status_disclosure,
        target_match_pass=target_match,
        details={
            "proof_status": status,
            "llm_used_step_ids": llm_payload.get("used_step_ids") if isinstance(llm_payload, dict) else None,
            "llm_mentioned_formulas": llm_payload.get("mentioned_formulas") if isinstance(llm_payload, dict) else None,
        },
    )


class ModuleSolutionRenderer:
    def __init__(self, model_client=None, prompt_path: Path | None = None, config=None):
        self.model_client = model_client
        self.prompt_path = prompt_path
        self.config = config
        self.template = load_template(prompt_path, DEFAULT_RENDER_PROMPT) if prompt_path else DEFAULT_RENDER_PROMPT

    def _config_bool(self, name: str, default: bool) -> bool:
        return bool(getattr(self.config, name, default)) if self.config is not None else default

    def _config_int(self, name: str, default: int) -> int:
        value = getattr(self.config, name, default) if self.config is not None else default
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _call_llm(self, solution_trace: SolutionTrace, *, repair_context: dict[str, Any] | None = None) -> tuple[str | None, dict[str, Any], str | None]:
        if self.model_client is None:
            return None, {}, "model_client_missing"
        prompt = build_solution_renderer_prompt(
            solution_trace=solution_trace,
            template=self.template,
            max_steps=self._config_int("max_trace_steps_for_prompt", 24),
            max_chars=self._config_int("max_prompt_chars", 8000),
        )
        if repair_context:
            prompt += "\n\n审计失败信息，只能基于同一个 SolutionTrace 修订，不得新增公式：\n"
            prompt += json.dumps(repair_context, ensure_ascii=False, indent=2)
        response = self.model_client.generate_text(prompt)
        raw = str(getattr(response, "text", response))
        payload = extract_json_object(raw) or {}
        natural = str(payload.get("natural_solution") or "").strip() if isinstance(payload, dict) else ""
        if not natural:
            return raw, payload if isinstance(payload, dict) else {}, "llm_json_missing_natural_solution"
        return raw, payload, None

    def run(
        self,
        *,
        sample,
        grounding,
        model_ir,
        controlled_sketch,
        selected_candidate,
        proof_attempts,
        proof_check,
        proof_search_trace=None,
        dependency_audit=None,
    ) -> SolutionRenderResult:
        sample_payload = _to_payload(sample)
        problem_ir = None
        grounding_payload = _to_payload(grounding)
        if grounding_payload:
            problem_ir = grounding_payload.get("problem_ir")
        if problem_ir is None and sample_payload:
            problem_ir = {"problem_text": sample_payload.get("problem_text"), "sample_id": sample_payload.get("sample_id")}

        evidence = collect_solution_evidence(
            problem_ir=problem_ir,
            model_ir=_to_payload(model_ir),
            controlled_sketch=_to_payload(controlled_sketch),
            theorem_candidate=_to_payload(selected_candidate),
            proof_attempt=_list_payload(proof_attempts),
            proof_check=_to_payload(proof_check),
            proof_search_trace=_to_payload(proof_search_trace),
            dependency_audit=_to_payload(dependency_audit),
        )
        trace = build_solution_trace(evidence)
        raw_llm: str | None = None
        llm_payload: dict[str, Any] = {}
        error: str | None = None
        natural_solution = ""
        preferred_deterministic = _render_textbook_two_body_solution(trace)
        if preferred_deterministic:
            natural_solution = preferred_deterministic
            llm_payload = {
                "natural_solution": natural_solution,
                "used_step_ids": [step.step_id for step in trace.steps],
                "mentioned_formulas": [
                    formula.display_formula or formula.formal_formula
                    for formula in trace.final_answers
                ],
                "verification_note": _status_disclosure(trace.proof_status),
                "renderer": "deterministic_textbook_two_body",
            }
        elif self._config_bool("natural_language_enabled", False):
            try:
                raw_llm, llm_payload, error = self._call_llm(trace)
                natural_solution = str(llm_payload.get("natural_solution") or "").strip() if not error else ""
            except Exception as exc:
                natural_solution = ""
                error = f"llm_render_failed:{type(exc).__name__}:{exc}"

        if not natural_solution:
            natural_solution = render_deterministic_solution(trace)
            if error:
                trace.warnings.append(error)
            llm_payload = {
                "natural_solution": natural_solution,
                "used_step_ids": [step.step_id for step in trace.steps],
                "mentioned_formulas": [
                    formula.display_formula or formula.formal_formula
                    for formula in trace.final_answers
                ],
                "verification_note": _status_disclosure(trace.proof_status),
                "renderer": "deterministic_fallback",
            }

        audit = audit_rendered_solution(
            solution_trace=trace,
            natural_solution=natural_solution,
            llm_payload=llm_payload,
        )
        if (
            not audit.audit_pass
            and self._config_bool("natural_language_enabled", False)
            and self._config_bool("repair_on_audit_fail", True)
        ):
            try:
                repair_raw, repair_payload, repair_error = self._call_llm(
                    trace,
                    repair_context={
                        "failure_tags": audit.failure_tags,
                        "failure_summary": audit.failure_summary,
                        "previous_solution_excerpt": truncate(natural_solution, 1200),
                    },
                )
                if repair_raw:
                    raw_llm = repair_raw
                repaired_solution = str(repair_payload.get("natural_solution") or "").strip() if not repair_error else ""
                if repaired_solution:
                    repaired_audit = audit_rendered_solution(
                        solution_trace=trace,
                        natural_solution=repaired_solution,
                        llm_payload=repair_payload,
                    )
                    if repaired_audit.audit_pass or len(repaired_audit.failure_tags) <= len(audit.failure_tags):
                        natural_solution = repaired_solution
                        llm_payload = repair_payload
                        audit = repaired_audit
                elif repair_error and error is None:
                    error = repair_error
            except Exception as exc:
                if error is None:
                    error = f"llm_repair_failed:{type(exc).__name__}:{exc}"

        if not audit.audit_pass:
            fallback_solution = render_deterministic_solution(trace)
            fallback_payload = {
                "natural_solution": fallback_solution,
                "used_step_ids": [step.step_id for step in trace.steps],
                "mentioned_formulas": [
                    formula.display_formula or formula.formal_formula
                    for formula in trace.final_answers
                ],
                "verification_note": _status_disclosure(trace.proof_status),
                "renderer": "deterministic_audit_fallback",
            }
            fallback_audit = audit_rendered_solution(
                solution_trace=trace,
                natural_solution=fallback_solution,
                llm_payload=fallback_payload,
            )
            if fallback_audit.audit_pass or len(fallback_audit.failure_tags) < len(audit.failure_tags):
                natural_solution = fallback_solution
                llm_payload = fallback_payload
                audit = fallback_audit

        return SolutionRenderResult(
            sample_id=trace.sample_id,
            candidate_id=trace.candidate_id,
            render_success=bool(natural_solution.strip()),
            proof_status=trace.proof_status,
            solution_trace=trace,
            natural_solution=natural_solution,
            render_audit=audit,
            raw_llm_response=raw_llm,
            error=error,
        )
