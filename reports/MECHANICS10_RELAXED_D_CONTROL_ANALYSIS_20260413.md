# 10题小对照实验分析：放松 D 阶段是否能恢复近期回归样本

## 实验目的

本实验用于判断：在近期主流程 101 题全量实验中，成功率下降是否主要由 D 阶段语义门控收紧导致。

为此，从“上一次 101 题全量主流程成功、但本次全量主流程失败”的样本中抽取 10 题，构造一个最小对照实验：

- 基线一：`20260405_214834_mechanics101-realapi-par10-20260405-full`
  - 代表较早版本的 101 题全量主流程结果
- 基线二：`20260413_113815_mechanics101-realapi-par10-cdfeedback2-20260413`
  - 代表当前主流程、严格版 D、`max_revision_rounds = 2` 的 101 题全量结果
- 对照实验：`20260413_161257_mechanics10-relaxed-d-control-20260413`
  - 只在运行时临时放松 D 的两项规则：
    - 将 target mismatch 的 rule fallback 阈值从 `0.5` 放松到 `0.4`
    - 去掉“函数型目标必须显式绑定目标符号”的 hard gate
  - 其余主流程配置保持不变

## 对照实验结果

- 运行目录：[20260413_161257_mechanics10-relaxed-d-control-20260413](/f:/AI4Mechanics/coding/pipeline1/runs/20260413_161257_mechanics10-relaxed-d-control-20260413)
- 日志文件：[mechanics10_relaxed_d_control_20260413.log](/f:/AI4Mechanics/coding/pipeline1/tmp/run_logs/mechanics10_relaxed_d_control_20260413.log)

核心指标：

- `num_total_samples = 10`
- `semantic_ok = 4`
- `proof_ok = 2`
- `end_to_end_ok = 2`
- `end_to_end_verified_solve_rate = 0.2`

对比结论：

- 在这 10 个回归样本中，严格版 D 下是 `0/10` 成功
- 放松 D 后恢复为 `2/10` 成功

这说明：

1. D 阶段收紧**确实**造成了部分真实回归。
2. 但 D 不是唯一原因，因为大多数样本在放松 D 后仍未恢复。

## 样本级对照表

| 样本 | 旧全量(20260405) | 严格版D(20260413) | 放松版D对照 | 解释 |
|---|---|---|---|---|
| `Mechanics_1` | 成功 | `proof_search_failure / type_mismatch` | `proof_search_failure / type_mismatch` | 与 D 无关，主要问题在 proof/type mismatch |
| `Mechanics_4` | 成功 | `proof_search_failure / type_mismatch` | `proof_search_failure / type_mismatch` | 与 D 无关，主要问题在 proof/type mismatch |
| `Mechanics_11` | 成功 | `semantic_drift / wrong_target` | `semantic_drift / trivial_goal` | 放松 D 后仍未恢复，说明不只是 target gate 问题 |
| `Mechanics_12` | 成功 | `semantic_drift / wrong_target` | `semantic_drift / missing_given` | 放松 D 后仍未恢复，说明还存在 statement 语义缺失 |
| `Mechanics_19` | 成功 | `proof_search_failure / type_mismatch` | `semantic_drift / unit_or_sign_mismatch` | 放松 D 没有恢复，失败形态改变，但仍未成功 |
| `Mechanics_27` | 成功 | `semantic_drift / missing_given` | `semantic_drift / missing_given` | 与 D 收紧无关，问题在 givens 缺失 |
| `Mechanics_29` | 成功 | `semantic_drift / wrong_target` | `statement_generation_parse_failed` | 放松 D 后反而暴露出更前面的生成问题 |
| `Mechanics_32` | 成功 | `semantic_drift / trivial_goal` | 成功 | 明显是 D 收紧带来的回归样本 |
| `Mechanics_37` | 成功 | `semantic_drift / wrong_target` | 成功 | 明显是 D 收紧带来的回归样本 |
| `Ch1_Q14` | 成功 | `proof_search_failure / type_mismatch` | `semantic_drift / wrong_target` | 放松 D 后仍未恢复，问题不是单一 D gate |

## 分组结论

### 1. 明显由 D 收紧导致的回归

只有 2 题在放松 D 后被直接救回：

- `lean4phys-university_mechanics_Mechanics_32_University`
- `lean4phys-university_mechanics_Mechanics_37_University`

这类样本说明，当前 D 的收紧确实会把一部分原本可解的题目挡在 proof 阶段之前。

### 2. 并非主要由 D 收紧导致的回归

以下类型在放松 D 后仍未恢复：

- `proof_search_failure / type_mismatch`
  - `Mechanics_1`
  - `Mechanics_4`
- `semantic_drift / missing_given`
  - `Mechanics_27`
- `statement_generation_parse_failed`
  - `Mechanics_29`

这说明回归并不主要集中在 D，还包括：

- B 阶段生成不稳定
- C/E 阶段的 type mismatch
- 题干 givens 未被完整翻译到 statement 中

### 3. D 收紧可能与其它问题叠加

有些样本在严格版和放松版中的失败类型不同，但都未恢复，例如：

- `Mechanics_19`
- `Ch1_Q14`

这类样本更像是：

- D 的收紧会改变最终被选中的 candidate
- 但真正阻碍成功的还可能包括 type mismatch、单位处理问题或目标表达不稳定

## 总体判断

这组 10 题小对照实验支持以下判断：

1. **D 阶段收紧是近期主流程成功率下降的一个真实原因。**
2. **但它不是主导全部回归的唯一因素。**
3. **在这 10 题里，能明确归因于 D 收紧并通过放松 D 恢复的样本比例为 `2/10`。**
4. **其余 `8/10` 的失败仍然指向 statement 质量、givens 翻译、proof type mismatch 等其它问题。**

因此，更准确的结论不是“最近的下降完全由 D 引起”，而是：

> D 的收紧确实带来了部分回归，但当前主流程的整体下降来自 D 收紧与 B/E 侧不稳定问题的叠加。

## 下一步建议

这组实验之后，最合理的下一步不是简单把 D 全面放松回旧版本，而是做有针对性的回调：

1. 只放松“函数型目标显式绑定”的 hard gate，而保留其它 target mismatch 约束。
2. 对 `wrong_target` 和 `trivial_goal` 做题型区分，避免把所有隐式等价形式一律挡掉。
3. 并行检查最近新增的 `proof_search_failure / type_mismatch`，因为这类回归在样本中占比同样很高。

