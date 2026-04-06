# Mechanics 20 单题复测报告

运行对象：
- 本次 run: `runs/20260404_200021_mechanics20-single-proxy-gpt54-20260404`
- 对比 run: `runs/20260402_175059_mechanics-full-realapi-par10-20260402`
- 数据源：`LeanPhysBench_v0.json` 中 `university_mechanics_Mechanics_20_University`
- 模型：`gpt-5.4`，OpenAI-compatible 代理
- 当前架构：启用 `B/C/D` 闭环能力、细粒度 D 语义诊断、增强版 C/E 失败信息

## 一、结论摘要

这道题在上一次全量实测中没有顺利完成：
- 上次结果：`semantic_ok = true`，`proof_ok = false`
- 上次最终错误：`proof_search_failure`
- 上次触发闭环：`feedback_loop_used = true`
- 上次最终轮次：`final_round_index = 1`

这次在修改后的架构下单题重跑后，结果变为：
- `grounding_ok = true`
- `statement_generation_ok = true`
- `compile_ok = true`
- `semantic_ok = true`
- `proof_ok = true`
- `end_to_end_ok = true`

但要特别指出一个结构性问题：
- 当前 `D` 阶段最终选中的 `c1` 只回答了“平均加速度是多少”
- 它没有回答原题中“速度是增加还是减小”这一半目标
- 尽管如此，`D` 仍将它判为 `semantic_pass = true`

所以这次 run 从系统指标上看是成功的，但从“是否完整回答原题”的角度看，仍然暴露出 `D` 阶段通过条件偏宽的问题。

## 二、原始题目

原始 informal statement：

```text
Question 20 An astronaut has left an orbiting spacecraft to test a new personal maneuvering unit. As she moves along a straight line, her partner on the spacecraft measures her velocity every 2.0 s, starting at time t = 1.0 s: t     vx      t       vx 1.0 s 0.8 m/s 9.0 s  -0.4 m/s 3.0 s 1.2 m/s 11.0 s -1.0 m/s 5.0 s 1.6 m/s 13.0 s -1.6 m/s 7.0 s 1.2 m/s 15.0 s -0.8 m/s Find the average x-acceleration, and state whether the speed of the as- tronaut increases or decreases over each of these 2.0 s time intervals: (d) t1 = 13.0 s to t2 = 15.0 s.
```

原始 formal theorem 目标是：
- 用单位量形式证明平均加速度为 `0.4 m/s^2`
- 题面自然语言还要求判断该区间内速度增减趋势

这意味着完整翻译应至少包含两个目标：
1. 平均 x 加速度数值
2. 速度在 `13s -> 15s` 区间是增大还是减小

## 三、A 模块生成结果

产物文件：
- `runs/20260404_200021_mechanics20-single-proxy-gpt54-20260404/problem_ir.jsonl`

A 模块提取到的核心内容如下。

### 1. 已知量

```json
[
  {"symbol": "t1", "value": 13.0, "unit": "s"},
  {"symbol": "t2", "value": 15.0, "unit": "s"},
  {"symbol": "v_x1", "value": -1.6, "unit": "m/s", "at_time": 13.0},
  {"symbol": "v_x2", "value": -0.8, "unit": "m/s", "at_time": 15.0},
  {"symbol": "delta_t", "value": 2.0, "unit": "s"}
]
```

### 2. 未知目标

```json
{
  "symbol": "average_x_acceleration",
  "description": "average_x_acceleration: a_x_avg over 13.0 s to 15.0 s",
  "extra_targets": [
    {
      "symbol": "speed_trend",
      "description": "speed_trend: whether speed increases or decreases during 13.0 s to 15.0 s"
    }
  ]
}
```

### 3. 关系与约束

```json
{
  "relations": [
    {"equation": "a_x_avg = (v_x2 - v_x1) / (t2 - t1)"},
    {"equation": "speed = |v_x|"}
  ],
  "constraints": [
    "Motion is along a straight line",
    "Consider only the interval from t = 13.0 s to t = 15.0 s",
    "Velocity values are measured in the x-direction"
  ],
  "physical_laws": ["Kinematics"]
}
```

判断：
- A 模块这次提取是正确的
- 它明确识别出了主目标 `average_x_acceleration`
- 也明确识别出了额外目标 `speed_trend`
- 所以后面只回答一半，并不是 A 漏提目标，而是 B/D 后续选择问题

