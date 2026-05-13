# Mechanics101 Minimal Routed Run 样本检测表

Run: `runs/20260511_154009_minimal-routed-101-realapi-20260511`

配置摘要：

- 数据集：Lean4Phys mechanics，101 题
- 模式：`generation_mode=minimal_skeleton`
- 反馈：`minimal_feedback_scope=routed_stage`
- 并发：10
- 模型：`gpt-5.4`
- API：`https://api.openai-proxy.org`

## 总览

| 项目 | 数量 / 比率 |
|---|---:|
| 总样本 | 101 |
| A/grounding 成功 | 96 |
| A2 ModelIR 成功率 | 0.920792 |
| SketchAudit 通过率 | 0.762376 |
| Skeleton 生成成功率 | 0.663366 |
| C Lean compile 成功率 | 0.425743 |
| D semantic 成功率 | 0.366337 |
| E proof 成功数 | 17 |
| End-to-end 成功率 | 0.168317 |
| Feedback loop 使用率 | 0.653465 |

主要失败类型：

- C/E 阶段大量 `type_mismatch`
- SketchAudit 中 `target_leakage` / `raw_law_equation_in_hypotheses`
- A2 的 canonical target / forbidden target assumption 问题
- EvidenceBinder 的 `no_verified_decl` 触发大量 routed retry

Mechanics73 本次状态：

- A2：通过
- SketchAudit：通过
- B skeleton：通过
- C compile：通过
- D semantic：通过
- E proof：失败，`type_mismatch`

## 样本检测表

说明：

- `Y/N` 表示该阶段是否通过。
- `Route` 是触发反馈时的责任阶段。
- `主要问题` 以最终失败点为主。
- `OK` 表示端到端 proof 成功。

