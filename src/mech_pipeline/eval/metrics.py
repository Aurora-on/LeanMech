from __future__ import annotations

from collections import Counter
from typing import Any

from mech_pipeline.types import CompileCheckResult, GroundingResult, ProofCheckResult, SampleRunSummary, SemanticRankResult


def _safe_rate(num: int, den: int) -> float:
    if den <= 0:
        return 0.0
    return round(num / den, 6)


def _is_mechlib_header(value: object) -> bool:
    if not isinstance(value, str):
        return False
    return "import MechLib" in value


def _row_sample_id(row: object) -> str:
    return str(getattr(row, "sample_id", "")) if not isinstance(row, dict) else str(row.get("sample_id", ""))


def _row_round_index(row: object) -> int:
    value = getattr(row, "round_index", 0) if not isinstance(row, dict) else row.get("round_index", 0)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return 0
    return 0


def _row_bool(row: object, key: str) -> bool:
    value = getattr(row, key, False) if not isinstance(row, dict) else row.get(key, False)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return False


def _row_string_list(row: dict[str, Any], key: str) -> list[str]:
    value = row.get(key)
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            out.append(text)
    return out


def _retrieval_refs_by_sample(retrieval_rows: list[dict[str, Any]]) -> dict[str, set[str]]:
    refs: dict[str, set[str]] = {}
    for row in retrieval_rows:
        sid = str(row.get("sample_id") or "")
        bucket = refs.setdefault(sid, set())
        for item in row.get("law_matched_items", []) if isinstance(row.get("law_matched_items"), list) else []:
            if not isinstance(item, dict):
                continue
            for key in ("theorem_name", "symbol_name"):
                text = str(item.get(key) or "").strip()
                if text:
                    bucket.add(text)
    return refs


def _statement_uses_mechlib(row: dict[str, Any], refs: set[str]) -> bool:
    symbols = _row_string_list(row, "library_symbols_used")
    return bool(symbols and any(sym in refs for sym in symbols))


def _proof_uses_mechlib(row: dict[str, Any], refs: set[str]) -> bool:
    if not refs:
        return False
    theorems = _row_string_list(row, "theorems_to_apply")
    if theorems and any(name in refs for name in theorems):
        return True
    proof_body = str(row.get("proof_body") or "")
    proof_plan = str(row.get("proof_plan") or "")
    text = f"{proof_body}\n{proof_plan}"
    return any(ref and ref in text for ref in refs)


