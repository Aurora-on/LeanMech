# Mechanics 全量实测分析报告

运行对象：
- [20260402_175059_mechanics-full-realapi-par10-20260402](/f:/AI4Mechanics/coding/pipeline1/runs/20260402_175059_mechanics-full-realapi-par10-20260402)
- 配置：真实 API，并发 `10`，`LeanPhysBench` 的 `mechanics` 子集
- 样本规模：`101` 题
- 近似总耗时：`1 小时 52 分 10 秒`

## 一、结论摘要

这次全量运行说明，项目在工程层面已经具备稳定跑完整个 Mechanics 基准的能力，但当前主瓶颈已经不再是 Lean 编译，而是“命题语义是否真的对题”。

核心结论：
- 最终有 `93/101` 题能编译通过，说明 `A/B/C` 链路已经基本可用。
- 只有 `47/101` 题通过语义一致性检查，说明 `D` 阶段仍是最大瓶颈。
- 只有 `28/101` 题实现端到端验证成功，说明 `E` 阶段虽然也有问题，但它是第二瓶颈，不是第一瓶颈。
- `competition` 子集表现明显弱于 `university` 子集，当前几乎还不在可靠工作区间。

一句话概括：
- 现在的系统更像“能大量产出可编译 Lean 候选的自动形式化系统”，还不是“稳定求解器”。

## 二、总体指标

来自 [metrics.json](/f:/AI4Mechanics/coding/pipeline1/runs/20260402_175059_mechanics-full-realapi-par10-20260402/metrics.json)：

- `num_total_samples = 101`
- `grounding_success_rate = 0.980198`，即 `99/101`
- `statement_generation_success_rate = 0.980198`，即 `99/101`
- `lean_compile_success_rate = 0.851010`，即 `93/101`
- `semantic_consistency_pass_rate = 0.505376`，即 `47/101`
- `proof_success_rate = 0.282828`
- `end_to_end_verified_solve_rate = 0.277228`，即 `28/101`
- `feedback_loop_used_rate = 0.603960`，即 `61/101`

几个更重要的条件视角：
- 在最终可编译的 `93` 题里，只有 `47` 题语义通过，即 `semantic | compile = 47/93 = 0.5054`
- 在语义通过的 `47` 题里，有 `28` 题证明成功，即 `proof | semantic = 28/47 = 0.5957`

这两个数直接说明：
- 当前最大损耗发生在 `compile -> semantic`
- 一旦语义选对了，证明成功率其实并不算太差

## 三、按题源拆分

### 1. University 子集

- 总数：`71`
- compile 成功：`65/71 = 0.9155`
- semantic 成功：`41/71 = 0.5775`
- 端到端成功：`28/71 = 0.3944`

### 2. Competition 子集

- 总数：`30`
- compile 成功：`28/30 = 0.9333`
- semantic 成功：`6/30 = 0.2000`
- 端到端成功：`0/30 = 0.0000`

这组对比非常关键：
- `competition` 题并不是先死在编译上
- 它们主要死在语义对齐
- 即便有 `6` 题通过了语义，最后也全部死在证明阶段

通过语义但仍证明失败的 competition 样本：
- `lean4phys-competition_mechanics_Ch1_Q3`
- `lean4phys-competition_mechanics_Ch1_Q10`
- `lean4phys-competition_mechanics_Ch3_Q1`
- `lean4phys-competition_mechanics_Ch3_Q2`
- `lean4phys-competition_mechanics_Ch6_Q1`
- `lean4phys-competition_mechanics_Ch6_Q2`

这说明：
- 对 competition 题，`D` 和 `E` 都需要专门增强
- 不能只靠当前以 university 风格为主的 prompt 和排序逻辑

## 四、闭环机制表现

本次 `B -> C -> D` 闭环一共触发了 `61/101` 题。

触发原因分布：
- `semantic_fail`：`54`
- `no_compile_pass`：`7`

闭环带来的净收益：
- `semantic_fail -> semantic recovered`：`9`
- `semantic_fail -> e2e recovered`：`5`
- `no_compile_pass -> compile recovered`：`6`
- `no_compile_pass -> semantic recovered`：`0`
- `no_compile_pass -> e2e recovered`：`0`

