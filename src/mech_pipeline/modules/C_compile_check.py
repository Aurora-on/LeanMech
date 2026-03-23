from __future__ import annotations

from pathlib import Path

from mech_pipeline.adapters.lean_runner import LeanRunner
from mech_pipeline.types import CompileCheckResult, StatementCandidate


class ModuleC:
    def __init__(self, lean_runner: LeanRunner) -> None:
        self.lean_runner = lean_runner

    def run(
        self,
        sample_id: str,
        candidates: list[StatementCandidate],
        run_dir: Path,
    ) -> list[CompileCheckResult]:
        rows: list[CompileCheckResult] = []
        for candidate in candidates:
            result = self.lean_runner.compile_statement(
                sample_id=sample_id,
                candidate_id=candidate.candidate_id,
                lean_header=candidate.lean_header,
                theorem_decl=candidate.theorem_decl,
                run_dir=run_dir,
            )
            rows.append(
                CompileCheckResult(
                    sample_id=sample_id,
                    candidate_id=candidate.candidate_id,
                    compile_pass=bool(result["compile_pass"]),
                    syntax_ok=bool(result["syntax_ok"]),
                    elaboration_ok=bool(result["elaboration_ok"]),
                    error_type=str(result["error_type"]) if result["error_type"] else None,
                    stderr_digest=str(result["stderr_digest"]),
                    log_path=str(result["log_path"]) if result["log_path"] else None,
                    backend_used=str(result.get("backend_used") or ""),
                    route_reason=str(result.get("route_reason") or ""),
                    route_fallback_used=bool(result.get("route_fallback_used")),
                )
            )
        return rows
