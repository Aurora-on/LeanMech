from __future__ import annotations

from abc import ABC, abstractmethod
from os import getenv

from mech_pipeline.config import ModelConfig
from mech_pipeline.types import ModelResponse


class ModelClient(ABC):
    model_id: str | None
    supports_vision: bool

    @abstractmethod
    def generate_text(self, prompt: str, **kwargs) -> ModelResponse:
        raise NotImplementedError

    @abstractmethod
    def generate_multimodal(self, prompt: str, images_b64: list[str], **kwargs) -> ModelResponse:
        raise NotImplementedError


def build_model_client(config: ModelConfig) -> ModelClient:
    provider = config.provider.strip().lower()
    if provider in {"mock", "dummy"}:
        from mech_pipeline.model.mock import MockModelClient

        return MockModelClient(model_id=config.model_id, supports_vision=config.supports_vision)

    if provider in {"openai", "openai_compatible"}:
        from mech_pipeline.model.openai_compatible import OpenAICompatibleClient

        api_key = config.api_key if config.api_key else getenv(config.api_key_env, "")
        return OpenAICompatibleClient(
            model_id=config.model_id,
            api_key=api_key,
            base_url=config.base_url,
            supports_vision=config.supports_vision,
            timeout_s=config.timeout_s,
            max_retries=config.max_retries,
        )

    raise ValueError("Unsupported provider, use {'mock', 'openai_compatible'}")
