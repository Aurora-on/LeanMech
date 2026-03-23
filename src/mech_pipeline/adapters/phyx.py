from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from mech_pipeline.adapters.base import DatasetAdapter
from mech_pipeline.types import CanonicalSample
from mech_pipeline.utils import redact_leakage_text

OPTION_PATTERN = re.compile(r"^\s*([A-D])[).:]\s*(.+?)\s*$")


@dataclass
class DataSourceUnavailableError(RuntimeError):
    message: str

    def __str__(self) -> str:
        return self.message


def normalize_answer(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().upper()
    m = re.search(r"\b([A-D])\b", text)
    if m:
        return m.group(1)
    return text[:1] if text else None


def parse_options(question_text: str) -> list[str]:
    options: list[str] = []
    for line in question_text.splitlines():
        m = OPTION_PATTERN.match(line)
        if m:
            options.append(f"{m.group(1)}. {m.group(2).strip()}")
    return options


def _import_pandas():
    try:
        import pandas as pd  # type: ignore

        return pd
    except Exception as exc:  # pragma: no cover
        raise DataSourceUnavailableError(f"data_source_unavailable: pandas import failed: {exc}") from exc


def _read_first_available(urls: list[str]) -> tuple[Any, str]:
    pd = _import_pandas()
    errors: list[str] = []
    for url in urls:
        try:
            return pd.read_parquet(url), url
        except Exception as exc:  # pragma: no cover
            errors.append(f"{url}: {type(exc).__name__}: {exc}")
    raise DataSourceUnavailableError(
        "data_source_unavailable: all phyx_urls failed\n" + "\n".join(errors)
    )


class PhyxDatasetAdapter(DatasetAdapter):
    def __init__(
        self,
        phyx_urls: list[str],
        category: str,
        sample_policy: str,
        limit: int,
        seed: int,
    ) -> None:
        self.phyx_urls = phyx_urls
        self.category = category
        self.sample_policy = sample_policy
        self.limit = limit
        self.seed = seed

    def load(self) -> list[CanonicalSample]:
        df, chosen_url = _read_first_available(self.phyx_urls)
        df = df[df["category"] == self.category]
        if "index" in df.columns:
            df = df.sort_values("index", ascending=True)

        if self.sample_policy == "seed_random":
            n = min(self.limit, len(df))
            df = df.sample(n=n, random_state=self.seed)
        else:
            df = df.head(self.limit)

        samples: list[CanonicalSample] = []
        for i, row in enumerate(df.to_dict(orient="records"), start=1):
            raw_index = row.get("index")
            sample_id = f"phyx-{raw_index}" if raw_index is not None else f"phyx-{i}"
            question_text = redact_leakage_text(str(row.get("question") or "").strip())
            image_value = row.get("image")
            image_b64 = image_value if isinstance(image_value, str) and image_value else None
            samples.append(
                CanonicalSample(
                    sample_id=sample_id,
                    source="phyx",
                    problem_text=question_text,
                    options=parse_options(question_text),
                    gold_answer=normalize_answer(row.get("answer")),
                    image_b64=image_b64,
                    image_path=None,
                    image_description=None,
                    category=str(row.get("category") or "") or None,
                    subfield=str(row.get("subfield") or "") or None,
                    reasoning_type=str(row.get("reasoning_type") or "") or None,
                    skip_reason=None,
                    meta={"raw_index": raw_index, "phyx_url": chosen_url},
                )
            )
        return samples
