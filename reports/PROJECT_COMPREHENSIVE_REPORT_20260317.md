# 项目综合报告（Baseline V1，2026-03-17）

## 1. 项目定位
本项目是一个面向力学题目的模块化 baseline pipeline，目标是验证在 **zero-shot / few-shot、无专项训练** 条件下，各阶段可达成功率与失败归因能力。

当前版本坚持：
- 先可运行、可评测、可解释；
- 不做训练/微调/RL；
- 先 text-only，再扩展 image+text；
- 先 statement generation，再 proof generation。

## 2. 系统架构总览

### 2.1 流程图（文字版）
`题目输入 -> A结构化 -> B命题候选(k=4) -> C Lean编译检查 -> D语义一致性筛选 -> E证明生成/修复 -> F指标与报告`

### 2.2 目录与职责
- `src/mech_pipeline/cli.py`：主编排入口，串联 A-F，全流程落盘。
- `src/mech_pipeline/modules/`：A-F 六个模块。
- `src/mech_pipeline/adapters/`：数据适配器（Lean4Phys / local archive / PhyX）+ Lean 执行器。
- `src/mech_pipeline/model/`：LLM 适配（mock 与 openai_compatible）。
- `src/mech_pipeline/eval/`：指标计算与错误分类。
- `prompts/`：A/B/D/E 提示词模板。
- `configs/`：运行配置。

## 3. 各模块运行方式

### A. Grounding（题目理解与结构化）
- 输入：`CanonicalSample`（文本、可选图片/图描述）。
- 输出：`GroundingResult`（统一 ProblemIR）。
- 核心实现：`src/mech_pipeline/modules/A_grounding.py`
- 关键点：
  - 支持文本与图文（模型不支持视觉时回退文本）。
  - 强制补齐 schema：`objects/known_quantities/unknown_target/...`。
  - 对题目先做泄露清洗（`Answer/Solution/Proof` 行过滤）。

### B. Statement Generation（IR -> Lean 候选）
- 输入：`problem_ir`。
- 输出：4 个 `StatementCandidate`。
- 核心实现：`src/mech_pipeline/modules/B_statement_gen.py`
- 关键点：
  - 固定 `k=4`，不足时补 fallback。
  - 禁止 trivial goal（`: True/: False/: Prop`）。
  - 统一声明名、清理乱码符号、禁止 proof body 混入。

### C. Compile Check（Lean 编译/展开检查）
- 输入：4 个候选 theorem/lemma 声明。
- 输出：逐候选 `CompileCheckResult`（compile/syntax/elaboration/error/log）。
- 核心实现：`src/mech_pipeline/modules/C_compile_check.py`
- Lean 执行：`src/mech_pipeline/adapters/lean_runner.py`
- 关键点：
  - 统一在 `lake env lean` + PhysLean 环境下执行。
  - 提供 preflight（目录、`lakefile.toml`、`lean-toolchain`、探活文件）。

### D. Semantic Ranking（语义一致性筛选）
- 输入：compile 通过的候选 + 原题 + IR。
- 输出：`SemanticRankResult`（排序、最佳候选、语义通过标记）。
- 核心实现：`src/mech_pipeline/modules/D_semantic_rank.py`
- 关键点：
  - 规则分（target/known/law/unit/assumption）+ LLM 语义回译与打分融合。
  - 显式 hard gate（`trivial_goal/target_mismatch/law_mismatch/known_quantity_mismatch`）。
  - 明确区分“可编译”与“语义正确”。

### E. Prover（证明生成与修复）
- 输入：D 选中 statement + IR。
- 输出：`ProofAttemptResult[]` + `ProofCheckResult`。
- 核心实现：`src/mech_pipeline/modules/E_prover.py`
- 关键点：
  - 先 LLM 生成，再 LLM 修复（按 `max_attempts`）。
  - 失败后再试确定性 tactics（`rfl/simp/aesop/linarith/ring`）。
  - 严格禁止 `sorry/admit/axiom`。

### F. Report（指标与分析）
- 输入：全阶段结果。
- 输出：`metrics.json`、`analysis.md`、run README 与全量 jsonl。
- 核心实现：`src/mech_pipeline/modules/F_report.py`

## 4. LLM 与 Lean 的交互机制

### 4.1 LLM 交互
- 统一入口：`build_model_client()` -> `OpenAICompatibleClient` 或 `MockModelClient`。
- 实现位置：
  - `src/mech_pipeline/model/base.py`
  - `src/mech_pipeline/model/openai_compatible.py`