解释：
- 闭环是有效的，但主要是“部分修复工具”，不是强力纠错器
- 对“首轮完全编译不过”的样本，闭环经常能把它救回可编译状态
- 但对“编译能过、语义却错”的样本，闭环目前只在少数情况下能真正救回来
- `no_compile_pass` 分支现在更像是在修语法和 elaboration，而不是修命题意义

语义恢复样本示例：
- `lean4phys-university_mechanics_Mechanics_20_University`
- `lean4phys-university_mechanics_Mechanics_22_University`
- `lean4phys-university_mechanics_Mechanics_25_University`
- `lean4phys-university_mechanics_Mechanics_28_University`
- `lean4phys-university_mechanics_Mechanics_45_University`
- `lean4phys-university_mechanics_Mechanics_46_University`
- `lean4phys-university_mechanics_Mechanics_68_University`
- `lean4phys-competition_mechanics_Ch1_Q10`
- `lean4phys-competition_mechanics_Ch3_Q2`

最终端到端恢复成功的样本：
- `lean4phys-university_mechanics_Mechanics_22_University`
- `lean4phys-university_mechanics_Mechanics_25_University`
- `lean4phys-university_mechanics_Mechanics_28_University`
- `lean4phys-university_mechanics_Mechanics_45_University`
- `lean4phys-university_mechanics_Mechanics_68_University`

总体判断：
- 闭环值得保留
- 但当前闭环的反馈信息仍然“不够针对语义”

## 五、失败类型分析

最终错误分布：
- `semantic_drift`：`46`
- `proof_search_failure`：`19`
- `elaboration_failure`：`6`
- `wrong_target_extraction`：`2`

### 1. 语义漂移是头号问题

这是本次运行最明确的结论。

系统现在已经能够比较高概率地写出“可以编译”的 Lean，但还远远不能保证它“真的在回答原题”。

代表性样本：
- `lean4phys-university_mechanics_Mechanics_2_University`
- `lean4phys-university_mechanics_Mechanics_3_University`
- `lean4phys-university_mechanics_Mechanics_9_University`
- `lean4phys-university_mechanics_Mechanics_10_University`
- `lean4phys-university_mechanics_Mechanics_11_University`
- `lean4phys-university_mechanics_Mechanics_17_University`
- `lean4phys-university_mechanics_Mechanics_19_University`
- `lean4phys-competition_mechanics_Ch1_Q4`
- `lean4phys-competition_mechanics_Ch2_Q4`
- `lean4phys-competition_mechanics_Ch6_Q23`

直接含义：
- 之后最该投入的不是“再提一点 compile rate”
- 而是“怎么让 B 生成的候选更少偏题，D 的筛选更少选错”

### 2. 证明失败是第二瓶颈

共有 `19` 个最终 `proof_search_failure`。

proof 检查中：
- `attempts_used = 1`：`24`
- `attempts_used = 2`：`23`
- `attempts_used = 0`：`52`

成功分布：
- 第 `1` 次尝试就成功：`24`
- 第 `2` 次尝试修复成功：`4`

说明：
- `E` 并不是完全无效
- 对语义已经正确、结构比较规整的题，它经常可以一次过
- 但一旦题目需要更深的代数化简、变量替换或 proof planning，当前 repair 深度明显不够

代表性 proof 失败样本：
- `lean4phys-university_mechanics_Mechanics_5_University_Converting_volume_units`
- `lean4phys-university_mechanics_Mechanics_13_University`
- `lean4phys-university_mechanics_Mechanics_18_University`
- `lean4phys-university_mechanics_Mechanics_20_University`
- `lean4phys-competition_mechanics_Ch1_Q3`
- `lean4phys-competition_mechanics_Ch6_Q1`

### 3. 最终编译失败已经变成小而集中的问题

