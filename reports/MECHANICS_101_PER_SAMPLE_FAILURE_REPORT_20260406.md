# Lean4PhysBench Mechanics 101 题逐题失败分析报告（2026-04-06）

- 运行目录：[20260405_214834_mechanics101-realapi-par10-20260405-full](/f:/AI4Mechanics/coding/pipeline1/runs/20260405_214834_mechanics101-realapi-par10-20260405-full)
- 指标文件：[metrics.json](/f:/AI4Mechanics/coding/pipeline1/runs/20260405_214834_mechanics101-realapi-par10-20260405-full/metrics.json)
- 样本汇总：[sample_summary.jsonl](/f:/AI4Mechanics/coding/pipeline1/runs/20260405_214834_mechanics101-realapi-par10-20260405-full/sample_summary.jsonl)

说明：

- 本报告按 101 题逐题给出最终状态、失败点和一句中文分析。
- “失败点”指最终阻断样本端到端成功的阶段，不代表该题前面各阶段完全没有问题。
- 对已端到端成功的题，失败点记为“无（端到端成功）”。

## 一、总体统计

- 总题数：101
- 端到端成功：42
- 端到端失败：59
- 触发闭环：59

## 二、逐题分析

### 1. lean4phys-university_mechanics_Mechanics_1_University

- 最终状态：端到端成功
- 失败点：无（端到端成功）
- 最终错误标签：none / none
- 最终轮次：1
- 是否触发闭环：是
- 简短分析：首轮未直接定稿，但通过 B/C/D 闭环在第 1 轮修正后端到端成功。

### 2. lean4phys-university_mechanics_Mechanics_2_University

- 最终状态：端到端成功
- 失败点：无（端到端成功）
- 最终错误标签：none / none
- 最终轮次：1
- 是否触发闭环：是
- 简短分析：首轮未直接定稿，但通过 B/C/D 闭环在第 1 轮修正后端到端成功。

### 3. lean4phys-university_mechanics_Mechanics_3_University

- 最终状态：失败
- 失败点：D 模块（Semantic Rank）
- 最终错误标签：semantic_drift / trivial_goal
- 最终轮次：1
- 是否触发闭环：是
- 简短分析：候选命题退化为重放假设或循环陈述，表面可编译，但没有完成真正推导；问题主要在物理规律、已知量、目标量。

### 4. lean4phys-university_mechanics_Mechanics_4_University_Converting_speed_units

- 最终状态：端到端成功
- 失败点：无（端到端成功）
- 最终错误标签：none / none
- 最终轮次：1
- 是否触发闭环：是
- 简短分析：首轮未直接定稿，但通过 B/C/D 闭环在第 1 轮修正后端到端成功。

### 5. lean4phys-university_mechanics_Mechanics_5_University_Converting_volume_units

- 最终状态：失败
- 失败点：D 模块（Semantic Rank）
- 最终错误标签：semantic_drift / wrong_target
- 最终轮次：1
- 是否触发闭环：是
- 简短分析：命题的目标量没有对准原题。当前更像是在回答较弱或偏移后的目标（target_relation=weaker）。

### 6. lean4phys-university_mechanics_Mechanics_6_University_Significant_figures_in_multiplication

- 最终状态：端到端成功
- 失败点：无（端到端成功）
- 最终错误标签：none / none
- 最终轮次：1
- 是否触发闭环：是
- 简短分析：首轮未直接定稿，但通过 B/C/D 闭环在第 1 轮修正后端到端成功。

### 7. lean4phys-university_mechanics_Mechanics_8_University

- 最终状态：失败
- 失败点：C 模块（Lean Compile Check）
- 最终错误标签：elaboration_failure / type_mismatch
- 最终轮次：1
- 是否触发闭环：是
- 简短分析：Lean elaboration 阶段出现类型不匹配，说明 B 生成的命题在局部表达上仍不符合库中的对象或函数签名；报错为“F:/AI4Mechanics/coding/pipeline1/runs/20260405_214834_mechanics101-realapi-par10-20260405-full/.pipeline1_tmp/compile/mechlib/lean4phys-university_mechanics_Mechanics_8_University_c1.lean:11:25: error(lean.unknownIdentifier): Unknown con...”。

### 8. lean4phys-university_mechanics_Mechanics_9_University

- 最终状态：失败
- 失败点：D 模块（Semantic Rank）
- 最终错误标签：semantic_drift / wrong_target
- 最终轮次：1
- 是否触发闭环：是
- 简短分析：命题的目标量没有对准原题。当前更像是在回答较弱或偏移后的目标（target_relation=weaker）。

### 9. lean4phys-university_mechanics_Mechanics_10_University

- 最终状态：失败
- 失败点：D 模块（Semantic Rank）
- 最终错误标签：semantic_drift / trivial_goal
- 最终轮次：1
- 是否触发闭环：是
- 简短分析：候选命题退化为重放假设或循环陈述，表面可编译，但没有完成真正推导；问题主要在目标量、约束条件、已知量。

### 10. lean4phys-university_mechanics_Mechanics_11_University

