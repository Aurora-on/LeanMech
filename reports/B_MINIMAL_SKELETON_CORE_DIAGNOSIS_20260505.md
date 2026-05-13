# B Minimal Skeleton 核心诊断报告（2026-05-05）

## 本轮真实 API 测试

- 配置：`tmp/minimal_random5_plus_mechanics73_20260505_213018.yaml`
- 随机 5 题：Mechanics59、Mechanics10、Mechanics73、Mechanics71、Mechanics37
- 必含样本：Mechanics73
- run 1：`runs/20260505_214707_typed-assembler-random5-mechanics73-fix1`
- run 2：`runs/20260505_220221_typed-assembler-random5-mechanics73-fix2`
- 测试：`.venv/bin/python -m pytest -q` -> `127 passed`

## 与 legacy pipeline 的关键差异

legacy B 阶段直接让 LLM 输出完整 `theorem_decl`。它虽然容易产生伪 MechLib API、自然语言 Prop、derived equation hypotheses，但有一个实际能力：LLM 会在 B 阶段同时承担目标公式生成、代数消元和 Lean statement 编排。

当前 minimal_skeleton 路径把 B 改成 deterministic assembler，LLM 只选择 givens、model instances、sketch steps。这样能阻止伪 Prop 进入 theorem，但也移除了 legacy B 原本隐式承担的“生成最终 conclusion”能力。

当前前半段没有新增等价的 Target/Conclusion 生成阶段，所以当 `ProblemIR/ModelIR/ControlledSketch` 没有显式目标公式时，B 只能 blocked，无法自然生成：

```lean
a.val = ... ∧ T.val = ...
```

这就是最近出现“结论错误或者没有输出”的主要原因。

## Mechanics73 断点

当前 `ProblemIR` 保留了建模关系：

- `T = m1 * a`
- `m2 * g - T = m2 * a`

但 `ModelIR.target` 只有描述性目标：

- acceleration: `a`
- tension: `T`
- expected form: expression in `m1, m2, g`

`ControlledSketch` 生成了两个 law obligations：

- `T = m1 * a`
- `m2 * g - T = m2 * a`

但没有生成 `algebra_obligation`，因为 prompt 将 algebra 设置为 optional，且没有要求从 law equations 解出最终目标。

B 的 target source 顺序是：

1. `controlled_sketch.algebra_obligation.formal_claim`
2. `model_ir.target.lean`
3. `model_ir.forbidden_as_assumption` 中显式带 `=` 的 target/final/answer

Mechanics73 这三处都没有最终 closed-form formula。因此旧版出现 `m1.val = m1.val`，修复后改为 blocked sentinel `: False`，并且 `parse_ok=false`，不会进入 C/D/E。

## EvidenceBinding / ModelPredicateRegistry 问题

EvidenceBinder 当前的 `binding_status=ok` 只表示 declaration 来自 verified corpus 且 `#check` 通过，不表示它能作为当前 model instance 的可装配模型谓词。

这会导致两类问题：

1. `ControlledSketch` 把可 check 的 theorem 当成 proof step 支撑，即使该 theorem 只是 course-form 或桥接 lemma。
2. B 的 ModelPredicateRegistry 需要从 theorem statement 反推 predicate，容易过宽。

本轮已修一个通用错误：对于

```lean
CenterOfMassBalance M Rddot Fext = ...
```

如果 `Rddot`、`Fext` 是高阶函数参数，不能截断成：

```lean
CenterOfMassBalance m2
```

修复后 Mechanics73 只保留可装配的：

```lean
MechLib.Dynamics.NewtonLaw.NewtonSecondLaw m1 a T
```

而 `mi2/mi3/mi4` 被标为 signature mismatch / blocked gap。

## 与期望示例的差距

期望形态中最重要的是：

```lean
(glider_law : <checked Newton predicate> T m1 a)
(hanger_law : <checked Newton predicate> (forceSub (weight m2 g) T) m2 a)
: a.val = ... ∧ T.val = ...
```

当前只做到：

- header 顺序正确：`import Mathlib` 在 `import MechLib` 前，所有 import 在 open 前。
- typed binders 正确：`m1 m2 : Mass`、`T : Force`、`g a : Acceleration`。
- 自然语言伪 Prop 已被排除：`track_is_level`、`massless_string` 等不进入 theorem。
- 不再伪造不存在的 `Newton1D/forceSub/weight`。

仍缺：

- 没有从 equations 构造 final `.val` target formula 的 Target/ConclusionPlanner。
- 没有经过 corpus/#check 验证的 force expression builder，所以不能生成 hanger law 的 net-force expression。
- EvidenceBinder 还缺少“可作为模型谓词装配”的强类型资格，而不只是 `#check theorem_name`。

## 已完成修复

- 未注册函数/常量不再进入 problem fact binder，例如 `direction(...)`、`weight(...)`、`x.val(t.val)`。
- 目标公式缺失时不再生成 tautology。
- course-form theorem 反推 predicate 时校验 LHS arity，避免高阶参数被截断。
- 新增 regression test，防止 `CenterOfMassBalance m2` 这类错误回归。

## 下一步建议

需要把当前表层 guardrail 升级为两个前置结构：

1. `ConclusionPlanner`
   - 输入 ProblemIR relations、ControlledSketch proof_steps、target variables。
   - 输出最多一个 audited algebra target formula。
   - 对 Mechanics73，应从两个 law equations 得到：
     `a.val = (m2.val * g.val) / (m1.val + m2.val) ∧ T.val = ...`
   - 如果无法从 equations 解出 target，明确 blocked，不生成 theorem。

2. `ModelPredicateRegistry` / `ModelExpressionRegistry`
   - 不只检查 theorem 名称，还要检查 predicate/interface declaration 和参数签名。
   - 只有验证过 force expression builder 时，才能生成 `forceSub/weight` 组合。
   - 没有 verified expression builder 时，hanger law 必须 blocked，而不是用自然语言 Prop 或伪 API 替代。

这些改动是通用结构改造，不是针对 Mechanics73 的兜底。
