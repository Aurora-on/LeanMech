# MechLib 使用情况与消融实验报告（2026-04-09）

## 1. 结论摘要

本次先分析了最近一次完整运行：

- 基线 run： [20260407_123429_theoretical-mechanics-14-realapi-par10-20260407](f:/AI4Mechanics/coding/pipeline1/runs/20260407_123429_theoretical-mechanics-14-realapi-par10-20260407)

然后新增了一个独立的消融 CLI：

- 新入口： [cli_ablate_no_mechlib.py](f:/AI4Mechanics/coding/pipeline1/src/mech_pipeline/cli_ablate_no_mechlib.py)

它的定义是：

- 保留现有 Lean / MechLib 后端与头文件策略
- 只关闭 `MechLib` 检索上下文及其注入
- 不修改原有 [cli.py](f:/AI4Mechanics/coding/pipeline1/src/mech_pipeline/cli.py)

核心结论有三点：

1. 最近一次 14 题理论力学 run 虽然 `mechlib_header_rate = 1.0`、`selected_mechlib_candidate_rate = 1.0`，但**没有发现生成的 theorem / proof 正文实际调用检索到的 MechLib 定理名**。
2. 对 14 题理论力学集，去掉 MechLib 检索信息后，端到端成功数**没有变化**，仍然是 `5 / 14`。这说明当前这套题上，模型主要是在 `Real` 代数层面工作，而不是在“借助 MechLib 定理”工作。
3. 对 101 题 Lean4PhysBench mechanics，全量消融后端到端成功数从 `42 / 101` 降到 `38 / 101`，说明 MechLib 检索信息**有一定帮助，但帮助幅度有限**；当前主收益不是“直接调用库定理”，更像是提供了少量主题提示和建模偏置。

## 2. 最近一次 14 题运行中，是否真的使用了 MechLib 定理

### 2.1 先区分两类“用了 MechLib”

当前项目里至少有两种完全不同的“用了 MechLib”：

- 环境层面：
  - `import MechLib`
  - `open MechLib`
  - Lean backend 选择为 `mechlib`
- 实质层面：
  - theorem 声明或 proof 正文里，显式调用 MechLib 中的定义、定理或类型
  - 例如 `velocityConstAccel`、`secondLaw`、`kineticEnergy_change_formula`、`eulerLagrangeResidual1D` 之类的库符号

这次 14 题 run 的 metrics 是：

- `mechlib_header_rate = 1.0`
- `selected_mechlib_candidate_rate = 1.0`

它们只能说明：

- 候选头文件都带了 `import MechLib`
- D 选中的候选都走了 `mechlib` backend

它们**不能**说明：

- 生成的 Lean 代码真的调用了 MechLib 定理

### 2.2 本次核查方法

对 run [20260407_123429_theoretical-mechanics-14-realapi-par10-20260407](f:/AI4Mechanics/coding/pipeline1/runs/20260407_123429_theoretical-mechanics-14-realapi-par10-20260407) 做了两层检查：

1. 读取 [mechlib_retrieval.jsonl](f:/AI4Mechanics/coding/pipeline1/runs/20260407_123429_theoretical-mechanics-14-realapi-par10-20260407/mechlib_retrieval.jsonl)，提取每题检索到的 `symbol_name`
2. 在导出的 Lean 文件和 proof 中间文件里，查找这些符号是否真的出现在正文中

检查范围包括：

- [lean_exports/problems](f:/AI4Mechanics/coding/pipeline1/runs/20260407_123429_theoretical-mechanics-14-realapi-par10-20260407/lean_exports/problems)
- [proof/mechlib tmp files](f:/AI4Mechanics/coding/pipeline1/runs/20260407_123429_theoretical-mechanics-14-realapi-par10-20260407/.pipeline1_tmp/proof/mechlib)

### 2.3 核查结果

结果是：

- `14 / 14` 题都带 `import MechLib`
- `14 / 14` 题 D 选中的候选 backend 都是 `mechlib`
- 但在 14 个样本中，**检索到的 MechLib 符号与最终 Lean 正文的精确命中数是 `0 / 14`**

也就是说：

- 这次 run 的 Lean 代码**运行在 MechLib 环境中**
- 但**没有证据表明它实际调用了检索到的 MechLib 定理**

### 2.4 直接表现

导出的 Lean 文件普遍长这样：

- `import MechLib`
- theorem 参数全部是 `Real`
- proof 主要用 `linarith`、`ring`、`field_simp`、`rw`

例如以下成功样本：

- [theoretical_mechanics_angular_momentum_theorem_basic_05.lean](f:/AI4Mechanics/coding/pipeline1/runs/20260407_123429_theoretical-mechanics-14-realapi-par10-20260407/lean_exports/problems/theoretical_mechanics_angular_momentum_theorem_basic_05.lean)
- [theoretical_mechanics_dalembert_principle_basic_09.lean](f:/AI4Mechanics/coding/pipeline1/runs/20260407_123429_theoretical-mechanics-14-realapi-par10-20260407/lean_exports/problems/theoretical_mechanics_dalembert_principle_basic_09.lean)

