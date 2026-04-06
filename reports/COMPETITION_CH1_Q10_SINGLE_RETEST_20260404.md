# Competition Ch1_Q10 单题复测报告

运行对象：
- 本次 run：`runs/20260404_205514_competition-ch1-q10-single-proxy-gpt54-20260404`
- 对比 run：`runs/20260402_175059_mechanics-full-realapi-par10-20260402`
- 数据源：`LeanPhysBench_v0.json` 中 `competition_mechanics_Ch1_Q10`
- 难度：`competition_hard`
- 模型：`gpt-5.4`，OpenAI-compatible 代理

## 一、结论摘要

我这次选的是 `competition_mechanics_Ch1_Q10`，因为它在上次全量实测中已经触发过 `B/C/D` 闭环，而且最终进入了 `E`，但死在 `proof_search_failure`，属于高难样本。

这次在修改后的架构下单题重跑，结果是：
- `grounding_ok = true`
- `statement_generation_ok = true`
- `compile_ok = true`
- `semantic_ok = false`
- `proof_ok = false`
- `end_to_end_ok = false`
- `final_error_type = semantic_drift`
- `feedback_loop_used = true`
- `final_round_index = 1`

这次最重要的结论不是“又失败了”，而是：

1. 这题确实触发了完整的反馈链路，适合分析。
2. 当前细粒度反馈已经足够具体，能够清楚指出错译位置。
3. 但这题相较于 `20260402` 那次全量 run，实际上发生了回退。
4. 上次这题在 revision 后至少进入了 `E`，这次则停在 `D`，连 proof 都没有机会尝试。

也就是说：
- 当前修改后的架构在“反馈信息更细”这件事上是成功的
- 但在这道 competition 难题上，整体通过能力并没有提升，反而出现了前移失败

## 二、原始题目

原始 informal statement：

```text
EXAMPLE Ch1_Q10 Q: A slender rod rotates uniformly with angular velocity ω around a fixed endpoint O in a plane. A small ring moves along the rod with constant speed v relative to the rod. At time t = 0, the ring is located at the endpoint O. Prove that the trajectory of the ring is an Archimedean spiral: r = (v / ω) φ where r is the distance from O and φ is the angle the rod makes with a fixed axis.
```

原始 formal theorem 的目标实际上更强，包含三部分：
1. `∀ t, r_ring t = (v / ω) * φ_ring t`
2. `∀ t, v_r t = v ∧ v_φ t = v * ω * t`
3. `∀ t, a_r t = -v * ω**2 * t ∧ a_φ t = 2 • v * ω`

但题面自然语言里最核心的目标是第一部分：
- 证明轨迹是阿基米德螺线
- 即 `r = (v / ω) φ`

## 三、与上次全量 run 的对比

上次 `20260402` 全量 run 中，这题的最终状态是：
- `semantic_ok = true`
- `proof_ok = false`
- `final_error_type = proof_search_failure`
- `feedback_loop_used = true`
- `final_round_index = 1`

也就是说，上次它在 revision 后至少达到了“语义通过，证明失败”。

这次单题复测的最终状态则是：
- `semantic_ok = false`
- `proof_ok = false`
- `final_error_type = semantic_drift`
- `feedback_loop_used = true`
- `final_round_index = 1`

这表明：
- 当前版本在这题上的失败位置从 `E` 前移到了 `D`
- 从“证明失败”退化成了“语义未通过”

## 四、A 模块生成结果

产物文件：
- `runs/20260404_205514_competition-ch1-q10-single-proxy-gpt54-20260404/problem_ir.jsonl`

A 模块提取结果是正确的，而且相当完整。

### 1. 关键对象

```json
[
  {"name": "slender rod", "type": "rigid rod"},
  {"name": "small ring", "type": "particle"},
  {"name": "endpoint O", "type": "fixed pivot"}
]
```

### 2. 已知量

