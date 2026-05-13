# E 阶段阶段 5B/6/7：Probe Replay、ActionGuard 与 StrategyController 开发备注

日期：2026-05-11
范围：在阶段 6 前先把 Lean probe 接到 deterministic replay；随后实现 ActionGuard 与 LLMStrategyController prompt。仍保留 legacy E fallback，不实现完整 search controller。

## 阶段 5B：Lean probe 接入 ProofObligationReplayer

新增文件：

- `src/mech_pipeline/modules/e_certified_replay.py`

新增能力：

1. `probe_action_checker(lean_runner, timeout_s)`
   将 `LeanRunner.probe_proof_prefix` 包成 `ProofObligationReplayer` 可用的 `ActionChecker`。

2. `run_deterministic_obligation_replay_with_probe(...)`
   构造 `ProofObligationReplayer(action_checker=...)`，运行 deterministic obligation replay，并生成：
   - `ProofSearchTrace`
   - `ProofDependencyAudit`
   - `proof_action_checks` rows

Orchestrator 接入：

- 当 `select_proof_execution_mode(cfg.proof, selected_candidate) == "llm_guided_search"` 且 D 阶段语义通过时，先构造 `ProofContext`。
- 然后运行 deterministic obligation replay probe。
- 写入：
  - `proof_action_checks.jsonl`
  - `proof_search_trace.jsonl`
  - `proof_dependency_audit.jsonl`
- 之后继续走 legacy `ModuleE.run(...)` 作为 fallback。

这样当前主流程不会丢失旧 E 行为，同时已经开始产生局部 action 级 artifacts。

## 阶段 6：ActionGuard

新增文件：

- `src/mech_pipeline/modules/e_action_guard.py`

核心接口：

```python
validate_action_proposal(
    proposal: ProofActionProposal,
    proof_context: ProofContext,
) -> tuple[bool, list[str]]
```

Hard gate 覆盖：

- 拒绝 `sorry`
- 拒绝 `admit`
- 拒绝 `axiom`
- 拒绝 `set_option`
- 拒绝修改 theorem/environment 的命令，如 `theorem` / `lemma` / `def` / `import` / `open`
- 拒绝 whitelist 外的 `MechLib.*` declaration
- 拒绝 schema/problem/concept metadata 当 proof fact
- 拒绝 uses_facts 中未列入 proof context 的局部 fact
- 拒绝明显自然语言和占位符
- 限制 tactic block 长度，默认 1200 字符

初版允许的 tactic head：

- `have`
- `exact`
- `apply`
- `rw`
- `simp`
- `simp_all`
- `simpa`
- `constructor`
- `field_simp`
- `ring`
- `ring_nf`
- `linarith`
- `nlinarith`
- `norm_num`
- `positivity`
- `aesop`

## 阶段 7：LLMStrategyController

新增文件：

- `src/mech_pipeline/modules/e_strategy_controller.py`
- `prompts/E_strategy_controller.md`

配置更新：

- `PromptConfig.e_strategy_controller = "E_strategy_controller.md"`

核心接口：

```python
LLMStrategyController.build_prompt(
    proof_context=...,
    local_facts=...,
    remaining_obligations=...,
    last_error=...,
    failed_actions=...,
) -> str
```

Prompt 只包含 compact proof state：

- target
- local_facts
- remaining_obligations
- allowed_decls
- available_strategy_cards
- last_error
- failed_actions

Prompt 明确要求：

- LLM 是 proof strategy controller，不是完整 proof writer。
- 只输出下一步 local tactic block。
- 只使用列出的 local facts、obligations、verified declarations 和标准 tactic。
- 返回 JSON only。
- 不使用完整 `retrieval_context`。

Strategy cards：

- `derive_law_equation`
- `derive_model_equation`
- `prove_side_condition`
- `split_conjunction`
- `algebra_solve`
- `rewrite_forward`
- `rewrite_backward`
- `simp_normalize`
- `quantity_value_projection`
- `introduce_intermediate_have`
- `close_goal`

## 测试

新增测试：

- `tests/test_e_certified_replay.py`
- `tests/test_e_action_guard.py`
- `tests/test_e_strategy_controller_prompt.py`

已运行：

```bash
.venv/bin/pytest -q tests/test_e_certified_replay.py tests/test_e_action_guard.py tests/test_e_strategy_controller_prompt.py tests/test_e_config_modes.py tests/test_e_lean_probe.py tests/test_e_obligation_replayer.py tests/test_e_build_proof_context.py tests/test_e_proof_search_types.py tests/test_lean_runner.py
.venv/bin/pytest -q tests/test_orchestrator_minimal_skeleton_smoke.py::test_minimal_skeleton_run_archives_front_half_artifacts_and_summary tests/test_orchestrator_minimal_skeleton_smoke.py::test_orchestrator_minimal_feedback_reruns_sketch_and_b
.venv/bin/pytest -q tests/test_config.py tests/test_config_minimal_skeleton.py tests/test_cli_smoke.py::test_cli_smoke_local_text
.venv/bin/python -m py_compile src/mech_pipeline/adapters/lean_runner.py src/mech_pipeline/modules/e_certified_replay.py src/mech_pipeline/modules/e_action_guard.py src/mech_pipeline/modules/e_strategy_controller.py src/mech_pipeline/modules/e_obligation_replayer.py src/mech_pipeline/orchestrator.py src/mech_pipeline/config.py src/mech_pipeline/modules/__init__.py
```

结果：

- E 阶段新增/相关测试：37 passed
- Orchestrator minimal skeleton smoke：2 passed
- Config/CLI smoke：15 passed
- Python 编译检查：通过

## 当前边界

当前仍未实现完整 LLM-guided search controller。已经完成的是：

1. deterministic obligation replay 可以通过 Lean probe 检查 action。
2. action checks 和 trace artifacts 已接入 orchestrator。
3. LLM action proposal 有 guard。
4. LLM strategy prompt 已缩小到 compact proof state。

下一阶段可以实现 search loop：

- 从 deterministic replay prefix 开始。
- 调用 `LLMStrategyController` 生成 proposals。
- 对每个 proposal 先过 `ActionGuard`。
- 通过后用 `LeanRunner.probe_proof_prefix` 检查。
- accepted action 进入 `ProofSearchTrace`。
- 最终用 `verify_proof` 完整 replay。
