# MechLib 更新后真实 API 运行逐题错误报告

运行目录：

`runs/20260515_171114_minimal-v2-mixed-mechlib-update-20260515_171113`

配置文件：

`tmp/minimal_testset_v2_mixed_legacy_proof.yaml`

运行设置：

- 测试集：mixed v2，共 33 题
- 模型：`gpt-5.4`
- API：`https://api.openai-proxy.org`
- 并发：5
- B 阶段模式：`minimal_skeleton`
- 证明阶段模式：`legacy_full_proof`

总体结果：

- 编译通过：17/33
- 语义通过：13/33
- 证明通过：2/33
- 证明成功样本：`Mechanics_76`、`archive_part1_7_1`

说明：

部分样本在 `sample_summary.jsonl` 中显示为 `final_error_type=elaboration_failure`，但实际根因并不一定是 Lean 后端编译失败。很多样本是在 C 阶段之前就被阻塞，例如上游草图审计失败、canonical target 非法、函数型公式非法、skeleton audit 失败等。下表按实际链路根因重新归类。

## 逐题诊断

| 序号 | 样本 | 最终阶段 | 主要原因 | 归因环节 |
|---:|---|---|---|---|
| 1 | `Mechanics_3` | B/A2/Sketch 阻塞 | `upstream_sketch_audit_failed`；“速度是位置函数导数”这一关系在当前实例中仍没有可用的模型谓词绑定。目标涉及 `Time -> Length/Speed` 函数型物理量，导数关系仍然只能作为 explicit gap。 | A2 + EvidenceBinder + Sketch |
| 2 | `Mechanics_16` | B/A2/Sketch 阻塞 | `upstream_sketch_audit_failed`；由速度分量求加速度分量的导数关系没有单一可用的 Lean-like 方程绑定。Sketch 还把 `given_time_value` 判为 target leakage。 | A2 + SketchAudit + EvidenceBinder |
| 3 | `Mechanics_31` | E/证明失败 | 编译和语义均通过，但旧证明脚本失败：`rewrite` 在 `v_top.val ^ 2 = ...` 中找不到可重写的 `0`。证明脚本的等式方向与可用假设不匹配。 | E 证明 |
| 4 | `Ch2_Q2` | D/语义失败 | theorem 给出了最终公式，但 D 判断两种摩擦方向 case 的处理错误，候选似乎把两个分支的符号条件混在一起。 | A2/Sketch 分支建模 |
| 5 | `Mechanics_76` | 通过 | 编译、语义和旧证明均通过。 | 无 |
| 6 | `Mechanics_74` | E/证明失败 | 编译和语义均通过；旧证明脚本有语法错误：`unexpected token 'using'; expected ':='`。 | E 证明语法 |
| 7 | `Ch2_Q1` | B/A2 阻塞 | `invalid_function_formula_ir`；capstan / 缠绕角关系和两端张力已被识别，但函数/公式规范化阻塞了 theorem skeleton 生成。 | A2 target / formula 规范化 |
| 8 | `Mechanics_73` | E/证明失败 | 编译和语义均通过；旧证明阶段 type mismatch。skeleton 本身可用，但当前证明脚本无法 replay Atwood 代数和建模假设。 | E 证明 |
| 9 | `Mechanics_71` | D hard gate / B 问题 | D 认为主要物理语义基本正确，但因 `derived_equation_hypothesis_violation` / unsupported claim 拒绝。核心是 B 把派生/建模方程放在了不合适的位置。 | B hypothesis policy / Sketch |
| 10 | `Ch1_Q11` | B/A2/Sketch 阻塞 | `upstream_sketch_audit_failed`；ModelIR 中 `x_A`、`x_B_parallel`、`y_B`、`r_sq` 等局部函数定义没有被完整解析和审计。相对运动与最小距离模型缺少 verified binding。 | A2 函数定义 + Sketch |
| 11 | `Ch3_Q1` | E/证明失败 | 编译和语义均通过；证明阶段留下弹簧平衡 / 简谐运动代数目标未解。 | E 证明 |
| 12 | `archive_part1_2_3` | B/A2 target 阻塞 | target 写成 `F2 = <Real expression>`，但 `F2 : Force`；应改成 value-level 的 `F2.val = ...`，或使用专门的力大小方程。同时平面分量平衡绑定仍不能直接使用。 | A2 CanonicalTarget + B 公式类型 |
| 13 | `archive_part1_9_1` | E/证明失败 | 编译和语义均通过；旧证明在倾斜弯道/摩擦代数中出现 application type mismatch。 | E 证明 |
| 14 | `archive_part1_9_11` | B/A2/Sketch 阻塞 | `upstream_sketch_audit_failed`；时变力 Newton 关系，以及 `deriv v = a`、`deriv x = v` 这类函数型关系缺少可用模型谓词绑定。 | A2 函数公式 + EvidenceBinder |
| 15 | `archive_part1_5_10` | D hard gate / B 问题 | D 认为没有主要语义错误，但标记 `candidate_answer_hypothesis_violation` / unsupported claim。同时候选缺少显式数值求值，没有完整利用速度分量推出速度大小。 | B 泄漏 gate + Sketch 代数目标 |
| 16 | `archive_part1_6_6` | E/证明失败 | MechLib 更新后已能编译和语义通过；证明阶段仍留下滑轮无滑动、旋转点切向/法向加速度相关代数目标。 | E 证明 |
| 17 | `archive_part1_7_1` | 通过 | 编译、语义和旧证明均通过。 | 无 |
| 18 | `archive_part1_10_2` | D/语义失败 | 候选只推出了含 `v_open` 的空气阻力中间式，没有从完整 givens 消元得到题目要求的最终阻力大小。 | A2 target + Sketch 代数目标 |
| 19 | `archive_part1_10_4` | B skeleton audit | `raw_law_equation_in_hypotheses`；质量关系 / 位移定义被处理得太像 theorem hypotheses 或 law equation。 | B/Sketch hypothesis 分类 |
| 20 | `archive_part1_10_8` | B skeleton audit | `raw_law_equation_in_hypotheses`；target identification 和质量/重量关系仍作为 explicit given gap 进入，而不是留在受控 proof obligation 中。 | B/Sketch hypothesis 分类 |
| 21 | `archive_part1_11_1` | C/Lean 语法失败 | theorem 进入编译路径，但 Lean 报 `unexpected token '('; expected ')'`。同时平面角动量公式和坐标导数关系仍是 explicit gap。 | B 公式 assembler + A2 函数语法 |
| 22 | `archive_part1_11_4` | E/证明失败 | 编译和语义均通过；证明阶段 `linarith` 无法关闭矛盾或代数侧条件。 | E 证明 |
| 23 | `archive_part1_11_9` | B/A2 阻塞 | `invalid_function_formula_ir`；转动动力学和阻尼力矩已被识别，但函数型角速度/角加速度公式还不能被合法组装。 | A2 函数 target + formula normalizer |
| 24 | `archive_part1_11_23` | E/证明失败 | 编译和语义均通过；证明脚本出现 `No goals to be solved`，说明 tactic 顺序和当前 proof state 不匹配。 | E proof control |
| 25 | `archive_part1_12_1` | E/证明失败 | 编译和语义均通过；功-能、力矩做功、重力做功相关代数目标未能证明。 | E 证明 |
| 26 | `archive_part1_12_7` | B/A2 target 阻塞 | `tautological_canonical_target`；ModelIR 的 canonical target 缺失或变成重言式，B 正确选择阻塞，没有猜一个假 theorem。 | A2 CanonicalTarget |
| 27 | `archive_part1_13_3` | E/证明失败 | 编译和语义均通过；小车-物块-悬挂物系统的代数证明在 simplification 后 type mismatch。 | E 证明 |
| 28 | `archive_part2_1_9` | B/A2/Sketch 阻塞 | `invalid_function_formula_ir` 和 `upstream_sketch_audit_failed`；摆线式函数参数化和功-能关系没有规范化成合法 pointwise 公式。 | A2 函数 target + Sketch |
| 29 | `archive_part2_1_16` | B/A2 target 阻塞 | 公式中使用了非正式占位符 `x_ddot`、`phi_dot`、`phi_ddot`；缺少明确的导数算子和 typed function formula。 | A2 函数语义 |
| 30 | `archive_part2_4_2` | E/证明失败 | 编译和语义均通过；证明阶段仍有未解目标。 | E 证明 |
| 31 | `archive_part2_4_5` | B/A2 target 阻塞 | `missing_canonical_target`；ModelIR parse failed，B 正确阻塞并输出 `False`，没有猜测目标。 | A2 CanonicalTarget |
| 32 | `archive_part2_5_8` | Evidence gap / B 阻塞 | `blocked_by_evidence_gap`；角速度分解 / 进动关系缺少可用 verified binding。重言式约束已被排除。 | EvidenceBinder + MechLib API |
| 33 | `archive_part2_6_6` | B/A2/Sketch 阻塞 | `upstream_sketch_audit_failed` 和 target leakage；推力 `mdot * v_rel`、变质量受力平衡、速度导数关系都仍是 explicit gap。 | A2 + EvidenceBinder + SketchAudit |

