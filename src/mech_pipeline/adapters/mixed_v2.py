from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from mech_pipeline.adapters.base import DatasetAdapter
from mech_pipeline.adapters.lean4phys import _parse_answer_from_statement, _parse_options
from mech_pipeline.types import CanonicalSample
from mech_pipeline.utils import redact_leakage_text


def _resolve_optional_image(path_value: object, archive_root: Path, bench_path: Path) -> str | None:
    if not isinstance(path_value, str) or not path_value.strip():
        return None
    raw = Path(path_value.strip())
    candidates = [raw] if raw.is_absolute() else [archive_root / raw, bench_path.parent / raw, archive_root.parent / raw]
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.exists():
            return str(resolved)
    return None


class MixedV2DatasetAdapter(DatasetAdapter):
    """Load mixed v2 manifests containing Lean4Phys rows and archive+image rows."""

    def __init__(
        self,
        bench_path: str,
        archive_root: str,
        category: str = "mechanics",
        level: str | None = None,
        sample_policy: str = "index_head",
        limit: int = 10,
        seed: int = 42,
        single_image_only: bool = True,
    ) -> None:
        self.bench_path = Path(bench_path)
        self.archive_root = Path(archive_root)
        self.category = category
        self.level = level
        self.sample_policy = sample_policy
        self.limit = limit
        self.seed = seed
        self.single_image_only = single_image_only

    def load(self) -> list[CanonicalSample]:
        if not self.bench_path.exists():
            raise FileNotFoundError(f"Mixed v2 bench file not found: {self.bench_path}")
        rows = json.loads(self.bench_path.read_text(encoding="utf-8"))
        if not isinstance(rows, list):
            raise ValueError("Mixed v2 bench json root must be a list")

        filtered: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            if str(row.get("Category", "")).lower() != self.category.lower():
                continue
            if self.level and str(row.get("Level", "")).lower() != self.level.lower():
                continue
            filtered.append(row)

        if self.sample_policy == "seed_random":
            import random

            rng = random.Random(self.seed)
            rng.shuffle(filtered)

        samples: list[CanonicalSample] = []
        for idx, row in enumerate(filtered[: self.limit], start=1):
            source_kind = str(row.get("V2SourceKind") or "lean4phys")
            name = str(row.get("Name") or f"mixed_v2_{idx}")
            informal = str(row.get("Informal_statement") or "").strip()
            problem_text = redact_leakage_text(informal) if informal else ""
            skip_reason: str | None = None if problem_text else "missing_informal_statement"
            image_path: str | None = None

            if source_kind in {"archive_part1", "archive_part2"}:
                image_values = row.get("V2ArchiveImagePaths")
                images = image_values if isinstance(image_values, list) else []
                resolved_images = [
                    resolved
                    for value in images
                    if (resolved := _resolve_optional_image(value, self.archive_root, self.bench_path)) is not None
                ]
                if images and not resolved_images:
                    skip_reason = "missing_diagram_information"
                elif resolved_images and self.single_image_only and len(resolved_images) != 1:
                    skip_reason = "unsupported_multi_image_sample"
                elif resolved_images:
                    image_path = resolved_images[0]

            samples.append(
                CanonicalSample(
                    sample_id=f"{source_kind}-{name}",
                    source=source_kind,
                    problem_text=problem_text,
                    options=_parse_options(problem_text),
                    gold_answer=_parse_answer_from_statement(problem_text),
                    image_b64=None,
                    image_path=image_path,
                    image_description=None,
                    category=str(row.get("Category") or "").lower() or None,
                    subfield="mechanics",
                    reasoning_type=str(row.get("Level") or "") or None,
                    skip_reason=skip_reason,
                    meta={
                        "name": name,
                        "source_kind": source_kind,
                        "source_ref": row.get("V2SourceRef"),
                        "header": str(row.get("Header") or ""),
                    },
                )
            )
        return samples
