# MechLib v2 对接差异报告（2026-05-04）

## 1. 本次变更结论

本次已完成 MechLib v2 corpus 对接的代码层实现，并通过本地测试验证。核心变化不是改变主流程阶段，而是把原来“检索文本提示”升级为“可审计的 verified declaration / schema metadata 分层绑定”。

当前状态：

- 主 CLI 未变：`mech-baseline run --config ...`
- A -> MechLib -> B -> C -> D -> E 的 orchestrator 串联方式未变。
- `StatementCandidate` 旧字段全部保留；新增字段只作为 grounding metadata。
- C 阶段仍只检查 theorem statement elaboration，不要求 B 输出 proof。
- 已完成本地测试：`pytest -q`，结果为 `74 passed`。
- 101 题 live run 尚未执行：当前 shell 环境未设置 `OPENAI_PROXY_KEY`，因此没有生成新的 `mechlib-v2-audit-mechanics101-par5` 指标。

## 2. 与之前链路的关键区别

### 2.1 MechLib corpus 来源

之前多数配置使用：

- `../MechLib/theorem_corpus.jsonl`
- 当前本机该文件为 205 行。

本次默认新增 v2 corpus：

- `../MechLib/corpus/theorem_corpus.jsonl`：243 行。
- `../MechLib/corpus/decl_corpus_enriched.jsonl`：243 行。
- `../MechLib/corpus/law_schema_corpus.jsonl`：10 行。
- `../MechLib/corpus/problem_schema_corpus.jsonl`：12 行。
- `../MechLib/corpus/concept_corpus.jsonl`：9 行。
- `../MechLib/corpus/alias_map.jsonl`：4 行。

实际字段已从当前文件读取确认。`decl_corpus_enriched.jsonl` 中 243 行均为 `status=verified`，其中 199 行 `callable_by_llm=true`，3 行 `needs_review=true`。

### 2.2 Proof-eligible 与 schema metadata 分离

之前：

- MechLib context 主要是 summary text 与从 `.lean` 文件解析出的 source supplement。
- B/D 可以看到 theorem 名称，但没有稳定区分 verified declaration、schema metadata、alignment metadata。
- 历史报告中已经指出：系统常常“运行在 MechLib 环境中”，但没有证据表明稳定复用了检索到的 MechLib 定理。

现在：

- `decl_corpus_enriched.jsonl` 是 verified declaration 的主来源。
- 只有 `status=verified`、`callable_by_llm=true`、`needs_review=false` 的 declaration 会进入 proof-eligible context。
- law/problem/concept schema 只进入 `Schema Context`，明确标记为 metadata，不作为 proof fact。
- 如果只命中 schema 而没有 verified declaration，candidate 会标记：
  - `grounding_status = "gap_schema_only"`
  - `gap_schema_only = true`
  - `unsupported_claims` 中记录 `gap_schema_only:no_verified_decl_binding`

### 2.3 Candidate 与 ranking 可审计性

`StatementCandidate` 新增 JSON 可序列化字段：

- `verified_decl_refs`
- `schema_refs`
- `alias_refs`
- `grounding_status`
- `gap_schema_only`

B 阶段会把这些字段写入 `statement_candidates.jsonl`。D 阶段会把它们带入 semantic ranking，并在 `semantic_rank.jsonl` / README / revision feedback 中保留。metrics 中的 MechLib usage 判断也会识别 `verified_decl_refs`。

## 3. 历史结果基线

本机当前没有完整的新 101 题 live run 产物，因此这里只能先列历史基线，供 live run 完成后补齐对比。

### 3.1 101 题主流程历史基线

来自 `reports/MECHANICS_FULL_REALAPI_ANALYSIS_20260405.md`：

| 指标 | 2026-04-05 baseline |
| --- | ---: |
| total samples | 101 |
| grounding_success_rate | 0.970297 |
| lean_compile_success_rate | 0.886427 |
| semantic_consistency_pass_rate | 0.765957 |
| proof_success_rate | 0.428571 |
| end_to_end_verified_solve_rate | 0.415842 |
| end-to-end count | 42 / 101 |

### 3.2 101 题无 MechLib 检索消融

来自 `reports/MECHLIB_ABLATION_MECHANICS101_R1_ANALYSIS_20260413.md`：

| 指标 | no-MechLib retrieval |
| --- | ---: |
| total samples | 101 |
| grounding_success_rate | 0.980198 |
| lean_compile_success_rate | 0.926316 |
| semantic_consistency_pass_rate | 0.590909 |
| proof_success_rate | 0.323232 |
| end_to_end_verified_solve_rate | 0.316832 |
| end-to-end count | 32 / 101 |

