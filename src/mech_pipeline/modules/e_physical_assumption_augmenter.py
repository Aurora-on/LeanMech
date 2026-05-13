from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from mech_pipeline.types import ProofActionCheckResult, ProofActionProposal, ProofContext
from mech_pipeline.utils import normalize_lean_text, truncate

_VAL_TERM_RE = re.compile(r"\b(?P<name>[A-Za-z_][A-Za-z0-9_']*)\.val\b")
_BINDER_RE = re.compile(r"\(([^()]*)\)")
_POS_LT_RE = re.compile(r"(?P<name>[A-Za-z_][A-Za-z0-9_']*)\s*:\s*0\s*<\s*(?P<term>[^,\]\n;]+)")
_POS_GT_RE = re.compile(r"(?P<name>[A-Za-z_][A-Za-z0-9_']*)\s*:\s*(?P<term>[^,\]\n;]+)\s*>\s*0")
_MISSING_DENOM_RE = re.compile(
    r"denominator\s+(?P<denom>.*?)\s+requires positivity facts for\s+(?P<missing>.*)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PhysicalAssumptionAugmentationResult:
    context: ProofContext
    check: ProofActionCheckResult
    compile_result: dict[str, Any] | None = None


def _normalize_type(text: str) -> str:
    value = normalize_lean_text(str(text or "")).strip()
    if value.startswith("(") and value.endswith(")"):
        value = value[1:-1].strip()
    return value.rsplit(".", 1)[-1]


def _normalize_term(text: str) -> str:
    return re.sub(r"\s+", " ", normalize_lean_text(str(text or "")).strip()).strip("() ")


def _decl_without_body(theorem_decl: str) -> str:
    decl = normalize_lean_text(theorem_decl)
    if ":=" in decl:
        decl = decl.split(":=", 1)[0]
    if decl.rstrip().endswith(" by"):
        decl = decl.rstrip()[:-3]
    return decl.strip()


def _binder_chunks(theorem_decl: str) -> list[str]:
    return [chunk.strip() for chunk in _BINDER_RE.findall(_decl_without_body(theorem_decl)) if chunk.strip()]


def _split_decl_target(theorem_decl: str) -> tuple[str, str] | None:
    decl = _decl_without_body(theorem_decl)
    if " : " not in decl:
        return None
    prefix, target = decl.rsplit(" : ", 1)
    if not prefix.strip() or not target.strip():
        return None
    return prefix.strip(), target.strip()


def _binder_names(chunk: str) -> list[str]:
    if ":" not in chunk:
        return []
    names, _type = chunk.split(":", 1)
    return [part.strip() for part in names.split() if part.strip() and part.strip() != "_"]


def _existing_positive_terms(chunks: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for chunk in chunks:
        for regex in (_POS_LT_RE, _POS_GT_RE):
            match = regex.search(chunk)
            if not match:
                continue
            mapping.setdefault(_normalize_term(match.group("term")), match.group("name").strip())
    return mapping


def _physical_vars_from_local_binders(
    chunks: list[str],
    positive_types: set[str],
) -> dict[str, str]:
    out: dict[str, str] = {}
    for chunk in chunks:
        if ":" not in chunk:
            continue
        names_part, type_part = chunk.split(":", 1)
        lean_type = normalize_lean_text(type_part).strip()
        if "->" in lean_type or "→" in lean_type or "∀" in lean_type:
            continue
        normalized = _normalize_type(lean_type)
        if normalized not in positive_types:
            continue
        for name in names_part.split():
            clean = name.strip()
            if clean and re.match(r"^[A-Za-z_][A-Za-z0-9_']*$", clean):
                out.setdefault(clean, normalized)
    return out


def _physical_vars_from_typed_binders(
    typed_binders: list[dict[str, Any]],
    positive_types: set[str],
) -> dict[str, str]:
    out: dict[str, str] = {}
    for row in typed_binders:
        if not isinstance(row, dict):
            continue
        name = str(
            row.get("symbol")
            or row.get("name")
            or row.get("lean_name")
            or row.get("variable")
            or ""
        ).strip()
        lean_type = _normalize_type(row.get("lean_type") or row.get("type") or "")
        if name and lean_type in positive_types:
            out.setdefault(name, lean_type)
    return out


def physical_quantity_vars(
    context: ProofContext,
    positive_types: list[str],
) -> dict[str, str]:
    """Return scalar typed physical variables that are safe for E-local positivity assumptions."""
    allowed = {_normalize_type(item) for item in positive_types if str(item).strip()}
    chunks = list(context.local_binders) or _binder_chunks(context.theorem_decl)
    out = _physical_vars_from_local_binders(chunks, allowed)
    out.update(_physical_vars_from_typed_binders(context.typed_binders, allowed))
    return out


def _missing_terms_from_proposal(proposal: ProofActionProposal) -> list[str]:
    text = normalize_lean_text(str(proposal.expected_effect or ""))
    match = _MISSING_DENOM_RE.search(text)
    if not match:
        return []
    raw_terms = [item.strip() for item in match.group("missing").split(",")]
    return [_normalize_term(item) for item in raw_terms if item.strip()]


def _needed_vars_from_missing_terms(terms: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for term in terms:
        for match in _VAL_TERM_RE.finditer(term):
            name = match.group("name")
            if name not in seen:
                seen.add(name)
                out.append(name)
    return out


def _safe_hypothesis_name(var_name: str, used: set[str]) -> str:
    stem = re.sub(r"[^A-Za-z0-9_']", "_", var_name).strip("_") or "q"
    if stem[0].isdigit():
        stem = f"q_{stem}"
    candidate = f"h_{stem}_pos"
    if candidate not in used:
        used.add(candidate)
        return candidate
    idx = 2
    while f"{candidate}_{idx}" in used:
        idx += 1
    out = f"{candidate}_{idx}"
    used.add(out)
    return out


def _augment_theorem_decl(theorem_decl: str, assumptions: list[dict[str, Any]]) -> str | None:
    split = _split_decl_target(theorem_decl)
    if split is None:
        return None
    prefix, target = split
    suffix = " ".join(f"({item['name']} : {item['expression']})" for item in assumptions)
    return f"{prefix} {suffix} : {target}"


def _compile_augmented_context(
    *,
    context: ProofContext,
    lean_runner: Any,
    require_compile: bool,
) -> dict[str, Any] | None:
    if not require_compile:
        return {"compile_pass": True, "route_reason": "compile_not_required"}
    if not hasattr(lean_runner, "compile_statement"):
        return {"compile_pass": True, "route_reason": "compile_unavailable_assumed_ok"}
    with tempfile.TemporaryDirectory(prefix="pipeline_e_pos_aug_") as tmp:
        return dict(
            lean_runner.compile_statement(
                sample_id=context.sample_id,
                candidate_id=f"{context.candidate_id}_physical_pos_aug",
                lean_header=context.lean_header,
                theorem_decl=context.theorem_decl,
                run_dir=Path(tmp),
            )
        )


def augment_context_for_missing_side_condition(
    *,
    context: ProofContext,
    proposal: ProofActionProposal,
    positive_types: list[str],
    max_added: int,
    lean_runner: Any | None = None,
    require_compile: bool = True,
) -> PhysicalAssumptionAugmentationResult:
    """Create an E-local theorem with positive hypotheses for typed physical quantities.

    This does not prove the original theorem.  It proves a stronger-premise theorem and
    records the augmentation explicitly in the proof trace and dependency audit.
    """
    missing_terms = _missing_terms_from_proposal(proposal)
    needed_vars = _needed_vars_from_missing_terms(missing_terms)
    physical_vars = physical_quantity_vars(context, positive_types)
    chunks = list(context.local_binders) or _binder_chunks(context.theorem_decl)
    existing_positive = _existing_positive_terms(chunks)

    if not needed_vars:
        return PhysicalAssumptionAugmentationResult(
            context=context,
            check=ProofActionCheckResult(
                action_id="augment_physical_positive_hypotheses",
                strategy="augment_physical_positive_hypotheses",
                tactic_block="",
                status="invalid",
                error_type="no_val_terms_for_physical_positive_augmentation",
                error_message=proposal.expected_effect,
                stderr_excerpt=proposal.expected_effect,
            ),
        )

    additions: list[dict[str, Any]] = []
    used_names = set(context.local_hypotheses) | set(context.allowed_local_facts)
    used_names.update(_binder_names(chunk)[0] for chunk in chunks if _binder_names(chunk))
    for var_name in needed_vars:
        expression = f"0 < {var_name}.val"
        if _normalize_term(f"{var_name}.val") in existing_positive:
            continue
        lean_type = physical_vars.get(var_name)
        if not lean_type:
            return PhysicalAssumptionAugmentationResult(
                context=context,
                check=ProofActionCheckResult(
                    action_id="augment_physical_positive_hypotheses",
                    strategy="augment_physical_positive_hypotheses",
                    tactic_block="",
                    status="invalid",
                    error_type="missing_term_not_typed_physical_quantity",
                    error_message=f"{var_name}.val is not an allowed typed physical quantity.",
                    stderr_excerpt=proposal.expected_effect,
                ),
            )
        additions.append(
            {
                "name": _safe_hypothesis_name(var_name, used_names),
                "variable": var_name,
                "lean_type": lean_type,
                "expression": expression,
                "source": "e_physical_assumption_augmentation",
                "reason": proposal.expected_effect,
            }
        )

    if not additions:
        return PhysicalAssumptionAugmentationResult(
            context=context,
            check=ProofActionCheckResult(
                action_id="augment_physical_positive_hypotheses",
                strategy="augment_physical_positive_hypotheses",
                tactic_block="",
                status="progress",
                error_type=None,
                error_message="required positive hypotheses already exist",
                stderr_excerpt=None,
            ),
        )

    if len(context.added_physical_assumptions) + len(additions) > max_added:
        return PhysicalAssumptionAugmentationResult(
            context=context,
            check=ProofActionCheckResult(
                action_id="augment_physical_positive_hypotheses",
                strategy="augment_physical_positive_hypotheses",
                tactic_block="",
                status="invalid",
                error_type="too_many_physical_positive_hypotheses",
                error_message=f"max_added_positive_hypotheses={max_added}",
                stderr_excerpt=proposal.expected_effect,
            ),
        )

    augmented_decl = _augment_theorem_decl(context.theorem_decl, additions)
    if not augmented_decl:
        return PhysicalAssumptionAugmentationResult(
            context=context,
            check=ProofActionCheckResult(
                action_id="augment_physical_positive_hypotheses",
                strategy="augment_physical_positive_hypotheses",
                tactic_block="",
                status="invalid",
                error_type="theorem_decl_not_augmentable",
                error_message=truncate(context.theorem_decl, 240),
                stderr_excerpt=None,
            ),
        )

    next_binders = [*chunks, *(f"{item['name']} : {item['expression']}" for item in additions)]
    next_context = replace(
        context,
        theorem_decl=augmented_decl,
        base_theorem_decl=context.base_theorem_decl or context.theorem_decl,
        local_binders=next_binders,
        local_hypotheses=list(dict.fromkeys([*context.local_hypotheses, *(item["name"] for item in additions)])),
        allowed_local_facts=list(dict.fromkeys([*context.allowed_local_facts, *(item["name"] for item in additions)])),
        added_physical_assumptions=[*context.added_physical_assumptions, *additions],
        augmentation_status="applied",
        augmentation_reason=proposal.expected_effect,
    )
    compile_result = None
    if lean_runner is not None:
        compile_result = _compile_augmented_context(
            context=next_context,
            lean_runner=lean_runner,
            require_compile=require_compile,
        )
        if not bool(compile_result.get("compile_pass")):
            return PhysicalAssumptionAugmentationResult(
                context=context,
                compile_result=compile_result,
                check=ProofActionCheckResult(
                    action_id="augment_physical_positive_hypotheses",
                    strategy="augment_physical_positive_hypotheses",
                    tactic_block="",
                    status="invalid",
                    error_type="augmented_theorem_compile_failed",
                    error_message=str(compile_result.get("error_message") or compile_result.get("stderr_digest") or ""),
                    stderr_excerpt=str(compile_result.get("stderr_excerpt") or compile_result.get("stderr_digest") or ""),
                ),
            )

    return PhysicalAssumptionAugmentationResult(
        context=next_context,
        compile_result=compile_result,
        check=ProofActionCheckResult(
            action_id="augment_physical_positive_hypotheses",
            strategy="augment_physical_positive_hypotheses",
            tactic_block="",
            status="progress",
            error_type=None,
            error_message=f"added {len(additions)} typed physical positivity assumption(s)",
            stderr_excerpt=None,
        ),
    )
