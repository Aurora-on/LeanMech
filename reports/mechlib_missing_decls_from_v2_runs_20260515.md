# MechLib missing / insufficient declaration report from recent minimal-skeleton runs

本报告整理最近三次同一测试集链路中暴露的 MechLib declaration 缺口，供 MechLib 侧补库使用。

## 数据来源

三次运行均为 minimal skeleton 前半段 + 旧 proof 阶段，样本集为 27 题混合测试集：

| 标记 | run |
|---|---|
| run1 | `runs/20260515_125015_minimal-v2-mixed-legacy-proof-gpt54-20260515_125014` |
| run2 | `runs/20260515_143038_minimal-v2-mixed-legacy-proof-post-contract-20260515_143038` |
| run3 | `runs/20260515_154850_minimal-v2-mixed-legacy-proof-post-formula-20260515_154840` |

主要依据：

- `controlled_sketch.jsonl` 中的 `blocked_law_steps`
- `controlled_sketch.jsonl` 中 `proof_fact_allowed=false` 且没有 `verified_constructor` 的 `model_interface_instantiations`
- `evidence_bindings.jsonl` 中反复命中的过泛 declaration

判定原则：

- `law_schema`、`problem_schema`、concept metadata 不计为 proof fact。
- 只把能够作为可调用模型定理、接口谓词或抽取定理的 verified declaration 视为可用。
- 若 EvidenceBinder 命中 verified decl，但 ControlledSketch 仍报告“不能提供单一 Lean-like expected claim”或“不是当前模型关系的合适构造器”，这里归类为“MechLib API/定理签名不足”，而不简单说 corpus 完全缺失。
- 纯题面给定、局部定义、数值代入不列为 MechLib 必补定理，除非它们实际代表通用物理建模接口。

## 总体结论

三次运行中，`evidence_bindings.jsonl` 大多能命中某些 verified declaration，但大量命中是如下过泛或不适配的 declaration：

- `MechLib.Compat.PHYSlib.SI.newton_second_law`
- `MechLib.Dynamics.NewtonLaw.newton_second_law_verified`
- `MechLib.Dynamics.NewtonLaw.newtonSecondLaw_course_form`
- `MechLib.Dynamics.Verified.Dynamics.newton_second_law`
- `MechLib.Examples.FinalTheoremDemos.newtonSecondLaw_byDefinition`
- `MechLib.Examples.FinalTheoremDemos.uniformAccelerationDisplacement_byCalculation`
- `MechLib.Analytical.LagrangeEquation.eulerLagrange_iff_newton_course_form`
- `MechLib.Examples.FinalTheoremDemos.eulerLagrangeNewtonBridge_byResidualAlgebra`

这些 declaration 虽然 verified，但对 pipeline 来说通常不是“可实例化的物理模型接口”。主要缺口不是单个 theorem 名称，而是缺少一批可被 LLM / EvidenceBinder 稳定调用的 MechLib API：

1. 点运动函数型运动学：位置、速度、加速度的逐点导数关系。
2. 分量形式牛顿第二定律和静力/匀速力平衡。
3. 摩擦、绳张力、滑轮、capstan 等约束模型。
4. 转动动力学、转动惯量、力矩、角运动学。
5. 功-能关系、刚体/质点动能、变力矩做功积分。
6. 质心/相对位移/矢量分解/几何约束。
7. 优化或极值型运动学关系，例如最近距离、最小距离。

## P0 建议优先补充的 declaration families

### 1. Pointwise kinematics for function-valued quantities

需求形态：

- `position : Time -> Length`
- `velocity : Time -> Speed`
- `acceleration : Time -> Acceleration`
- 逐点关系：`forall t : Time, (v t).val = deriv ... t.val`
- 逐点关系：`forall t : Time, (a t).val = deriv ... t.val`

受影响样本：

- `Mechanics_3`
- `Mechanics_16`
- `archive_part1_9_11`
- `archive_part1_11_1`
- `archive_part1_11_4`
- `archive_part1_11_9`
- `archive_part1_6_6`
- `Ch1_Q11`

