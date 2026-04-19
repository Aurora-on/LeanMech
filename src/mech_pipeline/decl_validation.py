from __future__ import annotations

import re

from mech_pipeline.utils import normalize_lean_text, truncate

_DECIMAL_LITERAL_PATTERN = re.compile(r"(?<![A-Za-z0-9_])-?\d+\.\d+(?![A-Za-z0-9_])")
_ALLOWED_UNICODE = {"≠", "≤", "≥", "→", "∀", "∧", "∨", "ℝ", "ℕ", "ℤ"}
_MOJIBAKE_REPLACEMENTS = {
    "鈭€": "∀",
    "鈮?": "≠",
    "鈥?": "*",
}
_GREEK_IDENTIFIER_REPLACEMENTS = {
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
}
_TACTIC_RESIDUE_RE = re.compile(r":=\s*(?:by\b|simp\b|rw\b|ring\b|linarith\b|aesop\b|nlinarith\b|norm_num\b)")
_LET_BY_RESIDUE_RE = re.compile(r"\blet\b[\s\S]{0,400}:=\s*by\b", re.IGNORECASE)


def declaration_only(text: str) -> str:
    out = str(text or "").strip()
    if out.startswith("```"):
        out = out.replace("```lean", "").replace("```", "").strip()
    if ":= by" in out:
        out = out.split(":= by", 1)[0].rstrip()
    elif ":=" in out:
        out = out.split(":=", 1)[0].rstrip()
    if out.endswith(" by"):
        out = out[:-3].rstrip()
    return out


def _normalize_common_mojibake(text: str) -> str:
    out = text
    for src, dst in _MOJIBAKE_REPLACEMENTS.items():
        out = out.replace(src, dst)
    return out


def _normalize_unicode_identifiers(text: str) -> str:
    out = text
    for src, dst in _GREEK_IDENTIFIER_REPLACEMENTS.items():
        out = out.replace(src, dst)
    return out


def _normalize_numeric_literals(text: str) -> str:
    def _replace(match: re.Match[str]) -> str:
        literal = match.group(0)
        if "." not in literal:
            return literal
        negative = literal.startswith("-")
        body = literal[1:] if negative else literal
        whole, frac = body.split(".", 1)
        if not frac:
            return literal
        denominator = 10 ** len(frac)
        numerator = int(whole or "0") * denominator + int(frac)
        rendered = f"(({numerator} : Real) / {denominator})"
        return f"(-{rendered})" if negative else rendered

    return _DECIMAL_LITERAL_PATTERN.sub(_replace, text)


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
        if ch in _ALLOWED_UNICODE:
            continue
        return True
    return False


def _is_trivial_assumption_replay(text: str) -> bool:
    stripped = declaration_only(text)
    if ":" not in stripped:
        return False
    goal = " ".join(stripped.rsplit(":", 1)[1].strip().split())
    ident_eq = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_']*)\s*=\s*([A-Za-z_][A-Za-z0-9_']*)", goal)
    return bool(ident_eq and ident_eq.group(1) == ident_eq.group(2))


def _is_meaningful_decl(text: str) -> bool:
    stripped = declaration_only(text)
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
    if _is_trivial_assumption_replay(stripped):
        return False
    return True


def prevalidate_theorem_decl(theorem_decl: str) -> dict[str, str] | None:
    raw = normalize_lean_text(str(theorem_decl or ""))
    if _TACTIC_RESIDUE_RE.search(raw):
        return {
            "validation_reason": "embedded_proof_or_tactic_residue",
            "validation_excerpt": truncate(raw, 240),
        }
    if _LET_BY_RESIDUE_RE.search(raw):
        return {
            "validation_reason": "invalid_let_by_residue",
            "validation_excerpt": truncate(raw, 240),
        }

    decl = declaration_only(raw)
    decl = _normalize_common_mojibake(decl)
    decl = _normalize_unicode_identifiers(decl)
    decl = _normalize_numeric_literals(decl)
    decl = normalize_lean_text(decl)

    if not re.match(r"^\s*(theorem|lemma)\s+", decl) or ":" not in decl:
        return {
            "validation_reason": "invalid_declaration_shape",
            "validation_excerpt": truncate(decl, 240),
        }
    if not _has_balanced_delimiters(decl):
        return {
            "validation_reason": "unbalanced_delimiters",
            "validation_excerpt": truncate(decl, 240),
        }
    if _has_disallowed_non_ascii(decl):
        return {
            "validation_reason": "disallowed_non_ascii",
            "validation_excerpt": truncate(decl, 240),
        }
    if not _is_meaningful_decl(decl):
        return {
            "validation_reason": "trivial_or_non_meaningful_declaration",
            "validation_excerpt": truncate(decl, 240),
        }
    return None
