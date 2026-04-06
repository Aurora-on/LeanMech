# Mechanics 全量实测分析报告（2026-04-05）

运行对象：

- 运行目录：[20260405_214834_mechanics101-realapi-par10-20260405-full](/f:/AI4Mechanics/coding/pipeline1/runs/20260405_214834_mechanics101-realapi-par10-20260405-full)
- 配置文件：[config_mechanics101_proxy_gpt54_parallel10_20260405.yaml](/f:/AI4Mechanics/coding/pipeline1/tmp/config_mechanics101_proxy_gpt54_parallel10_20260405.yaml)
- 数据集：`LeanPhysBench_v0.json` 的 `mechanics` 子集
- 样本规模：`101` 题
- 并发度：`10`
- 模型：`gpt-5.4`，`openai_compatible`，代理端点 `https://api.openai-proxy.org/v1`
- 总耗时：约 `6468.1s`，即约 `1 小时 47 分 48 秒`

关联输出：

- 指标文件：[metrics.json](/f:/AI4Mechanics/coding/pipeline1/runs/20260405_214834_mechanics101-realapi-par10-20260405-full/metrics.json)
- 样本汇总：[sample_summary.jsonl](/f:/AI4Mechanics/coding/pipeline1/runs/20260405_214834_mechanics101-realapi-par10-20260405-full/sample_summary.jsonl)
- 语义排序：[semantic_rank.jsonl](/f:/AI4Mechanics/coding/pipeline1/runs/20260405_214834_mechanics101-realapi-par10-20260405-full/semantic_rank.jsonl)
- 证明结果：[proof_checks.jsonl](/f:/AI4Mechanics/coding/pipeline1/runs/20260405_214834_mechanics101-realapi-par10-20260405-full/proof_checks.jsonl)
- 运行内分析：[analysis.md](/f:/AI4Mechanics/coding/pipeline1/runs/20260405_214834_mechanics101-realapi-par10-20260405-full/analysis.md)

## 一、结论摘要

这次 101 题全量 run 说明，当前 pipeline 在工程层面已经具备稳定跑完整个 `mechanics` 子集的能力，而且相较于 `2026-04-02` 的全量实测，核心结果有明显提升。

最重要的结论有五条：

1. 端到端成功数已经达到 `42/101`，`end_to_end_verified_solve_rate = 0.415842`，明显高于上一轮全量 run 的 `28/101`。
2. 当前最大瓶颈已经从“语义筛选大量误杀”转移为“证明阶段成功率不足”，因为这次语义通过已经达到 `72/101`，但最终 proof 只成功了 `42/101`。
3. `university` 子集已经进入“中等可用区间”，`40/71` 题端到端成功；`competition` 子集虽然语义有提升，但 proof 仍明显落后，只成功了 `2/30`。
4. `B/C/D` 闭环仍然有价值，但收益几乎全部发生在 `university` 子集；对 `competition` 的帮助接近于零。
5. 本轮改动后，系统最值得继续投入的方向已经不是编译，而是 `competition` 题上的 proof 策略，以及 D 到 E 之间的形式选择。

## 二、总体指标

来自 [metrics.json](/f:/AI4Mechanics/coding/pipeline1/runs/20260405_214834_mechanics101-realapi-par10-20260405-full/metrics.json)：

- `num_total_samples = 101`
- `grounding_success_rate = 0.970297`，即 `98/101`
- `statement_generation_success_rate = 0.960396`，即 `97/101`
- `lean_compile_success_rate = 0.886427`
- `semantic_consistency_pass_rate = 0.765957`，即 `72/101`
- `proof_success_rate = 0.428571`
- `end_to_end_verified_solve_rate = 0.415842`，即 `42/101`
- `feedback_loop_used_rate = 0.584158`，即 `59/101`

几个条件成功率更能说明问题：

- `semantic | compile = 72 / 89 = 0.8090`
- `proof | semantic = 42 / 72 = 0.5833`

这两个数说明：

- 当前 `compile -> semantic` 这段已经大幅改善，不再是过去那种“编译过了但大半语义漂移”的状态。
- 现在最大的损耗在 `semantic -> proof`，也就是 theorem 已经基本对题，但 proof 搜索和修复还不够强。

## 三、与 2026-04-02 全量 run 的对比

对比对象：

- [20260402_175059_mechanics-full-realapi-par10-20260402](/f:/AI4Mechanics/coding/pipeline1/runs/20260402_175059_mechanics-full-realapi-par10-20260402)

核心指标变化如下：