- 最终状态：端到端成功
- 失败点：无（端到端成功）
- 最终错误标签：none / none
- 最终轮次：1
- 是否触发闭环：是
- 简短分析：首轮未直接定稿，但通过 B/C/D 闭环在第 1 轮修正后端到端成功。

### 11. lean4phys-university_mechanics_Mechanics_12_University

- 最终状态：端到端成功
- 失败点：无（端到端成功）
- 最终错误标签：none / none
- 最终轮次：0
- 是否触发闭环：否
- 简短分析：首轮即完成端到端验证，当前没有暴露最终失败点。

### 12. lean4phys-university_mechanics_Mechanics_13_University

- 最终状态：端到端成功
- 失败点：无（端到端成功）
- 最终错误标签：none / none
- 最终轮次：0
- 是否触发闭环：否
- 简短分析：首轮即完成端到端验证，当前没有暴露最终失败点。

### 13. lean4phys-university_mechanics_Mechanics_14_University

- 最终状态：失败
- 失败点：D 模块（Semantic Rank）
- 最终错误标签：semantic_drift / trivial_goal
- 最终轮次：1
- 是否触发闭环：是
- 简短分析：候选命题退化为重放假设或循环陈述，表面可编译，但没有完成真正推导；问题主要在已知量。

### 14. lean4phys-university_mechanics_Mechanics_15_University

- 最终状态：失败
- 失败点：D 模块（Semantic Rank）
- 最终错误标签：semantic_drift / trivial_goal
- 最终轮次：1
- 是否触发闭环：是
- 简短分析：候选命题退化为重放假设或循环陈述，表面可编译，但没有完成真正推导；问题主要在物理规律、目标量、已知量。

### 15. lean4phys-university_mechanics_Mechanics_16_University

- 最终状态：失败
- 失败点：D 模块（Semantic Rank）
- 最终错误标签：semantic_drift / wrong_target
- 最终轮次：1
- 是否触发闭环：是
- 简短分析：命题的目标量没有对准原题。当前更像是在回答较弱或偏移后的目标（target_relation=weaker）。

### 16. lean4phys-university_mechanics_Mechanics_17_University

- 最终状态：端到端成功
- 失败点：无（端到端成功）
- 最终错误标签：none / none
- 最终轮次：1
- 是否触发闭环：是
- 简短分析：首轮未直接定稿，但通过 B/C/D 闭环在第 1 轮修正后端到端成功。

### 17. lean4phys-university_mechanics_Mechanics_18_University

- 最终状态：端到端成功
- 失败点：无（端到端成功）
- 最终错误标签：none / none
- 最终轮次：1
- 是否触发闭环：是
- 简短分析：首轮未直接定稿，但通过 B/C/D 闭环在第 1 轮修正后端到端成功。

### 18. lean4phys-university_mechanics_Mechanics_19_University

- 最终状态：端到端成功
- 失败点：无（端到端成功）
- 最终错误标签：none / none
- 最终轮次：1
- 是否触发闭环：是
- 简短分析：首轮未直接定稿，但通过 B/C/D 闭环在第 1 轮修正后端到端成功。

### 19. lean4phys-university_mechanics_Mechanics_20_University

- 最终状态：端到端成功
- 失败点：无（端到端成功）
- 最终错误标签：none / none
- 最终轮次：1
- 是否触发闭环：是
- 简短分析：首轮未直接定稿，但通过 B/C/D 闭环在第 1 轮修正后端到端成功。

### 20. lean4phys-university_mechanics_Mechanics_21_University

- 最终状态：端到端成功
- 失败点：无（端到端成功）
- 最终错误标签：none / none
- 最终轮次：0
- 是否触发闭环：否
- 简短分析：首轮即完成端到端验证，当前没有暴露最终失败点。

### 21. lean4phys-university_mechanics_Mechanics_22_University

- 最终状态：失败
- 失败点：C 模块（Lean Compile Check）
- 最终错误标签：elaboration_failure / timeout_or_tooling_block
- 最终轮次：1
- 是否触发闭环：是
- 简短分析：本题在编译阶段遇到超时或工具链阻塞，尚未进入稳定的语义筛选；报错为“[PIPELINE_TIMEOUT]”。

### 22. lean4phys-university_mechanics_Mechanics_23_University

- 最终状态：失败
- 失败点：D 模块（Semantic Rank）
- 最终错误标签：semantic_drift / wrong_target
- 最终轮次：1
- 是否触发闭环：是
- 简短分析：命题的目标量没有对准原题。当前更像是在回答较弱或偏移后的目标（target_relation=weaker）。

### 23. lean4phys-university_mechanics_Mechanics_24_University

- 最终状态：失败
- 失败点：D 模块（Semantic Rank）
- 最终错误标签：semantic_drift / trivial_goal
- 最终轮次：1
- 是否触发闭环：是
- 简短分析：候选命题退化为重放假设或循环陈述，表面可编译，但没有完成真正推导；问题主要在物理规律、目标量。

### 24. lean4phys-university_mechanics_Mechanics_25_University