## 四、B 模块生成结果

产物文件：
- `runs/20260404_200021_mechanics20-single-proxy-gpt54-20260404/statement_candidates.jsonl`

这次 B 没有触发 revision，只有 `round_index = 0`。

### Candidate c1

```lean
theorem lean4phys_university_mechanics_Mechanics_20_University_c1_average_x_acceleration_numeric
  (a_x_avg v_x1 v_x2 t1 t2 : Real)
  (hacc : a_x_avg = (v_x2 - v_x1) / (t2 - t1))
  (hv1 : v_x1 = (-((8 : Real) / 5)))
  (hv2 : v_x2 = (-((4 : Real) / 5)))
  (ht1 : t1 = 13)
  (ht2 : t2 = 15)
  : a_x_avg = ((2 : Real) / 5)
```

plan:
```text
Model the tabulated 1D kinematics data in Real, substitute the given velocities and times into the average-acceleration formula, and simplify.
```

### Candidate c2

```lean
theorem lean4phys_university_mechanics_Mechanics_20_University_c2_speed_decreases_from_negative_velocity_data
  (v_x1 v_x2 : Real)
  (hv1 : v_x1 = (-((8 : Real) / 5)))
  (hv2 : v_x2 = (-((4 : Real) / 5)))
  : |v_x2| < |v_x1|
```

plan:
```text
Use the 1D speed relation speed = |v_x| and the given negative velocity values to show the later speed magnitude is smaller.
```

### Candidate c3

```lean
theorem lean4phys_university_mechanics_Mechanics_20_University_c3_positive_average_acceleration_from_velocity_increase
  (a_x_avg v_x1 v_x2 t1 t2 : Real)
  (hacc : a_x_avg = (v_x2 - v_x1) / (t2 - t1))
  (hv1 : v_x1 = (-((8 : Real) / 5)))
  (hv2 : v_x2 = (-((4 : Real) / 5)))
  (ht1 : t1 = 13)
  (ht2 : t2 = 15)
  : 0 < a_x_avg
```

plan:
```text
Compute the numerator and denominator from the given interval data, note both yield a positive quotient, and conclude the average x-acceleration is positive.
```

### Candidate c4

```lean
theorem lean4phys_university_mechanics_Mechanics_20_University_c4_average_acceleration_using_given_delta_t
  (a_x_avg v_x1 v_x2 delta_t : Real)
  (hacc : a_x_avg = (v_x2 - v_x1) / delta_t)
  (hv1 : v_x1 = (-((8 : Real) / 5)))
  (hv2 : v_x2 = (-((4 : Real) / 5)))
  (hdt : delta_t = 2)
  : a_x_avg = ((2 : Real) / 5)
```

plan:
```text
Use the provided interval length directly with the change in x-velocity, avoiding extra time variables, then simplify the quotient.
```

判断：
- B 这次没有生成平凡命题
- 四个候选都和题意有关
- 但四个候选没有一个同时覆盖“加速度 + 速度趋势”两个目标
- 这说明 B 仍然偏向把多目标自然题拆成单目标 theorem，而不是生成完整联合目标

## 五、C 阶段验证结果

产物文件：
- `runs/20260404_200021_mechanics20-single-proxy-gpt54-20260404/compile_checks.jsonl`

这次 `C` 的结果非常干净：四个候选全部编译通过。

| candidate | compile_pass | backend | route | error_type | sub_error_type |
| --- | --- | --- | --- | --- | --- |
| c1 | true | mechlib | auto_import_mechlib | null | null |
| c2 | true | mechlib | auto_import_mechlib | null | null |
| c3 | true | mechlib | auto_import_mechlib | null | null |
| c4 | true | mechlib | auto_import_mechlib | null | null |

结论：
- C 阶段这次没有报错
- 因此没有产生 compile feedback 包
- 也没有因为 compile fail 触发 revision

## 六、D 阶段语义验证结果

产物文件：
- `runs/20260404_200021_mechanics20-single-proxy-gpt54-20260404/semantic_rank.jsonl`

### 1. 最终选择

- `selected_candidate_id = c1`
- `semantic_pass = true`
- `selected_backend = mechlib`
- `retry_triggered = false`
- `retry_feedback_summary = null`

