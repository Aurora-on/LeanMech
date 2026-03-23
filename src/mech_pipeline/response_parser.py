from __future__ import annotations

import json
import re
from typing import TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class ResponseParseError(RuntimeError):
    pass


def _extract_json_text(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ResponseParseError("No JSON object found in model response")
    return cleaned[start : end + 1]


def parse_json_model(text: str, model: type[T]) -> T:
    try:
        payload = json.loads(_extract_json_text(text))
    except (json.JSONDecodeError, ResponseParseError) as exc:
        raise ResponseParseError(str(exc)) from exc

    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise ResponseParseError(str(exc)) from exc