## 横向问题归类

### A2 / CanonicalTarget / 函数型公式问题

影响样本：

- `Mechanics_3`
- `Mechanics_16`
- `Ch2_Q1`
- `Ch1_Q11`
- `archive_part1_9_11`
- `archive_part1_11_9`
- `archive_part1_12_7`
- `archive_part2_1_9`
- `archive_part2_1_16`
- `archive_part2_4_5`
- `archive_part2_6_6`

典型症状：

- `invalid_function_formula_ir`
- `missing_canonical_target`
- `tautological_canonical_target`
- 出现 `x_ddot`、`phi_dot`、`phi_ddot` 等非正式导数占位符
- 函数型物理量没有转换成合法的 pointwise Lean 公式

### B / Sketch 假设分类问题

影响样本：

- `Mechanics_71`
- `archive_part1_5_10`
- `archive_part1_10_4`
- `archive_part1_10_8`
- `archive_part1_11_1`

典型症状：

- `raw_law_equation_in_hypotheses`
- `derived_equation_hypothesis_violation`
- `candidate_answer_hypothesis_violation`
- assembler 生成的函数型公式存在 Lean 语法问题

### D 语义 / target 对齐问题

影响样本：

- `Ch2_Q2`
- `archive_part1_10_2`

典型症状：

- 分支 case 错误
- 只得到部分 target
- 只得到中间公式，没有得到题目要求的最终目标

### E 旧证明阶段限制

影响样本：

- `Mechanics_31`
- `Mechanics_74`
- `Mechanics_73`
- `Ch3_Q1`
- `archive_part1_9_1`
- `archive_part1_6_6`
- `archive_part1_11_4`
- `archive_part1_11_23`
- `archive_part1_12_1`
- `archive_part1_13_3`
- `archive_part2_4_2`

典型症状：

- type mismatch
- tactic 顺序错误
- unsolved goals
- 代数侧条件无法自动关闭

这些不应算作 D 之前 pipeline 的失败；它们主要是 `legacy_full_proof` 下的 proof search / proof script replay 问题。

