from __future__ import annotations

from pathlib import Path

from mech_pipeline.adapters.lean_runner import LeanRunner


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
