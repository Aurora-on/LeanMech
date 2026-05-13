# Stage 7 Regression Report（2026-05-05）

## 1. Commands

Full tests:

```bash
.venv/bin/python -m pytest -q
```

Result:

```text
114 passed in 5.16s
```

Smoke and regression runs:

```bash
.venv/bin/python -m mech_pipeline.cli run \
  --config configs/smoke_legacy_candidate.yaml \
  --limit 1 \
  --tag stage7-legacy-smoke-stable \
  --sample-concurrency 1

.venv/bin/python -m mech_pipeline.cli run \
  --config configs/smoke_minimal_skeleton.yaml \
  --limit 1 \
  --tag stage7-minimal-smoke \
  --sample-concurrency 1

.venv/bin/python -m mech_pipeline.cli run \
  --config configs/smoke_minimal_skeleton.yaml \
  --limit 3 \
  --tag minimal-skeleton-regression \
  --sample-concurrency 1

.venv/bin/python -m mech_pipeline.cli run \
  --config configs/smoke_minimal_skeleton_gap.yaml \
  --limit 1 \
  --tag stage7-minimal-gap-smoke \
  --sample-concurrency 1
```

Run directories:

- `runs/20260505_123900_stage7-legacy-smoke-stable`
- `runs/20260505_123645_stage7-minimal-smoke`
- `runs/20260505_123652_minimal-skeleton-regression`
- `runs/20260505_124048_stage7-minimal-gap-smoke`

## 2. Artifact Check

For the 3-sample minimal regression run, these files exist in `runs/20260505_123652_minimal-skeleton-regression/`. The same artifact set was mirrored into `outputs/latest/` after each run; after the final gap smoke, `outputs/latest/` points at `runs/20260505_124048_stage7-minimal-gap-smoke`.

- `problem_ir.jsonl`
- `model_ir.jsonl`
- `structured_mechlib_context.jsonl`
- `evidence_bindings.jsonl`
- `controlled_sketch.jsonl`
- `sketch_audit.jsonl`
- `statement_candidates.jsonl`
- `compile_checks.jsonl`
- `semantic_rank.jsonl`
- `metrics.json`
- `analysis.md`
- `README.md`

## 3. Metrics Summary

| Run | samples | statement gen | model IR | binding ok | verified binding | gap only | sketch audit | skeleton gen | derived violation | schema proof violation |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| legacy stable smoke | 1 | 1.0 | null | null | null | null | null | null | null | null |
| minimal smoke | 1 | 1.0 | 1.0 | 1.0 | 1.0 | 0.0 | 1.0 | 1.0 | 0.0 | 0.0 |
| minimal regression | 3 | 1.0 | 1.0 | 1.0 | 1.0 | 0.0 | 1.0 | 1.0 | 0.0 | 0.0 |
| minimal gap smoke | 1 | 1.0 | 1.0 | 0.0 | 0.0 | 1.0 | 1.0 | 1.0 | 0.0 | 0.0 |

The smoke configs used here set `lean.enabled=false`, so C emits `lean_disabled` rows. This verifies pipeline reachability and artifact generation, not Lean elaboration compatibility.

## 4. Per-Sample Diagnosis

### archive-1-1

- ModelIR generated: yes.
- model_instances: `mi1`, kind `constant_speed_kinematics`, schema `law.kinematics.constant_speed`, expected claim `s = v * t`.
- Evidence bindings: 8 proof-eligible rows in the 3-sample regression run. First bound declaration: `MechLib.Analytical.LagrangeEquation.eulerLagrange_iff_newton`.
- gap_schema_only: none in the verified-context regression run.
- B hypotheses: roles are `problem_fact`, `problem_fact`; no law application equation in ordinary hypotheses.
- proof_obligations: contains a `law_application` claim with verified declaration `MechLib.Analytical.LagrangeEquation.eulerLagrange_iff_newton`.
- skeleton audit: pass.
- C/D: C row emitted with `lean_disabled`; D row emitted with `semantic_drift`.

### archive-1-2

- ModelIR generated: yes.
- model_instances: `mi1`, kind `constant_speed_kinematics`, schema `law.kinematics.constant_speed`, expected claim `s = v * t`.
- Evidence bindings: 8 proof-eligible rows. First bound declaration: `MechLib.Kinematics.Verified.Kinematics.linear_constraint_velocity`.
- gap_schema_only: none in the verified-context regression run.
- B hypotheses: roles are `problem_fact`, `problem_fact`; no law application equation in ordinary hypotheses.
- proof_obligations: contains a `law_application` claim with verified declaration `MechLib.Kinematics.Verified.Kinematics.linear_constraint_velocity`.
- skeleton audit: pass.
- C/D: C row emitted with `lean_disabled`; D row emitted with `semantic_drift`.

### archive-1-3

- ModelIR generated: yes.
- model_instances: `mi1`, kind `constant_speed_kinematics`, schema `law.kinematics.constant_speed`, expected claim `s = v * t`.
- Evidence bindings: 8 proof-eligible rows. First bound declaration: `MechLib.Kinematics.Verified.Kinematics.linear_constraint_velocity`.
- gap_schema_only: none in the verified-context regression run.
- B hypotheses: roles are `problem_fact`, `problem_fact`; no law application equation in ordinary hypotheses.
- proof_obligations: contains a `law_application` claim with verified declaration `MechLib.Kinematics.Verified.Kinematics.linear_constraint_velocity`.
- skeleton audit: pass.
- C/D: C row emitted with `lean_disabled`; D row emitted with `semantic_drift`.

## 5. Gap Exposure Check

The no-knowledge minimal smoke run verifies that an unbound model instance is recorded as a gap:

- run: `runs/20260505_124048_stage7-minimal-gap-smoke`
- `evidence_bindings.jsonl`: `binding_status=gap_schema_only`, `verified_decl=null`, `proof_fact_allowed=false`
- `statement_candidates.jsonl`: `verified_decls=[]`
- `statement_candidates.jsonl`: `gap_laws` contains the controlled law step with `binding_status=gap_schema_only`
- `proof_obligations` keeps the law application expected claim with `verified_decl=null`
- `gap_schema_only_rate=1.0`

This confirms the pipeline exposes missing verified declarations instead of inventing a MechLib theorem.

## 6. Failure Categories

- corpus read failure: not observed.
- EvidenceBinder matching failure: not observed in the verified-context regression run; intentionally observed in the no-knowledge gap smoke as `gap_schema_only`.
- LLM JSON parse failure: not observed with mock model.
- skeleton audit fail: not observed.
- C statement check incompatibility: not assessed because smoke configs disable Lean; C still emitted rows.
- legacy regression: not observed with `configs/smoke_legacy_candidate.yaml`. The older `configs/smoke_mock_local_text.yaml` enables the revision loop by default, which is not a stable one-sample legacy smoke target when Lean is disabled.

## 7. Conclusion

Legacy mode remains runnable through an explicit legacy smoke config. Minimal skeleton mode reaches B/C/D and writes the new front-half artifacts. Verified declarations stay in `proof_obligations`, not ordinary hypotheses. Missing declarations are surfaced as `gap_schema_only` with `proof_fact_allowed=false`.
