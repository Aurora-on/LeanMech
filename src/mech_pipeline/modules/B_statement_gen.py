from __future__ import annotations

import json
import hashlib
import re
from fractions import Fraction
from pathlib import Path
from typing import Any

from mech_pipeline.llm_schemas import StatementCandidatesPayload, TheoremSkeletonCandidatesPayload
from mech_pipeline.prompting import load_template, render_template
from mech_pipeline.prompt_views import (
    compact_candidate_for_feedback,
    compact_controlled_sketch,
    compact_evidence_bindings,
    compact_model_ir,
    compact_problem_ir,
    compact_sketch_audit,
    compact_structured_context,
)
from mech_pipeline.quantity_types import (
    SUPPORTED_LEAN_QUANTITY_TYPES,
    SUPPORTED_SI_QUANTITY_TYPES,
    function_quantity_parts,
    is_function_quantity_lean_type,
    normalize_quantity_lean_type,
)
from mech_pipeline.response_parser import ResponseParseError, parse_json_model
from mech_pipeline.types import (
    AlgebraObligation,
    ControlledSketch,
    ControlledSketchStep,
    EvidenceBinding,
    GroundingResult,
    HypothesisProvenance,
    ModelIR,
    ModelInterfaceInstantiation,
    SketchVariant,
    SketchAuditResult,
    StatementCandidate,
    TheoremSkeletonCandidate,
)
from mech_pipeline.utils import (
    is_tautological_equality,
    lean_ident,
    normalize_lean_text,
    sanitize_problem_ir_for_llm,
)

MECHLIB_HEADER = "\n".join(
    [
        "import Mathlib",
        "import MechLib",
        "open MechLib",
        "open MechLib.SI",
        "open MechLib.Mechanics",
        "open MechLib.Compat.PHYSlib.SI (F_of secondLaw displacement_end_x_init_x displacement_delta_t_const_v)",
    ]
)
PHYSLEAN_HEADER = "\n".join(["import Physlib", "open Physlib"])
TYPED_MECHLIB_TYPES = tuple(sorted(SUPPORTED_SI_QUANTITY_TYPES))
MOJIBAKE_PATTERN = re.compile(r"[鈧鈮鈭鉁锛晑�]")
DECIMAL_LITERAL_PATTERN = re.compile(r"(?<![A-Za-z0-9_])-?\d+\.\d+(?![A-Za-z0-9_])")
IDENT_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_']*")
ALLOWED_UNICODE = {"≠", "≤", "≥", "→", "∀", "∧", "∨", "ℝ", "ℕ", "ℤ"}
MOJIBAKE_REPLACEMENTS = {
    "鈭€": "∀",
    "鈮?": "≠",
    "鈥?": "*",
}
GREEK_IDENTIFIER_REPLACEMENTS = {
    "α": "alpha",
    "β": "beta",
    "γ": "gamma",
    "δ": "delta",
    "ε": "epsilon",
    "ζ": "zeta",
    "η": "eta",
    "θ": "theta",
    "ι": "iota",
    "κ": "kappa",
    "λ": "lambda",
    "μ": "mu",
    "ν": "nu",
    "ξ": "xi",
    "ο": "omicron",
    "π": "pi",
    "ρ": "rho",
    "σ": "sigma",
    "τ": "tau",
    "υ": "upsilon",
    "φ": "phi",
    "χ": "chi",
    "ψ": "psi",
    "ω": "omega",
    "Α": "Alpha",
    "Β": "Beta",
    "Γ": "Gamma",
    "Δ": "Delta",
    "Ε": "Epsilon",
    "Ζ": "Zeta",
    "Η": "Eta",
    "Θ": "Theta",
    "Ι": "Iota",
    "Κ": "Kappa",
    "Λ": "Lambda",
    "Μ": "Mu",
    "Ν": "Nu",
    "Ξ": "Xi",
    "Ο": "Omicron",
    "Π": "Pi",
    "Ρ": "Rho",
    "Σ": "Sigma",
    "Τ": "Tau",
    "Υ": "Upsilon",
    "Φ": "Phi",
    "Χ": "Chi",
    "Ψ": "Psi",
    "Ω": "Omega",
}
LEAN_CORE_TOKENS = {
    "theorem",
    "lemma",
    "import",
    "open",
    "by",
    "fun",
    "let",
    "in",
    "if",
    "then",
    "else",
    "forall",
    "True",
    "False",
    "Prop",
    "Type",
    "Real",
    "Nat",
    "Int",
    "Rat",
    "And",
    "Or",
    "Not",
    "Quantity",
    "SI",
}
SAFE_FUNCTION_TOKENS = {"sqrt", "abs", "min", "max", "sin", "cos", "tan", "asin", "acos", "atan", "exp", "log", "pow"}

DEFAULT_PROMPT = """__TASK_B_GENERATE_STATEMENTS__
You are a Lean4 statement generator for classical mechanics.

Important workflow:
1) First learn the target library conventions from the provided library context.
2) Then generate formal theorem declarations that follow import/namespace discipline.
3) Output JSON only.

Target library policy:
- library_target={{library_target}}
- required_header_template:
{{required_header_template}}

Generate exactly 4 theorem/lemma declaration candidates from ProblemIR.
Output JSON only:
{
  "candidates": [
    {
      "candidate_id":"c1",
      "lean_header":"...",
      "theorem_decl":"theorem ... : ...",
      "assumptions":[],
      "plan":"short modeling plan",
      "supporting_facts":["..."],
      "fact_sources":["problem","mechlib:SomeTheorem"],
      "library_symbols_used":["SomeTheorem"],
      "grounding_explanation":"why the statement is justified"
    },
    {
      "candidate_id":"c2",
      "lean_header":"...",
      "theorem_decl":"theorem ... : ...",
      "assumptions":[],
      "plan":"short modeling plan",
      "supporting_facts":["..."],
      "fact_sources":["problem"],
      "library_symbols_used":[],
      "grounding_explanation":"why the statement is justified"
    },
    {
      "candidate_id":"c3",
      "lean_header":"...",
      "theorem_decl":"theorem ... : ...",
      "assumptions":[],
      "plan":"short modeling plan",
      "supporting_facts":["..."],
      "fact_sources":["problem"],
      "library_symbols_used":[],
      "grounding_explanation":"why the statement is justified"
    },
    {
      "candidate_id":"c4",
      "lean_header":"...",
      "theorem_decl":"theorem ... : ...",
      "assumptions":[],
      "plan":"short modeling plan",
      "supporting_facts":["..."],
      "fact_sources":["problem"],
      "library_symbols_used":[],
      "grounding_explanation":"why the statement is justified"
    }
  ]
}

Constraints:
1) No proof body. Never output ':= by'.
2) Forbidden trivial goals: ': True', ': False', ': Prop', 'x = x', '1 = 1'.
3) Reject assumption-replay goals: do not output `h : x = y ⊢ y = x` or any conclusion that merely restates a given hypothesis.
4) Keep physics quantities, units, and unknown target aligned with ProblemIR.
5) Read Domain Summary Context first, then generate declarations.
6) Align with physical_laws in ProblemIR. Reject off-topic law drift.
7) Stay inside selected domain tags from context; avoid cross-domain drift.
8) Prefer symbol naming and theorem semantics consistent with MechLib domain summaries.
9) Use multiline readable declarations:
   theorem/lemma name
     (arg1 : Type)
     (arg2 : Type)
     ...
     : goal
10) Put each binder on its own line with 2-space indentation.
11) Keep lines reasonably short (recommended <= 100 chars).
12) Use meaningful names for hypotheses and quantities.
13) Use retrieved MechLib references as ontology/style hints only.
14) Never copy retrieved declarations verbatim.
15) If library_target is mechlib, do not import Physlib.
16) If library_target is physlean, do not import MechLib.
17) Prefer typed mechanics quantities (Mass/Force/Acceleration/Length/Time) when available.
18) If typed quantities are uncertain, use Real but keep units and laws explicit in assumptions.
19) Never use `!=` in theorem propositions; use propositional inequality (`≠`) or `Not (...)`.
20) For expressions that divide physical quantities (e.g., m2 / (m1 + m2)), prefer Real modeling.
21) Avoid `Quantity.cast` unless you are certain the identifier and dimension lemma exist.
22) Do not invent MechLib APIs or helper names. If uncertain, write direct algebraic equalities over binders.
23) If typed MechLib modeling would require undocumented helper defs or `Quantity.cast`, back off to `Real`.
24) Every nontrivial physical claim must be justified by either problem givens, definitions, or retrieved library theorems.
25) `fact_sources` must align with `supporting_facts`; use `problem`, `definition`, or `mechlib:<theorem_name>`.
26) `library_symbols_used` must only contain theorem/symbol names that appear in retrieved context.

ProblemIR:
{{problem_ir_json}}

Domain Summary Context + Retrieved library context:
{{mechlib_context}}
"""

DEFAULT_REVISE_PROMPT = """__TASK_B_REVISE_STATEMENTS__
You are revising Lean4 mechanics theorem declarations after compile/semantic feedback.

Your job:
1) Read the original ProblemIR and library context.
2) Read the previous candidates and structured feedback from compile + semantic ranking.
3) Generate a fresh set of 4 candidates that avoids the failed patterns.
4) Output JSON only.

Target library policy:
- library_target={{library_target}}
- required_header_template:
{{required_header_template}}

Return exactly 4 candidates:
{
  "candidates": [
    {
      "candidate_id":"c1",
      "lean_header":"...",
      "theorem_decl":"theorem ... : ...",
      "assumptions":[],
      "plan":"short revision plan",
      "supporting_facts":["..."],
      "fact_sources":["problem","mechlib:SomeTheorem"],
      "library_symbols_used":["SomeTheorem"],
      "grounding_explanation":"why the revised statement is justified"
    },
    {
      "candidate_id":"c2",
      "lean_header":"...",
      "theorem_decl":"theorem ... : ...",
      "assumptions":[],
      "plan":"short revision plan",
      "supporting_facts":["..."],
      "fact_sources":["problem"],
      "library_symbols_used":[],
      "grounding_explanation":"why the revised statement is justified"
    },
    {
      "candidate_id":"c3",
      "lean_header":"...",
      "theorem_decl":"theorem ... : ...",
      "assumptions":[],
      "plan":"short revision plan",
      "supporting_facts":["..."],
      "fact_sources":["problem"],
      "library_symbols_used":[],
      "grounding_explanation":"why the revised statement is justified"
    },
    {
      "candidate_id":"c4",
      "lean_header":"...",
      "theorem_decl":"theorem ... : ...",
      "assumptions":[],
      "plan":"short revision plan",
      "supporting_facts":["..."],
      "fact_sources":["problem"],
      "library_symbols_used":[],
      "grounding_explanation":"why the revised statement is justified"
    }
  ]
}

Revision rules:
1) Do not repeat the same theorem declarations from the previous round.
2) If compile feedback reports syntax/library-symbol/import issues, fix those first.
3) If semantic feedback reports target mismatch, law drift, trivial goals, or wrong known quantities, correct those before trying stylistic variation.
4) Do not output assumption-replay goals whose conclusion merely restates a hypothesis or flips an equality assumption.
5) Keep the unknown target, known quantities, laws, and constraints aligned with ProblemIR.
6) Prefer direct algebraic statements over undocumented helper APIs.
7) If typed MechLib modeling is causing failures, switch to `Real`.
8) Never output proof bodies.
9) Keep output fully valid JSON.
10) Use structured feedback to remove unsupported claims and unresolved library references.
11) Every nontrivial physical claim must have a source in `supporting_facts` / `fact_sources`.

ProblemIR:
{{problem_ir_json}}

Domain Summary Context + Retrieved library context:
{{mechlib_context}}

Previous candidates:
{{previous_candidates_json}}

Structured revision feedback:
{{revision_feedback}}
"""

DEFAULT_MINIMAL_SKELETON_PROMPT = """__TASK_B_GENERATE_MINIMAL_SKELETON__
You are selecting inputs for a deterministic minimal Lean theorem skeleton assembler.
Output JSON only.

Rules:
1. Do not generate theorem_decl, Lean binders, Lean proofs, or proof placeholders.
2. Do not invent MechLib declarations, predicates, interfaces, or namespaces.
3. Select only givens/model instances/sketch steps that are supported by the supplied JSON.
4. Qualitative facts such as frictionless_track, massless_string, flexible_string, stationary_pulley are metadata only.
5. Verified law expected_claims belong in proof_obligations, not theorem hypotheses.
6. Target facts and candidate answers must not be selected as hypotheses.
7. If a key law has no verified model predicate binding, leave it selected and note the evidence gap.
8. Explicit model_interface_instantiations are allowed as audited model gaps; do not convert them into fake MechLib APIs.
9. The deterministic assembler decides typed binders, .val target formulas, and theorem_decl from ModelIR.canonical_target only. Do not select or rewrite the target.
10. Select exactly one candidate. Prefer the explicit-gap sketch variant when ControlledSketch includes sketch_variants.
11. Do not invent variant IDs; use variant_id values from ControlledSketch.sketch_variants.

Return exactly 1 candidate selection payload. If previous feedback exists, adjust this one selection only.
Return JSON:
{
  "candidates": [
    {
      "candidate_id": "c1",
      "variant_id": "v2_explicit_gap_allowed",
      "theorem_name_hint": "short_descriptive_name",
      "selected_givens": [],
      "selected_model_instances": [],
      "plan": "short skeleton plan",
      "controlled_sketch_steps_used": [],
      "unsupported_claims": []
    }
  ]
}

ProblemIR:
{{problem_ir_json}}

ModelIR:
{{model_ir_json}}

ControlledSketch:
{{controlled_sketch_json}}

EvidenceBindings:
{{evidence_bindings_json}}

StructuredMechLibContext:
{{structured_context_json}}

SketchAudit:
{{sketch_audit_json}}

Revision feedback:
{{revision_feedback}}

Previous candidates:
{{previous_candidates_json}}
"""


def _strip_code_fence(text: str) -> str:
    out = text.strip()
    if out.startswith("```"):
        out = out.replace("```lean", "").replace("```", "").strip()
    return out


def _declaration_only(text: str) -> str:
    out = _strip_code_fence(text)
    if ":= by" in out:
        out = out.split(":= by", 1)[0].rstrip()
    elif ":=" in out:
        out = out.split(":=", 1)[0].rstrip()
    if out.endswith(" by"):
        out = out[:-3].rstrip()
    return out


def _is_meaningful_decl(text: str) -> bool:
    stripped = _declaration_only(text)
    if not re.match(r"^\s*(theorem|lemma)\s+", stripped):
        return False
    if ":" not in stripped:
        return False
    lowered = stripped.lower()
    if re.search(r":\s*(true|false)\s*$", lowered):
        return False
    if re.search(r":\s*prop\s*$", lowered):
        return False
    if re.search(r":\s*1\s*=\s*1\s*$", lowered):
        return False
    goal = stripped.rsplit(":", 1)[1].strip()
    ident_eq = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_']*)\s*=\s*([A-Za-z_][A-Za-z0-9_']*)", goal)
    if ident_eq and ident_eq.group(1) == ident_eq.group(2):
        return False
    num_eq = re.fullmatch(r"(-?\d+(?:\.\d+)?)\s*=\s*(-?\d+(?:\.\d+)?)", goal)
    if num_eq and num_eq.group(1) == num_eq.group(2):
        return False
    if _is_trivial_assumption_replay(stripped):
        return False
    return True


def _has_balanced_delimiters(text: str) -> bool:
    pairs = {"(": ")", "[": "]", "{": "}"}
    stack: list[str] = []
    for ch in text:
        if ch in pairs:
            stack.append(pairs[ch])
        elif ch in pairs.values():
            if not stack or stack.pop() != ch:
                return False
    return not stack


def _has_disallowed_non_ascii(text: str) -> bool:
    for ch in text:
        if ord(ch) <= 127:
            continue
        if ch in ALLOWED_UNICODE:
            continue
        return True
    return False


def _parse_decl_name(text: str) -> tuple[str, str, str] | None:
    decl = _declaration_only(text)
    m = re.match(r"^\s*(theorem|lemma)\s+([A-Za-z_][A-Za-z0-9_']*)([\s\S]*)$", decl)
    if not m:
        return None
    return m.group(1), m.group(2), m.group(3)


def _normalize_common_mojibake(text: str) -> str:
    out = text
    for src, dst in MOJIBAKE_REPLACEMENTS.items():
        out = out.replace(src, dst)
    return out


def _normalize_unicode_identifiers(text: str) -> str:
    out = text
    for src, dst in GREEK_IDENTIFIER_REPLACEMENTS.items():
        out = out.replace(src, dst)
    return out


def _render_real_literal(value: Fraction) -> str:
    abs_num = abs(value.numerator)
    if value.denominator == 1:
        base = f"({abs_num} : Real)"
    else:
        base = f"(({abs_num} : Real) / {value.denominator})"
    if value < 0:
        return f"(-{base})"
    return base


def _normalize_numeric_literals(text: str) -> str:
    def _replace(match: re.Match[str]) -> str:
        literal = match.group(0)
        try:
            value = Fraction(literal)
        except ValueError:
            return literal
        return _render_real_literal(value)

    return DECIMAL_LITERAL_PATTERN.sub(_replace, text)


def _normalize_value_level_numeric_quantity_casts(text: str) -> str:
    return re.sub(
        r"\(\s*((?:-?\d+(?:\.\d+)?)|(?:\(-?\d+\s*:\s*Real\)))\s*:\s*"
        r"(?:MechLib\.SI\.)?(?!Real\b|Nat\b|Int\b|Rat\b)[A-Z][A-Za-z0-9_']*\s*\)",
        r"\1",
        text,
    )


def _extract_context_symbols(mechlib_context: str) -> set[str]:
    symbols: set[str] = set()
    for match in re.finditer(r"symbol=([A-Za-z_][A-Za-z0-9_']*)", mechlib_context or ""):
        symbols.add(match.group(1))
    for match in re.finditer(r"fq_name=([A-Za-z_][A-Za-z0-9_'.]*)", mechlib_context or ""):
        fq_name = match.group(1)
        symbols.add(fq_name)
        symbols.add(fq_name.rsplit(".", 1)[-1])
    return symbols


def _extract_context_theorem_names(mechlib_context: str) -> set[str]:
    names: set[str] = set()
    for match in re.finditer(r"theorem_name=([A-Za-z_][A-Za-z0-9_']*)", mechlib_context or ""):
        names.add(match.group(1))
    return names


