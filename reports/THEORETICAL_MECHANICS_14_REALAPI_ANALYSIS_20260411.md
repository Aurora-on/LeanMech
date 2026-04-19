# 理论力学 14 题真实 API 专项分析报告

## 1. 实验概况

- 运行目录：[/f:/AI4Mechanics/coding/pipeline1/runs/20260411_204726_theoretical-mechanics-14-proxy-gpt54-20260407](/f:/AI4Mechanics/coding/pipeline1/runs/20260411_204726_theoretical-mechanics-14-proxy-gpt54-20260407)
- 数据集：`bench_theoretical_mechanics_14_20260407.json`
- 模型：`gpt-5.4`
- 后端：`openai_compatible`
- Lean 环境：`physlean+mechlib`
- 并发：`4`
- 环境健康状态：`clean`

本次实验目标是验证当前主 pipeline 在一组小型理论力学题目上的表现，并重点观察：

- 各阶段的主要瓶颈在哪一层
- 新增的 MechLib 依据化改造是否真的进入最终 statement 和 proof
- 反馈闭环是否在这组题上带来稳定收益

## 2. 总体结果

本次 14 题的总体指标如下：

- `grounding_success_rate = 0.857143`
- `statement_generation_success_rate = 0.857143`
- `lean_compile_success_rate = 0.906977`
- `semantic_consistency_pass_rate = 0.5`
- `proof_success_rate = 0.25`
- `end_to_end_verified_solve_rate = 0.214286`
- `feedback_loop_used_rate = 0.785714`

直接结论：

1. 当前这组题的主瓶颈不是编译，而是 `D` 和 `E`。
2. `C` 阶段编译通过率已经较高，说明 statement 的语法/Lean 壳层基本可跑。
3. 真正把题目翻对并证出来仍然困难，最终只有 `3/14` 题端到端成功。

## 3. 端到端成功与失败分布

端到端成功的题目：

- `angular_momentum_theorem_basic_05`
- `moment_of_momentum_theorem_complex_08`
- `dalembert_principle_basic_09`

主要失败类型分布：

- `semantic_drift = 6`
- `proof_search_failure = 3`
- `wrong_target_extraction = 2`

子错误进一步表现为：

- `wrong_target = 4`
- `trivial_goal = 2`
- `type_mismatch = 3`
- `wrong_target_extraction = 2`

这说明这组题当前主要卡在两类问题：

1. `A/B/D` 没有把题目的真实目标准确落成 theorem。
2. theorem 选对后，`E` 仍然经常停留在代数整理层，没形成稳定的证明骨架。

## 4. 分主题观察

### 4.1 动量定理

- `momentum_theorem_basic_01` 在 `A` 直接失败，属于 `wrong_target_extraction`。
- `momentum_theorem_complex_02` 在第二轮选中了只从假设的 `delta_p` 推 `v_T` 的弱化命题，被 `D` 判成 `wrong_target`。

这里的问题不是 Lean 不会编译，而是：

- 题目要求先从给定力函数求冲量/动量变化，再求末速度。
- 最终被选中的 theorem 只保留了“已知 delta_p 时怎么解 v_T”的代数后半段。

这类失败说明：对“需要先建物理过程，再解目标”的题，当前 statement 仍倾向退化成局部代数关系。

### 4.2 动能定理

- `kinetic_energy_theorem_basic_03` 失败点和上面类似：只保留了最后的速度公式，没有把“功-能关系”的来源正式化。
- `kinetic_energy_theorem_complex_04` 语义通过，但 proof 失败，错误是 `linarith failed to find a contradiction`。

这组题的信号是：

- `D` 已经能拦掉“只给结果公式”的弱化命题。
- 但进入 `E` 后，证明仍主要靠通用代数 tactic，不足以稳定完成中间量较多的能量题。

### 4.3 角动量定理 / 动量矩定理

- `angular_momentum_theorem_basic_05` 成功。
- `angular_momentum_theorem_complex_06` 失败，原因是把最终目标公式直接作为假设，属于 `trivial_goal`。
- `moment_of_momentum_theorem_basic_07` 语义通过，但 proof 失败，报错 `No goals to be solved`。
- `moment_of_momentum_theorem_complex_08` 成功。

