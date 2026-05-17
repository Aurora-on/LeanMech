# Low-success preproof rerun classification

Date: 2026-05-17

Source run:

- `runs/20260517_193624_preproof-low18-route-rerun-20260517`

Success archive:

- `outputs/success_proof`

## Success samples moved

The successful samples were copied into `outputs/success_proof` as sample-scoped audit folders. The original run directories were not deleted or modified.

| sample_id | source run | note |
|---|---|---|
| `lean4phys-university_mechanics_Mechanics_74_University` | `runs/20260517_191254_pass4-highprob-e-20260517` | proof success from earlier high-probability E run |
| `archive_part1-archive_part1_10_8` | `runs/20260517_195248_pass4-e-fix-check-20260517` | proof success after E-stage fixes |
| `lean4phys-university_mechanics_Mechanics_73_University` | `runs/20260517_200727_pass4-e-fix-mech73-20260517` | proof success, classified conservatively as gap-assisted rather than fully MechLib verified |
| `archive_part1-archive_part1_10_2` | `runs/20260517_193624_preproof-low18-route-rerun-20260517` | proof success in the updated low18 rerun, legacy full-proof mode |

## Updated low18 run summary

The rerun contains 18 samples. Based on `sample_summary.jsonl`:

- compile ok: 14 / 18
- semantic ok: 10 / 18
- proof ok: 1 / 18
- semantic drift: 4 / 18
- elaboration failure before proof: 4 / 18

This run used legacy full-proof mode for proof attempts, not the newer step-checked LLM-guided E search.

## Reclassification

### Already succeeded

| sample_id | classification | reason |
|---|---|---|
| `archive_part1-archive_part1_10_2` | succeeded, archive only | Lean proof replay passed in legacy mode for the selected symbolic drag-force theorem. It should be kept as proof-success evidence, but not treated as fully MechLib verified because no proof dependency audit is present in this legacy run. |

### High priority for current E rerun

| sample_id | classification | reason |
|---|---|---|
| `lean4phys-university_mechanics_Mechanics_31_University` | high probability | Target is direct scalar algebra from `v_top^2 = v0^2 + 2*a_y*delta_y`, `v_top=0`, `a_y=-g`, `delta_y=h_max`, and `g=49/5`. The previous failure was a timeout from an overly heavy proof script, not an apparent modeling gap. |
| `lean4phys-university_mechanics_Mechanics_71_University` | medium-high probability | Target follows from incline force balance plus Newton equation, but the theorem needs positive/nonzero mass handling to cancel `m.val`. Current E physical-assumption augmentation may make this feasible. |
| `lean4phys-competition_mechanics_Ch2_Q1` | medium-high probability | Final selected theorem contains capstan saturation and bucket force-balance equations. The proof needs controlled cancellation, positivity by cases for `g`, and `Real.log_exp`/exponential inversion. This is an E algebra/transcendental planner issue, not an obvious upstream target gap. |

### Possible, but needs targeted E improvements

| sample_id | classification | blocking issue |
|---|---|---|
| `archive_part1-archive_part1_11_1` | medium-low | Requires differentiating trig trajectories and simplifying angular momentum. Current E lacks a reliable derivative/trig local planner; LLM attempted invalid rewrites. |
| `lean4phys-university_mechanics_Mechanics_3_University` | low-to-medium after upstream check | The theorem gives the position law only on `0 <= t <= 4`, but the target asks for a derivative statement on the closed interval. Endpoint derivative facts are not justified by a closed-interval pointwise formula alone. Prefer upstream strengthening to a global/local-neighborhood position law or an explicit velocity equation. |
| `archive_part1-archive_part1_6_6` | low-to-medium after side-condition repair | The intended result rewrites a square-root magnitude into `2*a*sqrt(...)`. This needs sign and nonzero-radius assumptions such as `0 <= a.val` and `R.val ≠ 0`; otherwise the statement is not generally derivable. |

### Low probability or upstream-blocked

| sample_id | classification | reason |
|---|---|---|
| `archive_part1-archive_part1_11_4` | upstream/MechLib blocked | The target asserts a full exponential ODE solution and half-life from rotational drag equations. This requires a verified ODE solution theorem, not only local algebra. |
| `archive_part1-archive_part1_12_1` | upstream-blocked | The target includes `W_M = 8*pi^2`, but the theorem only has the torque law `M phi = 4*phi`; it lacks a work-integral relation connecting torque to `W_M`. |
| `archive_part1-archive_part1_9_11` | semantic-blocked | Semantic rank reports distance/displacement mismatch and missing derivative laws; proof should remain skipped. |
| `lean4phys-university_mechanics_Mechanics_16_University` | semantic-blocked | The selected target is component-only and lacks the acceleration-as-derivative grounding needed for the original vector acceleration statement. |
| `lean4phys-competition_mechanics_Ch3_Q1` | semantic-blocked | Correct-looking formula, but missing the definition/verification that `v_max` is the actual maximum speed after removal. |
| `archive_part1-archive_part1_11_9` | upstream/MechLib blocked | Requires damped rotational ODE integration and revolution count; current skeleton has derivative relations but no verified solution/integral theorem. |
| `archive_part1-archive_part1_13_3` | compile/upstream-blocked | No compile-passed semantic candidate; current theorem has final mass/acceleration formulas without enough statics/dynamics support. |
| `archive_part2-archive_part2_1_9` | semantic-blocked | Semantic rank reports an unstated small-angle SHM translation for a cycloid problem. |
| `archive_part2-archive_part2_4_5` | compile/upstream-blocked | No compile-passed semantic candidate and sparse theorem hypotheses. |
| `archive_part2-archive_part2_6_6` | compile/upstream-blocked | Rocket/log formulas and mass evolution are asserted without a proof-friendly dynamics bridge; compile failed before proof. |
| `archive_part1-archive_part1_12_7` | compile/upstream-blocked | Selected theorem degenerates to `False`; should not enter E or natural-language solution generation. |

## Recommended next E batch

Run only these first:

1. `lean4phys-university_mechanics_Mechanics_31_University`
2. `lean4phys-university_mechanics_Mechanics_71_University`
3. `lean4phys-competition_mechanics_Ch2_Q1`

Do not spend API budget on the upstream-blocked group until the corresponding skeleton/proof-obligation gaps are corrected. For the medium-low group, first add or verify targeted E support:

- derivative/trig local plan for `archive_part1-archive_part1_11_1`
- explicit position/velocity domain repair for `Mechanics_3`
- sign/nonzero side-condition repair for `archive_part1_6_6`

## Failure diagnosis

The failures are mixed:

- LLM-performance or prompt issue: `Mechanics_31` mainly timed out due to a heavy proof body; it should be recoverable with shorter algebra facts.
- E-flow capability issue: `Mechanics_71` and `Ch2_Q1` need better side-condition/cancellation/transcendental algebra planning.
- Upstream theorem issue: `12_1`, `11_4`, `11_9`, `6_6`, `Mechanics_3`, and the semantic/compile-blocked samples need stronger or corrected skeletons before E should spend search budget.

The key operational rule remains: samples with semantic failure, compile failure, or degenerate targets like `: False` should not proceed to E proof search or downstream readable-solution rendering.
