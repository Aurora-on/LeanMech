import Mathlib
import MechLib
import MechLib.Kinematics.FixedAxisRotation
import MechLib.Kinematics.PointMotion
open MechLib
open MechLib.SI
open MechLib.Mechanics
open MechLib.Compat.PHYSlib.SI (F_of secondLaw displacement_end_x_init_x displacement_delta_t_const_v)

theorem archive_part1_archive_part1_10_4_c1_explicit_gap_allowed
  (m_A m_B : Mass)
  (a b Delta_x xA_i xA_f xB_i xB_f dxB_rel : Length)
  (v_0 : Speed)
  (theta : PhysAngle)
  (given_mass_relation : m_A.val = 3 * m_B.val)
  (given_initial_rest : v_0.val = 0)
  (def_Delta_x : Delta_x.val = xA_i.val - xA_f.val)
  (def_relative_shift : dxB_rel.val = xB_f.val - xB_i.val - (xA_f.val - xA_i.val))
  (def_figure_geometry_shift : dxB_rel.val = b.val)
  (h_global_rel_shift_expand : dxB_rel.val = xB_f.val - xB_i.val - (xA_f.val - xA_i.val))
  (h_mi1_com_balance : m_A.val * xA_i.val + m_B.val * xB_i.val = m_A.val * xA_f.val + m_B.val * xB_f.val)
  (h_mi2_geom_shift : dxB_rel.val = b.val)
  (h_mi3_sign_conv : Delta_x.val = xA_i.val - xA_f.val)
  (h_mii1 : dxB_rel.val = xB_f.val - xB_i.val - (xA_f.val - xA_i.val))
  (h_mii2 : dxB_rel.val = b.val)
  (h_mii3 : Delta_x.val = xA_i.val - xA_f.val) (h_m_A_pos : 0 < m_A.val) (h_m_B_pos : 0 < m_B.val) : Delta_x.val = b.val / 4 ∧
  Delta_x.val = (m_B.val / (m_A.val + m_B.val)) * b.val := by
  have hden_m_A_val___m_B_val : m_A.val + m_B.val ≠ 0 := by
    nlinarith [h_m_A_pos, h_m_B_pos]
  have hdiff : xB_f.val - xB_i.val = b.val - Delta_x.val := by
    nlinarith [h_mii1, h_mii2, h_mii3]
  have hlin : (m_A.val + m_B.val) * Delta_x.val = m_B.val * b.val := by
    nlinarith [h_mi1_com_balance, hdiff, h_mii3]
  have hDelta_ratio : Delta_x.val = (m_B.val / (m_A.val + m_B.val)) * b.val := by
    field_simp [hden_m_A_val___m_B_val]
    nlinarith [hlin]
  have hm_sum : m_A.val + m_B.val = 4 * m_B.val := by
    nlinarith [given_mass_relation]
  have hden4 : (4 : Real) ≠ 0 := by norm_num
  have hDelta_quarter : Delta_x.val = b.val / 4 := by
    rw [hDelta_ratio, hm_sum]
    field_simp [hden4]
    ring
  exact ⟨hDelta_quarter, hDelta_ratio⟩