- 最终状态：端到端成功
- 失败点：无（端到端成功）
- 最终错误标签：none / none
- 最终轮次：1
- 是否触发闭环：是
- 简短分析：首轮未直接定稿，但通过 B/C/D 闭环在第 1 轮修正后端到端成功。

### 25. lean4phys-university_mechanics_Mechanics_26_University

- 最终状态：失败
- 失败点：E 模块（Proof Search / Repair）
- 最终错误标签：proof_search_failure / goal_shape_mismatch
- 最终轮次：0
- 是否触发闭环：否
- 简短分析：证明脚本与实际目标形状不匹配，说明当前 proof 生成没有正确贴合 theorem 的最终 goal；Lean 报错为“Application type mismatch: The argument”。

### 26. lean4phys-university_mechanics_Mechanics_27_University

- 最终状态：端到端成功
- 失败点：无（端到端成功）
- 最终错误标签：none / none
- 最终轮次：1
- 是否触发闭环：是
- 简短分析：首轮未直接定稿，但通过 B/C/D 闭环在第 1 轮修正后端到端成功。

### 27. lean4phys-university_mechanics_Mechanics_28_University

- 最终状态：失败
- 失败点：D 模块（Semantic Rank）
- 最终错误标签：semantic_drift / trivial_goal
- 最终轮次：1
- 是否触发闭环：是
- 简短分析：候选命题退化为重放假设或循环陈述，表面可编译，但没有完成真正推导；问题主要在目标量、物理规律、已知量、约束条件。

### 28. lean4phys-university_mechanics_Mechanics_29_University

- 最终状态：端到端成功
- 失败点：无（端到端成功）
- 最终错误标签：none / none
- 最终轮次：1
- 是否触发闭环：是
- 简短分析：首轮未直接定稿，但通过 B/C/D 闭环在第 1 轮修正后端到端成功。

### 29. lean4phys-university_mechanics_Mechanics_30_University

- 最终状态：端到端成功
- 失败点：无（端到端成功）
- 最终错误标签：none / none
- 最终轮次：0
- 是否触发闭环：否
- 简短分析：首轮即完成端到端验证，当前没有暴露最终失败点。

### 30. lean4phys-university_mechanics_Mechanics_31_University

- 最终状态：失败
- 失败点：E 模块（Proof Search / Repair）
- 最终错误标签：proof_search_failure / wrong_tactic_strategy
- 最终轮次：1
- 是否触发闭环：是
- 简短分析：定理已通过语义筛选，但当前 proof tactic 路线不合适，Lean 最终报错集中在“linarith failed to find a contradiction”。

### 31. lean4phys-university_mechanics_Mechanics_32_University

- 最终状态：端到端成功
- 失败点：无（端到端成功）
- 最终错误标签：none / none
- 最终轮次：1
- 是否触发闭环：是
- 简短分析：首轮未直接定稿，但通过 B/C/D 闭环在第 1 轮修正后端到端成功。

### 32. lean4phys-university_mechanics_Mechanics_33_University_copy

- 最终状态：失败
- 失败点：D 模块（Semantic Rank）
- 最终错误标签：semantic_drift / trivial_goal
- 最终轮次：1
- 是否触发闭环：是
- 简短分析：候选命题退化为重放假设或循环陈述，表面可编译，但没有完成真正推导；问题主要在目标量、已知量、物理规律。

### 33. lean4phys-university_mechanics_Mechanics_34_University_copy

- 最终状态：端到端成功
- 失败点：无（端到端成功）
- 最终错误标签：none / none
- 最终轮次：0
- 是否触发闭环：否
- 简短分析：首轮即完成端到端验证，当前没有暴露最终失败点。

### 34. lean4phys-university_mechanics_Mechanics_35_University_copy

- 最终状态：失败
- 失败点：E 模块（Proof Search / Repair）
- 最终错误标签：proof_search_failure / wrong_tactic_strategy
- 最终轮次：0
- 是否触发闭环：否
- 简短分析：定理已通过语义筛选，但当前 proof tactic 路线不合适，Lean 最终报错集中在“No goals to be solved”。

### 35. lean4phys-university_mechanics_Mechanics_36_University_copy

- 最终状态：失败
- 失败点：E 模块（Proof Search / Repair）
- 最终错误标签：proof_search_failure / missing_intermediate_fact
- 最终轮次：1
- 是否触发闭环：是
- 简短分析：证明过程中缺少关键中间结论或中间变形步骤，导致最终仍有未解目标；Lean 报错为“unsolved goals”。

### 36. lean4phys-university_mechanics_Mechanics_37_University

- 最终状态：端到端成功
- 失败点：无（端到端成功）
- 最终错误标签：none / none
- 最终轮次：0
- 是否触发闭环：否
- 简短分析：首轮即完成端到端验证，当前没有暴露最终失败点。

### 37. lean4phys-university_mechanics_Mechanics_38_University

- 最终状态：端到端成功
- 失败点：无（端到端成功）
- 最终错误标签：none / none
- 最终轮次：1
- 是否触发闭环：是
- 简短分析：首轮未直接定稿，但通过 B/C/D 闭环在第 1 轮修正后端到端成功。

