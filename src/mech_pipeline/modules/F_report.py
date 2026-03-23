from __future__ import annotations

from collections import Counter
from typing import Any

from mech_pipeline.eval.metrics import build_metrics
from mech_pipeline.types import CompileCheckResult, GroundingResult, ProofCheckResult, SampleRunSummary, SemanticRankResult


class ModuleF:
    def build(
        self,
        summaries: list[SampleRunSummary],
        grounding_rows: list[GroundingResult],
        compile_rows: list[CompileCheckResult],
        semantic_rows: list[SemanticRankResult],
        proof_rows: list[ProofCheckResult],
    ) -> tuple[dict[str, Any], str]:
        metrics = build_metrics(
            summaries=summaries,
            grounding_rows=grounding_rows,
            compile_rows=compile_rows,
            semantic_rows=semantic_rows,
            proof_rows=proof_rows,
        )

        counter: Counter[str] = Counter()
        for s in summaries:
            if s.final_error_type:
                counter[s.final_error_type] += 1
        failed_ids = [s.sample_id for s in summaries if not s.end_to_end_ok][:10]

        lines = [
            "# Baseline V1 Analysis",
            "",
            "## Metrics",
            f"- num_total_samples: {metrics['num_total_samples']}",
            f"- grounding_success_rate: {metrics['grounding_success_rate']}",
            f"- statement_generation_success_rate: {metrics['statement_generation_success_rate']}",
            f"- lean_compile_success_rate: {metrics['lean_compile_success_rate']}",
            f"- semantic_consistency_pass_rate: {metrics['semantic_consistency_pass_rate']}",
            f"- proof_success_rate: {metrics['proof_success_rate']}",
            f"- end_to_end_verified_solve_rate: {metrics['end_to_end_verified_solve_rate']}",
            "",
            "## Error Distribution",
        ]
        if counter:
            for key, value in counter.most_common():
                lines.append(f"- {key}: {value}")
        else:
            lines.append("- none")

        lines.extend(
            [
                "",
                "## Representative Failed Samples",
                f"- sample_ids: {failed_ids}",
                "",
                "## Stage Log Files",
                "- problem_ir.jsonl",
                "- mechlib_retrieval.jsonl",
                "- statement_candidates.jsonl",
                "- compile_checks.jsonl",
                "- semantic_rank.jsonl",
                "- proof_attempts.jsonl",
                "- proof_checks.jsonl",
                "- sample_summary.jsonl",
                "- metrics.json",
                "- analysis.md",
            ]
        )
        return metrics, "\n".join(lines) + "\n"
