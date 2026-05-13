# E 阶段阶段 1-3 开发备注

日期：2026-05-11
范围：新增配置、数据结构和 ProofContext 构造；保留 legacy E 行为，不接入新 proof search 主流程。

## 阶段 1：Proof 配置与模式路由

新增 `LLMGuidedSearchConfig`，挂在 `ProofConfig.llm_guided_search` 下。默认配置为：

- `proof.mode = "auto"`
- `proof.legacy_fallback_enabled = true`
- `llm_guided_search.enabled = true`
- `max_nodes = 80`
- `max_depth = 16`
- `max_llm_calls = 12`
- `proposals_per_call = 5`
- `max_action_chars = 1200`
- `max_failed_actions_kept = 20`
- `final_replay_required = true`
- `deterministic_obligation_replay_first = true`
- `deterministic_side_conditions_first = true`
- `allow_gap_assisted_proof = false`
- `require_verified_decl_use = true`
- `require_all_proof_obligations_covered = true`
- `allow_llm_subgoals = true`
- `allow_llm_rewrite_actions = true`
- `allow_llm_algebra_actions = true`
- `forbid_sorry = true`
- `forbid_admit = true`
- `forbid_axiom = true`
- `forbid_set_option = true`

新增 `select_proof_execution_mode(proof, candidate)`：

- `legacy_full_proof`：强制走旧 E。
- `llm_guided_search`：配置启用时走新 prover；禁用且允许 fallback 时走旧 E。
- `auto`：`candidate.generation_mode == "minimal_skeleton"` 或 `candidate.skeleton_mode = true` 时路由到 `llm_guided_search`，否则路由到 `legacy_full_proof`。

当前只提供路由 helper，尚未替换 orchestrator 中的 E 调用。

## 阶段 2：Proof search 数据结构

新增 dataclass：

- `ProofObligationReplayItem`
- `ProofActionProposal`
- `ProofActionCheckResult`
- `ProofSearchNode`
- `ProofSearchTrace`
- `ProofDependencyAudit`
- `ProofContext`

兼容性处理：

- 不改变现有 `ProofAttemptResult` / `ProofCheckResult` 必填字段。
- 给 `ProofAttemptResult` 追加可选字段：
  - `proof_search_trace`
  - `dependency_audit`

新增 JSONL 文件名已登记到 CLI stage rows：

- `proof_search_trace.jsonl`
- `proof_action_checks.jsonl`
- `proof_dependency_audit.jsonl`

当前这些文件会随 run artifact 体系存在，但 E 主流程还不会写入非空 trace。

## 阶段 3：ProofContext 构造

新增文件：

- `src/mech_pipeline/modules/e_proof_context.py`

实现：

```python
build_proof_context(
    *,
    sample_id: str,
    problem_ir: dict,
    selected_candidate: StatementCandidate | TheoremSkeletonCandidate,
    mechlib_context: str | None,
) -> ProofContext
```

当前 `ProofContext` 包含：

- `sample_id`
- `candidate_id`
- `theorem_decl`
- `lean_header`
- `target_formula`
- `local_binders`
- `local_hypotheses`
- `typed_binders`
- `hypothesis_provenance`
- `proof_obligations`
- `allowed_verified_decls`
- `allowed_local_facts`
- `gap_laws`
- `model_predicate_bindings`
- `explicit_model_gaps`
- `skeleton_mode`
- `obligation_replay_items`
- `obligation_replay_blocked`
- `mechlib_context_excerpt`

关键映射规则：

1. 优先从 `proof_obligations` 读取 `formal_claim`、`verified_decl`、`produces`。
2. 若缺少 `from_hypothesis`，根据 `source_model_instance` 查 `model_predicate_bindings.name`。
3. 若缺少 `must_use`，根据 `source_model_instance` 查 proof-eligible `evidence_bindings.verified_decl`。
4. 只允许 proof-eligible verified binding 进入 `allowed_verified_decls`：
   - `binding_status == "ok"`
   - `decl_status == "verified"`
   - `proof_fact_allowed == true`
   - `callable_by_llm is not false`
   - `lean_check_pass is not false`
5. `gap_schema_only`、schema-only law、explicit model gap 不进入 `allowed_verified_decls`。

当前不会从 schema 或自然语言 claim fallback 成 proof fact。

## 测试

新增测试：

- `tests/test_e_config_modes.py`
- `tests/test_e_proof_search_types.py`
- `tests/test_e_build_proof_context.py`

已运行：

```bash
.venv/bin/pytest -q tests/test_e_config_modes.py tests/test_e_proof_search_types.py tests/test_e_build_proof_context.py
.venv/bin/pytest -q tests/test_config.py tests/test_config_minimal_skeleton.py tests/test_types_model_ir.py tests/test_orchestrator_minimal_skeleton_smoke.py
.venv/bin/python -m py_compile src/mech_pipeline/config.py src/mech_pipeline/types.py src/mech_pipeline/modules/e_proof_context.py src/mech_pipeline/cli.py
```

结果：

- 新增测试：9 passed
- 相关回归测试：18 passed
- Python 编译检查：通过

## 当前边界

本次没有实现：

- Lean proof state 交互。
- 局部 tactic block 检查。
- proof search controller。
- E orchestrator 路由切换。
- legacy fallback 的实际调用包装。

这些属于后续阶段。当前改动只为 MechCopilot-style E prover 建立配置、artifact schema 和 minimal skeleton metadata 读取基础。