### 38. lean4phys-university_mechanics_Mechanics_39_University

- 最终状态：失败
- 失败点：D 模块（Semantic Rank）
- 最终错误标签：semantic_drift / trivial_goal
- 最终轮次：1
- 是否触发闭环：是
- 简短分析：候选命题退化为重放假设或循环陈述，表面可编译，但没有完成真正推导；问题主要在目标量、物理规律、已知量。

### 39. lean4phys-university_mechanics_Mechanics_40_University

- 最终状态：端到端成功
- 失败点：无（端到端成功）
- 最终错误标签：none / none
- 最终轮次：0
- 是否触发闭环：否
- 简短分析：首轮即完成端到端验证，当前没有暴露最终失败点。

### 40. lean4phys-university_mechanics_Mechanics_43_University

- 最终状态：失败
- 失败点：E 模块（Proof Search / Repair）
- 最终错误标签：proof_search_failure / wrong_tactic_strategy
- 最终轮次：1
- 是否触发闭环：是
- 简短分析：定理已通过语义筛选，但当前 proof tactic 路线不合适，Lean 最终报错集中在“ring_nf made no progress on goal”。

### 41. lean4phys-university_mechanics_Mechanics_44_University

- 最终状态：失败
- 失败点：E 模块（Proof Search / Repair）
- 最终错误标签：proof_search_failure / wrong_tactic_strategy
- 最终轮次：1
- 是否触发闭环：是
- 简短分析：定理已通过语义筛选，但当前 proof tactic 路线不合适，Lean 最终报错集中在“unexpected token 'calc'; expected ':='”。

### 42. lean4phys-university_mechanics_Mechanics_45_University

- 最终状态：失败
- 失败点：D 模块（Semantic Rank）
- 最终错误标签：semantic_drift / trivial_goal
- 最终轮次：1
- 是否触发闭环：是
- 简短分析：候选命题退化为重放假设或循环陈述，表面可编译，但没有完成真正推导；问题主要在目标量、约束条件、已知量。

### 43. lean4phys-university_mechanics_Mechanics_46_University

- 最终状态：端到端成功
- 失败点：无（端到端成功）
- 最终错误标签：none / none
- 最终轮次：0
- 是否触发闭环：否
- 简短分析：首轮即完成端到端验证，当前没有暴露最终失败点。

### 44. lean4phys-university_mechanics_Mechanics_47_University

- 最终状态：失败
- 失败点：C 模块（Lean Compile Check）
- 最终错误标签：elaboration_failure / type_mismatch
- 最终轮次：1
- 是否触发闭环：是
- 简短分析：Lean elaboration 阶段出现类型不匹配，说明 B 生成的命题在局部表达上仍不符合库中的对象或函数签名；报错为“F:/AI4Mechanics/coding/pipeline1/runs/20260405_214834_mechanics101-realapi-par10-20260405-full/.pipeline1_tmp/compile/mechlib/lean4phys-university_mechanics_Mechanics_47_University_c3.lean:13:25: error(lean.unknownIdentifier): Unknown co...”。

### 45. lean4phys-university_mechanics_Mechanics_48_University

- 最终状态：失败
- 失败点：A 模块（Grounding）
- 最终错误标签：wrong_target_extraction / wrong_target_extraction
- 最终轮次：0
- 是否触发闭环：否
- 简短分析：A 阶段把题目的目标量抽取错了，后续形式化会整体偏离，因此流程在最上游就失效了。

### 46. lean4phys-university_mechanics_Mechanics_49_University

- 最终状态：失败
- 失败点：D 模块（Semantic Rank）
- 最终错误标签：semantic_drift / trivial_goal
- 最终轮次：1
- 是否触发闭环：是
- 简短分析：候选命题退化为重放假设或循环陈述，表面可编译，但没有完成真正推导；问题主要在目标量、物理规律。

### 47. lean4phys-university_mechanics_Mechanics_51_University

- 最终状态：失败
- 失败点：E 模块（Proof Search / Repair）
- 最终错误标签：proof_search_failure / wrong_tactic_strategy
- 最终轮次：1
- 是否触发闭环：是
- 简短分析：定理已通过语义筛选，但当前 proof tactic 路线不合适，Lean 最终报错集中在“linarith failed to find a contradiction”。

### 48. lean4phys-university_mechanics_Mechanics_52_University

- 最终状态：失败
- 失败点：E 模块（Proof Search / Repair）
- 最终错误标签：proof_search_failure / wrong_tactic_strategy
- 最终轮次：0
- 是否触发闭环：否
- 简短分析：定理已通过语义筛选，但当前 proof tactic 路线不合适，Lean 最终报错集中在“Tactic `rewrite` failed: Did not find an occurrence of the pattern”。

### 49. lean4phys-university_mechanics_Mechanics_53_University

- 最终状态：失败
- 失败点：E 模块（Proof Search / Repair）
- 最终错误标签：proof_search_failure / wrong_tactic_strategy
- 最终轮次：0
- 是否触发闭环：否
- 简短分析：定理已通过语义筛选，但当前 proof tactic 路线不合适，Lean 最终报错集中在“No goals to be solved”。

