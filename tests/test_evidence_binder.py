from __future__ import annotations

import json
from pathlib import Path

from mech_pipeline.knowledge.evidence_binder import EvidenceBinder, LeanDeclCheckCache, evidence_binding_stage_rows
from mech_pipeline.knowledge.mechlib_structured import StructuredMechLibContext
from mech_pipeline.types import ModelIR, ModelInstance


class FakeCheckRunner:
    def __init__(self, ok: bool) -> None:
        self.ok = ok
        self.checked: list[str] = []
        self.imports_seen: list[list[str]] = []

    def check_decl(self, fq_name: str, required_imports: list[str]) -> bool:
        self.checked.append(fq_name)
        self.imports_seen.append(list(required_imports))
        return self.ok


class FakePrivateLeanRunner:
    enabled = True
    _mechlib_ready = True

    def __init__(self) -> None:
        self.paths: list[str] = []
        self.timeouts_seen: list[int | None] = []

    def _backend_root(self, backend: str) -> Path:
        _ = backend
        return Path.cwd()

    def _run_lean(self, *, root_dir: Path, rel_file: Path, timeout_s: int | None = None):
        _ = root_dir
        self.paths.append(str(rel_file))
        self.timeouts_seen.append(timeout_s)
        return True, "", ""


def _context_with_decl(*, proof_fact_allowed: bool = True, callable_by_llm: bool = True) -> StructuredMechLibContext:
    return StructuredMechLibContext(
        modeling_context={
            "matched_topics": ["Kinematics"],
            "concepts": [],
            "law_schemas": [
                {
                    "schema_id": "law.kinematics.constant_speed",
                    "corpus_type": "law_schema",
                    "verified_decls": ["MechLib.Kinematics.constant_speed_relation"],
                    "proof_fact_allowed": False,
                }
            ],
            "problem_schemas": [],
            "aliases": [
                {
                    "alias_name": "const_speed_alias",
                    "alias_fq_name": "MechLib.Compat.const_speed_alias",
                    "alias_to_fq_name": "MechLib.Kinematics.constant_speed_relation",
                    "proof_fact_allowed": False,
                }
            ],
        },
        proof_context={
            "verified_decls": [
                {
                    "fq_name": "MechLib.Kinematics.constant_speed_relation",
                    "theorem_name": "constant_speed_relation",
                    "statement": "theorem constant_speed_relation (s v t : Real) : s = v * t",
                    "status": "verified",
                    "trust_level": "core",
                    "callable_by_llm": callable_by_llm,
                    "required_imports": ["import MechLib"],
                    "law_schema_ids": ["law.kinematics.constant_speed"],
                    "problem_schema_ids": ["problem.uniform_motion"],
                    "tags": ["Kinematics"],
                    "proof_fact_allowed": proof_fact_allowed,
                }
            ],
            "required_imports": ["import MechLib"],
            "proof_hints": [],
            "proof_style_examples": [],
        },
    )


def _constant_speed_instance() -> ModelInstance:
    return ModelInstance(
        instance_id="mi1",
        kind="constant_speed_kinematics",
        natural_language="Use the constant speed kinematics relation.",
        planning_schema_id="law.kinematics.constant_speed",
        expected_claim="s = v * t",
        variables={"s": "displacement", "v": "speed", "t": "time"},
    )


def test_evidence_binder_binds_verified_callable_decl() -> None:
    model_ir = ModelIR(sample_id="s1", model_instances=[_constant_speed_instance()], parse_ok=True)
    bindings = EvidenceBinder(top_k=1, lean_check_decls=False).bind(
        model_ir,
        _context_with_decl(),
        problem_text="constant speed displacement",
        problem_ir={"physical_laws": ["Kinematics"]},
    )

    assert len(bindings) == 1
    assert bindings[0].binding_status == "ok"
    assert bindings[0].proof_fact_allowed is True
    assert bindings[0].verified_decl == "MechLib.Kinematics.constant_speed_relation"
    json.dumps(evidence_binding_stage_rows("s1", bindings))


def test_evidence_binder_never_promotes_schema_name_to_verified_decl() -> None:
    context = StructuredMechLibContext(
        modeling_context={
            "matched_topics": ["Kinematics"],
            "concepts": [],
            "law_schemas": [
                {
                    "schema_id": "law.kinematics.constant_speed",
                    "corpus_type": "law_schema",
                    "proof_fact_allowed": False,
                }
            ],
            "problem_schemas": [],
            "aliases": [],
        },
        proof_context={"verified_decls": [], "required_imports": [], "proof_hints": [], "proof_style_examples": []},
    )

    bindings = EvidenceBinder(top_k=1, lean_check_decls=False).bind([_constant_speed_instance()], context)

    assert bindings[0].binding_status == "gap_schema_only"
    assert bindings[0].proof_fact_allowed is False
    assert bindings[0].verified_decl is None


