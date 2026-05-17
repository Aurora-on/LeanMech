from __future__ import annotations

import json
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, TypedDict

from mech_pipeline.config import PipelineConfig
from mech_pipeline.failure_routing import apply_minimal_feedback_scope, build_failure_route, stage_at_or_before
from mech_pipeline.knowledge import (
    EvidenceBinder,
    LeanDeclCheckCache,
    MechLibRetriever,
    StructuredMechLibContext,
    build_structured_mechlib_context,
    evidence_binding_stage_rows,
    structured_context_stage_row,
)
from mech_pipeline.modules.sketch_audit import SketchAuditor, sketch_audit_stage_row
from mech_pipeline.modules.sketch_builder import controlled_sketch_stage_row
from mech_pipeline.types import (
    CompileCheckResult,
    ControlledSketch,
    EvidenceBinding,
    FailureRoute,
    GroundingResult,
    ModelIR,
    ProofCheckResult,
    SampleRunSummary,
    SemanticRankResult,
    SketchAuditResult,
    StatementCandidate,
)
from mech_pipeline.utils import append_jsonl, to_row


class ProcessSampleResult(TypedDict):
    stage_rows: dict[str, list[dict[str, object]]]
    grounding_rows: list[GroundingResult]
    compile_rows: list[CompileCheckResult]
    semantic_rows: list[SemanticRankResult]
    proof_rows: list[ProofCheckResult]
    summary: SampleRunSummary


class ExecutionResult(TypedDict):
    stage_rows: dict[str, list[dict[str, object]]]
    grounding_rows: list[GroundingResult]
    compile_rows: list[CompileCheckResult]
    semantic_rows: list[SemanticRankResult]
    proof_rows: list[ProofCheckResult]
    summaries: list[SampleRunSummary]
    sample_concurrency: int
    lean_decl_check_cache_stats: dict[str, int]


def new_stage_rows(stage_row_files: tuple[str, ...]) -> dict[str, list[dict[str, object]]]:
    return {name: [] for name in stage_row_files}


def _append_completed_sample_rows(
    *,
    run_dir: Path,
    stage_row_files: tuple[str, ...],
    result: ProcessSampleResult,
) -> None:
    for name in stage_row_files:
        if name == "sample_summary.jsonl":
            continue
        rows = result["stage_rows"].get(name, [])
        if rows:
            append_jsonl(run_dir / name, rows)
    append_jsonl(run_dir / "sample_summary.jsonl", [to_row(result["summary"])])