def _extract_context_decl_rows(mechlib_context: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in (mechlib_context or "").splitlines():
        if "theorem_name=" not in line:
            continue
        theorem = re.search(r"theorem_name=([A-Za-z_][A-Za-z0-9_']*)", line)
        if not theorem:
            continue
        fq = re.search(r"fq_name=([A-Za-z_][A-Za-z0-9_'.]*)", line)
        module = re.search(r"module=([A-Za-z_][A-Za-z0-9_'.]*)", line)
        status = re.search(r"status=([A-Za-z_][A-Za-z0-9_']*)", line)
        trust = re.search(r"trust_level=([A-Za-z_][A-Za-z0-9_']*)", line)
        proof_eligible = re.search(r"proof_eligible=(True|False|true|false)", line)
        rows.append(
            {
                "theorem_name": theorem.group(1),
                "symbol_name": theorem.group(1),
                "fq_name": fq.group(1) if fq else None,
                "module": module.group(1) if module else None,
                "status": status.group(1) if status else None,
                "trust_level": trust.group(1) if trust else None,
                "proof_eligible": (
                    proof_eligible.group(1).lower() == "true" if proof_eligible else None
                ),
            }
        )
    return rows


def _extract_context_schema_rows(mechlib_context: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in (mechlib_context or "").splitlines():
        if "schema_id=" not in line:
            continue
        schema = re.search(r"schema_id=([A-Za-z0-9_.:-]+)", line)
        corpus_type = re.search(r"corpus_type=([A-Za-z_][A-Za-z0-9_]*)", line)
        if not schema:
            continue
        rows.append(
            {
                "schema_id": schema.group(1),
                "corpus_type": corpus_type.group(1) if corpus_type else None,
                "proof_eligible": False,
            }
        )
    return rows


def _extract_context_alias_rows(mechlib_context: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in (mechlib_context or "").splitlines():
        if "alias_name=" not in line or "alias_to_fq_name=" not in line:
            continue
        alias = re.search(r"alias_name=([A-Za-z_][A-Za-z0-9_']*)", line)
        alias_fq = re.search(r"alias_fq_name=([A-Za-z_][A-Za-z0-9_'.]*)", line)
        target = re.search(r"alias_to_fq_name=([A-Za-z_][A-Za-z0-9_'.]*)", line)
        if not alias or not target:
            continue
        rows.append(
            {
                "alias_name": alias.group(1),
                "alias_fq_name": alias_fq.group(1) if alias_fq else None,
                "alias_to_fq_name": target.group(1),
            }
        )
    return rows


def _context_gap_schema_only(mechlib_context: str) -> bool:
    match = re.search(r"gap_schema_only:\s*(True|False|true|false)", mechlib_context or "")
    return bool(match and match.group(1).lower() == "true")


def _candidate_grounding_refs(
    *,
    theorem_decl: str,
    fact_sources: list[str],
    library_symbols_used: list[str],
    mechlib_context: str,
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]], str | None, bool]:
    decl_rows = _extract_context_decl_rows(mechlib_context)
    schema_rows = _extract_context_schema_rows(mechlib_context)
    alias_rows = _extract_context_alias_rows(mechlib_context)
    gap_schema_only = _context_gap_schema_only(mechlib_context)

    requested: set[str] = set(library_symbols_used)
    for source in fact_sources:
        if source.lower().startswith("mechlib:"):
            requested.add(source.split(":", 1)[1].strip())
    text = theorem_decl or ""

    verified_refs: list[dict[str, object]] = []
    seen_decl: set[str] = set()
    for row in decl_rows:
        names = {
            str(row.get("theorem_name") or ""),
            str(row.get("symbol_name") or ""),
            str(row.get("fq_name") or ""),
        }
        names.update(name.rsplit(".", 1)[-1] for name in list(names) if name)
        matched = bool(requested.intersection(names)) or any(name and name in text for name in names)
        if not matched:
            continue
        key = str(row.get("fq_name") or row.get("theorem_name") or "")
        if not key or key in seen_decl:
            continue
        seen_decl.add(key)
        verified_refs.append(row)

    alias_refs: list[dict[str, object]] = []
    seen_alias: set[str] = set()
    for row in alias_rows:
        names = {
            str(row.get("alias_name") or ""),
            str(row.get("alias_fq_name") or ""),
            str(row.get("alias_to_fq_name") or ""),
        }
        names.update(name.rsplit(".", 1)[-1] for name in list(names) if name)
        if not requested.intersection(names) and not any(name and name in text for name in names):
            continue
        key = str(row.get("alias_name") or "")
        if not key or key in seen_alias:
            continue
        seen_alias.add(key)
        alias_refs.append(row)

    schema_refs = schema_rows[:6] if gap_schema_only and not verified_refs else []
    if verified_refs:
        status = "verified_decl_bound"
    elif gap_schema_only:
        status = "gap_schema_only"
    else:
        status = "ungrounded"
    return verified_refs, schema_refs, alias_refs, status, gap_schema_only


def _normalize_text_list(value: object) -> list[str]:
    if isinstance(value, str):
        text = str(value).strip()
        return [text] if text else []
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = normalize_lean_text(str(item or "").strip())
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _normalize_library_symbol_list(value: object) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in _normalize_text_list(value):
        symbol = lean_ident(item, prefix="sym")
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        out.append(symbol)
    return out


def _unsupported_fact_sources(fact_sources: list[str], mechlib_context: str) -> list[str]:
    if not fact_sources:
        return []
    known_refs = _extract_context_symbols(mechlib_context) | _extract_context_theorem_names(mechlib_context)
    unsupported: list[str] = []
    for source in fact_sources:
        lowered = source.strip()
        if not lowered.lower().startswith("mechlib:"):
            continue
        ref = lowered.split(":", 1)[1].strip()
        if ref and ref not in known_refs:
            unsupported.append(f"unsupported_fact_source:{ref}")
    return unsupported


def _normalize_library_target(raw: str | None) -> str:
    value = (raw or "mechlib").strip().lower()
    if value in {"mechlib", "physlean", "auto"}:
        return value
    return "mechlib"


def _required_header(target: str) -> str:
    return MECHLIB_HEADER if target == "mechlib" else PHYSLEAN_HEADER


def _infer_library_target(lean_header: str, theorem_decl: str, default_target: str) -> str:
    text = f"{lean_header}\n{theorem_decl}"
    if "MechLib" in text:
        return "mechlib"
    if "PhysLean" in text:
        return "physlean"
    if default_target == "auto":
        return "mechlib"
    return default_target


def _normalize_header(lean_header: str, target: str) -> str:
    raw_lines = [ln.rstrip() for ln in normalize_lean_text(lean_header).splitlines() if ln.strip()]
    kept: list[str] = []
    for line in raw_lines:
        if target == "mechlib" and "PhysLean" in line:
            continue
        if target == "physlean" and "MechLib" in line:
            continue
        kept.append(line)

    required = _required_header(target).splitlines()
    merged: list[str] = []
    seen: set[str] = set()
    for line in required + kept:
        if line in seen:
            continue
        seen.add(line)
        merged.append(line)
    import_lines = sorted(
        [line for line in merged if line.lstrip().startswith("import ")],
        key=lambda line: (0 if line.strip() == "import Mathlib" else 1 if line.strip() == "import MechLib" else 2, line),
    )
    other_lines = [line for line in merged if not line.lstrip().startswith("import ")]
    return "\n".join(import_lines + other_lines).strip()


def _contains_typed_mechlib_types(text: str) -> bool:
    return any(re.search(rf"\b{re.escape(tp)}\b", text) for tp in TYPED_MECHLIB_TYPES)


def _extract_binder_names(text: str) -> set[str]:
    names: set[str] = set()
    for m in re.finditer(
        r"\(\s*([A-Za-z_][A-Za-z0-9_']*(?:\s+[A-Za-z_][A-Za-z0-9_']*)*)\s*:\s*[^)]+\)",
        text,
    ):
        for token in m.group(1).split():
            names.add(token)
    return names


def _decl_local_symbols(text: str) -> set[str]:
    names = _extract_binder_names(text)
    parsed = _parse_decl_name(text)
    if parsed:
        names.add(parsed[1])
    return names


def _ensure_real_binder(text: str, symbol: str) -> str:
    binders = _extract_binder_names(text)
    if symbol in binders:
        return text
    if not re.search(rf"\b{re.escape(symbol)}\b", text):
        return text
    lines = text.splitlines()
    if not lines:
        return text
    # Insert just after theorem/lemma line.
    lines.insert(1, f"  ({symbol} : Real)")
    return "\n".join(lines)


def _coerce_typed_binders_to_real(text: str) -> str:
    out = text
    out = re.sub(
        r":\s*(Mass|Force|Acceleration|Length|Time|Speed|Momentum)\b",
        ": Real",
        out,
    )
    out = out.replace(".val", "")
    out = _ensure_real_binder(out, "g")
    return out


def _looks_like_library_symbol(token: str) -> bool:
    if len(token) <= 1:
        return False
    if "_" in token:
        return True
    return token[0].islower() and any(ch.isupper() for ch in token[1:])


def _looks_like_unknown_prefix_application(token: str, text: str) -> bool:
    if len(token) <= 2 or not token.islower():
        return False
    return re.search(rf"\b{re.escape(token)}\b\s+[A-Za-z_(]", text) is not None


def _find_unknown_library_symbols(text: str, mechlib_context: str) -> list[str]:
    known = _extract_context_symbols(mechlib_context)
    known.update(_extract_context_theorem_names(mechlib_context))
    known.update(TYPED_MECHLIB_TYPES)
    known.update(LEAN_CORE_TOKENS)
    known.update(SAFE_FUNCTION_TOKENS)
    known.update(_decl_local_symbols(text))
    unknown: set[str] = set()
    for token in IDENT_PATTERN.findall(text):
        if token in known:
            continue
        if not _looks_like_library_symbol(token) and not _looks_like_unknown_prefix_application(token, text):
            continue
        unknown.add(token)
    return sorted(unknown)


def _infer_unsupported_claims(
    *,
    theorem_decl: str,
    fact_sources: list[str],
    library_symbols_used: list[str],
    mechlib_context: str,
    library_target: str,
) -> list[str]:
    unsupported: list[str] = []
    known_refs = _extract_context_symbols(mechlib_context) | _extract_context_theorem_names(mechlib_context)
    for source in _unsupported_fact_sources(fact_sources, mechlib_context):
        if source not in unsupported:
            unsupported.append(source)
    for symbol in library_symbols_used:
        if known_refs and symbol not in known_refs:
            tag = f"unsupported_library_symbol:{symbol}"
            if tag not in unsupported:
                unsupported.append(tag)
    if library_target == "mechlib":
        for symbol in _find_unknown_library_symbols(theorem_decl, mechlib_context):
            tag = f"unknown_library_symbol_in_decl:{symbol}"
            if tag not in unsupported:
                unsupported.append(tag)
    return unsupported


def _strip_quantity_casts(text: str) -> str:
    needle = "Quantity.cast"
    idx = 0
    out: list[str] = []
    while True:
        start = text.find(needle, idx)
        if start < 0:
            out.append(text[idx:])
            break
        out.append(text[idx:start])
        pos = start + len(needle)
        while pos < len(text) and text[pos].isspace():
            pos += 1
        if pos >= len(text) or text[pos] != "(":
            out.append(needle)
            idx = pos
            continue
        depth = 1
        pos += 1
        expr_start = pos
        while pos < len(text) and depth > 0:
            ch = text[pos]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            pos += 1
        if depth != 0:
            out.append(text[start:])
            break
        expr = text[expr_start : pos - 1].strip()
        trail = pos
        while trail < len(text) and text[trail].isspace():
            trail += 1
        if text.startswith("SI.", trail):
            trail += 3
            while trail < len(text) and (text[trail].isalnum() or text[trail] in {"_", "'"}):
                trail += 1
        out.append(f"({expr})")
        idx = trail
    return "".join(out)


def _rewrite_known_mechlib_hallucinations(text: str) -> str:
    ident = r"([A-Za-z_][A-Za-z0-9_']*)"
    out = text.replace("**", "^")
    out = _strip_quantity_casts(out)
    out = re.sub(
        rf"\bvelocityConstAccel\s+{ident}\s+{ident}\s+{ident}",
        lambda m: f"({m.group(1)} + {m.group(2)} * {m.group(3)})",
        out,
    )
    out = re.sub(
        rf"\bpositionConstAccel\s+{ident}\s+{ident}\s+{ident}\s+{ident}",
        lambda m: (
            f"({m.group(1)} + {m.group(2)} * {m.group(4)} + "
            f"((1 : Real) / 2) * {m.group(3)} * ({m.group(4)} ^ (2 : Nat)))"
        ),
        out,
    )
    out = re.sub(
        rf"\bdisplacementConstAccelForm2\s+{ident}\s+{ident}\s+{ident}",
        lambda m: f"((({m.group(1)} + {m.group(2)}) / 2) * {m.group(3)})",
        out,
    )
    out = re.sub(
        rf"\bdisplacement\s+{ident}\s+{ident}",
        lambda m: f"({m.group(1)} - {m.group(2)})",
        out,
    )
    out = re.sub(
        rf"\bF_of\s+{ident}\s+{ident}",
        lambda m: f"({m.group(1)} * {m.group(2)})",
        out,
    )
    return out


def _repair_decl_for_mechlib_safety(
    *,
    sample_id: str,
    candidate_id: str,
    theorem_decl: str,
    problem_ir: dict[str, Any] | None,
    mechlib_context: str,
    library_target: str,
) -> str | None:
    text = _normalize_common_mojibake(theorem_decl.replace("!=", "≠"))
    text = _normalize_unicode_identifiers(text)
    text = _normalize_numeric_literals(text)
    if MOJIBAKE_PATTERN.search(text):
        return None
    if not _has_balanced_delimiters(text):
        return None
    if _has_disallowed_non_ascii(text):
        return None
    unknown_library_symbols: list[str] = []
    if library_target == "mechlib":
        unknown_library_symbols = _find_unknown_library_symbols(text, mechlib_context)
    if "Quantity.cast" in text or unknown_library_symbols:
        text = _rewrite_known_mechlib_hallucinations(text)
        text = _coerce_typed_binders_to_real(text)
        text = _normalize_numeric_literals(text)
        if MOJIBAKE_PATTERN.search(text):
            return None
        if not _has_balanced_delimiters(text):
            return None
        if _has_disallowed_non_ascii(text):
            return None
    if _contains_typed_mechlib_types(text):
        risky = "/" in text or "≠ 0" in text or ".val" in text
        if risky:
            text = _coerce_typed_binders_to_real(text)
            if not _has_balanced_delimiters(text):
                return None
    return text


def _normalize_theorem_decl(
    sample_id: str,
    candidate_id: str,
    value: object,
    problem_ir: dict[str, Any] | None,
    mechlib_context: str,
    library_target: str,
) -> str | None:
    text = normalize_lean_text(_declaration_only(str(value or "")))
    text = _normalize_unicode_identifiers(text)
    text = text.replace("!=", "≠")
    if _is_meaningful_decl(text):
        parsed = _parse_decl_name(text)
        if parsed:
            kw, old_name, rest = parsed
            safe_name = lean_ident(f"{sample_id}_{candidate_id}_{old_name}", prefix="thm")
            renamed = f"{kw} {safe_name}{rest}"
            return _repair_decl_for_mechlib_safety(
                sample_id=sample_id,
                candidate_id=candidate_id,
                theorem_decl=renamed,
                problem_ir=problem_ir,
                mechlib_context=mechlib_context,
                library_target=library_target,
            )
        return _repair_decl_for_mechlib_safety(
            sample_id=sample_id,
            candidate_id=candidate_id,
            theorem_decl=text,
            problem_ir=problem_ir,
            mechlib_context=mechlib_context,
            library_target=library_target,
        )
    return None


def _extract_binder_types(text: str) -> list[str]:
    types: list[str] = []
    for m in re.finditer(r"\(\s*[A-Za-z_][A-Za-z0-9_']*(?:\s+[A-Za-z_][A-Za-z0-9_']*)*\s*:\s*([^)]+)\)", text):
        types.append(" ".join(m.group(1).split()))
    return types


def _is_simple_commutativity_goal(goal: str) -> bool:
    patterns = [
        r"^\(?([A-Za-z_][A-Za-z0-9_']*)\s*\*\s*([A-Za-z_][A-Za-z0-9_']*)\)?\s*=\s*\(?\2\s*\*\s*\1\)?$",
        r"^\(?([A-Za-z_][A-Za-z0-9_']*)\s*\+\s*([A-Za-z_][A-Za-z0-9_']*)\)?\s*=\s*\(?\2\s*\+\s*\1\)?$",
    ]
    compact = " ".join(goal.split())
    return any(re.fullmatch(pattern, compact) for pattern in patterns)


def _is_trivial_assumption_replay(text: str) -> bool:
    stripped = _declaration_only(text)
    if ":" not in stripped:
        return False
    goal = " ".join(stripped.rsplit(":", 1)[1].strip().split())
    if _is_simple_commutativity_goal(goal):
        return True
    for binder_type in _extract_binder_types(stripped):
        binder_prop = " ".join(binder_type.split())
        if goal == binder_prop:
            return True
        eq = re.fullmatch(r"(.+?)\s*=\s*(.+)", binder_prop)
        goal_eq = re.fullmatch(r"(.+?)\s*=\s*(.+)", goal)
        if eq and goal_eq:
            lhs = " ".join(eq.group(1).split())
            rhs = " ".join(eq.group(2).split())
            goal_lhs = " ".join(goal_eq.group(1).split())
            goal_rhs = " ".join(goal_eq.group(2).split())
            if (goal_lhs == lhs and goal_rhs == rhs) or (goal_lhs == rhs and goal_rhs == lhs):
                return True
    return False


MINIMAL_HYPOTHESIS_ROLES = {
    "problem_fact",
    "coordinate_convention",
    "local_definition",
    "model_instance",
    "explicit_gap_law",
}

DERIVED_HYPOTHESIS_ROLES = {
    "target",
    "law_application_equation",
    "algebra_elimination",
    "unknown",
}

MINIMAL_MECHLIB_HEADER = "\n".join(["import Mathlib", "import MechLib", "open MechLib", "open MechLib.SI"])
QUALITATIVE_PREDICATE_MARKERS = {
    "frictionless",
    "massless",
    "flexible",
    "stationary",
    "level",
    "track",
    "string",
    "pulley",
    "horizontal",
    "vertical",
}
TYPE_HINTS: tuple[tuple[str, str], ...] = (
    ("moment_of_inertia", "MomentOfInertia"),
    ("moment of inertia", "MomentOfInertia"),
    ("angular_acceleration", "AngularAcceleration"),
    ("angular acceleration", "AngularAcceleration"),
    ("angular_velocity", "AngularVelocity"),
    ("angular velocity", "AngularVelocity"),
    ("torque", "Torque"),
    ("tension", "Force"),
    ("weight", "Force"),
    ("net_force", "Force"),
    ("net force", "Force"),
    ("force", "Force"),
    ("gravity", "Acceleration"),
    ("gravitational acceleration", "Acceleration"),
    ("acceleration", "Acceleration"),
    ("velocity", "Speed"),
    ("speed", "Speed"),
    ("radius", "Length"),
    ("height", "Length"),
    ("distance", "Length"),
    ("length", "Length"),
    ("time", "Time"),
    ("mass", "Mass"),
)
QUANTITY_TYPE_NAMES = set(SUPPORTED_SI_QUANTITY_TYPES)


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return False


def _dataclass_payload(value: object) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "to_dict"):
        payload = value.to_dict()
        return payload if isinstance(payload, dict) else {}
    if isinstance(value, dict):
        return dict(value)
    return {}


