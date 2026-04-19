# MechLib 检索消融实验报告（Mechanics 101, R1）

## 实验设置

本次实验采用 `Lean4Phys mechanics 101` 数据集，在当前主流程框架下执行“MechLib 检索消融”测试。消融方式为：

- 关闭 `knowledge.enabled`
- 清空 `knowledge.inject_modules`
- 关闭 `statement.with_mechlib_context`

除上述检索上下文相关设置外，其余流程保持不变。`B/C/D` 反馈轮数设置为 `1`，并发数为 `10`。

相关运行目录：

- [20260413_205749_mechanics101-proxy-gpt54-r1-20260413-ablate-no-mechlib](/f:/AI4Mechanics/coding/pipeline1/runs/20260413_205749_mechanics101-proxy-gpt54-r1-20260413-ablate-no-mechlib)

主要文件：

- [metrics.json](/f:/AI4Mechanics/coding/pipeline1/runs/20260413_205749_mechanics101-proxy-gpt54-r1-20260413-ablate-no-mechlib/metrics.json)
- [analysis.md](/f:/AI4Mechanics/coding/pipeline1/runs/20260413_205749_mechanics101-proxy-gpt54-r1-20260413-ablate-no-mechlib/analysis.md)
- [sample_summary.jsonl](/f:/AI4Mechanics/coding/pipeline1/runs/20260413_205749_mechanics101-proxy-gpt54-r1-20260413-ablate-no-mechlib/sample_summary.jsonl)

## 核心结果

本次消融实验的核心指标如下：

- `num_total_samples = 101`
- `grounding_success_rate = 0.980198`
- `statement_generation_success_rate = 0.940594`
- `lean_compile_success_rate = 0.926316`
- `semantic_consistency_pass_rate = 0.590909`
- `proof_success_rate = 0.323232`
- `end_to_end_verified_solve_rate = 0.316832`

按题目统计：

- `compile_ok = 88 / 101`
- `semantic_ok = 52 / 101`
- `proof_ok = 32 / 101`
- `end_to_end_ok = 32 / 101`

由于本次实验明确关闭了检索上下文，因此与库复用相关的统计均降为零：

- `statement_mechlib_usage_rate = 0.0`
- `selected_statement_mechlib_usage_rate = 0.0`
- `proof_mechlib_usage_rate = 0.0`
- `library_grounded_selection_rate = 0.0`

这与实验设定一致，说明本次消融确实切断了“检索结果进入 B/D/E”的链路。

## 主要失败分布

从最终错误类型看，本次失败主要集中在三类：

- `semantic_drift = 36`
- `proof_search_failure = 20`
- `elaboration_failure = 7`

更细的子类型分布表明，当前消融后最主要的问题仍然是“类型不匹配”与“目标偏移”：

- `proof_search_failure / type_mismatch = 17`
- `semantic_drift / wrong_target = 15`
- `semantic_drift / trivial_goal = 13`
- `elaboration_failure / type_mismatch = 7`
- `semantic_drift / missing_given = 6`

从 `analysis.md` 的 mismatch 统计看，语义层的主要偏差字段为：

- `unknown_target = 28`
- `physical_laws = 25`
- `known_quantities = 19`
- `constraints = 19`

这说明在关闭 MechLib 检索后，系统更容易在目标量表达、定律选择和已知条件覆盖上出现偏差，而不只是简单的证明失败。

## 与历史主流程全量实验的对比

作为参考，可将本次消融实验与此前的全量主流程实验进行对照：

- 参考运行：[20260405_214834_mechanics101-realapi-par10-20260405-full](/f:/AI4Mechanics/coding/pipeline1/runs/20260405_214834_mechanics101-realapi-par10-20260405-full)

需要说明的是，这并不是严格的同配置对照。当前代码在 `D` 阶段规则、报告口径和若干前后处理逻辑上都已发生变化，因此下面的比较只用于观察整体趋势，不应被解释为严格控制变量实验。

相对于该历史全量实验，本次消融结果表现为：

- `grounding_success_rate`: `0.970297 -> 0.980198`，上升 `0.009901`
- `statement_generation_success_rate`: `0.960396 -> 0.940594`，下降 `0.019802`
- `lean_compile_success_rate`: `0.886427 -> 0.926316`，上升 `0.039889`
- `semantic_consistency_pass_rate`: `0.765957 -> 0.590909`，下降 `0.175048`
- `proof_success_rate`: `0.428571 -> 0.323232`，下降 `0.105339`
- `end_to_end_verified_solve_rate`: `0.415842 -> 0.316832`，下降 `0.09901`

这组结果呈现出一个清晰现象：

1. 关闭 MechLib 检索后，前端编译层面并未恶化，反而略有上升。
2. 但语义通过率、证明成功率和最终端到端成功率都显著下降。

这意味着检索上下文的主要作用并不体现在“让 Lean 更容易编译”，而更体现在：

- 帮助 statement 更贴近题意与所需物理关系
- 帮助 D 阶段选择更合理的候选
- 间接提高后续 proof 的可完成性

## 结果解释

本次消融实验支持如下判断：

1. `MechLib` 检索上下文对最终成功率具有正面作用。  
   虽然当前系统“真实调用库定理”的比例仍然偏低，但完全移除检索上下文后，语义与证明阶段的表现仍明显退化。

2. 当前检索的收益主要是“约束与引导”，而不是“显式定理调用”。  
   即使 `proof_mechlib_usage_rate = 0.0`，系统仍然能从检索文本中获得目标量、定律方向和表达风格上的辅助。

3. 当前主瓶颈仍然不是编译，而是语义对齐和证明稳定性。  
   消融后 `lean_compile_success_rate` 仍有 `0.926316`，但 `semantic_consistency_pass_rate` 和 `proof_success_rate` 明显下滑，说明系统的主要困难仍在“说对”和“证对”，而不在“写出可编译的 Lean 语句”。

## 结论

本次 `Mechanics 101` 检索消融实验表明：

- 在当前架构下，移除 `MechLib` 检索上下文后，系统的编译表现并未明显变差；
- 但语义筛选、证明成功和最终端到端成功率均明显下降；
- 因而可以认为，`MechLib` 检索对当前系统仍具有实质性正效应，其主要贡献集中在语义引导与候选约束，而非已经充分实现的“显式库定理复用”。

后续若要继续提高这一路径的收益，优先方向应是：

1. 进一步提高检索结果到 statement 的真实落地率；
2. 使 D 阶段更稳定地区分“真正有库依据的候选”和“仅语义接近的弱化候选”；
3. 提高 E 阶段对检索到的定理名称与接口的真实调用能力。