| # | 样本 | A2 | Sketch | B | C | D | E | Route | 主要问题 |
|---:|---|:--:|:--:|:--:|:--:|:--:|:--:|---|---|
| 1 | Mechanics_1 | Y | Y | Y | N | N | N | A2 | C compile: type_mismatch |
| 2 | Mechanics_2 | Y | Y | Y | Y | Y | Y | - | OK |
| 3 | Mechanics_3 | Y | Y | N | N | N | N | EvidenceBinder | B blocked: blocked_by_evidence_gap |
| 4 | Mechanics_4_Converting_speed_units | Y | Y | Y | Y | Y | Y | - | OK |
| 5 | Mechanics_5_Converting_volume_units | Y | Y | N | N | N | N | A2 | B blocked: invalid_function_formula_ir |
| 6 | Mechanics_6_Significant_figures_in_multiplication | Y | N | N | N | N | N | EvidenceBinder | SketchAudit: schema_used_as_proof_fact, raw_law_equation_in_hypotheses |
| 7 | Mechanics_8 | Y | Y | N | N | N | N | EvidenceBinder | B blocked: Length sqrt / quantity coercion issue |
| 8 | Mechanics_9 | N | N | N | N | N | N | A2 | A2 ModelIR: missing forbidden target assumption |
| 9 | Mechanics_10 | Y | N | N | N | N | N | A2 | SketchAudit: target_leakage |
| 10 | Mechanics_11 | Y | Y | Y | N | N | N | A2 | C compile: type_mismatch |
| 11 | Mechanics_12 | Y | N | N | N | N | N | A2 | SketchAudit: target_leakage |
| 12 | Mechanics_13 | Y | N | N | N | N | N | EvidenceBinder | SketchAudit: target_leakage |
| 13 | Mechanics_14 | Y | Y | Y | N | N | N | EvidenceBinder | C compile: type_mismatch |
| 14 | Mechanics_15 | N | N | N | N | N | N | A2 | A2 ModelIR: missing forbidden target assumption |
| 15 | Mechanics_16 | Y | Y | N | N | N | N | A2 | B blocked: invalid_function_formula_ir |
| 16 | Mechanics_17 | Y | N | N | N | N | N | EvidenceBinder | SketchAudit: target_leakage, raw_law_equation_in_hypotheses |
| 17 | Mechanics_18 | Y | N | N | N | N | N | EvidenceBinder | SketchAudit: target_leakage |
| 18 | Mechanics_19 | Y | N | N | N | N | N | EvidenceBinder | SketchAudit: target_leakage |
| 19 | Mechanics_20 | Y | Y | Y | Y | Y | Y | A2 | OK |
| 20 | Mechanics_21 | Y | N | N | N | N | N | EvidenceBinder | SketchAudit: raw_law_equation_in_hypotheses |
| 21 | Mechanics_22 | Y | Y | Y | Y | Y | N | A2 | E proof: type_mismatch |
| 22 | Mechanics_23 | Y | N | N | N | N | N | A2 | SketchAudit: target_leakage |
| 23 | Mechanics_24 | Y | Y | Y | Y | Y | N | - | E proof: type_mismatch |
| 24 | Mechanics_25 | Y | Y | Y | Y | N | N | A2 | D semantic: trivial_goal |
| 25 | Mechanics_26 | Y | Y | N | N | N | N | EvidenceBinder | C compile: no compile-passed candidate |
| 26 | Mechanics_27 | Y | N | N | N | N | N | EvidenceBinder | SketchAudit: target_leakage |
| 27 | Mechanics_28 | N | N | N | N | N | N | A2 | A2 ModelIR: missing forbidden target assumption |
| 28 | Mechanics_29 | N | N | N | N | N | N | A2 | A2 ModelIR: missing forbidden target assumption |
| 29 | Mechanics_30 | Y | Y | Y | N | N | N | EvidenceBinder | C compile: type_mismatch |
| 30 | Mechanics_31 | Y | Y | Y | Y | Y | Y | - | OK |
| 31 | Mechanics_32 | Y | Y | Y | N | N | N | EvidenceBinder | C compile: type_mismatch |
| 32 | Mechanics_33 | Y | Y | Y | N | N | N | A2 | C compile: type_mismatch |
| 33 | Mechanics_34 | Y | Y | Y | Y | Y | Y | - | OK |
| 34 | Mechanics_35 | Y | N | N | N | N | N | EvidenceBinder | SketchAudit: raw_law_equation_in_hypotheses |
| 35 | Mechanics_36 | Y | N | N | N | N | N | A2 | SketchAudit: target_leakage |
| 36 | Mechanics_37 | Y | Y | N | N | N | N | EvidenceBinder | B blocked: tuple/function target shape not first-order Lean-like |
| 37 | Mechanics_38 | Y | N | N | N | N | N | A2 | SketchAudit: target_leakage |
| 38 | Mechanics_39 | N | N | N | N | N | N | A2 | A2 ModelIR: missing forbidden target assumption |
| 39 | Mechanics_40 | Y | Y | Y | N | N | N | A2 | C compile: type_mismatch |
| 40 | Mechanics_43 | Y | Y | Y | Y | Y | N | A2 | E proof: type_mismatch |
| 41 | Mechanics_44 | N | N | N | N | N | N | A2 | A2 ModelIR: missing forbidden target assumption |
| 42 | Mechanics_45 | Y | Y | Y | Y | Y | Y | - | OK |
| 43 | Mechanics_46 | Y | Y | Y | Y | N | N | A2 | D semantic: wrong_target |
| 44 | Mechanics_47 | Y | Y | N | N | N | N | A2 | B blocked: invalid_function_formula_ir |
| 45 | Mechanics_48 | N | N | N | N | N | N | - | A grounding: wrong_target_extraction |
| 46 | Mechanics_49 | N | N | N | N | N | N | - | A grounding: wrong_target_extraction |
| 47 | Mechanics_51 | Y | Y | Y | Y | Y | N | - | E proof: type_mismatch |
| 48 | Mechanics_52 | Y | N | N | N | N | N | EvidenceBinder | SketchAudit: raw_law_equation_in_hypotheses |
| 49 | Mechanics_53 | Y | Y | Y | Y | Y | Y | - | OK |
| 50 | Mechanics_54 | Y | Y | Y | Y | Y | Y | A2 | OK |
| 51 | Mechanics_55 | Y | Y | Y | Y | Y | Y | - | OK |
| 52 | Mechanics_56 | Y | N | N | N | N | N | A2 | SketchAudit: schema_used_as_proof_fact |
| 53 | Mechanics_59 | Y | Y | Y | Y | Y | Y | - | OK |
| 54 | Mechanics_60 | Y | N | N | N | N | N | A2 | SketchAudit: raw_law_equation_in_hypotheses |
| 55 | Mechanics_61 | Y | Y | Y | Y | Y | N | EvidenceBinder | E proof: type_mismatch |
| 56 | Mechanics_62 | Y | Y | Y | Y | N | N | A2 | D semantic: trivial_goal |
| 57 | Mechanics_63 | Y | N | N | N | N | N | EvidenceBinder | SketchAudit: target_leakage |
| 58 | Mechanics_64 | Y | Y | Y | Y | Y | Y | - | OK |
| 59 | Mechanics_65 | Y | Y | Y | Y | Y | Y | - | OK |
| 60 | Mechanics_66 | Y | Y | Y | Y | Y | Y | - | OK |
| 61 | Mechanics_67 | Y | Y | Y | Y | Y | N | - | E proof: type_mismatch |
| 62 | Mechanics_68 | Y | Y | Y | Y | Y | Y | - | OK |
| 63 | Mechanics_69 | Y | Y | Y | Y | Y | N | - | E proof: type_mismatch |
| 64 | Mechanics_70 | Y | Y | Y | Y | Y | Y | - | OK |
| 65 | Mechanics_71 | Y | Y | Y | Y | Y | N | - | E proof: type_mismatch |
| 66 | Mechanics_72 | N | N | N | N | N | N | - | A grounding: wrong_target_extraction |
| 67 | Mechanics_73 | Y | Y | Y | Y | Y | N | - | E proof: type_mismatch |
| 68 | Mechanics_74 | Y | Y | Y | Y | Y | Y | - | OK |
| 69 | Mechanics_75 | Y | Y | Y | Y | Y | Y | - | OK |
| 70 | Mechanics_76 | Y | Y | Y | Y | Y | N | - | E proof: type_mismatch |
| 71 | Mechanics_77 | Y | Y | Y | Y | Y | N | - | E proof: type_mismatch |
| 72 | Ch1_Q1 | Y | Y | Y | Y | Y | N | - | E proof: type_mismatch |
| 73 | Ch1_Q2 | Y | Y | Y | N | N | N | EvidenceBinder | C compile: type_mismatch |
| 74 | Ch1_Q3 | Y | N | N | N | N | N | EvidenceBinder | SketchAudit: raw_law_equation_in_hypotheses |
| 75 | Ch1_Q4 | Y | Y | Y | Y | N | N | A2 | D semantic: wrong_target |
| 76 | Ch1_Q5 | Y | Y | Y | Y | Y | N | A2 | E proof: type_mismatch |
| 77 | Ch1_Q6 | Y | Y | N | N | N | N | EvidenceBinder | B blocked: angle coercion / PhysAngle target issue |
| 78 | Ch1_Q7 | N | N | N | N | N | N | - | A grounding: wrong_target_extraction |
| 79 | Ch1_Q8 | Y | Y | Y | N | N | N | A2 | C compile: type_mismatch |
| 80 | Ch1_Q9 | Y | Y | N | N | N | N | EvidenceBinder | B blocked: directional-vector semantics incomplete |
| 81 | Ch1_Q10 | Y | Y | Y | N | N | N | EvidenceBinder | C compile: type_mismatch |
| 82 | Ch1_Q11 | Y | Y | Y | Y | Y | N | A2 | E proof: type_mismatch |
| 83 | Ch1_Q12 | Y | Y | Y | N | N | N | EvidenceBinder | C compile: type_mismatch |
| 84 | Ch1_Q13 | Y | Y | Y | Y | Y | N | - | E proof: type_mismatch |
| 85 | Ch1_Q14 | Y | Y | Y | Y | Y | N | - | E proof: type_mismatch |
| 86 | Ch2_Q1 | Y | Y | Y | Y | Y | N | - | E proof: type_mismatch |
| 87 | Ch2_Q2 | Y | Y | Y | Y | Y | N | - | E proof: type_mismatch |
| 88 | Ch2_Q3 | Y | Y | Y | N | N | N | EvidenceBinder | C compile: type_mismatch |
| 89 | Ch2_Q4 | Y | Y | Y | N | N | N | EvidenceBinder | C compile: type_mismatch |
| 90 | Ch2_Q5 | Y | N | N | N | N | N | EvidenceBinder | SketchAudit: target_leakage, raw_law_equation_in_hypotheses |
| 91 | Ch3_Q1 | Y | Y | Y | Y | Y | N | - | E proof: type_mismatch |
| 92 | Ch3_Q2 | Y | Y | Y | N | N | N | A2 | C compile: type_mismatch |
| 93 | Ch4_Q1 | N | N | N | N | N | N | - | A grounding: wrong_target_extraction |
| 94 | Ch4_Q2 | Y | Y | Y | N | N | N | A2 | C compile: type_mismatch |
| 95 | Ch5_Q1 | Y | Y | Y | Y | Y | N | - | E proof: type_mismatch |
| 96 | Ch5_Q2 | Y | Y | Y | Y | N | N | A2 | D semantic: wrong_target |
| 97 | Ch5_Q3 | Y | Y | Y | Y | N | N | A2 | D semantic: wrong_law |
| 98 | Ch6_Q1 | Y | N | N | N | N | N | EvidenceBinder | SketchAudit: raw_law_equation_in_hypotheses |
| 99 | Ch6_Q2 | N | N | N | N | N | N | A2 | A2 ModelIR: generated theorem/proof text |
| 100 | Ch6_Q23 | Y | Y | Y | N | N | N | EvidenceBinder | C compile: type_mismatch |
| 101 | Ch7_Q1 | N | N | N | N | N | N | A2 | A2 ModelIR: generated theorem/proof text |

## 读数备注

本表由以下 artifact 合并得到：

- `sample_summary.jsonl`
- `model_ir.jsonl`
- `sketch_audit.jsonl`
- `theorem_skeleton_candidates.jsonl`
- `compile_checks.jsonl`
- `semantic_rank.jsonl`
- `proof_checks.jsonl`
- `failure_routes.jsonl`

样本多轮 retry 时，本表取该样本每个阶段的最新一轮结果。
