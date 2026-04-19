from __future__ import annotations

from pathlib import Path

from mech_pipeline.adapters.lean_runner import (
    LeanRunner,
    classify_compile_sub_error,
    classify_timeout_sub_error,
    extract_lean_error_details,
    prevalidate_theorem_decl,
)


def test_run_lean_resolves_relative_path_from_backend_root(tmp_path: Path, monkeypatch) -> None:
    root_dir = tmp_path / "physlean"
    root_dir.mkdir()
    captured: dict[str, object] = {}

    class _Proc:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, cwd, capture_output, text, encoding, errors, timeout, check):
        _ = (capture_output, text, encoding, errors, timeout, check)
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        return _Proc()

    monkeypatch.setattr("mech_pipeline.adapters.lean_runner.subprocess.run", fake_run)
    runner = LeanRunner(
        physlean_dir=root_dir,
        mechlib_dir=tmp_path / "mechlib",
        timeout_s=10,
        strict_blocklist=[],
        lean_header="import PhysLean",
    )

    ok, _stdout, _stderr = runner._run_lean(
        root_dir=root_dir,
        rel_file=Path("PhysLean/ClassicalMechanics/Basic.lean"),
    )

    assert ok is True
    assert Path(captured["cwd"]) == root_dir
    assert captured["cmd"][-1] == "PhysLean/ClassicalMechanics/Basic.lean"


def test_extract_lean_error_details_and_compile_sub_error() -> None:
    stderr = (
        "F:/repo/tmp.lean:11:4: error: Function expected at\n"
        "  averageVelocity\n"
        "but this term has type\n"
        "  ?m.1\n"
    )
    details = extract_lean_error_details("", stderr)

    assert details["error_line"] == 11
    assert details["error_message"] == "Function expected at"
    assert "averageVelocity" in str(details["stderr_excerpt"])
    assert classify_compile_sub_error("elaboration_failure", stderr) == "wrong_api_shape"


def test_prevalidate_decl_rejects_embedded_proof_without_spawning_lean(tmp_path: Path, monkeypatch) -> None:
    runner = LeanRunner(
        physlean_dir=tmp_path / "physlean",
        mechlib_dir=tmp_path / "mechlib",
        timeout_s=10,
        strict_blocklist=[],
        lean_header="import PhysLean",
        route_fallback=False,
    )

    def fail_run(*args, **kwargs):
        raise AssertionError("Lean subprocess should not be invoked for prevalidated invalid declarations")

    monkeypatch.setattr(runner, "_run_lean", fail_run)

    result = runner.compile_statement(
        sample_id="s1",
        candidate_id="c1",
        lean_header="import PhysLean",
        theorem_decl="theorem bad : 1 = 1 := by rfl",
        run_dir=tmp_path / "run",
    )

    assert prevalidate_theorem_decl("theorem bad : 1 = 1 := by rfl") is not None
    assert result["compile_pass"] is False
    assert result["error_type"] == "elaboration_failure"
    assert result["sub_error_type"] == "invalid_decl_shape"
    assert result["route_reason"] == "prelean_validation"
    assert result["failure_summary"] == "pre-lean declaration validation failed"
    assert result["failure_details"]["validation_reason"] == "embedded_proof_or_tactic_residue"


def test_compile_statement_classifies_empty_timeout(tmp_path: Path, monkeypatch) -> None:
    physlean_dir = tmp_path / "physlean"
    physlean_dir.mkdir()
    runner = LeanRunner(
        physlean_dir=physlean_dir,
        mechlib_dir=tmp_path / "mechlib",
        timeout_s=10,
        strict_blocklist=[],
        lean_header="import PhysLean",
        route_fallback=False,
    )

    monkeypatch.setattr(runner, "_run_lean", lambda *, root_dir, rel_file: (False, "", "[PIPELINE_TIMEOUT]"))
    result = runner.compile_statement(
        sample_id="s1",
        candidate_id="c1",
        lean_header="import PhysLean",
        theorem_decl="theorem ok (v : Real) : v = v + 1 - 1",
        run_dir=tmp_path / "run",
    )

    assert classify_timeout_sub_error("", "[PIPELINE_TIMEOUT]") == "empty_stderr_timeout"
    assert result["sub_error_type"] == "empty_stderr_timeout"
    assert result["failure_details"]["stderr_was_empty"] is True
    assert result["failure_details"]["stderr_had_warning_before_timeout"] is False


def test_compile_statement_classifies_timeout_after_warning(tmp_path: Path, monkeypatch) -> None:
    physlean_dir = tmp_path / "physlean"
    physlean_dir.mkdir()
    runner = LeanRunner(
        physlean_dir=physlean_dir,
        mechlib_dir=tmp_path / "mechlib",
        timeout_s=10,
        strict_blocklist=[],
        lean_header="import PhysLean",
        route_fallback=False,
    )
    stderr = "warning: batteries: repository 'X' has local changes\n[PIPELINE_TIMEOUT]"
    monkeypatch.setattr(runner, "_run_lean", lambda *, root_dir, rel_file: (False, "", stderr))

    result = runner.compile_statement(
        sample_id="s1",
        candidate_id="c1",
        lean_header="import PhysLean",
        theorem_decl="theorem ok (v : Real) : v = v + 1 - 1",
        run_dir=tmp_path / "run",
    )

    assert result["sub_error_type"] == "timeout_after_warning"
    assert result["failure_details"]["stderr_was_empty"] is False
    assert result["failure_details"]["stderr_had_warning_before_timeout"] is True


def test_preflight_details_reports_dirty_packages_from_probe_warning(tmp_path: Path, monkeypatch) -> None:
    physlean_dir = tmp_path / "physlean"
    physlean_dir.mkdir()
    (physlean_dir / "lakefile.toml").write_text('name = "PhysLean"\n', encoding="utf-8")
    (physlean_dir / "lean-toolchain").write_text("leanprover/lean4:v4.26.0\n", encoding="utf-8")

    runner = LeanRunner(
        physlean_dir=physlean_dir,
        mechlib_dir=None,
        timeout_s=10,
        strict_blocklist=[],
        lean_header="import PhysLean",
        route_fallback=False,
    )
    monkeypatch.setattr(
        runner,
        "_run_lean",
        lambda *, root_dir, rel_file: (True, "", "warning: batteries: repository 'X' has local changes"),
    )

    details = runner.preflight_details()

    assert details["ok"] is True
    assert details["environment_health"] == "dirty_packages"
    assert details["environment_warnings"]
