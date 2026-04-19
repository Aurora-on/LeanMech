# 项目中期报告（2026-04-10）

## 一、项目概述

本项目的目标是构建一条面向力学题自动形式化与 Lean 校验的可复现流水线。系统输入自然语言题目，输出结构化的物理问题表示、Lean 定理候选、Lean 编译结果、语义筛选结果、证明尝试与最终归档报告。项目当前已经完成从题面到 Lean 文件导出的端到端基线，并针对 `LeanPhysBench` 的 `mechanics` 子集与自建理论力学小样本集进行了多轮真实 API 实验。

当前项目的主线流程为：

```text
题目输入
  -> A Grounding
  -> MechLib 检索
  -> B Statement Generation
  -> C Lean Compile Check
  -> D Semantic Rank
  -> E Proof Search / Repair
  -> F Metrics / Analysis / Export
```

代码主目录位于 [src/mech_pipeline](f:/AI4Mechanics/coding/pipeline1/src/mech_pipeline)，当前已经完成：

- 真实 Lean 环境接入
- `MechLib` / `Mathlib` 工作区导出
- `B-C-D` 单轮反馈闭环
- 题目级并发执行
- 细粒度错误归档与报告生成
- 无 MechLib 检索信息的独立消融入口

---

## 二、已有研究成果

### 1. MechLib

#### 1.1 MechLib 本体已经接入项目

当前本地 `MechLib` 路径为：

- [F:/AI4Mechanics/coding/MechLib](f:/AI4Mechanics/coding/MechLib)

项目已经完成以下接入工作：

- LeanRunner 支持 `mechlib` backend
- preflight 能检测 `PhysLean + MechLib` 环境
- run 完成后可导出可直接打开的 Lean workspace
- 导出 workspace 会显式接入本地 `MechLib`，并在可用时显式接入本地 `mathlib`

相关代码位置：

- [lean_runner.py](f:/AI4Mechanics/coding/pipeline1/src/mech_pipeline/adapters/lean_runner.py)
- [rendering.py](f:/AI4Mechanics/coding/pipeline1/src/mech_pipeline/rendering.py)
- [lakefile.toml](f:/AI4Mechanics/coding/pipeline1/lakefile.toml)

#### 1.2 MechLib 内容规模已经具备初步研究价值

对本地 `MechLib` 代码树做静态统计后，当前可见的核心 Lean 文件共 `15` 个，其中力学相关主模块包括：

- `Mechanics/AnalyticalMechanics.lean`
- `Mechanics/CentralForce.lean`
- `Mechanics/DampedSHM.lean`
- `Mechanics/Dynamics.lean`
- `Mechanics/Kinematics.lean`
- `Mechanics/MomentumImpulse.lean`
- `Mechanics/Rotation.lean`
- `Mechanics/SHM.lean`
- `Mechanics/SystemDynamics.lean`
- `Mechanics/WorkEnergy.lean`

同时，本地 theorem corpus 文件：

- [theorem_corpus.jsonl](f:/AI4Mechanics/coding/MechLib/theorem_corpus.jsonl)

当前共有 `182` 条索引项。按模块统计，条目数较多的部分包括：

- `MechLib.SI`: `28`
- `MechLib.Mechanics.Kinematics`: `24`
- `MechLib.Mechanics.DampedSHM`: `21`
- `MechLib.Units.Quantity`: `20`
- `MechLib.Mechanics.CentralForce`: `15`
- `MechLib.Mechanics.SystemDynamics`: `14`
- `MechLib.Mechanics.AnalyticalMechanics`: `11`

这说明 `MechLib` 已经不是空壳环境，而是具备实际物理定理、单位体系和分析力学模块的可用知识库。

#### 1.3 已完成 MechLib 检索适配

项目中已实现一个面向 `MechLib` 的检索器：

- [knowledge/mechlib.py](f:/AI4Mechanics/coding/pipeline1/src/mech_pipeline/knowledge/mechlib.py)

它当前支持：

- 基于 theorem corpus 的摘要注入
- 源条目检索
- 标签筛选
- 领域上下文拼装
- 缓存落盘

相关输出会写入：

- `mechlib_retrieval.jsonl`

这意味着系统已经具备“题目 -> 物理领域 -> MechLib 候选定理/定义”的基本桥接能力。

#### 1.4 当前关于 MechLib 的关键研究结论

截至目前，项目已经证明了两件事：

1. 系统可以稳定运行在 `MechLib` 环境中；
2. `MechLib` 检索信息对部分 benchmark 有一定帮助。