- 当前 D 模块没有引入“第二个独立模型”，而是复用同一个 `model_client` 做语义回译与评分。

### 4.2 Lean 交互
- 统一执行器：`LeanRunner`（preflight / compile_statement / verify_proof）。
- 执行命令：`lake env lean <tmp_file.lean>`（工作目录在 PhysLean）。
- 错误归类：`invalid_lean_syntax / missing_import_or_namespace / elaboration_failure / ...`。

## 5. 数据源与防泄露策略

### 5.1 数据源
- Lean4Phys：`src/mech_pipeline/adapters/lean4phys.py`
- 本地归档：`src/mech_pipeline/adapters/local_archive.py`
- PhyX：`src/mech_pipeline/adapters/phyx.py`

### 5.2 防泄露设计（已落地）
- 仅使用 Lean4Phys `Informal_statement` 作为问题输入，避免把 `Statement/Theorem/Proof` 作为 prompt 内容。
- 输入文本统一经 `redact_leakage_text()` 清洗。
- 向 LLM 传递的 IR 字段走白名单 `sanitize_problem_ir_for_llm()`。
- 运行配置写盘时 API 密钥字段脱敏（`***REDACTED***`）。

## 6. 评测协议与错误分类

### 6.1 核心指标
- `grounding_success_rate`
- `statement_generation_success_rate`
- `lean_compile_success_rate`
- `semantic_consistency_pass_rate`
- `proof_success_rate`
- `end_to_end_verified_solve_rate`

### 6.2 错误分类（最小闭集）
定义位置：`src/mech_pipeline/eval/error_taxonomy.py`

包含：
- `visual_grounding_failure`
- `missing_diagram_information`
- `variable_mapping_error`
- `wrong_target_extraction`
- `unit_dimension_mismatch`
- `invalid_lean_syntax`
- `missing_import_or_namespace`
- `elaboration_failure`
- `semantic_drift`
- `proof_search_failure`
- `partially_correct_but_unverifiable`
- `unsupported_multi_image_sample`
- `data_source_unavailable`
- `physlean_missing`
- `physlean_env_error`

## 7. 当前可复现实验结果（2026-03-17）

### 7.1 代码测试
- 命令：`pytest -q`
- 结果：`14 passed in 1.66s`

### 7.2 快速 smoke 运行（mock，本地文本，3题）
- 运行目录：`runs/20260317_093636_report-smoke-20260317`
- 指标：
  - `grounding_success_rate = 1.0`
  - `statement_generation_success_rate = 1.0`
  - `lean_compile_success_rate = 0.0`（该配置 `lean.enabled=false`）
  - `semantic_consistency_pass_rate = 0.0`
  - `proof_success_rate = 0.0`
  - `end_to_end_verified_solve_rate = 0.0`
- 解读：
  - A/B 链路可稳定执行；
  - 当前 smoke 配置用于通路验证，不用于评估真实 Lean 验证能力。

## 8. 当前问题与风险
- D 阶段仍可能出现“语义误判”与 hard gate 边界问题。
- E 阶段 proof 成功率在真实题目上仍是主要瓶颈。
- 长时运行中断时可能残留 `lake/lean` 子进程，需要主动清理。
- Windows 终端编码链路复杂，虽已做 UTF-8 处理，仍建议统一按 UTF-8 终端运行。

## 9. 下一阶段建议
1. 在 D 中加入更强的“目标覆盖率”约束，减少“可证但题意弱对齐”。
2. 在 E 中增加“候选切换重试”（不仅修复同一候选，还尝试 semantic top-k）。
3. 增加 proof 失败细分统计（哪类 tactic/哪类 goal 最常失败）。
4. 为 Lean4Phys mechanics 做固定样本集基准（例如 10/20/50 题分层评测）。
5. 将本报告自动化（每次 run 自动产出项目级 summary）。

## 10. 关键文件索引
- 编排入口：`src/mech_pipeline/cli.py`
- 配置：`src/mech_pipeline/config.py`
- 模块 A-F：`src/mech_pipeline/modules/*.py`
- Lean 执行器：`src/mech_pipeline/adapters/lean_runner.py`
- 数据适配器：`src/mech_pipeline/adapters/{lean4phys,local_archive,phyx}.py`
- 模型适配：`src/mech_pipeline/model/{base,openai_compatible,mock}.py`
- Prompt：`prompts/{A_extract_ir,B_generate_statements,D_semantic_rank,E_generate_proof,E_repair_proof}.txt`