- `grounding_success_rate`：`0.980198 -> 0.970297`，下降 `0.009901`
- `statement_generation_success_rate`：`0.980198 -> 0.960396`，下降 `0.019802`
- `lean_compile_success_rate`：`0.851010 -> 0.886427`，提升 `0.035417`
- `semantic_consistency_pass_rate`：`0.505376 -> 0.765957`，提升 `0.260581`
- `proof_success_rate`：`0.282828 -> 0.428571`，提升 `0.145743`
- `end_to_end_verified_solve_rate`：`0.277228 -> 0.415842`，提升 `0.138614`
- `feedback_loop_used_rate`：`0.603960 -> 0.584158`，下降 `0.019802`

从结果看，最关键的变化是：

- **语义通过率提升了 26 个百分点**
- **端到端成功率提升了 13.86 个百分点**

一个合理但未做严格 A/B 验证的推断是：最近这轮修改中，最可能贡献这部分提升的是：

- B 阶段移除了伪造 `fallback theorem`
- D 阶段开始区分 `exact / equivalent / special_case / weaker / drift`
- D 阶段细粒度反馈进入了闭环

同时也能看到一个代价：

- `grounding` 和 `statement_generation` 的表面成功率略有下降

这个下降目前是可接受的，因为它换来了更高质量的最终结果。换句话说，系统现在更少“用占位式成功把失败藏起来”。

## 四、按题源拆分

### 1. University 子集

- 总数：`71`
- `grounding_ok = 70/71 = 0.9859`
- `statement_generation_ok = 70/71 = 0.9859`
- `compile_ok = 67/71 = 0.9437`
- `semantic_ok = 53/71 = 0.7465`
- `proof_ok = 40/71 = 0.5634`
- `end_to_end_ok = 40/71 = 0.5634`

条件成功率：

- `semantic | compile = 53 / 67 = 0.7910`
- `proof | semantic = 40 / 53 = 0.7547`

这说明对 `university` 题：

- D 阶段已经进入比较可用的状态。
- 一旦 D 选中了正确候选，E 有较大概率能把证明做出来。
- 当前 university 子集已经不是“纯 baseline demo”，而是有一定批量求解能力。

### 2. Competition 子集

- 总数：`30`
- `grounding_ok = 28/30 = 0.9333`
- `statement_generation_ok = 27/30 = 0.9000`
- `compile_ok = 27/30 = 0.9000`
- `semantic_ok = 19/30 = 0.6333`
- `proof_ok = 2/30 = 0.0667`
- `end_to_end_ok = 2/30 = 0.0667`

条件成功率：

- `semantic | compile = 19 / 27 = 0.7037`
- `proof | semantic = 2 / 19 = 0.1053`

这部分结论非常清楚：

- `competition` 题现在已经不主要死在 compile 或 D。
- 它们主要死在 E，也就是 theorem 虽然基本选对了，但 proof 跑不出来。

本轮 `competition` 中端到端成功的只有两题：

- `lean4phys-competition_mechanics_Ch1_Q14`
- `lean4phys-competition_mechanics_Ch2_Q5`

因此，当前系统已经不该再把 `competition` 的主要问题归因于“语义全错”。  
更准确的判断是：**competition 已经从“前段失败”转移到了“后段失败”**。

## 五、闭环机制的实际收益

本轮一共 `59/101` 题触发了 `B/C/D` 闭环。

总体情况：

- `feedback_loop_used_count = 59`
- 其中最终端到端成功 `19` 题
- 未触发闭环的 `42` 题中，最终端到端成功 `23` 题

分桶看：

- `university`：触发闭环 `41` 题，其中最终成功 `19` 题
- `competition`：触发闭环 `18` 题，其中最终成功 `0` 题

这说明：

- 闭环对 `university` 是有效工具。
- 闭环对 `competition` 目前几乎无效。

`university` 中通过闭环救回来的端到端成功样本包括：