但尚未证明第三件更强的事情：

- **生成的 Lean 代码已经系统性地复用了 MechLib 中的现成定理。**

根据最新分析报告 [MECHLIB_USAGE_AND_ABLATION_20260409.md](f:/AI4Mechanics/coding/pipeline1/reports/MECHLIB_USAGE_AND_ABLATION_20260409.md)，最近一次完整 14 题理论力学 run 中虽然：

- `mechlib_header_rate = 1.0`
- `selected_mechlib_candidate_rate = 1.0`

但对导出 Lean 文件和 proof 中间文件逐题核查后，`14/14` 个样本都没有发现“检索到的 MechLib 符号名在最终正文中出现”的证据。当前更准确的表述应是：

- “项目已经接入并运行于 MechLib 环境，并接收 MechLib 检索提示”

而不是：

- “项目已经稳定复用了 MechLib 定理来完成建模和证明”

这是当前中期阶段最重要的事实判断之一。

---

### 2. pipeline

#### 2.1 已形成完整的 A-F 基线流水线

当前 pipeline 已经不是零散脚本，而是一条完整的、可反复运行的实验流水线。核心模块包括：

- [A_grounding.py](f:/AI4Mechanics/coding/pipeline1/src/mech_pipeline/modules/A_grounding.py)
- [B_statement_gen.py](f:/AI4Mechanics/coding/pipeline1/src/mech_pipeline/modules/B_statement_gen.py)
- [C_compile_check.py](f:/AI4Mechanics/coding/pipeline1/src/mech_pipeline/modules/C_compile_check.py)
- [D_semantic_rank.py](f:/AI4Mechanics/coding/pipeline1/src/mech_pipeline/modules/D_semantic_rank.py)
- [E_prover.py](f:/AI4Mechanics/coding/pipeline1/src/mech_pipeline/modules/E_prover.py)
- [F_report.py](f:/AI4Mechanics/coding/pipeline1/src/mech_pipeline/modules/F_report.py)

项目当前能够完成以下完整链路：

- 从自然语言题目抽取 `Problem IR`
- 生成 Lean theorem 候选
- 用真实 Lean 环境编译候选
- 对候选做规则+LLM 联合语义筛选
- 对选中 theorem 生成和修复 proof
- 导出 run 报告、指标和可打开的 Lean workspace

#### 2.2 已完成 B-C-D 闭环机制

当前系统在 `B -> C -> D` 之间已经实现单轮反馈闭环：

- round 0 正常生成/编译/语义排序
- 若 `no_compile_pass` 或 `semantic_fail`
- 则将结构化反馈回送给 B
- B 在 round 1 重新生成候选
- round 1 作为最终轮

这套机制已落地在：

- [orchestrator.py](f:/AI4Mechanics/coding/pipeline1/src/mech_pipeline/orchestrator.py)
- [rendering.py](f:/AI4Mechanics/coding/pipeline1/src/mech_pipeline/rendering.py)

并且反馈内容已经不是早期的粗摘要，而是包含：

- C 阶段编译错误结构化信息
- D 阶段语义错位信息
- `sub_error_type`
- `failure_summary`
- `failure_tags`
- `mismatch_fields`
- `missing_or_incorrect_translations`
- `suggested_fix_direction`

#### 2.3 已完成 D 阶段的语义等价区分

当前 D 阶段不再简单用“字面形式是否一致”判断目标是否对齐，而是区分：

- `exact`
- `equivalent`
- `special_case`
- `weaker`
- `drift`

这项修改的研究意义在于：

- 能区分“表面形式不同但语义等价”和“真正的 target drift”
- 避免把等价变形误判为错题
- 为后续引入 proofability bias 和库定理优先级打下基础

#### 2.4 已清理一类对研究无价值的 fallback

项目早期曾在 B 阶段生成伪造 `fallback theorem`。这一行为已经被移除。当前 B 阶段不再人为制造 `fallback_goal` 之类的占位命题，避免污染实验结果。

同时，E 阶段中无意义的裸 tactic fallback 也已经停用，不再自动追加：

- `rfl`
- `simp`
- `aesop`
- `linarith`
- `ring`

这两类修改的意义是：

- 结果更真实
- 失败更可诊断
- 不会再用无研究价值的“伪成功”掩盖真实问题

#### 2.5 已支持题目级并发与实时进度

当前项目支持题目级并发执行，配置项为：

- `runtime.sample_concurrency`

