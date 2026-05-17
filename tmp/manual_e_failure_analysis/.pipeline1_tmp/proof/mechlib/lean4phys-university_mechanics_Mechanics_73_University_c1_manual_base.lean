import Mathlib
import MechLib
import MechLib.Compat.PHYSlib
import MechLib.Dynamics.NewtonLaw
import MechLib.Dynamics.SystemDynamics
import MechLib.Kinematics.PointMotion
import MechLib.Kinematics.Verified
open MechLib
open MechLib.SI
open MechLib.Mechanics
open MechLib.Compat.PHYSlib.SI (F_of secondLaw displacement_end_x_init_x displacement_delta_t_const_v)

theorem lean4phys_university_mechanics_Mechanics_73_University_c1_explicit_gap_allowed
  (m1 m2 : Mass)
  (T Fnet1 Fnet2 T_glider T_hanging : Force)
  (g a a_glider a_hanging : Acceleration)
  (h_mi1_net_force_balance : Fnet1.val = T.val)
  (h_mi1_newton_second_law : Fnet1.val = m1.val * a.val)
  (h_mi2_net_force_balance : Fnet2.val = m2.val * g.val - T.val)
  (h_mi2_newton_second_law : Fnet2.val = m2.val * a.val)
  (h_mi3_constraint_acceleration : a_glider.val = a.val)
  (h_mi3_constraint_acceleration_2 : a_hanging.val = a.val)
  (h_mi3_uniform_tension : T_glider.val = T.val)
  (h_mi3_uniform_tension_2 : T_hanging.val = T.val)
  (h_mii1 : T.val = m1.val * a.val)
  (h_mii2 : m2.val * g.val - T.val = m2.val * a.val)
  : a.val = (m2.val * g.val) / (m1.val + m2.val) ∧
  T.val = (m1.val * m2.val * g.val) / (m1.val + m2.val) := by
  have hden_m1_val___m2_val : m1.val + m2.val ≠ 0 := by
    nlinarith [h_m1_pos, h_m2_pos]
  have ha : a.val = m2.val * g.val / (m1.val + m2.val) := by
    field_simp [hden_m1_val___m2_val] at *
    nlinarith [h_mii1, h_mii2]
  have hTfinal : T.val = m1.val * m2.val * g.val / (m1.val + m2.val) := by
    rw [h_mii1, ha]
    field_simp [hden_m1_val___m2_val]
  exact ⟨ha, hTfinal⟩
