# LeanMech Minimal Pipeline 交接文档 2026-05-13

本文面向接手的新智能体，概括本轮对话中 minimal skeleton pipeline 的状态、已完成修改、验证结果、被中止的真实运行，以及下一步应优先处理的问题。

## 当前目标

本轮工作的目标是减少 minimal skeleton 流程中的 token 使用，同时尽量不降低性能。用户明确要求：

- 保留新 E 阶段，不允许为了跑通评测切回 legacy proof。
- B minimal 不应继续承担 theorem 生成职责；theorem skeleton 由 deterministic assembler 生成。
- 重点减少 B/A2/ControlledSketch/D/failure feedback 中重复传完整 artifact 的 token 浪费。
- 修改后使用新的 12 题评测集，模型 `gpt-5.4`，并发 4 做真实 API 测试。

## 已完成修改

### 1. B minimal 支持 no-LLM deterministic selector

相关文件：

- `src/mech_pipeline/config.py`
- `src/mech_pipeline/cli.py`
- `src/mech_pipeline/modules/B_statement_gen.py`
- `tests/test_b_minimal_skeleton.py`
- `tests/test_config_minimal_skeleton.py`

新增配置：

```yaml
statement:
  b_minimal_llm_enabled: false
  b_minimal_llm_on_retry: true
  compact_minimal_prompts: true
```

行为：

- CLI 构造 `ModuleB` 时读取这些配置。
- 默认首轮 minimal B 不调用 LLM，使用 deterministic payload。
- 如果 `b_minimal_llm_on_retry=true` 且 revision round 有反馈，B 可以继续调用 LLM 做选择。
- 直接实例化 `ModuleB` 的默认参数仍保持兼容：`b_minimal_llm_enabled=True`，避免旧单测和外部调用行为突变。

注意：

- B 仍然不会信任 LLM 生成的 `theorem_decl`。
- theorem declaration、typed binders、`.val` target、MechLib predicate binder 仍由 deterministic assembler 生成。
- 新增测试 `test_b_minimal_skeleton_can_skip_llm_selection` 覆盖首轮不调用 B LLM。

### 2. 新增 compact prompt view 层

新增文件：

- `src/mech_pipeline/prompt_views.py`

用途：

- 将完整归档 artifact 和传给 LLM 的 prompt payload 分离。
- 保留 runs/outputs 中完整 JSONL，但 A2/Sketch/B/D/feedback 不再默认吞完整上游对象。

核心 helper：

- `compact_problem_ir`
- `compact_structured_context`
- `compact_model_ir`
- `compact_evidence_bindings`
- `compact_controlled_sketch`
- `compact_sketch_audit`
- `compact_candidate_for_feedback`
- `compact_skeleton_candidate_for_semantic`

### 3. A2 / ControlledSketch / B / D / failure routing 改用 compact payload

相关文件：

- `src/mech_pipeline/modules/A2_model_ir.py`
- `src/mech_pipeline/modules/sketch_builder.py`
- `src/mech_pipeline/modules/B_statement_gen.py`
- `src/mech_pipeline/modules/D_semantic_rank.py`
- `src/mech_pipeline/failure_routing.py`

主要变化：

- A2 prompt 只接收 compact ProblemIR 和 compact structured MechLib context。
- ControlledSketch prompt 不再传完整 ModelIR raw_response、完整 structured context、完整 previous sketch/candidates。
- B minimal prompt 在需要调用 LLM 时使用 compact view；默认首轮不调用 LLM。
- D semantic rank 去掉重复的 `skeleton_semantic_payload`，改用 compact skeleton candidate payload。
- D 的 `mechlib_context` 字符串若过长会截断到 3000 字符。
- failure route 的 candidate feedback 改为 compact，保留必要的 audit details 和 compile/semantic 摘要。

## 已完成验证

### Focused tests

```bash
.venv/bin/python -m pytest -q \
  tests/test_config_minimal_skeleton.py \
  tests/test_b_minimal_skeleton.py \
  tests/test_failure_routing.py \
  tests/test_d_skeleton_aware_rank.py
```

结果：

```text
39 passed
```

### 关键回归

```bash
.venv/bin/python -m pytest -q \
  tests/test_orchestrator_minimal_routed_retry.py \
  tests/test_orchestrator_minimal_skeleton_smoke.py \
  tests/test_controlled_sketch.py \
  tests/test_sketch_audit.py \
  tests/test_semantic_rank.py \
  tests/test_cli_smoke.py
```

结果：

```text
46 passed
```

### 全量 pytest

```bash
.venv/bin/python -m pytest -q
```

结果：

```text
254 passed in 65.24s
```

## 真实 12 题评测状态

使用配置：

- `configs/minimal_testset_v1_selected12.yaml`
- fixture: `fixtures/bench_testset_v1_selected12.json`
- 模型：`gpt-5.4`
- 并发：4

启动过的命令：

```bash
.venv/bin/python -m mech_pipeline.cli run \
  --config configs/minimal_testset_v1_selected12.yaml \
  --sample-concurrency 4 \
  --tag minimal-token-opt-selected12-gpt54-20260513_152417
```

运行目录：

```text
runs/20260513_152417_minimal-token-opt-selected12-gpt54-20260513_152417
```

该 run 后来被中止。原因不是 B/D 前流程卡死，而是进入新 E 阶段后反复启动 `pipeline_proof_probe_*.lean` Lean 子进程，长时间不落盘最终 JSONL/metrics。用户指出如果暂时无法处理应停下，因此已终止父进程和遗留 proof worker。