当前上限限制为 `10`。并发机制的特点是：

- 并发粒度是题目，不是候选
- 单题内部依然保持 `A -> B -> C -> D -> E`
- 主线程统一汇总和写盘
- 输出顺序保持稳定
- 终端实时显示 `progress: k/N completed`

相关实现已从旧的超大 [cli.py](f:/AI4Mechanics/coding/pipeline1/src/mech_pipeline/cli.py) 中拆出，当前主要逻辑位于：

- [cli.py](f:/AI4Mechanics/coding/pipeline1/src/mech_pipeline/cli.py)
- [orchestrator.py](f:/AI4Mechanics/coding/pipeline1/src/mech_pipeline/orchestrator.py)
- [rendering.py](f:/AI4Mechanics/coding/pipeline1/src/mech_pipeline/rendering.py)

#### 2.6 已完成产物管理与仓库结构清理

当前项目已经完成一轮结构清理：

- 新增归档脚本 [archive_cleanup.py](f:/AI4Mechanics/coding/pipeline1/src/mech_pipeline/archive_cleanup.py)
- 历史测试过程文件已迁入 `rubbish/`
- `outputs/latest/` 轻量化，不再复制 `.pipeline1_tmp`、`lean_compile`、`lean_proof`
- 完整调试产物只保留在对应 `runs/` 目录

这使得项目从“实验脚本堆积”进入了“可维护实验仓库”的状态。

---

### 3. 实验

#### 3.1 LeanPhysBench mechanics 全量实验

当前最重要的正式 benchmark 是：

- [20260405_214834_mechanics101-realapi-par10-20260405-full](f:/AI4Mechanics/coding/pipeline1/runs/20260405_214834_mechanics101-realapi-par10-20260405-full)

这是 `LeanPhysBench` 中 `mechanics` 子集的 `101` 题全量运行，使用真实 API，并发 `10`。

其关键指标为：

- `grounding_success_rate = 0.970297`
- `statement_generation_success_rate = 0.960396`
- `lean_compile_success_rate = 0.886427`
- `semantic_consistency_pass_rate = 0.765957`
- `proof_success_rate = 0.428571`
- `end_to_end_verified_solve_rate = 0.415842`

对应绝对计数为：

- grounding 成功：`98 / 101`
- statement 成功：`97 / 101`
- compile 成功：`94 / 101`
- semantic 成功：`72 / 101`
- proof 成功：`42 / 101`
- e2e 成功：`42 / 101`

这说明项目当前已经具备在完整 benchmark 上稳定跑通、并取得约 `41.6%` 端到端成功率的能力。

#### 3.2 理论力学 14 题专项实验

为弥补 `LeanPhysBench` 在理论力学方向覆盖不足的问题，项目已自建 14 题小型理论力学样本集：

- [bench_theoretical_mechanics_14_20260407.json](f:/AI4Mechanics/coding/pipeline1/fixtures/bench_theoretical_mechanics_14_20260407.json)

覆盖主题包括：

- 动量定理
- 动能定理
- 角动量定理
- 动量矩定理
- 达朗贝尔原理
- 拉格朗日方程
- 机械振动基础

正式 run：

- [20260407_123429_theoretical-mechanics-14-realapi-par10-20260407](f:/AI4Mechanics/coding/pipeline1/runs/20260407_123429_theoretical-mechanics-14-realapi-par10-20260407)

关键指标为：

- `grounding_success_rate = 0.928571`
- `statement_generation_success_rate = 0.928571`
- `lean_compile_success_rate = 0.884615`
- `semantic_consistency_pass_rate = 0.923077`
- `proof_success_rate = 0.384615`
- `end_to_end_verified_solve_rate = 0.357143`

对应绝对计数为：

- grounding：`13 / 14`
- statement：`13 / 14`
- compile：`13 / 14`
- semantic：`12 / 14`
- proof：`5 / 14`
- e2e：`5 / 14`

这说明项目对理论力学基础题已有初步处理能力，但证明阶段仍明显偏弱。

#### 3.3 MechLib 信息消融实验

项目已经完成一项关键消融：

- 不提供 MechLib 检索信息
- 保留 MechLib backend 与头文件环境

为此新增了独立入口：

- [cli_ablate_no_mechlib.py](f:/AI4Mechanics/coding/pipeline1/src/mech_pipeline/cli_ablate_no_mechlib.py)

结果如下。

**对 14 题理论力学集：**

- 基线：`5 / 14`
- 消融：`5 / 14`

