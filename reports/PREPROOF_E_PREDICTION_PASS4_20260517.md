# Preproof E Prediction for pass4_semantic_preproof_20260516_215607

## Scope

- Input snapshot: `outputs/pass4_semantic_preproof_20260516_215607`
- Eligible selected theorems inspected: 29
- Stage boundary: A-D artifacts are treated as fixed; this prediction only estimates E-stage proof feasibility.
- API use: none.

## Method

I inspected `eligible_samples.jsonl`, `selected_candidates.jsonl`, `selected_compile_checks.jsonl`, and `selected_semantic_rank.jsonl`.

The first attempt at a generic multi-strategy Lean algebra probe was stopped because the first sample already made `ring_nf`/field-style probing run longer than expected. To avoid turning the prediction pass into an expensive proof run, the final classification below is static and structural:

- whether the target is a direct algebraic consequence of theorem hypotheses;
- whether the target needs missing side conditions such as nonzero denominators or positivity;
- whether it contains `forall`, `deriv`, `Real.sin`, `Real.cos`, `Real.sqrt`, `Real.log`, or ODE/integration content;
- whether target-only quantities appear without a linking hypothesis;
- whether proof obligations / verified declarations are available, and whether success would still be gap-assisted.

This is a prediction, not a certified proof result.

## Summary

| Bucket | Count | Meaning |
|---|---:|---|
| High | 5 | Likely closable by target proof from available hypotheses, usually algebra plus side-condition handling. |
| Medium | 6 | Plausibly closable but brittle: needs nonzero side conditions, trig/sqrt reasoning, or stronger local planning. |
| Low | 18 | Very likely not closable from current theorem hypotheses; missing model equations, derivative/integration facts, branch facts, or target-only quantities. |

Important provenance note: every selected theorem in this snapshot has `fully_mechlib_verified = false`. Therefore a successful E proof should still be classified conservatively, typically `gap_assisted_success` or `algebra_only_success`, unless the final proof actually uses accepted verified declarations.

## High Probability

| Sample | Why it is likely |
|---|---|
| `archive_part1-archive_part1_10_4` | Center-of-mass displacement relation is algebraic from `given_mass_relation`, relative shift, and `Delta_x` definitions. Needs denominator/positive-mass handling for the ratio form. |
| `archive_part1-archive_part1_11_23` | Engine torque target follows from explicit torque, inertia, angular-acceleration, and angle-time equations. Main risk is denominator side conditions for `d_A` and `t`, both numerically fixed. |
| `lean4phys-university_mechanics_Mechanics_73_University` | Same structure as the earlier successful Atwood/glider sample: two linear force equations imply `a` and `T`; needs positive mass denominator side condition. |
| `lean4phys-university_mechanics_Mechanics_74_University` | Static/kinetic friction coefficients follow from `N = W`, pull-force balances, friction laws, and numeric pulls. `N ≠ 0` is derivable from `W = 500`. |
| `archive_part1-archive_part1_10_8` | Boat/person COM equation plus mass definitions should algebraically imply the displacement. Needs nonzero `g` and `P + Q`; E positive-hypothesis augmentation may be necessary. |

## Medium Probability

| Sample | Main risk |
|---|---|
| `archive_part1-archive_part1_9_1` | First squared-speed formula is algebraic, but the second `v_max = sqrt ...` needs nonnegativity/branch reasoning for `Speed` and denominator handling. |
| `archive_part2-archive_part2_4_2` | Spring-constant formula can be derived by squaring period equations, but requires positivity/nonzero facts for `k`, masses, and period denominator. |
| `lean4phys-university_mechanics_Mechanics_76_University` | Algebraic force-pull formula, but denominator `cos theta + mu_k sin theta` is not explicitly nonzero; proving it from `theta = 30*pi/180` is likely brittle. |
| `archive_part1-archive_part1_2_3` | Force equilibrium gives component equations, but the target uses `sqrt`, `sin gamma`, `cos gamma`, and trig expressions; branch and trig normalization are nontrivial. |
| `lean4phys-competition_mechanics_Ch2_Q2` | Algebraic rotating-cone formulas are present, but denominators contain trigonometric terms and sign/positivity assumptions are absent. |
| `archive_part1-archive_part1_5_10` | First curvature relation is algebraic, but numeric forms require exact trig values for `30*pi/180` and square-root simplification. |