### 50. lean4phys-university_mechanics_Mechanics_54_University

- 最终状态：端到端成功
- 失败点：无（端到端成功）
- 最终错误标签：none / none
- 最终轮次：0
- 是否触发闭环：否
- 简短分析：首轮即完成端到端验证，当前没有暴露最终失败点。

### 51. lean4phys-university_mechanics_Mechanics_55_University

- 最终状态：端到端成功
- 失败点：无（端到端成功）
- 最终错误标签：none / none
- 最终轮次：0
- 是否触发闭环：否
- 简短分析：首轮即完成端到端验证，当前没有暴露最终失败点。

### 52. lean4phys-university_mechanics_Mechanics_56_University

- 最终状态：端到端成功
- 失败点：无（端到端成功）
- 最终错误标签：none / none
- 最终轮次：0
- 是否触发闭环：否
- 简短分析：首轮即完成端到端验证，当前没有暴露最终失败点。

### 53. lean4phys-university_mechanics_Mechanics_59_University

- 最终状态：端到端成功
- 失败点：无（端到端成功）
- 最终错误标签：none / none
- 最终轮次：0
- 是否触发闭环：否
- 简短分析：首轮即完成端到端验证，当前没有暴露最终失败点。

### 54. lean4phys-university_mechanics_Mechanics_60_University

- 最终状态：端到端成功
- 失败点：无（端到端成功）
- 最终错误标签：none / none
- 最终轮次：1
- 是否触发闭环：是
- 简短分析：首轮未直接定稿，但通过 B/C/D 闭环在第 1 轮修正后端到端成功。

### 55. lean4phys-university_mechanics_Mechanics_61_University

- 最终状态：失败
- 失败点：E 模块（Proof Search / Repair）
- 最终错误标签：proof_search_failure / goal_shape_mismatch
- 最终轮次：0
- 是否触发闭环：否
- 简短分析：证明脚本与实际目标形状不匹配，说明当前 proof 生成没有正确贴合 theorem 的最终 goal；Lean 报错为“unexpected end of input; expected ':='”。

### 56. lean4phys-university_mechanics_Mechanics_62_University

- 最终状态：端到端成功
- 失败点：无（端到端成功）
- 最终错误标签：none / none
- 最终轮次：1
- 是否触发闭环：是
- 简短分析：首轮未直接定稿，但通过 B/C/D 闭环在第 1 轮修正后端到端成功。

### 57. lean4phys-university_mechanics_Mechanics_63_University

- 最终状态：端到端成功
- 失败点：无（端到端成功）
- 最终错误标签：none / none
- 最终轮次：0
- 是否触发闭环：否
- 简短分析：首轮即完成端到端验证，当前没有暴露最终失败点。

### 58. lean4phys-university_mechanics_Mechanics_64_University

- 最终状态：端到端成功
- 失败点：无（端到端成功）
- 最终错误标签：none / none
- 最终轮次：0
- 是否触发闭环：否
- 简短分析：首轮即完成端到端验证，当前没有暴露最终失败点。

### 59. lean4phys-university_mechanics_Mechanics_65_University

- 最终状态：端到端成功
- 失败点：无（端到端成功）
- 最终错误标签：none / none
- 最终轮次：1
- 是否触发闭环：是
- 简短分析：首轮未直接定稿，但通过 B/C/D 闭环在第 1 轮修正后端到端成功。

### 60. lean4phys-university_mechanics_Mechanics_66_University

- 最终状态：端到端成功
- 失败点：无（端到端成功）
- 最终错误标签：none / none
- 最终轮次：0
- 是否触发闭环：否
- 简短分析：首轮即完成端到端验证，当前没有暴露最终失败点。

### 61. lean4phys-university_mechanics_Mechanics_67_University

- 最终状态：端到端成功
- 失败点：无（端到端成功）
- 最终错误标签：none / none
- 最终轮次：0
- 是否触发闭环：否
- 简短分析：首轮即完成端到端验证，当前没有暴露最终失败点。

### 62. lean4phys-university_mechanics_Mechanics_68_University

- 最终状态：端到端成功
- 失败点：无（端到端成功）
- 最终错误标签：none / none
- 最终轮次：1
- 是否触发闭环：是
- 简短分析：首轮未直接定稿，但通过 B/C/D 闭环在第 1 轮修正后端到端成功。

### 63. lean4phys-university_mechanics_Mechanics_69_University

- 最终状态：失败
- 失败点：E 模块（Proof Search / Repair）
- 最终错误标签：proof_search_failure / wrong_tactic_strategy
- 最终轮次：0
- 是否触发闭环：否
- 简短分析：定理已通过语义筛选，但当前 proof tactic 路线不合适，Lean 最终报错集中在“Tactic `rewrite` failed: Did not find an occurrence of the pattern”。

### 64. lean4phys-university_mechanics_Mechanics_70_University