端到端成功数不变。

**对 101 题 mechanics 全量集：**

- 基线：`42 / 101`
- 消融：`38 / 101`

端到端成功数下降 `4` 题。

这说明：

- MechLib 检索信息在 101 题 benchmark 上是有帮助的
- 但在当前 14 题理论力学集上帮助并不显著
- 更重要的是，当前帮助方式更像“提供建模提示”，而不是“直接复用库定理”

#### 3.4 并发加速实验

项目已完成题目级并发 benchmark，详见：

- [CONCURRENCY_BENCHMARK_20260331.md](f:/AI4Mechanics/coding/pipeline1/reports/CONCURRENCY_BENCHMARK_20260331.md)

代表性结果：

- 4 题串行：`866.42s`
- 4 题并发 4：`414.51s`

总耗时下降约 `52.16%`，加速比约 `2.09x`。

这证明并发机制不是形式上的，而是真正带来了实验吞吐的提升。

#### 3.5 单题排障实验

项目还完成了若干具有代表性的单题复盘：

- [MECHANICS20_SINGLE_RETEST_20260404.md](f:/AI4Mechanics/coding/pipeline1/reports/MECHANICS20_SINGLE_RETEST_20260404.md)
- [COMPETITION_CH1_Q10_SINGLE_RETEST_20260404.md](f:/AI4Mechanics/coding/pipeline1/reports/COMPETITION_CH1_Q10_SINGLE_RETEST_20260404.md)
- [COMPETITION_CH1_Q10_NO_FALLBACK_FIX_20260404.md](f:/AI4Mechanics/coding/pipeline1/reports/COMPETITION_CH1_Q10_NO_FALLBACK_FIX_20260404.md)

这些排障工作已经直接推动了：

- B 阶段移除伪造 fallback
- D 阶段引入 target equivalence 区分
- 竞争题样本的语义判定改善

说明项目当前已进入“问题驱动修正 -> 单题验证 -> 回到全量 benchmark”这一正常研究循环。

---

## 三、当前存在的问题和拟解决方法

### 问题 1：MechLib 检索已接入，但尚未形成“真实库定理复用”

#### 现象

当前项目在形式上已经大量使用 MechLib：

- `import MechLib`
- `mechlib` backend
- `mechlib_retrieval.jsonl`

但从最新核查结果看，生成的 Lean 正文多数仍停留在：

- `Real` 变量
- 手工物理关系式
- 通用代数 tactic

而没有真正把检索到的 `MechLib` 定理名落到 theorem/proof 正文中。

#### 影响

- `mechlib_header_rate` 等指标会高估当前“库复用程度”
- 检索信息对研究问题的帮助不够可解释
- 项目难以验证“MechLib 是否真的提升了形式化能力”

#### 拟解决方法

1. 新增显式指标：
   - `retrieved_symbol_hit_rate`
   - `actual_mechlib_symbol_usage_rate`
   - `retrieval_to_selected_overlap_rate`
2. 修改 B 阶段 prompt 与后处理：
   - 当检索命中明确 theorem/definition 时，优先生成“显式引用库符号”的候选
3. 修改 D 阶段排序：
   - 在语义都对时，优先保留真正使用检索符号的候选
4. 修改 E 阶段：
   - 针对“已显式引用库符号”的候选，优先尝试 `rw` / `simpa` / `have` 风格的库定理驱动 proof

---

### 问题 2：检索主题与题目主题仍有错位

#### 现象

从 14 题理论力学集的 `mechlib_retrieval.jsonl` 看：

- 动量定理题常被拉向 `Kinematics`
- 角动量题也频繁命中 `Kinematics`
- 拉格朗日和振动题虽然偶尔命中 `AnalyticalMechanics` / `DampedSHM`，但稳定性不够

#### 影响

- 即使后续强制 B 使用库符号，也可能用错领域
- 检索信息对 theorem 生成的价值被稀释
- 理论力学题尤其容易被拉回初等运动学表述

#### 拟解决方法

1. 重新设计 A -> retrieval 的 law/tag 映射：
   - 动量定理优先 `MomentumImpulse`
   - 动量矩/角动量优先 `Rotation`
   - 拉格朗日优先 `AnalyticalMechanics`
   - 振动优先 `SHM` / `DampedSHM`
2. 在 `MechLibRetriever` 中加入主题白名单加权
3. 报告中增加“检索主题命中率”统计，避免只看 top-k 而不知道是否对题

---

