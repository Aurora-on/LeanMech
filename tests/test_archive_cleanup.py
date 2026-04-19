from __future__ import annotations

from pathlib import Path

from mech_pipeline.archive_cleanup import apply_archive_plan, build_archive_plan


def _touch(path: Path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_archive_cleanup_plans_and_applies_expected_moves(tmp_path: Path) -> None:
    _touch(tmp_path / "README.md", "# repo\n")
    _touch(tmp_path / "reports" / "bench.md", "keep reference runs/20260331_174709_bench-20260331-l4-c2\n")
    _touch(tmp_path / "fixtures" / "bench.json", "{}")
    _touch(tmp_path / "configs" / "cfg.yaml", "x: 1\n")
    _touch(tmp_path / "tmp" / "mechlib_index.jsonl", "")
    _touch(tmp_path / "tmp" / "manual_cli_export_check" / "note.txt", "x")
    _touch(tmp_path / "tmp" / "run_logs" / "one.log", "x")
    _touch(tmp_path / "tmp" / "pytest" / "basetemp" / "oldcase" / "a.txt", "x")
    _touch(tmp_path / "tmp" / "mathlib_probe.lean", "-- probe\n")
    _touch(tmp_path / "outputs" / "latest" / "README.md", "# latest\n")

    complete_run = tmp_path / "runs" / "20260405_214834_mechanics101-realapi-par10-20260405-full"
    _touch(complete_run / "metrics.json", "{}")
    _touch(complete_run / "sample_summary.jsonl", "")
    _touch(complete_run / "README.md", "# run\n")

    incomplete_run = tmp_path / "runs" / "20260405_214152_mechanics101-realapi-par10-20260505"
    _touch(incomplete_run / "README.md", "# incomplete\n")

    bench_keep = tmp_path / "runs" / "20260331_173229_bench-20260331-l4-c1"
    _touch(bench_keep / "metrics.json", "{}")
    _touch(bench_keep / "sample_summary.jsonl", "")
    _touch(bench_keep / "README.md", "# keep\n")

    bench_ref = tmp_path / "runs" / "20260331_174709_bench-20260331-l4-c2"
    _touch(bench_ref / "metrics.json", "{}")
    _touch(bench_ref / "sample_summary.jsonl", "")
    _touch(bench_ref / "README.md", "# referenced\n")

    plan = build_archive_plan(tmp_path)

    assert "tmp/manual_cli_export_check" in plan["to_move"]
    assert "tmp/run_logs" in plan["to_move"]
    assert "tmp/pytest/basetemp/oldcase" in plan["to_move"]
    assert "tmp/mathlib_probe.lean" in plan["to_move"]
    assert "runs/20260405_214152_mechanics101-realapi-par10-20260505" in plan["to_move"]
    assert "runs/20260331_174709_bench-20260331-l4-c2" in plan["skipped"]
    assert all(not item.startswith("outputs/latest") for item in plan["to_move"])
    assert "tmp/mechlib_index.jsonl" not in plan["to_move"]
    assert "tmp/mechlib_index.jsonl" not in plan["skipped"]

    moved = apply_archive_plan(plan, tmp_path)

    assert "tmp/manual_cli_export_check" in moved
    assert not (tmp_path / "tmp" / "manual_cli_export_check").exists()
    assert (tmp_path / "rubbish" / "tmp" / "manual_cli_export_check" / "note.txt").exists()
    assert not (tmp_path / "tmp" / "run_logs").exists()
    assert (tmp_path / "rubbish" / "tmp" / "run_logs" / "one.log").exists()
    assert not incomplete_run.exists()
    assert (tmp_path / "rubbish" / "runs" / incomplete_run.name / "README.md").exists()
    assert bench_ref.exists()
    assert (tmp_path / "tmp" / "pytest" / "basetemp").exists()
