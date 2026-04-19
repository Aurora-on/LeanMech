# B 阶段 Few-shot 样例重设

## 1. 这次修正的目标

上一次的样例有根本问题：

- 题面本身并没有要求“用牛顿第二定律推出某个新的物理结论”
- 结果只是把两个并列关系放在一起
- 它没有形成“由多个定理共同支撑一个 statement”的真实结构

这次重设只做一件事：

- 为 `B` 阶段设计一个**真正会同时用到牛顿第二定律、动量定理和冲量定义**的 few-shot 样例

并且：

- 先只写在文档里
- 不写进 prompt

## 2. 新样例的设计原则

这个 few-shot 要满足四个条件：

1. 题目本身必须真的需要多个定理共同支撑  
2. theorem 目标不能只是并列摆出两个现成公式  
3. `supporting_facts` / `fact_sources` / `library_symbols_used` 要能一一对应  
4. 样例中使用的库符号必须是当前检索里确实能稳定出现的名字  

基于当前仓库里检索最稳定的 theorem，建议优先使用：

- `newton_second_law`
- `impulse_momentum_theorem`
- `impulse_def`

它们比“只用 `momentum_change_const_mass`”更能体现：

- 题干条件
- 定理链条
- 结论推导

## 3. 推荐新题目

### 题目文本

一质量为 `m` 的质点在一维直线运动中受到恒定加速度 `a`，持续时间为 `dt`。设初末动量分别为 `p1` 与 `p2`。请形式化如下结论：

- 由牛顿第二定律可知合力为 `F_of m a`
- 由动量定理可知末动量等于初动量加上该合力在时间 `dt` 内产生的冲量
- 再结合冲量定义，可将末动量写成“初动量加上 `m * a * dt` 对应的冲量形式”

### 为什么这题是合格的 few-shot 题目

因为这题不是在并列罗列关系，而是在要求形成一个链条：

1. `newton_second_law`
2. `impulse_momentum_theorem`
3. `impulse_def`

也就是说，statement 的最终结论不是单独来自某一个 theorem，而是来自多个 theorem 的组合。

这才是你想要强化的“有理有据”。

## 4. 推荐 few-shot 输入

```text
ProblemIR:
{
  "problem_summary": "A particle of mass m moves in one dimension with constant acceleration a for a time interval dt. Let p1 and p2 be the initial and final momenta. Formalize that the final momentum equals the initial momentum plus the impulse produced by the constant net force, and rewrite that impulse using Newton's second law and the impulse definition.",
  "unknown_target": "final momentum after a constant-force interval",
  "known_quantities": ["m", "a", "dt", "p1", "p2"],
  "constraints": ["one-dimensional motion", "constant acceleration over dt"],
  "physical_laws": ["Newton's second law", "impulse-momentum theorem", "impulse definition"],
  "domain_tags": ["Dynamics", "NewtonSecondLaw", "MomentumImpulse"]
}

Retrieved library context:
- theorem_name=newton_second_law
  signature: theorem newton_second_law (m : Mass) (a : Acceleration) : F_of m a = m * a
  applicability_hint: module=Dynamics

- theorem_name=impulse_momentum_theorem
  signature: theorem impulse_momentum_theorem (p2 p1 : Momentum) (F : Force) (dt : Time) (h : p2 - p1 = impulse F dt) : p2 = p1 + impulse F dt
  applicability_hint: module=MomentumImpulse

- theorem_name=impulse_def
  signature: theorem impulse_def (F : Force) (dt : Time) : impulse F dt = Quantity.cast (F * dt) SI.force_time_eq_momentum
  applicability_hint: module=MomentumImpulse
```

## 5. 推荐 few-shot 输出