```json
[
  {"symbol": "omega", "value": null, "description": "constant angular velocity of the rod"},
  {"symbol": "v", "value": null, "description": "constant speed of the ring relative to the rod"},
  {"symbol": "t", "value": 0, "description": "initial time"},
  {"symbol": "r(0)", "value": 0, "description": "ring is at endpoint O at t = 0"}
]
```

### 3. 目标

```json
{
  "symbol": "r(phi)",
  "description": "trajectory of the ring in polar form",
  "target_expression": "r = (v/omega) phi"
}
```

### 4. 关系与约束

```json
{
  "relations": [
    {"expression": "dr/dt = v", "description": "ring moves along the rod with constant speed relative to the rod"},
    {"expression": "dphi/dt = omega", "description": "rod rotates uniformly"},
    {"expression": "r(0) = 0"},
    {"expression": "phi(0) = 0", "description": "angle origin may be chosen at t = 0 with a fixed axis"}
  ],
  "constraints": [
    "rod rotates uniformly in a plane",
    "endpoint O is fixed",
    "ring moves along the rod",
    "ring speed relative to the rod is constant",
    "at t = 0 the ring is at O"
  ],
  "physical_laws": ["Kinematics"]
}
```

判断：
- A 这次没有问题
- 目标、关系、约束都提取得很完整
- 后续失败不是 A 漏提信息导致的

## 五、B 模块生成结果

产物文件：
- `runs/20260404_205514_competition-ch1-q10-single-proxy-gpt54-20260404/statement_candidates.jsonl`

这次 B 有两个明显阶段。

### 1. Round 0 的最终落盘结果

round 0 的四个候选最终都变成了同一个 catastrophic fallback：

```lean
theorem lean4phys_competition_mechanics_Ch1_Q10_c1_fallback_goal
  (F m a : Real)
  (hm : m ≠ 0)
  (h_force : F = m * a)
  : a = F / m
```

同样的结构还出现在 `c2/c3/c4`，只是 theorem 名不同。

它们的 plan 全都是：

```text
Catastrophic fallback declaration after unusable model output.
```

这是一个非常严重的问题，因为：
- 原题是纯 kinematics 螺线问题
- Round 0 的最终候选却全部漂移成了牛顿第二定律代数重排

### 2. Round 0 的 raw_response 实际上并不是完全无关

更值得注意的是，`statement_candidates.jsonl` 里保存的 `raw_response` 显示，模型原始输出其实是和题意相关的，例如：

```text
theorem archimedean_spiral_from_time_param ...
theorem spiral_relation_from_rate_equations ...
theorem spiral_trajectory_pointwise ...
theorem radial_coordinate_as_function_of_angle ...
```

也就是说：
- 模型原始输出不是牛顿第二定律
- 是本地后处理 / 校验 / 修复链路把它们全部判坏了
- 最后才退成了 `fallback_goal`

这说明当前 B 的问题不是“模型完全不会做题”，而是：
- B 的本地声明验证与修复策略对这类 competition theorem 过于脆弱
- 一旦判坏，就会落入灾难性 fallback

### 3. Round 1 的 revision 结果

收到反馈后，B 重新输出了 4 个候选。最终落盘如下。

#### c1 / c2 / c3

这三个候选都被克隆成了同一个有效候选：

```lean
theorem lean4phys_competition_mechanics_Ch1_Q10_c1_lean4phys_competition_mechanics_Ch1_Q10_c4_lean4phys_competition_mechanics_archimedean_spiral_c4
  (r phi : Real -> Real) (v omega : Real)
  (h_r : forall t, r t = v * t)
  (h_phi : forall t, phi t = omega * t)
  : forall t, omega * r t = v * phi t
```

plan:
```text
Cloned from a valid candidate because the original c1 declaration was invalid.
```

`c2` 和 `c3` 也是同样的结构，只是 theorem 名不同。

#### c4

唯一保留下来的原始 revision candidate 是：

```lean
theorem lean4phys_competition_mechanics_Ch1_Q10_c4_lean4phys_competition_mechanics_archimedean_spiral_c4
  (r phi : Real -> Real) (v omega : Real)
  (h_r : forall t, r t = v * t)
  (h_phi : forall t, phi t = omega * t)
  : forall t, omega * r t = v * phi t
```

