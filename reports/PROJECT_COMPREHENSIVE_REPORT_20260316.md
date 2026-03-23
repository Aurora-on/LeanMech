# 项目综合报告（Baseline V1）

更新时间：2026-03-16

## 1. 项目定位与目标
本项目是一个面向力学题目的多模态自动形式化与 Lean4 验证/求解 baseline pipeline。当前阶段目标是：
- 先跑通完整链路（不做训练/微调）；
- 可分阶段评测；
- 可归因失败；
- 支持后续扩展（题型、数据源、证明策略）。

## 2. 当前代码架构

### 2.1 顶层结构
- `src/mech_pipeline/`：核心逻辑
  - `cli.py`：统一入口，编排 A-F 全流程
  - `config.py`：配置装载/合并/校验
  - `types.py`：全链路数据结构定义
  - `utils.py`：JSON 抽取、泄露清洗、Lean 文本归一化等通用工具
  - `modules/`：A-F 功能模块
  - `adapters/`：数据源与 Lean 适配
  - `model/`：LLM 适配（`openai_compatible` / `mock`）
  - `archive/`：run 目录与产物落盘
  - `eval/metrics.py`：分阶段指标计算
- `configs/`：运行配置模板
- `prompts/`：A/B/D/E Prompt 模板
- `runs/`：每次实验输出
- `reports/`：阶段性报告

### 2.2 A-F 模块职责
1. Module A（`A_grounding.py`）
- 输入：`CanonicalSample`（题干、可选图片/图描述）
- 输出：`GroundingResult`（统一 ProblemIR）
- 关键点：
  - 支持文本和图文（vision 不可用时自动降级文本）
  - 强制补齐 IR 必要字段
  - 题干先做泄露清洗（忽略 Answer/Solution/Proof 行）

2. Module B（`B_statement_gen.py`）
- 输入：`GroundingResult.problem_ir`
- 输出：4 个 `StatementCandidate`
- 关键点：
  - 只向 LLM 发送 IR 白名单字段
  - 规范 theorem/lemma 声明形态
  - 禁止 `: True / : False / : Prop`
  - 声明名安全化与乱码归一化

3. Module C（`C_compile_check.py` + `adapters/lean_runner.py`）
- 输入：statement 候选
- 输出：`CompileCheckResult`（逐候选 compile/elaboration 状态）
- 关键点：
  - 统一 `lake env lean` 在 PhysLean 下执行
  - preflight 检查 PhysLean 环境
  - 超时/异常已转为可归类错误，不会中断整次 run

4. Module D（`D_semantic_rank.py`）
- 输入：IR + compile pass 候选
- 输出：`SemanticRankResult`（排序、选中候选、语义通过）
- 关键点：
  - 显式区分“可编译”和“语义通过”
  - 当前为确定性启发式评分，不额外调用 LLM

5. Module E（`E_prover.py`）
- 输入：选中的 statement + IR
- 输出：`ProofAttemptResult[]` + `ProofCheckResult`
- 关键点：
  - 先 2 轮 LLM（生成 + 修复）
  - 再确定性 fallback tactics（`rfl/simp/aesop/linarith/ring`）
  - proof 过程与错误日志全量记录

6. Module F（`F_report.py`）
- 输入：全流程结果
- 输出：`metrics.json` + `analysis.md`
- 指标：
  - `grounding_success_rate`
  - `statement_generation_success_rate`
  - `lean_compile_success_rate`
  - `semantic_consistency_pass_rate`
  - `proof_success_rate`
  - `end_to_end_verified_solve_rate`

## 3. 组块之间的运行方式

### 3.1 总体流程
`CLI run` -> `DatasetAdapter` -> A -> B -> C -> D -> E -> F -> 输出 run 产物。

### 3.2 运行入口与配置
- 入口命令：
```powershell
python -m mech_pipeline.cli run --config <config.yaml> [--limit N] [--tag TAG]
```
- 主要配置：
  - `dataset`：`lean4phys | local_archive | phyx`
  - `model`：`openai_compatible | mock`
  - `lean`：PhysLean 路径、超时、preflight
  - `semantic`：阈值
  - `proof`：LLM 尝试次数
  - `prompts`：A/B/D/E 模板路径