```json
{
  "candidates": [
    {
      "candidate_id": "c1",
      "lean_header": "import MechLib\nopen MechLib\nopen MechLib.SI\nopen MechLib.Mechanics",
      "theorem_decl": "theorem particle_final_momentum_from_constant_acceleration (m : Mass) (a : Acceleration) (dt : Time) (p1 p2 : Momentum) (himp : p2 - p1 = impulse (F_of m a) dt) : p2 = p1 + Quantity.cast ((m * a) * dt) SI.force_time_eq_momentum",
      "assumptions": [
        "himp : p2 - p1 = impulse (F_of m a) dt"
      ],
      "plan": "Use Newton's second law to identify the net force as F_of m a = m * a, use the impulse-momentum theorem to rewrite p2 as p1 plus the impulse, and then use the impulse definition to rewrite that impulse as Quantity.cast ((m * a) * dt) SI.force_time_eq_momentum.",
      "supporting_facts": [
        "newton_second_law (m : Mass) (a : Acceleration) : F_of m a = m * a",
        "impulse_momentum_theorem (p2 p1 : Momentum) (F : Force) (dt : Time) (h : p2 - p1 = impulse F dt) : p2 = p1 + impulse F dt",
        "impulse_def (F : Force) (dt : Time) : impulse F dt = Quantity.cast (F * dt) SI.force_time_eq_momentum"
      ],
      "fact_sources": [
        "mechlib:newton_second_law",
        "mechlib:impulse_momentum_theorem",
        "mechlib:impulse_def"
      ],
      "library_symbols_used": [
        "newton_second_law",
        "impulse_momentum_theorem",
        "impulse_def",
        "F_of",
        "impulse"
      ],
      "grounding_explanation": "The conclusion is not an invented formula. It is obtained by chaining three grounded facts: Newton's second law identifies the constant force, the impulse-momentum theorem rewrites final momentum as initial momentum plus impulse, and the impulse definition rewrites that impulse into the explicit force-time quantity."
    }
  ]
}
```

## 6. 为什么这个样例比上一次强

### 6.1 它真的用了牛顿第二定律

上一次的问题在于：

- theorem 里虽然写了 `F_of m a = m * a`
- 但题目本身并不需要“通过牛顿第二定律来得到后续目标”

这次不同：

- 如果没有 `newton_second_law`
- 就无法把 `F_of m a` 进一步改写成 `m * a`

所以牛顿第二定律不是装饰项，而是推导链的必要一环。

### 6.2 它真的用了动量定理

这次的目标是 `p2 = p1 + ...`

这一步正是：

- `impulse_momentum_theorem`

在起作用，而不是把 theorem 写成一个独立的代数关系。

### 6.3 它还展示了“定义级定理也可以是依据”

`impulse_def` 的作用是：

- 把抽象的 `impulse F dt`
- 进一步改写成可见的 force-time quantity

这能教模型：

- statement 的依据不只可以来自“物理定律”
- 也可以来自“定义展开”

这对当前项目很重要，因为很多题在真实生成里都需要：

- 定律 + 定义

而不是只有一个 theorem。

## 7. 这个样例在 B 阶段到底想教什么

这个 few-shot 的真正教学目标是：

1. 一个 statement 可以是“由多个 theorem 链接起来的最终结论”
2. `supporting_facts` 不是注释，而是推导来源列表
3. `fact_sources` 要精确对应到具体 theorem
4. `grounding_explanation` 要解释“为什么这些 theorem 能推出目标”

也就是说，它教的不是“多写 theorem 名”，而是：

- 如何把来源结构写出来

## 8. 当前阶段的接入建议

我建议下一步如果真的要试 few-shot，只做下面这件事：

- 把这一组样例接进 `B_generate_statements`
- `B_revise_statements` 可以先不加

原因：

- 先观察初始候选是否开始更稳定地输出多来源 grounded statement
- 如果初始生成已经明显改善，再决定是否把同样的风格同步到 revise prompt

否则一开始同时改两处，后面不好判断改善来自哪里。

## 9. 一句话结论

当前更合适的 B few-shot，不应该是“并列展示两个现成公式”，而应该是：

- 一个真正通过牛顿第二定律、动量定理、冲量定义三步链条支撑最终结论的样例

这样模型才会学到“多定理共同支撑一个 statement”这件事。