plan:
```text
Provide the equivalent cross-multiplied Archimedean spiral law, avoiding division and only using the linear kinematic relations.
```

判断：
- Round 1 确实比 Round 0 更接近题意
- 但它没有生成精确目标 `r = (v/omega) * phi`
- 而是选择了交叉相乘后的弱等价形式 `omega * r = v * phi`
- 同时还丢了 `omega ≠ 0` 和初始约束

## 六、C 阶段验证结果

产物文件：
- `runs/20260404_205514_competition-ch1-q10-single-proxy-gpt54-20260404/compile_checks.jsonl`

这题在 C 阶段两轮都很“顺”：
- Round 0：4/4 compile pass
- Round 1：4/4 compile pass

换句话说：
- C 没有暴露任何问题
- 这题的核心难点不是编译，而是语义是否真的对题

这也意味着：
- 对于高难 competition 题，compile pass 的信号非常弱
- 如果 B 产出的是“可编译但偏题”的命题，C 根本拦不住

## 七、D 阶段语义验证结果

产物文件：
- `runs/20260404_205514_competition-ch1-q10-single-proxy-gpt54-20260404/semantic_rank.jsonl`

### 1. Round 0：严重语义漂移

Round 0 的 4 个候选都是 `fallback_goal`，D 的诊断非常明确：

- `semantic_pass = false`
- `sub_error_type = trivial_goal`
- `failure_tags`:
  - `wrong_target`
  - `law_drift`
  - `wrong_quantities`
  - `trivial_or_tautological`
  - `off_topic`
  - `target_mismatch`

核心 failure summary：

```text
The theorem completely drifts to Newton's second law and does not formalize the Archimedean spiral trajectory claim at all.
```

这次 D 细粒度反馈指出的错译位置包括：
- `unknown_target`
- `physical_laws`
- `known_quantities`
- `constraints`
- `units`

这说明 D 的详细反馈能力这次是有效的，而且很强。

### 2. Round 0 的完整 feedback 包

下面是这次真正返回给 B 的 `retry_feedback_summary` 原文：

