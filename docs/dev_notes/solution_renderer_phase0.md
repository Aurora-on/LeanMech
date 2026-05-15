# SolutionRenderer Phase 0 Notes

## Available E-After Inputs

The current pipeline already writes the core artifacts needed by a readable solution renderer:

- `problem_ir.jsonl`: `GroundingResult` rows with `problem_ir`.
- `model_ir.jsonl`: minimal-mode `ModelIR` rows when A2 succeeds.
- `controlled_sketch.jsonl`: `ControlledSketch` rows with proof-step order, algebra obligation, model interface instantiations, and blocked law steps.
- `theorem_skeleton_candidates.jsonl`: minimal theorem candidates with `proof_obligations`, `verified_decls`, `hypothesis_provenance`, `gap_laws`, and optional embedded `controlled_sketch`.
- `proof_attempts.jsonl`: E attempts, including `proof_mode`, final proof body excerpts/bodies, optional embedded `proof_search_trace`, and optional `dependency_audit`.
- `proof_checks.jsonl`: final E status, including skipped/failed/success states and optional embedded trace/audit.
- `proof_search_trace.jsonl`: accepted/rejected checked proof actions when `llm_guided_search` records trace rows.
- `proof_dependency_audit.jsonl`: audit classification for verified declaration and obligation coverage when available.

## Artifacts That May Be Empty

Recent runs show that `proof_search_trace.jsonl` and `proof_dependency_audit.jsonl` can be empty even when E runs. This happens when E falls back to legacy full-proof mode, when proof is skipped after semantic failure, or when a run is interrupted before final rows are flushed. `proof_attempts.jsonl` may also be empty for proof-skipped samples.

The renderer must therefore prefer explicit trace/audit rows when present, then fall back to embedded `ProofAttemptResult` / `ProofCheckResult` fields, and finally produce a conservative partial solution from skeleton and proof status only.

## Orchestrator Insertion Point

`SolutionRenderer` should run immediately after `ModuleE.run(...)` or after the proof-skipped `ProofCheckResult` is constructed, before `SampleRunSummary` is created. This lets it emit a partial readable solution for:

- proof success,
- proof failure,
- proof skipped due to semantic failure.

It should not change C/D/E behavior, selected-candidate logic, or legacy fallback behavior.

## Reusable Rendering Code

`rendering.py` already builds run README sections from `stage_rows`, groups rows by sample and round, truncates long text with `truncate(...)`, and writes Lean exports. It does not currently produce a structured readable solution. The reusable pieces are row grouping, truncation, and README section formatting.

## Proposed New Outputs

The single renderer stage should write three JSONL artifacts:

- `solution_trace.jsonl`: structured `SolutionTrace` rows.
- `natural_solution.jsonl`: rendered natural-language solution rows, including proof status and raw LLM response if any.
- `solution_render_audit.jsonl`: audit rows for formula coverage, law-step coverage, unsupported formulas, gap disclosure, and proof-status disclosure.

These rows should be included in both `runs/<run>/` and `outputs/latest/` through the existing `stage_rows` archive writer.