def test_evidence_binder_rejects_failed_lean_check() -> None:
    runner = FakeCheckRunner(ok=False)
    bindings = EvidenceBinder(top_k=1, lean_runner=runner, lean_check_decls=True).bind(
        [_constant_speed_instance()],
        _context_with_decl(),
        problem_text="constant speed displacement",
    )

    assert runner.checked == ["MechLib.Kinematics.constant_speed_relation"]
    assert bindings[0].binding_status == "lean_check_failed"
    assert bindings[0].lean_check_pass is False
    assert bindings[0].proof_fact_allowed is False
    assert bindings[0].verified_decl == "MechLib.Kinematics.constant_speed_relation"


def test_evidence_binder_shared_cache_checks_same_fq_name_once() -> None:
    runner = FakeCheckRunner(ok=True)
    cache = LeanDeclCheckCache()
    binder_1 = EvidenceBinder(top_k=1, lean_runner=runner, lean_check_decls=True, lean_check_cache=cache)
    binder_2 = EvidenceBinder(top_k=1, lean_runner=runner, lean_check_decls=True, lean_check_cache=cache)

    first = binder_1.bind([_constant_speed_instance()], _context_with_decl(), problem_text="constant speed")
    second = binder_2.bind([_constant_speed_instance()], _context_with_decl(), problem_text="constant speed")

    assert first[0].binding_status == "ok"
    assert second[0].binding_status == "ok"
    assert runner.checked == ["MechLib.Kinematics.constant_speed_relation"]
    stats = cache.stats()
    assert stats["checked_decl_count"] == 1
    assert stats["decl_check_cache_misses"] == 1
    assert stats["decl_check_cache_hits"] >= 1


def test_evidence_binder_normalizes_module_imports_before_lean_check() -> None:
    runner = FakeCheckRunner(ok=True)
    context = _context_with_decl()
    context.proof_context["verified_decls"][0]["required_imports"] = ["MechLib.Kinematics.Verified"]

    bindings = EvidenceBinder(top_k=1, lean_runner=runner, lean_check_decls=True).bind(
        [_constant_speed_instance()],
        context,
        problem_text="constant speed displacement",
    )

    assert bindings[0].binding_status == "ok"
    assert runner.imports_seen == [["import MechLib.Kinematics.Verified"]]


def test_evidence_binder_skips_lean_check_when_mechlib_backend_is_unavailable() -> None:
    runner = FakeCheckRunner(ok=False)
    runner._mechlib_ready = False

    bindings = EvidenceBinder(top_k=1, lean_runner=runner, lean_check_decls=True).bind(
        [_constant_speed_instance()],
        _context_with_decl(),
        problem_text="constant speed displacement",
    )

    assert runner.checked == []
    assert bindings[0].binding_status == "ok"
    assert bindings[0].lean_check_pass is None
    assert bindings[0].proof_fact_allowed is True


def test_evidence_binder_uses_absolute_evidence_check_path(tmp_path: Path) -> None:
    runner = FakePrivateLeanRunner()

    bindings = EvidenceBinder(
        top_k=1,
        lean_runner=runner,
        lean_check_decls=True,
        run_dir=tmp_path / "relative_like_run",
    ).bind(
        [_constant_speed_instance()],
        _context_with_decl(),
        problem_text="constant speed displacement",
    )

    assert bindings[0].binding_status == "ok"
    assert runner.paths
    assert Path(runner.paths[0]).is_absolute()
    assert runner.timeouts_seen == [120]


def test_evidence_binder_allows_custom_lean_check_timeout(tmp_path: Path) -> None:
    runner = FakePrivateLeanRunner()

    bindings = EvidenceBinder(
        top_k=1,
        lean_runner=runner,
        lean_check_decls=True,
        lean_check_timeout_s=240,
        run_dir=tmp_path / "run",
    ).bind(
        [_constant_speed_instance()],
        _context_with_decl(),
        problem_text="constant speed displacement",
    )

    assert bindings[0].binding_status == "ok"
    assert runner.timeouts_seen == [240]


def test_evidence_binder_rejects_not_callable_or_not_proof_allowed_decl() -> None:
    for context in (
        _context_with_decl(callable_by_llm=False),
        _context_with_decl(proof_fact_allowed=False),
    ):
        bindings = EvidenceBinder(top_k=1, lean_check_decls=False).bind([_constant_speed_instance()], context)
        assert bindings[0].binding_status == "gap_schema_only"
        assert bindings[0].verified_decl is None
        assert bindings[0].proof_fact_allowed is False


def test_evidence_binder_does_not_invent_unmatched_declaration() -> None:
    instance = ModelInstance(
        instance_id="mi_unmatched",
        kind="pendulum_energy_balance",
        natural_language="Use a pendulum energy balance.",
        planning_schema_id="law.energy.pendulum",
        expected_claim="energy is conserved",
    )
    bindings = EvidenceBinder(top_k=1, lean_check_decls=False).bind(
        [instance],
        _context_with_decl(),
        problem_text="pendulum oscillation energy",
        problem_ir={"physical_laws": ["EnergyConservation"]},
    )

    assert bindings[0].binding_status == "gap_schema_only"
    assert bindings[0].verified_decl is None
