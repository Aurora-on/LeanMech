from __future__ import annotations

from typing import Any

from openai import OpenAI
from openai.types.chat import (
    ChatCompletionContentPartImageParam,
    ChatCompletionContentPartParam,
    ChatCompletionContentPartTextParam,
    ChatCompletionMessageParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionUserMessageParam,
)

from mech_pipeline.model.base import ModelClient
from mech_pipeline.types import ModelResponse


def normalize_base_url(base_url: str | None) -> str | None:
    if base_url is None:
        return None
    value = base_url.strip().rstrip("/")
    if not value:
        return None
    if value.endswith("/v1"):
        return value
    return f"{value}/v1"


def _extract_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
        return "\n".join(parts).strip()
    return str(content or "")


class OpenAICompatibleClient(ModelClient):
    def __init__(
        self,
        model_id: str | None,
        api_key: str,
        base_url: str | None,
        supports_vision: bool,
        timeout_s: int,
        max_retries: int,
    ) -> None:
        if not model_id:
            raise ValueError("model_id is required for openai_compatible provider")
        if not api_key:
            raise ValueError("API key is empty, check model.api_key_env")
        # Keep a non-optional field for SDK calls to satisfy static type checkers.
        self._model_id: str = model_id
        self.model_id = model_id
        self.supports_vision = supports_vision
        self.client = OpenAI(
            api_key=api_key,
            base_url=normalize_base_url(base_url),
            timeout=timeout_s,
            max_retries=max_retries,
        )

    def generate_text(self, prompt: str, **kwargs) -> ModelResponse:
        system_message: ChatCompletionSystemMessageParam = {
            "role": "system",
            "content": "You are a strict JSON generator for mechanics formalization.",
        }
        user_message: ChatCompletionUserMessageParam = {
            "role": "user",
            "content": prompt,
        }
        messages: list[ChatCompletionMessageParam] = [system_message, user_message]
        completion = self.client.chat.completions.create(
            model=self._model_id,
            temperature=float(kwargs.get("temperature", 0.0)),
            messages=messages,
        )
        text = _extract_text(completion.choices[0].message.content)
        usage = completion.usage.model_dump() if completion.usage else {}
        return ModelResponse(text=text, raw=completion.model_dump(), usage=usage)

    def generate_multimodal(self, prompt: str, images_b64: list[str], **kwargs) -> ModelResponse:
        if not self.supports_vision:
            raise RuntimeError("supports_vision=false")
        content: list[ChatCompletionContentPartParam] = []
        text_part: ChatCompletionContentPartTextParam = {"type": "text", "text": prompt}
        content.append(text_part)
        for img in images_b64:
            image_part: ChatCompletionContentPartImageParam = {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{img}"},
            }
            content.append(image_part)
        system_message: ChatCompletionSystemMessageParam = {
            "role": "system",
            "content": "You are a strict JSON generator for mechanics formalization.",
        }
        user_message: ChatCompletionUserMessageParam = {"role": "user", "content": content}
        messages: list[ChatCompletionMessageParam] = [system_message, user_message]
        completion = self.client.chat.completions.create(
            model=self._model_id,
            temperature=float(kwargs.get("temperature", 0.0)),
            messages=messages,
        )
        text = _extract_text(completion.choices[0].message.content)
        usage = completion.usage.model_dump() if completion.usage else {}
        return ModelResponse(text=text, raw=completion.model_dump(), usage=usage)
