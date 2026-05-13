# E 阶段阶段 4：ProofObligationReplayer 开发备注

日期：2026-05-11
范围：新增确定性 proof obligation replay 模块；不修改 pipeline 主流程，不接入 benchmark。

## 目标

阶段 4 的目标是把 minimal skeleton 中已经绑定好的 `proof_obligations` 优先转成确定性的 Lean `have` 片段。该步骤发生在 LLM strategy controller 之前，因为这些信息已经由 EvidenceBinder 和 ControlledSketch 给出，不应再让 LLM 猜测。

## 新增模块

新增文件：

- `src/mech_pipeline/modules/e_obligation_replayer.py`

核心类：

```python
ProofObligationReplayer(action_checker: ActionChecker | None = None)
```

核心方法：

```python
replay(context: ProofContext, proof_prefix: str = "") -> ObligationReplayResult
```

其中 `ActionChecker` 是可注入检查器：

```python
Callable[[ProofContext, str, ProofActionProposal], ProofActionCheckResult]
```

当前阶段不直接绑定 LeanRunner。后续可以把 local action checker 接到这里，使每个 deterministic `have` 都经过 Lean 检查后再进入 proof trace。若没有传入 `ActionChecker`，模块只会生成候选并把检查结果标为 invalid，不会把未检查 action 接收到 proof prefix 中。

## Replay 策略

对 `law_to_equation` 和 `constraint_to_equation` obligation，按顺序尝试：

```lean
have h_obl_x : <formal_claim> := by
  exact <must_use> <from_hypothesis>
```

然后尝试少量结构化替代：

```lean
have h_obl_x : <formal_claim> := by
  simpa using <must_use> <from_hypothesis>
```

```lean
have h_obl_x := <must_use> <from_hypothesis>
```

```lean
have h_obl_x : <formal_claim> := by
  simpa [<must_use>] using <from_hypothesis>
```

这些不是通用 proof portfolio，而是 verified extractor declaration 的确定性 replay。

## 安全规则

Replayer 只使用 `ProofContext.allowed_verified_decls` 中的 declaration。

阻断条件：

- 缺少 `from_hypothesis`：`from_hypothesis_missing`
- 缺少或不允许使用 `must_use`：`extractor_decl_mismatch`
- `formal_claim` 为空或形状不安全：`formal_claim_shape_mismatch`
- obligation kind 不支持或所有候选都失败：`obligation_replay_failed`

schema/problem_schema/concept metadata 不会作为 proof fact 使用；如果 `must_use` 不在 verified whitelist 中，直接 blocked。
从 ProofContext 继承来的 `missing_verified_extractor_decl`、`must_use_not_allowed_verified_decl`、`missing_formal_claim` 会在 replayer 层规范化为上述四类 replay failure tag。

## 新增测试

新增文件：

- `tests/test_e_obligation_replayer.py`

覆盖：

1. `law_to_equation` obligation 生成 `have`。
2. 生成的 action 正确使用 `from_hypothesis` 与 `must_use`。
3. 缺少 `must_use` 时 replay blocked。
4. 缺少 `from_hypothesis` 时 replay blocked。
5. schema metadata 不进入 proof fact。
6. 第一个 deterministic form 失败后会尝试 `simpa using` 替代形式。

## 测试命令

已运行：

```bash
.venv/bin/pytest -q tests/test_e_obligation_replayer.py tests/test_e_build_proof_context.py tests/test_e_proof_search_types.py
.venv/bin/pytest -q tests/test_e_config_modes.py tests/test_e_obligation_replayer.py tests/test_e_build_proof_context.py tests/test_e_proof_search_types.py tests/test_config.py tests/test_config_minimal_skeleton.py
.venv/bin/python -m py_compile src/mech_pipeline/modules/e_obligation_replayer.py src/mech_pipeline/modules/e_proof_context.py src/mech_pipeline/types.py
```

结果：

- proof obligation replay 相关测试：11 passed
- E 配置/上下文/回归组合测试：29 passed
- Python 编译检查：通过

## 当前边界

本阶段还没有实现：

- Lean proof state 读取。
- 真正的 local action checker。
- proof search node expansion。
- orchestrator 中的 `llm_guided_search` 路由接入。

当前模块已经为后续接入 Lean local checker 做好接口：只需要传入 `ActionChecker`，即可让 deterministic replay 的每个 candidate tactic block 经过 Lean 验证。
