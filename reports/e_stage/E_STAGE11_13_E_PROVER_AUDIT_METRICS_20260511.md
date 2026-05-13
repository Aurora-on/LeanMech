# E 阶段阶段 11-13 开发报告：E_prover 集成、DependencyAudit 与指标

日期：2026-05-11

## 任务范围

本次覆盖阶段 11-13：

1. 确认并补强 `E_prover.py` 的 proof mode 路由。
2. 新增独立 `DependencyAudit`，对最终 proof 的 MechLib 依赖完整性分类。
3. 在 metrics 中加入 LLM-guided certified proof search 的阶段指标。

不修改 pipeline benchmark，不引入 theorem，不改变 Lean 证明文件。

## 阶段 11：E_prover 集成

`ModuleE.run` 现在按 `ProofConfig` 路由：

- `legacy_full_proof`：调用 `_run_legacy_full_proof`，完整保留旧 E 行为。
- `llm_guided_search`：调用 `_run_llm_guided_search_prover`。
- `auto`：minimal skeleton candidate 进入 `llm_guided_search`，legacy candidate 进入 `legacy_full_proof`。

新的 search prover 返回的 `ProofAttemptResult` / `ProofCheckResult` 仍兼容原有：

- `proof_attempts.jsonl`
- `proof_checks.jsonl`

同时携带并由 orchestrator 展开：

- `proof_search_trace.jsonl`
- `proof_action_checks.jsonl`
- `proof_dependency_audit.jsonl`

如果 search 失败且 `legacy_fallback_enabled = true`，会调用 legacy full proof，并标记：

```json
"fallback_to_legacy_full_proof": true
```

fallback 结果不会标记为 `fully_mechlib_verified`。

## 阶段 12：DependencyAudit

新增文件：

```text
src/mech_pipeline/modules/e_dependency_audit.py
```

核心入口：

```python
def audit_proof_dependencies(
    *,
    proof_context: ProofContext,
    proof_body: str,
    final_replay_pass: bool,
) -> ProofDependencyAudit
```

审计项：

1. `proof_body` 是否包含 required `proof_obligations.must_use`。
2. 每个 proof obligation 是否产生了 `produced_fact_name`。
3. 是否使用 explicit gap law。
4. proof body 中是否出现 schema/problem/concept metadata。
5. 是否为 algebra-only success。

分类：

- `fully_mechlib_verified`
- `partial_mechlib_verified`
- `gap_assisted_success`
- `algebra_only_success`
- `proof_failed`

## 阶段 13：新增指标

修改文件：

```text
src/mech_pipeline/eval/metrics.py
```

新增 E 阶段指标：

- `llm_guided_search_enabled_rate`
- `obligation_replay_success_rate`
- `proof_obligation_coverage_rate`
- `verified_decl_use_rate`
- `fully_mechlib_verified_proof_rate`
- `partial_mechlib_verified_proof_rate`
- `gap_assisted_success_rate`
- `algebra_only_success_rate`
- `llm_strategy_success_rate`
- `valid_llm_action_rate`
- `invalid_llm_action_rate`
- `missing_side_condition_rate`
- `average_llm_calls_per_proof`
- `average_lean_action_checks_per_proof`

这些指标优先读取：

- `proof_search_trace.jsonl`
- `proof_action_checks.jsonl`
- `proof_dependency_audit.jsonl`

如果 stage row 缺失，则从 `proof_attempts.jsonl` 的嵌套 search metadata 中回退读取。

## 测试结果

已运行：

```bash
.venv/bin/pytest -q tests/test_e_dependency_audit.py tests/test_e_metrics_llm_guided_search.py tests/test_e_mode_routing.py
.venv/bin/python -m py_compile src/mech_pipeline/modules/e_dependency_audit.py src/mech_pipeline/modules/E_prover.py src/mech_pipeline/eval/metrics.py src/mech_pipeline/types.py
.venv/bin/pytest -q tests/test_e_config_modes.py tests/test_e_proof_search_types.py tests/test_e_build_proof_context.py tests/test_e_obligation_replayer.py tests/test_e_lean_probe.py tests/test_e_certified_replay.py tests/test_e_action_guard.py tests/test_e_strategy_controller_prompt.py tests/test_e_side_condition_analyzer.py tests/test_e_search_controller_basic.py tests/test_e_algebra_strategy_cards.py tests/test_e_dependency_audit.py tests/test_e_mode_routing.py tests/test_e_prover.py tests/test_e_metrics_llm_guided_search.py tests/test_lean_runner.py tests/test_metrics.py tests/test_metrics_minimal_skeleton.py
.venv/bin/pytest -q tests/test_config.py tests/test_config_minimal_skeleton.py tests/test_cli_smoke.py::test_cli_smoke_local_text tests/test_orchestrator_minimal_skeleton_smoke.py::test_minimal_skeleton_run_archives_front_half_artifacts_and_summary tests/test_orchestrator_minimal_skeleton_smoke.py::test_orchestrator_minimal_feedback_reruns_sketch_and_b
```

结果：

- 阶段 12/13 新测试：`9 passed`
- E + metrics 回归：`65 passed`
- 配置 / CLI / orchestrator smoke：`17 passed`

新增文件的 `axiom/sorry/admit` 扫描无命中。

## 当前限制

1. `DependencyAudit` 当前通过 proof body 文本检查 required decl 与 produced fact，尚未做 Lean 内核级 proof term dependency extraction。
2. algebra-only success 的分类依赖 required decl 列表；如果前段没有提供 proof obligations，审计会更保守。
3. metrics 当前按 stage rows 聚合，后续如果支持多 candidate 多 proof trace，需要进一步区分 selected candidate。

## 后续建议

1. 在 Lean final replay 成功后导出实际 used constants，替代文本级 dependency audit。
2. 把 `missing_side_condition` 写回 failure routing，用于要求 B 阶段补正性/非零假设。
3. 给每个 proof obligation 增加稳定 `obligation_id -> produced_fact_name -> required_decl` trace，降低审计歧义。