它们本质上都是：

- 在 `MechLib` 环境里写 `Real` 代数命题
- 再用通用代数 tactic 证明

而不是：

- 调用 `MechLib.Mechanics.*` 中检索到的物理定理

### 2.5 为什么会这样

这次 14 题理论力学集里，检索结果与题目主题有明显错位或偏浅：

- 动量定理题常检到 `Kinematics`
- 角动量定理题也大量检到 `Kinematics`
- 拉格朗日方程题能检到 `AnalyticalMechanics` 相关条目，但最终生成仍然退回纯 `Real` 关系式

例如：

- 动量定理基础题 top symbols:
  - `vec_velocity_const_accel_eq`
  - `velocity_increment`
  - `displacement_forms_equiv`
- 拉格朗日基础题 top symbols:
  - `eulerLagrangeResidual1D`
  - `eulerLagrange_iff_newton`
  - `radialEquation_eq`

但最终 Lean 代码里并没有出现这些名字。

这说明当前链路的问题不是“MechLib 完全没接上”，而是：

- 检索结果虽然进了 prompt
- 但 B/E 最终没有把这些库符号落到 theorem / proof 里

## 3. 消融实验设置

### 3.1 消融定义

本次“无 MechLib 信息”消融的定义是：

- `knowledge.enabled = False`
- `knowledge.inject_modules = []`
- `statement.with_mechlib_context = False`

即：

- 不给 B / D / E 提供 MechLib 检索上下文
- 但保留现有 Lean / MechLib backend 与头文件策略不变

因此本实验评估的是：

- **MechLib 检索信息**对成功率的影响

而不是评估：

- **彻底移除 MechLib 运行环境**的影响

### 3.2 消融入口

新 CLI：

- [cli_ablate_no_mechlib.py](f:/AI4Mechanics/coding/pipeline1/src/mech_pipeline/cli_ablate_no_mechlib.py)

相关配置：

- 14 题：复用 [theoretical_mechanics_14_proxy_gpt54_20260407.yaml](f:/AI4Mechanics/coding/pipeline1/configs/theoretical_mechanics_14_proxy_gpt54_20260407.yaml)
- 101 题：新增 [mechanics101_proxy_gpt54_20260409.yaml](f:/AI4Mechanics/coding/pipeline1/configs/mechanics101_proxy_gpt54_20260409.yaml)

并发：

- `sample_concurrency = 10`

## 4. 14 题理论力学集：基线 vs 消融

### 4.1 运行目录

- 基线： [20260407_123429_theoretical-mechanics-14-realapi-par10-20260407](f:/AI4Mechanics/coding/pipeline1/runs/20260407_123429_theoretical-mechanics-14-realapi-par10-20260407)
- 消融： [20260409_171638_theoretical-mechanics-14-ablate-no-mechlib-20260409](f:/AI4Mechanics/coding/pipeline1/runs/20260409_171638_theoretical-mechanics-14-ablate-no-mechlib-20260409)

### 4.2 样本级绝对计数

- 基线：
  - grounding 成功：`13 / 14`
  - statement 成功：`13 / 14`
  - compile 成功：`13 / 14`
  - semantic 成功：`12 / 14`
  - proof 成功：`5 / 14`
  - e2e 成功：`5 / 14`
- 消融：
  - grounding 成功：`11 / 14`
  - statement 成功：`11 / 14`
  - compile 成功：`11 / 14`
  - semantic 成功：`10 / 14`
  - proof 成功：`5 / 14`
  - e2e 成功：`5 / 14`

### 4.3 指标层结论

结论非常明确：

- 去掉 MechLib 检索信息后，**端到端成功数没有下降**
- 只是前半段的 grounding / statement / semantic 稍有波动
- 最终 `e2e` 仍然是 `5 / 14`

这与“正文里没有实际调用检索到的 MechLib 定理”完全一致。

换句话说，对这 14 道理论力学题而言，当前 MechLib 检索信息的作用非常有限。

## 5. 101 题 mechanics 全量集：基线 vs 消融

### 5.1 运行目录

- 基线： [20260405_214834_mechanics101-realapi-par10-20260405-full](f:/AI4Mechanics/coding/pipeline1/runs/20260405_214834_mechanics101-realapi-par10-20260405-full)
- 消融： [20260409_173624_mechanics101-ablate-no-mechlib-20260409](f:/AI4Mechanics/coding/pipeline1/runs/20260409_173624_mechanics101-ablate-no-mechlib-20260409)

### 5.2 样本级绝对计数

- 基线：
  - grounding 成功：`98 / 101`
  - statement 成功：`97 / 101`
  - compile 成功：`94 / 101`
  - semantic 成功：`72 / 101`
  - proof 成功：`42 / 101`
  - e2e 成功：`42 / 101`
