# E-Stage Proof Search Fixes on Pass4 Preproof Artifacts

Date: 2026-05-17

Base preproof directory: `outputs/pass4_semantic_preproof_20260516_215607`

## Purpose

This round addressed the failure modes observed in the high-probability E-stage replay:

1. Physical assumption augmentation split theorem targets incorrectly when the target contained Lean type ascriptions.
2. Side-condition discovery only scanned the final target and missed denominators introduced by accepted local facts.
3. LLM fact plans could overpack several `have` blocks into one action.
4. `tactic_no_goals` repair did not handle semicolon tactic chains.
5. Accepted repair prefixes kept stale fact-plan remainders.
6. Blocked proof obligations could still contaminate dependency audit accounting.

## Changed Files

- `src/mech_pipeline/modules/e_physical_assumption_augmenter.py`
  - Replaced final textual `rsplit(" : ", 1)` theorem target splitting with a top-level-colon scanner.
  - Prevents `(1 : Real)` and similar target-local type ascriptions from corrupting augmented theorem declarations.

- `src/mech_pipeline/modules/e_side_conditions.py`
  - Side-condition discovery now scans the target, current fact summaries, allowed local facts, and local binders.
  - This lets E detect denominators such as `g.val` after accepted substitutions introduce `/ g.val`.

- `src/mech_pipeline/modules/e_search_controller.py`
  - Splits overpacked fact-plan `have` blocks before Lean probing.
  - Adds semicolon-aware `tactic_no_goals` prefix repair.
  - Preserves independent dropped `have` blocks as pending actions when possible.
  - Drops stale fact-plan remainders after accepted repair and replans from the accepted prefix.
  - Improves claim-repair proof-block indentation for one-line nested `have ... := by` bodies.

- `src/mech_pipeline/modules/e_dependency_audit.py`
  - Treats blocked obligations as gap-assisted evidence, preventing accidental `fully_mechlib_verified` classification.

- `src/mech_pipeline/modules/E_prover.py`
  - Rebuilds the dependency-audit context from the final search trace so trace-blocked obligations are removed from active required obligations.

- Tests updated:
  - `tests/test_e_physical_assumption_augmenter.py`
  - `tests/test_e_side_condition_analyzer.py`
  - `tests/test_e_search_controller_basic.py`
  - `tests/test_e_dependency_audit.py`
  - `tests/test_e_mode_routing.py`

## Test Results

Focused E tests:

```bash
.venv/bin/python -m pytest tests/test_e_mode_routing.py tests/test_e_dependency_audit.py tests/test_e_search_controller_basic.py tests/test_e_physical_assumption_augmenter.py tests/test_e_side_condition_analyzer.py -q
```

Result: `53 passed`

Broader E-stage tests:

```bash
.venv/bin/python -m pytest tests/test_e_*.py -q
```

Result: `100 passed`

## Real API Rechecks

### Four-sample regression check

Run directory: `runs/20260517_195248_pass4-e-fix-check-20260517`

Command:

```bash
.venv/bin/python -m mech_pipeline.cli run-preproof-e \
  --preproof-dir outputs/pass4_semantic_preproof_20260516_215607 \
  --tag pass4-e-fix-check-20260517 \
  --sample-concurrency 2 \
  --api-key-env OPENAI_PROXY_KEY \
  --output-dir outputs/pass4_e_fix_check_latest \
  --sample-id archive_part1-archive_part1_10_4 \
  --sample-id archive_part1-archive_part1_11_23 \
  --sample-id lean4phys-university_mechanics_Mechanics_73_University \
  --sample-id archive_part1-archive_part1_10_8
```

Observed result:

- `archive_part1_10_8`: proof succeeded. This validates denominator discovery from accepted facts and physical positivity augmentation for the latent denominator.
- `archive_part1_11_23`: no longer fails before LLM search. The augmented theorem compiles, confirming the target-split fix. The sample still fails later in proof search.
- `Mechanics73`: still failed in this run because `hTfinal` used a semicolon tactic chain that closed early and then kept running extra tactics.
- `archive_part1_10_4`: still failed in target proof search after blocked obligations.

### Mechanics73 after semicolon repair

Run directory: `runs/20260517_200727_pass4-e-fix-mech73-20260517`

Result:

- Proof succeeded.
- Classification: `gap_assisted_success`
- `fully_mechlib_verified`: `false`
- Key accepted repair action: `llm_plan_3_2_repair_no_goals_2`

This validates semicolon-aware `tactic_no_goals` repair and repair-prefix replanning.

### 10_4 audit recheck

Run directory: `runs/20260517_201406_pass4-e-fix-10-4-audit-20260517`

Result:

- Proof still failed: `target_proof_failed_after_blocked_obligations`
- Dependency audit now reports:
  - `required_verified_decls: []`
  - `missing_required_decls: []`
  - `missing_obligations: []`
  - blocked obligations remain visible in `proof_search_trace.jsonl`

This validates that blocked obligations no longer pollute required verified declaration accounting.

## Remaining Failures

### `archive_part1_10_4`

Still fails after blocking three unusable obligations:

- `sk_mi1`: `from_hypothesis_missing`
- `sk_mi2`: `from_hypothesis_missing`
- `sk_mi3`: `from_hypothesis_missing`

The target is manually provable under augmented positivity assumptions, but the current LLM plan often jumps directly from the linear COM equation to `Delta_x = b / 4` using `nlinarith`, which cannot handle the required division/field normalization. This needs a stronger algebra fact planner, not more blind retries.

### `archive_part1_11_23`

The deterministic augmentation parser issue is fixed, but the proof remains search-limited. It now reaches LLM-guided proof search and fails after many local facts and repairs. This should be treated as the next proof-planning target, not as the same pre-LLM augmentation bug.

## Current Assessment

The changes improved replayability and audit correctness:

- One previously failing sample (`10_8`) now succeeds.
- `Mechanics73` now succeeds after semicolon-aware no-goals repair.
- `11_23` moves past deterministic augmentation failure.
- Blocked obligations no longer count as missing required verified declarations.

The remaining failures are no longer caused by invalid prefixes being accepted or by dependency-audit pollution. They are mostly algebra planning gaps and upstream proof-obligation binding quality issues.