最终只有 `8` 题编译失败：
- `lean4phys-university_mechanics_Mechanics_12_University`
- `lean4phys-university_mechanics_Mechanics_14_University`
- `lean4phys-university_mechanics_Mechanics_15_University`
- `lean4phys-university_mechanics_Mechanics_16_University`
- `lean4phys-university_mechanics_Mechanics_48_University`
- `lean4phys-university_mechanics_Mechanics_63_University`
- `lean4phys-competition_mechanics_Ch1_Q7`
- `lean4phys-competition_mechanics_Ch4_Q1`

候选级别 compile 失败中，最常见的 stderr 标签是：
- `PIPELINE_TIMEOUT`：`69`
- `Function expected at ...`：`45`

说明：
- compile 已经不是面上大问题，但剩下的问题很具体，适合逐个清理
- `Function expected at ...` 基本说明仍存在函数符号形状、API arity 或调用方式误判
- `PIPELINE_TIMEOUT` 现在过于粗糙，会掩盖真实错误，影响后续修复定位

### 4. 目标抽取错误频率低，但杀伤力大

只出现了 `2` 次：
- `lean4phys-university_mechanics_Mechanics_48_University`
- `lean4phys-competition_mechanics_Ch1_Q7`

这个问题虽然不多，但它会直接把上游 grounding 和 statement generation 一起带偏，所以要单独盯住。

## 六、候选生成与选择特征

最终被选中的候选分布：
- `c4`：`49`
- `c3`：`21`
- `c1`：`12`
- `c2`：`11`

候选 compile 比例：
- `c1`：`126/160 = 0.7875`
- `c2`：`123/160 = 0.7688`
- `c3`：`135/160 = 0.8438`
- `c4`：`135/160 = 0.8438`

说明：
- 当前后两个候选明显更稳
- `c4` 既最常被选中，又和 `c3` 并列 compile 最强
- 这说明 B 阶段虽然名义上输出 4 个候选，但质量并不均衡
- 也说明 D 当前对后置候选有明显偏好

这不一定是坏事，但说明：
- prompt 生成的 4 个候选还没有拉开“语义表达策略上的差异”
- 反而更像是“后面两个版本更成熟、前面两个版本更容易坏”

## 七、对当前 pipeline 的判断

这次运行说明项目已经跨过了一个重要门槛：
- 可以稳定跑完整个 Mechanics 子集
- 可以稳定维持 `10` 个题目级并发 worker
- 可以产出大量可编译、可检查、可导出的 Lean 文档

但它还没有跨过“可作为强求解器”的门槛：
- 编译通过已经不是主要问题
- 语义忠实性仍是决定性短板
- 证明能力在语义正确之后才显现为第二瓶颈
- competition 风格题目目前整体偏弱

## 八、将来的修改意见

下面按优先级给出建议。排序原则很直接：谁最影响最终 `e2e`，谁优先。

### 优先级 1：先改 `B/D` 的语义对齐，不要先花主要精力继续优化编译

原因：
- 当前最大掉点是 `93 compile -> 47 semantic`
- 这远大于 proof 端的损耗

建议改法：
- 在 `B` prompt 中进一步收紧“目标量”和“适用物理定律”的约束
- 明确禁止“看起来合理但答非所问”的命题模板
- 对常见题型增加更强的结构化 target extraction，例如：
  - 求平均速度 vs 求位移
  - 求标量大小 vs 求有符号量
  - 求最终状态 vs 求全过程关系
- 在 `D` 中加入更严格的 hard gate：
  - 目标变量不匹配直接降为不可选
  - 已知量覆盖不足直接降为不可选
  - law match 明显不符直接降为不可选
- 对 competition 题单独增加偏置，不要完全共用 university 的语义评分习惯

预期收益：
- 这是最可能同时提升 `semantic_pass_rate` 和 `e2e_rate` 的改动

### 优先级 2：把闭环反馈改成“针对错误原因的语义反馈”，而不是泛化反馈

原因：
- 当前闭环触发很多，但真正恢复端到端成功的只有 `5` 题
- `no_compile_pass` 经常只能修回 compile，修不回 semantics

