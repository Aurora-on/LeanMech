from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any

from mech_pipeline.utils import build_run_name, ensure_dir, write_json, write_jsonl, write_text


def create_run_dir(runs_dir: Path, tag: str | None) -> Path:
    ensure_dir(runs_dir)
    run_dir = runs_dir / build_run_name(tag)
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _build_manifest(run_dir: Path) -> dict[str, Any]:
    files = []
    for p in sorted(run_dir.rglob("*")):
        if p.is_file():
            files.append(
                {
                    "path": p.relative_to(run_dir).as_posix(),
                    "bytes": p.stat().st_size,
                    "sha256": _sha256(p),
                }
            )
    return {"files": files}


def write_outputs(
    run_dir: Path,
    latest_dir: Path,
    stage_rows: dict[str, list[dict[str, Any]]],
    metrics: dict[str, Any],
    analysis_md: str,
    run_readme_md: str,
    config_payload: dict[str, Any],
) -> None:
    ensure_dir(run_dir)
    ensure_dir(latest_dir)

    for name, rows in stage_rows.items():
        write_jsonl(run_dir / name, rows)
    write_json(run_dir / "metrics.json", metrics)
    write_text(run_dir / "analysis.md", analysis_md)
    write_text(run_dir / "README.md", run_readme_md)
    write_json(run_dir / "config.json", config_payload)
    write_json(run_dir / "manifest.json", _build_manifest(run_dir))

    if latest_dir.exists():
        for child in latest_dir.iterdir():
            if child.is_file():
                child.unlink()
            else:
                shutil.rmtree(child)
    ensure_dir(latest_dir)
    for p in run_dir.iterdir():
        target = latest_dir / p.name
        if p.is_file():
            shutil.copy2(p, target)
        else:
            shutil.copytree(p, target)