当前现象：

- `Mechanics_3` 命中 `MechLib.Kinematics.PointMotion.displacement_forms_equiv_course_form`，但无法提供“速度是给定位置函数导数”的单一可用 Lean claim。
- `Mechanics_16` 命中 `MechLib.Kinematics.PointMotion.velocityDerivativeRelation_apply`，但仍不能直接表达分量速度函数到分量加速度函数的逐点关系。
- 多个 archive 题需要 `forall t` 的点值关系，而当前 declaration 很容易被错误抽象成非逐点等式或自然语言描述。

建议 MechLib 提供：

- `PointMotion.velocity_eq_deriv_position`
- `PointMotion.acceleration_eq_deriv_velocity`
- `PointMotion.component_velocity_eq_deriv_coordinate`
- `PointMotion.component_acceleration_eq_deriv_velocity`
- 对 SI wrapper 的 `.val` 层公式示例和 callable theorem metadata。

### 2. Component Newton law and force balance

需求形态：

- `Fnet_x.val = m.val * ax.val`
- `Fnet_y.val = m.val * ay.val`
- 静止/匀速：`ax = 0` 时 `sum_force_x = 0`
- 二维分量平衡和分量投影。

受影响样本：

- `Mechanics_31`
- `Mechanics_71`
- `Mechanics_73`
- `Mechanics_74`
- `Mechanics_76`
- `Ch2_Q2`
- `archive_part1_9_1`
- `archive_part1_10_2`
- `archive_part1_13_3`

当前现象：

- 频繁命中 generic Newton declarations，但不能稳定生成“某个物体某个方向的净力等于质量乘以加速度”的具体接口。
- `MechLib.Examples.FinalTheoremDemos.newtonSecondLaw_byDefinition` 作为 demo theorem 被反复匹配，但不适合作为通用建模 API。

建议 MechLib 提供：

- `Dynamics.force_balance_1d`
- `Dynamics.force_balance_component_x`
- `Dynamics.force_balance_component_y`
- `Dynamics.static_equilibrium_component`
- `Dynamics.constant_velocity_force_balance`
- `Dynamics.net_force_eq_sum_components`

### 3. Friction, rope, pulley, and capstan constraints

需求形态：

- `f_k.val = mu_k * N.val`
- `f_s.val <= mu_s * N.val`
- limiting static friction: `f_s.val = mu_s * N.val`
- ideal rope uniform tension
- shared acceleration magnitude in ideal string / pulley systems
- capstan relation: `T_heavy / T_light = Real.exp (mu * theta)` or inequality variant.

受影响样本：

- `Mechanics_73`
- `Mechanics_74`
- `Mechanics_76`
- `Ch2_Q1`
- `Ch2_Q2`
- `archive_part1_9_1`
- `archive_part1_13_3`

当前现象：

- `Mechanics_73` 需要 Atwood / pulley 建模：两物体共用加速度、同一绳张力、两侧受力方程。
- `Ch2_Q1` 需要 capstan / belt friction 的张力比关系。
- `Mechanics_74` 和 `Mechanics_76` 需要静摩擦阈值、动摩擦和匀速力平衡组合。

建议 MechLib 提供：

- `Contact.kinetic_friction_eq`
- `Contact.static_friction_bound`
- `Contact.static_friction_limiting_eq`
- `Rope.ideal_rope_uniform_tension`
- `Pulley.ideal_string_shared_acceleration`
- `Belt.capstan_tension_ratio`
- `Belt.capstan_tension_bound`

### 4. Rotational dynamics, inertia, and torque

需求形态：

- `tau_net.val = I.val * alpha.val`
- `I.val = m.val * r.val^2`
- `I_cm.val = (1/12) * m.val * L.val^2`
- `tau.val = r.val * F.val`
- signed torque sums.

受影响样本：

- `archive_part1_11_4`
- `archive_part1_11_9`
- `archive_part1_11_23`
- `archive_part1_12_1`
- `archive_part1_12_7`
- `archive_part1_6_6`

当前现象：