- 最终状态：失败
- 失败点：E 模块（Proof Search / Repair）
- 最终错误标签：proof_search_failure / goal_shape_mismatch
- 最终轮次：0
- 是否触发闭环：否
- 简短分析：证明脚本与实际目标形状不匹配，说明当前 proof 生成没有正确贴合 theorem 的最终 goal；Lean 报错为“Type mismatch: After simplification, term”。

### 65. lean4phys-university_mechanics_Mechanics_71_University

- 最终状态：失败
- 失败点：E 模块（Proof Search / Repair）
- 最终错误标签：proof_search_failure / missing_intermediate_fact
- 最终轮次：0
- 是否触发闭环：否
- 简短分析：证明过程中缺少关键中间结论或中间变形步骤，导致最终仍有未解目标；Lean 报错为“unsolved goals”。

### 66. lean4phys-university_mechanics_Mechanics_72_University

- 最终状态：端到端成功
- 失败点：无（端到端成功）
- 最终错误标签：none / none
- 最终轮次：0
- 是否触发闭环：否
- 简短分析：首轮即完成端到端验证，当前没有暴露最终失败点。

### 67. lean4phys-university_mechanics_Mechanics_73_University

- 最终状态：端到端成功
- 失败点：无（端到端成功）
- 最终错误标签：none / none
- 最终轮次：0
- 是否触发闭环：否
- 简短分析：首轮即完成端到端验证，当前没有暴露最终失败点。

### 68. lean4phys-university_mechanics_Mechanics_74_University

- 最终状态：端到端成功
- 失败点：无（端到端成功）
- 最终错误标签：none / none
- 最终轮次：0
- 是否触发闭环：否
- 简短分析：首轮即完成端到端验证，当前没有暴露最终失败点。

### 69. lean4phys-university_mechanics_Mechanics_75_University

- 最终状态：端到端成功
- 失败点：无（端到端成功）
- 最终错误标签：none / none
- 最终轮次：0
- 是否触发闭环：否
- 简短分析：首轮即完成端到端验证，当前没有暴露最终失败点。

### 70. lean4phys-university_mechanics_Mechanics_76_University

- 最终状态：端到端成功
- 失败点：无（端到端成功）
- 最终错误标签：none / none
- 最终轮次：1
- 是否触发闭环：是
- 简短分析：首轮未直接定稿，但通过 B/C/D 闭环在第 1 轮修正后端到端成功。

### 71. lean4phys-university_mechanics_Mechanics_77_University

- 最终状态：端到端成功
- 失败点：无（端到端成功）
- 最终错误标签：none / none
- 最终轮次：0
- 是否触发闭环：否
- 简短分析：首轮即完成端到端验证，当前没有暴露最终失败点。

### 72. lean4phys-competition_mechanics_Ch1_Q1

- 最终状态：失败
- 失败点：D 模块（Semantic Rank）
- 最终错误标签：semantic_drift / wrong_target
- 最终轮次：1
- 是否触发闭环：是
- 简短分析：命题的目标量没有对准原题。当前更像是在回答较弱或偏移后的目标（target_relation=weaker）。

### 73. lean4phys-competition_mechanics_Ch1_Q2

- 最终状态：失败
- 失败点：E 模块（Proof Search / Repair）
- 最终错误标签：proof_search_failure / wrong_tactic_strategy
- 最终轮次：1
- 是否触发闭环：是
- 简短分析：定理已通过语义筛选，但当前 proof tactic 路线不合适，Lean 最终报错集中在“Invalid field `mp`: The environment does not contain `Function.mp`”。

### 74. lean4phys-competition_mechanics_Ch1_Q3

- 最终状态：失败
- 失败点：E 模块（Proof Search / Repair）
- 最终错误标签：proof_search_failure / wrong_tactic_strategy
- 最终轮次：1
- 是否触发闭环：是
- 简短分析：定理已通过语义筛选，但当前 proof tactic 路线不合适，Lean 最终报错集中在“linarith failed to find a contradiction”。

### 75. lean4phys-competition_mechanics_Ch1_Q4

- 最终状态：失败
- 失败点：E 模块（Proof Search / Repair）
- 最终错误标签：proof_search_failure / wrong_tactic_strategy
- 最终轮次：1
- 是否触发闭环：是
- 简短分析：定理已通过语义筛选，但当前 proof tactic 路线不合适，Lean 最终报错集中在“[PIPELINE_TIMEOUT]”。

### 76. lean4phys-competition_mechanics_Ch1_Q5

- 最终状态：失败
- 失败点：D 模块（Semantic Rank）
- 最终错误标签：semantic_drift / wrong_target
- 最终轮次：1
- 是否触发闭环：是
- 简短分析：命题的目标量没有对准原题。当前更像是在回答较弱或偏移后的目标（target_relation=weaker）。

### 77. lean4phys-competition_mechanics_Ch1_Q6

- 最终状态：失败
- 失败点：E 模块（Proof Search / Repair）
- 最终错误标签：proof_search_failure / missing_intermediate_fact
- 最终轮次：1
- 是否触发闭环：是
- 简短分析：证明过程中缺少关键中间结论或中间变形步骤，导致最终仍有未解目标；Lean 报错为“linarith failed to find a contradiction”。