def _list_payload(values: list[object] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in values or []:
        payload = _dataclass_payload(item)
        if payload:
            out.append(payload)
    return out


def _model_ir_digest(model_ir: ModelIR | None) -> str | None:
    if model_ir is None:
        return None
    if model_ir.source_problem_ir_hash:
        return model_ir.source_problem_ir_hash
    payload = json.dumps(model_ir.to_dict(), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _verified_decl_whitelist(evidence_bindings: list[EvidenceBinding]) -> set[str]:
    return {
        str(binding.verified_decl).strip()
        for binding in evidence_bindings
        if binding.binding_status == "ok" and binding.proof_fact_allowed and binding.verified_decl
    }


def _required_import_line(value: object) -> str | None:
    text = normalize_lean_text(str(value or "").strip())
    if not text:
        return None
    if text.startswith("open "):
        return None
    if text.startswith("import "):
        return text
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_'.]*", text):
        return f"import {text}"
    return None


def _minimal_header(
    evidence_bindings: list[EvidenceBinding] | None = None,
    verified_decls: list[str] | None = None,
) -> str:
    verified = {str(name).strip() for name in (verified_decls or []) if str(name).strip()}
    lines = [line for line in MINIMAL_MECHLIB_HEADER.splitlines() if line.strip()]
    for binding in evidence_bindings or []:
        if verified and str(binding.verified_decl or "").strip() not in verified:
            continue
        if binding.binding_status != "ok" or not binding.proof_fact_allowed:
            continue
        for item in binding.required_imports:
            line = _required_import_line(item)
            if line:
                lines.append(line)
    seen: set[str] = set()
    unique: list[str] = []
    for line in lines:
        if line in seen:
            continue
        seen.add(line)
        unique.append(line)
    import_lines = sorted(
        [line for line in unique if line.startswith("import ")],
        key=lambda line: (0 if line == "import Mathlib" else 1 if line == "import MechLib" else 2, line),
    )
    other_lines = [line for line in unique if not line.startswith("import ")]
    return "\n".join(import_lines + other_lines).strip()


def _all_sketch_steps(controlled_sketch: ControlledSketch | None) -> list[ControlledSketchStep]:
    if controlled_sketch is None:
        return []
    if controlled_sketch.schema_version >= 2:
        steps = list(controlled_sketch.proof_steps)
        if controlled_sketch.algebra_obligation is not None:
            steps.append(_algebra_obligation_step(controlled_sketch.algebra_obligation))
        return steps
    return []


def _algebra_obligation_step(obligation: AlgebraObligation) -> ControlledSketchStep:
    return ControlledSketchStep(
        step_id=obligation.obligation_id,
        kind="algebra_obligation",
        claim=obligation.claim,
        formal_claim=obligation.formal_claim,
        binding_status="algebra_obligation",
        expected_claim=obligation.formal_claim,
        proof_fact_allowed=False,
        allowed_solvers=list(obligation.allowed_solvers),
        required_hypotheses=list(obligation.required_equations),
        produces=obligation.produces,
        notes=obligation.notes,
    )


def _step_from_payload(value: object, index: int) -> ControlledSketchStep:
    if isinstance(value, ControlledSketchStep):
        return value
    payload = _dataclass_payload(value)
    return ControlledSketchStep(
        step_id=str(payload.get("step_id") or f"po{index}"),
        kind=str(payload.get("kind") or "law_application"),
        claim=normalize_lean_text(str(payload.get("claim") or "")),
        formal_claim=normalize_lean_text(str(payload.get("formal_claim") or "")).strip() or None,
        source_model_instance=str(payload.get("source_model_instance") or "").strip() or None,
        planning_schema=str(payload.get("planning_schema") or "").strip() or None,
        verified_decl=str(payload.get("verified_decl") or "").strip() or None,
        binding_status=str(payload.get("binding_status") or "").strip() or None,
        expected_claim=normalize_lean_text(str(payload.get("expected_claim") or "")).strip() or None,
        proof_fact_allowed=_as_bool(payload.get("proof_fact_allowed")),
        allowed_solvers=[str(x) for x in payload.get("allowed_solvers", [])]
        if isinstance(payload.get("allowed_solvers"), list)
        else [],
        required_hypotheses=[str(x) for x in payload.get("required_hypotheses", [])]
        if isinstance(payload.get("required_hypotheses"), list)
        else [],
        produces=str(payload.get("produces") or "").strip() or None,
        notes=str(payload.get("notes") or "").strip() or None,
    )


def _payload_name(value: object) -> str:
    payload = _dataclass_payload(value)
    return str(payload.get("name") or "").strip()


def _payload_lean(value: object) -> str:
    payload = _dataclass_payload(value)
    return normalize_lean_text(str(payload.get("lean") or "")).strip()


def _payload_allowed(value: object) -> bool:
    payload = _dataclass_payload(value)
    return _as_bool(payload.get("allowed_in_hypotheses"))


def _type_from_hint(*parts: object) -> str:
    text = " ".join(str(part or "") for part in parts).replace("-", "_").lower()
    for hint, lean_type in TYPE_HINTS:
        if hint in text:
            return lean_type
    if re.search(r"(?<![A-Za-z0-9_])g(?![A-Za-z0-9_])", text):
        return "Acceleration"
    return "Real"


def _type_from_symbol(symbol: str) -> str | None:
    value = str(symbol or "").strip()
    if re.fullmatch(r"m\d*|mass\d*", value):
        return "Mass"
    if re.fullmatch(r"T\d*|F\d*|N|W|f", value):
        return "Force"
    if re.fullmatch(r"a\d*|g", value):
        return "Acceleration"
    if re.fullmatch(r"R|r|L|x|y|h|d", value):
        return "Length"
    if re.fullmatch(r"t\d*", value):
        return "Time"
    if re.fullmatch(r"v\d*", value):
        return "Speed"
    if re.fullmatch(r"I\d*", value):
        return "MomentOfInertia"
    if re.fullmatch(r"alpha\d*", value):
        return "AngularAcceleration"
    return None


def _model_interface_instantiation_from_payload(value: object, index: int) -> ModelInterfaceInstantiation | None:
    if isinstance(value, ModelInterfaceInstantiation):
        return value
    payload = _dataclass_payload(value)
    formal_claim = normalize_lean_text(str(payload.get("formal_claim") or "")).strip()
    if not formal_claim:
        return None
    introduced = payload.get("introduced_variable")
    return ModelInterfaceInstantiation(
        instantiation_id=str(payload.get("instantiation_id") or f"mii{index}").strip() or f"mii{index}",
        kind=str(payload.get("kind") or "model_interface_instantiation").strip()
        or "model_interface_instantiation",
        formal_claim=formal_claim,
        source_model_instance=str(payload.get("source_model_instance") or "").strip() or None,
        interface_name=str(payload.get("interface_name") or "").strip() or None,
        parameter_role=str(payload.get("parameter_role") or "").strip() or None,
        introduced_variable=dict(introduced) if isinstance(introduced, dict) else None,
        source_type=str(payload.get("source_type") or "model_ir").strip() or "model_ir",
        modeling_basis=[str(item) for item in payload.get("modeling_basis", [])]
        if isinstance(payload.get("modeling_basis"), list)
        else [],
        verified_constructor=str(payload.get("verified_constructor") or "").strip() or None,
        proof_fact_allowed=_as_bool(payload.get("proof_fact_allowed")),
        binding_status=str(payload.get("binding_status") or "explicit_model_gap").strip()
        or "explicit_model_gap",
        notes=str(payload.get("notes") or "").strip() or None,
    )


def _model_interface_instantiations_from_model_ir(model_ir: ModelIR | None) -> list[ModelInterfaceInstantiation]:
    if model_ir is None:
        return []
    out: list[ModelInterfaceInstantiation] = []
    seen: set[str] = set()

    def add(item: ModelInterfaceInstantiation) -> None:
        key = f"{item.instantiation_id}:{item.source_model_instance}:{item.formal_claim}"
        if key in seen:
            return
        seen.add(key)
        out.append(item)

    for idx, raw in enumerate(getattr(model_ir, "interface_instantiations", []) or [], start=1):
        item = _model_interface_instantiation_from_payload(raw, idx)
        if item is not None:
            add(item)
    next_index = len(out) + 1
    for instance in model_ir.model_instances:
        for raw in getattr(instance, "interface_instantiations", []) or []:
            item = _model_interface_instantiation_from_payload(raw, next_index)
            next_index += 1
            if item is not None:
                if not item.source_model_instance:
                    item.source_model_instance = instance.instance_id
                add(item)
    return out


def _model_interface_instantiations_from_sketch(
    controlled_sketch: ControlledSketch | None,
) -> list[ModelInterfaceInstantiation]:
    if controlled_sketch is None:
        return []
    out: list[ModelInterfaceInstantiation] = []
    for idx, raw in enumerate(getattr(controlled_sketch, "model_interface_instantiations", []) or [], start=1):
        item = _model_interface_instantiation_from_payload(raw, idx)
        if item is not None:
            out.append(item)
    return out


def _expected_claim_instantiations_for_blocked_predicates(
    *,
    model_ir: ModelIR | None,
    blocked_model_predicates: list[dict[str, Any]],
    selected_model_instances: set[str],
) -> list[ModelInterfaceInstantiation]:
    if model_ir is None:
        return []
    blocked_instances = {
        str(row.get("source_model_instance") or "").strip()
        for row in blocked_model_predicates
        if str(row.get("source_model_instance") or "").strip()
    }
    out: list[ModelInterfaceInstantiation] = []
    for instance in model_ir.model_instances:
        if selected_model_instances and instance.instance_id not in selected_model_instances:
            continue
        if instance.instance_id not in blocked_instances:
            continue
        if not str(instance.expected_claim or "").strip():
            continue
        out.append(
            ModelInterfaceInstantiation(
                instantiation_id=f"{lean_ident(instance.instance_id, prefix='mi')}_expected_claim",
                kind=instance.kind or "model_expected_claim",
                formal_claim=str(instance.expected_claim or "").strip(),
                source_model_instance=instance.instance_id,
                interface_name=instance.planning_schema_id,
                source_type="model_ir",
                modeling_basis=[item for item in [instance.natural_language] if item],
                proof_fact_allowed=False,
                binding_status="explicit_model_gap",
                notes=(
                    "No checked Prop-valued MechLib model predicate matched this ModelInstance; "
                    "ModelIR expected_claim is kept as an explicit modeling gap."
                ),
            )
        )
    return out


def _introduced_quantity_info(item: ModelInterfaceInstantiation) -> dict[str, Any] | None:
    payload = item.introduced_variable if isinstance(item.introduced_variable, dict) else {}
    raw_name = str(payload.get("name") or payload.get("symbol") or "").strip()
    if not raw_name:
        return None
    lean_name = lean_ident(_normalize_unicode_identifiers(raw_name), prefix="q")
    explicit_type = str(payload.get("lean_type") or payload.get("type") or "").strip()
    lean_type, supported, status = normalize_quantity_lean_type(explicit_type)
    if not supported:
        lean_type = "Real"
    return {
        "name": lean_name,
        "source_name": raw_name,
        "lean_type": lean_type,
        "source": payload,
        "typed_quantity": lean_type != "Real",
        "type_status": status,
        "type_supported": supported,
        "type_source": "introduced_variable",
        "type_confidence": 1.0 if status == "ok" else 0.0,
        "requested_lean_type": explicit_type,
    }


def _quantity_infos(
    model_ir: ModelIR | None,
    controlled_sketch: ControlledSketch | None = None,
) -> list[dict[str, Any]]:
    if model_ir is None:
        return []
    infos: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add_info(info: dict[str, Any]) -> None:
        lean_name = str(info["name"])
        if not lean_name or lean_name in seen:
            return
        seen.add(lean_name)
        infos.append(info)

    variables = model_ir.variables if isinstance(model_ir.variables, dict) else {}
    annotations: dict[str, dict[str, Any]] = {}
    for annotation in getattr(model_ir, "quantity_annotations", []) or []:
        payload = _dataclass_payload(annotation)
        symbol = str(payload.get("symbol") or "").strip()
        if not symbol:
            continue
        lean_name = lean_ident(_normalize_unicode_identifiers(symbol), prefix="q")
        annotations[symbol] = payload
        annotations[lean_name] = payload
    for raw_name, meta in variables.items():
        source_name = str(raw_name or "").strip()
        if not source_name:
            continue
        lean_name = lean_ident(_normalize_unicode_identifiers(source_name), prefix="q")
        payload = meta if isinstance(meta, dict) else {}
        annotation = annotations.get(source_name) or annotations.get(lean_name)
        if annotation:
            requested_type = str(annotation.get("lean_type") or "").strip()
            lean_type, supported, status = normalize_quantity_lean_type(requested_type)
            confidence = float(annotation.get("confidence") or 0.0)
            if confidence < 0.5 and lean_type != "Real":
                status = "low_confidence_quantity_type"
                supported = False
            if not supported:
                lean_type = "Real"
            source_payload = {**payload, "quantity_annotation": annotation}
            type_source = "quantity_annotation"
        else:
            requested_type = ""
            lean_type = "Real"
            supported = True
            status = "quantity_type_unresolved"
            confidence = 0.0
            source_payload = payload
            type_source = "unresolved"
        add_info(
            {
                "name": lean_name,
                "source_name": source_name,
                "lean_type": lean_type,
                "source": source_payload,
                "typed_quantity": lean_type != "Real",
                "type_status": status,
                "type_supported": supported,
                "type_source": type_source,
                "type_confidence": confidence,
                "requested_lean_type": requested_type,
            }
        )
    for item in [
        *_model_interface_instantiations_from_model_ir(model_ir),
        *_model_interface_instantiations_from_sketch(controlled_sketch),
    ]:
        info = _introduced_quantity_info(item)
        if info is not None:
            add_info(info)
    return infos


def _quantity_info_map(infos: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for info in infos:
        out[str(info["name"])] = info
        out[str(info["source_name"])] = info
    return out


def _bound_formula_variables(formula: str) -> set[str]:
    out: set[str] = set()
    for match in re.finditer(
        r"\b(?:forall|∀)\s+([A-Za-z_][A-Za-z0-9_']*)(?:\.val)?\s*(?::|,)",
        formula,
    ):
        out.add(match.group(1))
    for match in re.finditer(r"\bfun\s+([A-Za-z_][A-Za-z0-9_']*)(?:\.val)?\s*(?::|=>)", formula):
        out.add(match.group(1))
    return out


def _normalize_invalid_val_binders(formula: str) -> str:
    out = formula
    out = re.sub(r"\b(fun\s+)([A-Za-z_][A-Za-z0-9_']*)\.val(\s*(?::|=>))", r"\1\2\3", out)
    out = re.sub(r"\b(forall\s+)([A-Za-z_][A-Za-z0-9_']*)\.val(\s*:)", r"\1\2\3", out)
    out = re.sub(r"\b(forall\s+)([A-Za-z_][A-Za-z0-9_']*)\.val(\s*,)", r"\1\2\3", out)
    out = re.sub(r"(∀\s*)([A-Za-z_][A-Za-z0-9_']*)\.val(\s*:)", r"\1\2\3", out)
    out = re.sub(r"(∀\s*)([A-Za-z_][A-Za-z0-9_']*)\.val(\s*,)", r"\1\2\3", out)
    return out


def _declared_quantity_type(symbol: str, quantity_infos: list[dict[str, Any]]) -> str | None:
    raw = str(symbol or "").strip()
    if not raw:
        return None
    for info in quantity_infos:
        if raw in {str(info.get("source_name") or ""), str(info.get("name") or "")}:
            lean_type = str(info.get("lean_type") or "").strip()
            normalized, supported, _status = normalize_quantity_lean_type(lean_type)
            return normalized if supported else lean_type or None
    return None


def _inferred_bound_type_from_function_application(
    symbol: str,
    formula: str,
    quantity_infos: list[dict[str, Any]],
) -> str | None:
    raw_symbol = str(symbol or "").strip()
    if not raw_symbol:
        return None
    for info in quantity_infos:
        lean_type = str(info.get("lean_type") or "")
        parts = function_quantity_parts(lean_type)
        if parts is None:
            continue
        domain, _codomain = parts
        names = [
            str(info.get("source_name") or "").strip(),
            str(info.get("name") or "").strip(),
        ]
        for name in [item for index, item in enumerate(names) if item and item not in names[:index]]:
            if _function_application_pattern(name).search(formula):
                for match in _function_application_pattern(name).finditer(formula):
                    if match.group(1).strip() == raw_symbol:
                        return domain
    return None


def _normalize_quantified_binders(formula: str, quantity_infos: list[dict[str, Any]]) -> str:
    def forall_repl(match: re.Match[str]) -> str:
        keyword = match.group("kw")
        symbol = match.group("sym")
        explicit_type = " ".join(str(match.group("typ") or "").split())
        lean_type = (
            explicit_type
            or _declared_quantity_type(symbol, quantity_infos)
            or _inferred_bound_type_from_function_application(symbol, formula, quantity_infos)
        )
        if not lean_type:
            return f"{keyword} {symbol},"
        return f"{keyword} {symbol} : {lean_type},"

    def fun_repl(match: re.Match[str]) -> str:
        symbol = match.group("sym")
        explicit_type = " ".join(str(match.group("typ") or "").split())
        lean_type = (
            explicit_type
            or _declared_quantity_type(symbol, quantity_infos)
            or _inferred_bound_type_from_function_application(symbol, formula, quantity_infos)
        )
        if not lean_type:
            return f"fun {symbol} =>"
        return f"fun {symbol} : {lean_type} =>"

    out = re.sub(
        r"(?P<kw>\bforall|∀)\s+(?P<sym>[A-Za-z_][A-Za-z0-9_']*)(?:\.val)?"
        r"(?:\s*:\s*(?P<typ>[^,]+?))?\s*,",
        forall_repl,
        formula,
    )
    out = re.sub(
        r"\bfun\s+(?P<sym>[A-Za-z_][A-Za-z0-9_']*)(?:\.val)?"
        r"(?:\s*:\s*(?P<typ>[^=]+?))?\s*=>",
        fun_repl,
        out,
    )
    return out


def _rewrite_function_lambda_equalities(formula: str, quantity_infos: list[dict[str, Any]]) -> str:
    out = formula
    function_infos = [
        info for info in quantity_infos if is_function_quantity_lean_type(str(info.get("lean_type") or ""))
    ]
    for info in sorted(function_infos, key=lambda row: len(str(row["source_name"])), reverse=True):
        parts = function_quantity_parts(str(info.get("lean_type") or ""))
        if parts is None:
            continue
        domain, codomain = parts
        lean_name = str(info.get("name") or "")
        names = [str(info.get("source_name") or ""), lean_name]
        for function_name in [name for idx, name in enumerate(names) if name and name not in names[:idx]]:
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_']*", function_name):
                continue

            def repl(match: re.Match[str]) -> str:
                arg = match.group("arg")
                body = str(match.group("body") or "").strip()
                lhs = f"{lean_name} {arg}" if codomain == "Real" else f"({lean_name} {arg}).val"
                return f"(forall {arg} : {domain}, {lhs} = {body})"

            out = re.sub(
                rf"(?<![A-Za-z0-9_.]){re.escape(function_name)}\s*=\s*fun\s+"
                rf"(?P<arg>[A-Za-z_][A-Za-z0-9_']*)(?:\.val)?"
                rf"(?:\s*:\s*[^=∧]+?)?\s*=>\s*(?P<body>[^∧\n]+)",
                repl,
                out,
            )
    return out


def _function_application_pattern(name: str) -> re.Pattern[str]:
    return re.compile(
        rf"(?<![A-Za-z0-9_.]){re.escape(name)}\s+([A-Za-z_][A-Za-z0-9_']*)(?:\.val)?"
        rf"(?![A-Za-z0-9_']|\s*\.|\s*\)\s*\.val)"
    )


def _protect_matches(text: str, patterns: list[re.Pattern[str]]) -> tuple[str, dict[str, str]]:
    protected: dict[str, str] = {}
    out = text
    counter = 0
    for pattern in patterns:
        def repl(match: re.Match[str]) -> str:
            nonlocal counter
            key = f"__PIPELINE_PROTECTED_{counter}__"
            counter += 1
            protected[key] = match.group(0)
            return key

        out = pattern.sub(repl, out)
    return out, protected


def _restore_matches(text: str, protected: dict[str, str]) -> str:
    out = text
    for key, value in protected.items():
        out = out.replace(key, value)
    return out


def _replace_quantity_value_symbol(
    formula: str,
    *,
    source_name: str,
    lean_name: str,
    function_infos: list[dict[str, Any]],
) -> str:
    protected_patterns: list[re.Pattern[str]] = [
        re.compile(rf"(?P<prefix>\b(?:forall|∀)\s+){re.escape(source_name)}(?P<suffix>\s*:)"),
        re.compile(rf"(?P<prefix>\bfun\s+){re.escape(source_name)}(?P<suffix>\s*(?::|=>))"),
    ]
    for info in function_infos:
        for function_name in {str(info.get("source_name") or ""), str(info.get("name") or "")}:
            if not function_name:
                continue
            protected_patterns.append(
                re.compile(
                    rf"(?<![A-Za-z0-9_.]){re.escape(function_name)}\s+{re.escape(source_name)}"
                    rf"(?![A-Za-z0-9_'])"
                )
            )
            if lean_name != source_name:
                protected_patterns.append(
                    re.compile(
                        rf"(?<![A-Za-z0-9_.]){re.escape(function_name)}\s+{re.escape(lean_name)}"
                        rf"(?![A-Za-z0-9_'])"
                    )
                )
    protected_formula, protected = _protect_matches(formula, protected_patterns)
    protected_formula = re.sub(
        rf"(?<![A-Za-z0-9_.]){re.escape(source_name)}(?![A-Za-z0-9_']|\s*\.)",
        f"{lean_name}.val",
        protected_formula,
    )
    if lean_name != source_name:
        protected_formula = re.sub(
            rf"(?<![A-Za-z0-9_.]){re.escape(lean_name)}(?![A-Za-z0-9_']|\s*\.)",
            f"{lean_name}.val",
            protected_formula,
        )
    return _restore_matches(protected_formula, protected)


def _typed_formula_from_text(text: object, quantity_infos: list[dict[str, Any]]) -> str:
    formula = normalize_lean_text(_normalize_unicode_identifiers(str(text or ""))).strip()
    formula = _normalize_invalid_val_binders(formula)
    formula = _rewrite_function_lambda_equalities(formula, quantity_infos)
    formula = _normalize_quantified_binders(formula, quantity_infos)
    formula = formula.replace("!=", "≠")
    formula = re.sub(r"\s+•\s+", " * ", formula)
    formula = _normalize_numeric_literals(formula)
    formula = re.sub(
        r"\(\(\s*([^()]+?)\s*:\s*Real\s*\)\s*:\s*(?:MechLib\.SI\.)?[A-Z][A-Za-z0-9_']*\s*\)",
        r"\1",
        formula,
    )
    formula = _normalize_value_level_numeric_quantity_casts(formula)
    formula = re.sub(r"(?<!\d)\.(?=\s*$)", "", formula).strip()
    if not formula:
        return ""
    bound_variables = _bound_formula_variables(formula)
    function_infos = [
        info for info in quantity_infos if is_function_quantity_lean_type(str(info.get("lean_type") or ""))
    ]
    for info in sorted(function_infos, key=lambda row: len(str(row["source_name"])), reverse=True):
        source_name = str(info["source_name"])
        lean_name = str(info["name"])
        if source_name in bound_variables or lean_name in bound_variables:
            continue
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_']*", source_name):
            continue
        parts = function_quantity_parts(str(info.get("lean_type") or ""))
        codomain = parts[1] if parts else "Real"

        def repl(match: re.Match[str]) -> str:
            arg = match.group(1)
            application = f"{lean_name} {arg}"
            if codomain != "Real":
                return f"({application}).val"
            return application

        formula = _function_application_pattern(source_name).sub(repl, formula)
        if lean_name != source_name:
            formula = _function_application_pattern(lean_name).sub(repl, formula)
    for match in re.finditer(
        r"\b(?:forall|∀)\s+([A-Za-z_][A-Za-z0-9_']*)\s*:\s*([A-Za-z_][A-Za-z0-9_.']*)\s*,",
        formula,
    ):
        bound_name = match.group(1)
        bound_type, supported, _status = normalize_quantity_lean_type(match.group(2))
        if supported and bound_type != "Real":
            formula = _replace_quantity_value_symbol(
                formula,
                source_name=bound_name,
                lean_name=bound_name,
                function_infos=function_infos,
            )
    for info in sorted(quantity_infos, key=lambda row: len(str(row["source_name"])), reverse=True):
        if info.get("lean_type") == "Real" or is_function_quantity_lean_type(str(info.get("lean_type") or "")):
            continue
        source_name = str(info["source_name"])
        lean_name = str(info["name"])
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_']*", source_name):
            continue
        formula = _replace_quantity_value_symbol(
            formula,
            source_name=source_name,
            lean_name=lean_name,
            function_infos=function_infos,
        )
    return formula


def _is_tautological_equality(text: object) -> bool:
    return is_tautological_equality(text)


def _has_unsupported_tuple_formula(text: object) -> bool:
    value = normalize_lean_text(str(text or "")).strip()
    if not value:
        return False
    # The minimal skeleton has no audited vector/pair quantity binder yet.
    # Tuple-valued facts should be canonicalized upstream into scalar component
    # relations before they enter theorem hypotheses or goals.
    return bool(
        re.search(r"=\s*\([^()]*,[^()]*\)", value)
        or re.search(r"\([^()]*,[^()]*\)\s*=", value)
        or re.search(r"=\s*⟨[^⟩]*,[^⟩]*⟩", value)
        or re.search(r"⟨[^⟩]*,[^⟩]*⟩\s*=", value)
    )


def _is_qualitative_hypothesis(text: object) -> bool:
    value = normalize_lean_text(str(text or "")).strip()
    if not value:
        return True
    lowered = value.lower()
    if any(marker in lowered for marker in QUALITATIVE_PREDICATE_MARKERS) and "=" not in value and "<" not in value:
        return True
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_']*(?:\s*∧\s*[A-Za-z_][A-Za-z0-9_']*)*", value):
        return True
    if re.search(r"[A-Za-z_][A-Za-z0-9_']*\s+[A-Za-z_][A-Za-z0-9_']+", value) and not any(
        token in value for token in ("=", "≠", "<", ">", "≤", "≥")
    ):
        return True
    return False


def _selected_names(raw: object) -> set[str]:
    if not isinstance(raw, list):
        return set()
    out: set[str] = set()
    for item in raw:
        if isinstance(item, dict):
            for key in ("name", "source_id", "instance_id", "model_instance_id", "step_id"):
                value = str(item.get(key) or "").strip()
                if value:
                    out.add(value)
        else:
            value = str(item or "").strip()
            if value:
                out.add(value)
    return out


def _safe_given_binders(
    *,
    model_ir: ModelIR | None,
    quantity_infos: list[dict[str, Any]],
    selected_givens: set[str],
) -> tuple[list[HypothesisProvenance], list[dict[str, Any]], list[dict[str, Any]]]:
    if model_ir is None:
        return [], [], []
    accepted: list[HypothesisProvenance] = []
    typed_rows: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    seen: set[str] = set()
    candidates = [*model_ir.givens, *model_ir.local_definitions]
    for index, raw in enumerate(candidates, start=1):
        payload = _dataclass_payload(raw)
        name = str(payload.get("name") or f"h_given_{index}").strip()
        source_id = str(payload.get("source_id") or "").strip()
        if selected_givens and name not in selected_givens and source_id not in selected_givens:
            continue
        lean_text = _payload_lean(raw)
        role = str(payload.get("role") or "problem_fact").strip() or "problem_fact"
        allowed = _payload_allowed(raw)
        typed_lean = _typed_formula_from_text(lean_text, quantity_infos)
        reason: str | None = None
        if not allowed:
            reason = "not_allowed_by_model_ir"
        elif role not in {"problem_fact", "coordinate_convention", "local_definition"}:
            reason = f"unsupported_hypothesis_role:{role}"
        elif _is_tautological_equality(typed_lean):
            reason = "tautological_hypothesis"
        elif _has_unsupported_tuple_formula(typed_lean):
            reason = "tuple_valued_formula"
        elif _is_qualitative_hypothesis(typed_lean):
            reason = "qualitative_or_unknown_predicate"
        elif not _is_allowed_lean_hypothesis(typed_lean):
            reason = "not_lean_like_numeric_fact"
        elif _has_unregistered_formula_symbol(typed_lean, quantity_infos):
            reason = "unregistered_formula_symbol"
        if reason:
            excluded.append(
                {
                    "name": name,
                    "lean": lean_text,
                    "typed_lean": typed_lean,
                    "role": role,
                    "source_type": str(payload.get("source_type") or ""),
                    "source_id": source_id or None,
                    "reason": reason,
                }
            )
            continue
        if name in seen:
            continue
        seen.add(name)
        hyp = HypothesisProvenance(
            name=name,
            lean=typed_lean,
            role=role,
            source_type=str(payload.get("source_type") or "problem_ir").strip() or "problem_ir",
            source_id=source_id or None,
            allowed_in_hypotheses=True,
            notes=str(payload.get("notes") or "").strip() or None,
            proof_fact_allowed=False,
        )
        accepted.append(hyp)
        typed_rows.append(
            {
                "name": name,
                "binder_kind": "hypothesis",
                "lean_type": "Prop",
                "proposition": typed_lean,
                "source": "model_ir.givens",
            }
        )
    return accepted, typed_rows, excluded


def _model_interface_hypotheses(
    *,
    model_ir: ModelIR | None,
    controlled_sketch: ControlledSketch | None,
    quantity_infos: list[dict[str, Any]],
    selected_model_instances: set[str],
    extra_instantiations: list[ModelInterfaceInstantiation] | None = None,
    include_explicit_gaps: bool = True,
) -> tuple[list[HypothesisProvenance], list[dict[str, Any]], list[dict[str, Any]]]:
    if not include_explicit_gaps:
        return [], [], []
    instantiations = [
        *_model_interface_instantiations_from_model_ir(model_ir),
        *_model_interface_instantiations_from_sketch(controlled_sketch),
        *(extra_instantiations or []),
    ]
    accepted: list[HypothesisProvenance] = []
    typed_rows: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(instantiations, start=1):
        if (
            selected_model_instances
            and item.source_model_instance
            and item.source_model_instance not in selected_model_instances
        ):
            continue
        raw_claim = normalize_lean_text(item.formal_claim).strip()
        typed_claim = _typed_formula_from_text(raw_claim, quantity_infos)
        hyp_name = lean_ident(f"h_{item.instantiation_id}", prefix="h")
        reason: str | None = None
        if item.proof_fact_allowed and not item.verified_constructor:
            reason = "proof_fact_allowed_without_verified_constructor"
        elif "MechLib." in typed_claim and not item.verified_constructor:
            reason = "unverified_mechlib_reference"
        elif _is_tautological_equality(typed_claim):
            reason = "tautological_model_interface"
        elif _has_unsupported_tuple_formula(typed_claim):
            reason = "tuple_valued_model_interface"
        elif _is_qualitative_hypothesis(typed_claim):
            reason = "qualitative_or_unknown_predicate"
        elif not _is_allowed_lean_hypothesis(typed_claim):
            reason = "not_lean_like_model_interface"
        elif _has_unregistered_formula_symbol(typed_claim, quantity_infos):
            reason = "unregistered_formula_symbol"
        if reason:
            excluded.append(
                {
                    "name": hyp_name,
                    "lean": raw_claim,
                    "typed_lean": typed_claim,
                    "role": "explicit_gap_law",
                    "source_type": item.source_type,
                    "source_id": item.instantiation_id,
                    "source_model_instance": item.source_model_instance,
                    "reason": reason,
                }
            )
            continue
        key = f"{hyp_name}:{typed_claim}"
        if key in seen:
            continue
        seen.add(key)
        notes = item.notes or "Explicit model interface instantiation; not a verified MechLib declaration."
        hyp = HypothesisProvenance(
            name=hyp_name,
            lean=typed_claim,
            role="explicit_gap_law",
            source_type="gap",
            source_id=item.instantiation_id,
            allowed_in_hypotheses=True,
            notes=notes,
            proof_fact_allowed=False,
        )
        accepted.append(hyp)
        typed_rows.append(
            {
                "name": hyp_name,
                "binder_kind": "model_interface_gap",
                "lean_type": "Prop",
                "proposition": typed_claim,
                "source": {
                    "instantiation_id": item.instantiation_id,
                    "source_model_instance": item.source_model_instance,
                    "kind": item.kind,
                    "binding_status": item.binding_status,
                },
            }
        )
    return accepted, typed_rows, excluded


def _render_typed_quantity_binders(quantity_infos: list[dict[str, Any]]) -> tuple[list[str], list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for info in quantity_infos:
        grouped.setdefault(str(info["lean_type"]), []).append(info)
    lines: list[str] = []
    typed_rows: list[dict[str, Any]] = []
    order = [
        "Mass",
        "Force",
        "Acceleration",
        "Length",
        "Time",
        "Speed",
        "Torque",
        "MomentOfInertia",
        "AngularAcceleration",
        "AngularVelocity",
        "Momentum",
        "Energy",
        "Power",
        "SpringConstant",
        "Real",
    ]
    for lean_type in order + sorted(set(grouped) - set(order)):
        rows = grouped.get(lean_type, [])
        if not rows:
            continue
        names = " ".join(str(row["name"]) for row in rows)
        lines.append(f"  ({names} : {lean_type})")
        for row in rows:
            typed_rows.append(
                {
                    "name": row["name"],
                    "source_name": row["source_name"],
                    "binder_kind": "quantity",
                    "lean_type": lean_type,
                    "typed_quantity": lean_type != "Real",
                    "source": row.get("source", {}),
                    "type_status": row.get("type_status", "ok"),
                    "type_supported": bool(row.get("type_supported", True)),
                    "type_source": row.get("type_source"),
                    "type_confidence": row.get("type_confidence"),
                    "requested_lean_type": row.get("requested_lean_type"),
                }
            )
    return lines, typed_rows


def _decl_returns_model_predicate(statement: str) -> bool:
    text = normalize_lean_text(statement)
    if re.search(r":\s*Prop(\s|$)", text):
        return True
    if re.search(r"(→|->)\s*Prop(\s|$)", text):
        return True
    return False


def _predicate_fq_from_short_name(binding_fq_name: str, predicate_name: str) -> str:
    if "." in predicate_name:
        return predicate_name
    namespace = str(binding_fq_name or "").rsplit(".", 1)[0]
    return f"{namespace}.{predicate_name}" if namespace else predicate_name


def _model_predicate_from_decl_statement(binding: EvidenceBinding) -> tuple[str, list[str]] | None:
    statement = normalize_lean_text(binding.decl_statement or "")
    if not binding.verified_decl or not statement:
        return None
    param_types = _decl_param_types(statement)
    if _decl_returns_model_predicate(statement):
        return binding.verified_decl, param_types
    conclusion = statement.rsplit(":", 1)[-1].strip() if ":" in statement else ""
    match = re.match(r"([A-Z][A-Za-z0-9']*(?:\.[A-Z][A-Za-z0-9']*)*)\s+(.+?)\s*=", conclusion)
    if not match:
        return None
    predicate_name = match.group(1)
    if not param_types:
        return None
    lhs_arg_count = len(re.findall(r"[A-Za-z_][A-Za-z0-9_']*", match.group(2)))
    if lhs_arg_count != len(param_types):
        return None
    return _predicate_fq_from_short_name(binding.verified_decl, predicate_name), param_types


def _decl_param_types(statement: str) -> list[str]:
    types: list[str] = []
    for match in re.finditer(r"\(\s*[A-Za-z_][A-Za-z0-9_']*(?:\s+[A-Za-z_][A-Za-z0-9_']*)*\s*:\s*([^)]+)\)", statement):
        raw_type = " ".join(match.group(1).split())
        if any(token in raw_type for token in ("->", "→", "=>", "∀", "forall")):
            continue
        lean_type = raw_type.rsplit(".", 1)[-1]
        if lean_type in QUANTITY_TYPE_NAMES or lean_type == "Real":
            types.append(lean_type)
    return types


def _role_type_hint(role: object) -> str:
    return _type_from_hint(role)


def _instance_symbol_by_type(
    instance: ModelInstance,
    info_by_symbol: dict[str, dict[str, Any]],
) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for raw_role, raw_symbol in (instance.variables or {}).items():
        if not isinstance(raw_symbol, str):
            continue
        symbol = lean_ident(_normalize_unicode_identifiers(raw_symbol), prefix="q")
        info = info_by_symbol.get(raw_symbol) or info_by_symbol.get(symbol)
        lean_type = str(info.get("lean_type")) if info else "Real"
        out.setdefault(lean_type, [])
        if symbol not in out[lean_type]:
            out[lean_type].append(symbol)
    for raw in getattr(instance, "interface_instantiations", []) or []:
        item = _model_interface_instantiation_from_payload(raw, len(out) + 1)
        if item is None:
            continue
        info = _introduced_quantity_info(item)
        if info is None:
            continue
        symbol = str(info["name"])
        lean_type = str(info["lean_type"])
        out.setdefault(lean_type, [])
        if symbol not in out[lean_type]:
            out[lean_type].insert(0, symbol)
    return out


def _instance_roles(instance: ModelInstance) -> set[str]:
    roles = {str(role or "").strip().lower() for role in (instance.variables or {})}
    for raw in getattr(instance, "interface_instantiations", []) or []:
        item = _model_interface_instantiation_from_payload(raw, 1)
        if item is None:
            continue
        roles.update(
            value
            for value in (
                item.kind,
                item.interface_name or "",
                item.parameter_role or "",
            )
            if value
        )
    return {role.lower() for role in roles}


def _force_argument_is_safe_for_predicate(instance: ModelInstance, predicate_fq_name: str) -> bool:
    if "NewtonSecondLaw" not in predicate_fq_name and "Newton1D" not in predicate_fq_name:
        return True
    roles = _instance_roles(instance)
    if any("net" in role or "resultant" in role for role in roles):
        return True
    force_like_roles = {role for role in roles if any(key in role for key in ("force", "tension", "weight"))}
    gravity_like = any("gravity" in role or "weight" in role for role in roles)
    if gravity_like and force_like_roles:
        return False
    return bool(force_like_roles)


def _predicate_application_for_instance(
    *,
    instance: ModelInstance,
    binding: EvidenceBinding,
    info_by_symbol: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    predicate_info = _model_predicate_from_decl_statement(binding)
    statement = normalize_lean_text(binding.decl_statement or "")
    if predicate_info is None:
        return None
    predicate_fq_name, param_types = predicate_info
    if not param_types:
        return None
    if "Force" in param_types and not _force_argument_is_safe_for_predicate(instance, predicate_fq_name):
        return None
    symbols_by_type = _instance_symbol_by_type(instance, info_by_symbol)
    used_symbols: list[str] = []
    for lean_type in param_types:
        choices = symbols_by_type.get(lean_type, [])
        if not choices:
            return None
        used_symbols.append(choices.pop(0))
    proposition = " ".join([predicate_fq_name, *used_symbols])
    binder_name = lean_ident(f"{instance.instance_id}_law", prefix="law")
    return {
        "name": binder_name,
        "proposition": proposition,
        "verified_decl": binding.verified_decl,
        "model_predicate": predicate_fq_name,
        "binding_id": binding.binding_id,
        "model_instance_id": instance.instance_id,
        "param_types": param_types,
        "arguments": used_symbols,
        "decl_statement": statement,
    }


def _model_predicate_bindings(
    *,
    model_ir: ModelIR | None,
    evidence_bindings: list[EvidenceBinding],
    quantity_infos: list[dict[str, Any]],
    selected_model_instances: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if model_ir is None:
        return [], []
    binding_by_instance: dict[str, list[EvidenceBinding]] = {}
    for binding in evidence_bindings:
        if (
            binding.binding_status == "ok"
            and binding.proof_fact_allowed
            and binding.verified_decl
            and binding.lean_check_pass is not False
            and binding.callable_by_llm is not False
        ):
            binding_by_instance.setdefault(binding.model_instance_id, []).append(binding)
    info_by_symbol = _quantity_info_map(quantity_infos)
    bound: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for instance in model_ir.model_instances:
        if selected_model_instances and instance.instance_id not in selected_model_instances:
            continue
        match: dict[str, Any] | None = None
        for binding in binding_by_instance.get(instance.instance_id, []):
            match = _predicate_application_for_instance(
                instance=instance,
                binding=binding,
                info_by_symbol=info_by_symbol,
            )
            if match is not None:
                break
        if match is not None:
            bound.append(match)
        else:
            first = (binding_by_instance.get(instance.instance_id) or [None])[0]
            blocked.append(
                {
                    "step_id": f"blocked_{instance.instance_id}",
                    "source_model_instance": instance.instance_id,
                    "planning_schema": instance.planning_schema_id,
                    "expected_claim": instance.expected_claim,
                    "verified_decl": None,
                    "candidate_decl": first.verified_decl if first else None,
                    "binding_status": "signature_mismatch" if first else "gap_schema_only",
                    "proof_fact_allowed": False,
                    "reason": "No checked Prop-valued MechLib model predicate matched this ModelInstance signature.",
                }
            )
    return bound, blocked


FUNCTION_FORMULA_KINDS = {
    "scalar_relation",
    "pointwise_relation",
    "evaluation_relation",
    "ode_relation",
    "component_relation",
    "property",
    "unknown",
}


def _quantity_infos_with_bound_variables(
    quantity_infos: list[dict[str, Any]],
    bound_variables: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    out = list(quantity_infos)
    existing = {str(info.get("name") or "") for info in out}
    existing.update(str(info.get("source_name") or "") for info in out)
    for item in bound_variables:
        name = str(item.get("name") or item.get("symbol") or item.get("variable") or "").strip()
        if not name or name in existing:
            continue
        requested = str(item.get("lean_type") or item.get("type") or item.get("domain") or "").strip()
        lean_type, supported, status = normalize_quantity_lean_type(requested or "Real")
        if not supported:
            lean_type = "Real"
        out.append(
            {
                "name": name,
                "source_name": name,
                "lean_type": lean_type,
                "source": item,
                "typed_quantity": lean_type != "Real",
                "type_status": status,
                "type_supported": supported,
                "type_source": "function_formula_ir.bound_variable",
                "type_confidence": 1.0 if requested else 0.0,
                "requested_lean_type": requested,
            }
        )
        existing.add(name)
    return out


def _bound_variable_binder(item: dict[str, Any]) -> tuple[str, str] | None:
    name = str(item.get("name") or item.get("symbol") or item.get("variable") or "").strip()
    requested = str(item.get("lean_type") or item.get("type") or item.get("domain") or "").strip()
    if not name or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_']*", name):
        return None
    lean_type, supported, _status = normalize_quantity_lean_type(requested or "Real")
    if not supported:
        lean_type = "Real"
    return name, lean_type


def _formula_from_function_formula_ir(
    row: dict[str, Any],
    quantity_infos: list[dict[str, Any]],
) -> tuple[str, str | None]:
    if row.get("parse_ok") is False:
        return "", str(row.get("error") or "invalid_function_formula_ir")
    formula_kind = str(row.get("formula_kind") or "unknown").strip() or "unknown"
    if formula_kind not in FUNCTION_FORMULA_KINDS:
        return "", "invalid_function_formula_kind"
    bound_variables = [dict(item) for item in row.get("bound_variables") or [] if isinstance(item, dict)]
    local_infos = _quantity_infos_with_bound_variables(quantity_infos, bound_variables)
    lhs = normalize_lean_text(str(row.get("lhs") or "")).strip()
    rhs = normalize_lean_text(str(row.get("rhs") or "")).strip()
    relation = str(row.get("relation") or "=").strip() or "="
    raw_formula = normalize_lean_text(str(row.get("lean_formula") or "")).strip()
    if lhs and rhs:
        raw_formula = f"{lhs} {relation} {rhs}"
    if not raw_formula:
        return "", "missing_function_formula"
    if formula_kind in {"pointwise_relation", "ode_relation"} and not bound_variables and not re.match(
        r"^\s*(?:forall|∀)\b", raw_formula
    ):
        return "", "missing_function_bound_variables"
    body = _typed_formula_from_text(raw_formula, local_infos)
    if not body or "?" in body or _has_unsupported_tuple_formula(body) or not _is_allowed_lean_target(body):
        return "", "invalid_function_formula_ir"
    if _has_unregistered_formula_symbol(body, local_infos):
        return "", "invalid_function_formula_ir"
    if not re.match(r"^\s*(?:forall|∀)\b", body):
        domain_conditions = [
            _typed_formula_from_text(item, local_infos)
            for item in row.get("domain_conditions") or []
            if str(item or "").strip()
        ]
        domain_conditions = [
            item
            for item in domain_conditions
            if item and "?" not in item and _is_allowed_lean_hypothesis(item)
        ]
        if domain_conditions:
            body = f"{' ∧ '.join(domain_conditions)} -> {body}"
        for bound in reversed(bound_variables):
            binder = _bound_variable_binder(bound)
            if binder is None:
                return "", "invalid_function_bound_variable"
            name, lean_type = binder
            body = f"forall {name} : {lean_type}, {body}"
    if _is_tautological_equality(body):
        return "", "tautological_canonical_target"
    return body, None


def _target_formula(
    *,
    model_ir: ModelIR | None,
    controlled_sketch: ControlledSketch | None,
    quantity_infos: list[dict[str, Any]],
) -> tuple[str, str | None]:
    _ = controlled_sketch
    canonical = getattr(model_ir, "canonical_target", None) if model_ir is not None else None
    if canonical is None:
        return "False", "missing_canonical_target"
    payload = _dataclass_payload(canonical)
    if payload.get("parse_ok") is not True:
        return "False", str(payload.get("error") or "missing_canonical_target")
    function_formula_rows = [
        _dataclass_payload(item)
        for item in (payload.get("function_formula_ir") or [])
        if _dataclass_payload(item)
    ]
    if function_formula_rows:
        formulas: list[str] = []
        seen_ir: set[str] = set()
        for row in function_formula_rows:
            formula, error = _formula_from_function_formula_ir(row, quantity_infos)
            if error:
                return "False", error
            key = re.sub(r"\s+", "", formula)
            if key and key not in seen_ir:
                seen_ir.add(key)
                formulas.append(formula)
        if formulas:
            if len(formulas) > 1:
                formulas = [
                    f"({formula})" if re.match(r"^\s*(?:forall|∀|Exists|∃)\b", formula) else formula
                    for formula in formulas
                ]
            return " ∧\n  ".join(formulas), None
        return "False", "invalid_function_formula_ir"
    raw_formulas = [normalize_lean_text(str(payload.get("lean_formula") or "")).strip()]
    secondary = payload.get("secondary_formulas")
    if isinstance(secondary, list):
        raw_formulas.extend(normalize_lean_text(str(item or "")).strip() for item in secondary)
    formulas: list[str] = []
    seen: set[str] = set()
    for raw in raw_formulas:
        if not raw:
            continue
        formula = _typed_formula_from_text(raw, quantity_infos)
        key = re.sub(r"\s+", "", formula)
        if not formula or key in seen:
            continue
        seen.add(key)
        if _is_tautological_equality(formula):
            return "False", "tautological_canonical_target"
        if (
            "?" in formula
            or _has_unsupported_tuple_formula(formula)
            or not _is_allowed_lean_target(formula)
            or _has_unregistered_formula_symbol(formula, quantity_infos)
        ):
            return "False", "invalid_canonical_target_formula"
        formulas.append(formula)
    if formulas:
        if len(formulas) > 1:
            formulas = [
                f"({formula})" if re.match(r"^\s*(?:forall|∀|Exists|∃)\b", formula) else formula
                for formula in formulas
            ]
        return " ∧\n  ".join(formulas), None
    return "False", "invalid_canonical_target_formula"


def _target_formula_from_forbidden_as_assumption(model_ir: ModelIR) -> str:
    for item in model_ir.forbidden_as_assumption or []:
        text = str(item or "").strip()
        if "|" not in text:
            continue
        parts = [part.strip() for part in text.split("|")]
        if len(parts) < 2:
            continue
        label = parts[0].lower()
        formula = parts[1]
        if not any(marker in label for marker in ("target", "final", "answer")):
            continue
        if "=" not in formula:
            continue
        formula = re.sub(r"\s+and\s+", " ∧ ", formula, flags=re.IGNORECASE)
        return formula
    return ""


def _target_formula_from_target_spec(model_ir: ModelIR | None, selected_target: object | None = None) -> str:
    candidates: list[object] = []

    def add_target_payload(payload: object) -> None:
        if not isinstance(payload, dict):
            return
        candidates.extend(
            payload.get(key)
            for key in ("lean", "formal_claim", "formula", "target_form", "expected_formula")
        )
        for key in ("formal_targets", "targets", "target_formulas", "expected_formulas"):
            value = payload.get(key)
            if isinstance(value, list):
                formulas: list[str] = []
                for item in value:
                    if isinstance(item, dict):
                        item_text = next(
                            (
                                str(item.get(item_key) or "").strip()
                                for item_key in ("lean", "formal_claim", "formula", "target_form", "expected_formula")
                                if str(item.get(item_key) or "").strip()
                            ),
                            "",
                        )
                    else:
                        item_text = str(item or "").strip()
                    if item_text and any(token in item_text for token in ("=", "≠", "<", ">", "≤", "≥", "\\le", "\\ge")):
                        formulas.append(item_text)
                if formulas:
                    candidates.append(" ∧ ".join(formulas))

    if isinstance(selected_target, dict):
        add_target_payload(selected_target)
    if model_ir is not None:
        target_spec = getattr(model_ir, "target_spec", {}) or {}
        add_target_payload(target_spec)
        add_target_payload(model_ir.target)
    for raw in candidates:
        text = normalize_lean_text(str(raw or "")).strip()
        if text and any(token in text for token in ("=", "≠", "<", ">", "≤", "≥", "\\le", "\\ge", "∧", "∨")):
            return text
    return ""


def _proof_obligation_conjunction(
    controlled_sketch: ControlledSketch | None,
    quantity_infos: list[dict[str, Any]],
) -> str:
    if controlled_sketch is None:
        return ""
    formulas: list[str] = []
    seen: set[str] = set()
    for step in controlled_sketch.proof_steps:
        raw = str(step.formal_claim or step.expected_claim or "").strip()
        typed = _typed_formula_from_text(raw, quantity_infos)
        if not typed or "?" in typed or not _is_allowed_lean_hypothesis(typed):
            continue
        if _has_unregistered_formula_symbol(typed, quantity_infos):
            continue
        if typed in seen:
            continue
        seen.add(typed)
        formulas.append(typed)
    if not formulas:
        return ""
    return " ∧ ".join(formulas)


def _target_formula_with_policy(
    *,
    model_ir: ModelIR | None,
    controlled_sketch: ControlledSketch | None,
    quantity_infos: list[dict[str, Any]],
    target_form_policy: str,
    selected_target: object | None,
) -> tuple[str, str | None]:
    _ = (target_form_policy, selected_target)
    return _target_formula(
        model_ir=model_ir,
        controlled_sketch=controlled_sketch,
        quantity_infos=quantity_infos,
    )


def _render_theorem_decl(
    *,
    sample_id: str,
    candidate_id: str,
    theorem_name_hint: str | None,
    quantity_infos: list[dict[str, Any]],
    given_hypotheses: list[HypothesisProvenance],
    model_predicates: list[dict[str, Any]],
    target_formula: str,
) -> tuple[str, list[dict[str, Any]]]:
    hint = theorem_name_hint or "minimal_skeleton"
    name = lean_ident(f"{sample_id}_{candidate_id}_{hint}", prefix="thm")
    quantity_lines, typed_rows = _render_typed_quantity_binders(quantity_infos)
    hyp_lines = [f"  ({hyp.name} : {hyp.lean})" for hyp in given_hypotheses]
    predicate_lines = [
        f"  ({row['name']} : {row['proposition']})"
        for row in model_predicates
    ]
    lines = [f"theorem {name}", *quantity_lines, *hyp_lines, *predicate_lines, f"  : {target_formula}"]
    return "\n".join(lines), typed_rows


def _is_allowed_lean_hypothesis(text: object) -> bool:
    value = normalize_lean_text(str(text or "")).strip()
    if not value or value in {"True", "False"}:
        return False
    lowered = value.lower()
    if any(unit in f" {lowered} " for unit in (" in ", " cm ", " kg ", " m/s ", " n ")):
        return False
    if any(marker in lowered for marker in (" is ", " are ", " represented as ", " occurs ", " applies ")):
        return False
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_']*(?:\s+[A-Za-z_][A-Za-z0-9_']*)*", value):
        return False
    return any(token in value for token in ("=", "≠", "<", ">", "≤", "≥", "\\le", "\\ge"))


def _is_allowed_lean_target(text: object) -> bool:
    value = normalize_lean_text(str(text or "")).strip()
    if not value or value == "False":
        return False
    if _is_allowed_lean_hypothesis(value):
        return True
    if value.startswith(("∀", "forall ", "∃", "Exists ")):
        return True
    return "MechLib." in value and not _is_qualitative_hypothesis(value)


def _has_unregistered_formula_symbol(text: object, quantity_infos: list[dict[str, Any]]) -> bool:
    value = normalize_lean_text(str(text or "")).strip()
    if not value:
        return True
    # SI quantity values are Real values, not functions. Forms like x.val(t)
    # come from opaque natural-language modeling and cannot be audited here.
    if re.search(r"\.val\s*\(", value):
        return True
    declared = {str(info.get("name") or "") for info in quantity_infos}
    declared.update(str(info.get("source_name") or "") for info in quantity_infos)
    known = set(declared)
    known.update(_bound_formula_variables(value))
    known.update(LEAN_CORE_TOKENS)
    known.update(SAFE_FUNCTION_TOKENS)
    known.update(QUANTITY_TYPE_NAMES)
    known.update({"val", "pi"})
    for match in re.finditer(r"(?<!\.)\b([A-Za-z_][A-Za-z0-9_']*)\s*\(", value):
        if match.group(1) not in known:
            return True
    for token in IDENT_PATTERN.findall(value):
        if token in known or token in {"Real", "Nat", "Int", "Rat"}:
            continue
        return True
    return False


def _canonical_provenance(value: object, index: int) -> HypothesisProvenance:
    if isinstance(value, HypothesisProvenance):
        return value
    payload = _dataclass_payload(value)
    role = str(payload.get("role") or "unknown").strip() or "unknown"
    source_type = str(payload.get("source_type") or "llm_generated").strip() or "llm_generated"
    notes = str(payload.get("notes") or "").strip() or None
    if role == "explicit_gap_law" and notes is None:
        notes = "No verified MechLib declaration bound; used as explicit modeling gap."
    lean_text = normalize_lean_text(str(payload.get("lean") or ""))
    allowed = _as_bool(payload.get("allowed_in_hypotheses"))
    if allowed and not _is_allowed_lean_hypothesis(lean_text):
        allowed = False
        notes = (notes + " " if notes else "") + "Excluded from theorem hypotheses: not a Lean-like problem fact."
    return HypothesisProvenance(
        name=str(payload.get("name") or f"h_unknown_{index}").strip() or f"h_unknown_{index}",
        lean=lean_text,
        role=role,
        source_type=source_type,
        source_id=str(payload.get("source_id") or "").strip() or None,
        allowed_in_hypotheses=allowed,
        notes=notes,
        proof_fact_allowed=False if role == "explicit_gap_law" else _as_bool(payload.get("proof_fact_allowed")),
    )


def _provenance_missing_required(value: object) -> bool:
    payload = _dataclass_payload(value)
    required = ("name", "lean", "role", "source_type", "allowed_in_hypotheses")
    return any(key not in payload or payload.get(key) in (None, "") for key in required)


def _hypothesis_binders(theorem_decl: str) -> list[tuple[str, str]]:
    binders: list[tuple[str, str]] = []
    decl = _declaration_only(theorem_decl)
    idx = 0
    while idx < len(decl):
        if decl[idx] != "(":
            idx += 1
            continue
        depth = 1
        end = idx + 1
        while end < len(decl) and depth:
            if decl[end] == "(":
                depth += 1
            elif decl[end] == ")":
                depth -= 1
            end += 1
        if depth:
            break
        content = decl[idx + 1 : end - 1].strip()
        idx = end
        if ":" not in content:
            continue
        lhs, rhs = content.split(":", 1)
        names = lhs.split()
        if len(names) != 1:
            continue
        name = names[0].strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_']*", name):
            continue
        proposition = " ".join(rhs.split())
        if not proposition:
            continue
        if _is_type_binder_proposition(proposition):
            continue
        if name.startswith("h") or any(token in proposition for token in ["=", "≠", "<", ">", "≤", "≥", "∧", "∨", "Not "]):
            binders.append((name, proposition))
    return binders


def _decl_binder_spans(theorem_decl: str) -> list[tuple[int, int, str, str]]:
    spans: list[tuple[int, int, str, str]] = []
    decl = _declaration_only(theorem_decl)
    idx = 0
    while idx < len(decl):
        if decl[idx] != "(":
            idx += 1
            continue
        depth = 1
        end = idx + 1
        while end < len(decl) and depth:
            if decl[end] == "(":
                depth += 1
            elif decl[end] == ")":
                depth -= 1
            end += 1
        if depth:
            break
        content = decl[idx + 1 : end - 1].strip()
        if ":" in content:
            lhs, rhs = content.split(":", 1)
            names = lhs.split()
            if len(names) == 1 and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_']*", names[0]):
                spans.append((idx, end, names[0], " ".join(rhs.split())))
        idx = end
    return spans


def _is_type_binder_proposition(proposition: str) -> bool:
    prop = " ".join(str(proposition or "").split())
    if prop in {"Real", "Nat", "Int", "Rat", "Prop", "Type"}:
        return True
    normalized, supported, _status = normalize_quantity_lean_type(prop)
    if supported and normalized:
        return True
    return prop.startswith("Type")


def _remove_decl_spans(text: str, spans: list[tuple[int, int]]) -> str:
    out = text
    for start, end in sorted(spans, reverse=True):
        left = out[:start].rstrip()
        right = out[end:].lstrip()
        joiner = " " if left and right and not right.startswith(":") else ""
        out = f"{left}{joiner}{right}"
    return "\n".join(line.rstrip() for line in out.splitlines()).strip()


def _goal_text(theorem_decl: str) -> str:
    decl = _declaration_only(theorem_decl)
    if ":" not in decl:
        return ""
    return decl.rsplit(":", 1)[1].strip()


def _unknown_real_symbols(text: str, theorem_decl: str) -> list[str]:
    declared = _extract_binder_names(theorem_decl)
    parsed = _parse_decl_name(theorem_decl)
    if parsed:
        declared.add(parsed[1])
    known = set(declared)
    known.update(_bound_formula_variables(text))
    known.update(LEAN_CORE_TOKENS)
    known.update(SAFE_FUNCTION_TOKENS)
    known.update({"sin", "cos", "tan", "asin", "acos", "atan", "exp", "log", "pow", "unit_of"})
    out: list[str] = []
    seen: set[str] = set()
    for token in IDENT_PATTERN.findall(text):
        if token in known or token in seen:
            continue
        if token.startswith("h_") or token.startswith("h"):
            continue
        if token[0].isupper() and len(token) > 1:
            continue
        seen.add(token)
        out.append(token)
    return out


def _add_symbols_to_first_real_binder(theorem_decl: str, symbols: list[str]) -> str:
    symbols = [sym for sym in symbols if sym and sym not in _extract_binder_names(theorem_decl)]
    if not symbols:
        return theorem_decl

    def repl(match: re.Match[str]) -> str:
        names = match.group(1).split()
        merged = names + [sym for sym in symbols if sym not in names]
        return f"({' '.join(merged)} : Real)"

    updated, count = re.subn(
        r"\(\s*([A-Za-z_][A-Za-z0-9_']*(?:\s+[A-Za-z_][A-Za-z0-9_']*)*)\s*:\s*Real\s*\)",
        repl,
        theorem_decl,
        count=1,
    )
    if count:
        return updated
    parsed = _parse_decl_name(theorem_decl)
    if not parsed:
        return theorem_decl
    kw, name, rest = parsed
    return f"{kw} {name} ({' '.join(symbols)} : Real){rest}"


def _sanitize_minimal_theorem_decl(
    theorem_decl: str,
    hypothesis_provenance: list[HypothesisProvenance],
) -> str:
    provenance_by_name = {hyp.name: hyp for hyp in hypothesis_provenance}
    provenance_by_lean = {normalize_lean_text(hyp.lean): hyp for hyp in hypothesis_provenance if hyp.lean}
    remove: list[tuple[int, int]] = []
    for start, end, name, proposition in _decl_binder_spans(theorem_decl):
        if _is_type_binder_proposition(proposition):
            continue
        hyp = provenance_by_name.get(name) or provenance_by_lean.get(normalize_lean_text(proposition))
        if not _is_allowed_lean_hypothesis(proposition):
            remove.append((start, end))
            continue
        if hyp is not None and not hyp.allowed_in_hypotheses:
            remove.append((start, end))
            continue
        if hyp is not None and hyp.role not in MINIMAL_HYPOTHESIS_ROLES:
            remove.append((start, end))
            continue
    sanitized = _remove_decl_spans(theorem_decl, remove)
    formula_text = "\n".join([prop for _, prop in _hypothesis_binders(sanitized)])
    goal = _goal_text(sanitized)
    symbols = _unknown_real_symbols(f"{formula_text}\n{goal}", sanitized)
    return _add_symbols_to_first_real_binder(sanitized, symbols)


def _norm_compact(text: object) -> str:
    return re.sub(r"\s+", "", str(text or "").strip().lower())


def _tokens_for_match(text: object) -> set[str]:
    return {tok.lower() for tok in re.findall(r"[A-Za-z_][A-Za-z0-9_']*", str(text or "")) if len(tok) > 1}


def _text_matches(reference: object, candidate: object) -> bool:
    ref = " ".join(str(reference or "").lower().split())
    cand = " ".join(str(candidate or "").lower().split())
    if not ref or not cand:
        return False
    ref_compact = _norm_compact(reference)
    cand_compact = _norm_compact(candidate)
    if len(ref_compact) >= 4 and len(cand_compact) >= 4:
        if ref_compact in cand_compact or cand_compact in ref_compact:
            return True
    ref_tokens = _tokens_for_match(reference)
    cand_tokens = _tokens_for_match(candidate)
    if len(ref_tokens) >= 2 and ref_tokens.issubset(cand_tokens):
        return True
    if len(cand_tokens) >= 2 and cand_tokens.issubset(ref_tokens):
        return True
    return False


def _has_formula_relation(text: object) -> bool:
    raw = str(text or "")
    return any(token in raw for token in ("=", "≠", "<", ">", "≤", "≥", "\\le", "\\ge"))


def _target_text_matches(reference: object, candidate: object) -> bool:
    ref = " ".join(str(reference or "").lower().split())
    cand = " ".join(str(candidate or "").lower().split())
    if not ref or not cand:
        return False
    if _has_target_marker(candidate) and _text_matches(reference, candidate):
        return True
    ref_compact = _norm_compact(reference)
    cand_compact = _norm_compact(candidate)
    if _has_formula_relation(reference) and _has_formula_relation(candidate):
        if len(ref_compact) >= 8 and ref_compact == cand_compact:
            return True
        if len(cand_compact) >= 16 and cand_compact in ref_compact:
            return True
        if len(ref_compact) >= 16 and ref_compact in cand_compact:
            return True
    if len(ref_compact) >= 16 and ref_compact == cand_compact:
        return True
    return False


MODELING_HYPOTHESIS_MARKERS = (
    "model",
    "interface",
    "constraint",
    "definition",
    "coordinate",
    "sign_convention",
    "net_force",
    "fnet",
    "newton",
    "force_balance",
    "torque_balance",
    "same_acceleration",
    "common_acceleration",
    "acceleration_magnitude",
    "nonstretch",
    "no_slip",
    "kinematic",
)


def _looks_like_audited_modeling_hypothesis(
    hyp: HypothesisProvenance | None,
    proposition: object,
) -> bool:
    if hyp is None:
        return False
    text = normalize_lean_text(str(proposition or "")).strip()
    if not _is_allowed_lean_hypothesis(text):
        return False
    if _is_tautological_equality(text) or _has_unsupported_tuple_formula(text):
        return False
    if hyp.role == "explicit_gap_law" and hyp.source_type == "gap" and not hyp.proof_fact_allowed:
        return True
    if hyp.role not in {"problem_fact", "coordinate_convention", "local_definition", "model_instance"}:
        return False
    blob = " ".join(
        str(item or "").lower()
        for item in (hyp.name, hyp.source_type, hyp.source_id, hyp.notes, text)
    )
    if any(marker in blob for marker in MODELING_HYPOTHESIS_MARKERS):
        return True
    return hyp.source_type == "model_ir" and hyp.role in {"coordinate_convention", "local_definition"}


def _has_target_marker(text: object) -> bool:
    low = " ".join(str(text or "").lower().split())
    if not low:
        return False
    if any(phrase in low for phrase in ("candidate answer", "final answer", "final_numeric")):
        return True
    return re.search(r"(?<![A-Za-z0-9_])(target|goal|answer|final)(?![A-Za-z0-9_])", low) is not None


def _is_target_forbidden_text(text: object) -> bool:
    low = " ".join(str(text or "").lower().split())
    if not low:
        return False
    return low.startswith(("target", "goal", "candidate_answer", "final", "final_numeric")) or _has_target_marker(low)


def _step_result_refs(step: ControlledSketchStep) -> list[str]:
    refs = [str(step.formal_claim or step.expected_claim or "").strip()]
    if not refs[0]:
        refs = [str(step.claim or "").strip()]
    return [ref for ref in refs if ref]


def _target_texts(model_ir: ModelIR | None, problem_ir: dict[str, Any] | None) -> list[str]:
    out: list[str] = []
    if model_ir is not None:
        canonical = getattr(model_ir, "canonical_target", None)
        if canonical is not None:
            payload = _dataclass_payload(canonical)
            keys = ("lean_formula", "source_text") if payload.get("parse_ok") is True else ("source_text",)
            for key in keys:
                value = str(payload.get(key) or "").strip()
                if value:
                    out.append(value)
            secondary = payload.get("secondary_formulas")
            if payload.get("parse_ok") is True and isinstance(secondary, list):
                out.extend(str(item).strip() for item in secondary if str(item).strip())
            function_formula_ir = payload.get("function_formula_ir")
            if payload.get("parse_ok") is True and isinstance(function_formula_ir, list):
                for item in function_formula_ir:
                    row = _dataclass_payload(item)
                    for key in ("lean_formula", "lhs", "rhs", "source_text"):
                        value = str(row.get(key) or "").strip()
                        if value:
                            out.append(value)
        else:
            target = model_ir.target or {}
            if isinstance(target, dict):
                pieces = [str(v).strip() for v in target.values() if str(v).strip()]
                if len(pieces) > 1:
                    out.append(" ".join(pieces))
                out.extend(v for v in pieces if len(v) >= 2)
        out.extend(
            str(item).strip()
            for item in model_ir.forbidden_as_assumption
            if str(item).strip() and _is_target_forbidden_text(item)
        )
    ir = problem_ir or {}
    unknown = ir.get("unknown_target")
    if isinstance(unknown, dict):
        pieces = [str(unknown.get("symbol") or ""), str(unknown.get("description") or "")]
        text = " ".join(x for x in pieces if x.strip()).strip()
        if text:
            out.append(text)
    goal = str(ir.get("goal_statement") or "").strip()
    if goal:
        out.append(goal)
    seen: set[str] = set()
    unique: list[str] = []
    for item in out:
        key = " ".join(item.lower().split())
        if key and key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def _candidate_answer_texts(problem_ir: dict[str, Any] | None) -> list[str]:
    ir = problem_ir or {}
    out: list[str] = []
    for key in ("candidate_answer", "predicted_answer", "answer", "final_answer", "gold_answer", "choice_answer"):
        value = str(ir.get(key) or "").strip()
        if value:
            out.append(value)
    return out


def _model_expected_claims(model_ir: ModelIR | None) -> list[str]:
    if model_ir is None:
        return []
    return [str(item.expected_claim or "").strip() for item in model_ir.model_instances if str(item.expected_claim or "").strip()]


def _selected_sketch_steps(
    controlled_sketch: ControlledSketch | None,
    requested_ids: list[str],
) -> list[ControlledSketchStep]:
    steps = _all_sketch_steps(controlled_sketch)
    if not requested_ids:
        return steps
    requested = set(requested_ids)
    return [step for step in steps if step.step_id in requested]


def _canonical_proof_obligations(
    *,
    controlled_sketch: ControlledSketch | None,
    requested_ids: list[str],
) -> list[ControlledSketchStep]:
    return [
        _step_from_payload(step, idx)
        for idx, step in enumerate(_selected_sketch_steps(controlled_sketch, requested_ids), start=1)
    ]


def _sketch_for_variant(controlled_sketch: ControlledSketch | None, variant: SketchVariant | None) -> ControlledSketch | None:
    if controlled_sketch is None or variant is None:
        return controlled_sketch
    return ControlledSketch(
        sample_id=controlled_sketch.sample_id,
        schema_version=controlled_sketch.schema_version,
        status=controlled_sketch.status,
        proof_steps=list(variant.proof_steps),
        algebra_obligation=variant.algebra_obligation,
        blocked_law_steps=list(variant.blocked_law_steps),
        model_interface_instantiations=(
            list(controlled_sketch.model_interface_instantiations)
            if variant.gap_policy == "explicit_gap_law"
            else []
        ),
        sketch_variants=list(controlled_sketch.sketch_variants),
        repair_directives=list(controlled_sketch.repair_directives),
        parse_ok=controlled_sketch.parse_ok,
        raw_response=controlled_sketch.raw_response,
        error=controlled_sketch.error,
    )


def _variant_payloads(controlled_sketch: ControlledSketch | None) -> list[dict[str, Any]]:
    if controlled_sketch is None:
        return []
    variants = list(getattr(controlled_sketch, "sketch_variants", []) or [])
    variant = next(
        (
            item
            for item in variants
            if isinstance(item, SketchVariant)
            and (item.gap_policy == "explicit_gap_law" or item.variant_policy == "explicit_gap_allowed")
        ),
        None,
    )
    if variant is None and variants:
        variant = next((item for item in variants if isinstance(item, SketchVariant)), None)
    if variant is not None:
        proof_steps = list(variant.proof_steps)
        blocked_steps = list(variant.blocked_law_steps)
        target_form_policy = variant.target_form_policy or "algebra_obligation"
        variant_id = variant.variant_id
        variant_policy = variant.variant_policy or "explicit_gap_allowed"
        hypothesis_policy = variant.hypothesis_policy or "numeric_plus_explicit_gaps"
        law_policy = variant.law_policy or "verified_plus_gap"
        gap_policy = "explicit_gap_law"
        obligation_policy = variant.obligation_policy or "law_plus_algebra"
        repair_directives = list(variant.repair_directives)
    else:
        proof_steps = list(getattr(controlled_sketch, "proof_steps", []) or [])
        blocked_steps = list(getattr(controlled_sketch, "blocked_law_steps", []) or [])
        target_form_policy = "algebra_obligation"
        variant_id = "single_explicit_gap_allowed"
        variant_policy = "explicit_gap_allowed"
        hypothesis_policy = "numeric_plus_explicit_gaps"
        law_policy = "verified_plus_gap"
        gap_policy = "explicit_gap_law"
        obligation_policy = "law_plus_algebra"
        repair_directives = list(getattr(controlled_sketch, "repair_directives", []) or [])
    step_ids = [step.step_id for step in proof_steps if step.step_id]
    selected_instances = sorted(
        {
            str(step.source_model_instance)
            for step in proof_steps
            if step.source_model_instance
        }.union(
            {
                str(step.source_model_instance)
                for step in blocked_steps
                if step.source_model_instance
            }
        )
    )
    return [
        {
            "candidate_id": "c1",
            "theorem_name_hint": variant_policy or variant_id,
            "selected_model_instances": selected_instances,
            "selected_givens": [],
            "selected_target": {
                "variant_id": variant_id,
                "target_form_policy": target_form_policy,
            },
            "controlled_sketch_steps_used": step_ids,
            "unsupported_claims": [],
            "variant_id": variant_id,
            "variant_policy": variant_policy,
            "target_form_policy": target_form_policy,
            "hypothesis_policy": hypothesis_policy,
            "law_policy": law_policy,
            "gap_policy": gap_policy,
            "obligation_policy": obligation_policy,
            "repair_directives": repair_directives,
        }
    ]


def _deterministic_minimal_payload(
    controlled_sketch: ControlledSketch | None,
    model_ir: ModelIR | None,
) -> list[dict[str, Any]]:
    variant_payload = _variant_payloads(controlled_sketch)
    if variant_payload:
        return variant_payload
    selected_instances = sorted(
        {
            str(getattr(instance, "instance_id", "") or "").strip()
            for instance in (getattr(model_ir, "model_instances", []) or [])
            if str(getattr(instance, "instance_id", "") or "").strip()
        }
    )
    step_ids = [step.step_id for step in _all_sketch_steps(controlled_sketch) if step.step_id]
    return [
        {
            "candidate_id": "c1",
            "theorem_name_hint": "minimal_skeleton",
            "selected_model_instances": selected_instances,
            "selected_givens": [],
            "selected_target": {
                "target_form_policy": "algebra_obligation",
            },
            "controlled_sketch_steps_used": step_ids,
            "unsupported_claims": [],
            "variant_id": "deterministic_baseline",
            "variant_policy": "deterministic_baseline",
            "target_form_policy": "algebra_obligation",
            "hypothesis_policy": "minimal_numeric",
            "law_policy": "verified_plus_gap",
            "gap_policy": "explicit_gap_law",
            "obligation_policy": "law_plus_algebra",
            "repair_directives": [],
        }
    ]


def _theorem_shape(theorem_decl: str) -> str:
    shape = re.sub(r"theorem\s+[^\s]+", "theorem NAME", theorem_decl or "", count=1)
    return re.sub(r"\s+", " ", shape).strip()


def _gap_laws_from_steps_and_hypotheses(
    *,
    proof_obligations: list[ControlledSketchStep],
    hypothesis_provenance: list[HypothesisProvenance],
    controlled_sketch: ControlledSketch | None = None,
    model_interface_sources: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    if controlled_sketch is not None and controlled_sketch.schema_version >= 2:
        for step in controlled_sketch.blocked_law_steps:
            key = f"blocked:{step.source_model_instance}:{step.step_id}"
            if key in seen:
                continue
            seen.add(key)
            out.append(
                {
                    "step_id": step.step_id,
                    "source_model_instance": step.source_model_instance,
                    "planning_schema": step.planning_schema,
                    "claim": step.expected_claim,
                    "expected_claim": step.expected_claim,
                    "binding_status": step.binding_status,
                    "proof_fact_allowed": False,
                    "verified_decl": step.verified_decl,
                    "notes": step.reason or step.notes,
                }
            )
        proof_obligations = []
    for step in proof_obligations:
        if step.kind not in {"law_application", "constraint_application", "law_to_equation", "constraint_to_equation"}:
            continue
        if step.binding_status != "gap_schema_only" and step.proof_fact_allowed:
            continue
        key = f"step:{step.step_id}"
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "step_id": step.step_id,
                "source_model_instance": step.source_model_instance,
                "planning_schema": step.planning_schema,
                "claim": step.claim,
                "expected_claim": step.expected_claim,
                "binding_status": step.binding_status or "gap_schema_only",
                "proof_fact_allowed": False,
                "notes": step.notes,
            }
        )
    for hyp in hypothesis_provenance:
        if hyp.role != "explicit_gap_law":
            continue
        key = f"hyp:{hyp.name}:{hyp.lean}"
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "name": hyp.name,
                "lean": hyp.lean,
                "source_type": hyp.source_type,
                "source_id": hyp.source_id,
                "source_model_instance": (model_interface_sources or {}).get(str(hyp.source_id or "")),
                "proof_fact_allowed": False,
                "notes": hyp.notes or "No verified MechLib declaration bound; used as explicit modeling gap.",
            }
        )
    return out