这组题说明：

- 该主题里，pipeline 已经具备一定成功能力。
- 但复杂题仍容易走向两种坏模式：
  - statement 直接把目标当假设写进去
  - proof 结构不稳定，repair 后出现 tactic 与当前 goal 不匹配

### 4.4 达朗贝尔原理

- `dalembert_principle_basic_09` 成功。
- `dalembert_principle_complex_10` 失败，原因是只求了拉力 `T`，没有把法向反力 `N` 和斜面/摩擦侧的动力学一起纳入。

这说明当前复杂多物体系统题依然存在“只抓住一个局部方程”的问题。

### 4.5 拉格朗日方程

- `lagrange_equation_basic_11` 被判为 `wrong_target`。
- `lagrange_equation_complex_12` 语义通过，但 proof 失败，仍是 `linarith failed to find a contradiction`。

关键问题是：

- theorem 虽然接近正确微分方程，但没有把 `theta_ddot` 明确绑定为 `theta` 的二阶导数，也没有把系统建模条件完整形式化。
- 这意味着当前系统在“微分方程类目标”上，仍容易产出“看起来像对的 ODE”，但不够严密。

### 4.6 机械振动基础

- `mechanical_vibration_basic_13` 在 `A` 阶段失败。
- `mechanical_vibration_complex_14` 失败为 `trivial_goal`。

这一组是本次最弱的主题之一。复杂振动题最终 theorem 中虽然提到了正确方程和幅频关系，但把关键输出退化成：

- 幅值公式的自反等式
- `zeta < 1 / sqrt 2 -> True`

这类候选在字面上覆盖了很多关键词，但本质上不提供有效物理结论。

## 5. MechLib 实际使用情况

这是本次实验最重要的观察之一。

新增统计结果如下：

- `statement_mechlib_usage_rate = 0.046512`
- `selected_statement_mechlib_usage_rate = 0.0`
- `proof_mechlib_usage_rate = 0.0`
- `library_grounded_selection_rate = 0.0`

结论非常明确：

1. 模型在 B 阶段偶尔会尝试写出 `library_symbols_used`，但最终被选中的 statement 基本没有真实落到检索到的库定理上。
2. 成功 proof 的 `proof_plan` 中，`theorems_to_apply` 为空，说明 E 仍然主要依赖题目给定假设和后续代数整理，而不是显式调用 MechLib theorem。
3. 当前“MechLib 依据化改造”已经能把“是否真的用到了库”统计出来，但还没有把“有库依据的候选更容易成为最终赢家”稳定做出来。

从具体样本看，这个问题不是“模型完全不想用库”，而是“库引用在现有环境里经常不稳定，最后反而被 Real 版 statement 替代”。

例如 `momentum_theorem_complex_02`：

- 第一轮 B 里模型尝试了 `impulse_momentum_theorem`、`momentum_change_const_mass`、`impulse_def` 等库符号。
- 但这些候选要么 compile timeout，要么 type mismatch，要么被标记为 `unsupported_library_symbol`。
- 第二轮最终选中的 theorem 反而是一个纯 `Real` 代数版 statement。

这说明当前主问题不是“没有检索”，而是：

- 检索到的 theorem 和当前声明/证明环境之间还没有形成稳定的可编译、可证明接口。

## 6. 反馈闭环的真实作用

本次：

- `feedback_loop_used_count = 11`
- `feedback_loop_success_count = 2`

也就是说，大部分题都触发了闭环，但真正救回来的很少。

闭环目前的作用更像：

- 从明显错误候选拉回到“至少可编译、至少和题意接近”的候选

而不是：

- 稳定把弱化命题修到严格正确
- 稳定把 theorem-first 计划修成真正用库的 proof

所以闭环目前是必要的，但还不是强纠错机制。

## 7. 当前最需要解决的问题

### 7.1 MechLib 与声明环境没有真正接上

