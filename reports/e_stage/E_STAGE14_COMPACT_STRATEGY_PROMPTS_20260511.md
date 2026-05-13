# E 阶段阶段 14 开发报告：Prompt 与日志压缩

日期：2026-05-11

## 任务范围

本次实现 E 阶段 LLM strategy controller 的 compact prompt 约束与日志落盘。目标是让 LLM 只接收 proof-search 所需的紧凑证明状态，而不是完整 MechLib retrieval context、完整 ProblemIR 或 theorem corpus。

## 关键修改

修改文件：

```text
src/mech_pipeline/modules/e_strategy_controller.py
src/mech_pipeline/modules/e_search_controller.py
src/mech_pipeline/modules/E_prover.py
src/mech_pipeline/types.py
src/mech_pipeline/orchestrator.py
src/mech_pipeline/cli.py
prompts/E_strategy_controller.md
```

新增测试：

```text
tests/test_e_strategy_prompt_compact.py
```

## Prompt 输入约束

允许进入 prompt：

- target
- current proof prefix 摘要
- local facts
- remaining obligations
- allowed verified declarations
- last error excerpt
- failed action summaries
- strategy cards
- algebra strategy cards

禁止进入 prompt：

- 完整 `retrieval_context`
- 完整 `ProblemIR`
- 完整 `StructuredMechLibContext`
- 完整 previous proof attempts
- 完整 theorem corpus
- 长篇自然语言解题过程

实现层面：

- `compact_proof_state_payload` 对 target、proof prefix、last error、facts、decls、obligations、failed actions 做数量和长度裁剪。
- `LLMStrategyController.build_prompt` 对最终 prompt 设置 `< 8000` 字符的保守上限，必要时二次压缩。
- `run_llm_guided_search` 传入 `proof_prefix_summary`，而不是完整历史上下文。

## 新增落盘

新增 stage row：

```text
proof_strategy_prompts.jsonl
```

该文件只保存 compact prompt summary，不保存完整长 prompt：

- `prompt_chars`
- `target_excerpt`
- `proof_prefix_excerpt`
- `local_facts`
- `remaining_obligations`
- `allowed_decls`
- `failed_action_count`
- `prompt_excerpt`
- `omitted_context`

`omitted_context` 明确记录未落盘内容：

- `full_retrieval_context`
- `full_problem_ir`
- `full_structured_mechlib_context`
- `full_theorem_corpus`
- `full_previous_proof_attempts`

## 测试结果

已运行：

```bash
.venv/bin/pytest -q tests/test_e_strategy_prompt_compact.py tests/test_e_strategy_controller_prompt.py tests/test_e_search_controller_basic.py tests/test_e_mode_routing.py tests/test_e_proof_search_types.py
.venv/bin/python -m py_compile src/mech_pipeline/modules/e_strategy_controller.py src/mech_pipeline/modules/e_search_controller.py src/mech_pipeline/modules/E_prover.py src/mech_pipeline/types.py src/mech_pipeline/orchestrator.py src/mech_pipeline/cli.py
.venv/bin/pytest -q tests/test_e_config_modes.py tests/test_e_proof_search_types.py tests/test_e_build_proof_context.py tests/test_e_obligation_replayer.py tests/test_e_lean_probe.py tests/test_e_certified_replay.py tests/test_e_action_guard.py tests/test_e_strategy_controller_prompt.py tests/test_e_strategy_prompt_compact.py tests/test_e_side_condition_analyzer.py tests/test_e_search_controller_basic.py tests/test_e_algebra_strategy_cards.py tests/test_e_dependency_audit.py tests/test_e_mode_routing.py tests/test_e_prover.py tests/test_e_metrics_llm_guided_search.py tests/test_lean_runner.py
.venv/bin/pytest -q tests/test_config.py tests/test_config_minimal_skeleton.py tests/test_cli_smoke.py::test_cli_smoke_local_text tests/test_orchestrator_minimal_skeleton_smoke.py::test_minimal_skeleton_run_archives_front_half_artifacts_and_summary tests/test_orchestrator_minimal_skeleton_smoke.py::test_orchestrator_minimal_feedback_reruns_sketch_and_b
```

结果：

- 阶段 14 相关测试：`15 passed`
- E 阶段回归：`63 passed`
- 配置 / CLI / orchestrator smoke：`17 passed`

新增测试文件无 `axiom/sorry/admit` 命中。`e_strategy_controller.py` 中出现的 `sorry/admit/axiom` 是 prompt 禁止规则文本，不是代码使用。

## 当前限制

1. prompt 摘要仍保存短 `prompt_excerpt`，用于调试；若之后需要更严格脱敏，可以只保留结构化字段和 hash。
2. proof prefix 当前是文本摘要，不是 Lean proof-state AST。
3. prompt 长度上限为硬截断策略，后续可以改成按字段预算自适应分配。