def build_metrics(
    summaries: list[SampleRunSummary],
    statement_rows: list[dict[str, Any]],
    grounding_rows: list[GroundingResult],
    compile_rows: list[CompileCheckResult],
    semantic_rows: list[SemanticRankResult],
    proof_rows: list[ProofCheckResult],
    retrieval_rows: list[dict[str, Any]] | None = None,
    proof_attempt_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    total = len(summaries)
    final_round_map = {s.sample_id: int(s.final_round_index) for s in summaries}
    final_statement_rows = [
        row for row in statement_rows if final_round_map.get(_row_sample_id(row), 0) == _row_round_index(row)
    ]
    final_compile_rows = [
        row for row in compile_rows if final_round_map.get(_row_sample_id(row), 0) == _row_round_index(row)
    ]
    final_semantic_rows = [
        row for row in semantic_rows if final_round_map.get(_row_sample_id(row), 0) == _row_round_index(row)
    ]
    final_proof_rows = [
        row for row in proof_rows if final_round_map.get(_row_sample_id(row), 0) == _row_round_index(row)
    ]
    compile_check_total = len(final_compile_rows)
    retrieval_refs = _retrieval_refs_by_sample(retrieval_rows or [])
    grounding_success = sum(1 for row in grounding_rows if row.parse_ok)
    statement_generation_success = sum(1 for s in summaries if s.statement_generation_ok)
    compile_by_sample: dict[str, bool] = {}
    for row in final_compile_rows:
        sid = _row_sample_id(row)
        compile_by_sample[sid] = compile_by_sample.get(sid, False) or _row_bool(row, "compile_pass")
    compile_pass = sum(1 for passed in compile_by_sample.values() if passed)
    compile_total = len(compile_by_sample)
    semantic_pass = sum(1 for row in final_semantic_rows if row.semantic_pass)
    semantic_total = sum(1 for row in final_semantic_rows if row.ranking)
    proof_success = sum(1 for row in final_proof_rows if row.proof_success)
    proof_total = len(final_proof_rows)
    e2e_success = sum(1 for s in summaries if s.end_to_end_ok)
    mechlib_header = sum(1 for row in final_statement_rows if _is_mechlib_header(row.get("lean_header")))
    mechlib_header_total = len(final_statement_rows)
    mechlib_compile_pass = sum(
        1
        for row in final_compile_rows
        if row.compile_pass and (row.backend_used or "").strip().lower() == "mechlib"
    )
    selected_rows = [row for row in final_semantic_rows if row.selected_candidate_id]
    selected_mechlib = sum(
        1
        for row in selected_rows
        if (row.selected_backend or "").strip().lower() == "mechlib"
    )
    candidate_map: dict[tuple[str, int, str], dict[str, Any]] = {}
    for row in final_statement_rows:
        candidate_map[(str(row.get("sample_id") or ""), _row_round_index(row), str(row.get("candidate_id") or ""))] = row
    statement_mechlib_usage = sum(
        1
        for row in final_statement_rows
        if _statement_uses_mechlib(row, retrieval_refs.get(str(row.get("sample_id") or ""), set()))
    )
    selected_statement_mechlib_usage = 0
    library_grounded_selection = 0
    for row in selected_rows:
        sid = _row_sample_id(row)
        cid = str(row.selected_candidate_id or "")
        selected_candidate_row = candidate_map.get((sid, _row_round_index(row), cid))
        if selected_candidate_row and _statement_uses_mechlib(selected_candidate_row, retrieval_refs.get(sid, set())):
            selected_statement_mechlib_usage += 1
        if bool(selected_candidate_row and _statement_uses_mechlib(selected_candidate_row, retrieval_refs.get(sid, set()))) or any(
            isinstance(item, dict) and str(item.get("candidate_id") or "") == cid and float(item.get("library_grounding_score") or 0.0) > 0
            for item in (row.ranking or [])
        ):
            library_grounded_selection += 1
    final_attempt_by_sample: dict[str, dict[str, Any]] = {}
    for row in proof_attempt_rows or []:
        sid = str(row.get("sample_id") or "")
        if final_round_map.get(sid, 0) != _row_round_index(row):
            continue
        current = final_attempt_by_sample.get(sid)
        if current is None or _row_round_index(row) > _row_round_index(current) or int(row.get("attempt_index") or 0) >= int(current.get("attempt_index") or 0):
            final_attempt_by_sample[sid] = row
    proof_mechlib_usage = sum(
        1
        for sid, row in final_attempt_by_sample.items()
        if _proof_uses_mechlib(row, retrieval_refs.get(sid, set()))
    )
    feedback_loop_used = sum(1 for s in summaries if s.feedback_loop_used)

    error_counter: Counter[str] = Counter()
    for s in summaries:
        if s.final_error_type:
            error_counter[s.final_error_type] += 1

    return {
        "num_total_samples": total,
        "grounding_success_rate": _safe_rate(grounding_success, total),
        "statement_generation_success_rate": _safe_rate(statement_generation_success, total),
        "lean_compile_success_rate": _safe_rate(compile_pass, compile_total),
        "semantic_consistency_pass_rate": _safe_rate(semantic_pass, semantic_total),
        "proof_success_rate": _safe_rate(proof_success, proof_total),
        "end_to_end_verified_solve_rate": _safe_rate(e2e_success, total),
        "mechlib_header_rate": _safe_rate(mechlib_header, mechlib_header_total),
        "mechlib_compile_pass_rate": _safe_rate(mechlib_compile_pass, compile_check_total),
        "selected_mechlib_candidate_rate": _safe_rate(selected_mechlib, len(selected_rows)),
        "statement_mechlib_usage_rate": _safe_rate(statement_mechlib_usage, len(final_statement_rows)),
        "selected_statement_mechlib_usage_rate": _safe_rate(selected_statement_mechlib_usage, len(selected_rows)),
        "proof_mechlib_usage_rate": _safe_rate(proof_mechlib_usage, len(final_attempt_by_sample)),
        "library_grounded_selection_rate": _safe_rate(library_grounded_selection, len(selected_rows)),
        "feedback_loop_used_rate": _safe_rate(feedback_loop_used, total),
        "error_type_distribution": dict(error_counter),
    }