- `lean4phys-university_mechanics_Mechanics_1_University`
- `lean4phys-university_mechanics_Mechanics_2_University`
- `lean4phys-university_mechanics_Mechanics_4_University_Converting_speed_units`
- `lean4phys-university_mechanics_Mechanics_6_University_Significant_figures_in_multiplication`
- `lean4phys-university_mechanics_Mechanics_11_University`
- `lean4phys-university_mechanics_Mechanics_17_University`
- `lean4phys-university_mechanics_Mechanics_18_University`
- `lean4phys-university_mechanics_Mechanics_19_University`
- `lean4phys-university_mechanics_Mechanics_20_University`
- `lean4phys-university_mechanics_Mechanics_25_University`
- `lean4phys-university_mechanics_Mechanics_27_University`
- `lean4phys-university_mechanics_Mechanics_29_University`
- `lean4phys-university_mechanics_Mechanics_32_University`
- `lean4phys-university_mechanics_Mechanics_38_University`
- `lean4phys-university_mechanics_Mechanics_60_University`
- `lean4phys-university_mechanics_Mechanics_62_University`
- `lean4phys-university_mechanics_Mechanics_65_University`
- `lean4phys-university_mechanics_Mechanics_68_University`
- `lean4phys-university_mechanics_Mechanics_76_University`

当前可以下一个很明确的判断：

- 闭环不应该移除。
- 但闭环下一步应该针对 `competition` 的 proof 侧失败设计更具体的反馈，而不是继续只强化 B。

## 六、失败类型分析

最终错误分布：

- `proof_search_failure: 30`
- `semantic_drift: 22`
- `elaboration_failure: 3`
- `wrong_target_extraction: 3`
- `statement_generation_parse_failed: 1`

与上次全量 run 相比，排序已经发生变化：

- 之前的头号问题是 `semantic_drift`
- 这次的头号问题已经变成 `proof_search_failure`

这说明系统的主瓶颈确实发生了迁移。

### 1. 证明失败是当前第一瓶颈

共有 `30` 题最终卡在 proof。

对应的细分标签：

- `wrong_tactic_strategy: 20`
- `goal_shape_mismatch: 5`
- `missing_intermediate_fact: 5`

这三类基本覆盖了大部分 proof 失败：

- `wrong_tactic_strategy`
  - theorem 本身大体对，但 proof 选的 tactic 路线不合适
- `goal_shape_mismatch`
  - proof body 与实际目标形状不匹配
- `missing_intermediate_fact`
  - 证明路线需要中间引理或中间代数步骤，但当前 repair 深度不够

这说明 E 阶段接下来要增强的重点不是“再试更多次”，而是：

- 更好的 proof planning
- 更好的 goal-shape aware repair
- 更好的中间结论构造

### 2. 语义漂移仍然重要，但不再是头号问题

共有 `22` 题最终仍为 `semantic_drift`。

对应子标签：

- `wrong_target: 10`
- `trivial_goal: 12`

从 summary 中提取出的 `mismatch_fields` 分布：

- `unknown_target: 21`
- `physical_laws: 14`
- `known_quantities: 14`
- `constraints: 9`
- `units: 1`

当前最主要的语义失败模式仍然是：

- 目标量没对准
- 虽然定理表面可编译，但在物理上只回答了更弱的问题
- 一部分候选仍然会退化成“看起来对题，实则是 trivial replay”

不过与上次相比，这个问题已经显著缩小。

### 3. 剩余的 compile 失败已经很集中

最终仍有 `12` 题没有走到 proof 成功，其中 compile 相关失败只占很小部分：

- `elaboration_failure: 3`
- `statement_generation_parse_failed: 1`

从工程角度看，这说明：

- C 阶段已经从“系统性短板”变成“局部扫尾问题”
- 继续投入大量精力提升 compile rate，边际收益不会太高

## 七、D 阶段的当前状态判断

这次 run 的一个重要信号是：D 的质量已经明显好于上一轮。

失败语义结果中的 `target_relation` 分布：

- `weaker: 47`
- `drift: 13`
- `special_case: 5`
- `equivalent: 4`
- `exact: 2`
- `none: 14`

其中最值得注意的是：

- 失败样本中已经开始出现 `equivalent`
- 这说明 D 不再一律把“表面形式不同”打成 drift

一个合理推断是：

- 最近加入的 `target_relation` 机制已经在发挥作用
- 现在 D 的主要剩余问题不是“完全看不懂等价形式”，而是“如何处理 weaker / special_case 与真正可证目标之间的界线”

因此，D 的下一步不应只是继续提高通过率，而应当：

- 更稳定地区分 `equivalent` 与 `weaker`
- 减少 `trivial_goal` 漏网
- 更明确地把 `suggested_fix_direction` 写成 proof-friendly 形式

## 八、Competition 子集的专项判断

当前 `competition` 的状态与 `university` 已经明显不同。

它的问题不是单一的“语义差”，而是两个连续问题：

1. 命题虽然比以前更接近原题，但仍然常常是较弱形式。
2. 即便 D 接受了 theorem，E 也很难把 proof 推完。

