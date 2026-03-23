from __future__ import annotations

import pandas as pd

from mech_pipeline.adapters.phyx import PhyxDatasetAdapter


def test_phyx_fallback(monkeypatch) -> None:
    calls: list[str] = []

    def fake_read_parquet(url: str):
        calls.append(url)
        if "first" in url:
            raise RuntimeError("fail first")
        return pd.DataFrame(
            [
                {
                    "index": 1,
                    "category": "Mechanics",
                    "question": "A. 1\nB. 2",
                    "answer": "A",
                    "image": None,
                    "subfield": "basic",
                    "reasoning_type": "calc",
                }
            ]
        )

    monkeypatch.setattr(pd, "read_parquet", fake_read_parquet)
    adapter = PhyxDatasetAdapter(
        phyx_urls=["first-url", "second-url"],
        category="Mechanics",
        sample_policy="index_head",
        limit=1,
        seed=42,
    )
    samples = adapter.load()
    assert len(samples) == 1
    assert calls == ["first-url", "second-url"]