### 问题 3：当前主瓶颈已经转移到 E 阶段 proof

#### 现象

在 101 题全量 benchmark 中：

- semantic 成功：`72 / 101`
- proof 成功：`42 / 101`

说明至少有 `30` 题是“命题基本对了，但 proof 没做出来”。

从已有分析中看，proof 失败主要集中在：

- `wrong_tactic_strategy`
- `goal_shape_mismatch`
- `missing_intermediate_fact`

#### 影响

- 系统上游进步无法转化为 end-to-end 提升
- `competition` 子集尤其受限
- 继续只改 B/D，收益会越来越小

#### 拟解决方法

1. 把 E 阶段从“统一 prompt + 统一 repair”改成按失败类型分路由：
   - 代数化简型
   - 中间结论缺失型
   - 目标形状不匹配型
2. 建立 proof failure cluster 清单，先针对 `semantic_ok but proof_fail` 样本集中迭代
3. 对成功 proof 进行模板沉淀，反向用作 repair few-shot 样例

---

### 问题 4：理论力学样本集规模还太小

#### 现象

当前理论力学专项集只有 `14` 题，虽然覆盖了多个主题，但难度层次和表述风格还不够丰富。

#### 影响

- 难以稳定评估项目对理论力学的真实能力
- 单次 run 的波动对结论影响过大
- 无法支撑更细的误差统计

#### 拟解决方法

1. 扩充专项数据集：
   - 每类至少扩展到 `5-10` 题
   - 增加不同叙述风格、不同未知量位置、不同推导深度
2. 增加中英文平行题面版本
3. 将理论力学集纳入固定 benchmark，而不是一次性实验夹具

---

### 问题 5：D 阶段虽然已改进，但仍存在“语义正确但证明不友好”的候选选择问题

#### 现象

当前 D 阶段已经能区分 `exact / equivalent / drift`，但仍可能出现：

- 语义上可接受
- 证明上不够友好
- 最终导致 E 更难接住

#### 影响

- semantic 指标看起来不错
- e2e 指标却提不上去
- 上游与下游优化脱节

#### 拟解决方法

1. 强化 proofability bias
2. 在 D 中加入“是否调用检索库符号”的偏好
3. 明确惩罚：
   - 不必要的存在量
   - 过弱命题
   - 不利于 `rw` / `linarith` / `field_simp` 的目标形状

---

### 问题 6：当前指标体系仍未完全覆盖研究关注点

#### 现象

目前常见指标包括：

- grounding success
- statement success
- compile success
- semantic success
- proof success
- e2e success

这些指标能反映总体效果，但对研究问题“项目是否真的借助物理库完成自动形式化”还不够。

#### 拟解决方法

新增一组研究导向指标：

- 真实库符号使用率
- 检索-候选重合率
- 闭环恢复率
- 语义正确但 proof 失败率
- 主题级命中率

这会使项目从“工程上能跑”进一步转向“研究上能解释”。

---

## 四、阶段性判断

截至中期阶段，可以做出以下较稳妥的判断：

1. 项目已经完成了一个**可运行、可复现、可诊断**的自动形式化基线。
2. `MechLib` 已在工程层面成功接入，并具备检索和 Lean 工作区导出能力。
3. 全量 benchmark 已经可以稳定运行，端到端成功率达到 `42 / 101`。
4. 理论力学方向已经有专项样本和专项实验，但当前证明能力仍偏弱。
5. 目前最关键的研究瓶颈不再是“能不能跑起来”，而是：
   - 是否真正用到了 `MechLib`
   - 检索是否对题
   - proof 阶段如何把正确命题真正证明出来

换句话说，项目已经从“系统搭建阶段”进入“能力兑现阶段”。后续工作的重点应该从基础设施继续转向：

- 检索质量
- 库定理复用
- proof 能力提升
- 理论力学专项评测扩展

---

## 五、后续工作重点

下一阶段建议按以下顺序推进：

1. 为项目新增“真实 MechLib 使用率”指标，并落到报告中。
2. 调整 B 阶段，使候选能够显式引用检索到的库定理。
3. 调整 D 阶段，使其在语义对齐时优先选择“既对题又用库”的候选。
4. 重构 E 阶段 proof 策略，优先解决 `semantic_ok but proof_fail` 样本。
5. 扩充理论力学专项数据集，使其能支撑更稳定的研究结论。

如果这五项推进顺利，项目的下一阶段目标就可以从“中期基线系统”转向“具备明确物理库复用能力的研究型自动形式化系统”。
