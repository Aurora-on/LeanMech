from __future__ import annotations

from mech_pipeline.model.openai_compatible import OpenAICompatibleClient, normalize_base_url


class _FakeUsage:
    def model_dump(self):
        return {}


class _FakeMessage:
    content = '{"ok": true}'


class _FakeChoice:
    message = _FakeMessage()


class _FakeCompletion:
    choices = [_FakeChoice()]
    usage = _FakeUsage()

    def model_dump(self):
        return {"id": "fake"}


class _FakeCompletions:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeCompletion()


class _FakeChat:
    def __init__(self) -> None:
        self.completions = _FakeCompletions()


class _FakeOpenAI:
    instances: list["_FakeOpenAI"] = []

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.chat = _FakeChat()
        self.instances.append(self)


def test_normalize_deepseek_base_url_adds_v1() -> None:
    assert normalize_base_url("https://api.deepseek.com") == "https://api.deepseek.com/v1"


def test_openai_compatible_client_passes_reasoning_and_thinking_extra(monkeypatch) -> None:
    import mech_pipeline.model.openai_compatible as module

    _FakeOpenAI.instances.clear()
    monkeypatch.setattr(module, "OpenAI", _FakeOpenAI)
    client = OpenAICompatibleClient(
        model_id="deepseek-v4-pro",
        api_key="test-key",
        base_url="https://api.deepseek.com",
        supports_vision=False,
        timeout_s=30,
        max_retries=0,
        request_extra={
            "reasoning_effort": "max",
            "extra_body": {"thinking": {"type": "enabled"}},
        },
    )

    response = client.generate_text("Return JSON.")

    assert response.text == '{"ok": true}'
    fake = _FakeOpenAI.instances[0]
    assert fake.kwargs["base_url"] == "https://api.deepseek.com/v1"
    call = fake.chat.completions.calls[0]
    assert call["model"] == "deepseek-v4-pro"
    assert call["reasoning_effort"] == "max"
    assert call["extra_body"] == {"thinking": {"type": "enabled"}}
