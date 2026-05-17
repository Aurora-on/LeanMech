from __future__ import annotations

import json
from pathlib import Path

from mech_pipeline.adapters.mixed_v2 import MixedV2DatasetAdapter


def test_mixed_v2_loads_archive_rows_with_image_path_without_description(tmp_path: Path) -> None:
    archive_root = tmp_path / "archive"
    image_dir = archive_root / "images"
    image_dir.mkdir(parents=True)
    image_file = image_dir / "sample.jpg"
    image_file.write_bytes(b"fake-image")

    bench = tmp_path / "mixed.json"
    bench.write_text(
        json.dumps(
            [
                {
                    "Name": "lean_item",
                    "Level": "college_level",
                    "Category": "mechanics",
                    "Informal_statement": "Question: Find acceleration.",
                    "V2SourceKind": "lean4phys",
                    "V2SourceRef": "lean_item",
                },
                {
                    "Name": "archive_part1_9_1",
                    "Level": "archive_part1",
                    "Category": "mechanics",
                    "Informal_statement": "9-1题面文字\n![](images/sample.jpg)",
                    "V2SourceKind": "archive_part1",
                    "V2SourceRef": "9-1",
                    "V2ArchiveImagePaths": ["images/sample.jpg"],
                },
                {
                    "Name": "archive_part2_1_9",
                    "Level": "archive_part2",
                    "Category": "mechanics",
                    "Informal_statement": "1-9题面文字\n![](images/sample.jpg)",
                    "V2SourceKind": "archive_part2",
                    "V2SourceRef": "1-9",
                    "V2ArchiveImagePaths": ["images/sample.jpg"],
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    samples = MixedV2DatasetAdapter(
        bench_path=str(bench),
        archive_root=str(archive_root),
        category="mechanics",
        limit=10,
        single_image_only=True,
    ).load()

    assert len(samples) == 3
    assert samples[0].image_path is None
    assert samples[0].image_description is None
    assert samples[1].sample_id == "archive_part1-archive_part1_9_1"
    assert samples[1].image_path == str(image_file.resolve())
    assert samples[1].image_description is None
    assert samples[1].skip_reason is None
    assert samples[2].sample_id == "archive_part2-archive_part2_1_9"
    assert samples[2].image_path == str(image_file.resolve())
    assert samples[2].image_description is None
    assert samples[2].skip_reason is None


def test_mixed_v2_allows_archive_row_without_image_as_text_only(tmp_path: Path) -> None:
    bench = tmp_path / "mixed.json"
    bench.write_text(
        json.dumps(
            [
                {
                    "Name": "archive_part1_10_2",
                    "Level": "archive_part1",
                    "Category": "mechanics",
                    "Informal_statement": "10-2题面文字",
                    "V2SourceKind": "archive_part1",
                    "V2SourceRef": "10-2",
                    "V2ArchiveImagePaths": [],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    samples = MixedV2DatasetAdapter(
        bench_path=str(bench),
        archive_root=str(tmp_path / "archive"),
        category="mechanics",
        limit=10,
        single_image_only=True,
    ).load()

    assert samples[0].image_path is None
    assert samples[0].image_description is None
    assert samples[0].skip_reason is None


def test_mixed_v2_marks_declared_but_missing_image_as_missing_diagram(tmp_path: Path) -> None:
    bench = tmp_path / "mixed.json"
    bench.write_text(
        json.dumps(
            [
                {
                    "Name": "archive_part1_10_2",
                    "Level": "archive_part1",
                    "Category": "mechanics",
                    "Informal_statement": "10-2题面文字",
                    "V2SourceKind": "archive_part1",
                    "V2SourceRef": "10-2",
                    "V2ArchiveImagePaths": ["images/missing.jpg"],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    samples = MixedV2DatasetAdapter(
        bench_path=str(bench),
        archive_root=str(tmp_path / "archive"),
        category="mechanics",
        limit=10,
        single_image_only=True,
    ).load()

    assert samples[0].image_path is None
    assert samples[0].image_description is None
    assert samples[0].skip_reason == "missing_diagram_information"
