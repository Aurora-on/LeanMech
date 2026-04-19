# Baseline V1 Analysis

## Runtime Environment
- environment_health: clean
- environment_warnings_count: 0

## Metrics
- num_total_samples: 14
- grounding_success_rate: 0.785714
- statement_generation_success_rate: 0.785714
- lean_compile_success_rate: 1.0
- semantic_consistency_pass_rate: 0.454545
- proof_success_rate: 0.363636
- end_to_end_verified_solve_rate: 0.285714
- mechlib_header_rate: 1.0
- mechlib_compile_pass_rate: 0.970588
- selected_mechlib_candidate_rate: 1.0
- statement_mechlib_usage_rate: 0.088235
- selected_statement_mechlib_usage_rate: 0.0
- proof_mechlib_usage_rate: 0.0
- library_grounded_selection_rate: 0.0
- feedback_loop_used_rate: 0.714286

## Feedback Loop
- feedback_loop_used_count: 10
- feedback_loop_success_count: 3

## Error Distribution
- semantic_drift: 6
- wrong_target_extraction: 3
- proof_search_failure: 1

## Sub Error Distribution
- trivial_goal: 4
- wrong_target_extraction: 3
- wrong_target: 2
- type_mismatch: 1

## Compile Sub Error Distribution
- type_mismatch: 18
- empty_stderr_timeout: 1

## Proof Sub Error Distribution
- proof_skipped_due_to_semantic_fail: 6
- type_mismatch: 1

## Semantic Mismatch Fields
- unknown_target: 6
- physical_laws: 5
- known_quantities: 3
- constraints: 2

## Representative Failed Samples
- sample_ids: ['lean4phys-theoretical_mechanics_momentum_theorem_basic_01', 'lean4phys-theoretical_mechanics_kinetic_energy_theorem_complex_04', 'lean4phys-theoretical_mechanics_angular_momentum_theorem_complex_06', 'lean4phys-theoretical_mechanics_moment_of_momentum_theorem_basic_07', 'lean4phys-theoretical_mechanics_moment_of_momentum_theorem_complex_08', 'lean4phys-theoretical_mechanics_dalembert_principle_complex_10', 'lean4phys-theoretical_mechanics_lagrange_equation_basic_11', 'lean4phys-theoretical_mechanics_lagrange_equation_complex_12', 'lean4phys-theoretical_mechanics_mechanical_vibration_basic_13', 'lean4phys-theoretical_mechanics_mechanical_vibration_complex_14']

## Stage Log Files
- problem_ir.jsonl
- mechlib_retrieval.jsonl
- statement_candidates.jsonl
- compile_checks.jsonl
- semantic_rank.jsonl
- proof_attempts.jsonl
- proof_checks.jsonl
- sample_summary.jsonl
- metrics.json
- analysis.md