```json
{
  "retry_reason": "semantic_fail",
  "compile_pass_count": 4,
  "semantic_pass": false,
  "selected_candidate_id": "c4",
  "candidates": [
    {
      "candidate_id": "c1",
      "theorem_decl": "theorem lean4phys_competition_mechanics_Ch1_Q10_c1_fallback_goal\n  (F m a : Real)\n  (hm : m ≠ 0)\n  (h_force : F = m * a)\n  : a = F / m",
      "plan": "Catastrophic fallback declaration after unusable model output.",
      "compile_pass": true,
      "error_type": null,
      "sub_error_type": null,
      "failure_tags": [],
      "failure_summary": null,
      "stderr_digest": "",
      "stderr_excerpt": null,
      "backend_used": "mechlib",
      "route_reason": "auto_import_mechlib",
      "route_fallback_used": false,
      "error_line": null,
      "error_message": null,
      "error_snippet": null,
      "semantic_score": 0.0954,
      "semantic_pass": false,
      "semantic_sub_error_type": "trivial_goal",
      "semantic_failure_tags": [
        "wrong_target",
        "law_drift",
        "wrong_quantities",
        "trivial_or_tautological",
        "off_topic",
        "target_mismatch"
      ],
      "semantic_failure_summary": "The theorem completely drifts to Newton's second law and does not formalize the Archimedean spiral trajectory claim at all.",
      "semantic_reason": "This is an algebraic rearrangement of Newton's second law, not the kinematics problem about a ring sliding on a uniformly rotating rod and proving the polar trajectory r = (v/omega) phi. It is off-topic, uses the wrong physical law, wrong symbols, and wrong target.",
      "back_translation_text": "Given real numbers F, m, and a, with m nonzero and F = m a, prove that a = F/m.",
      "mismatch_fields": [
        "unknown_target",
        "physical_laws",
        "known_quantities",
        "constraints",
        "units"
      ],
      "missing_or_incorrect_translations": [
        "The original problem asks to prove the trajectory relation r = (v/omega) phi, but the theorem instead solves for acceleration a from F = m a.",
        "The original givens omega, v, r, phi, and the initial condition that the ring starts at O at t = 0 are entirely missing.",
        "The kinematic relations dr/dt = v and dphi/dt = omega were not translated.",
        "The theorem introduces unrelated quantities F, m, and a that do not appear in the original problem."
      ],
      "suggested_fix_direction": "Replace the Newton-law statement with a kinematics theorem using dr/dt = v, dphi/dt = omega, r(0)=0, and conclude r = (v/omega) phi.",
      "hard_gate_reasons": [
        "target_mismatch"
      ],
      "semantic_rank_score": 0.1354
    },
    {
      "candidate_id": "c2",
      "theorem_decl": "theorem lean4phys_competition_mechanics_Ch1_Q10_c2_fallback_goal\n  (F m a : Real)\n  (hm : m ≠ 0)\n  (h_force : F = m * a)\n  : a = F / m",
      "plan": "Catastrophic fallback declaration after unusable model output.",
      "compile_pass": true,
      "error_type": null,
      "sub_error_type": null,
      "failure_tags": [],
      "failure_summary": null,
      "stderr_digest": "",
      "stderr_excerpt": null,
      "backend_used": "mechlib",
      "route_reason": "auto_import_mechlib",
      "route_fallback_used": false,
      "error_line": null,
      "error_message": null,
      "error_snippet": null,
      "semantic_score": 0.0954,
      "semantic_pass": false,
      "semantic_sub_error_type": "trivial_goal",
      "semantic_failure_tags": [
        "wrong_target",
        "law_drift",
        "wrong_quantities",
        "trivial_or_tautological",
        "off_topic",
        "target_mismatch"
      ],
      "semantic_failure_summary": "The theorem completely drifts to Newton's second law and does not formalize the Archimedean spiral trajectory claim at all.",
      "semantic_reason": "This is an algebraic rearrangement of Newton's second law, not the kinematics problem about a ring sliding on a uniformly rotating rod and proving the polar trajectory r = (v/omega) phi. It is off-topic, uses the wrong physical law, wrong symbols, and wrong target.",
      "back_translation_text": "Given real numbers F, m, and a, with m nonzero and F = m a, prove that a = F/m.",
      "mismatch_fields": [
        "unknown_target",
        "physical_laws",
        "known_quantities",
        "constraints",
        "units"
      ],
      "missing_or_incorrect_translations": [
        "The original problem asks to prove the trajectory relation r = (v/omega) phi, but the theorem instead solves for acceleration a from F = m a.",
        "The original givens omega, v, r, phi, and the initial condition that the ring starts at O at t = 0 are entirely missing.",
        "The kinematic relations dr/dt = v and dphi/dt = omega were not translated.",
        "The theorem introduces unrelated quantities F, m, and a that do not appear in the original problem."
      ],
      "suggested_fix_direction": "Replace the Newton-law statement with a kinematics theorem using dr/dt = v, dphi/dt = omega, r(0)=0, and conclude r = (v/omega) phi.",
      "hard_gate_reasons": [
        "target_mismatch"
      ],
      "semantic_rank_score": 0.1354
    },
    {
      "candidate_id": "c3",
      "theorem_decl": "theorem lean4phys_competition_mechanics_Ch1_Q10_c3_fallback_goal\n  (F m a : Real)\n  (hm : m ≠ 0)\n  (h_force : F = m * a)\n  : a = F / m",
      "plan": "Catastrophic fallback declaration after unusable model output.",
      "compile_pass": true,
      "error_type": null,
      "sub_error_type": null,
      "failure_tags": [],
      "failure_summary": null,
      "stderr_digest": "",
      "stderr_excerpt": null,
      "backend_used": "mechlib",
      "route_reason": "auto_import_mechlib",
      "route_fallback_used": false,
      "error_line": null,
      "error_message": null,
      "error_snippet": null,
      "semantic_score": 0.0954,
      "semantic_pass": false,
      "semantic_sub_error_type": "trivial_goal",
      "semantic_failure_tags": [
        "wrong_target",
        "law_drift",
        "wrong_quantities",
        "trivial_or_tautological",
        "off_topic",
        "target_mismatch"
      ],
      "semantic_failure_summary": "The theorem completely drifts to Newton's second law and does not formalize the Archimedean spiral trajectory claim at all.",
      "semantic_reason": "This is an algebraic rearrangement of Newton's second law, not the kinematics problem about a ring sliding on a uniformly rotating rod and proving the polar trajectory r = (v/omega) phi. It is off-topic, uses the wrong physical law, wrong symbols, and wrong target.",
      "back_translation_text": "Given real numbers F, m, and a, with m nonzero and F = m a, prove that a = F/m.",
      "mismatch_fields": [
        "unknown_target",
        "physical_laws",
        "known_quantities",
        "constraints",
        "units"
      ],
      "missing_or_incorrect_translations": [
        "The original problem asks to prove the trajectory relation r = (v/omega) phi, but the theorem instead solves for acceleration a from F = m a.",
        "The original givens omega, v, r, phi, and the initial condition that the ring starts at O at t = 0 are entirely missing.",
        "The kinematic relations dr/dt = v and dphi/dt = omega were not translated.",
        "The theorem introduces unrelated quantities F, m, and a that do not appear in the original problem."
      ],
      "suggested_fix_direction": "Replace the Newton-law statement with a kinematics theorem using dr/dt = v, dphi/dt = omega, r(0)=0, and conclude r = (v/omega) phi.",
      "hard_gate_reasons": [
        "target_mismatch"
      ],
      "semantic_rank_score": 0.1354
    },
    {
      "candidate_id": "c4",
      "theorem_decl": "theorem lean4phys_competition_mechanics_Ch1_Q10_c4_fallback_goal\n  (F m a : Real)\n  (hm : m ≠ 0)\n  (h_force : F = m * a)\n  : a = F / m",
      "plan": "Catastrophic fallback declaration after unusable model output.",
      "compile_pass": true,
      "error_type": null,
      "sub_error_type": null,
      "failure_tags": [],
      "failure_summary": null,
      "stderr_digest": "",
      "stderr_excerpt": null,
      "backend_used": "mechlib",
      "route_reason": "auto_import_mechlib",
      "route_fallback_used": false,
      "error_line": null,
      "error_message": null,
      "error_snippet": null,
      "semantic_score": 0.0954,
      "semantic_pass": false,
      "semantic_sub_error_type": "trivial_goal",
      "semantic_failure_tags": [
        "wrong_target",
        "law_drift",
        "wrong_quantities",
        "trivial_or_tautological",
        "off_topic",
        "target_mismatch"
      ],
      "semantic_failure_summary": "The theorem completely drifts to Newton's second law and does not formalize the Archimedean spiral trajectory claim at all.",
      "semantic_reason": "This is an algebraic rearrangement of Newton's second law, not the kinematics problem about a ring sliding on a uniformly rotating rod and proving the polar trajectory r = (v/omega) phi. It is off-topic, uses the wrong physical law, wrong symbols, and wrong target.",
      "back_translation_text": "Given real numbers F, m, and a, with m nonzero and F = m a, prove that a = F/m.",
      "mismatch_fields": [
        "unknown_target",
        "physical_laws",
        "known_quantities",
        "constraints",
        "units"
      ],
      "missing_or_incorrect_translations": [
        "The original problem asks to prove the trajectory relation r = (v/omega) phi, but the theorem instead solves for acceleration a from F = m a.",
        "The original givens omega, v, r, phi, and the initial condition that the ring starts at O at t = 0 are entirely missing.",
        "The kinematic relations dr/dt = v and dphi/dt = omega were not translated.",
        "The theorem introduces unrelated quantities F, m, and a that do not appear in the original problem."
      ],
      "suggested_fix_direction": "Replace the Newton-law statement with a kinematics theorem using dr/dt = v, dphi/dt = omega, r(0)=0, and conclude r = (v/omega) phi.",
      "hard_gate_reasons": [
        "target_mismatch"
      ],
      "semantic_rank_score": 0.1354
    }
  ]
}
```