def _build_skeleton_audit(
    *,
    sample_id: str,
    theorem_decl: str,
    problem_ir: dict[str, Any] | None,
    model_ir: ModelIR | None,
    controlled_sketch: ControlledSketch | None,
    evidence_bindings: list[EvidenceBinding],
    hypothesis_provenance: list[HypothesisProvenance],
    original_hypothesis_payloads: list[object],
    proof_obligations: list[ControlledSketchStep],
    verified_decls: list[str],
    allow_explicit_gap_laws: bool,
    upstream_sketch_audit: SketchAuditResult | None,
    untrusted_verified_decls: list[str],
    registered_model_predicates: list[dict[str, Any]] | None = None,
) -> SketchAuditResult:
    tags: list[str] = []
    bad_hypotheses: list[dict[str, Any]] = []
    bad_binders: list[dict[str, Any]] = []

    target_leakage = False
    candidate_answer_leakage = False
    raw_law_equation_in_hypotheses = False
    algebra_result_in_hypotheses = False
    schema_used_as_proof_fact = False
    unbound_verified_decl = False
    missing_provenance = False

    if upstream_sketch_audit is not None and not upstream_sketch_audit.audit_pass:
        tags.append("upstream_sketch_audit_failed")
    if untrusted_verified_decls:
        unbound_verified_decl = True
        tags.append("unbound_verified_decl")

    whitelist = _verified_decl_whitelist(evidence_bindings)
    registered_model_props = {
        normalize_lean_text(str(row.get("proposition") or "")).strip(): str(row.get("verified_decl") or "").strip()
        for row in (registered_model_predicates or [])
        if str(row.get("proposition") or "").strip() and str(row.get("verified_decl") or "").strip()
    }
    for decl in verified_decls:
        if decl not in whitelist:
            unbound_verified_decl = True
            if "unbound_verified_decl" not in tags:
                tags.append("unbound_verified_decl")

    law_claims = [
        ref
        for step in proof_obligations
        if step.kind in {"law_application", "constraint_application", "law_to_equation", "constraint_to_equation"}
        for ref in _step_result_refs(step)
    ]
    algebra_claims = [
        ref
        for step in proof_obligations
        if step.kind in {"algebra_elimination", "algebra_obligation"} and str(step.claim or "").strip()
        for ref in _step_result_refs(step)
    ]
    model_expected = _model_expected_claims(model_ir)
    target_refs = _target_texts(model_ir, problem_ir)
    candidate_answers = _candidate_answer_texts(problem_ir)
    binder_map = {name: proposition for name, proposition in _hypothesis_binders(theorem_decl)}

    for idx, hyp in enumerate(hypothesis_provenance):
        issues: list[str] = []
        if idx < len(original_hypothesis_payloads) and _provenance_missing_required(original_hypothesis_payloads[idx]):
            missing_provenance = True
            issues.append("missing_provenance")
            if "missing_provenance" not in tags:
                tags.append("missing_provenance")
        if hyp.role not in MINIMAL_HYPOTHESIS_ROLES:
            issues.append("invalid_hypothesis_role")
            if "invalid_hypothesis_role" not in tags:
                tags.append("invalid_hypothesis_role")
        if hyp.role in DERIVED_HYPOTHESIS_ROLES:
            issues.append("derived_role_in_hypotheses")
        if hyp.proof_fact_allowed and hyp.source_type in {"law_schema", "problem_schema", "concept", "alignment"}:
            schema_used_as_proof_fact = True
            issues.append("schema_used_as_proof_fact")
            if "schema_used_as_proof_fact" not in tags:
                tags.append("schema_used_as_proof_fact")
        if hyp.role == "explicit_gap_law":
            if not allow_explicit_gap_laws:
                raw_law_equation_in_hypotheses = True
                issues.append("explicit_gap_law_not_allowed")
                if "raw_law_equation_in_hypotheses" not in tags:
                    tags.append("raw_law_equation_in_hypotheses")
            if hyp.source_type != "gap" or hyp.proof_fact_allowed:
                issues.append("invalid_gap_law_provenance")
                if "invalid_gap_law_provenance" not in tags:
                    tags.append("invalid_gap_law_provenance")
        hyp_text = "\n".join([hyp.lean, binder_map.get(hyp.name, ""), hyp.name, hyp.notes or ""])
        checked_model_predicate = (
            hyp.role == "model_instance"
            and hyp.source_type == "verified_decl"
            and hyp.source_id in whitelist
            and normalize_lean_text(hyp.lean).strip() in registered_model_props
            and registered_model_props.get(normalize_lean_text(hyp.lean).strip()) == hyp.source_id
        )
        if (
            "MechLib." in hyp_text
            and not checked_model_predicate
            and not any(decl_name and decl_name in hyp_text for decl_name in whitelist)
        ):
            unbound_verified_decl = True
            issues.append("unbound_mechlib_reference_in_hypothesis")
            if "unbound_verified_decl" not in tags:
                tags.append("unbound_verified_decl")
        gap_allowed = hyp.role == "explicit_gap_law" and allow_explicit_gap_laws and hyp.source_type == "gap"
        active_hypothesis = hyp.allowed_in_hypotheses or gap_allowed
        modeling_hypothesis = _looks_like_audited_modeling_hypothesis(hyp, hyp.lean)
        if (
            active_hypothesis
            and any(_target_text_matches(ref, hyp_text) for ref in target_refs)
            and not modeling_hypothesis
        ):
            target_leakage = True
            issues.append("target_leakage")
            if "target_leakage" not in tags:
                tags.append("target_leakage")
        if active_hypothesis and any(_target_text_matches(ref, hyp_text) for ref in candidate_answers):
            candidate_answer_leakage = True
            issues.append("candidate_answer_leakage")
            if "candidate_answer_leakage" not in tags:
                tags.append("candidate_answer_leakage")
        law_match = any(_text_matches(ref, hyp_text) for ref in [*law_claims, *model_expected])
        if active_hypothesis and law_match and not gap_allowed and not checked_model_predicate and not modeling_hypothesis:
            raw_law_equation_in_hypotheses = True
            issues.append("law_application_claim_in_hypotheses")
            if "raw_law_equation_in_hypotheses" not in tags:
                tags.append("raw_law_equation_in_hypotheses")
        if active_hypothesis and any(_text_matches(ref, hyp_text) for ref in algebra_claims):
            algebra_result_in_hypotheses = True
            issues.append("algebra_result_in_hypotheses")
            if "algebra_result_in_hypotheses" not in tags:
                tags.append("algebra_result_in_hypotheses")
        if issues:
            bad_hypotheses.append(
                {
                    "name": hyp.name,
                    "role": hyp.role,
                    "source_type": hyp.source_type,
                    "issues": issues,
                }
            )

    provenance_by_name = {hyp.name: hyp for hyp in hypothesis_provenance}
    provenance_by_lean = {normalize_lean_text(hyp.lean): hyp for hyp in hypothesis_provenance if hyp.lean}
    for name, proposition in binder_map.items():
        hyp = provenance_by_name.get(name) or provenance_by_lean.get(normalize_lean_text(proposition))
        issues: list[str] = []
        if hyp is None:
            missing_provenance = True
            issues.append("missing_provenance")
            if "missing_provenance" not in tags:
                tags.append("missing_provenance")
        gap_allowed = (
            hyp is not None
            and hyp.role == "explicit_gap_law"
            and allow_explicit_gap_laws
            and hyp.source_type == "gap"
            and not hyp.proof_fact_allowed
        )
        norm_prop = normalize_lean_text(proposition).strip()
        checked_model_predicate = (
            hyp is not None
            and hyp.role == "model_instance"
            and hyp.source_type == "verified_decl"
            and hyp.source_id in whitelist
            and norm_prop in registered_model_props
            and registered_model_props.get(norm_prop) == hyp.source_id
        )
        if (
            "MechLib." in proposition
            and not checked_model_predicate
            and not any(decl_name and decl_name in proposition for decl_name in whitelist)
        ):
            unbound_verified_decl = True
            issues.append("unbound_mechlib_reference_in_binder")
            if "unbound_verified_decl" not in tags:
                tags.append("unbound_verified_decl")
        if not checked_model_predicate and not _is_allowed_lean_hypothesis(proposition):
            issues.append("invalid_binder_proposition")
            if "invalid_hypothesis_shape" not in tags:
                tags.append("invalid_hypothesis_shape")
        if hyp is not None and not hyp.allowed_in_hypotheses:
            issues.append("disallowed_hypothesis_in_binder")
            if "invalid_hypothesis_shape" not in tags:
                tags.append("invalid_hypothesis_shape")
        modeling_binder = hyp is not None and _looks_like_audited_modeling_hypothesis(hyp, proposition)
        if any(_target_text_matches(ref, proposition) for ref in target_refs) and not modeling_binder:
            target_leakage = True
            issues.append("target_leakage")
            if "target_leakage" not in tags:
                tags.append("target_leakage")
        if any(_target_text_matches(ref, proposition) for ref in candidate_answers):
            candidate_answer_leakage = True
            issues.append("candidate_answer_leakage")
            if "candidate_answer_leakage" not in tags:
                tags.append("candidate_answer_leakage")
        if (
            any(_text_matches(ref, proposition) for ref in [*law_claims, *model_expected])
            and not gap_allowed
            and not checked_model_predicate
            and not _looks_like_audited_modeling_hypothesis(hyp, proposition)
        ):
            raw_law_equation_in_hypotheses = True
            issues.append("law_application_claim_in_binder")
            if "raw_law_equation_in_hypotheses" not in tags:
                tags.append("raw_law_equation_in_hypotheses")
        if any(_text_matches(ref, proposition) for ref in algebra_claims):
            algebra_result_in_hypotheses = True
            issues.append("algebra_result_in_binder")
            if "algebra_result_in_hypotheses" not in tags:
                tags.append("algebra_result_in_hypotheses")
        if issues:
            bad_binders.append({"name": name, "proposition": proposition, "issues": issues})

    if missing_provenance and "missing_provenance" not in tags:
        tags.append("missing_provenance")
    details = {
        "bad_hypotheses": bad_hypotheses,
        "bad_binders": bad_binders,
        "verified_decl_whitelist": sorted(whitelist),
        "untrusted_verified_decls": untrusted_verified_decls,
        "upstream_sketch_audit": upstream_sketch_audit.to_dict() if upstream_sketch_audit else None,
    }
    return SketchAuditResult(
        sample_id=sample_id,
        audit_pass=not tags,
        failure_tags=tags,
        failure_summary="; ".join(tags) if tags else None,
        target_leakage=target_leakage,
        candidate_answer_leakage=candidate_answer_leakage,
        raw_law_equation_in_hypotheses=raw_law_equation_in_hypotheses,
        algebra_result_in_hypotheses=algebra_result_in_hypotheses,
        schema_used_as_proof_fact=schema_used_as_proof_fact,
        unbound_verified_decl=unbound_verified_decl,
        missing_provenance=missing_provenance,
        details=details,
    )