历史解读：

- 关闭 MechLib 检索后 compile rate 没有下降，甚至略升。
- semantic 与 proof 明显下降。
- 这支持之前结论：旧 MechLib context 的主要价值在语义引导，而不是已经稳定实现的 theorem reuse。

### 3.3 本次 v2 对接后的预期可观测差异

live run 完成后，重点不只看端到端成功率，还应看以下新增/更精确的指标和文件字段：

- `mechlib_retrieval.jsonl`
  - `verified_decl_items_count`
  - `schema_items_count`
  - `alias_items_count`
  - `gap_schema_only`
  - `verified_decl_items`
  - `schema_items`
  - `alias_items`
- `statement_candidates.jsonl`
  - `verified_decl_refs`
  - `schema_refs`
  - `alias_refs`
  - `grounding_status`
  - `gap_schema_only`
- `semantic_rank.jsonl`
  - ranking item 内的 `verified_decl_refs`
  - `grounding_status`
  - `gap_schema_only`
  - `grounding_gap_summary`
- metrics
  - `statement_mechlib_usage_rate`
  - `selected_statement_mechlib_usage_rate`
  - `library_grounded_selection_rate`

如果 v2 对接有效，最直接的变化应是：

- `statement_mechlib_usage_rate` 不再主要依赖字符串命中旧 retrieval refs，而能通过 `verified_decl_refs` 被审计。
- schema-only 命中不会被误报为 MechLib theorem grounding。
- D 阶段更倾向选择 verified declaration bound candidate，而不是只有 schema metadata 的 candidate。

## 4. 当前验证结果

本地测试：

```text
pytest -q
74 passed in 1.34s
```

新增测试覆盖：

- v2 corpus loader 能读取 enriched declaration、schema、alias。
- B 阶段能标记 `verified_decl_bound`。
- B 阶段能标记 `gap_schema_only`。
- D 阶段会优先选择 verified declaration bound candidate。

真实 MechLib v2 corpus 探针：

```text
decl_entries 243
schema_entries 31
alias_entries 4
verified_decl_items_count 4
schema_items_count 3
gap_schema_only False
first_verified MechLib.Kinematics.PointMotion.displacement_forms_equiv_course_form
```

## 5. 待补齐的 101 题 live 对比

待运行命令：

```bash
mech-baseline run \
  --config configs/mechanics101_proxy_gpt54_20260409.yaml \
  --sample-concurrency 5 \
  --tag mechlib-v2-audit-mechanics101-par5
```

要求：

- `OPENAI_PROXY_KEY` 只通过环境变量提供。
- 不把 API key 写入 YAML、report、README 或 shell history。
- 运行完成后，用新 run 的 `metrics.json` 与本报告第 3 节两组历史结果对比。

建议补充的最终对比表：

| 指标 | 2026-04-05 baseline | no-MechLib retrieval | MechLib v2 run | v2 - baseline |
| --- | ---: | ---: | ---: | ---: |
| grounding_success_rate | 0.970297 | 0.980198 | TBD | TBD |
| lean_compile_success_rate | 0.886427 | 0.926316 | TBD | TBD |
| semantic_consistency_pass_rate | 0.765957 | 0.590909 | TBD | TBD |
| proof_success_rate | 0.428571 | 0.323232 | TBD | TBD |
| end_to_end_verified_solve_rate | 0.415842 | 0.316832 | TBD | TBD |
| statement_mechlib_usage_rate | historical limited | N/A | TBD | TBD |
| selected_statement_mechlib_usage_rate | historical limited | N/A | TBD | TBD |
| library_grounded_selection_rate | historical limited | N/A | TBD | TBD |

## 6. 风险与兼容性检查

已保持兼容：

- 旧 YAML 不需要新增字段即可加载。
- `statement.with_mechlib_context=false` 或 `knowledge.enabled=false` 时仍走旧模式。
- C 阶段仍只消费 `lean_header` 和 `theorem_decl`。
- E 阶段没有被强制要求证明新的 skeleton。
- 没有把 law schema / problem schema / concept metadata 当 proof fact。

需要注意：

- 当前配置默认 corpus 已切到 `../MechLib/corpus/theorem_corpus.jsonl`，但旧配置中显式写死 `../MechLib/theorem_corpus.jsonl` 的条目仍会按旧路径读取 summary corpus；v2 declaration corpus 独立由新增默认路径加载。
- `runs/` 与 `outputs/` 被 `.gitignore` 忽略；live run 会更新 ignored 产物，但不会修改 tracked 源码文件。
