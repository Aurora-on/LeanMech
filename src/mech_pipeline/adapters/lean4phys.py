from __future__ import annotations

import json
import re
from pathlib import Path

from mech_pipeline.adapters.base import DatasetAdapter
from mech_pipeline.types import CanonicalSample
from mech_pipeline.utils import redact_leakage_text

OPTION_PATTERN = re.compile(r"^\s*([A-D])[).:]\s*(.+?)\s*$")
ANSWER_PATTERN = re.compile(r"\b([A-D])\b")


def _parse_options(text: str) -> list[str]:
    options: list[str] = []
    for line in text.splitlines():
        m = OPTION_PATTERN.match(line)
        if m:
            options.append(f"{m.group(1)}. {m.group(2).strip()}")
    return options


def _parse_answer_from_statement(statement: str) -> str | None:
    m = ANSWER_PATTERN.search(statement)
    if not m:
        return None
    return m.group(1).upper()


class Lean4PhysDatasetAdapter(DatasetAdapter):
    def __init__(
        self,
        bench_path: str,
        category: str = "mechanics",
        level: str | None = None,
        sample_policy: str = "index_head",
        limit: int = 10,
        seed: int = 42,
    ) -> None:
        self.bench_path = Path(bench_path)
        self.category = category
        self.level = level
        self.sample_policy = sample_policy
        self.limit = limit
        self.seed = seed

    def load(self) -> list[CanonicalSample]:
        if not self.bench_path.exists():
            raise FileNotFoundError(f"Lean4Phys bench file not found: {self.bench_path}")

        rows = json.loads(self.bench_path.read_text(encoding="utf-8"))
        if not isinstance(rows, list):
            raise ValueError("Lean4Phys bench json root must be a list")

        filtered: list[dict] = []
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

        filtered = filtered[: self.limit]
        samples: list[CanonicalSample] = []
        for idx, row in enumerate(filtered, start=1):
            name = str(row.get("Name") or f"lean4phys_{idx}")
            informal = str(row.get("Informal_statement") or "").strip()
            header = str(row.get("Header") or "").strip()
            if not informal:
                # Prevent leaking formal targets/proofs as input text.
                problem_text = ""
                skip_reason = "missing_informal_statement"
            else:
                problem_text = redact_leakage_text(informal)
                skip_reason = None
            options = _parse_options(problem_text)
            gold_answer = _parse_answer_from_statement(problem_text)
            samples.append(
                CanonicalSample(
                    sample_id=f"lean4phys-{name}",
                    source="lean4phys",
                    problem_text=problem_text,
                    options=options,
                    gold_answer=gold_answer,
                    image_b64=None,
                    image_path=None,
                    image_description=None,
                    category=str(row.get("Category") or "").lower() or None,
                    subfield="mechanics",
                    reasoning_type=str(row.get("Level") or "") or None,
                    skip_reason=skip_reason,
                    meta={
                        "name": name,
                        "header": header,
                    },
                )
            )
        return samples
