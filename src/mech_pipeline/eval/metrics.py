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


def build_metrics(
    summaries: list[SampleRunSummary],
    statement_rows: list[dict[str, Any]],
    grounding_rows: list[GroundingResult],
    compile_rows: list[CompileCheckResult],
    semantic_rows: list[SemanticRankResult],
    proof_rows: list[ProofCheckResult],
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
    grounding_success = sum(1 for row in grounding_rows if row.parse_ok)
    statement_generation_success = sum(1 for s in summaries if s.statement_generation_ok)
    compile_pass = sum(1 for row in final_compile_rows if row.compile_pass)
    compile_total = len(final_compile_rows)
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
        "mechlib_compile_pass_rate": _safe_rate(mechlib_compile_pass, compile_total),
        "selected_mechlib_candidate_rate": _safe_rate(selected_mechlib, len(selected_rows)),
        "feedback_loop_used_rate": _safe_rate(feedback_loop_used, total),
        "error_type_distribution": dict(error_counter),
    }
