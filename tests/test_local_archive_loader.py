from __future__ import annotations

from pathlib import Path

from mech_pipeline.adapters.local_archive import LocalArchiveDatasetAdapter


def _prepare_archive(root: Path) -> None:
    (root / "output_description_part1").mkdir(parents=True, exist_ok=True)
    (root / "output_checked_part1").mkdir(parents=True, exist_ok=True)
    (root / "images").mkdir(parents=True, exist_ok=True)

    (root / "output_description_part1" / "1-1.md").write_text(
        "<image_description>desc</image_description>\n题目: 已知 F=ma",
        encoding="utf-8",
    )
    (root / "images" / "a.jpg").write_bytes(b"fake")
    (root / "output_checked_part1" / "1-2.md").write_text(
        "题目: 受力分析\n![](../images/a.jpg)",
        encoding="utf-8",
    )


def test_local_archive_text_only(tmp_path: Path) -> None:
    _prepare_archive(tmp_path)
    loader = LocalArchiveDatasetAdapter(
        root_dir=str(tmp_path),
        mode="text_only",
        limit=5,
        single_image_only=True,
    )
    samples = loader.load()
    assert len(samples) == 1
    assert samples[0].image_description == "desc"
    assert samples[0].skip_reason is None


def test_local_archive_image_text(tmp_path: Path) -> None:
    _prepare_archive(tmp_path)
    loader = LocalArchiveDatasetAdapter(
        root_dir=str(tmp_path),
        mode="image_text",
        limit=5,
        single_image_only=True,
    )
    samples = loader.load()
    assert len(samples) == 1
    assert samples[0].image_path is not None
    assert samples[0].skip_reason is None