## Low Probability

| Sample | Why it is unlikely from the current theorem alone |
|---|---|
| `archive_part1-archive_part1_10_2` | Target numeric drag force is not a straightforward consequence of the stated equations; the speed-squared relation leaves a sign/branch issue and appears inconsistent with the target value. |
| `archive_part1-archive_part1_11_1` | Angular-momentum target requires trig identity reasoning and the two target forms appear not obviously equivalent under the stated hypotheses. |
| `archive_part1-archive_part1_11_4` | Half-life target requires solving a damping ODE; only differential/model relations are present, not the closed-form solution. |
| `archive_part1-archive_part1_12_1` | Work target includes `W_M = 8*pi^2`, but the theorem lacks a verified/integral equation deriving this work from the torque law. |
| `archive_part1-archive_part1_6_6` | Acceleration magnitude target needs derivative/no-slip derivations for `alpha` and `omega`; these pointwise formulas are not available as hypotheses. |
| `archive_part1-archive_part1_9_11` | Stopping time and distance require integration of force/acceleration; the theorem lacks velocity/displacement evolution equations. |
| `lean4phys-university_mechanics_Mechanics_31_University` | Maximum-height formula needs a kinematic energy/constant-acceleration relation; only acceleration and initial velocity facts are present. |
| `lean4phys-university_mechanics_Mechanics_3_University` | Velocity target needs a derivative relation between `x` and `v`; theorem only states the position function and interval. |
| `lean4phys-university_mechanics_Mechanics_71_University` | Incline acceleration target lacks the net-force or gravity-component equation; only friction and weight definition are present. |
| `lean4phys-university_mechanics_Mechanics_16_University` | Acceleration component targets require differentiating velocity functions; no derivative relation to `ax`/`ay` is included. |
| `lean4phys-competition_mechanics_Ch3_Q1` | Spring maximum-speed target has almost no supporting dynamics equations in the theorem. |
| `archive_part1-archive_part1_11_9` | Damping half-life and revolution count require ODE solution/integration and logarithm reasoning, not present as hypotheses. |
| `archive_part1-archive_part1_13_3` | `m3_max` appears only in the target and is not linked to the force equations; `a_at_m3_max` is only partly linked by a ratio equation. |
| `archive_part2-archive_part2_1_9` | Cycloid differential equations require differentiating the geometric constraints; no derivative facts are provided. |
| `archive_part2-archive_part2_4_5` | Period and amplitude targets lack the oscillator dynamics/energy equations needed for proof. |
| `archive_part2-archive_part2_6_6` | Acceleration values may be partly derivable, but velocity values at 45/90 seconds require integration not present in the theorem. |
| `lean4phys-competition_mechanics_Ch2_Q1` | Capstan target needs logarithm inversion of an exponential tension relation and nonzero/positive side conditions; current hypotheses are insufficient and `g` cancellation is underconstrained. |
| `archive_part1-archive_part1_12_7` | Rotational energy/speed target is not connected to the available hypotheses; only angle and speed relation facts are present. |

## Recommended E Evaluation Order

1. Run the 5 high-probability samples first. They are the best signal for whether the preproof replay framework and current E search are functioning.
2. Run the 6 medium samples next with normal timeout but inspect `proof_search_trace.jsonl` and `proof_dependency_audit.jsonl`; most failures should be side-condition, sqrt/trig, or denominator failures, not search-state pollution.
3. Keep the 18 low-probability samples in a separate diagnostic batch. For these, a good E-stage behavior is often a clear failure reason such as missing derivative/integration facts, target-only symbol, or unsupported branch condition, not an indefinite LLM loop.

