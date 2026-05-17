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
你正在把一个结构化解题叙述计划渲染成中文力学解题流程。
不要重新解题。不要新增公式。不要新增物理定律。不要修改最终答案。
不要隐藏 gap、partial、legacy/no-audit、proof_failed 状态。
只能使用 renderer_plan / solution_trace_summary 中的步骤、公式和验证状态。优先使用 renderer_plan；solution_trace_summary 只作为追溯依据。
不要输入或依赖完整 Lean proof、完整 MechLib context、完整 theorem corpus、完整 raw_response。
写成教材式中文解题过程：先说明要求解的量和建模约定，再按建模方程/物理方程编号，最后展示可用的代数中间式和最终答案。
不要写“目标公式：”“轨迹中给出”“按轨迹中的目标结果可得”“结构化 artifact”等内部流水线措辞。
不要用项目符号罗列 artifact；自然段和独立公式行优先。
如果 renderer_plan 没有某个中间公式，不要补写该公式。
不要把 target_display 直接作为“目标公式”抄在开头；开头只说明“本题要求求出/证明”的量或关系。
公式编号应服务于解题叙述，例如“得到 ... (1)”“联立 (1)(2)”。不要暴露 step_id、verified_decl、source_artifacts 等内部字段名。
可以把 renderer_plan.symbol_intro、numbered_equations[].narrative_intro 和 algebra_exposition[].text 改写成更自然的中文，但不能改变其公式和验证含义。
如果 renderer_plan 给出了 modeling_notes，可以翻译成必要的受力分析、正方向和建模说明；不要照抄英文。

输出 JSON，格式必须是：
{
  "natural_solution": "...",
  "used_step_ids": ["..."],
  "mentioned_formulas": ["..."],
  "verification_note": "..."
}

Renderer input:
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


def _formula_key_variants(text: str | None) -> set[str]:
    key = _canon_formula_for_pattern(text)
    if not key:
        return set()
    return {key, key.replace("(", "").replace(")", "")}


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


def _formula_strings_from_steps(steps: list[SolutionStep]) -> list[str]:
    formulas: list[str] = []
    for step in steps:
        for value in (step.formal_formula, step.display_formula):
            if value:
                formulas.append(value)
        for formula in list(step.input_formulas) + list(step.output_formulas):
            formulas.append(formula.formal_formula)
            if formula.display_formula:
                formulas.append(formula.display_formula)
    return [formula for formula in formulas if formula]


def _looks_like_formula(text: str | None) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    if not any(token in value for token in ("=", "≠", "<", ">", "≤", "≥", "\\frac")):
        return False
    if any(marker in value for marker in (". ", ";", "；", "。")):
        return False
    if re.search(r"\b(The|Because|This|Model|Treat|Use|Apply|where|and this)\b", value):
        return False
    return len(value) <= 180


def _accepted_action_formula_step(
    accepted_actions: list[dict[str, Any]],
    *,
    proof_status: str,
) -> SolutionStep | None:
    formulas: list[SolutionFormula] = []
    seen: set[str] = set()
    for action in accepted_actions:
        action_id = str(action.get("action_id") or "").strip()
        claims = _str_list(action.get("new_local_fact_claims")) or _str_list(action.get("proposed_local_fact_claims"))
        for idx, claim in enumerate(claims, start=1):
            if not _looks_like_formula(claim):
                continue
            key = _canon_formula_for_pattern(claim)
            if key in seen:
                continue
            seen.add(key)
            formula = _formula(
                f"accepted_action_{len(formulas) + 1}",
                claim,
                source="ProofSearchTrace.accepted_actions",
                verified=proof_status in SUCCESS_STATUSES,
            )
            if formula:
                formula.provenance.append(action_id or f"accepted_action_{idx}")
                formulas.append(formula)
    if not formulas:
        return None
    return SolutionStep(
        step_id="accepted_proof_actions_1",
        kind="algebra_elimination",
        title="代数推导与目标闭合",
        text_intent="E 阶段 accepted proof actions 产生的中间关系。",
        output_formulas=formulas,
        source_artifacts=["ProofSearchTrace.accepted_actions"],
        verified=proof_status in SUCCESS_STATUSES,
        gap_assisted=proof_status == "gap_assisted_success",
        notes="accepted_action_formula_chain",
    )