### 3.3 每次 run 的产物
每个 run 目录至少包含：
- `problem_ir.jsonl`
- `statement_candidates.jsonl`
- `compile_checks.jsonl`
- `semantic_rank.jsonl`
- `proof_attempts.jsonl`
- `proof_checks.jsonl`
- `sample_summary.jsonl`
- `metrics.json`
- `analysis.md`
- `README.md`（含题目、候选 Lean 代码、语义排序、proof 每次尝试、最终结果）

## 4. 数据源与安全策略

### 4.1 数据源
- Lean4Phys：`LeanPhysBench_v0.json`
- 本地归档：`text_only`/`image_text` 两模式
- PhyX：镜像优先 + 官方回退（parquet URL 列表）

### 4.2 防泄露策略（已落地）
- 题干输入前清洗答案/解析/证明行；
- Lean4Phys 不再把 theorem/proof 等 gold 信息透传给后续 prompt；
- 向 LLM 发送的 IR 使用白名单字段；
- run 输出 `config.json` 已做敏感字段脱敏。

## 5. 与 Lean/PhysLean 的集成状态
- `physlean_dir` 默认：`F:/AI4Mechanics/PhysLean-master`
- 运行前 preflight：检查 `lakefile.toml`、`lean-toolchain`、探活 `lake env lean PhysLean/ClassicalMechanics/Basic.lean`
- 编译与 proof 检查均通过 `lake env lean` 执行
- 编码读取统一 UTF-8（并带 replace 回退），减少 Windows 编码问题

## 6. 当前成果（以最近有效 run 为准）

### 6.1 真实 API + Lean4Phys（3题）
- run：`runs/20260315_212014_selftest-r5`
- 指标：
  - grounding: 1.000
  - statement_generation: 1.000
  - lean_compile: 1.000
  - semantic: 0.333
  - proof: 0.333
  - end_to_end: 0.333
- 结论：链路稳定可跑通，短样本下已有可验证解，但证明成功率仍是主要瓶颈。

### 6.2 真实 API + Lean4Phys（单题烟测）
- run：`runs/20260315_235030_prompt-paper-check`
- 指标：全部 1.000
- 说明：用于验证 prompt 改造与新版 run README 内容完整性。

### 6.3 mock 回归（local/phyx）
- run：
  - `runs/20260315_211311_selftest-r5-local`
  - `runs/20260315_211311_selftest-r5-phyx`
- 指标：全部 1.000
- 说明：主要用于工程回归和链路稳定性，不代表真实 LLM 能力上限。

## 7. 当前可用于汇报的亮点
1. 从题目到 Lean 验证与 proof 的完整可运行链路已稳定。
2. 每阶段均可观测、可统计、可归因（含错误类型分布）。
3. run README 已提升为“可直接展示实验过程”的细粒度报告（含 proof 过程）。
4. 数据源、模型源、配置均可切换，便于后续做横向实验。
5. 数据泄露防护与配置脱敏机制已纳入主流程。

## 8. 当前主要不足
1. 真实 API（Lean4Phys）下 proof success 仍偏低（复杂题）。
2. 语义筛选仍为启发式，存在误判空间。
3. image+text 路径对复杂多图样本尚未系统增强。
4. 部分文本源存在历史编码噪声，需要持续清理。

## 9. 下一步建议（面向毕设推进）
1. 在 E 模块实现“候选切换重试”（semantic top-k 依次 proof）。
2. 对 Lean4Phys 进行 20-50 题小规模评测，按题型拆分统计。
3. 增加 proof 失败细分标签（rewrite 失败/类型不匹配/未解子目标）。
4. 为 image+text 增加结构化图信息抽取质量检查。
5. 将综合报告自动化生成（按 run 自动产出项目级汇总）。

## 10. 关键文件索引
- 入口编排：`src/mech_pipeline/cli.py`
- 模块：`src/mech_pipeline/modules/*.py`
- Lean 执行器：`src/mech_pipeline/adapters/lean_runner.py`
- 数据适配：`src/mech_pipeline/adapters/{lean4phys,local_archive,phyx}.py`
- 指标：`src/mech_pipeline/eval/metrics.py`
- Prompt：`prompts/*.txt`
- 多轮测试报告：`reports/SELFTEST_REPORT_20260315.md`
