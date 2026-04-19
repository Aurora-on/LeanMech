from __future__ import annotations

from collections import Counter
from typing import Any

from mech_pipeline.eval.metrics import build_metrics
from mech_pipeline.types import CompileCheckResult, GroundingResult, ProofCheckResult, SampleRunSummary, SemanticRankResult


class ModuleF:
    def build(
        self,
        summaries: list[SampleRunSummary],
        statement_rows: list[dict[str, Any]],
        grounding_rows: list[GroundingResult],
        compile_rows: list[CompileCheckResult],
        semantic_rows: list[SemanticRankResult],
        proof_rows: list[ProofCheckResult],
        retrieval_rows: list[dict[str, Any]] | None = None,
        proof_attempt_rows: list[dict[str, Any]] | None = None,
        run_metadata: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], str]:
        metrics = build_metrics(
            summaries=summaries,
            statement_rows=statement_rows,
            grounding_rows=grounding_rows,
            compile_rows=compile_rows,
            semantic_rows=semantic_rows,
            proof_rows=proof_rows,
            retrieval_rows=retrieval_rows,
            proof_attempt_rows=proof_attempt_rows,
        )

        counter: Counter[str] = Counter()
        sub_counter: Counter[str] = Counter()
        mismatch_counter: Counter[str] = Counter()
        for s in summaries:
            if s.final_error_type:
                counter[s.final_error_type] += 1
            if s.sub_error_type:
                sub_counter[s.sub_error_type] += 1
            mismatch_fields = s.failure_details.get("mismatch_fields") if isinstance(s.failure_details, dict) else None
            if isinstance(mismatch_fields, list):
                for item in mismatch_fields:
                    text = str(item).strip()
                    if text:
                        mismatch_counter[text] += 1
        failed_ids = [s.sample_id for s in summaries if not s.end_to_end_ok][:10]
        feedback_loop_used = sum(1 for s in summaries if s.feedback_loop_used)
        feedback_loop_success = sum(1 for s in summaries if s.feedback_loop_used and s.end_to_end_ok)
        compile_sub_counter: Counter[str] = Counter()
        proof_sub_counter: Counter[str] = Counter()
        for row in compile_rows:
            if not row.compile_pass and row.sub_error_type:
                compile_sub_counter[row.sub_error_type] += 1
        for row in proof_rows:
            if not row.proof_success and row.sub_error_type:
                proof_sub_counter[row.sub_error_type] += 1
        env_health = str((run_metadata or {}).get("environment_health") or "unknown")
        env_warnings = (run_metadata or {}).get("environment_warnings") if isinstance(run_metadata, dict) else []
        if not isinstance(env_warnings, list):
            env_warnings = []

        lines = [
            "# Baseline V1 Analysis",
            "",
            "## Runtime Environment",
            f"- environment_health: {env_health}",
            f"- environment_warnings_count: {len(env_warnings)}",
        ]
        if env_warnings:
            lines.extend([f"- warning: {str(item)}" for item in env_warnings[:5]])

        lines.extend([
            "",
            "## Metrics",
            f"- num_total_samples: {metrics['num_total_samples']}",
            f"- grounding_success_rate: {metrics['grounding_success_rate']}",
            f"- statement_generation_success_rate: {metrics['statement_generation_success_rate']}",
            f"- lean_compile_success_rate: {metrics['lean_compile_success_rate']}",
            f"- semantic_consistency_pass_rate: {metrics['semantic_consistency_pass_rate']}",
            f"- proof_success_rate: {metrics['proof_success_rate']}",
            f"- end_to_end_verified_solve_rate: {metrics['end_to_end_verified_solve_rate']}",
            f"- mechlib_header_rate: {metrics['mechlib_header_rate']}",
            f"- mechlib_compile_pass_rate: {metrics['mechlib_compile_pass_rate']}",
            f"- selected_mechlib_candidate_rate: {metrics['selected_mechlib_candidate_rate']}",
            f"- statement_mechlib_usage_rate: {metrics['statement_mechlib_usage_rate']}",
            f"- selected_statement_mechlib_usage_rate: {metrics['selected_statement_mechlib_usage_rate']}",
            f"- proof_mechlib_usage_rate: {metrics['proof_mechlib_usage_rate']}",
            f"- library_grounded_selection_rate: {metrics['library_grounded_selection_rate']}",
            f"- feedback_loop_used_rate: {metrics.get('feedback_loop_used_rate', 0)}",
            "",
            "## Feedback Loop",
            f"- feedback_loop_used_count: {feedback_loop_used}",
            f"- feedback_loop_success_count: {feedback_loop_success}",
            "",
            "## Error Distribution",
        ])
        if counter:
            for key, value in counter.most_common():
                lines.append(f"- {key}: {value}")
        else:
            lines.append("- none")

        lines.extend(
            [
                "",
                "## Sub Error Distribution",
            ]
        )
        if sub_counter:
            for key, value in sub_counter.most_common():
                lines.append(f"- {key}: {value}")
        else:
            lines.append("- none")

        lines.extend(
            [
                "",
                "## Compile Sub Error Distribution",
            ]
        )
        if compile_sub_counter:
            for key, value in compile_sub_counter.most_common():
                lines.append(f"- {key}: {value}")
        else:
            lines.append("- none")

        lines.extend(
            [
                "",
                "## Proof Sub Error Distribution",
            ]
        )
        if proof_sub_counter:
            for key, value in proof_sub_counter.most_common():
                lines.append(f"- {key}: {value}")
        else:
            lines.append("- none")

        lines.extend(
            [
                "",
                "## Semantic Mismatch Fields",
            ]
        )
        if mismatch_counter:
            for key, value in mismatch_counter.most_common():
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