这个 feedback 包的价值很高，因为它明确说明：
- 不是 compile 问题
- 不是 proof 问题
- 是 B 最终命题完全偏题
- 而且偏题位置被分解到了 law / quantities / constraints / units / target 五个层面

### 3. Round 1：revision 后仍未通过

Round 1 选中了 `c4`，但最终仍然 `semantic_pass = false`。

最终 D 诊断如下：

```json
{
  "selected_candidate_id": "c4",
  "semantic_pass": false,
  "sub_error_type": "wrong_target",
  "failure_tags": [
    "weaker_equivalent_form",
    "missing_constraints",
    "implicit_nonzero_condition",
    "target_mismatch"
  ],
  "failure_summary": "Mostly correct kinematic reformulation, but it states only the cross-multiplied relation instead of the explicit polar trajectory formula and omits some problem constraints.",
  "failure_details": {
    "mismatch_fields": [
      "unknown_target",
      "constraints"
    ],
    "missing_or_incorrect_translations": [
      "The original goal is the explicit polar trajectory r = (v/omega) phi, but the theorem only proves the cross-multiplied form omega r = v phi.",
      "The theorem omits the stated setup that the rod rotates about a fixed endpoint in a plane and that the ring starts at O at t = 0.",
      "To match the exact target expression, a nonzero condition on omega is needed but is not included."
    ],
    "suggested_fix_direction": "State the conclusion as forall t, r t = (v / omega) * phi t and add omega ≠ 0, while keeping the kinematic assumptions and initial setup.",
    "back_translation_text": "Assume the ring's distance from the endpoint satisfies r(t)=vt for all time and the rod angle satisfies phi(t)=omega t for all time. Then for every time t, omega·r(t)=v·phi(t).",
    "semantic_reason": "This captures the intended kinematic content behind the Archimedean spiral: linear radial motion and uniform angular motion imply the equivalent relation omega r = v phi. It uses the correct law family (kinematics) and the right known quantities. However, it does not state the target explicitly as r = (v/omega) phi, omits the initial-condition context and geometric wording about the trajectory, and avoids the needed nonzero-omega condition for division. It is not trivial, but it is a slightly weaker/equivalent algebraic form rather than the exact target statement.",
    "hard_gate_reasons": [
      "target_mismatch"
    ]
  }
}
```