当前最大问题不是“没有检索到定理”，而是：

- 库定理名被模型引用了
- 但 theorem declaration 和当前 Lean/MechLib 接口之间不稳定
- 结果是：
  - compile timeout
  - type mismatch
  - unsupported library symbol
  - 最终回退成纯 `Real` 版 statement

这是当前“MechLib 使用率接近 0”最核心的原因。

### 7.2 D 已经会惩罚弱化命题，但还不能稳定把题拉到“可证明的严格版本”

当前 `D` 已经能识别：

- `wrong_target`
- `trivial_goal`
- 部分弱化/辅助关系

但在复杂题上，候选集里经常没有“既严格正确、又可编译、又可证明”的版本，因此最终还是只能在一组不理想候选中选相对不差的那个。

### 7.3 E 仍然主要停留在代数整理层

即便这次 E 已经改成两阶段：

- `proof_plan`
- `proof generation`

但从成功样本和失败样本看，`theorems_to_apply` 基本为空，说明：

- planner 还没有稳定输出“要调用哪些 theorem”
- generator 也还没有真正把 theorem application 变成 proof 主骨架

这直接限制了：

- 动能定理
- 拉格朗日方程
- 动量矩复杂题

这类需要中间量和结构化物理推导的题。

## 8. 下一步修改建议

### 建议 1：优先打通“可编译的 MechLib 最小接口”

当前不该继续泛泛强调“多用库”，而应先明确一小批高频、稳定、可编译的 theorem 接口。

建议做法：

- 先从理论力学 14 题里涉及最多的定理出发，整理一个小型白名单：
  - 动量定理
  - 功能定理/动能定理
  - 角动量/动量矩相关关系
- 对每条 theorem 提供：
  - 稳定 theorem 名
  - 真实 Lean 签名
  - 最小可工作的调用样例

在没有这层稳定接口前，单纯加大 `MechLib` 注入不会带来真正使用率提升。

### 建议 2：B 阶段要区分“题干直译 statement”和“库驱动 statement”

当前这两类 statement 混在一起竞争，结果往往是：

- 库驱动版本更物理，但更不稳定
- Real 版更容易编译，于是最终胜出

建议后续显式区分：

- 题干直译候选
- 库定理驱动候选

然后在 D 中做同类比较，而不是简单混排。

### 建议 3：E planner 需要强制给出 theorem application

现在两阶段 proof 还不够强，下一步应继续收紧：

- 对物理定律题，若 `theorems_to_apply` 为空，则 plan 直接降级
- 若 plan 只写“代数化简”，则在 law problem 上视为低质量计划

这样才能真正逼 E 从“整理公式”走向“先搭物理证明骨架”。

### 建议 4：A 阶段需要补强理论力学目标抽取

本次 `momentum_theorem_basic_01` 和 `mechanical_vibration_basic_13` 直接死在 `A`。

说明这套 A prompt / schema 还是偏向现有 Lean4Phys 的基础题风格，对理论力学题中的：

- 多目标输出
- 过程性目标
- “写出方程并求条件”类型目标

支持不够。

如果 A 不稳定，后面的 B/D/E 再强也会被前置误抽取拖住。

## 9. 结论

这次 14 题理论力学测试给出的结论很清楚：

1. 当前主 pipeline 已经具备在理论力学小样本上工作的基础能力，但总体成功率仍低，端到端仅 `3/14`。
2. 主瓶颈是：
   - `D` 前的 statement 弱化/漂移
   - `E` 的 theorem-first proof 仍未真正落地
3. 新增的 MechLib 使用统计已经证明：当前系统虽然“运行在 MechLib 环境中”，但并没有真正把检索到的库定理稳定转化为最终 statement 和 proof。
4. 下一阶段最重要的工作不是继续堆检索文本，而是先打通一条“小而稳定的 MechLib 定理调用链”，让 B 能生成、C 能编译、D 能偏好、E 能应用。

一句话总结：

当前 pipeline 已经能看见“用库”的方向，但还没有真正进入“靠库做题”的阶段。