def _two_body_linear_algebra_step(
    *,
    steps: list[SolutionStep],
    final_answers: list[SolutionFormula],
    proof_status: str,
    accepted_actions: list[dict[str, Any]],
) -> SolutionStep | None:
    trace_formulas = _formula_strings_from_steps(steps)
    if not _trace_has_formula(trace_formulas, "T = m1 * a"):
        return None
    if not _trace_has_formula(trace_formulas, "m2 * g - T = m2 * a"):
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
            "SolutionTrace.steps",
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
    model_summaries: list[dict[str, Any]] = []
    for item in instances[:4]:
        text = _first_text(item.get("natural_language"), item.get("kind"), item.get("instance_id"))
        if text:
            descriptions.append(text)
        model_summaries.append(
            {
                "instance_id": item.get("instance_id"),
                "kind": item.get("kind"),
                "natural_language": item.get("natural_language"),
                "variables": item.get("variables") if isinstance(item.get("variables"), dict) else {},
                "coordinate_convention": item.get("coordinate_convention"),
                "expected_claim": item.get("expected_claim"),
                "planning_schema_id": item.get("planning_schema_id"),
            }
        )
    instantiation_summaries = [
        {
            "instantiation_id": item.get("instantiation_id"),
            "kind": item.get("kind"),
            "formal_claim": item.get("formal_claim"),
            "display_formula": pretty_print_formula(str(item.get("formal_claim") or "")) if item.get("formal_claim") else None,
            "source_model_instance": item.get("source_model_instance"),
            "interface_name": item.get("interface_name"),
            "notes": item.get("notes"),
            "binding_status": item.get("binding_status"),
        }
        for item in interface_instantiations[:24]
    ]
    text_intent = "; ".join(descriptions) if descriptions else "根据 ModelIR 建立对象、变量、约束和局部定义。"
    return SolutionStep(
        step_id="modeling_1",
        kind="modeling",
        title="建立力学模型",
        text_intent=text_intent,
        output_formulas=formulas,
        source_artifacts=["ModelIR", "TheoremSkeletonCandidate.hypothesis_provenance"],
        verified=False,
        notes=json.dumps(
            {
                "model_instances": model_summaries,
                "interface_instantiations": instantiation_summaries,
            },
            ensure_ascii=False,
        ),
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

    accepted_action_step = _accepted_action_formula_step(accepted_actions, proof_status=proof_status)
    if accepted_action_step is not None:
        steps.append(accepted_action_step)

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
    step_summaries: list[dict[str, Any]] = []
    for step in payload.get("steps", [])[:max_steps]:
        step_summaries.append(
            {
                "step_id": step.get("step_id"),
                "kind": step.get("kind"),
                "title": step.get("title"),
                "text_intent": truncate(str(step.get("text_intent") or ""), 260),
                "proof_obligation_id": step.get("proof_obligation_id"),
                "verified_decl": step.get("verified_decl"),
                "verified": step.get("verified"),
                "gap_assisted": step.get("gap_assisted"),
            }
        )
    trace_summary = {
        "sample_id": solution_trace.sample_id,
        "candidate_id": solution_trace.candidate_id,
        "proof_status": solution_trace.proof_status,
        "target_formal": solution_trace.target_formal,
        "target_display": solution_trace.target_display,
        "steps": step_summaries,
        "final_answers": [
            {
                "formula_id": formula.formula_id,
                "formal_formula": formula.formal_formula,
                "display_formula": formula.display_formula,
                "verified": formula.verified,
            }
            for formula in solution_trace.final_answers
        ],
        "warnings": solution_trace.warnings,
    }
    trace_summary["source_status"] = {
        key: value
        for key, value in dict(payload.get("source_status") or {}).items()
        if isinstance(value, bool)
    }
    renderer_plan = _build_narrative_plan(solution_trace)
    prompt_plan = dict(renderer_plan)
    prompt_plan["equation_source_counts"] = {
        "modeling_equations": len(_list_payload(renderer_plan.get("modeling_equations"))),
        "law_equations": len(_list_payload(renderer_plan.get("law_equations"))),
        "algebra_steps": len(_list_payload(renderer_plan.get("algebra_steps"))),
    }
    prompt_plan["modeling_notes"] = [
        truncate(str(note), 180)
        for note in _str_list(renderer_plan.get("modeling_notes"))[:3]
    ]
    # The prompt should preserve the curated narrative plan, not duplicate every
    # auxiliary equation already available in solution_trace.jsonl.
    prompt_plan.pop("modeling_equations", None)
    prompt_plan.pop("law_equations", None)
    prompt_plan.pop("algebra_steps", None)
    return {
        "renderer_plan": prompt_plan,
        "solution_trace_summary": trace_summary,
    }


def build_solution_renderer_prompt(
    *,
    solution_trace: SolutionTrace,
    template: str | None = None,
    max_steps: int = 24,
    max_chars: int = 12000,
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
        return "本题 Lean replay 已通过，但其中部分建模关系依赖 gap law，不能计为 fully MechLib verified。"
    if proof_status == "proof_failed":
        return "当前形式化证明未通过，因此以下只展示已构造的建模和计划步骤，不作为最终 verified solution。"
    if proof_status == "proof_skipped_due_to_semantic_fail":
        return "当前证明阶段因语义检查失败被跳过，因此以下只展示已构造的建模和计划步骤，不作为最终 verified solution。"
    if proof_status == "partial_mechlib_verified":
        return "当前只有部分物理步骤被 MechLib 依赖审计覆盖，未覆盖步骤不能视为 fully MechLib verified。"
    if proof_status == "algebra_only_success":
        return "当前 proof 主要验证了代数目标，但缺少必要的 MechLib verified declaration 覆盖，不能计为 fully MechLib verified。"
    return f"当前 proof_status={proof_status}，不能视为 fully MechLib verified。"


def _formula_display(formula: SolutionFormula) -> str:
    return str(formula.display_formula or formula.formal_formula or "").strip()


def _append_formula_record(
    records: list[dict[str, Any]],
    seen: set[str],
    *,
    formula_id: str,
    formal: str | None,
    display: str | None = None,
    role: str,
    step_id: str | None,
    step_title: str | None,
    verified: bool,
    source: str | None = None,
    text_intent: str | None = None,
) -> None:
    text = str(formal or display or "").strip()
    if not _looks_like_formula(text):
        return
    key = _canon_formula_for_pattern(text)
    if not key or key in seen:
        return
    seen.add(key)
    records.append(
        {
            "formula_id": formula_id,
            "formal_formula": text,
            "display_formula": display or pretty_print_formula(text),
            "role": role,
            "step_id": step_id,
            "step_title": step_title,
            "text_intent": text_intent,
            "verified": verified,
            "source": source,
        }
    )


def _target_variables(solution_trace: SolutionTrace) -> list[str]:
    out: list[str] = []
    for formula in solution_trace.final_answers:
        text = formula.display_formula or formula.formal_formula
        if "=" not in text:
            continue
        lhs = text.split("=", 1)[0].strip()
        if lhs and len(lhs) <= 40 and lhs not in out:
            out.append(lhs)
    return out


def _load_json_object(text: str | None) -> dict[str, Any]:
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _modeling_context(solution_trace: SolutionTrace) -> dict[str, Any]:
    model_instances: list[dict[str, Any]] = []
    interface_instantiations: list[dict[str, Any]] = []
    for step in solution_trace.steps:
        if step.kind != "modeling":
            continue
        payload = _load_json_object(step.notes)
        model_instances.extend(_list_payload(payload.get("model_instances")))
        interface_instantiations.extend(_list_payload(payload.get("interface_instantiations")))
    instances_by_id = {
        str(item.get("instance_id")): item
        for item in model_instances
        if str(item.get("instance_id") or "").strip()
    }
    interfaces_by_formula: dict[str, list[dict[str, Any]]] = {}
    for item in interface_instantiations:
        for value in (item.get("formal_claim"), item.get("display_formula")):
            for key in _formula_key_variants(value):
                interfaces_by_formula.setdefault(key, []).append(item)
    return {
        "model_instances": model_instances,
        "interface_instantiations": interface_instantiations,
        "instances_by_id": instances_by_id,
        "interfaces_by_formula": interfaces_by_formula,
    }


def _object_label(model_summary: dict[str, Any] | None) -> str | None:
    text = " ".join(
        str((model_summary or {}).get(key) or "")
        for key in ("kind", "natural_language", "expected_claim", "coordinate_convention")
    ).lower()
    if any(token in text for token in ("glider", "cart", "block on", "track")):
        return "小车"
    if any(token in text for token in ("hanging", "lab weight", "weight")):
        return "悬挂物"
    if "pulley" in text or "string" in text:
        return "绳-滑轮约束"
    if "spring" in text:
        return "弹簧连接物体"
    if "projectile" in text:
        return "抛体"
    if "particle" in text:
        return "质点"
    return None


def _display_symbol(symbol: str | None) -> str:
    text = str(symbol or "").strip()
    if not text:
        return ""
    return pretty_print_formula(text)


def _symbols_in_records(records: list[dict[str, Any]]) -> set[str]:
    text = " ".join(str(record.get("formal_formula") or "") for record in records)
    return set(re.findall(r"\b[A-Za-z][A-Za-z0-9_]*\b", text))


def _symbol_intro(context: dict[str, Any], target_variables: list[str], equation_records: list[dict[str, Any]]) -> str | None:
    model_instances = _list_payload(context.get("model_instances"))
    symbols = _symbols_in_records(equation_records)
    for variable in target_variables:
        symbols.update(re.findall(r"\b[A-Za-z][A-Za-z0-9_]*\b", variable))
    has_glider = any(_object_label(item) == "小车" for item in model_instances)
    has_hanging = any(_object_label(item) == "悬挂物" for item in model_instances)
    if has_glider and has_hanging and {"m1", "m2", "a", "T"}.issubset(symbols):
        return "设小车质量为 m₁，悬挂物质量为 m₂，系统共同加速度为 a，绳中张力为 T。取小车运动方向和悬挂物向下方向为正方向。"

    phrases: list[str] = []
    seen_symbols: set[str] = set()
    for item in model_instances:
        label = _object_label(item)
        variables = item.get("variables") if isinstance(item.get("variables"), dict) else {}
        mass = str(variables.get("mass") or "").strip()
        if mass and mass not in seen_symbols:
            phrases.append(f"{label + '的' if label else ''}质量为 {_display_symbol(mass)}")
            seen_symbols.add(mass)
    shared: list[str] = []
    for item in model_instances:
        variables = item.get("variables") if isinstance(item.get("variables"), dict) else {}
        for role, label in (("acceleration", "加速度"), ("tension", "张力"), ("gravity", "重力加速度")):
            symbol = str(variables.get(role) or "").strip()
            if symbol and symbol not in seen_symbols:
                shared.append(f"{label}为 {_display_symbol(symbol)}")
                seen_symbols.add(symbol)
    if phrases or shared:
        intro = "设" + "，".join(phrases + shared) + "。"
        if any(str(item.get("coordinate_convention") or "").strip() for item in model_instances):
            intro += "正方向按建模阶段给出的坐标约定选取。"
        return intro
    if target_variables:
        return f"本题要求求出 {', '.join(target_variables)}，并使用建模阶段给出的符号和正方向约定。"
    return None


def _record_interfaces(record: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
    keys = _formula_key_variants(record.get("formal_formula")) | _formula_key_variants(record.get("display_formula"))
    out: list[dict[str, Any]] = []
    interfaces_by_formula = context.get("interfaces_by_formula") if isinstance(context.get("interfaces_by_formula"), dict) else {}
    for key in keys:
        out.extend(_list_payload(interfaces_by_formula.get(key)))
    return _dedupe_dicts(out, "instantiation_id")


def _record_model_summary(record: dict[str, Any], context: dict[str, Any]) -> dict[str, Any] | None:
    interfaces = _record_interfaces(record, context)
    instances_by_id = context.get("instances_by_id") if isinstance(context.get("instances_by_id"), dict) else {}
    for item in interfaces:
        source_id = str(item.get("source_model_instance") or "").strip()
        summary = instances_by_id.get(source_id)
        if isinstance(summary, dict):
            return summary
    return None


def _record_narrative_intro(record: dict[str, Any], context: dict[str, Any]) -> str:
    formula = str(record.get("formal_formula") or record.get("display_formula") or "")
    canon = _canon_formula_for_pattern(formula)
    model_summary = _record_model_summary(record, context)
    label = _object_label(model_summary)
    model_text = " ".join(
        str((model_summary or {}).get(key) or "")
        for key in ("kind", "natural_language", "expected_claim", "coordinate_convention", "planning_schema_id")
    ).lower()
    if canon == "t=m1a" and label == "小车":
        return "对小车进行受力分析，水平方向合力为绳的张力 T。对小车应用牛顿第二定律，得到"
    if canon == "t=m1a":
        return "对与 m₁ 对应的物体沿所取正方向应用牛顿第二定律，得到"
    if canon == "m2g-t=m2a" and label == "悬挂物":
        return "对悬挂物进行受力分析，取向下为正方向，其合力为 m₂g - T。对悬挂物应用牛顿第二定律，得到"
    if canon == "m2g-t=m2a":
        return "对与 m₂ 对应的物体沿所取正方向应用牛顿第二定律，得到"
    if label and "newton" in model_text:
        return f"对{label}沿所取正方向应用牛顿第二定律，得到"
    if _mentions_friction_model(model_text, formula=formula, canon=canon):
        return "根据摩擦模型和临界条件，得到"
    if "constraint" in model_text or "constraint" in str(record.get("role") or ""):
        return "由约束关系得到"
    text_intent = str(record.get("text_intent") or "").strip()
    if text_intent and not re.search(r"[A-Za-z]{4,}", text_intent):
        return f"{text_intent}，得到"
    return "由建模关系得到"


def _build_narrative_plan(solution_trace: SolutionTrace) -> dict[str, Any]:
    final_answers = [
        {
            "formula_id": formula.formula_id,
            "formal_formula": formula.formal_formula,
            "display_formula": _formula_display(formula),
            "verified": formula.verified,
        }
        for formula in solution_trace.final_answers
    ]
    final_keys: set[str] = set()
    for item in final_answers:
        final_keys.update(_formula_key_variants(item["formal_formula"]))
        final_keys.update(_formula_key_variants(item["display_formula"]))

    modeling_equations: list[dict[str, Any]] = []
    law_equations: list[dict[str, Any]] = []
    algebra_steps: list[dict[str, Any]] = []
    seen_model: set[str] = set()
    seen_law: set[str] = set()
    seen_algebra: set[str] = set()
    modeling_notes: list[str] = []
    context = _modeling_context(solution_trace)

    for step in solution_trace.steps:
        if step.kind == "modeling" and step.text_intent:
            modeling_notes.append(step.text_intent)
        if step.kind in {"modeling", "law_application"}:
            target = law_equations if step.kind == "law_application" else modeling_equations
            seen = seen_law if step.kind == "law_application" else seen_model
            _append_formula_record(
                target,
                seen,
                formula_id=f"{step.step_id}_formula",
                formal=step.formal_formula,
                display=step.display_formula,
                role=step.kind,
                step_id=step.step_id,
                step_title=step.title,
                verified=step.verified,
                source=step.verified_decl,
                text_intent=step.text_intent,
            )
            for formula in step.output_formulas:
                _append_formula_record(
                    target,
                    seen,
                    formula_id=formula.formula_id,
                    formal=formula.formal_formula,
                    display=formula.display_formula,
                    role=step.kind,
                    step_id=step.step_id,
                    step_title=step.title,
                    verified=step.verified or formula.verified,
                    source=formula.source or step.verified_decl,
                    text_intent=step.text_intent,
                )
        if step.kind == "algebra_elimination":
            _append_formula_record(
                algebra_steps,
                seen_algebra,
                formula_id=f"{step.step_id}_formula",
                formal=step.formal_formula,
                display=step.display_formula,
                role=step.notes or "algebra_elimination",
                step_id=step.step_id,
                step_title=step.title,
                verified=step.verified,
                source=";".join(step.source_artifacts),
                text_intent=step.text_intent,
            )
            for formula in step.output_formulas:
                key_variants = _formula_key_variants(formula.formal_formula) | _formula_key_variants(formula.display_formula)
                role = "final_answer_from_proof_action" if key_variants & final_keys else (step.notes or "algebra_elimination")
                _append_formula_record(
                    algebra_steps,
                    seen_algebra,
                    formula_id=formula.formula_id,
                    formal=formula.formal_formula,
                    display=formula.display_formula,
                    role=role,
                    step_id=step.step_id,
                    step_title=step.title,
                    verified=step.verified or formula.verified,
                    source=formula.source,
                    text_intent=step.text_intent,
                )

    target_variables = _target_variables(solution_trace)
    numbered_equations = _select_numbered_equations(
        modeling_equations + law_equations,
        target_variables=target_variables,
    )
    for idx, record in enumerate(numbered_equations, start=1):
        record["equation_number"] = idx
        record["narrative_intro"] = _record_narrative_intro(record, context)
    algebra_exposition = _build_algebra_exposition(
        numbered_equations=numbered_equations,
        algebra_steps=algebra_steps,
        final_answers=final_answers,
    )

    return {
        "sample_id": solution_trace.sample_id,
        "candidate_id": solution_trace.candidate_id,
        "proof_status": solution_trace.proof_status,
        "target_variables": target_variables,
        "target_display": solution_trace.target_display,
        "symbol_intro": _symbol_intro(context, target_variables, numbered_equations),
        "modeling_notes": modeling_notes[:4],
        "modeling_equations": modeling_equations,
        "law_equations": law_equations,
        "numbered_equations": numbered_equations,
        "algebra_steps": algebra_steps,
        "algebra_exposition": algebra_exposition,
        "final_answers": final_answers,
        "verification_note": _status_disclosure(solution_trace.proof_status),
        "warnings": solution_trace.warnings,
        "style_constraints": {
            "avoid_internal_phrases": [
                "目标公式：",
                "轨迹中给出",
                "按轨迹中的目标结果可得",
                "结构化 artifact",
                "SolutionTrace",
                "proof_status=",
                "verified_decl=",
            ],
            "formula_policy": "只使用 renderer_plan 中出现的公式；缺失的代数中间式不能补写。",
        },
    }


def _render_formula_line(formula: str, punctuation: str = "。") -> str:
    return f"{formula}{punctuation}"


def _render_equation_list(records: list[dict[str, Any]], *, start_index: int = 1) -> tuple[list[str], int]:
    lines: list[str] = []
    idx = start_index
    for record in records:
        formula = str(record.get("display_formula") or record.get("formal_formula") or "").strip()
        if not formula:
            continue
        intro = str(record.get("narrative_intro") or "").strip()
        title = str(record.get("step_title") or "").strip()
        if intro:
            lines.append(intro)
            lines.append("")
        elif title and title not in {"建立力学模型", "联立方程求解", "代数推导与目标闭合", "合并建模关系"}:
            lines.append(f"{title}给出")
            lines.append("")
        number = int(record.get("equation_number") or idx)
        lines.append(f"{formula}。        ({number})")
        lines.append("")
        idx += 1
    return lines, idx


def _record_lhs(record: dict[str, Any]) -> str:
    formula = str(record.get("formal_formula") or record.get("display_formula") or "").strip()
    if "=" not in formula:
        return ""
    return formula.split("=", 1)[0].strip()


def _mentions_friction_model(model_text: str, *, formula: str, canon: str) -> bool:
    if "mu" in canon or "μ" in formula:
        return True
    cleaned = re.sub(
        r"\bfrictionless\b|\bfriction\s+is\s+absent\b|\bfriction\s+absent\b|\bno\s+friction\b|\bwithout\s+friction\b",
        "",
        model_text,
    )
    return any(
        token in cleaned
        for token in (
            "static friction",
            "kinetic friction",
            "coefficient of friction",
            "friction force",
            "frictional force",
            "maximum friction",
        )
    )


def _is_auxiliary_equation_record(record: dict[str, Any], target_variables: list[str]) -> bool:
    lhs = _canon_formula_for_pattern(_record_lhs(record))
    target_lhs = {_canon_formula_for_pattern(variable) for variable in target_variables}
    if lhs and lhs in target_lhs:
        return False
    text = str(record.get("formal_formula") or record.get("display_formula") or "")
    canon = _canon_formula_for_pattern(text)
    if "positive_direction" in text or any(token in canon for token in ("toward_pulley", "downward", "upward")):
        return True
    if re.search(r"\b[aA]_[A-Za-z0-9]+\b\s*=\s*a\b", text):
        return True
    if re.search(r"\bT_[A-Za-z0-9]+\b\s*=\s*T\b", text):
        return True
    if re.search(r"\b(?:a|T)_(?:glider|hanging|cart|block|left|right)\b", text):
        return True
    if re.search(r"\bFnet(?:_|[A-Za-z0-9]|\b)", text):
        return True
    if re.search(r"\b[A-Za-z][A-Za-z0-9]*(?:_left|_right)\b", text):
        return True
    if re.search(r"\ba\d+\b", text):
        return True
    return False


def _select_numbered_equations(records: list[dict[str, Any]], *, target_variables: list[str]) -> list[dict[str, Any]]:
    if not records:
        return []
    primary = [
        record for record in records
        if not _is_auxiliary_equation_record(record, target_variables)
    ]
    return primary or records


def _sort_algebra_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def rank(item: tuple[int, dict[str, Any]]) -> tuple[int, int]:
        idx, record = item
        formula = str(record.get("display_formula") or record.get("formal_formula") or "")
        if "=" in formula and "≠" not in formula and "<" not in formula and ">" not in formula:
            return (0, idx)
        if any(token in formula for token in ("≠", "<", ">", "≤", "≥")):
            return (1, idx)
        return (2, idx)

    return [record for _, record in sorted(enumerate(records), key=rank)]


def _record_display_formula(record: dict[str, Any] | None) -> str | None:
    if not record:
        return None
    text = str(record.get("display_formula") or record.get("formal_formula") or "").strip()
    return text or None


def _find_record_like(records: list[dict[str, Any]], expected: str) -> dict[str, Any] | None:
    expected_keys = _formula_key_variants(expected)
    for record in records:
        keys = _formula_key_variants(record.get("formal_formula")) | _formula_key_variants(record.get("display_formula"))
        if expected_keys & keys:
            return record
    return None


def _find_answer_by_lhs(final_answers: list[dict[str, Any]], lhs: str) -> dict[str, Any] | None:
    lhs_key = _canon_formula_for_pattern(lhs)
    for answer in final_answers:
        for value in (answer.get("formal_formula"), answer.get("display_formula")):
            text = str(value or "").strip()
            if "=" not in text:
                continue
            if _canon_formula_for_pattern(text.split("=", 1)[0]) == lhs_key:
                return answer
    return None


def _build_algebra_exposition(
    *,
    numbered_equations: list[dict[str, Any]],
    algebra_steps: list[dict[str, Any]],
    final_answers: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    nonfinal_algebra = [
        record for record in algebra_steps
        if record.get("role") != "final_answer_from_proof_action"
    ]
    sorted_algebra = _sort_algebra_records(nonfinal_algebra)
    equation_formulas = [
        str(record.get("formal_formula") or record.get("display_formula") or "")
        for record in numbered_equations
    ]
    has_two_body_equations = _trace_has_formula(equation_formulas, "T = m1 * a") and _trace_has_formula(
        equation_formulas,
        "m2 * g - T = m2 * a",
    )
    substitution = _find_record_like(sorted_algebra, "m2 * g - m1 * a = m2 * a")
    collected = _find_record_like(sorted_algebra, "m2 * g = (m1 + m2) * a")
    denominator = _find_record_like(sorted_algebra, "m1 + m2 ≠ 0")
    a_answer = _find_answer_by_lhs(final_answers, "a")
    t_answer = _find_answer_by_lhs(final_answers, "T")
    if has_two_body_equations and substitution and collected and a_answer and t_answer:
        exposition: list[dict[str, Any]] = [
            {
                "text": "由 (1) 和 (2) 联立，代入 T = m₁a，有",
                "formula": _record_display_formula(substitution),
                "punctuation": ",",
            },
            {
                "text": "即",
                "formula": _record_display_formula(collected),
                "punctuation": "。",
            },
        ]
        if denominator:
            exposition.append(
                {
                    "text": "由于 m₁ 和 m₂ 均为正，m₁ + m₂ ≠ 0，因此",
                    "formula": _record_display_formula(a_answer),
                    "punctuation": "。",
                }
            )
        else:
            exposition.append(
                {
                    "text": "因此",
                    "formula": _record_display_formula(a_answer),
                    "punctuation": "。",
                }
            )
        exposition.append(
            {
                "text": "再代回 T = m₁a，得到",
                "formula": _record_display_formula(t_answer),
                "punctuation": "。",
            }
        )
        return exposition

    out: list[dict[str, Any]] = []
    for idx, record in enumerate(sorted_algebra):
        formula = _record_display_formula(record)
        if not formula:
            continue
        out.append(
            {
                "text": "由上述关系进行代数整理，得到" if idx == 0 else None,
                "formula": formula,
                "punctuation": "," if idx < len(sorted_algebra) - 1 else "。",
            }
        )
    return out


def _render_final_answers(final_answers: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    if len(final_answers) == 2:
        first = str(final_answers[0].get("display_formula") or final_answers[0].get("formal_formula") or "").strip()
        second = str(final_answers[1].get("display_formula") or final_answers[1].get("formal_formula") or "").strip()
        if first and second:
            return [f"{first}, \\qquad", f"{second}。"]
    for idx, answer in enumerate(final_answers):
        formula = str(answer.get("display_formula") or answer.get("formal_formula") or "").strip()
        if not formula:
            continue
        punctuation = "," if idx < len(final_answers) - 1 else "。"
        lines.append(_render_formula_line(formula, punctuation))
    return lines


def render_deterministic_solution(solution_trace: SolutionTrace) -> str:
    plan = _build_narrative_plan(solution_trace)
    lines: list[str] = []

    variables = plan["target_variables"]
    if plan.get("symbol_intro"):
        lines.append(str(plan["symbol_intro"]))
    elif variables:
        lines.append(f"本题要求求出 {', '.join(variables)}。")
    elif plan.get("target_display"):
        lines.append("本题要求证明给定的目标关系。")
    else:
        lines.append("本题的目标关系未能从结构化结果中可靠提取。")
    lines.append("")

    equation_index = 1
    numbered_equations = plan.get("numbered_equations") or []
    if numbered_equations:
        equation_lines, equation_index = _render_equation_list(numbered_equations, start_index=equation_index)
        lines.extend(equation_lines)
    else:
        lines.append("当前可审计记录没有给出可直接编号的建模方程或物理方程。")
        lines.append("")

    algebra_exposition = _list_payload(plan.get("algebra_exposition"))
    if algebra_exposition:
        for item in algebra_exposition:
            text = str(item.get("text") or "").strip()
            formula = str(item.get("formula") or "").strip()
            punctuation = str(item.get("punctuation") or "。")
            if text:
                lines.append(text)
                lines.append("")
            if formula:
                lines.append(_render_formula_line(formula, punctuation))
                lines.append("")
    else:
        lines.append("当前可审计轨迹没有提供更多代数中间式，因此这里不补写额外公式。")
        lines.append("")

    if plan["final_answers"]:
        lines.append("所以")
        lines.append("")
        lines.extend(_render_final_answers(plan["final_answers"]))
    else:
        lines.append("最终答案未能从 theorem target 中提取。")
    lines.append("")
    lines.append(plan["verification_note"])
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

    internal_markers = [
        "目标公式：",
        "轨迹中给出",
        "按轨迹中的目标结果可得",
        "结构化 artifact",
        "SolutionTrace",
        "proof_status=",
        "verified_decl=",
        "source_artifacts",
        "step_id",
    ]
    if any(marker in text for marker in internal_markers):
        failure_tags.append("internal_artifact_language")

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

    audit_pass = (
        render_success
        and final_coverage
        and law_coverage
        and unsupported_count == 0
        and "internal_artifact_language" not in failure_tags
        and gap_disclosure
        and proof_status_disclosure
        and target_match
    )
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
            max_chars=self._config_int("max_prompt_chars", 12000),
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
        natural_solution = render_deterministic_solution(trace)
        llm_payload = {
            "natural_solution": natural_solution,
            "used_step_ids": [step.step_id for step in trace.steps],
            "mentioned_formulas": [
                formula.display_formula or formula.formal_formula
                for formula in trace.final_answers
            ],
            "verification_note": _status_disclosure(trace.proof_status),
            "renderer": "deterministic_narrative_plan",
        }

        audit = audit_rendered_solution(
            solution_trace=trace,
            natural_solution=natural_solution,
            llm_payload=llm_payload,
        )
        if self._config_bool("natural_language_enabled", False) and self.model_client is not None:
            try:
                raw_llm, llm_payload, error = self._call_llm(trace)
                llm_solution = str(llm_payload.get("natural_solution") or "").strip() if not error else ""
                if llm_solution:
                    llm_audit = audit_rendered_solution(
                        solution_trace=trace,
                        natural_solution=llm_solution,
                        llm_payload=llm_payload,
                    )
                    if llm_audit.audit_pass or (
                        not audit.audit_pass and len(llm_audit.failure_tags) < len(audit.failure_tags)
                    ):
                        natural_solution = llm_solution
                        audit = llm_audit
            except Exception as exc:
                error = f"llm_render_failed:{type(exc).__name__}:{exc}"

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
