# 理论力学 14 题两轮运行分析报告

## 实验设置

本次实验针对理论力学 `14` 题专题数据集进行两轮真实 API 运行，目标是验证“失败题重跑一次”是否能够显著提升最终成功率。

运行策略如下：

1. 首轮对全部 `14` 题执行主流程，使用并发 `8`。
2. 从首轮结果中筛出所有失败题。
3. 对失败题单独再跑一轮，仍使用并发 `8`。
4. 最终统计时，采用“首轮成功题保留首轮结果，首轮失败题用第二轮结果覆盖”的口径。

相关目录：

- 首轮运行：[20260413_165847_theoretical-mechanics-14-realapi-par8-rerunfailed-20260413-pass1](/f:/AI4Mechanics/coding/pipeline1/runs/20260413_165847_theoretical-mechanics-14-realapi-par8-rerunfailed-20260413-pass1)
- 第二轮重跑失败题：[20260413_171518_theoretical-mechanics-12failed-realapi-par8-rerun-20260413-pass2](/f:/AI4Mechanics/coding/pipeline1/runs/20260413_171518_theoretical-mechanics-12failed-realapi-par8-rerun-20260413-pass2)
- 合并统计结果：[theoretical14_rerunfailed_merged_20260413](/f:/AI4Mechanics/coding/pipeline1/reports/theoretical14_rerunfailed_merged_20260413)

其中，`lean_compile_success_rate` 已按题目统计：每道题在最终轮次中只要至少有一个候选定理通过 Lean 编译，即计为该题编译成功。

## 首轮结果

首轮 `14` 题全量运行的核心指标为：

- `grounding_success_rate = 0.857143`
- `statement_generation_success_rate = 0.785714`
- `lean_compile_success_rate = 1.0`
- `semantic_consistency_pass_rate = 0.363636`
- `proof_success_rate = 0.166667`
- `end_to_end_verified_solve_rate = 0.142857`

对应成功数为：

- 首轮端到端成功：`2 / 14`

首轮失败分布显示，主要瓶颈仍然集中在语义筛选与目标抽取，而不是编译：

- `semantic_drift = 7`
- `proof_search_failure = 2`
- `statement_generation_parse_failed = 1`
- `wrong_target_extraction = 2`

## 第二轮重跑结果

首轮失败样本共有 `12` 题，因此第二轮只重跑这 `12` 题。第二轮的核心指标为：

- `grounding_success_rate = 0.75`
- `statement_generation_success_rate = 0.75`
- `lean_compile_success_rate = 1.0`
- `semantic_consistency_pass_rate = 0.333333`
- `proof_success_rate = 0.222222`
- `end_to_end_verified_solve_rate = 0.166667`

在这 `12` 题中，第二轮成功救回了 `2` 题：

- `lean4phys-theoretical_mechanics_momentum_theorem_complex_02`
- `lean4phys-theoretical_mechanics_dalembert_principle_basic_09`

## 最终合并统计

按“最后一次结果为准”的规则合并后，最终指标为：

- `num_total_samples = 14`
- `grounding_success_rate = 0.785714`
- `statement_generation_success_rate = 0.785714`
- `lean_compile_success_rate = 1.0`
- `semantic_consistency_pass_rate = 0.454545`
- `proof_success_rate = 0.363636`
- `end_to_end_verified_solve_rate = 0.285714`

从成功数看：

- 首轮成功：`2 / 14`
- 重跑失败题后新增救回：`2` 题
- 最终成功：`4 / 14`

这说明在当前主流程下，失败题重跑一次确实能带来可见收益，但增幅仍然有限，尚不足以根本改变整体成功率水平。

## 最终成功与失败样本

合并后最终成功的题目为：

- `lean4phys-theoretical_mechanics_momentum_theorem_complex_02`
- `lean4phys-theoretical_mechanics_kinetic_energy_theorem_basic_03`
- `lean4phys-theoretical_mechanics_angular_momentum_theorem_basic_05`
- `lean4phys-theoretical_mechanics_dalembert_principle_basic_09`

最终仍失败的题目及其主要失败类型为：

- `momentum_theorem_basic_01`：`semantic_drift / wrong_target`
- `kinetic_energy_theorem_complex_04`：`proof_search_failure / type_mismatch`
- `angular_momentum_theorem_complex_06`：`semantic_drift / trivial_goal`
- `moment_of_momentum_theorem_basic_07`：`semantic_drift / trivial_goal`
- `moment_of_momentum_theorem_complex_08`：`semantic_drift / trivial_goal`
- `dalembert_principle_complex_10`：`wrong_target_extraction / wrong_target_extraction`
- `lagrange_equation_basic_11`：`semantic_drift / trivial_goal`
- `lagrange_equation_complex_12`：`wrong_target_extraction / wrong_target_extraction`
- `mechanical_vibration_basic_13`：`wrong_target_extraction / wrong_target_extraction`
- `mechanical_vibration_complex_14`：`semantic_drift / wrong_target`

## 结果分析

### 1. 重跑的主要收益来自采样波动，而不是系统性修复

本次两轮运行中，确有 `2` 题被第二轮成功救回。这表明当前系统在以下环节上存在较强随机性：

- statement 候选生成
- semantic ranking 的最终选择
- proof 生成与修复

换句话说，部分题目并不是“系统绝对不会做”，而是“单次运行不稳定”。在这种情况下，对失败题追加一次重跑，可以获得有限但真实的收益。

### 2. 主要瓶颈仍然是 D 和目标抽取

从最终失败分布看：

- `semantic_drift = 6`
- `wrong_target_extraction = 3`
- `proof_search_failure = 1`

这说明在理论力学专题上，当前瓶颈仍然更偏前段：

- 题意目标抽取不稳定
- theorem 的目标表达容易被判为弱化或偏题
- 一些候选虽然编译通过，但在语义层被识别为平凡命题或错误目标

因此，这一专题集上的问题并不主要表现为“证明能力不够”，而更像是“前端形式化表达尚未稳定落在正确目标上”。

### 3. proof 阶段并不是当前最主要短板

最终只有 `1` 题落在 `proof_search_failure / type_mismatch`。这与 101 题全量 mechanics 集相比有明显差别。对于理论力学 14 题专题，目前更关键的并不是先增强 proof tactic，而是先提高：

- 目标抽取质量
- theorem 语义对齐质量
- 避免生成 `trivial_goal`

### 4. MechLib 真实使用仍然偏弱

合并结果中：

- `statement_mechlib_usage_rate = 0.088235`
- `selected_statement_mechlib_usage_rate = 0.0`
- `proof_mechlib_usage_rate = 0.0`
- `library_grounded_selection_rate = 0.0`

这表明尽管系统运行在 `MechLib` 环境中，且检索链路已经接通，但最终真正被选中的 statement 和 proof 仍然几乎没有落到检索出的库定理上。换言之，当前系统更多是“在 MechLib 环境里运行”，而不是“真正复用了 MechLib 的定理知识”。

## 结论

本次两轮实验表明：

1. 对失败题追加一次重跑是有价值的，能够带来有限但真实的恢复收益。
2. 理论力学 14 题专题的主瓶颈仍然是语义筛选与目标抽取，而不是编译或证明本身。
3. 当前 MechLib 的真实使用率仍然较低，尚未形成“检索到定理 -> statement 使用 -> proof 引用”的稳定闭环。

因此，若后续继续优化这一专题集，优先级建议为：

1. 优先改进目标抽取与 D 阶段的语义对齐。
2. 控制 `trivial_goal` 与 `wrong_target_extraction`。
3. 再逐步提升 statement 与 proof 对 MechLib 定理的真实使用率。
