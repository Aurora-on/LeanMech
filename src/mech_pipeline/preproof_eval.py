from __future__ import annotations

import json
import os
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import fields
from pathlib import Path
from typing import Any, Callable, TypedDict

from mech_pipeline.adapters import LeanRunner
from mech_pipeline.archive import create_run_dir, write_outputs
from mech_pipeline.config import (
    DatasetConfig,
    KnowledgeConfig,
    Lean4PhysConfig,
    LeanConfig,
    LLMGuidedSearchConfig,
    LocalArchiveConfig,
    ModelConfig,
    OutputConfig,
    PipelineConfig,
    PromptConfig,
    ProofConfig,
    RuntimeConfig,
    SemanticConfig,
    SolutionRendererConfig,
    StatementConfig,
    load_config,
    validate_config,
)
from mech_pipeline.model import build_model_client
from mech_pipeline.modules import ModuleE, ModuleF, ModuleSolutionRenderer
from mech_pipeline.rendering import build_lean_export_files, build_run_readme
from mech_pipeline.types import (
    CanonicalSample,
    CompileCheckResult,
    GroundingResult,
    ProofCheckResult,
    SampleRunSummary,
    SemanticRankResult,
    StatementCandidate,
    TheoremSkeletonCandidate,
)
from mech_pipeline.utils import append_jsonl, read_jsonl, to_row


PREPROOF_STAGE_ROW_FILES = (
    "problem_ir.jsonl",
    "model_ir.jsonl",
    "structured_mechlib_context.jsonl",
    "evidence_bindings.jsonl",
    "controlled_sketch.jsonl",
    "sketch_audit.jsonl",
    "failure_routes.jsonl",
    "mechlib_retrieval.jsonl",
    "statement_candidates.jsonl",
    "theorem_skeleton_candidates.jsonl",
    "compile_checks.jsonl",
    "semantic_rank.jsonl",
    "proof_attempts.jsonl",
    "proof_checks.jsonl",
    "proof_search_trace.jsonl",
    "proof_action_checks.jsonl",
    "proof_strategy_prompts.jsonl",
    "proof_dependency_audit.jsonl",
    "solution_trace.jsonl",
    "natural_solution.jsonl",
    "solution_render_audit.jsonl",
    "sample_summary.jsonl",
)

_REDACTED = "***REDACTED***"


class PreproofSampleResult(TypedDict):
    stage_rows: dict[str, list[dict[str, object]]]
    proof_rows: list[ProofCheckResult]
    summary: SampleRunSummary


class PreproofExecutionResult(TypedDict):
    stage_rows: dict[str, list[dict[str, object]]]
    proof_rows: list[ProofCheckResult]
    summaries: list[SampleRunSummary]
    sample_concurrency: int


