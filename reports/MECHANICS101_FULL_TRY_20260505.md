# Mechanics101 Full Run Try（2026-05-05）

## Command

```bash
.venv/bin/python -m mech_pipeline.cli run \
  --config configs/mechanics101_proxy_gpt54_20260409.yaml \
  --sample-concurrency 5 \
  --tag mechanics101-full-try-20260505
```

The run used the existing config:

- dataset: Lean4Phys mechanics, `limit=101`
- model: `gpt-5.4`
- base URL: `https://api.openai-proxy.org`
- API key source: environment variable
- generation mode: legacy candidate
- run dir: `runs/20260505_124521_mechanics101-full-try-20260505`

No API key is stored in this report.

## Result

The full 101-sample run completed with exit code 0.

Preflight:

```text
lean_preflight=True, message=ok: physlean (mechlib unavailable)
environment_health=clean, warnings=0
```

## Metrics

| Metric | Value |
| --- | ---: |
| `num_total_samples` | 101 |
| `grounding_success_rate` | 0.970297 |
| `statement_generation_success_rate` | 0.940594 |
| `lean_compile_success_rate` | 0.936842 |
| `semantic_consistency_pass_rate` | 0.47191 |
| `proof_success_rate` | 0.27551 |
| `end_to_end_verified_solve_rate` | 0.267327 |
| `mechlib_header_rate` | 1.0 |
| `mechlib_compile_pass_rate` | 0.872093 |
| `selected_mechlib_candidate_rate` | 1.0 |
| `statement_mechlib_usage_rate` | 0.218023 |
| `selected_statement_mechlib_usage_rate` | 0.157303 |
| `proof_mechlib_usage_rate` | 0.15 |
| `library_grounded_selection_rate` | 0.157303 |
| `feedback_loop_used_rate` | 0.772277 |

Minimal skeleton metrics are `null` because this config uses legacy candidate mode.

## Counts

| Item | Count |
| --- | ---: |
| `problem_ir.jsonl` | 101 |
| `mechlib_retrieval.jsonl` | 101 |
| `statement_candidates.jsonl` | 622 |
| `compile_checks.jsonl` | 622 |
| `semantic_rank.jsonl` | 176 |
| `proof_attempts.jsonl` | 66 |
| `proof_checks.jsonl` | 98 |
| `sample_summary.jsonl` | 101 |
| end-to-end solved samples | 27 |
| grounding ok samples | 98 |
| statement generation ok samples | 95 |
| compile ok samples | 89 |
| semantic ok samples | 42 |
| proof ok samples | 27 |

## Failure Distribution

Final error distribution:

| Error | Count |
| --- | ---: |
| `semantic_drift` | 47 |
| none | 27 |
| `proof_search_failure` | 15 |
| `elaboration_failure` | 6 |
| `statement_generation_parse_failed` | 3 |
| `wrong_target_extraction` | 3 |

Compile checks:

| Error | Count |
| --- | ---: |
| none | 500 |
| `elaboration_failure` | 122 |

Compile sub errors:

| Sub error | Count |
| --- | ---: |
| none | 500 |
| `type_mismatch` | 107 |
| `empty_stderr_timeout` | 15 |

Proof checks:

| Error | Count |
| --- | ---: |
| `proof_skipped_due_to_semantic_fail` | 56 |
| none | 27 |
| `proof_search_failure` | 15 |

## Comparison With Historical Reports

| Metric | 2026-04-05 baseline | no-MechLib retrieval | 2026-05-05 full try |
| --- | ---: | ---: | ---: |
| `grounding_success_rate` | 0.970297 | 0.980198 | 0.970297 |
| `lean_compile_success_rate` | 0.886427 | 0.926316 | 0.936842 |
| `semantic_consistency_pass_rate` | 0.765957 | 0.590909 | 0.47191 |
| `proof_success_rate` | 0.428571 | 0.323232 | 0.27551 |
| `end_to_end_verified_solve_rate` | 0.415842 | 0.316832 | 0.267327 |
| end-to-end count | 42 / 101 | 32 / 101 | 27 / 101 |

Interpretation:

- Compile rate improved relative to both historical baselines.
- Semantic pass and proof success are lower than both historical baselines.
- The dominant failure class is semantic drift, not compile failure.
- Feedback loop was used on 78 / 101 samples.

## Notes

This run confirms the 101-sample legacy pipeline remains runnable end to end with the current codebase. It does not exercise the minimal skeleton front half because the selected config does not set `statement.generation_mode=minimal_skeleton`.
