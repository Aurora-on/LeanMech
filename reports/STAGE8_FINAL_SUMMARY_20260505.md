# Stage 8 Final Summary（2026-05-05）

## 1. Main Deliverables

The front-half minimal skeleton pipeline is implemented behind:

```yaml
statement:
  generation_mode: minimal_skeleton
```

Legacy candidate generation remains available through:

```yaml
statement:
  generation_mode: legacy_candidate
```

## 2. Main New Files

- `src/mech_pipeline/knowledge/mechlib_structured.py`
- `src/mech_pipeline/knowledge/evidence_binder.py`
- `src/mech_pipeline/modules/A2_model_ir.py`
- `src/mech_pipeline/modules/sketch_builder.py`
- `src/mech_pipeline/modules/sketch_audit.py`
- `prompts/A2_model_ir.txt`
- `prompts/controlled_sketch.txt`
- `prompts/B_generate_minimal_skeleton.txt`
- `prompts/README.md`
- `docs/minimal_skeleton_pipeline.md`
- `configs/smoke_minimal_skeleton.yaml`
- `configs/smoke_legacy_candidate.yaml`
- `configs/smoke_minimal_skeleton_gap.yaml`

## 3. Main Modified Files

- `src/mech_pipeline/types.py`
- `src/mech_pipeline/config.py`
- `src/mech_pipeline/llm_schemas.py`
- `src/mech_pipeline/model/mock.py`
- `src/mech_pipeline/modules/B_statement_gen.py`
- `src/mech_pipeline/orchestrator.py`
- `src/mech_pipeline/cli.py`
- `src/mech_pipeline/cli_ablate_no_mechlib.py`
- `src/mech_pipeline/rendering.py`
- `src/mech_pipeline/eval/metrics.py`
- `src/mech_pipeline/modules/F_report.py`

## 4. New Artifacts

Minimal skeleton runs write:

- `model_ir.jsonl`
- `structured_mechlib_context.jsonl`
- `evidence_bindings.jsonl`
- `controlled_sketch.jsonl`
- `sketch_audit.jsonl`
- `theorem_skeleton_candidates.jsonl`

These are written to `runs/<run>/` and mirrored by the existing archive writer to `outputs/latest/`.

## 5. New Metrics

- `model_ir_success_rate`
- `evidence_binding_success_rate`
- `verified_binding_rate`
- `gap_schema_only_rate`
- `sketch_audit_pass_rate`
- `skeleton_generation_success_rate`
- `derived_equation_hypothesis_violation_rate`
- `schema_as_proof_fact_violation_rate`
- `explicit_gap_law_rate`

Legacy runs can report these as `null`.

## 6. New Tests

- `tests/test_types_model_ir.py`
- `tests/test_config_minimal_skeleton.py`
- `tests/test_structured_mechlib_context.py`
- `tests/test_evidence_binder.py`
- `tests/test_model_ir_builder.py`
- `tests/test_schema_planner.py`
- `tests/test_controlled_sketch.py`
- `tests/test_sketch_audit.py`
- `tests/test_b_minimal_skeleton.py`
- `tests/test_b_no_derived_hypotheses.py`
- `tests/test_metrics_minimal_skeleton.py`
- `tests/test_orchestrator_minimal_skeleton_smoke.py`

Latest validation:

```text
.venv/bin/python -m pytest -q
114 passed in 2.92s
```

## 7. Design Summary

The new front half separates modeling from proof eligibility:

- schema, concept, problem schema, and alignment rows guide modeling only;
- verified declarations are the only proof-eligible MechLib references;
- missing declarations are recorded as `gap_schema_only`;
- B generates minimal theorem skeletons and provenance, not full proof content;
- law application expected claims remain in `proof_obligations` for future E-stage work.

## 8. Not In Scope

- E-stage LLM-guided proof-state search.
- Lean-Copilot-style proof search.
- Automatic addition of new MechLib declarations.
- Guarantee that every `gap_schema_only` relation is provable.
- Counting gap laws as verified MechLib use.

## 9. Follow-Up Entry Point

The next implementation step should teach E to consume:

- `proof_obligations`
- `verified_decls`
- `evidence_bindings`
- `controlled_sketch`
- `hypothesis_provenance`

That work should prove law application claims during proof search instead of moving those claims into B-stage theorem hypotheses.