### 2. 各 candidate 的 D 诊断

#### c1

- `semantic_pass = true`
- `sub_error_type = wrong_target`
- `failure_tags = ["partial_answer"]`
- `failure_summary = Correctly computes the average x-acceleration, but does not address the speed-trend part of the original question.`
- `mismatch_fields = ["unknown_target"]`
- `missing_or_incorrect_translations`:
  - The original problem also asks whether the astronaut's speed increases or decreases over the interval, but the theorem only states the acceleration value.
- `suggested_fix_direction`:
  - Keep the acceleration result and add a conclusion about the speed decreasing from 13 s to 15 s.

#### c2

- `semantic_pass = false`
- `sub_error_type = wrong_target`
- `failure_tags = ["partial_answer", "target_mismatch"]`
- `failure_summary = Correctly states that the speed decreases, but leaves out the required average x-acceleration computation.`

#### c3

- `semantic_pass = false`
- `sub_error_type = trivial_goal`
- `failure_tags = ["wrong_target", "partial_answer", "weakened_claim"]`
- `failure_summary = The theorem gives only the sign of the acceleration instead of the requested numerical value and speed trend.`

#### c4

- `semantic_pass = true`
- `sub_error_type = wrong_target`
- `failure_tags = ["partial_answer"]`
- `failure_summary = Correct acceleration result, but missing the speed-trend part of the original question.`

### 3. 关键观察

这是本次 run 最重要的现象：

- D 给 `c1` 和 `c4` 都打了“partial_answer / wrong_target”诊断
- 但同时又把它们判成了 `semantic_pass = true`
- 最终 `c1` 被选中，并进入 E 阶段

这说明当前 D 的逻辑仍存在一个明显缺口：
- 它已经能通过 LLM 识别“少翻译了一部分目标”
- 但这类问题还没有被提升为足够强的 hard gate
- 因此系统会把“部分正确”的 theorem 当成“语义通过”的 theorem

换句话说：
- 这次端到端成功，证明的是 `c1` 可以被证明
- 但并没有证明系统完整回答了原题

## 七、反馈环节的全部内容

本次 run 中，`B/C/D` 闭环没有触发。

具体状态：
- `feedback_loop_used = false`
- `final_round_index = 0`
- `retry_triggered = false`
- `retry_reason = null`
- `retry_feedback_summary = null`

因此这次没有生成“返回给 B 的 revision feedback 包”。原因不是反馈机制失效，而是：
- C 阶段没有 compile fail
- D 阶段虽然识别出了 `wrong_target / partial_answer`
- 但 D 仍把 `c1` 判成 `semantic_pass = true`
- 所以控制流没有进入 revision 分支

这恰好反过来证明：
- 当前反馈信息已经足够细
- 真正的问题变成“这些细信息还没有被用来阻止错误通过”

## 八、E 阶段证明结果与反馈内容

产物文件：
- `runs/20260404_200021_mechanics20-single-proxy-gpt54-20260404/proof_attempts.jsonl`
- `runs/20260404_200021_mechanics20-single-proxy-gpt54-20260404/proof_checks.jsonl`

### Attempt 1

- `attempt_index = 1`
- `compile_pass = false`
- `strict_pass = false`
- `error_type = proof_search_failure`
- `sub_error_type = wrong_tactic_strategy`
- `failure_tags = ["proof_search_failure", "wrong_tactic_strategy"]`

failure_summary:
```text
F:/AI4Mechanics/coding/pipeline1/runs/20260404_200021_mechanics20-single-proxy-gpt54-20260404/.pipeline1_tmp/proof/mechlib/lean4phys-university_mechanics_Mechanics_20_University_c1.lean:19:4: error: 'calc' expression has type ...
```

failure_details:
```json
{
  "error_line": 19,
  "error_message": "'calc' expression has type",
  "error_snippet": ":19:4: error: 'calc' expression has type",
  "stderr_excerpt": "F:/AI4Mechanics/coding/pipeline1/runs/20260404_200021_mechanics20-single-proxy-gpt54-20260404/.pipeline1_tmp/proof/mechlib/lean4phys-university_mechanics_Mechanics_20_University_c1.lean:19:4: error: 'calc' expression has type ..."
}
```

proof_body:

```lean
by
  subst hacc
  subst hv1
  subst hv2
  subst ht1
  subst ht2
  calc
    ((-((4 : Real) / 5)) - (-((8 : Real) / 5))) / (15 - 13)
        = (((8 : Real) / 5) - ((4 : Real) / 5)) / 2 by ring
    _ = ((4 : Real) / 5) / 2 by ring
    _ = (2 : Real) / 5 by ring
```

问题点：
- 使用了 `subst hacc`
- 但 `hacc` 不是适合这样处理的变量等式
- `calc` 内也用了不正确的 `by` 语法位置

### Attempt 2

- `attempt_index = 2`
- `compile_pass = true`
- `strict_pass = true`
- `error_type = null`
- `sub_error_type = null`

proof_body:

```lean
by
  rw [hacc, hv1, hv2, ht1, ht2]
  calc
    ((-((4 : Real) / 5)) - (-((8 : Real) / 5))) / (15 - 13)
        = (((8 : Real) / 5) - ((4 : Real) / 5)) / 2 := by ring
    _ = ((4 : Real) / 5) / 2 := by ring
    _ = (2 : Real) / 5 := by ring
```

修复方向：
- 用 `rw` 替换错误的 `subst`
- 用 `:= by ring` 写成合法的 `calc` step
- 最终 proof 通过

### Final Proof Check

- `proof_success = true`
- `attempts_used = 2`
- `selected_candidate_id = c1`
- `backend_used = mechlib`
- `final_log_path = runs/20260404_200021_mechanics20-single-proxy-gpt54-20260404/lean_proof/lean4phys-university_mechanics_Mechanics_20_University_c1_mechlib.log`

## 九、最终 Lean 产物

导出的完整 Lean 文件：
- `runs/20260404_200021_mechanics20-single-proxy-gpt54-20260404/lean_exports/problems/university_mechanics_Mechanics_20_University.lean`

其内容对应的是：
- D 选中的 `c1`
- E 第 2 次修复后的成功 proof

也就是说，这份导出的 Lean 文件是“当前系统最终认可的答案”。

## 十、最终判断与后续修改建议

### 本次单题复测说明了什么

1. 当前修改后的架构，确实能把这道上次失败的题跑通。
2. E 阶段的 proof repair 在这题上是有效的。
3. C/E 的细粒度失败信息现在已经足够具体，可用于定位真实失败点。
4. 但 D 阶段虽然已经能识别“哪部分没有正确翻译”，却还没有把这类错译真正拦下来。

### 这题暴露出的最关键问题

当前系统把下面这件事当成了“成功”：
- 题目要求：平均加速度 + 速度增减趋势
- 最终 theorem 只证明：平均加速度

这意味着当前 `semantic_pass` 的语义还不够严格。

### 建议的下一步修改

1. 把 `failure_tags` 中的 `partial_answer` 升级为更强约束。
   - 当 A 明确提取出 `extra_targets` 时，如果 theorem 没覆盖，应默认 `semantic_pass = false`
   - 至少不应允许这种候选直接成为最终 selected candidate

2. 把 `sub_error_type = wrong_target` 与 `mismatch_fields = ["unknown_target"]` 接入 hard gate。
   - 当前这些字段已经被 D 输出出来了
   - 但还只是“解释信息”，没有真正改变控制流

3. 对多目标题引入“目标覆盖率”刚性阈值。
   - 当前 `target_match` 仍可能对只覆盖主目标的命题打高分
   - 对 `main target + extra_targets` 结构，应要求 coverage 达到完整覆盖

4. 报表层要把这类“系统判成功但语义仍残缺”的样本单独标出来。
   - 否则端到端成功率会高估系统真实能力

## 十一、最终结论

这次单题复测从工程角度是成功的：
- 它比上次完整
- 它证明了修改后的架构确实提升了这题的通过能力

但从任务正确性角度看，这次结果同样说明了一个更深层的问题：
- 反馈变细了
- 证明也变强了
- 可是 D 仍然允许“部分翻译正确”的 theorem 混进最终成功样本

因此，这次报告最重要的结论不是“Mechanics 20 已经解决”，而是：
- `D` 的细粒度诊断已经够用了
- 下一步必须把这些诊断真正接进筛选与 hard gate，否则系统会继续出现“形式上成功、语义上不完整”的假阳性