这是这次复测里最有价值的诊断结果：
- Round 0：完全偏题
- Round 1：已经接近题意，但仍然不是“精确翻译”

## 八、反馈环节的总体判断

这题说明当前反馈机制已经具备了两种能力：

1. **粗错误定位**
   - Round 0 能明确指出“完全漂移到牛顿第二定律”

2. **细错误定位**
   - Round 1 能明确指出“已经接近题意，但只是 weaker equivalent form”
   - 并能具体指出：
     - 目标形式不精确
     - 约束丢失
     - `omega ≠ 0` 缺失

所以从“反馈内容质量”看，这次是成功的。  
真正没成功的是：
- B 收到这类细反馈后，还不能稳定地产出精确目标形式

## 九、E 阶段证明结果与反馈内容

产物文件：
- `runs/20260404_205514_competition-ch1-q10-single-proxy-gpt54-20260404/proof_checks.jsonl`
- `runs/20260404_205514_competition-ch1-q10-single-proxy-gpt54-20260404/proof_attempts.jsonl`

这次 `proof_attempts.jsonl` 是空的，因为 proof 根本没有启动。

最终 proof check 为：

```json
{
  "proof_success": false,
  "attempts_used": 0,
  "selected_candidate_id": "c4",
  "error_type": "proof_skipped_due_to_semantic_fail",
  "sub_error_type": "proof_skipped_due_to_semantic_fail",
  "failure_tags": ["proof_skipped_due_to_semantic_fail"],
  "failure_summary": "Proof stage skipped because semantic ranking failed.",
  "failure_details": {
    "semantic_error_type": "semantic_drift",
    "semantic_sub_error_type": "wrong_target",
    "semantic_failure_summary": "Mostly correct kinematic reformulation, but it states only the cross-multiplied relation instead of the explicit polar trajectory formula and omits some problem constraints."
  }
}
```