- 转动题经常被绑定到 translational Newton / Lagrange demo theorem。
- 缺少可直接描述 fixed-axis dynamics、resistive torque、rod inertia、point-mass inertia 和 signed torque sum 的 declaration。

建议 MechLib 提供：

- `Rotational.fixed_axis_torque_eq_inertia_mul_alpha`
- `Rotational.point_mass_moment_of_inertia`
- `Rotational.slender_rod_inertia_center`
- `Rotational.signed_torque_of_force`
- `Rotational.net_torque_sum`
- `Rotational.angular_displacement_const_alpha_from_rest`

### 5. Work-energy and rigid-body kinetic energy

需求形态：

- `T_f.val - T_i.val = W.val`
- `K.val = 1/2 * m.val * v.val^2`
- `K_rot.val = 1/2 * I.val * omega.val^2`
- rigid body total kinetic energy: translational plus rotational.
- variable torque work: `∫ phi in [phi_i, phi_f], M phi`

受影响样本：

- `archive_part1_12_1`
- `archive_part1_12_7`
- `archive_part1_10_2`

当前现象：

- `archive_part1_12_7` 需要整个机构的功-能方程、曲柄/连杆/滑块动能分解和质量-重量换算。
- `archive_part1_12_1` 需要变力矩做功积分、重力做功和绳轮位移关系。

建议 MechLib 提供：

- `Energy.work_energy_point_mass`
- `Energy.rigid_body_kinetic_energy`
- `Energy.rotational_kinetic_energy`
- `Energy.translational_kinetic_energy`
- `Energy.work_of_constant_torque`
- `Energy.work_of_variable_torque_integral`
- `Energy.gravity_work_vertical_displacement`

### 6. Center of mass, relative displacement, and vector decomposition

需求形态：

- 质心守恒：`m1 * dx1 + m2 * dx2 = 0`
- 相对位移：`dx_B - dx_A = given_relative_displacement`
- 矢量分解：`Fx = F * Real.cos theta`，`Fy = F * Real.sin theta`
- 合力大小/方向：`F^2 = Fx^2 + Fy^2`，`tan gamma = Fy/Fx`

受影响样本：

- `archive_part1_10_4`
- `archive_part1_10_8`
- `archive_part1_2_3`
- `archive_part1_5_10`
- `Ch1_Q11`

当前现象：

- `archive_part1_10_4` / `archive_part1_10_8` 需要可调用的二体质心位移守恒关系。
- `archive_part1_2_3` 和 `archive_part1_5_10` 需要向量分解、大小和法/切向分解关系。

建议 MechLib 提供：

- `System.center_of_mass_displacement_two_body`
- `Kinematics.relative_displacement_relation`
- `Vector2.force_components_from_angle`
- `Vector2.vector_magnitude_sq`
- `Vector2.tangential_normal_components`

## Per-sample handoff table

