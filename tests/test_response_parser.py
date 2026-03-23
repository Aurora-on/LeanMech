from __future__ import annotations

from pydantic import BaseModel

from mech_pipeline.response_parser import ResponseParseError, parse_json_model


class DemoPayload(BaseModel):
    value: int


def test_parse_json_model_plain() -> None:
    parsed = parse_json_model('{"value": 7}', DemoPayload)
    assert parsed.value == 7


def test_parse_json_model_fenced() -> None:
    parsed = parse_json_model("```json\n{\"value\": 11}\n```", DemoPayload)
    assert parsed.value == 11


def test_parse_json_model_invalid_raises() -> None:
    try:
        parse_json_model('{"value":"oops"}', DemoPayload)
    except ResponseParseError:
        return
    raise AssertionError("Expected ResponseParseError")