### 78. lean4phys-competition_mechanics_Ch1_Q7

- 最终状态：失败
- 失败点：A 模块（Grounding）
- 最终错误标签：wrong_target_extraction / wrong_target_extraction
- 最终轮次：0
- 是否触发闭环：否
- 简短分析：A 阶段把题目的目标量抽取错了，后续形式化会整体偏离，因此流程在最上游就失效了。

### 79. lean4phys-competition_mechanics_Ch1_Q8

- 最终状态：失败
- 失败点：D 模块（Semantic Rank）
- 最终错误标签：semantic_drift / wrong_target
- 最终轮次：1
- 是否触发闭环：是
- 简短分析：命题的目标量没有对准原题。当前更像是在回答较弱或偏移后的目标（target_relation=weaker）。

### 80. lean4phys-competition_mechanics_Ch1_Q9

- 最终状态：失败
- 失败点：D 模块（Semantic Rank）
- 最终错误标签：semantic_drift / trivial_goal
- 最终轮次：1
- 是否触发闭环：是
- 简短分析：候选命题退化为重放假设或循环陈述，表面可编译，但没有完成真正推导；问题主要在目标量、物理规律、约束条件。

### 81. lean4phys-competition_mechanics_Ch1_Q10

- 最终状态：失败
- 失败点：E 模块（Proof Search / Repair）
- 最终错误标签：proof_search_failure / wrong_tactic_strategy
- 最终轮次：0
- 是否触发闭环：否
- 简短分析：定理已通过语义筛选，但当前 proof tactic 路线不合适，Lean 最终报错集中在“No goals to be solved”。

### 82. lean4phys-competition_mechanics_Ch1_Q11

- 最终状态：失败
- 失败点：D 模块（Semantic Rank）
- 最终错误标签：semantic_drift / wrong_target
- 最终轮次：1
- 是否触发闭环：是
- 简短分析：命题的目标量没有对准原题。当前更像是在回答较弱或偏移后的目标（target_relation=special_case）。

### 83. lean4phys-competition_mechanics_Ch1_Q12

- 最终状态：失败
- 失败点：D 模块（Semantic Rank）
- 最终错误标签：semantic_drift / wrong_target
- 最终轮次：1
- 是否触发闭环：是
- 简短分析：命题的目标量没有对准原题。当前更像是在回答较弱或偏移后的目标（target_relation=weaker）。

### 84. lean4phys-competition_mechanics_Ch1_Q13

- 最终状态：失败
- 失败点：D 模块（Semantic Rank）
- 最终错误标签：semantic_drift / wrong_target
- 最终轮次：1
- 是否触发闭环：是
- 简短分析：命题的目标量没有对准原题。当前更像是在回答较弱或偏移后的目标（target_relation=special_case）。

### 85. lean4phys-competition_mechanics_Ch1_Q14

- 最终状态：端到端成功
- 失败点：无（端到端成功）
- 最终错误标签：none / none
- 最终轮次：0
- 是否触发闭环：否
- 简短分析：首轮即完成端到端验证，当前没有暴露最终失败点。

### 86. lean4phys-competition_mechanics_Ch2_Q1

- 最终状态：失败
- 失败点：E 模块（Proof Search / Repair）
- 最终错误标签：proof_search_failure / wrong_tactic_strategy
- 最终轮次：0
- 是否触发闭环：否
- 简短分析：定理已通过语义筛选，但当前 proof tactic 路线不合适，Lean 最终报错集中在“No goals to be solved”。

### 87. lean4phys-competition_mechanics_Ch2_Q2