| sample | repeated missing / insufficient MechLib relation |
|---|---|
| `Mechanics_3` | 位置函数到速度函数的逐点导数关系；当前 closest decl `PointMotion.displacement_forms_equiv_course_form` 不足以构造 expected claim。 |
| `Mechanics_16` | 分量速度函数到分量加速度函数的逐点导数关系；需要 `vx/vy -> ax/ay` 的 component API。 |
| `Mechanics_31` | 自由落体竖直分量动力学和恒加速度运动学组合：`a_y = -g`、顶点速度为零、速度-位移关系。 |
| `Mechanics_71` | 斜面重力分量、法向平衡和平行方向动力学。 |
| `Mechanics_73` | Atwood / 滑轮系统：理想绳张力一致、共用加速度、两物体一维 Newton 方程。 |
| `Mechanics_74` | 静摩擦最大值、动摩擦、匀速/启动阈值力平衡。 |
| `Mechanics_76` | 拉力分量、动摩擦、匀速水平/竖直平衡。 |
| `Ch1_Q11` | 两质点相对运动、距离函数、最小距离/最近点条件。 |
| `Ch2_Q1` | capstan / belt friction 张力比或不等式，结合桶重静平衡。 |
| `Ch2_Q2` | 旋转参考系/圆周运动约束、杆方向分量、摩擦方向分支平衡。 |
| `Ch3_Q1` | 弹簧平衡位移、平衡突变后的简谐运动模型、初始位移/速度接口。 |
| `archive_part1_2_3` | 三力平衡的向量分解、合力分量、未知力大小和方向关系。 |
| `archive_part1_5_10` | 法向/切向加速度分解、曲率关系 `a_n = v^2/rho`、速度向量大小。 |
| `archive_part1_6_6` | 无滑动绳轮运动学、角速度/角加速度到线速度/线加速度、旋转刚体点的切向/法向加速度。 |
| `archive_part1_7_1` | 运动轨迹参数化、时间消元、相对轨迹方程。 |
| `archive_part1_9_1` | 倾斜弯道最大速度：径向/竖直力分量、静摩擦极限、向心加速度。 |
| `archive_part1_9_11` | 时变力下的逐点 Newton 方程、速度/位置由加速度积分或导数关系。 |
| `archive_part1_10_2` | 降落伞开启前后恒加速度运动学、阻力-净力-加速度关系。 |
| `archive_part1_10_4` | 两体质心位置/位移守恒、相对位移约束。 |
| `archive_part1_10_8` | 船-人系统质心守恒、相对位移与船位移关系。 |
| `archive_part1_11_1` | 平面角动量标量公式 `L_z = m (x vy - y vx)`，以及坐标函数导数。 |
| `archive_part1_11_4` | 点质量转动惯量、阻力与角速度成正比、阻力矩、定轴转动方程。 |
| `archive_part1_11_9` | 阻力矩 `tau = -k omega`、`tau = J alpha`、角速度/角位移逐点关系。 |
| `archive_part1_11_23` | 杆质心转动惯量、两个推力的 signed torque sum、恒角加速度角位移。 |
| `archive_part1_12_1` | 绳轮位移-转角关系、重力做功、变力矩积分做功、总功-能关系。 |
| `archive_part1_12_7` | 曲柄-连杆-滑块系统的刚体动能分解、转动动能、功-能关系、质量-重量换算。 |
| `archive_part1_13_3` | 小车-物块-悬挂质量系统：接触/摩擦/张力耦合 Newton 方程、翻倒临界几何关系。 |

## 需要 MechLib 侧特别避免的导出形态

这些形态会导致 pipeline 误绑定或后续无法实例化：

1. 只给 course-form / demo theorem，没有可调用模型谓词或 extractor theorem。
2. declaration summary 说“Newton second law”，但 statement 不能实例化到 component equation。
3. theorem conclusion head 被导出成看似 predicate 的 namespace-qualified 名称，但实际上不是可调用 API。
4. 缺少 SI wrapper 示例，导致 LLM 生成裸 `Real` 或错误 `.val` 结构。
5. 函数型物理量没有 pointwise theorem 示例，导致输出 `v = ...` 而不是 `forall t, (v t).val = ...`。

## 建议的 MechLib 修复优先级

1. **P0**：补 function-valued pointwise kinematics + component Newton / force-balance API。它们覆盖最多样本，并且能显著减少 `blocked_by_evidence_gap`。
2. **P0**：补 friction / rope / pulley / capstan constraints。它们影响 `Mechanics_73`、`Mechanics_74`、`Mechanics_76`、`Ch2_Q1`、`archive_part1_9_1` 等典型力学题。
3. **P1**：补 rotational dynamics + work-energy + kinetic energy API。它们主要影响 archive part1 的 11、12 章题目。
4. **P1**：补 COM / vector decomposition / trajectory geometry API。它们能改善 archive part1 的几何和质心题，但优先级低于 Newton/friction/kinematics。

## Pipeline 侧建议

本报告不建议 pipeline 伪造这些 declaration。若 MechLib 暂无对应 verified declaration，pipeline 应继续把对应关系归档为 `gap_schema_only` / `explicit_model_gap` / `blocked_by_evidence_gap`，而不是生成假的 `MechLib.Dynamics.Newton1D` 或类似 namespace-qualified predicate。