建议改法：
- 让 `D` 返回更细的失败标签，而不是只说 `semantic_fail`
- 至少拆成：
  - `wrong_target`
  - `wrong_law`
  - `missing_given`
  - `trivial_goal`
  - `unit_or_sign_mismatch`
- 在 revision prompt 里直接告诉 `B`：
  - 上一轮回答错了什么
  - 不要重复哪一种错误
  - 哪个量必须成为最终结论
- 对 `no_compile_pass` 场景，额外区分：
  - API arity 错误
  - symbol hallucination
  - elaboration mismatch

预期收益：
- 提高闭环的“语义恢复率”，而不是只提高“能重新编译”

### 优先级 3：对 `competition` 题单独建模，不要继续混在同一套风格里处理

原因：
- `competition` 子集 `0/30` 端到端成功
- 它并不是 compile 差，而是 semantic 和 proof 都弱

建议改法：
- 在 `B` 和 `D` 中增加题型识别
- 识别后切换到 competition 专用提示词或额外约束
- 重点支持：
  - 多步文字条件
  - 隐含目标量
  - 叙述性题干里的变量绑定
  - 多阶段运动/条件切换

预期收益：
- 避免 competition 题被 university 风格的“直接公式化”策略带偏

### 优先级 4：增强 `E` 的定向证明能力，特别是数值题和代数题

原因：
- `proof | semantic = 28/47 = 0.5957`
- 这说明只要语义过了，proof 还有明显提升空间

建议改法：
- 为常见 Mechanics 数值题补充更强的 deterministic tactic 组合
- 优先处理这些高频模式：
  - 单位换算
  - 一元一次代数化简
  - 分数/比例关系
  - 已知量代入后化简
  - 简单平方或根式约束
- repair prompt 中直接喂 unsolved goal 和局部上下文，而不是泛化报错
- 对 competition 里已经 semantic pass 的那 `6` 题，逐题观察 proof 失败模式并做模板化增强

预期收益：
- 在不改前面语义链路的前提下，直接拉高 `proof_success_rate`

### 优先级 5：清理剩余 compile 病灶，但把它当作专项收尾，不要喧宾夺主

原因：
- 最终 compile fail 已经只剩 `8` 题
- 这是局部问题，不再是主导问题

建议改法：
- 逐题检查那 `8` 题
- 优先解决：
  - `Function expected at ...`
  - 长时间 timeout 后丢失真实 stderr
  - 明显的 symbol misuse
- 在超时场景里保留更多诊断信息，不要都压成 `[PIPELINE_TIMEOUT]`

预期收益：
- 可以把 compile rate 再往上推，但对 `e2e` 的边际收益已经不如改 `B/D`

### 优先级 6：重新设计 B 的四候选策略，让四个候选真正形成“差异化解法”

原因：
- 当前 `c3/c4` 明显比 `c1/c2` 更稳
- 说明四候选还不是四种独立思路，而更像四个质量不均衡的草稿

建议改法：
- 强制每个候选承担不同建模策略，例如：
  - 直接物理定义
  - 代数量化改写
  - 更贴近题面描述的版本
  - 更 proof-friendly 的版本
- 禁止候选间只做轻微表述变化

预期收益：
- 提高多候选机制的真实信息增益
- 让 D 的排序更有价值，而不是反复在近似候选里挑一个稍微没坏的

## 九、建议的实际执行顺序

如果只做一轮迭代，建议按这个顺序推进：

1. 改 `B/D` 语义对齐
2. 改闭环反馈结构
3. 给 competition 题加专项处理
4. 改 `E` 的 proof 能力
5. 清理 compile 长尾

理由：
- 这是最符合这次数据分布的投入顺序
- 先改编译不会带来最大收益
- 先改 orchestration 也不会带来最大收益

## 十、最终判断

这次全量运行不是“失败”，而是非常明确地暴露了系统当前真正的问题位置。

当前系统的形态是：
- 调度稳定
- 并发稳定
- 编译能力较强
- 语义精度不足
- 证明能力中等

因此，下一阶段最有价值的工作不是继续强化运行框架，而是回到 `B/D`，提升命题的语义忠实性。只要这一层上来，`E` 的改进才会更有放大效应。
