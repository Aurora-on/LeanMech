from __future__ import annotations

from collections import Counter
from typing import Any

from mech_pipeline.types import CompileCheckResult, GroundingResult, ProofCheckResult, SampleRunSummary, SemanticRankResult


def _safe_rate(num: int, den: int) -> float:
    if den <= 0:
        return 0.0
    return round(num / den, 6)


def build_metrics(
    summaries: list[SampleRunSummary],
    grounding_rows: list[GroundingResult],
    compile_rows: list[CompileCheckResult],
    semantic_rows: list[SemanticRankResult],
    proof_rows: list[ProofCheckResult],
) -> dict[str, Any]:
    total = len(summaries)
    grounding_success = sum(1 for row in grounding_rows if row.parse_ok)
    statement_generation_success = sum(1 for s in summaries if s.statement_generation_ok)
    compile_pass = sum(1 for row in compile_rows if row.compile_pass)
    compile_total = len(compile_rows)
    semantic_pass = sum(1 for row in semantic_rows if row.semantic_pass)
    semantic_total = sum(1 for row in semantic_rows if row.ranking)
    proof_success = sum(1 for row in proof_rows if row.proof_success)
    proof_total = len(proof_rows)
    e2e_success = sum(1 for s in summaries if s.end_to_end_ok)

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
        "error_type_distribution": dict(error_counter),
    }