这意味着：
- E 阶段这次没有“证明失败”
- 而是被上游正确地拦下来了
- 当前的 skip 机制是有效的

从控制流上看，这是合理的。  
从整体能力上看，这也说明：
- 当前系统的主要缺口仍在 `B/D`
- 不是 `E`

## 十、关键问题定位

### 1. Round 0 的 B 后处理存在结构性风险

模型原始输出其实给出了和题意相关的候选，但最终落盘成了 4 个 `fallback_goal`。

这说明：
- `B` 的“声明有效性判定 -> 修复 -> fallback”链路过于激进
- 它可能把本来可修的 candidate 一次性全打成灾难性回退

对于 competition 题，这种行为会直接毁掉后续链路。

### 2. Round 1 的 revision 方向是对的，但精度不够

revision 后的 candidate 至少回到了 kinematics 主线，但仍然有三个明显问题：
- 用了 `ω r = v φ`，没有给出精确目标 `r = (v/ω) φ`
- 缺少 `ω ≠ 0`
- 丢掉了初始条件和几何约束

所以当前 B 能“回到正确话题”，但还不能“回到精确目标”。

### 3. D 的 hard gate 现在是合理的

这次 D 没有放水，而是把弱等价形式拦下来了。  
这和上一题 `Mechanics_20_University` 形成鲜明对比：
- 上一题里 D 对 partial answer 放得过宽
- 这题里 D 对 weaker equivalent form 拦得比较准

说明 D 的问题不是“完全不会判”，而是：
- 不同类型的 target mismatch 处理还不统一

## 十一、后续修改建议

针对这题，我建议优先改这三块。

### 1. 先修 B 的“误杀后灾难回退”

这是这题最先爆炸的地方。

建议：
- 对“原始输出与题意相关，但 declaration 非法”的候选，不要直接落成 `fallback_goal`
- 先做结构化 repair：
  - 修 `∀`
  - 修箭头/量词/非法字符
  - 修 theorem 名
  - 修局部语法
- 只有确认语义完全不可救时，才走 catastrophic fallback

### 2. 给 revision prompt 强化“精确目标形式”约束

当前 revision 已经能走回正确主题，但不够精确。

建议在 B revision prompt 里增加：
- 不允许只给交叉相乘后的等价式，除非题面目标本身就是该形式
- 如果原题目标是除法形式，必须显式补上必要的非零条件
- 如果 A 提取了初始条件与几何约束，revision 不能默认丢掉

### 3. 统一 D 对 target mismatch 的判定标准

目前看有两类情况：
- `Mechanics_20_University`：少回答一半目标，但仍被放行
- `Ch1_Q10`：给了弱等价形式，被拦下

建议：
- 对 `partial_answer`
- 对 `weaker_equivalent_form`
- 对 `missing_constraints`

统一建立更明确的 pass/fail 规则。  
否则不同题型上会出现不一致。

## 十二、最终结论

这次 `competition Ch1_Q10` 的复测是有价值的，因为它证明了三件事：

1. 细粒度反馈机制已经真正工作起来了。
2. 当前 competition 难题的核心问题依然在 `B/D`，不是 `C/E`。
3. 现阶段系统对这类题的主要瓶颈，不是“不会证明”，而是“很难稳定地产生精确、完整、可接受的形式化目标”。

这题也给了一个非常清楚的改造优先级：
- 第一优先级：修 B 的有效候选被误杀后退成灾难 fallback
- 第二优先级：强化 revision 对“精确目标形式”的控制
- 第三优先级：统一 D 对 partial / weaker-equivalent target mismatch 的 hard gate 标准