def process_sample(
    *,
    cfg: PipelineConfig,
    sample,
    run_dir: Path,
    prompt_dir: Path,
    inject_set: set[str],
    retriever: MechLibRetriever | None,
    preflight_ok: bool,
    preflight_error: str | None,
    preflight_message: str,
    stage_row_files: tuple[str, ...],
    build_worker_modules: Callable[[PipelineConfig, Path], tuple[Any, ...]],
    build_revision_feedback: Callable[..., str],
    lean_check_cache: LeanDeclCheckCache | None = None,
) -> ProcessSampleResult:
    stage_rows = new_stage_rows(stage_row_files)
    grounding_rows: list[GroundingResult] = []
    compile_rows: list[CompileCheckResult] = []
    semantic_rows: list[SemanticRankResult] = []
    proof_rows: list[ProofCheckResult] = []

    if sample.skip_reason:
        return {
            "stage_rows": stage_rows,
            "grounding_rows": grounding_rows,
            "compile_rows": compile_rows,
            "semantic_rows": semantic_rows,
            "proof_rows": proof_rows,
            "summary": SampleRunSummary(
                sample_id=sample.sample_id,
                grounding_ok=False,
                statement_generation_ok=False,
                compile_ok=False,
                semantic_ok=False,
                proof_ok=False,
                end_to_end_ok=False,
                final_error_type=sample.skip_reason,
                notes="dataset skip",
                final_round_index=0,
                feedback_loop_used=False,
                sub_error_type=sample.skip_reason,
                failure_summary="Sample skipped by dataset adapter.",
                failure_details={"skip_reason": sample.skip_reason},
            ),
        }

    if not preflight_ok:
        return {
            "stage_rows": stage_rows,
            "grounding_rows": grounding_rows,
            "compile_rows": compile_rows,
            "semantic_rows": semantic_rows,
            "proof_rows": proof_rows,
            "summary": SampleRunSummary(
                sample_id=sample.sample_id,
                grounding_ok=False,
                statement_generation_ok=False,
                compile_ok=False,
                semantic_ok=False,
                proof_ok=False,
                end_to_end_ok=False,
                final_error_type=preflight_error,
                notes=preflight_message,
                final_round_index=0,
                feedback_loop_used=False,
                sub_error_type=preflight_error,
                failure_summary=preflight_message,
                failure_details={"preflight_error": preflight_error, "preflight_message": preflight_message},
            ),
        }

    worker_modules = build_worker_modules(cfg, prompt_dir)
    if len(worker_modules) == 5:
        module_a, module_b, module_c, module_d, module_e = worker_modules
        module_a2 = None
        module_sketch = None
    elif len(worker_modules) == 6:
        module_a, module_a2, module_b, module_c, module_d, module_e = worker_modules
        module_sketch = None
    else:
        module_a, module_a2, module_sketch, module_b, module_c, module_d, module_e = worker_modules[:7]

    model_ir_for_b: ModelIR | None = None
    evidence_bindings_for_b: list[EvidenceBinding] = []
    controlled_sketch_for_b: ControlledSketch | None = None
    sketch_audit_for_b: SketchAuditResult | None = None
    structured_context_for_b: StructuredMechLibContext | None = None

    def _feedback_text(feedback: str | None) -> str:
        return feedback if feedback and feedback.strip() else "(none)"

    def _append_model_ir_row(model_ir: ModelIR, round_index: int | None = None) -> None:
        row = to_row(model_ir)
        if round_index is not None:
            row["round_index"] = round_index
        stage_rows.setdefault("model_ir.jsonl", []).append(row)

    def _append_evidence_rows(bindings: list[EvidenceBinding], round_index: int | None = None) -> None:
        rows = evidence_binding_stage_rows(sample.sample_id, bindings)
        if round_index is not None:
            for row in rows:
                row["round_index"] = round_index
        stage_rows.setdefault("evidence_bindings.jsonl", []).extend(rows)

    def _excluded_decls_from_feedback(revision_feedback: str) -> set[str]:
        try:
            payload = json.loads(revision_feedback)
        except json.JSONDecodeError:
            return set()
        if not isinstance(payload, dict):
            return set()
        out: set[str] = set()
        for candidate in payload.get("candidates", []) if isinstance(payload.get("candidates"), list) else []:
            if not isinstance(candidate, dict):
                continue
            blob = " ".join(
                str(candidate.get(key) or "")
                for key in (
                    "compile_error_type",
                    "compile_sub_error_type",
                    "compile_failure_tags",
                    "compile_failure_summary",
                    "unsupported_claims",
                )
            ).lower()
            if not any(key in blob for key in ("lean_check_failed", "signature_mismatch", "bad_decl", "wrong_decl")):
                continue
            for decl in candidate.get("verified_decls", []) if isinstance(candidate.get("verified_decls"), list) else []:
                text = str(decl or "").strip()
                if text:
                    out.add(text)
        return out

    def _run_minimal_model_ir_and_evidence(
        *,
        round_index: int,
        grounding: GroundingResult,
        revision_feedback: str,
        start_stage: str,
    ) -> None:
        nonlocal model_ir_for_b, evidence_bindings_for_b
        if cfg.statement.generation_mode != "minimal_skeleton":
            return
        if stage_at_or_before(start_stage, "A2"):
            if module_a2 is not None:
                model_ir = module_a2.run(
                    sample_id=sample.sample_id,
                    problem_text=sample.problem_text,
                    problem_ir=grounding.problem_ir,
                    structured_mechlib_context=structured_context_for_b,
                    image_description=sample.image_description,
                    revision_feedback=_feedback_text(revision_feedback),
                )
            else:
                model_ir = ModelIR(sample_id=sample.sample_id, parse_ok=False, error="model_ir_module_unavailable")
            _append_model_ir_row(model_ir, round_index=round_index)
            model_ir_for_b = model_ir
            evidence_bindings_for_b = []

        if stage_at_or_before(start_stage, "EvidenceBinder"):
            evidence_bindings: list[EvidenceBinding] = []
            if model_ir_for_b is not None and model_ir_for_b.parse_ok:
                evidence_bindings = EvidenceBinder(
                    top_k=cfg.knowledge.evidence_top_k,
                    lean_runner=getattr(module_c, "lean_runner", None),
                    lean_check_decls=cfg.knowledge.lean_check_decls,
                    run_dir=run_dir,
                    excluded_decl_names=_excluded_decls_from_feedback(revision_feedback),
                    lean_check_cache=lean_check_cache,
                ).bind(
                    model_ir_for_b,
                    structured_context_for_b
                    or StructuredMechLibContext(
                        modeling_context={
                            "matched_topics": [],
                            "concepts": [],
                            "law_schemas": [],
                            "problem_schemas": [],
                            "aliases": [],
                        },
                        proof_context={
                            "verified_decls": [],
                            "required_imports": [],
                            "proof_hints": [],
                            "proof_style_examples": [],
                        },
                        source_counts={},
                    ),
                    problem_text=sample.problem_text,
                    problem_ir=grounding.problem_ir,
                )
            _append_evidence_rows(evidence_bindings, round_index=round_index)
            evidence_bindings_for_b = evidence_bindings

    def _run_minimal_sketch_round(
        *,
        round_index: int,
        grounding: GroundingResult,
        revision_feedback: str,
        previous_candidates: list[StatementCandidate] | None,
        previous_sketch: ControlledSketch | None,
        start_stage: str,
    ) -> None:
        nonlocal controlled_sketch_for_b, sketch_audit_for_b
        if cfg.statement.generation_mode != "minimal_skeleton":
            return
        rerun_sketch = (
            stage_at_or_before(start_stage, "Sketch")
            or controlled_sketch_for_b is None
            or sketch_audit_for_b is None
        )
        if not rerun_sketch:
            return

        if model_ir_for_b is not None and model_ir_for_b.parse_ok and module_sketch is not None:
            controlled_sketch = module_sketch.run(
                sample_id=sample.sample_id,
                problem_text=sample.problem_text,
                problem_ir=grounding.problem_ir,
                model_ir=model_ir_for_b,
                evidence_bindings=evidence_bindings_for_b,
                structured_mechlib_context=structured_context_for_b,
                revision_feedback=_feedback_text(revision_feedback),
                previous_sketch=previous_sketch,
                previous_candidates=previous_candidates,
                round_index=round_index,
            )
        else:
            reason = (
                "model_ir_unavailable"
                if model_ir_for_b is None or not model_ir_for_b.parse_ok
                else "controlled_sketch_module_unavailable"
            )
            controlled_sketch = ControlledSketch(sample_id=sample.sample_id, parse_ok=False, error=reason)
        stage_rows.setdefault("controlled_sketch.jsonl", []).append(
            controlled_sketch_stage_row(sample.sample_id, controlled_sketch, round_index=round_index)
        )
        controlled_sketch_for_b = controlled_sketch

        if model_ir_for_b is None:
            audit = SketchAuditResult(
                sample_id=sample.sample_id,
                audit_pass=False,
                failure_tags=["model_ir_unavailable"],
                failure_summary="ModelIR was unavailable for sketch audit.",
            )
        else:
            hypothesis_provenance = list(model_ir_for_b.givens) + list(model_ir_for_b.local_definitions)
            audit = SketchAuditor(allow_explicit_gap_laws=cfg.statement.allow_explicit_gap_laws).audit(
                sample_id=sample.sample_id,
                model_ir=model_ir_for_b,
                sketch=controlled_sketch,
                evidence_bindings=evidence_bindings_for_b,
                structured_mechlib_context=structured_context_for_b,
                hypothesis_provenance=hypothesis_provenance,
            )
        stage_rows.setdefault("sketch_audit.jsonl", []).append(
            sketch_audit_stage_row(sample.sample_id, audit, round_index=round_index)
        )
        sketch_audit_for_b = audit

    def _run_statement_round(
        *,
        round_index: int,
        grounding: GroundingResult,
        mechlib_context: str,
        revision_feedback: str = "(none)",
        previous_candidates: list[StatementCandidate] | None = None,
        previous_sketch: ControlledSketch | None = None,
        start_stage: str = "Sketch",
    ) -> tuple[list[StatementCandidate], list[CompileCheckResult], SemanticRankResult]:
        b_context = mechlib_context if "B" in inject_set else "(none)"
        if cfg.statement.generation_mode == "minimal_skeleton":
            _run_minimal_model_ir_and_evidence(
                round_index=round_index,
                grounding=grounding,
                revision_feedback=revision_feedback,
                start_stage=start_stage,
            )
            _run_minimal_sketch_round(
                round_index=round_index,
                grounding=grounding,
                revision_feedback=revision_feedback,
                previous_candidates=previous_candidates,
                previous_sketch=previous_sketch,
                start_stage=start_stage,
            )
            if start_stage == "C" and previous_candidates is not None:
                candidates = previous_candidates
            else:
                candidates = module_b.run(
                    grounding,
                    mechlib_context=b_context,
                    revision_feedback=_feedback_text(revision_feedback),
                    round_index=round_index,
                    previous_candidates=previous_candidates,
                    generation_mode=cfg.statement.generation_mode,
                    problem_ir=grounding.problem_ir,
                    model_ir=model_ir_for_b,
                    controlled_sketch=controlled_sketch_for_b,
                    evidence_bindings=evidence_bindings_for_b,
                    structured_mechlib_context=structured_context_for_b,
                    sketch_audit_result=sketch_audit_for_b,
                    allow_explicit_gap_laws=cfg.statement.allow_explicit_gap_laws,
                )
        else:
            candidates = module_b.run(
                grounding,
                mechlib_context=b_context,
                revision_feedback=revision_feedback,
                round_index=round_index,
                previous_candidates=previous_candidates,
            )
        stage_rows["statement_candidates.jsonl"].extend(to_row(c) for c in candidates)
        if cfg.statement.generation_mode == "minimal_skeleton":
            stage_rows.setdefault("theorem_skeleton_candidates.jsonl", []).extend(to_row(c) for c in candidates)
            compile_candidates = [
                c
                for c in candidates
                if c.parse_ok
                and getattr(getattr(c, "skeleton_audit", None), "audit_pass", False)
                and getattr(c, "generation_blocked_reason", None) is None
            ]
        else:
            compile_candidates = candidates

        compile_results = module_c.run(sample.sample_id, compile_candidates, run_dir=run_dir)
        for row in compile_results:
            row.round_index = round_index
        compile_rows.extend(compile_results)
        stage_rows["compile_checks.jsonl"].extend(to_row(r) for r in compile_results)

        d_context = mechlib_context if "D" in inject_set else "(none)"
        semantic = module_d.run(
            grounding=grounding,
            candidates=compile_candidates,
            compile_checks=compile_results,
            problem_text=sample.problem_text,
            mechlib_context=d_context,
        )
        semantic.round_index = round_index
        return candidates, compile_results, semantic

    grounding = module_a.run(sample)
    grounding_rows.append(grounding)
    stage_rows["problem_ir.jsonl"].append(to_row(grounding))

    mechlib_items: list[dict[str, object]] = []
    summary_items: list[dict[str, object]] = []
    verified_decl_items: list[dict[str, object]] = []
    schema_items: list[dict[str, object]] = []
    alias_items: list[dict[str, object]] = []
    mechlib_pack: dict[str, object] = {
        "import_hints": [],
        "law_matched_items": [],
        "proof_style_examples": [],
        "domain_from_a": [],
        "selected_tags": [],
        "summary_items_count": 0,
        "verified_decl_items_count": 0,
        "schema_items_count": 0,
        "alias_items_count": 0,
        "source_items_count": 0,
        "final_context_chars": 0,
        "gap_schema_only": False,
    }
    mechlib_context = "(none)"
    structured_context: StructuredMechLibContext | None = None
    if retriever and grounding.parse_ok and cfg.statement.with_mechlib_context:
        domain_pack = retriever.build_domain_context(
            problem_text=sample.problem_text,
            problem_ir=grounding.problem_ir,
            top_k=cfg.knowledge.top_k,
        )
        raw_source_items = domain_pack.get("source_items")
        if isinstance(raw_source_items, list):
            mechlib_items = [x for x in raw_source_items if isinstance(x, dict)]
        raw_summary_items = domain_pack.get("summary_items")
        if isinstance(raw_summary_items, list):
            summary_items = [x for x in raw_summary_items if isinstance(x, dict)]
        raw_verified_decl_items = domain_pack.get("verified_decl_items")
        if isinstance(raw_verified_decl_items, list):
            verified_decl_items = [x for x in raw_verified_decl_items if isinstance(x, dict)]
        raw_schema_items = domain_pack.get("schema_items")
        if isinstance(raw_schema_items, list):
            schema_items = [x for x in raw_schema_items if isinstance(x, dict)]
        raw_alias_items = domain_pack.get("alias_items")
        if isinstance(raw_alias_items, list):
            alias_items = [x for x in raw_alias_items if isinstance(x, dict)]
        mechlib_pack = {
            "import_hints": domain_pack.get("import_hints", []),
            "law_matched_items": domain_pack.get("law_matched_items", []),
            "proof_style_examples": domain_pack.get("proof_style_examples", []),
            "domain_from_a": domain_pack.get("domain_from_a", []),
            "selected_tags": domain_pack.get("selected_tags", []),
            "summary_items_count": int(domain_pack.get("summary_items_count", len(summary_items))),
            "verified_decl_items_count": int(domain_pack.get("verified_decl_items_count", len(verified_decl_items))),
            "schema_items_count": int(domain_pack.get("schema_items_count", len(schema_items))),
            "alias_items_count": int(domain_pack.get("alias_items_count", len(alias_items))),
            "source_items_count": int(domain_pack.get("source_items_count", len(mechlib_items))),
            "final_context_chars": int(domain_pack.get("final_context_chars", 0)),
            "gap_schema_only": bool(domain_pack.get("gap_schema_only", False)),
        }
        mechlib_context = str(domain_pack.get("context_text") or "(none)")

    if grounding.parse_ok and cfg.statement.generation_mode == "minimal_skeleton":
        if retriever and cfg.knowledge.structured_context_enabled:
            structured_context = build_structured_mechlib_context(
                retriever,
                problem_text=sample.problem_text,
                problem_ir=grounding.problem_ir,
                top_k=cfg.knowledge.evidence_top_k,
            )
        else:
            structured_context = StructuredMechLibContext(
                modeling_context={
                    "matched_topics": [],
                    "concepts": [],
                    "law_schemas": [],
                    "problem_schemas": [],
                    "aliases": [],
                },
                proof_context={
                    "verified_decls": [],
                    "required_imports": [],
                    "proof_hints": [],
                    "proof_style_examples": [],
                },
                source_counts={},
            )
        stage_rows.setdefault("structured_mechlib_context.jsonl", []).append(
            structured_context_stage_row(sample.sample_id, structured_context)
        )
        structured_context_for_b = structured_context

        model_ir: ModelIR
        if module_a2 is not None:
            model_ir = module_a2.run(
                sample_id=sample.sample_id,
                problem_text=sample.problem_text,
                problem_ir=grounding.problem_ir,
                structured_mechlib_context=structured_context,
                image_description=sample.image_description,
            )
        else:
            model_ir = ModelIR(sample_id=sample.sample_id, parse_ok=False, error="model_ir_module_unavailable")
        stage_rows.setdefault("model_ir.jsonl", []).append(to_row(model_ir))
        model_ir_for_b = model_ir

        evidence_bindings: list[EvidenceBinding] = []
        if model_ir.parse_ok:
            evidence_bindings = EvidenceBinder(
                top_k=cfg.knowledge.evidence_top_k,
                lean_runner=getattr(module_c, "lean_runner", None),
                lean_check_decls=cfg.knowledge.lean_check_decls,
                run_dir=run_dir,
                lean_check_cache=lean_check_cache,
            ).bind(
                model_ir,
                structured_context,
                problem_text=sample.problem_text,
                problem_ir=grounding.problem_ir,
            )
        stage_rows.setdefault("evidence_bindings.jsonl", []).extend(
            evidence_binding_stage_rows(sample.sample_id, evidence_bindings)
        )
        evidence_bindings_for_b = evidence_bindings

    stage_rows["mechlib_retrieval.jsonl"].append(
        {
            "sample_id": sample.sample_id,
            "enabled": bool(retriever and cfg.statement.with_mechlib_context),
            "retrieved_count": int(mechlib_pack.get("summary_items_count", 0))
            + int(mechlib_pack.get("verified_decl_items_count", 0))
            + int(mechlib_pack.get("schema_items_count", 0))
            + int(mechlib_pack.get("alias_items_count", 0))
            + int(mechlib_pack.get("source_items_count", 0)),
            "domain_from_a": mechlib_pack.get("domain_from_a", []),
            "selected_tags": mechlib_pack.get("selected_tags", []),
            "summary_items_count": mechlib_pack.get("summary_items_count", 0),
            "verified_decl_items_count": mechlib_pack.get("verified_decl_items_count", 0),
            "schema_items_count": mechlib_pack.get("schema_items_count", 0),
            "alias_items_count": mechlib_pack.get("alias_items_count", 0),
            "source_items_count": mechlib_pack.get("source_items_count", 0),
            "final_context_chars": mechlib_pack.get("final_context_chars", 0),
            "gap_schema_only": mechlib_pack.get("gap_schema_only", False),
            "items": mechlib_items,
            "summary_items": summary_items,
            "verified_decl_items": verified_decl_items,
            "schema_items": schema_items,
            "alias_items": alias_items,
            "import_hints": mechlib_pack.get("import_hints", []),
            "law_matched_items": mechlib_pack.get("law_matched_items", []),
            "proof_style_examples": mechlib_pack.get("proof_style_examples", []),
            "retrieval_context": mechlib_context,
        }
    )

    if not grounding.parse_ok:
        summary = SampleRunSummary(
            sample_id=sample.sample_id,
            grounding_ok=False,
            statement_generation_ok=False,
            compile_ok=False,
            semantic_ok=False,
            proof_ok=False,
            end_to_end_ok=False,
            final_error_type=grounding.error or "visual_grounding_failure",
            notes="module A failed",
            final_round_index=0,
            feedback_loop_used=False,
            sub_error_type=grounding.error or "visual_grounding_failure",
            failure_summary=grounding.error or "module A failed",
            failure_details={"grounding_error": grounding.error, "parse_ok": grounding.parse_ok},
        )
        return {
            "stage_rows": stage_rows,
            "grounding_rows": grounding_rows,
            "compile_rows": compile_rows,
            "semantic_rows": semantic_rows,
            "proof_rows": proof_rows,
            "summary": summary,
        }

    feedback_loop_used = False
    final_round_index = 0
    max_revision_rounds = cfg.statement.max_revision_rounds if cfg.statement.feedback_loop_enabled else 0
    current_round_index = 0
    revision_feedback = "(none)"
    current_start_stage = "Sketch"
    previous_candidates: list[StatementCandidate] | None = None
    previous_sketch: ControlledSketch | None = None

    while True:
        candidates, compile_results, semantic = _run_statement_round(
            round_index=current_round_index,
            grounding=grounding,
            mechlib_context=mechlib_context,
            revision_feedback=revision_feedback,
            previous_candidates=previous_candidates,
            previous_sketch=previous_sketch,
            start_stage=current_start_stage,
        )

        retry_reason: str | None = None
        failure_route: FailureRoute | None = None
        if current_round_index < max_revision_rounds:
            if cfg.statement.generation_mode == "minimal_skeleton":
                if cfg.statement.minimal_feedback_scope != "none":
                    failure_route = build_failure_route(
                        sample_id=sample.sample_id,
                        round_index=current_round_index,
                        candidates=candidates,
                        compile_results=compile_results,
                        semantic=semantic,
                    )
                    if failure_route is not None:
                        failure_route = apply_minimal_feedback_scope(
                            failure_route,
                            cfg.statement.minimal_feedback_scope,
                        )
                retry_reason = failure_route.retry_reason if failure_route else None
            else:
                if not any(r.compile_pass for r in compile_results):
                    retry_reason = "no_compile_pass"
                elif not semantic.semantic_pass:
                    retry_reason = "semantic_fail"

        if retry_reason:
            feedback_loop_used = True
            semantic.retry_triggered = True
            semantic.retry_reason = retry_reason
            if failure_route is not None:
                stage_rows.setdefault("failure_routes.jsonl", []).append(to_row(failure_route))
                semantic.retry_feedback_summary = json.dumps(
                    failure_route.feedback_payload,
                    ensure_ascii=False,
                    indent=2,
                )
            else:
                semantic.retry_feedback_summary = build_revision_feedback(
                    retry_reason=retry_reason,
                    candidates=candidates,
                    compile_results=compile_results,
                    semantic=semantic,
                )
        else:
            semantic.retry_triggered = False
            semantic.retry_reason = None
            semantic.retry_feedback_summary = None

        semantic_rows.append(semantic)
        stage_rows["semantic_rank.jsonl"].append(to_row(semantic))

        if not retry_reason:
            final_round_index = current_round_index
            break

        previous_candidates = candidates
        previous_sketch = controlled_sketch_for_b
        revision_feedback = semantic.retry_feedback_summary or "(none)"
        current_start_stage = failure_route.start_stage if failure_route is not None else "B"
        current_round_index += 1

    statement_generation_ok = len(candidates) > 0
    compile_ok = any(r.compile_pass for r in compile_results)
    selected_candidate = None
    if semantic.selected_candidate_id:
        selected_candidate = next((c for c in candidates if c.candidate_id == semantic.selected_candidate_id), None)

    e_context = mechlib_context if "E" in inject_set else "(none)"
    if not semantic.semantic_pass:
        proof_attempts = []
        proof_check = ProofCheckResult(
            sample_id=grounding.sample_id,
            proof_success=False,
            attempts_used=0,
            selected_candidate_id=semantic.selected_candidate_id,
            error_type="proof_skipped_due_to_semantic_fail",
            final_log_path=None,
            backend_used=semantic.selected_backend,
            round_index=final_round_index,
            sub_error_type="proof_skipped_due_to_semantic_fail",
            failure_tags=["proof_skipped_due_to_semantic_fail"],
            failure_summary="Proof stage skipped because semantic ranking failed.",
            failure_details={
                "semantic_error_type": semantic.error,
                "semantic_sub_error_type": semantic.sub_error_type,
                "semantic_failure_summary": semantic.failure_summary,
            },
        )
    else:
        proof_attempts, proof_check = module_e.run(
            grounding=grounding,
            selected_candidate=selected_candidate,
            run_dir=run_dir,
            mechlib_context=e_context,
        )
        proof_check.round_index = final_round_index
        for attempt in proof_attempts:
            if attempt.proof_search_trace:
                trace_row = dict(attempt.proof_search_trace)
                trace_row["round_index"] = final_round_index
                stage_rows.setdefault("proof_search_trace.jsonl", []).append(trace_row)
            if attempt.proof_action_checks:
                action_rows = []
                for row in attempt.proof_action_checks:
                    payload = dict(row)
                    payload["round_index"] = final_round_index
                    action_rows.append(payload)
                stage_rows.setdefault("proof_action_checks.jsonl", []).extend(action_rows)
            if attempt.proof_strategy_prompts:
                prompt_rows = []
                for row in attempt.proof_strategy_prompts:
                    payload = dict(row)
                    payload["round_index"] = final_round_index
                    prompt_rows.append(payload)
                stage_rows.setdefault("proof_strategy_prompts.jsonl", []).extend(prompt_rows)
            if attempt.dependency_audit:
                audit_row = dict(attempt.dependency_audit)
                audit_row["round_index"] = final_round_index
                stage_rows.setdefault("proof_dependency_audit.jsonl", []).append(audit_row)

    proof_rows.append(proof_check)
    stage_rows["proof_attempts.jsonl"].extend(to_row(a) for a in proof_attempts)
    stage_rows["proof_checks.jsonl"].append(to_row(proof_check))

    end_to_end = (
        grounding.parse_ok
        and statement_generation_ok
        and compile_ok
        and semantic.semantic_pass
        and proof_check.proof_success
    )
    final_error: str | None = None
    final_sub_error: str | None = None
    final_failure_summary: str | None = None
    final_failure_details: dict[str, object] = {}
    if not end_to_end:
        compile_error = next((r.error_type for r in compile_results if not r.compile_pass), None)
        compile_failure_row = next((r for r in compile_results if not r.compile_pass), None)
        if not grounding.parse_ok:
            final_error = grounding.error or "visual_grounding_failure"
            final_sub_error = grounding.error or "visual_grounding_failure"
            final_failure_summary = grounding.error or "module A failed"
            final_failure_details = {"grounding_error": grounding.error, "parse_ok": grounding.parse_ok}
        elif not statement_generation_ok:
            final_error = "statement_generation_parse_failed"
            final_sub_error = "statement_generation_parse_failed"
            final_failure_summary = "Statement generation did not produce any usable candidates."
            final_failure_details = {"candidate_count": len(candidates)}
        elif not compile_ok:
            final_error = compile_error or "elaboration_failure"
            final_sub_error = compile_failure_row.sub_error_type if compile_failure_row else None
            final_failure_summary = compile_failure_row.failure_summary if compile_failure_row else None
            final_failure_details = compile_failure_row.failure_details if compile_failure_row else {}
        elif not semantic.semantic_pass:
            final_error = semantic.error or "semantic_drift"
            final_sub_error = semantic.sub_error_type
            final_failure_summary = semantic.failure_summary
            final_failure_details = semantic.failure_details
        else:
            final_error = proof_check.error_type or "proof_search_failure"
            final_sub_error = proof_check.sub_error_type
            final_failure_summary = proof_check.failure_summary
            final_failure_details = proof_check.failure_details

    summary = SampleRunSummary(
        sample_id=sample.sample_id,
        grounding_ok=grounding.parse_ok,
        statement_generation_ok=statement_generation_ok,
        compile_ok=compile_ok,
        semantic_ok=semantic.semantic_pass,
        proof_ok=proof_check.proof_success,
        end_to_end_ok=end_to_end,
        final_error_type=final_error,
        notes=None,
        final_round_index=final_round_index,
        feedback_loop_used=feedback_loop_used,
        sub_error_type=final_sub_error,
        failure_summary=final_failure_summary,
        failure_details=final_failure_details,
    )
    return {
        "stage_rows": stage_rows,
        "grounding_rows": grounding_rows,
        "compile_rows": compile_rows,
        "semantic_rows": semantic_rows,
        "proof_rows": proof_rows,
        "summary": summary,
    }