class ModuleB:
    def __init__(
        self,
        model_client,
        prompt_path: Path,
        revise_prompt_path: Path | None = None,
        minimal_prompt_path: Path | None = None,
        library_target: str = "mechlib",
        b_minimal_llm_enabled: bool = True,
        b_minimal_llm_on_retry: bool = True,
        compact_minimal_prompts: bool = True,
    ) -> None:
        self.model_client = model_client
        self.template = load_template(prompt_path, DEFAULT_PROMPT)
        self.minimal_template = (
            load_template(minimal_prompt_path, DEFAULT_MINIMAL_SKELETON_PROMPT)
            if minimal_prompt_path is not None
            else DEFAULT_MINIMAL_SKELETON_PROMPT
        )
        self.revise_template = (
            load_template(revise_prompt_path, DEFAULT_REVISE_PROMPT)
            if revise_prompt_path is not None
            else DEFAULT_REVISE_PROMPT
        )
        self.library_target = _normalize_library_target(library_target)
        self.b_minimal_llm_enabled = bool(b_minimal_llm_enabled)
        self.b_minimal_llm_on_retry = bool(b_minimal_llm_on_retry)
        self.compact_minimal_prompts = bool(compact_minimal_prompts)

    def run(
        self,
        grounding: GroundingResult,
        mechlib_context: str = "(none)",
        revision_feedback: str = "(none)",
        round_index: int = 0,
        previous_candidates: list[StatementCandidate] | None = None,
        generation_mode: str = "legacy_candidate",
        problem_ir: dict[str, Any] | None = None,
        model_ir: ModelIR | None = None,
        controlled_sketch: ControlledSketch | None = None,
        evidence_bindings: list[EvidenceBinding] | None = None,
        structured_mechlib_context: object | None = None,
        sketch_audit_result: SketchAuditResult | None = None,
        allow_explicit_gap_laws: bool = True,
    ) -> list[StatementCandidate]:
        if generation_mode == "minimal_skeleton":
            return self._run_minimal_skeleton(
                grounding=grounding,
                problem_ir=problem_ir,
                model_ir=model_ir,
                controlled_sketch=controlled_sketch,
                evidence_bindings=evidence_bindings or [],
                structured_mechlib_context=structured_mechlib_context,
                sketch_audit_result=sketch_audit_result,
                revision_feedback=revision_feedback,
                round_index=round_index,
                previous_candidates=previous_candidates,
                allow_explicit_gap_laws=allow_explicit_gap_laws,
            )

        safe_ir = sanitize_problem_ir_for_llm(grounding.problem_ir or {})
        use_revision_prompt = round_index > 0 and revision_feedback.strip() != "(none)"
        template = self.revise_template if use_revision_prompt else self.template
        previous_candidates_payload = [
            {
                "candidate_id": c.candidate_id,
                "lean_header": c.lean_header,
                "theorem_decl": c.theorem_decl,
                "assumptions": c.assumptions,
                "plan": c.plan,
                "supporting_facts": c.supporting_facts,
                "fact_sources": c.fact_sources,
                "library_symbols_used": c.library_symbols_used,
                "grounding_explanation": c.grounding_explanation,
                "unsupported_claims": c.unsupported_claims,
                "verified_decl_refs": c.verified_decl_refs,
                "schema_refs": c.schema_refs,
                "alias_refs": c.alias_refs,
                "grounding_status": c.grounding_status,
                "gap_schema_only": c.gap_schema_only,
                "round_index": c.round_index,
            }
            for c in (previous_candidates or [])
        ]
        prompt = render_template(
            template,
            {
                "problem_ir_json": json.dumps(safe_ir, ensure_ascii=False, indent=2),
                "mechlib_context": mechlib_context or "(none)",
                "library_target": self.library_target,
                "required_header_template": _required_header(
                    "mechlib" if self.library_target in {"mechlib", "auto"} else "physlean"
                ),
                "previous_candidates_json": json.dumps(previous_candidates_payload, ensure_ascii=False, indent=2),
                "revision_feedback": revision_feedback or "(none)",
            },
        )

        raw = ""
        parse_ok = False
        error: str | None = None
        try:
            resp = self.model_client.generate_text(prompt)
            raw = resp.text
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"

        payload: list[dict[str, object]] = []
        if raw:
            try:
                parsed = parse_json_model(raw, StatementCandidatesPayload)
                for idx, item in enumerate(parsed.candidates):
                    cand = item.model_dump()
                    cand.setdefault("candidate_id", f"c{idx + 1}")
                    payload.append(cand)
                parse_ok = True
            except ResponseParseError:
                error = error or "statement_generation_parse_failed"
        else:
            error = error or "statement_generation_parse_failed"

        payload = payload[:4]
        prepared: list[dict[str, object]] = []

        for item in payload:
            cid = str(item.get("candidate_id") or "c1")
            assumptions = item.get("assumptions")
            initial_target = _infer_library_target(
                str(item.get("lean_header") or ""),
                str(item.get("theorem_decl") or ""),
                self.library_target,
            )
            target = initial_target if self.library_target == "auto" else self.library_target
            if target == "auto":
                target = "mechlib"
            decl = _normalize_theorem_decl(
                grounding.sample_id,
                cid,
                item.get("theorem_decl"),
                grounding.problem_ir,
                mechlib_context=mechlib_context,
                library_target=target,
            )
            inferred_target = _infer_library_target(
                str(item.get("lean_header") or ""),
                decl,
                self.library_target,
            )
            target = inferred_target if self.library_target == "auto" else self.library_target
            if target == "auto":
                target = "mechlib"
            prepared_item = {
                "candidate_id": cid,
                "lean_header": _normalize_header(str(item.get("lean_header") or ""), target),
                "theorem_decl": decl,
                "assumptions": [str(x) for x in assumptions] if isinstance(assumptions, list) else [],
                "plan": str(item.get("plan") or "").strip() or None,
                "supporting_facts": _normalize_text_list(item.get("supporting_facts")),
                "fact_sources": _normalize_text_list(item.get("fact_sources")),
                "library_symbols_used": _normalize_library_symbol_list(item.get("library_symbols_used")),
                "grounding_explanation": normalize_lean_text(str(item.get("grounding_explanation") or "").strip())
                or None,
                "target": target,
            }
            prepared_item["unsupported_claims"] = _infer_unsupported_claims(
                theorem_decl=str(decl or ""),
                fact_sources=list(prepared_item["fact_sources"]),
                library_symbols_used=list(prepared_item["library_symbols_used"]),
                mechlib_context=mechlib_context,
                library_target=target,
            )
            (
                prepared_item["verified_decl_refs"],
                prepared_item["schema_refs"],
                prepared_item["alias_refs"],
                prepared_item["grounding_status"],
                prepared_item["gap_schema_only"],
            ) = _candidate_grounding_refs(
                theorem_decl=str(decl or ""),
                fact_sources=list(prepared_item["fact_sources"]),
                library_symbols_used=list(prepared_item["library_symbols_used"]),
                mechlib_context=mechlib_context,
            )
            if prepared_item["gap_schema_only"] and not prepared_item["verified_decl_refs"]:
                gap_tag = "gap_schema_only:no_verified_decl_binding"
                unsupported_claims = list(prepared_item["unsupported_claims"])
                if gap_tag not in unsupported_claims:
                    unsupported_claims.append(gap_tag)
                prepared_item["unsupported_claims"] = unsupported_claims
            prepared.append(prepared_item)

        out: list[StatementCandidate] = []
        for item in prepared:
            cid = str(item["candidate_id"])
            decl = item["theorem_decl"]
            if decl is None:
                continue
            header = str(item["lean_header"])
            assumptions = list(item["assumptions"]) if isinstance(item["assumptions"], list) else []
            plan = item["plan"] if isinstance(item["plan"], str) else None

            out.append(
                StatementCandidate(
                    sample_id=grounding.sample_id,
                    candidate_id=cid,
                    lean_header=header,
                    theorem_decl=decl,
                    assumptions=assumptions,
                    plan=plan,
                    supporting_facts=list(item["supporting_facts"]) if isinstance(item["supporting_facts"], list) else [],
                    fact_sources=list(item["fact_sources"]) if isinstance(item["fact_sources"], list) else [],
                    library_symbols_used=(
                        list(item["library_symbols_used"]) if isinstance(item["library_symbols_used"], list) else []
                    ),
                    grounding_explanation=(
                        str(item["grounding_explanation"]) if item.get("grounding_explanation") else None
                    ),
                    unsupported_claims=(
                        list(item["unsupported_claims"]) if isinstance(item["unsupported_claims"], list) else []
                    ),
                    verified_decl_refs=(
                        list(item["verified_decl_refs"]) if isinstance(item["verified_decl_refs"], list) else []
                    ),
                    schema_refs=(list(item["schema_refs"]) if isinstance(item["schema_refs"], list) else []),
                    alias_refs=(list(item["alias_refs"]) if isinstance(item["alias_refs"], list) else []),
                    grounding_status=str(item["grounding_status"]) if item.get("grounding_status") else None,
                    gap_schema_only=bool(item.get("gap_schema_only")),
                    parse_ok=parse_ok,
                    raw_response=raw,
                    error=error,
                    round_index=round_index,
                    source_round_index=(round_index - 1) if round_index > 0 else None,
                )
            )
        seen_shapes: dict[str, str] = {}
        for candidate in out:
            shape = _theorem_shape(candidate.theorem_decl)
            first = seen_shapes.get(shape)
            if first is None:
                seen_shapes[shape] = candidate.candidate_id
                continue
            tag = f"duplicate_skeleton_shape:{first}"
            if tag not in candidate.unsupported_claims:
                candidate.unsupported_claims.append(tag)
        return out

    def _run_minimal_skeleton(
        self,
        *,
        grounding: GroundingResult,
        problem_ir: dict[str, Any] | None,
        model_ir: ModelIR | None,
        controlled_sketch: ControlledSketch | None,
        evidence_bindings: list[EvidenceBinding],
        structured_mechlib_context: object | None,
        sketch_audit_result: SketchAuditResult | None,
        revision_feedback: str,
        round_index: int,
        previous_candidates: list[StatementCandidate] | None,
        allow_explicit_gap_laws: bool,
    ) -> list[StatementCandidate]:
        effective_problem_ir = problem_ir or grounding.problem_ir or {}
        raw = ""
        error: str | None = None
        use_minimal_llm = self.b_minimal_llm_enabled or (
            self.b_minimal_llm_on_retry
            and round_index > 0
            and str(revision_feedback or "").strip() not in {"", "(none)"}
        )
        payload: list[dict[str, Any]] = []
        llm_candidate_count: int | None = None
        if use_minimal_llm:
            previous_candidates_payload = [
                compact_candidate_for_feedback(c)
                if self.compact_minimal_prompts
                else {
                    "candidate_id": c.candidate_id,
                    "lean_header": c.lean_header,
                    "theorem_decl": c.theorem_decl,
                    "assumptions": c.assumptions,
                    "unsupported_claims": c.unsupported_claims,
                    "round_index": c.round_index,
                }
                for c in (previous_candidates or [])
            ]
            context_payload = (
                compact_structured_context(structured_mechlib_context)
                if self.compact_minimal_prompts
                else _dataclass_payload(structured_mechlib_context)
            )
            prompt = render_template(
                self.minimal_template,
                {
                    "problem_ir_json": json.dumps(
                        compact_problem_ir(sanitize_problem_ir_for_llm(effective_problem_ir))
                        if self.compact_minimal_prompts
                        else sanitize_problem_ir_for_llm(effective_problem_ir),
                        ensure_ascii=False,
                        indent=2,
                    ),
                    "model_ir_json": json.dumps(
                        compact_model_ir(model_ir) if self.compact_minimal_prompts else _dataclass_payload(model_ir),
                        ensure_ascii=False,
                        indent=2,
                    ),
                    "controlled_sketch_json": json.dumps(
                        compact_controlled_sketch(controlled_sketch)
                        if self.compact_minimal_prompts
                        else _dataclass_payload(controlled_sketch),
                        ensure_ascii=False,
                        indent=2,
                    ),
                    "evidence_bindings_json": json.dumps(
                        compact_evidence_bindings(list(evidence_bindings))
                        if self.compact_minimal_prompts
                        else _list_payload(list(evidence_bindings)),
                        ensure_ascii=False,
                        indent=2,
                    ),
                    "structured_context_json": json.dumps(context_payload, ensure_ascii=False, indent=2),
                    "sketch_audit_json": json.dumps(
                        compact_sketch_audit(sketch_audit_result)
                        if self.compact_minimal_prompts
                        else _dataclass_payload(sketch_audit_result),
                        ensure_ascii=False,
                        indent=2,
                    ),
                    "revision_feedback": revision_feedback or "(none)",
                    "previous_candidates_json": json.dumps(previous_candidates_payload, ensure_ascii=False, indent=2),
                },
            )

            try:
                raw = self.model_client.generate_text(prompt).text
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"

            if raw:
                try:
                    parsed = parse_json_model(raw, TheoremSkeletonCandidatesPayload)
                    payload = [item.model_dump() for item in parsed.candidates]
                except ResponseParseError as exc:
                    error = f"minimal_skeleton_selection_parse_failed:{exc}"
        llm_candidate_count = len(payload) if use_minimal_llm else None
        variant_payload = _variant_payloads(controlled_sketch)
        if variant_payload:
            merged_payload: list[dict[str, Any]] = []
            for idx, variant_item in enumerate(variant_payload, start=0):
                item = dict(variant_item)
                if idx < len(payload):
                    llm_item = payload[idx]
                    for key in ("plan", "supporting_facts", "fact_sources", "library_symbols_used", "grounding_explanation"):
                        if llm_item.get(key):
                            item[key] = llm_item.get(key)
                    item["unsupported_claims"] = [
                        *_normalize_text_list(llm_item.get("unsupported_claims")),
                        *_normalize_text_list(item.get("unsupported_claims")),
                    ]
                    ignored = normalize_lean_text(str(llm_item.get("theorem_decl") or "")).strip()
                    if ignored:
                        item["theorem_decl"] = ignored
                merged_payload.append(item)
            payload = merged_payload
        elif not payload:
            payload = _deterministic_minimal_payload(controlled_sketch, model_ir)
        candidate_count = len(payload)
        payload = payload[:1]
        candidate_count_below_requested = llm_candidate_count is not None and llm_candidate_count < 1
        candidate_count_above_requested = llm_candidate_count is not None and llm_candidate_count > 1
        variant_by_id = {
            variant.variant_id: variant
            for variant in (getattr(controlled_sketch, "sketch_variants", []) or [])
            if isinstance(variant, SketchVariant)
        }
        whitelist = _verified_decl_whitelist(evidence_bindings)
        out: list[StatementCandidate] = []
        for idx, item in enumerate(payload, start=1):
            cid = str(item.get("candidate_id") or f"c{idx}")
            variant_id = str(item.get("variant_id") or "").strip() or None
            variant = variant_by_id.get(variant_id or "")
            effective_sketch = _sketch_for_variant(controlled_sketch, variant)
            gap_policy = str(item.get("gap_policy") or "").strip()
            include_explicit_gaps = gap_policy == "explicit_gap_law" or (variant is None and allow_explicit_gap_laws)
            ignored_llm_theorem_decl = normalize_lean_text(str(item.get("theorem_decl") or "")).strip() or None
            quantity_infos = _quantity_infos(model_ir, effective_sketch)
            selected_givens = _selected_names(item.get("selected_givens"))
            selected_model_instances = _selected_names(item.get("selected_model_instances"))
            given_hypotheses, hypothesis_typed_rows, excluded_hypotheses = _safe_given_binders(
                model_ir=model_ir,
                quantity_infos=quantity_infos,
                selected_givens=selected_givens,
            )
            model_predicates, blocked_model_predicates = _model_predicate_bindings(
                model_ir=model_ir,
                evidence_bindings=evidence_bindings,
                quantity_infos=quantity_infos,
                selected_model_instances=selected_model_instances,
            )
            expected_claim_instantiations = _expected_claim_instantiations_for_blocked_predicates(
                model_ir=model_ir,
                blocked_model_predicates=blocked_model_predicates,
                selected_model_instances=selected_model_instances,
            )
            interface_hypotheses, interface_typed_rows, excluded_interface_hypotheses = _model_interface_hypotheses(
                model_ir=model_ir,
                controlled_sketch=effective_sketch,
                quantity_infos=quantity_infos,
                selected_model_instances=selected_model_instances,
                extra_instantiations=expected_claim_instantiations,
                include_explicit_gaps=include_explicit_gaps,
            )
            excluded_hypotheses.extend(excluded_interface_hypotheses)
            target_formula, target_block_reason = _target_formula_with_policy(
                model_ir=model_ir,
                controlled_sketch=effective_sketch,
                quantity_infos=quantity_infos,
                target_form_policy=str(item.get("target_form_policy") or "algebra_obligation").strip()
                or "algebra_obligation",
                selected_target=item.get("selected_target"),
            )
            decl, quantity_typed_rows = _render_theorem_decl(
                sample_id=grounding.sample_id,
                candidate_id=cid,
                theorem_name_hint=str(item.get("theorem_name_hint") or "").strip() or None,
                quantity_infos=quantity_infos,
                given_hypotheses=[*given_hypotheses, *interface_hypotheses],
                model_predicates=model_predicates,
                target_formula=target_formula,
            )
            hypothesis_provenance = [*given_hypotheses, *interface_hypotheses]
            for row in model_predicates:
                hypothesis_provenance.append(
                    HypothesisProvenance(
                        name=str(row["name"]),
                        lean=str(row["proposition"]),
                        role="model_instance",
                        source_type="verified_decl",
                        source_id=str(row["verified_decl"]),
                        allowed_in_hypotheses=True,
                        notes=f"Checked MechLib model predicate for {row['model_instance_id']}.",
                        proof_fact_allowed=True,
                    )
                )
            used_ids = _normalize_text_list(item.get("controlled_sketch_steps_used"))
            proof_obligations = _canonical_proof_obligations(
                controlled_sketch=effective_sketch,
                requested_ids=used_ids,
            )
            if not used_ids:
                used_ids = [step.step_id for step in proof_obligations if step.step_id]

            requested_verified = [str(row["verified_decl"]) for row in model_predicates]
            untrusted_verified = [decl_name for decl_name in requested_verified if decl_name not in whitelist]
            verified_from_steps = {
                str(step.verified_decl).strip()
                for step in proof_obligations
                if step.verified_decl and step.proof_fact_allowed and step.verified_decl in whitelist
            }
            verified_decls = sorted(verified_from_steps.union({name for name in requested_verified if name in whitelist}))

            selected_laws = _normalize_text_list(item.get("selected_laws"))
            for step in proof_obligations:
                if step.planning_schema and step.planning_schema not in selected_laws:
                    selected_laws.append(step.planning_schema)

            model_interface_rows = [
                item
                for item in [
                    *_model_interface_instantiations_from_model_ir(model_ir),
                    *_model_interface_instantiations_from_sketch(effective_sketch),
                    *(expected_claim_instantiations if include_explicit_gaps else []),
                ]
                if not selected_model_instances
                or not item.source_model_instance
                or item.source_model_instance in selected_model_instances
            ]
            model_interface_sources = {
                item.instantiation_id: str(item.source_model_instance)
                for item in model_interface_rows
                if item.instantiation_id and item.source_model_instance
            }
            gap_laws = _gap_laws_from_steps_and_hypotheses(
                proof_obligations=proof_obligations,
                hypothesis_provenance=hypothesis_provenance,
                controlled_sketch=effective_sketch,
                model_interface_sources=model_interface_sources,
            )
            explicit_model_gap_instances = {
                str(hyp.source_id or "").strip()
                for hyp in interface_hypotheses
                if hyp.role == "explicit_gap_law" and hyp.source_id
            }
            explicit_model_gap_source_instances = {
                str(row.get("source", {}).get("source_model_instance") or "").strip()
                for row in interface_typed_rows
                if isinstance(row.get("source"), dict)
            }
            explicit_model_gap_source_instances.discard("")
            seen_gap_keys = {str(row.get("source_model_instance") or row.get("step_id") or "") for row in gap_laws}
            for blocked in blocked_model_predicates:
                key = str(blocked.get("source_model_instance") or blocked.get("step_id") or "")
                if key and key in seen_gap_keys:
                    continue
                seen_gap_keys.add(key)
                gap_laws.append(blocked)
            skeleton_audit = _build_skeleton_audit(
                sample_id=grounding.sample_id,
                theorem_decl=decl,
                problem_ir=effective_problem_ir,
                model_ir=model_ir,
                controlled_sketch=effective_sketch,
                evidence_bindings=evidence_bindings,
                hypothesis_provenance=hypothesis_provenance,
                original_hypothesis_payloads=hypothesis_provenance,
                proof_obligations=proof_obligations,
                verified_decls=verified_decls,
                allow_explicit_gap_laws=allow_explicit_gap_laws,
                upstream_sketch_audit=sketch_audit_result,
                untrusted_verified_decls=untrusted_verified,
                registered_model_predicates=model_predicates,
            )

            unsupported_claims = _normalize_text_list(item.get("unsupported_claims"))
            for row in quantity_typed_rows:
                status = str(row.get("type_status") or "ok")
                if status == "ok":
                    continue
                source_name = str(row.get("source_name") or row.get("name") or "").strip()
                requested_type = str(row.get("requested_lean_type") or "").strip()
                if status == "unsupported_si_type":
                    tag = f"unsupported_si_type:{source_name}:{requested_type or row.get('lean_type')}"
                elif status == "low_confidence_quantity_type":
                    tag = f"quantity_type_low_confidence:{source_name}"
                else:
                    tag = f"quantity_type_unresolved:{source_name}"
                if tag not in unsupported_claims:
                    unsupported_claims.append(tag)
            if candidate_count_below_requested and "candidate_count_below_requested" not in unsupported_claims:
                unsupported_claims.append("candidate_count_below_requested")
            if candidate_count_above_requested and "candidate_count_above_requested_truncated" not in unsupported_claims:
                unsupported_claims.append("candidate_count_above_requested_truncated")
            if ignored_llm_theorem_decl:
                unsupported_claims.append("ignored_llm_theorem_decl")
            for tag in skeleton_audit.failure_tags:
                audit_tag = f"skeleton_audit:{tag}"
                if audit_tag not in unsupported_claims:
                    unsupported_claims.append(audit_tag)
            for decl_name in untrusted_verified:
                tag = f"unbound_verified_decl:{decl_name}"
                if tag not in unsupported_claims:
                    unsupported_claims.append(tag)
            if gap_laws and "gap_schema_only:no_verified_decl_binding" not in unsupported_claims:
                unsupported_claims.append("gap_schema_only:no_verified_decl_binding")
            generation_blocked_reason: str | None = None
            if target_block_reason:
                generation_blocked_reason = target_block_reason
            has_verified_proof_obligations = any(
                step.verified_decl and step.proof_fact_allowed and step.verified_decl in whitelist
                for step in proof_obligations
            )
            uncovered_blocked_predicates = [
                row
                for row in blocked_model_predicates
                if str(row.get("source_model_instance") or "").strip() not in explicit_model_gap_source_instances
            ]
            if (
                blocked_model_predicates
                and not model_predicates
                and not interface_hypotheses
                and not has_verified_proof_obligations
            ):
                generation_blocked_reason = "blocked_by_evidence_gap"
            elif uncovered_blocked_predicates and not allow_explicit_gap_laws and not has_verified_proof_obligations:
                generation_blocked_reason = "blocked_by_evidence_gap"
            if gap_laws and not allow_explicit_gap_laws:
                generation_blocked_reason = generation_blocked_reason or "blocked_by_evidence_gap"
            if sketch_audit_result is not None and not sketch_audit_result.audit_pass:
                generation_blocked_reason = generation_blocked_reason or "upstream_sketch_audit_failed"
            if generation_blocked_reason:
                tag = f"generation_blocked:{generation_blocked_reason}"
                if tag not in unsupported_claims:
                    unsupported_claims.append(tag)

            law_obligations = [
                step
                for step in proof_obligations
                if step.kind in {"law_application", "constraint_application", "law_to_equation", "constraint_to_equation"}
            ]
            fully_mechlib_verified = (
                skeleton_audit.audit_pass
                and not gap_laws
                and bool(model_predicates)
                and all(str(row["verified_decl"]) in whitelist for row in model_predicates)
            )
            if generation_blocked_reason == "blocked_by_evidence_gap":
                grounding_status = "blocked_by_evidence_gap"
            elif generation_blocked_reason:
                grounding_status = generation_blocked_reason
            elif not skeleton_audit.audit_pass:
                grounding_status = "skeleton_audit_failed"
            elif fully_mechlib_verified:
                grounding_status = "fully_mechlib_verified"
            elif interface_hypotheses:
                grounding_status = "partial_mechlib_with_model_gaps"
            elif gap_laws:
                grounding_status = "gap_schema_only"
            elif verified_decls:
                grounding_status = "verified_decl_bound"
            else:
                grounding_status = "ungrounded"

            verified_decl_refs = [
                binding.to_dict()
                for binding in evidence_bindings
                if binding.verified_decl and binding.verified_decl in set(verified_decls)
            ]
            assumptions = [
                prop
                for prop in [
                    *[hyp.lean for hyp in given_hypotheses],
                    *[hyp.lean for hyp in interface_hypotheses],
                    *[str(row["proposition"]) for row in model_predicates],
                ]
                if prop
            ]
            header = _minimal_header(evidence_bindings=evidence_bindings, verified_decls=verified_decls)
            parse_ok = bool(skeleton_audit.audit_pass and generation_blocked_reason is None)
            out.append(
                TheoremSkeletonCandidate(
                    sample_id=grounding.sample_id,
                    candidate_id=cid,
                    lean_header=header,
                    theorem_decl=decl,
                    assumptions=assumptions,
                    plan=str(item.get("plan") or "").strip() or None,
                    supporting_facts=_normalize_text_list(item.get("supporting_facts")),
                    fact_sources=_normalize_text_list(item.get("fact_sources")),
                    library_symbols_used=_normalize_library_symbol_list(item.get("library_symbols_used")),
                    grounding_explanation=normalize_lean_text(
                        str(item.get("grounding_explanation") or "").strip()
                    )
                    or None,
                    unsupported_claims=unsupported_claims,
                    verified_decl_refs=verified_decl_refs,
                    schema_refs=[],
                    alias_refs=[],
                    grounding_status=grounding_status,
                    gap_schema_only=bool(gap_laws),
                    parse_ok=parse_ok,
                    raw_response=raw,
                    error=error,
                    round_index=round_index,
                    source_round_index=(round_index - 1) if round_index > 0 else None,
                    hypothesis_provenance=hypothesis_provenance,
                    model_ir_digest=_model_ir_digest(model_ir),
                    evidence_bindings=list(evidence_bindings),
                    controlled_sketch=effective_sketch,
                    proof_obligations=proof_obligations,
                    controlled_sketch_steps_used=used_ids,
                    selected_laws=selected_laws,
                    verified_decls=verified_decls,
                    gap_laws=gap_laws,
                    fully_mechlib_verified=fully_mechlib_verified,
                    skeleton_audit=skeleton_audit,
                    variant_id=variant_id,
                    variant_policy=str(item.get("variant_policy") or "").strip() or None,
                    target_form_policy=str(item.get("target_form_policy") or "").strip() or None,
                    hypothesis_policy=str(item.get("hypothesis_policy") or "").strip() or None,
                    law_policy=str(item.get("law_policy") or "").strip() or None,
                    gap_policy=str(item.get("gap_policy") or "").strip() or None,
                    obligation_policy=str(item.get("obligation_policy") or "").strip() or None,
                    repair_directives=_normalize_text_list(item.get("repair_directives")),
                    typed_binders=[*quantity_typed_rows, *hypothesis_typed_rows, *interface_typed_rows],
                    model_predicate_bindings=model_predicates,
                    model_interface_instantiations=[
                        *model_interface_rows
                    ],
                    explicit_model_gaps=[
                        row for row in gap_laws if str(row.get("source_id") or "") in explicit_model_gap_instances
                    ],
                    target_spec=(
                        _dataclass_payload(getattr(model_ir, "canonical_target", None))
                        if model_ir is not None and getattr(model_ir, "canonical_target", None) is not None
                        else {}
                    ),
                    excluded_hypotheses=excluded_hypotheses,
                    generation_blocked_reason=generation_blocked_reason,
                    ignored_llm_theorem_decl=ignored_llm_theorem_decl,
                )
            )
        return out
