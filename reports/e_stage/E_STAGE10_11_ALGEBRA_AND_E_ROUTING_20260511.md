# E 阶段阶段 10/11 开发报告：代数策略卡与 E_prover 路由

日期：2026-05-11

## 任务范围

本次继续 E 阶段的 MechCopilot-style prover 改造，但不建立 benchmark，不修改 pipeline 之外的证明逻辑。重点是：

1. 将代数能力作为 LLM 可选择、可参数化的 strategy cards 暴露出来。
2. 在 `ModuleE` 内部加入 proof mode 路由，保留 legacy full-proof 行为。
3. 让新搜索模式继续产出原有 `proof_attempts/proof_checks`，并在 attempt/check 上携带 search trace、action checks 与 dependency audit metadata。

## 阶段 10：Algebra Strategy Cards

新增文件：

```text
src/mech_pipeline/modules/e_algebra_strategy.py
```

核心入口：

```python
def available_algebra_strategy_cards(proof_context, current_facts) -> list[dict]
```

当前提供的 cards：

- `split_conjunction`：目标含 `∧` 或 `/\` 时建议 `constructor`。
- `field_normalization`：目标含 `/` 时建议 `field_simp [hden]`，并标记是否已有 denominator nonzero fact。
- `linear_arithmetic`：局部 facts 含等式时建议 `linarith`。
- `nonlinear_arithmetic`：目标或 facts 含乘法/幂时建议 `nlinarith`。
- `ring_normalization`：多项式表达式归一化时建议 `ring_nf`。
- `definition_merge`：模型定义方程与 law equation 合并时建议 `linarith`。

这些 cards 不直接生成 tactic block，仍由 LLM 决定何时使用和如何参数化，系统随后通过 ActionGuard 与 Lean probe 验证。

`LLMStrategyController` 的 compact proof state 现在包含：

```json
"available_algebra_strategy_cards": [...]
```

## 阶段 11：E_prover 路由

修改文件：

```text
src/mech_pipeline/modules/E_prover.py
src/mech_pipeline/cli.py
src/mech_pipeline/orchestrator.py
src/mech_pipeline/types.py
```

`ModuleE.run` 现在根据 `ProofConfig` 路由：

- `legacy_full_proof`：调用旧 full-proof 逻辑。
- `llm_guided_search`：调用 `_run_llm_guided_search_prover`。
- `auto`：`minimal_skeleton` candidate 进入 `llm_guided_search`，普通 candidate 走 legacy。

新增内部方法：

```python
def _run_llm_guided_search_prover(...)
def _run_legacy_full_proof(...)
```

搜索模式失败且 `legacy_fallback_enabled = true` 时，会回退到 legacy full-proof，并标记：

```json
"fallback_to_legacy_full_proof": true
```

fallback 的结果不会标记为 `fully_mechlib_verified`。

## 输出兼容

原有输出仍保留：

- `proof_attempts.jsonl`
- `proof_checks.jsonl`

新增 search metadata 通过 `ProofAttemptResult` / `ProofCheckResult` 字段携带，并由 orchestrator 展开到：

- `proof_search_trace.jsonl`
- `proof_action_checks.jsonl`
- `proof_dependency_audit.jsonl`

## 测试结果

已运行：

```bash
.venv/bin/pytest -q tests/test_e_algebra_strategy_cards.py tests/test_e_mode_routing.py
.venv/bin/python -m py_compile src/mech_pipeline/modules/E_prover.py src/mech_pipeline/modules/e_algebra_strategy.py src/mech_pipeline/modules/e_strategy_controller.py src/mech_pipeline/modules/e_search_controller.py src/mech_pipeline/types.py src/mech_pipeline/cli.py src/mech_pipeline/orchestrator.py
.venv/bin/pytest -q tests/test_e_config_modes.py tests/test_e_proof_search_types.py tests/test_e_build_proof_context.py tests/test_e_obligation_replayer.py tests/test_e_lean_probe.py tests/test_e_certified_replay.py tests/test_e_action_guard.py tests/test_e_strategy_controller_prompt.py tests/test_e_side_condition_analyzer.py tests/test_e_search_controller_basic.py tests/test_e_algebra_strategy_cards.py tests/test_e_mode_routing.py tests/test_e_prover.py tests/test_lean_runner.py
.venv/bin/pytest -q tests/test_config.py tests/test_config_minimal_skeleton.py tests/test_cli_smoke.py::test_cli_smoke_local_text tests/test_orchestrator_minimal_skeleton_smoke.py::test_minimal_skeleton_run_archives_front_half_artifacts_and_summary tests/test_orchestrator_minimal_skeleton_smoke.py::test_orchestrator_minimal_feedback_reruns_sketch_and_b
```

结果：

- 阶段 10/11 新测试：`6 passed`
- E 阶段相关回归：`55 passed`
- 配置 / CLI / orchestrator smoke：`17 passed`

说明：一次并行 pytest 运行曾因两个 pytest 进程同时清理 `tmp/pytest/basetemp` 出现临时目录冲突；顺序重跑后全部通过。

## 当前限制

1. Algebra cards 只是策略提示，不保证 LLM 选用正确 tactic。
2. Search dependency audit 是初版，能统计 accepted actions 的 `uses_decls` 与 required decl 覆盖，但还没有完整 goal-level dependency reconstruction。
3. Search mode 已进入 `ModuleE`，但证明成功率仍取决于 skeleton metadata、proof obligations 和 LLM proposal 质量。
4. fallback legacy proof 默认不视为 fully MechLib verified，除非后续加入严格 dependency replay audit。

## 后续建议

1. 将 `ProofContext.local_facts` 升级为 `{name, type, source}`，增强 algebra cards 和 side-condition analyzer。
2. 在 final replay 后解析 proof dependency，避免仅依赖 LLM proposal 的 `uses_decls`。
3. 增加 `missing_side_condition` 到前段 failure routing 的反馈路径。
4. 逐步减少 legacy fallback 的默认依赖，把 search trace 作为主证明证据。