def execute_samples(
    *,
    cfg: PipelineConfig,
    samples,
    run_dir: Path,
    prompt_dir: Path,
    inject_set: set[str],
    retriever: MechLibRetriever | None,
    preflight_ok: bool,
    preflight_error: str | None,
    preflight_message: str,
    stage_row_files: tuple[str, ...],
    emit_console_line: Callable[[str], None],
    build_worker_modules: Callable[[PipelineConfig, Path], tuple[Any, ...]],
    build_revision_feedback: Callable[..., str],
) -> ExecutionResult:
    stage_rows = new_stage_rows(stage_row_files)
    grounding_rows: list[GroundingResult] = []
    compile_rows: list[CompileCheckResult] = []
    semantic_rows: list[SemanticRankResult] = []
    proof_rows: list[ProofCheckResult] = []
    summaries: list[SampleRunSummary] = []
    lean_check_cache = LeanDeclCheckCache() if cfg.knowledge.lean_check_decls else None
    total_samples = len(samples)
    sample_concurrency = min(cfg.runtime.sample_concurrency, total_samples) if total_samples else 1
    ordered_worker_results: list[ProcessSampleResult | None] = [None] * total_samples
    completed_samples = 0
    for idx, sample in enumerate(samples, start=1):
        emit_console_line(f"[{idx}/{total_samples}] sample={sample.sample_id}")
    emit_console_line(f"progress: 0/{total_samples} completed, sample_concurrency={sample_concurrency}")

    process_kwargs = {
        "cfg": cfg,
        "run_dir": run_dir,
        "prompt_dir": prompt_dir,
        "inject_set": inject_set,
        "retriever": retriever,
        "preflight_ok": preflight_ok,
        "preflight_error": preflight_error,
        "preflight_message": preflight_message,
        "stage_row_files": stage_row_files,
        "build_worker_modules": build_worker_modules,
        "build_revision_feedback": build_revision_feedback,
        "lean_check_cache": lean_check_cache,
    }

    if sample_concurrency <= 1:
        for idx, sample in enumerate(samples):
            try:
                result = process_sample(sample=sample, **process_kwargs)
            except Exception:
                emit_console_line(f"progress: failed after {completed_samples}/{total_samples} completed, sample={sample.sample_id}")
                raise
            ordered_worker_results[idx] = result
            _append_completed_sample_rows(run_dir=run_dir, stage_row_files=stage_row_files, result=result)
            completed_samples += 1
            emit_console_line(f"progress: {completed_samples}/{total_samples} completed, sample={sample.sample_id}")
    else:
        futures: dict[Future[ProcessSampleResult], tuple[int, str]] = {}
        executor = ThreadPoolExecutor(max_workers=sample_concurrency, thread_name_prefix="sample")
        try:
            for idx, sample in enumerate(samples):
                future = executor.submit(process_sample, sample=sample, **process_kwargs)
                futures[future] = (idx, sample.sample_id)
            for future in as_completed(futures):
                idx, sample_id = futures[future]
                try:
                    result = future.result()
                except Exception:
                    emit_console_line(f"progress: failed after {completed_samples}/{total_samples} completed, sample={sample_id}")
                    executor.shutdown(wait=False, cancel_futures=True)
                    raise
                ordered_worker_results[idx] = result
                _append_completed_sample_rows(run_dir=run_dir, stage_row_files=stage_row_files, result=result)
                completed_samples += 1
                emit_console_line(f"progress: {completed_samples}/{total_samples} completed, sample={sample_id}")
        except Exception:
            executor.shutdown(wait=False, cancel_futures=True)
            raise
        else:
            executor.shutdown(wait=True)

    emit_console_line(f"progress: {completed_samples}/{total_samples} completed")

    worker_results = [result for result in ordered_worker_results if result is not None]
    for result in worker_results:
        result_stage_rows = result["stage_rows"]
        for name in stage_row_files:
            if name == "sample_summary.jsonl":
                continue
            stage_rows[name].extend(result_stage_rows.get(name, []))
        grounding_rows.extend(result["grounding_rows"])
        compile_rows.extend(result["compile_rows"])
        semantic_rows.extend(result["semantic_rows"])
        proof_rows.extend(result["proof_rows"])
        summaries.append(result["summary"])

    stage_rows["sample_summary.jsonl"] = [to_row(s) for s in summaries]
    return {
        "stage_rows": stage_rows,
        "grounding_rows": grounding_rows,
        "compile_rows": compile_rows,
        "semantic_rows": semantic_rows,
        "proof_rows": proof_rows,
        "summaries": summaries,
        "sample_concurrency": sample_concurrency,
        "lean_decl_check_cache_stats": lean_check_cache.stats() if lean_check_cache is not None else {},
    }
