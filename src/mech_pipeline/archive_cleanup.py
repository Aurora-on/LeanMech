from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


CANONICAL_RUNS = {
    "20260405_214834_mechanics101-realapi-par10-20260405-full",
    "20260407_123429_theoretical-mechanics-14-realapi-par10-20260407",
    "20260404_214417_competition-ch1-q10-target-equivalence-20260404",
    "20260404_200021_mechanics20-single-proxy-gpt54-20260404",
    "20260402_175059_mechanics-full-realapi-par10-20260402",
}

BENCHMARK_KEEP_RUNS = {
    "20260331_173229_bench-20260331-l4-c1",
    "20260331_175645_bench-20260331-l4-c4",
}

REQUIRED_RUN_FILES = ("metrics.json", "sample_summary.jsonl", "README.md")


def _repo_root_from(path: str | Path | None) -> Path:
    if path is not None:
        return Path(path).resolve()
    return Path(__file__).resolve().parents[2]


def _is_protected_path(rel_path: Path) -> bool:
    top_level = rel_path.parts[0] if rel_path.parts else ""
    if top_level in {"fixtures", "configs", "reports"}:
        return True
    if rel_path.as_posix() == "tmp/mechlib_index.jsonl":
        return True
    if rel_path.as_posix().startswith("outputs/latest"):
        return True
    return False


def _load_reference_texts(repo_root: Path) -> list[str]:
    texts: list[str] = []
    for path in [repo_root / "README.md", *sorted((repo_root / "reports").glob("*.md"))]:
        if path.exists():
            texts.append(path.read_text(encoding="utf-8", errors="replace"))
    return texts


def _is_referenced(rel_path: Path, reference_texts: list[str]) -> bool:
    needle = rel_path.as_posix()
    return any(needle in text for text in reference_texts)


def _candidate_records(repo_root: Path) -> list[tuple[Path, str]]:
    records: list[tuple[Path, str]] = []
    tmp_root = repo_root / "tmp"
    runs_root = repo_root / "runs"

    if tmp_root.exists():
        for path in sorted(tmp_root.glob("manual_cli_export*")):
            records.append((path, "tmp_manual_export"))
        for path in sorted(tmp_root.glob("tmpp*")):
            records.append((path, "tmp_random_tempdir"))
        for path in sorted(tmp_root.glob("generate_*_report.py")):
            records.append((path, "tmp_oneoff_report_script"))
        for path in sorted(tmp_root.glob("progress_check_realapi_*.log")):
            records.append((path, "tmp_oneoff_progress_log"))
        mathlib_probe = tmp_root / "mathlib_probe.lean"
        if mathlib_probe.exists():
            records.append((mathlib_probe, "tmp_mathlib_probe"))
        run_logs = tmp_root / "run_logs"
        if run_logs.exists():
            records.append((run_logs, "tmp_run_logs"))
        midterm_latex = tmp_root / "midterm_latex"
        if midterm_latex.exists():
            records.append((midterm_latex, "tmp_midterm_latex"))
        pytest_basetemp = tmp_root / "pytest" / "basetemp"
        if pytest_basetemp.exists():
            for path in sorted(pytest_basetemp.iterdir()):
                records.append((path, "tmp_pytest_basetemp"))

    if runs_root.exists():
        for path in sorted(p for p in runs_root.iterdir() if p.is_dir()):
            if path.name in CANONICAL_RUNS:
                continue
            if path.name.startswith("20260331_") and "bench-20260331-" in path.name and path.name not in BENCHMARK_KEEP_RUNS:
                records.append((path, "redundant_benchmark_run"))
                continue
            names = {child.name for child in path.iterdir()}
            if any(required not in names for required in REQUIRED_RUN_FILES):
                records.append((path, "incomplete_run"))

    dedup: dict[Path, str] = {}
    for path, reason in records:
        dedup[path] = reason
    return sorted(dedup.items(), key=lambda item: item[0].as_posix())


def build_archive_plan(repo_root: str | Path | None = None) -> dict[str, object]:
    root = _repo_root_from(repo_root)
    reference_texts = _load_reference_texts(root)
    plan: dict[str, object] = {"to_move": [], "kept": [], "skipped": [], "reasons": {}}
    reasons: dict[str, str] = {}

    for path, reason in _candidate_records(root):
        rel_path = path.relative_to(root)
        rel_key = rel_path.as_posix()
        if _is_protected_path(rel_path):
            plan["kept"].append(rel_key)
            reasons[rel_key] = "protected_path"
            continue
        if _is_referenced(rel_path, reference_texts):
            plan["skipped"].append(rel_key)
            reasons[rel_key] = "referenced_by_readme_or_report"
            continue
        plan["to_move"].append(rel_key)
        reasons[rel_key] = reason

    plan["to_move"] = sorted(set(plan["to_move"]))
    plan["kept"] = sorted(set(plan["kept"]))
    plan["skipped"] = sorted(set(plan["skipped"]))
    plan["reasons"] = reasons
    return plan


def apply_archive_plan(plan: dict[str, object], repo_root: str | Path | None = None) -> list[str]:
    root = _repo_root_from(repo_root)
    moved: list[str] = []
    for rel in plan.get("to_move", []):
        rel_path = Path(str(rel))
        src = root / rel_path
        if not src.exists():
            continue
        dest = root / "rubbish" / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dest))
        moved.append(rel_path.as_posix())

    basetemp_root = root / "tmp" / "pytest" / "basetemp"
    basetemp_root.mkdir(parents=True, exist_ok=True)
    return moved


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="archive-cleanup", description="Archive test artifacts into rubbish/")
    parser.add_argument("--repo-root", type=str, default=None)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--indent", type=int, default=2)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    plan = build_archive_plan(args.repo_root)
    if args.apply:
        moved = apply_archive_plan(plan, args.repo_root)
        plan["moved"] = moved
    print(json.dumps(plan, ensure_ascii=False, indent=args.indent))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