def _merge_dict(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dict(merged[key], value)
        else:
            merged[key] = value
    return merged


def _config_from_dict(payload: dict[str, Any]) -> PipelineConfig:
    defaults = PipelineConfig()
    merged = _merge_dict(defaults.to_dict(), payload)
    return PipelineConfig(
        dataset=DatasetConfig(
            **{
                **merged["dataset"],
                "local_archive": LocalArchiveConfig(**merged["dataset"]["local_archive"]),
                "lean4phys": Lean4PhysConfig(**merged["dataset"]["lean4phys"]),
            }
        ),
        model=ModelConfig(**merged["model"]),
        lean=LeanConfig(**merged["lean"]),
        knowledge=KnowledgeConfig(**merged["knowledge"]),
        statement=StatementConfig(**merged["statement"]),
        semantic=SemanticConfig(**merged["semantic"]),
        proof=ProofConfig(
            **{
                **merged["proof"],
                "llm_guided_search": LLMGuidedSearchConfig(**merged["proof"]["llm_guided_search"]),
            }
        ),
        solution_renderer=SolutionRendererConfig(**merged["solution_renderer"]),
        prompts=PromptConfig(**merged["prompts"]),
        output=OutputConfig(**merged["output"]),
        runtime=RuntimeConfig(**merged["runtime"]),
    )


def _redact_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, nested in value.items():
            lowered = str(key).lower()
            if "api_key" in lowered or lowered.endswith("token") or "secret" in lowered:
                out[key] = _REDACTED if nested else nested
            else:
                out[key] = _redact_secrets(nested)
        return out
    if isinstance(value, list):
        return [_redact_secrets(item) for item in value]
    return value


def _auto_api_key_env() -> str | None:
    for name in ("OPENAI_PROXY_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY"):
        if os.environ.get(name):
            return name
    return None


def _repair_redacted_model_config(cfg: PipelineConfig, api_key_env: str | None) -> None:
    if cfg.model.api_key == _REDACTED:
        cfg.model.api_key = None
    if api_key_env:
        cfg.model.api_key_env = api_key_env
    elif cfg.model.api_key_env == _REDACTED:
        detected = _auto_api_key_env()
        if detected:
            cfg.model.api_key_env = detected


def load_preproof_config(preproof_dir: Path, override_config: Path | None, api_key_env: str | None) -> PipelineConfig:
    if override_config is not None:
        cfg = load_config(override_config)
    else:
        config_path = preproof_dir / "config_preproof.json"
        if not config_path.exists():
            raise FileNotFoundError(f"preproof config not found: {config_path}")
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        resolved = payload.get("resolved_config") if isinstance(payload, dict) else None
        if not isinstance(resolved, dict):
            raise ValueError(f"preproof config does not contain resolved_config: {config_path}")
        cfg = _config_from_dict(resolved)
    _repair_redacted_model_config(cfg, api_key_env)
    validate_config(cfg)
    return cfg


def _dataclass_from_row(cls, row: dict[str, Any]):
    allowed = {field.name for field in fields(cls)}
    return cls(**{key: value for key, value in row.items() if key in allowed})


def _candidate_from_row(row: dict[str, Any]) -> StatementCandidate:
    if str(row.get("generation_mode") or "") == "minimal_skeleton" or "proof_obligations" in row:
        return _dataclass_from_row(TheoremSkeletonCandidate, row)
    return _dataclass_from_row(StatementCandidate, row)


def _latest_by_sample(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        sid = str(row.get("sample_id") or "").strip()
        if sid:
            latest[sid] = row
    return latest


def _rows_for_samples(rows: list[dict[str, Any]], sample_ids: set[str]) -> list[dict[str, Any]]:
    return [row for row in rows if str(row.get("sample_id") or "") in sample_ids]


def _problem_text_from_ir(sample_id: str, problem_ir: dict[str, Any] | None) -> str:
    if not isinstance(problem_ir, dict):
        return sample_id
    for key in ("problem_text", "goal_statement", "statement", "question"):
        value = str(problem_ir.get(key) or "").strip()
        if value:
            return value
    target = problem_ir.get("unknown_target")
    if isinstance(target, dict):
        text = str(target.get("description") or target.get("name") or "").strip()
        if text:
            return text
    return sample_id


class PreproofBundle:
    def __init__(self, preproof_dir: Path, sample_ids: list[str]) -> None:
        self.preproof_dir = preproof_dir
        self.sample_ids = sample_ids
        self.sample_id_set = set(sample_ids)

        artifact_dir = preproof_dir / "artifacts"
        self.problem_rows = _rows_for_samples(read_jsonl(artifact_dir / "problem_ir.jsonl"), self.sample_id_set)
        self.model_rows = _rows_for_samples(read_jsonl(artifact_dir / "model_ir.jsonl"), self.sample_id_set)
        self.structured_context_rows = _rows_for_samples(
            read_jsonl(artifact_dir / "structured_mechlib_context.jsonl"), self.sample_id_set
        )
        self.evidence_rows = _rows_for_samples(read_jsonl(artifact_dir / "evidence_bindings.jsonl"), self.sample_id_set)
        self.controlled_sketch_rows = _rows_for_samples(
            read_jsonl(artifact_dir / "controlled_sketch.jsonl"), self.sample_id_set
        )
        self.sketch_audit_rows = _rows_for_samples(read_jsonl(artifact_dir / "sketch_audit.jsonl"), self.sample_id_set)
        self.failure_route_rows = _rows_for_samples(read_jsonl(artifact_dir / "failure_routes.jsonl"), self.sample_id_set)
        self.retrieval_rows = _rows_for_samples(read_jsonl(artifact_dir / "mechlib_retrieval.jsonl"), self.sample_id_set)

        self.selected_candidate_rows = _rows_for_samples(
            read_jsonl(preproof_dir / "selected_candidates.jsonl"), self.sample_id_set
        )
        self.selected_compile_rows = _rows_for_samples(
            read_jsonl(preproof_dir / "selected_compile_checks.jsonl"), self.sample_id_set
        )
        self.selected_semantic_rows = _rows_for_samples(
            read_jsonl(preproof_dir / "selected_semantic_rank.jsonl"), self.sample_id_set
        )

        self.problem_by_sample = _latest_by_sample(self.problem_rows)
        self.model_by_sample = _latest_by_sample(self.model_rows)
        self.controlled_sketch_by_sample = _latest_by_sample(self.controlled_sketch_rows)
        self.retrieval_by_sample = _latest_by_sample(self.retrieval_rows)
        self.candidate_by_sample = _latest_by_sample(self.selected_candidate_rows)
        self.compile_by_sample = _latest_by_sample(self.selected_compile_rows)
        self.semantic_by_sample = _latest_by_sample(self.selected_semantic_rows)

        self.samples = self._build_samples()

    @classmethod
    def load(
        cls,
        preproof_dir: Path,
        *,
        requested_sample_ids: list[str] | None = None,
        limit: int | None = None,
    ) -> "PreproofBundle":
        if not preproof_dir.exists():
            raise FileNotFoundError(f"preproof directory does not exist: {preproof_dir}")
        eligible_rows = read_jsonl(preproof_dir / "eligible_samples.jsonl")
        if eligible_rows:
            sample_ids = [
                str(row.get("sample_id") or "").strip()
                for row in eligible_rows
                if row.get("preproof_eligible", True) and str(row.get("sample_id") or "").strip()
            ]
        else:
            sample_ids = [
                str(row.get("sample_id") or "").strip()
                for row in read_jsonl(preproof_dir / "selected_candidates.jsonl")
                if str(row.get("sample_id") or "").strip()
            ]
        if requested_sample_ids:
            requested = set(requested_sample_ids)
            sample_ids = [sid for sid in sample_ids if sid in requested]
        if limit is not None:
            sample_ids = sample_ids[:limit]
        if not sample_ids:
            raise ValueError("no preproof eligible samples matched the requested filters")
        return cls(preproof_dir, sample_ids)

    def _build_samples(self) -> dict[str, CanonicalSample]:
        samples: dict[str, CanonicalSample] = {}
        for sid in self.sample_ids:
            problem_row = self.problem_by_sample.get(sid, {})
            problem_ir = problem_row.get("problem_ir") if isinstance(problem_row.get("problem_ir"), dict) else None
            source = sid.split("-", 1)[0] if "-" in sid else "preproof"
            samples[sid] = CanonicalSample(
                sample_id=sid,
                source=source,
                problem_text=_problem_text_from_ir(sid, problem_ir),
                meta={"name": sid, "preproof_source_dir": self.preproof_dir.as_posix()},
            )
        return samples

    def base_stage_rows(self) -> dict[str, list[dict[str, object]]]:
        rows: dict[str, list[dict[str, object]]] = {name: [] for name in PREPROOF_STAGE_ROW_FILES}
        rows["problem_ir.jsonl"] = list(self.problem_rows)
        rows["model_ir.jsonl"] = list(self.model_rows)
        rows["structured_mechlib_context.jsonl"] = list(self.structured_context_rows)
        rows["evidence_bindings.jsonl"] = list(self.evidence_rows)
        rows["controlled_sketch.jsonl"] = list(self.controlled_sketch_rows)
        rows["sketch_audit.jsonl"] = list(self.sketch_audit_rows)
        rows["failure_routes.jsonl"] = list(self.failure_route_rows)
        rows["mechlib_retrieval.jsonl"] = list(self.retrieval_rows)
        rows["statement_candidates.jsonl"] = list(self.selected_candidate_rows)
        rows["theorem_skeleton_candidates.jsonl"] = list(self.selected_candidate_rows)
        rows["compile_checks.jsonl"] = list(self.selected_compile_rows)
        rows["semantic_rank.jsonl"] = list(self.selected_semantic_rows)
        return rows


def _build_lean_runner(cfg: PipelineConfig) -> LeanRunner:
    return LeanRunner(
        physlean_dir=Path(cfg.lean.physlean_dir),
        mechlib_dir=Path(cfg.lean.mechlib_dir),
        timeout_s=cfg.lean.timeout_s,
        strict_blocklist=cfg.lean.strict_blocklist,
        lean_header=cfg.lean.lean_header,
        enabled=cfg.lean.enabled,
        route_policy=cfg.lean.route_policy,
        default_backend=cfg.lean.default_backend,
        route_fallback=cfg.lean.route_fallback,
    )


def _build_preproof_worker_modules(cfg: PipelineConfig, prompt_dir: Path) -> tuple[ModuleE, ModuleSolutionRenderer]:
    model_client = build_model_client(cfg.model)
    lean_runner = _build_lean_runner(cfg)
    module_e = ModuleE(
        model_client=model_client,
        lean_runner=lean_runner,
        prompt_plan_path=prompt_dir / cfg.prompts.e_plan_proof,
        prompt_generate_path=prompt_dir / cfg.prompts.e_generate_proof,
        prompt_repair_path=prompt_dir / cfg.prompts.e_repair_proof,
        max_attempts=cfg.proof.max_attempts,
        proof_config=cfg.proof,
    )
    renderer = ModuleSolutionRenderer(
        model_client=model_client,
        prompt_path=prompt_dir / cfg.prompts.solution_renderer,
        config=cfg.solution_renderer,
    )
    return module_e, renderer


def _stage_rows_for_proof_attempts(
    *,
    final_round_index: int,
    proof_attempts: list[Any],
    proof_check: ProofCheckResult,
) -> dict[str, list[dict[str, object]]]:
    rows: dict[str, list[dict[str, object]]] = {name: [] for name in PREPROOF_STAGE_ROW_FILES}
    for attempt in proof_attempts:
        if attempt.proof_search_trace:
            trace_row = dict(attempt.proof_search_trace)
            trace_row["round_index"] = final_round_index
            rows["proof_search_trace.jsonl"].append(trace_row)
        if attempt.proof_action_checks:
            action_rows = []
            for row in attempt.proof_action_checks:
                payload = dict(row)
                payload["round_index"] = final_round_index
                action_rows.append(payload)
            rows["proof_action_checks.jsonl"].extend(action_rows)
        if attempt.proof_strategy_prompts:
            prompt_rows = []
            for row in attempt.proof_strategy_prompts:
                payload = dict(row)
                payload["round_index"] = final_round_index
                prompt_rows.append(payload)
            rows["proof_strategy_prompts.jsonl"].extend(prompt_rows)
        if attempt.dependency_audit:
            audit_row = dict(attempt.dependency_audit)
            audit_row["round_index"] = final_round_index
            rows["proof_dependency_audit.jsonl"].append(audit_row)
    rows["proof_attempts.jsonl"].extend(to_row(attempt) for attempt in proof_attempts)
    rows["proof_checks.jsonl"].append(to_row(proof_check))
    return rows


def _skip_proof_check(
    *,
    sample_id: str,
    selected_candidate_id: str | None,
    semantic: SemanticRankResult | None,
    final_round_index: int,
    reason: str,
) -> ProofCheckResult:
    return ProofCheckResult(
        sample_id=sample_id,
        proof_success=False,
        attempts_used=0,
        selected_candidate_id=selected_candidate_id,
        error_type=reason,
        final_log_path=None,
        backend_used=semantic.selected_backend if semantic else None,
        round_index=final_round_index,
        sub_error_type=reason,
        failure_tags=[reason],
        failure_summary="Proof stage skipped by preproof E runner.",
        failure_details={
            "semantic_error_type": semantic.error if semantic else None,
            "semantic_sub_error_type": semantic.sub_error_type if semantic else None,
            "semantic_failure_summary": semantic.failure_summary if semantic else None,
        },
    )


def process_preproof_sample(
    *,
    cfg: PipelineConfig,
    bundle: PreproofBundle,
    sample_id: str,
    run_dir: Path,
    prompt_dir: Path,
    inject_set: set[str],
    preflight_ok: bool,
    preflight_error: str | None,
    preflight_message: str,
    dry_run: bool = False,
) -> PreproofSampleResult:
    rows: dict[str, list[dict[str, object]]] = {name: [] for name in PREPROOF_STAGE_ROW_FILES}
    sample = bundle.samples[sample_id]
    grounding_row = bundle.problem_by_sample.get(sample_id)
    candidate_row = bundle.candidate_by_sample.get(sample_id)
    compile_row = bundle.compile_by_sample.get(sample_id)
    semantic_row = bundle.semantic_by_sample.get(sample_id)

    grounding = _dataclass_from_row(GroundingResult, grounding_row) if grounding_row else None
    candidate = _candidate_from_row(candidate_row) if candidate_row else None
    compile_check = _dataclass_from_row(CompileCheckResult, compile_row) if compile_row else None
    semantic = _dataclass_from_row(SemanticRankResult, semantic_row) if semantic_row else None
    final_round_index = int(
        (semantic_row or {}).get("round_index")
        or (candidate_row or {}).get("round_index")
        or (compile_row or {}).get("round_index")
        or 0
    )

    proof_attempts: list[Any] = []
    if not preflight_ok:
        proof_check = _skip_proof_check(
            sample_id=sample_id,
            selected_candidate_id=(semantic.selected_candidate_id if semantic else None),
            semantic=semantic,
            final_round_index=final_round_index,
            reason=preflight_error or "lean_preflight_failed",
        )
        proof_check.failure_summary = preflight_message
    elif dry_run:
        proof_check = _skip_proof_check(
            sample_id=sample_id,
            selected_candidate_id=(semantic.selected_candidate_id if semantic else None),
            semantic=semantic,
            final_round_index=final_round_index,
            reason="dry_run_skipped",
        )
    elif grounding is None or candidate is None or compile_check is None or semantic is None:
        proof_check = _skip_proof_check(
            sample_id=sample_id,
            selected_candidate_id=(semantic.selected_candidate_id if semantic else None),
            semantic=semantic,
            final_round_index=final_round_index,
            reason="preproof_artifact_missing",
        )
    elif not semantic.semantic_pass:
        proof_check = _skip_proof_check(
            sample_id=sample_id,
            selected_candidate_id=semantic.selected_candidate_id,
            semantic=semantic,
            final_round_index=final_round_index,
            reason="proof_skipped_due_to_semantic_fail",
        )
    else:
        module_e, renderer = _build_preproof_worker_modules(cfg, prompt_dir)
        retrieval_row = bundle.retrieval_by_sample.get(sample_id, {})
        e_context = str(retrieval_row.get("retrieval_context") or "(none)") if "E" in inject_set else "(none)"
        proof_attempts, proof_check = module_e.run(
            grounding=grounding,
            selected_candidate=candidate,
            run_dir=run_dir,
            mechlib_context=e_context,
        )
        proof_check.round_index = final_round_index
        rows.update(
            _stage_rows_for_proof_attempts(
                final_round_index=final_round_index,
                proof_attempts=proof_attempts,
                proof_check=proof_check,
            )
        )
        if bool(getattr(cfg.solution_renderer, "enabled", True)) and proof_check.proof_success:
            solution_result = renderer.run(
                sample=sample,
                grounding=grounding,
                model_ir=bundle.model_by_sample.get(sample_id),
                controlled_sketch=bundle.controlled_sketch_by_sample.get(sample_id),
                selected_candidate=candidate,
                proof_attempts=proof_attempts,
                proof_check=proof_check,
            )
            if solution_result.solution_trace is not None:
                trace_row = solution_result.solution_trace.to_dict()
                trace_row["round_index"] = final_round_index
                rows["solution_trace.jsonl"].append(trace_row)
            natural_row = {
                "sample_id": solution_result.sample_id,
                "candidate_id": solution_result.candidate_id,
                "round_index": final_round_index,
                "render_success": solution_result.render_success,
                "proof_status": solution_result.proof_status,
                "natural_solution": solution_result.natural_solution,
                "raw_llm_response": solution_result.raw_llm_response,
                "error": solution_result.error,
                "render_audit_pass": (
                    solution_result.render_audit.audit_pass if solution_result.render_audit is not None else False
                ),
            }
            rows["natural_solution.jsonl"].append(natural_row)
            if solution_result.render_audit is not None:
                audit_row = solution_result.render_audit.to_dict()
                audit_row["round_index"] = final_round_index
                rows["solution_render_audit.jsonl"].append(audit_row)

    if not rows["proof_checks.jsonl"]:
        rows["proof_checks.jsonl"].append(to_row(proof_check))

    grounding_ok = bool(grounding and grounding.parse_ok)
    statement_ok = bool(candidate and candidate.parse_ok)
    compile_ok = bool(compile_check and compile_check.compile_pass)
    semantic_ok = bool(semantic and semantic.semantic_pass)
    end_to_end = grounding_ok and statement_ok and compile_ok and semantic_ok and proof_check.proof_success
    final_error: str | None = None
    final_sub_error: str | None = None
    final_failure_summary: str | None = None
    final_failure_details: dict[str, object] = {}
    if not end_to_end:
        if not grounding_ok:
            final_error = grounding.error if grounding else "preproof_grounding_missing"
            final_sub_error = final_error
            final_failure_summary = final_error
        elif not statement_ok:
            final_error = candidate.error if candidate else "preproof_candidate_missing"
            final_sub_error = final_error
            final_failure_summary = final_error
        elif not compile_ok:
            final_error = compile_check.error_type if compile_check else "preproof_compile_missing"
            final_sub_error = compile_check.sub_error_type if compile_check else final_error
            final_failure_summary = compile_check.failure_summary if compile_check else final_error
            final_failure_details = compile_check.failure_details if compile_check else {}
        elif not semantic_ok:
            final_error = semantic.error if semantic else "preproof_semantic_missing"
            final_sub_error = semantic.sub_error_type if semantic else final_error
            final_failure_summary = semantic.failure_summary if semantic else final_error
            final_failure_details = semantic.failure_details if semantic else {}
        else:
            final_error = proof_check.error_type or "proof_search_failure"
            final_sub_error = proof_check.sub_error_type
            final_failure_summary = proof_check.failure_summary
            final_failure_details = proof_check.failure_details

    summary = SampleRunSummary(
        sample_id=sample_id,
        grounding_ok=grounding_ok,
        statement_generation_ok=statement_ok,
        compile_ok=compile_ok,
        semantic_ok=semantic_ok,
        proof_ok=proof_check.proof_success,
        end_to_end_ok=end_to_end,
        final_error_type=final_error,
        notes="preproof_replay_e_only",
        final_round_index=final_round_index,
        feedback_loop_used=False,
        sub_error_type=final_sub_error,
        failure_summary=final_failure_summary,
        failure_details=final_failure_details,
    )
    return {"stage_rows": rows, "proof_rows": [proof_check], "summary": summary}


def _append_completed_preproof_rows(
    *,
    run_dir: Path,
    result: PreproofSampleResult,
) -> None:
    for name in PREPROOF_STAGE_ROW_FILES:
        if name == "sample_summary.jsonl":
            continue
        rows = result["stage_rows"].get(name, [])
        if rows:
            append_jsonl(run_dir / name, rows)
    append_jsonl(run_dir / "sample_summary.jsonl", [to_row(result["summary"])])


def execute_preproof_samples(
    *,
    cfg: PipelineConfig,
    bundle: PreproofBundle,
    run_dir: Path,
    prompt_dir: Path,
    inject_set: set[str],
    preflight_ok: bool,
    preflight_error: str | None,
    preflight_message: str,
    emit_console_line: Callable[[str], None],
    dry_run: bool = False,
) -> PreproofExecutionResult:
    sample_ids = bundle.sample_ids
    total = len(sample_ids)
    sample_concurrency = min(cfg.runtime.sample_concurrency, total) if total else 1
    ordered: list[PreproofSampleResult | None] = [None] * total
    completed = 0
    for idx, sample_id in enumerate(sample_ids, start=1):
        emit_console_line(f"[{idx}/{total}] preproof_sample={sample_id}")
    emit_console_line(f"progress: 0/{total} completed, sample_concurrency={sample_concurrency}")

    process_kwargs = {
        "cfg": cfg,
        "bundle": bundle,
        "run_dir": run_dir,
        "prompt_dir": prompt_dir,
        "inject_set": inject_set,
        "preflight_ok": preflight_ok,
        "preflight_error": preflight_error,
        "preflight_message": preflight_message,
        "dry_run": dry_run,
    }
    if sample_concurrency <= 1:
        for idx, sample_id in enumerate(sample_ids):
            result = process_preproof_sample(sample_id=sample_id, **process_kwargs)
            ordered[idx] = result
            _append_completed_preproof_rows(run_dir=run_dir, result=result)
            completed += 1
            emit_console_line(f"progress: {completed}/{total} completed, sample={sample_id}")
    else:
        futures: dict[Future[PreproofSampleResult], tuple[int, str]] = {}
        executor = ThreadPoolExecutor(max_workers=sample_concurrency, thread_name_prefix="preproof-e")
        try:
            for idx, sample_id in enumerate(sample_ids):
                future = executor.submit(process_preproof_sample, sample_id=sample_id, **process_kwargs)
                futures[future] = (idx, sample_id)
            for future in as_completed(futures):
                idx, sample_id = futures[future]
                try:
                    result = future.result()
                except Exception:
                    emit_console_line(f"progress: failed after {completed}/{total} completed, sample={sample_id}")
                    executor.shutdown(wait=False, cancel_futures=True)
                    raise
                ordered[idx] = result
                _append_completed_preproof_rows(run_dir=run_dir, result=result)
                completed += 1
                emit_console_line(f"progress: {completed}/{total} completed, sample={sample_id}")
        except Exception:
            executor.shutdown(wait=False, cancel_futures=True)
            raise
        else:
            executor.shutdown(wait=True)

    emit_console_line(f"progress: {completed}/{total} completed")
    stage_rows: dict[str, list[dict[str, object]]] = {name: [] for name in PREPROOF_STAGE_ROW_FILES}
    proof_rows: list[ProofCheckResult] = []
    summaries: list[SampleRunSummary] = []
    for result in [item for item in ordered if item is not None]:
        for name in PREPROOF_STAGE_ROW_FILES:
            if name == "sample_summary.jsonl":
                continue
            stage_rows[name].extend(result["stage_rows"].get(name, []))
        proof_rows.extend(result["proof_rows"])
        summaries.append(result["summary"])
    stage_rows["sample_summary.jsonl"] = [to_row(summary) for summary in summaries]
    return {
        "stage_rows": stage_rows,
        "proof_rows": proof_rows,
        "summaries": summaries,
        "sample_concurrency": sample_concurrency,
    }


def _preproof_extra_files(preproof_dir: Path) -> dict[str, str]:
    extra: dict[str, str] = {}
    for rel in (
        "source_run.txt",
        "preproof_metrics.json",
        "manifest_preproof.json",
        "selected_theorems.jsonl",
        "selected_theorems.lean",
    ):
        path = preproof_dir / rel
        if path.exists() and path.is_file():
            extra[f"preproof_source/{rel}"] = path.read_text(encoding="utf-8", errors="replace")
    return extra


def run_preproof_eval(
    *,
    preproof_dir: Path,
    config_path: Path | None,
    tag: str | None,
    sample_concurrency: int | None,
    limit: int | None,
    sample_ids: list[str] | None,
    api_key_env: str | None,
    output_dir: Path | None,
    runs_dir: Path | None,
    dry_run: bool,
    emit_console_line: Callable[[str], None],
) -> int:
    cfg = load_preproof_config(preproof_dir, config_path, api_key_env)
    if tag:
        cfg.output.tag = tag
    elif not cfg.output.tag:
        cfg.output.tag = "preproof-eval"
    else:
        cfg.output.tag = f"{cfg.output.tag}-preproof-e"
    if sample_concurrency is not None:
        cfg.runtime.sample_concurrency = sample_concurrency
    if output_dir is not None:
        cfg.output.output_dir = str(output_dir)
    if runs_dir is not None:
        cfg.output.runs_dir = str(runs_dir)
    validate_config(cfg)

    bundle = PreproofBundle.load(preproof_dir, requested_sample_ids=sample_ids, limit=limit)
    run_dir = create_run_dir(Path(cfg.output.runs_dir), cfg.output.tag)
    latest_dir = Path(cfg.output.output_dir)
    emit_console_line(f"run_dir={run_dir}")
    emit_console_line(f"latest_dir={latest_dir}")
    emit_console_line(f"preproof_dir={preproof_dir}")
    emit_console_line(f"preproof_samples={len(bundle.sample_ids)}")

    preflight_runner = _build_lean_runner(cfg)
    preflight_ok = True
    preflight_error: str | None = None
    preflight_message = "skip"
    preflight_details: dict[str, object] = {
        "ok": True,
        "error_type": None,
        "message": "skip",
        "environment_health": "clean",
        "environment_warnings": [],
    }
    if cfg.lean.enabled and cfg.lean.preflight_enabled:
        preflight_details = preflight_runner.preflight_details()
        preflight_ok = bool(preflight_details["ok"])
        preflight_error = str(preflight_details["error_type"]) if preflight_details.get("error_type") else None
        preflight_message = str(preflight_details["message"])
        emit_console_line(f"lean_preflight={preflight_ok}, message={preflight_message}")
        emit_console_line(
            f"environment_health={preflight_details.get('environment_health')}, warnings={len(preflight_details.get('environment_warnings') or [])}"
        )

    prompt_dir = Path(cfg.prompts.dir)
    inject_set = {item.strip().upper() for item in cfg.knowledge.inject_modules}
    execution = execute_preproof_samples(
        cfg=cfg,
        bundle=bundle,
        run_dir=run_dir,
        prompt_dir=prompt_dir,
        inject_set=inject_set,
        preflight_ok=preflight_ok,
        preflight_error=preflight_error,
        preflight_message=preflight_message,
        emit_console_line=emit_console_line,
        dry_run=dry_run,
    )

    stage_rows = bundle.base_stage_rows()
    for name in PREPROOF_STAGE_ROW_FILES:
        if name == "sample_summary.jsonl":
            continue
        stage_rows[name].extend(execution["stage_rows"].get(name, []))
    stage_rows["sample_summary.jsonl"] = [to_row(summary) for summary in execution["summaries"]]

    grounding_rows = [_dataclass_from_row(GroundingResult, row) for row in bundle.problem_rows]
    compile_rows = [_dataclass_from_row(CompileCheckResult, row) for row in bundle.selected_compile_rows]
    semantic_rows = [_dataclass_from_row(SemanticRankResult, row) for row in bundle.selected_semantic_rows]
    module_f = ModuleF()
    metrics, analysis = module_f.build(
        summaries=execution["summaries"],
        statement_rows=stage_rows["statement_candidates.jsonl"],
        grounding_rows=grounding_rows,
        compile_rows=compile_rows,
        semantic_rows=semantic_rows,
        proof_rows=execution["proof_rows"],
        retrieval_rows=stage_rows["mechlib_retrieval.jsonl"],
        proof_attempt_rows=stage_rows["proof_attempts.jsonl"],
        run_metadata={
            **preflight_details,
            "preproof_dir": preproof_dir.as_posix(),
            "preproof_e_only": True,
            "dry_run": dry_run,
        },
        stage_rows=stage_rows,
    )
    samples = [bundle.samples[sid] for sid in bundle.sample_ids]
    run_readme = build_run_readme(
        samples=samples,
        stage_rows=stage_rows,
        summaries=execution["summaries"],
        metrics=metrics,
        run_dir=run_dir,
        sample_concurrency=execution["sample_concurrency"],
        run_metadata={**preflight_details, "preproof_dir": preproof_dir.as_posix()},
    )
    lean_export_files = build_lean_export_files(
        cfg=cfg,
        samples=samples,
        stage_rows=stage_rows,
        summaries=execution["summaries"],
        run_dir=run_dir,
    )
    extra_files = {
        **lean_export_files,
        **_preproof_extra_files(preproof_dir),
        "preproof_eval_manifest.json": json.dumps(
            {
                "preproof_dir": preproof_dir.as_posix(),
                "sample_ids": bundle.sample_ids,
                "sample_count": len(bundle.sample_ids),
                "dry_run": dry_run,
                "stage_boundary": "A-D restored from preproof snapshot; E and solution rendering executed in this run.",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
    }
    write_outputs(
        run_dir=run_dir,
        latest_dir=latest_dir,
        stage_rows=stage_rows,
        metrics=metrics,
        analysis_md=analysis,
        run_readme_md=run_readme,
        config_payload={
            "resolved_config": _redact_secrets(cfg.to_dict()),
            "preproof_eval": {
                "preproof_dir": preproof_dir.as_posix(),
                "sample_count": len(bundle.sample_ids),
                "stage_boundary": "A-D restored from preproof snapshot; E and downstream stages executed only here.",
                "dry_run": dry_run,
            },
            "preflight": {
                "ok": preflight_ok,
                "error_type": preflight_error,
                "message": preflight_message,
                "environment_health": preflight_details.get("environment_health"),
                "environment_warnings": preflight_details.get("environment_warnings"),
            },
        },
        extra_text_files=extra_files,
    )
    return 0
