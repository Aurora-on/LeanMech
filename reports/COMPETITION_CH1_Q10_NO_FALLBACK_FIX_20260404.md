# competition_mechanics_Ch1_Q10 fallback 去除说明

## 1. 旧问题的直接触发原因

旧 run：
- `runs/20260404_205514_competition-ch1-q10-single-proxy-gpt54-20260404`

这题在旧版本中触发 `fallback_goal`，不是因为模型原始输出完全偏题，而是因为 B 阶段本地规范化把 4 个原始候选全部判成了无效声明。

根因定位：
- 原始 `raw_response` 中 4 个候选都与题意相关，且都在做阿基米德螺线轨迹形式化。
- 4 个候选都包含类似 `hω : omega ≠ 0` 的假设名。
- B 阶段的 `_repair_decl_for_mechlib_safety(...)` 会调用 `_has_disallowed_non_ascii(...)`。
- 该检查此前不允许 `ω` 这类合法的数学标识符出现在 theorem 声明中，因此 4 个候选全部被打成 `None`。
- `ModuleB.run(...)` 随后触发了 `Catastrophic fallback declaration after unusable model output.`，把 4 个候选全部替换成了无关的 `fallback_goal`。

也就是说，旧问题是：
- 模型输出相关
- 本地过滤过严
- fallback 伪造了一个与题目无关的新命题

## 2. 本次修复

本次修改的目标不是“优化 fallback”，而是直接去掉 B 阶段这类合成候选行为。

改动点：
- `src/mech_pipeline/modules/B_statement_gen.py`
  - 新增希腊字母标识符归一化，把 `ω/θ/φ/...` 统一转成 ASCII 名称，如 `hω -> homega`
  - 去掉 B 阶段“补满 4 个候选”的 fallback
  - 去掉 “Cloned from a valid candidate ...” 的 clone fallback
  - 去掉 “Catastrophic fallback declaration ...” 的 theorem fallback
  - 未知 API / 未修复符号不再直接被 B 替换成别的 theorem，而是保留给 C 阶段真实编译反馈
- `src/mech_pipeline/cli.py`
  - `statement_generation_ok` 从“必须正好 4 个候选”改成“至少有 1 个可用候选”
  - 当没有可用候选时，失败原因改成显式的 statement generation failure，而不是伪成功后进入 fallback theorem

## 3. 新版真实 API 复跑

新 run：
- `runs/20260404_212127_competition-ch1-q10-no-fallback-20260404`

使用：
- 配置：`configs/competition_ch1_q10_single_proxy_gpt54_20260404.yaml`
- 真实 API：`gpt-5.4`，OpenAI-compatible 代理

## 4. 新 run 结果

新 run 中已经确认：
- 不再出现 `fallback_goal`
- 不再出现 `Catastrophic fallback declaration`
- 不再出现 `Cloned from a valid candidate`

Round 0 的 4 个候选全部保留下来了，而且都与题目相关：
- `archimedean_spiral_from_time_elimination`
- `archimedean_spiral_with_initial_angle`
- `spiral_relation_from_derivative_constraints`
- `polar_trajectory_is_linear_in_angle`

Round 1 也继续保留真实 revision 候选，没有再造假 theorem。

最终状态：
- `grounding_ok = true`
- `statement_generation_ok = true`
- `compile_ok = true`
- `semantic_ok = false`
- `proof_ok = false`
- `end_to_end_ok = false`
- `final_error_type = semantic_drift`
- `feedback_loop_used = true`

## 5. 当前剩余问题

这题现在失败的原因已经不再是 fallback，而是 D 阶段的 hard gate 仍然把“带初始角偏移的等价形式”判成了 `target_mismatch`。

也就是说，当前链路已经从：
- “B 本地误杀 -> fallback 伪命题 -> 整题失真”

变成了：
- “B 候选真实保留 -> C 编译通过 -> D 对目标形式仍偏严格”

这说明本次修复已经把 fallback 这个研究噪声彻底移除了，后续如果继续提升 `competition_mechanics_Ch1_Q10` 的成功率，应该针对：
- D 对“等价目标 / 坐标原点选择”的判定规则
- B revision prompt 对“精确目标形式”的约束

而不是再回到 fallback 路径。
