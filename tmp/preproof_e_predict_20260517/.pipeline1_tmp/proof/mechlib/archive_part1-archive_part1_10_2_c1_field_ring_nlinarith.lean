import Mathlib
import MechLib
import MechLib.Analytical.LagrangeEquation
import MechLib.Compat.PHYSlib
import MechLib.Dynamics.NewtonLaw
import MechLib.Dynamics.SystemDynamics
import MechLib.Dynamics.Verified
open MechLib
open MechLib.SI
open MechLib.Mechanics
open MechLib.Compat.PHYSlib.SI (F_of secondLaw displacement_end_x_init_x displacement_delta_t_const_v)

theorem archive_part1_archive_part1_10_2_c1_explicit_gap_allowed
  (m : Mass)
  (F_r Fnet : Force)
  (g a_after : Acceleration)
  (drop_before_open : Length)
  (t_after_open : Time)
  (v_after_5s v0 v_open : Speed)
  (given_mass : m.val = 60)
  (given_drop_before_open : drop_before_open.val = 100)
  (given_time_after_open : t_after_open.val = 5)
  (given_speed_after_5s : v_after_5s.val = ((43 : Real) / 10))
  (given_initial_speed : v0.val = 0)
  (given_gravity_value : g.val = ((49 : Real) / 5))
  (h_mi1_const_accel_relation : v_open.val * v_open.val = v0.val * v0.val + 2 * g.val * drop_before_open.val)
  (h_mi2_net_force : Fnet.val = m.val * g.val - F_r.val)
  (h_mi2_newton_2 : Fnet.val = m.val * a_after.val)
  (h_mi3_velocity_time_relation : v_after_5s.val = v_open.val + a_after.val * t_after_open.val)
  (h_mii1 : v_open.val * v_open.val = v0.val * v0.val + 2 * g.val * drop_before_open.val)
  (h_mii2 : v_after_5s.val = v_open.val + a_after.val * t_after_open.val)
  (h_mii3 : m.val * a_after.val = m.val * g.val - F_r.val)
  : F_r.val = 846 := by
  repeat
    first
    | constructor
    | intro h_auto
  all_goals
    try field_simp at *
    ring_nf at *
    nlinarith
