# Minimal Skeleton Stage 6 接入报告（2026-05-04）

## 1. 结论

Stage 6 已把 minimal skeleton 前半段 artifacts 接入主 CLI run 的报告与指标层。主流程仍通过原 CLI 入口运行：

```bash
mech-baseline run --config ...
```

本阶段没有重构 E 阶段，也没有运行 live API 实验。验证使用本地 mock smoke 与 pytest。

## 2. 与 Stage 5 后状态的区别

| 项目 | Stage 5 后 | Stage 6 后 |
| --- | --- | --- |
| 主流程 artifacts | 已有前半段 JSONL rows | 继续保留，并验证 run 目录与 `outputs/latest` 同步 |
| `metrics.json` | 主要是 legacy 指标与 MechLib usage 指标 | 新增 minimal skeleton 前半段指标 |
| `analysis.md` | 未系统列出 ModelIR/Evidence/Sketch/Skeleton 计数 | 新增 `Minimal Skeleton Front Half` 区块 |
| run `README.md` | 未系统列出前半段接入摘要 | 新增 generation/model/evidence/audit/skeleton 字段 |
| tests | `111 passed` | `114 passed` |

## 3. 新增前半段指标

`metrics.json` 新增：

- `model_ir_success_rate`
- `evidence_binding_success_rate`
- `verified_binding_rate`
- `gap_schema_only_rate`
- `sketch_audit_pass_rate`
- `skeleton_generation_success_rate`
- `derived_equation_hypothesis_violation_rate`
- `schema_as_proof_fact_violation_rate`
- `explicit_gap_law_rate`

legacy 模式没有 minimal rows 时，上述字段返回 `null`，不影响旧配置或旧报告生成。

## 4. 新增报告字段

`analysis.md` 与 run `README.md` 新增：

- `generation_mode`
- `model_ir_ok`
- `evidence_binding_count`
- `verified_binding_count`
- `gap_schema_only_count`
- `sketch_audit_pass`
- `forbidden_hypothesis_count`
- `skeleton_candidate_count`

## 5. Mock Smoke 结果

运行命令：

```bash
.venv/bin/python -m mech_pipeline.cli run \
  --config configs/smoke_minimal_skeleton.yaml \
  --limit 1 \
  --tag minimal-skeleton-smoke \
  --sample-concurrency 1
```

产物目录：

- `runs/20260504_234501_minimal-skeleton-smoke`
- `outputs/latest`

新增 artifacts 在两处均存在：

- `model_ir.jsonl`
- `structured_mechlib_context.jsonl`
- `evidence_bindings.jsonl`
- `controlled_sketch.jsonl`
- `sketch_audit.jsonl`
- `theorem_skeleton_candidates.jsonl`

该 smoke run 的前半段指标：

| 指标 | 值 |
| --- | ---: |
| `model_ir_success_rate` | 1.0 |
| `evidence_binding_success_rate` | 1.0 |
| `verified_binding_rate` | 1.0 |
| `gap_schema_only_rate` | 0.0 |
| `sketch_audit_pass_rate` | 1.0 |
| `skeleton_generation_success_rate` | 1.0 |
| `derived_equation_hypothesis_violation_rate` | 0.0 |
| `schema_as_proof_fact_violation_rate` | 0.0 |
| `explicit_gap_law_rate` | 0.0 |

## 6. 测试结果

Stage 6 新增测试：

```text
tests/test_metrics_minimal_skeleton.py
tests/test_orchestrator_minimal_skeleton_smoke.py
```

验证结果：

```text
.venv/bin/python -m pytest -q tests/test_metrics_minimal_skeleton.py tests/test_orchestrator_minimal_skeleton_smoke.py
3 passed

.venv/bin/python -m pytest -q tests/test_types_model_ir.py tests/test_config_minimal_skeleton.py tests/test_structured_mechlib_context.py tests/test_evidence_binder.py tests/test_model_ir_builder.py tests/test_controlled_sketch.py tests/test_sketch_audit.py tests/test_b_minimal_skeleton.py tests/test_b_no_derived_hypotheses.py tests/test_metrics_minimal_skeleton.py tests/test_orchestrator_minimal_skeleton_smoke.py
38 passed

.venv/bin/python -m pytest -q
114 passed
```

## 7. 兼容性

- 旧配置不需要新增字段。
- `statement.generation_mode=legacy_candidate` 时新指标为 `null`，不会中断 metrics/report。
- `mech-baseline run --config ...` 不变。
- schema/problem/concept metadata 仍不会作为 proof fact 计数。
- E 阶段保持旧逻辑。
