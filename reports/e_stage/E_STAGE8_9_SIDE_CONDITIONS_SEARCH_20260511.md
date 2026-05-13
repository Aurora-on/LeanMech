# E 阶段阶段 8/9 开发报告：SideConditionAnalyzer 与 SearchController

日期：2026-05-11

## 任务范围

本次只实现 E 阶段的 proof-search 基础设施，不修改 pipeline benchmark，不移除 legacy E，也不改变 theorem statement 生成逻辑。

完成内容：

1. 新增 `SideConditionAnalyzer`，对常见分母非零条件做确定性 proposal。
2. 新增 `SearchController`，把 deterministic replay、side-condition proposal、LLM strategy proposals、ActionGuard、Lean probe 和 final replay 串成一个保守搜索循环。
3. 新增阶段 8/9 单元测试。

## 新增模块

### `src/mech_pipeline/modules/e_side_conditions.py`

核心入口：

```python
def propose_side_condition_actions(proof_context, current_facts) -> list[ProofActionProposal]
```

当前支持的确定性模式：

```lean
目标中存在分母: m1.val + m2.val
已有事实: hm1 : 0 < m1.val, hm2 : 0 < m2.val

生成动作:
have hden_m1_val___m2_val : m1.val + m2.val ≠ 0 := by
  nlinarith [hm1, hm2]
```

如果缺少正性事实，返回 `strategy = "missing_side_condition"` 的结构化 proposal，不让 LLM 直接硬证。

### `src/mech_pipeline/modules/e_search_controller.py`

核心入口：

```python
def run_llm_guided_search(
    *,
    proof_context: ProofContext,
    lean_runner: LeanRunner,
    llm_client: ...,
    cfg: ...,
) -> ProofSearchTrace
```

当前搜索流程：

1. 建立 root proof node。
2. 如配置允许，先运行 deterministic obligation replay。
3. 尝试 deterministic side-condition proposals。
4. 调用 `LLMStrategyController` 生成局部 action proposals。
5. 每个 proposal 先过 `ActionGuard`。
6. 过 guard 后调用 `LeanRunner.probe_proof_prefix`。
7. `progress` action 进入队列，`invalid` action 进入 rejected trace。
8. `closed` action 必须再通过 `verify_proof` final replay 才算 success。
9. 受 `max_nodes`、`max_depth`、`max_llm_calls` 约束。

当前实现是保守 best-first/beam 风格控制器，不是完整 MCTS。

## 分层与安全规则

- LLM 仍只提出局部 tactic block，不直接提交最终 proof。
- SearchController 只接受 Lean probe 通过的 `progress` / `closed` 动作。
- `closed` 还必须 final replay。
- ActionGuard 继续禁止 `sorry/admit/axiom/set_option`、未授权 MechLib theorem、schema/problem/concept metadata。
- 缺少 side condition 时生成 `missing_side_condition`，供前段补充假设或后续 routing 使用。

## 测试结果

已运行：

```bash
.venv/bin/pytest -q tests/test_e_side_condition_analyzer.py tests/test_e_search_controller_basic.py
.venv/bin/python -m py_compile src/mech_pipeline/modules/e_side_conditions.py src/mech_pipeline/modules/e_search_controller.py src/mech_pipeline/modules/__init__.py
.venv/bin/pytest -q tests/test_e_config_modes.py tests/test_e_proof_search_types.py tests/test_e_build_proof_context.py tests/test_e_obligation_replayer.py tests/test_e_lean_probe.py tests/test_e_certified_replay.py tests/test_e_action_guard.py tests/test_e_strategy_controller_prompt.py tests/test_e_side_condition_analyzer.py tests/test_e_search_controller_basic.py tests/test_lean_runner.py
.venv/bin/pytest -q tests/test_config.py tests/test_config_minimal_skeleton.py tests/test_cli_smoke.py::test_cli_smoke_local_text tests/test_orchestrator_minimal_skeleton_smoke.py::test_minimal_skeleton_run_archives_front_half_artifacts_and_summary tests/test_orchestrator_minimal_skeleton_smoke.py::test_orchestrator_minimal_feedback_reruns_sketch_and_b
```

结果：

- 阶段 8/9 新测试：`8 passed`
- E 阶段相关回归：`45 passed`
- 配置 / CLI / orchestrator smoke：`17 passed`

## 当前限制

1. SideConditionAnalyzer 当前只识别简单括号分母和正性事实，尚未做 Lean AST 级解析。
2. SearchController 已实现独立入口，但 orchestrator 当前仍只把 deterministic replay 的 trace 写入 `proof_search_trace.jsonl` / `proof_action_checks.jsonl`，完整 search loop 尚未替换 legacy E。
3. `current_facts` 目前主要是 fact 名称；要做更强 side-condition 分析，后续应在 `ProofContext` 中保留局部事实的完整 Lean 类型。
4. 搜索评分是初版启发式，后续可以加入 goal-state 差异、obligation coverage 和 dependency audit 的更精确评分。

## 后续建议

1. 在 orchestrator 的 `llm_guided_search` mode 下接入 `run_llm_guided_search`，并保留 legacy fallback。
2. 扩展 `ProofContext.local_facts` 为 `name/type/source` 结构，提升 side-condition 与 prompt 的可用性。
3. 增加 final `ProofDependencyAudit` 汇总，检查所有 required verified decl 与 obligation coverage。
4. 对 `missing_side_condition` 建立 failure routing，回传给 B/D 前段补充正性假设。