中止前观察到：

- Lean preflight 通过。
- 12 个样本已入队，包含 `Mechanics73`。
- 至少 5/12 样本已完成到控制台 progress。
- run 根目录尚未写最终 JSONL，因为当前 orchestrator 在全部 sample 完成后统一落盘。
- 临时目录中已有 compile/proof 日志。
- 部分 compile 已通过，例如 `Mechanics3`, `Mechanics31`, `Mechanics73`, `Mechanics74`, `Mechanics76`, `Ch2_Q1`, `Ch2_Q2`。
- `Mechanics16` 有函数型/量纲算术 compile error。
- `Mechanics45` 出现 unknown identifier：`MechLib.Kinematics.PointMotion.HasDerivAt`。
- E proof search 对已 semantic-pass 的样本启动了多轮 Lean proof probes，长尾明显。

## 重要纠正

中途曾短暂把 `configs/minimal_testset_v1_selected12.yaml` 的 proof mode 改成 legacy，以绕开 E 长尾；用户明确指出“不可以改成 legacy，当前就是需要测试新的 E 阶段”。该临时改动已经恢复。

当前配置中不应存在：

```yaml
proof:
  mode: legacy_full_proof
  legacy_fallback_enabled: false
```

如果接手者看到这些字段，请不要保留，除非用户重新明确要求只测 D 前流程。

## 当前主要问题

### 1. 新 E 阶段长尾会掩盖 D 前 token 优化评测

`proof.mode=auto` 对 minimal skeleton candidate 会选择 `llm_guided_search`。默认预算来自 `LLMGuidedSearchConfig`：

- `max_nodes=80`
- `max_depth=16`
- `max_llm_calls=12`
- `proposals_per_call=5`

每个 semantic-pass sample 可能触发大量 LLM strategy call 和 Lean proof probe。12 题并发 4 时，E 子进程可能长时间持续运行，且 run 结果在全部 sample 结束前不会写最终 JSONL。

这不是本轮 B token 优化本身的失败，但会让真实评测难以快速收敛。

### 2. 当前 run 中间结果不可见

orchestrator 当前按 sample futures 收集结果，最后统一写 stage rows。长跑中如果 E 卡住，`runs/<run>/` 根目录没有 `model_ir.jsonl`、`statement_candidates.jsonl`、`semantic_rank.jsonl`、`metrics.json`，只能从 `.pipeline1_tmp` 和 Lean log 推断状态。

建议后续支持按 sample flush stage rows，至少在 long run 中写增量 JSONL。

### 3. 仍存在函数型物理量和 MechLib declaration 对接问题

中止 run 的 compile log 显示：

- `Mechanics16`：`a_y 2` 期望 `Time`，以及 `Acceleration` 和 `Real/Nat` 的乘除实例不匹配。
- `Mechanics45`：`MechLib.Kinematics.PointMotion.HasDerivAt` unknown identifier。

这些属于 A2/B/EvidenceBinder/MechLib signature 对接问题，不应通过题目专用兜底解决。

## 建议下一步

### A. 先不要继续扩大真实 API 评测

当前真实 run 的主要阻塞已从 token prompt 优化转移到新 E proof search 长尾和增量落盘不可见。建议先修 E 的预算/可观测性，再重跑 12 题。

### B. 为新 E 增加测试预算配置

在不切回 legacy 的前提下，可以新增真实评测专用配置，例如：

```yaml
proof:
  mode: llm_guided_search
  legacy_fallback_enabled: false
  llm_guided_search:
    enabled: true
    max_nodes: 12
    max_depth: 6
    max_llm_calls: 3
    proposals_per_call: 3
```

这仍然测试新 E，但避免默认 `80 nodes / 12 LLM calls` 在 12 题并发 run 中失控。需要用户确认是否接受“新 E 限预算测试”。

### C. 增量落盘

建议修改 orchestrator/archive writer：

- 每个 sample 完成后立即 append stage rows。
- `sample_summary.jsonl` 和核心 stage JSONL 不等全部样本结束。
- 长跑中可以看到 A2/B/C/D/E 到哪一步，而不是只能看 Lean 临时日志。

### D. 保持 B no-LLM 改动，继续比较 token 与性能

待 E 可控后，复用 12 题集比较：

1. `b_minimal_llm_enabled=false`
2. `b_minimal_llm_enabled=true`
3. `b_minimal_llm_enabled=false`, `b_minimal_llm_on_retry=true`

统计：

- A2/Sketch/B/D LLM 调用次数；
- B 是否真的首轮 0 call；
- C/D 通过率；
- E 新 proof search 成功率；
- 总耗时和 proof probe 数量。

## 当前进程状态

已执行清理：

- 终止 `minimal-token-opt-selected12-gpt54-20260513_152417` run。
- 终止误启动的 `legacyproof` run。
- 终止遗留的 `.pipeline1_tmp/proof` Lean worker。

接手者在继续前可再次检查：

```bash
ps -Ao pid,ppid,etime,pcpu,pmem,command | \
  rg 'minimal-token-opt-selected12|pipeline_proof_probe|mech_pipeline.cli run --config configs/minimal_testset_v1_selected12.yaml|\\.pipeline1_tmp/proof'
```

预期应无相关活跃进程。

## 不要做的事

- 不要为了跑快把新 E 静默切到 legacy。
- 不要为了让某个题通过添加题目专用 fallback。
- 不要让 B 重新信任 LLM theorem_decl。
- 不要把 schema/problem/concept metadata 当作 proof fact。
- 不要伪造不存在的 MechLib declaration。