- 消融：
  - grounding 成功：`98 / 101`
  - statement 成功：`96 / 101`
  - compile 成功：`95 / 101`
  - semantic 成功：`72 / 101`
  - proof 成功：`38 / 101`
  - e2e 成功：`38 / 101`

### 5.3 变化

与基线相比：

- `e2e`：`42 -> 38`，下降 `4` 题
- `proof`：`42 -> 38`，下降 `4` 题
- `semantic`：`72 -> 72`，不变
- `compile`：样本级 `94 -> 95`，基本持平

这说明：

- 去掉 MechLib 检索信息后，最大的损失不在 compile，也不在 semantic
- 主要体现在最后 proof 没做出来

可见 MechLib 检索信息在 101 题 benchmark 上**是有帮助的**，但帮助幅度是“中等偏小”，不是决定性因素。

## 6. 这说明了什么

### 6.1 当前 MechLib 的主要作用，不是“直接被调用”

对最近一次 14 题 run 来看：

- MechLib 主要被当成了一个 backend / 环境标签
- 不是被当成真正的 theorem library 来调用

### 6.2 101 题上的收益，更像“建模偏置”而不是“库定理复用”

因为：

- 去掉检索信息后，semantic 数量几乎不变
- 但 proof 成功数少了 4 题

这更像是：

- 检索上下文给了模型一些建模与证明风格上的提示
- 但最终代码仍然主要靠 `Real` 代数与通用 tactic 完成

而不是：

- 显式调用了 `MechLib` 中的已知物理定理，因而大幅提升成功率

## 7. 下一步最需要修改的方向

### 第一优先级：新增“真实 MechLib 使用率”指标

当前这三个指标会造成误解：

- `mechlib_header_rate`
- `mechlib_compile_pass_rate`
- `selected_mechlib_candidate_rate`

它们反映的是：

- 是否用了 `MechLib` 头文件 / backend

不反映：

- 是否真的调用了 MechLib 定理

建议新增：

- `retrieved_symbol_hit_rate`
  - 最终 Lean 正文中是否出现了检索到的符号名
- `actual_mechlib_symbol_usage_rate`
  - 正文中是否使用了非通用、可识别的 MechLib 符号
- `retrieval_to_selected_overlap_rate`
  - 检索结果与最终选中候选之间的符号重合率

### 第二优先级：强制 B 阶段优先生成“可引用 MechLib 定理”的形式

现在 B 的典型问题是：

- 虽然看了检索上下文
- 但最后仍把题目改写成纯 `Real` 代数关系

建议：

- 当检索命中明确的 theorem / definition 时
- B 不应优先退回纯 `Real` 表述
- 应优先生成“显式引用库对象”的候选

例如：

- 若检到 `secondLaw`
- 候选中至少应有一条显式使用 `secondLaw` 或其等价库接口

### 第三优先级：D 阶段把“是否真正用了检索结果”纳入排序偏置

当前 D 的排序更关注：

- 语义对齐
- compile
- proofability

但没有显式鼓励：

- “使用了与检索结果一致的库符号”

建议：

- 如果两个候选语义都对
- 则优先选“调用了检索命中的 MechLib 符号”的候选

否则检索上下文即使正确，也很难进入最终产物。

### 第四优先级：E 阶段专门做“库定理驱动 proof”

目前 E 还是偏通用代数 tactic：

- `rw`
- `linarith`
- `ring`
- `field_simp`

建议增加一条 proof 路线：

- 若选中候选显式使用了某个 MechLib theorem / definition
- repair prompt 应优先尝试：
  - `rw [that_theorem]`
  - `simpa using ...`
  - `have := ...`

否则即使 B 将来开始显式使用库符号，E 也可能接不住。

### 第五优先级：先处理“检索主题错位”

从 14 题理论力学集看，当前检索主题有明显错位：

- 动量 / 角动量题常被拉向 `Kinematics`
- 理论力学 / 拉格朗日题虽然能检到少量 `AnalyticalMechanics`，但排序不稳定

所以在推动“显式使用 MechLib 定理”之前，先要让检索更像题目本身：

- 动量定理应优先命中 `MomentumImpulse` / `Dynamics`
- 角动量与动量矩应优先命中 `Rotation`
- 拉格朗日与振动应优先命中 `AnalyticalMechanics` / `SHM` / `DampedSHM`

## 8. 最终判断

目前项目已经证明：

- 接入 MechLib 环境是成功的
- MechLib 检索信息对 101 题 benchmark 有一定帮助

但还没有证明：

- 生成的 Lean 代码已经稳定复用了 MechLib 中的现成定理

严格地说，当前更准确的描述应是：

- “项目运行在 MechLib 环境下，并接收 MechLib 检索提示”

而不是：

- “项目已经系统性地使用了 MechLib 定理来完成形式化和证明”

下一阶段如果要把这件事做实，最该改的不是并发，也不是 README，而是：

1. 把“真实库符号使用率”变成显式指标
2. 让 B 真正生成引用库定理的候选
3. 让 D 明确偏好这种候选
4. 让 E 学会围绕这些库定理组织 proof