- 最终状态：失败
- 失败点：E 模块（Proof Search / Repair）
- 最终错误标签：proof_search_failure / wrong_tactic_strategy
- 最终轮次：0
- 是否触发闭环：否
- 简短分析：定理已通过语义筛选，但当前 proof tactic 路线不合适，Lean 最终报错集中在“F:/AI4Mechanics/coding/pipeline1/runs/20260405_214834_mechanics101-realapi-par10-20260405-full/.pipeline1_tmp/proof/mechlib/lean4phys-competition_mechanics_Ch2_Q2_c3.lean:22:14: error(lean.unknownIdentifier): Unknown identifier `sq_ne_ze...”。

### 88. lean4phys-competition_mechanics_Ch2_Q3

- 最终状态：失败
- 失败点：E 模块（Proof Search / Repair）
- 最终错误标签：proof_search_failure / goal_shape_mismatch
- 最终轮次：1
- 是否触发闭环：是
- 简短分析：证明脚本与实际目标形状不匹配，说明当前 proof 生成没有正确贴合 theorem 的最终 goal；Lean 报错为“Type mismatch”。

### 89. lean4phys-competition_mechanics_Ch2_Q4

- 最终状态：失败
- 失败点：E 模块（Proof Search / Repair）
- 最终错误标签：proof_search_failure / missing_intermediate_fact
- 最终轮次：1
- 是否触发闭环：是
- 简短分析：证明过程中缺少关键中间结论或中间变形步骤，导致最终仍有未解目标；Lean 报错为“unsolved goals”。

### 90. lean4phys-competition_mechanics_Ch2_Q5

- 最终状态：端到端成功
- 失败点：无（端到端成功）
- 最终错误标签：none / none
- 最终轮次：0
- 是否触发闭环：否
- 简短分析：首轮即完成端到端验证，当前没有暴露最终失败点。

### 91. lean4phys-competition_mechanics_Ch3_Q1

- 最终状态：失败
- 失败点：E 模块（Proof Search / Repair）
- 最终错误标签：proof_search_failure / wrong_tactic_strategy
- 最终轮次：0
- 是否触发闭环：否
- 简短分析：定理已通过语义筛选，但当前 proof tactic 路线不合适，Lean 最终报错集中在“No goals to be solved”。

### 92. lean4phys-competition_mechanics_Ch3_Q2

- 最终状态：失败
- 失败点：E 模块（Proof Search / Repair）
- 最终错误标签：proof_search_failure / wrong_tactic_strategy
- 最终轮次：0
- 是否触发闭环：否
- 简短分析：定理已通过语义筛选，但当前 proof tactic 路线不合适，Lean 最终报错集中在“No goals to be solved”。

### 93. lean4phys-competition_mechanics_Ch4_Q1

- 最终状态：失败
- 失败点：A 模块（Grounding）
- 最终错误标签：wrong_target_extraction / wrong_target_extraction
- 最终轮次：0
- 是否触发闭环：否
- 简短分析：A 阶段把题目的目标量抽取错了，后续形式化会整体偏离，因此流程在最上游就失效了。

### 94. lean4phys-competition_mechanics_Ch4_Q2

- 最终状态：失败
- 失败点：D 模块（Semantic Rank）
- 最终错误标签：semantic_drift / trivial_goal
- 最终轮次：1
- 是否触发闭环：是
- 简短分析：候选命题退化为重放假设或循环陈述，表面可编译，但没有完成真正推导；问题主要在目标量、物理规律、已知量、约束条件。

### 95. lean4phys-competition_mechanics_Ch5_Q1

- 最终状态：失败
- 失败点：E 模块（Proof Search / Repair）
- 最终错误标签：proof_search_failure / wrong_tactic_strategy
- 最终轮次：1
- 是否触发闭环：是
- 简短分析：定理已通过语义筛选，但当前 proof tactic 路线不合适，Lean 最终报错集中在“No goals to be solved”。

### 96. lean4phys-competition_mechanics_Ch5_Q2

- 最终状态：失败
- 失败点：E 模块（Proof Search / Repair）
- 最终错误标签：proof_search_failure / goal_shape_mismatch
- 最终轮次：0
- 是否触发闭环：否
- 简短分析：证明脚本与实际目标形状不匹配，说明当前 proof 生成没有正确贴合 theorem 的最终 goal；Lean 报错为“Invalid field `mp`: The environment does not contain `Function.mp`”。

### 97. lean4phys-competition_mechanics_Ch5_Q3

- 最终状态：失败
- 失败点：E 模块（Proof Search / Repair）
- 最终错误标签：proof_search_failure / wrong_tactic_strategy
- 最终轮次：1
- 是否触发闭环：是
- 简短分析：定理已通过语义筛选，但当前 proof tactic 路线不合适，Lean 最终报错集中在“Tactic `rewrite` failed: Did not find an occurrence of the pattern”。

### 98. lean4phys-competition_mechanics_Ch6_Q1

- 最终状态：失败
- 失败点：E 模块（Proof Search / Repair）
- 最终错误标签：proof_search_failure / wrong_tactic_strategy
- 最终轮次：0
- 是否触发闭环：否
- 简短分析：定理已通过语义筛选，但当前 proof tactic 路线不合适，Lean 最终报错集中在“linarith failed to find a contradiction”。

### 99. lean4phys-competition_mechanics_Ch6_Q2

- 最终状态：失败
- 失败点：E 模块（Proof Search / Repair）
- 最终错误标签：proof_search_failure / missing_intermediate_fact
- 最终轮次：0
- 是否触发闭环：否
- 简短分析：证明过程中缺少关键中间结论或中间变形步骤，导致最终仍有未解目标；Lean 报错为“unsolved goals”。

### 100. lean4phys-competition_mechanics_Ch6_Q23

- 最终状态：失败
- 失败点：E 模块（Proof Search / Repair）
- 最终错误标签：proof_search_failure / wrong_tactic_strategy
- 最终轮次：1
- 是否触发闭环：是
- 简短分析：定理已通过语义筛选，但当前 proof tactic 路线不合适，Lean 最终报错集中在“No goals to be solved”。

### 101. lean4phys-competition_mechanics_Ch7_Q1

- 最终状态：失败
- 失败点：B 模块（Statement Generation）
- 最终错误标签：statement_generation_parse_failed / statement_generation_parse_failed
- 最终轮次：1
- 是否触发闭环：是
- 简短分析：B 阶段没有产出可用候选，最终可用候选数为 0。这通常意味着模型输出解析失败，或本地规范化后全部候选都被判为不可用。