`competition` 中 `semantic_ok = true` 但 `proof_ok = false` 的有 `17` 题。  
这部分正是最值得深挖的样本，因为它们说明：

- 题目已经被形式化成了看起来可接受的 theorem
- 但 proof generator / repair 还不能稳定处理它们

这类题目应当成为下一轮 E 侧增强的主要训练样本。

## 九、当前 pipeline 的状态判断

现在的系统已经不是“能批量产出 compile-pass 候选”的阶段了。  
它已经进入下一阶段：

- 对 `university`，主瓶颈开始转向 E
- 对 `competition`，主瓶颈是 D 和 E 的组合，但最终更突出地表现为 E

因此，从研发优先级上看，当前不应该再把主要精力放在：

- 继续造更多候选
- 继续微调 compile fallback
- 继续做 orchestration 层面的改造

更应该做的是：

- 让 E 能真正利用现在已经更好的 theorem
- 让 D 输出更 proof-friendly 的语义修正方向

## 十、后续修改建议

下面按优先级给出建议。

### 优先级 1：加强 E 的 proof planning 与 repair，而不是单纯加尝试次数

原因：

- 当前 `72` 题语义通过，但只有 `42` 题最终证明成功。
- `proof_search_failure` 已经是头号失败类型。

建议：

- 在 E 的 prompt 中明确区分几类 proof 路线：
  - 代数恒等变形
  - 线性消元
  - 有理式化简
  - 开方 / 符号约束
  - 存在性证明
- 把 `wrong_tactic_strategy`、`goal_shape_mismatch`、`missing_intermediate_fact` 三类错误分别走不同 repair 模板。
- 对 proof fail 的样本，优先从 `semantic_ok = true` 的 competition 题中抽样做专门增强。

### 优先级 2：让 D 的 `suggested_fix_direction` 更偏向“可证明目标”，而不只是“语义更对”

原因：

- 现在 D 已经能挑出大体对题的 theorem，但不一定是 proof-friendly 的 theorem。
- `weaker` / `special_case` / `equivalent` 之间的边界仍会影响后续证明难度。

建议：

- 在 D 的 prompt 中增加“如果多个目标都语义可接受，优先选择更容易在 Lean 中证明的等价目标形式”。
- 将 `suggested_fix_direction` 从自然语言建议进一步结构化，例如：
  - `normalize_literals`
  - `avoid_division_form`
  - `prefer_explicit_existential`
  - `introduce_intermediate_quantity`

### 优先级 3：对 `competition` 单独做 proof 侧专项增强

原因：

- 当前 `competition` 已经不是 compile 问题。
- 它的核心是 theorem 更复杂、proof 更难。

建议：

- 把 `competition` 中 `semantic_ok && !proof_ok` 的 17 题单独列成一个 proof benchmark。
- 对这些题做集中分类：
  - 哪些是 algebra-heavy
  - 哪些需要额外中间事实
  - 哪些本质是 theorem 形式仍过弱
- 针对这组 benchmark 迭代 E，而不是继续拿 `university` 平均数据做判断。

### 优先级 4：继续压缩 trivial / weaker 类 semantic fail

原因：

- `trivial_goal` 还有 `12` 题。
- `wrong_target` 还有 `10` 题。

建议：

- 在 B revise prompt 中继续强化“不要输出 weaker restatement”。
- 对 D 的 hard gate 增加更明确的约束：
  - 目标变量不对，直接 fail
  - 已知量缺失且影响结论，直接 fail
  - 结论只是重放假设，直接 fail

### 优先级 5：保留闭环，但不要把它误当成 competition 的主解法

原因：

- `university` 的闭环收益很好。
- `competition` 的闭环收益几乎为零。

建议：

- 对 `university` 继续保留当前 `B/C/D` revision。
- 对 `competition`，下一步如果要扩展闭环，更值得考虑的是 `D -> E` 之间的信息利用，而不是再把更多信息回送给 B。

## 十一、最终判断

本轮 101 题全量 run 说明：

- 当前版本已经明显优于 `2026-04-02` 的全量版本。
- 系统已经从“语义大量漂移”阶段，进入“proof 端成为新主瓶颈”的阶段。
- `university` 已经进入可持续迭代区间。
- `competition` 也不再是纯语义灾难，而是更明确地暴露出 theorem-to-proof 这段能力不足。

因此，下一阶段最值钱的投入不是再修 compile，也不是再做 orchestration，而是：

- **优先增强 E**
- **同时让 D 输出更 proof-friendly 的候选偏好和修正建议**

