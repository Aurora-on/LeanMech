from mech_pipeline.modules.solution_renderer import pretty_print_formula


def test_pretty_print_hanging_mass_acceleration():
    text = pretty_print_formula("a.val = (m2.val * g.val) / (m1.val + m2.val)")
    assert ".val" not in text
    assert "a = " in text
    assert "m₂" in text
    assert "m₁" in text
    assert "g" in text
    assert "\\frac{m₂g}{m₁ + m₂}" in text


def test_pretty_print_hanging_mass_tension():
    text = pretty_print_formula("T.val = (m1.val * m2.val * g.val) / (m1.val + m2.val)")
    assert "T = " in text
    assert "m₁" in text
    assert "m₂" in text
    assert "\\frac{m₁m₂g}{m₁ + m₂}" in text


def test_pretty_print_friction_coefficient():
    text = pretty_print_formula("mu_s.val = F_start.val / W.val")
    assert "μ_s" in text
    assert "F_start" in text
    assert "W" in text


def test_pretty_print_standalone_mass_symbols():
    text = pretty_print_formula("m2 * g - T = m2 * a")
    assert text == "m₂g - T = m₂a"
