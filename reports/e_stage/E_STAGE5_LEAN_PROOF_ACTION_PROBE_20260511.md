# E 阶段阶段 5：Lean proof action probe 开发备注

日期：2026-05-11
范围：为 LeanRunner 增加 proof prefix 探测接口；不改变 legacy `verify_proof` 语义，不接入 proof search 主循环。

## 目标

为了让后续 MechCopilot-style search 能逐步检查 LLM/deterministic tactic block，本阶段新增局部 proof prefix probe：

```python
LeanRunner.probe_proof_prefix(
    *,
    lean_header: str,
    theorem_decl: str,
    proof_prefix: str,
    timeout_s: int | None = None,
) -> ProofActionCheckResult
```

该接口把 theorem 包装为：

```lean
<header>

<theorem_decl> := by
  <proof_prefix>
```

然后调用 Lean。

## 状态分类

粗分类规则：

- Lean 无错误并通过：`status = "closed"`
- Lean 报 `unsolved goals`：`status = "progress"`，并填充 `goals_excerpt`
- Lean 报 unknown identifier / type mismatch / invalid field notation / tactic failed / syntax error 等：`status = "invalid"`

当前实现还会识别：

- `symbol_hallucination`
- `namespace_or_import_issue`
- `type_mismatch`
- `wrong_api_shape`
- `tactic_failed`
- `invalid_lean_syntax`
- `timeout_or_tooling_block`
- `forbidden_token`

## 安全规则

probe 不允许使用：

- `sorry`
- `admit`
- `axiom`
- `set_option`

这些 token 会在调用 Lean 前被拦截，返回：

```text
status = invalid
error_type = forbidden_token
```

`unsolved goals` 在 probe 层只表示当前 prefix 语法和已执行 tactic 局部有效，不代表最终 proof 成功。最终 proof 仍必须由 `verify_proof` 完整 replay 通过。

## 兼容性处理

`_run_lean` 新增可选 `timeout_s` 参数，但旧调用不需要传入。为了兼容既有测试中 monkeypatch 的 `_run_lean(root_dir, rel_file)`，`_run_probe_code` 只有在显式传入 timeout 时才把 `timeout_s` 传给 `_run_lean`。

## 新增测试

新增文件：

- `tests/test_e_lean_probe.py`

测试 theorem：

```lean
theorem e_probe_real_symm (a b : Real) (h : a = b) : b = a
```

覆盖：

1. `symm\nexact h` -> `closed`
2. `symm` -> `progress` / `unsolved_goals`
3. `exact missing_h` -> `invalid` / `symbol_hallucination`
4. `sorry` -> `invalid` / `forbidden_token`

## 测试命令

已运行：

```bash
.venv/bin/pytest -q tests/test_e_lean_probe.py
.venv/bin/pytest -q tests/test_lean_runner.py tests/test_e_lean_probe.py tests/test_e_obligation_replayer.py tests/test_e_build_proof_context.py
.venv/bin/pytest -q tests/test_e_config_modes.py tests/test_e_lean_probe.py tests/test_e_obligation_replayer.py tests/test_e_build_proof_context.py tests/test_e_proof_search_types.py tests/test_lean_runner.py
.venv/bin/python -m py_compile src/mech_pipeline/adapters/lean_runner.py src/mech_pipeline/modules/e_obligation_replayer.py src/mech_pipeline/types.py
```

结果：

- Lean probe 测试：4 passed
- LeanRunner + E probe/context/replayer 组合测试：27 passed
- Python 编译检查：通过

## 当前边界

本阶段只提供 proof action probe。尚未实现：

- proof state 的结构化读取。
- search controller。
- LLM tactic proposal prompt。
- `ProofObligationReplayer` 与 LeanRunner probe 的实际 wiring。
- final replay 前的 dependency audit。

下一阶段应把 `probe_proof_prefix` 包成 `ActionChecker`，传给 `ProofObligationReplayer`，并把 accepted/rejected actions 写入 `proof_action_checks.jsonl` 与 `proof_search_trace.jsonl`。
