from __future__ import annotations

import re
from pathlib import Path

from mech_pipeline.adapters.base import DatasetAdapter
from mech_pipeline.types import CanonicalSample
from mech_pipeline.utils import redact_leakage_text

IMAGE_MD_PATTERN = re.compile(r"!\[[^\]]*]\(([^)]+)\)")
OPTION_PATTERN = re.compile(r"^\s*([A-D])[).:]\s*(.+?)\s*$")
ANSWER_PATTERN = re.compile(r"(?:^|\n)\s*(?:Answer|ANSWER|答案)\s*[:：]?\s*([A-D])\b")
IMAGE_DESCRIPTION_PATTERN = re.compile(
    r"<image_description>(.*?)</image_description>",
    re.DOTALL,
)


def _read_text(path: Path) -> str:
    for enc in ("utf-8", "utf-8-sig", "gb18030", "gbk"):
        try:
            return path.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def _parse_options(text: str) -> list[str]:
    out: list[str] = []
    for line in text.splitlines():
        m = OPTION_PATTERN.match(line)
        if m:
            out.append(f"{m.group(1)}. {m.group(2).strip()}")
    return out


def _parse_answer(text: str) -> str | None:
    m = ANSWER_PATTERN.search(text)
    if not m:
        return None
    return m.group(1).upper()


def _extract_image_description(text: str) -> str | None:
    m = IMAGE_DESCRIPTION_PATTERN.search(text)
    if not m:
        return None
    return m.group(1).strip()


def _collect_markdown_files(root: Path, mode: str) -> list[Path]:
    if mode == "text_only":
        folders = ["output_description_part1", "output_description_part2"]
    else:
        folders = ["output_checked_part1", "output_checked_part2"]
    files: list[Path] = []
    for folder in folders:
        full = root / folder
        if full.exists():
            files.extend(sorted(full.glob("*.md")))
    return files


class LocalArchiveDatasetAdapter(DatasetAdapter):
    def __init__(self, root_dir: str, mode: str, limit: int, single_image_only: bool) -> None:
        self.root_dir = Path(root_dir)
        self.mode = mode
        self.limit = limit
        self.single_image_only = single_image_only

    def load(self) -> list[CanonicalSample]:
        if not self.root_dir.exists():
            raise FileNotFoundError(f"Local archive root does not exist: {self.root_dir}")

        files = _collect_markdown_files(self.root_dir, self.mode)
        samples: list[CanonicalSample] = []
        for path in files[: self.limit]:
            text = _read_text(path)
            safe_text = redact_leakage_text(text)
            images = IMAGE_MD_PATTERN.findall(text)
            image_desc = _extract_image_description(text)
            image_path: str | None = None
            skip_reason: str | None = None

            if self.mode == "image_text":
                if self.single_image_only and len(images) != 1:
                    skip_reason = "unsupported_multi_image_sample"
                elif len(images) == 0:
                    skip_reason = "missing_diagram_information"
                else:
                    image_rel = images[0].strip()
                    image_abs = (path.parent / image_rel).resolve()
                    image_path = str(image_abs) if image_abs.exists() else None
                    if image_path is None:
                        skip_reason = "missing_diagram_information"

                    if image_desc is None and image_path is not None:
                        hash_name = Path(image_path).stem + ".txt"
                        desc_path = self.root_dir / "image_description" / hash_name
                        if desc_path.exists():
                            image_desc = _read_text(desc_path).strip()

            sample = CanonicalSample(
                sample_id=f"archive-{path.stem}",
                source="local_archive",
                problem_text=safe_text,
                options=_parse_options(safe_text),
                gold_answer=_parse_answer(text),
                image_b64=None,
                image_path=image_path,
                image_description=image_desc,
                category="Mechanics",
                skip_reason=skip_reason,
                meta={"file_path": str(path), "mode": self.mode, "num_images": len(images)},
            )
            samples.append(sample)

        return samples
