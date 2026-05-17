from __future__ import annotations

SUPPORTED_SI_QUANTITY_TYPES = {
    "Dimensionless",
    "PhysAngle",
    "Length",
    "Mass",
    "Time",
    "Current",
    "Temperature",
    "Amount",
    "Intensity",
    "Speed",
    "Acceleration",
    "Momentum",
    "Force",
    "Energy",
    "Power",
    "Pressure",
    "Frequency",
    "SpringConstant",
    "DampingCoefficient",
    "AngularVelocity",
    "AngularAcceleration",
    "AngularVelocitySquared",
    "MomentOfInertia",
    "Torque",
    "AngularMomentum",
}

SCALAR_TIME_FUNCTION_TYPES = {
    "ScalarTrajectory": "MechLib.Mechanics.Kinematics.ScalarTrajectory",
    "ScalarVelocityField": "MechLib.Mechanics.Kinematics.ScalarVelocityField",
    "ScalarAccelerationField": "MechLib.Mechanics.Kinematics.ScalarAccelerationField",
}

SCALAR_TIME_FUNCTION_PARTS = {
    "MechLib.Mechanics.Kinematics.ScalarTrajectory": ("Real", "Length"),
    "MechLib.Mechanics.Kinematics.ScalarVelocityField": ("Real", "Speed"),
    "MechLib.Mechanics.Kinematics.ScalarAccelerationField": ("Real", "Acceleration"),
}

_TIME_FUNCTION_ALIAS_BY_CODOMAIN = {
    "Length": "MechLib.Mechanics.Kinematics.ScalarTrajectory",
    "Speed": "MechLib.Mechanics.Kinematics.ScalarVelocityField",
    "Acceleration": "MechLib.Mechanics.Kinematics.ScalarAccelerationField",
}

SUPPORTED_LEAN_QUANTITY_TYPES = SUPPORTED_SI_QUANTITY_TYPES | {"Real"} | set(SCALAR_TIME_FUNCTION_PARTS)

SI_TYPE_ALIASES = {
    "SI.Dimensionless": "Dimensionless",
    "MechLib.SI.Dimensionless": "Dimensionless",
    "Angle": "PhysAngle",
    "SI.Angle": "PhysAngle",
    "MechLib.SI.Angle": "PhysAngle",
    "SI.PhysAngle": "PhysAngle",
    "MechLib.SI.PhysAngle": "PhysAngle",
    "Position": "Length",
    "SI.Position": "Length",
    "MechLib.SI.Position": "Length",
    "Displacement": "Length",
    "SI.Displacement": "Length",
    "MechLib.SI.Displacement": "Length",
    "Velocity": "Speed",
    "SI.Velocity": "Speed",
    "MechLib.SI.Velocity": "Speed",
    "SI.Speed": "Speed",
    "MechLib.SI.Speed": "Speed",
    "MechLib.SI.Length": "Length",
    "MechLib.SI.Mass": "Mass",
    "MechLib.SI.Time": "Time",
    "MechLib.SI.Acceleration": "Acceleration",
    "MechLib.SI.Force": "Force",
}
for _short_name, _fq_name in SCALAR_TIME_FUNCTION_TYPES.items():
    SI_TYPE_ALIASES[_short_name] = _fq_name
    SI_TYPE_ALIASES[_fq_name] = _fq_name


def _split_arrow_type(text: str) -> tuple[str, str] | None:
    normalized = " ".join(str(text or "").strip().replace("→", "->").split())
    if "->" not in normalized:
        return None
    parts = [part.strip() for part in normalized.split("->")]
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return None
    return parts[0].strip("() "), parts[1].strip("() ")


def normalize_quantity_lean_type(value: object) -> tuple[str, bool, str]:
    text = str(value or "").strip()
    if not text:
        return "Real", True, "unresolved"
    text = text.replace("ℝ", "Real")
    arrow = _split_arrow_type(text)
    if arrow is not None:
        domain, codomain = arrow
        normalized_domain, domain_supported, domain_status = normalize_quantity_lean_type(domain)
        normalized_codomain, codomain_supported, codomain_status = normalize_quantity_lean_type(codomain)
        supported = domain_supported and codomain_supported
        status = "ok" if supported else "unsupported_si_type"
        if domain_status == "unresolved" or codomain_status == "unresolved":
            status = "unresolved"
        if supported and normalized_domain in {"Time", "Real"} and normalized_codomain in _TIME_FUNCTION_ALIAS_BY_CODOMAIN:
            return _TIME_FUNCTION_ALIAS_BY_CODOMAIN[normalized_codomain], True, status
        if supported and normalized_domain == "Time":
            normalized_domain = "Real"
        return f"{normalized_domain} -> {normalized_codomain}", supported, status
    if text in SI_TYPE_ALIASES:
        return SI_TYPE_ALIASES[text], True, "ok"
    short = text.rsplit(".", 1)[-1]
    if short in SI_TYPE_ALIASES:
        return SI_TYPE_ALIASES[short], True, "ok"
    if short in SUPPORTED_LEAN_QUANTITY_TYPES:
        return short, True, "ok"
    return short or text, False, "unsupported_si_type"


def is_supported_quantity_lean_type(value: object) -> bool:
    _, supported, _ = normalize_quantity_lean_type(value)
    return supported


def is_function_quantity_lean_type(value: object) -> bool:
    normalized, supported, _ = normalize_quantity_lean_type(value)
    return supported and (normalized in SCALAR_TIME_FUNCTION_PARTS or "->" in normalized)


def function_quantity_parts(value: object) -> tuple[str, str] | None:
    normalized, supported, _ = normalize_quantity_lean_type(value)
    if not supported:
        return None
    if normalized in SCALAR_TIME_FUNCTION_PARTS:
        return SCALAR_TIME_FUNCTION_PARTS[normalized]
    return _split_arrow_type(normalized)
