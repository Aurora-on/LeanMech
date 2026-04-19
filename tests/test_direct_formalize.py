from __future__ import annotations

from pathlib import Path

from mech_pipeline.model.base import ModelClient
from mech_pipeline.modules.Z_direct_formalize import ModuleZDirectFormalize
from mech_pipeline.types import CanonicalSample, ModelResponse


class StaticDirectClient(ModelClient):
    def __init__(self, payload: str) -> None:
        self.model_id = "static-direct"
        self.supports_vision = False
        self._payload = payload

    def generate_text(self, prompt: str, **kwargs) -> ModelResponse:
        _ = (prompt, kwargs)
        return ModelResponse(text=self._payload)

    def generate_multimodal(self, prompt: str, images_b64: list[str], **kwargs) -> ModelResponse:
        _ = (prompt, images_b64, kwargs)
        return ModelResponse(text=self._payload)


def _sample() -> CanonicalSample:
    return CanonicalSample(
        sample_id="s1",
        source="lean4phys",
        problem_text="A body of mass m is acted on by a force F. Find the acceleration.",
        options=[],
        meta={"name": "sample_1"},
    )


def test_direct_formalize_parses_valid_payload(tmp_path: Path) -> None:
    prompt_path = tmp_path / "Z_direct_formalize.txt"
    prompt_path.write_text("__TASK_Z_DIRECT_FORMALIZE__", encoding="utf-8")
    module = ModuleZDirectFormalize(
        model_client=StaticDirectClient(
            '{"theorem_decl":"theorem t (F m a : Real) (hm : m != 0) (h : F = m * a) : a = F / m",'
            '"plan":"Solve for a","used_facts":["h","hm"]}'
        ),
        prompt_path=prompt_path,
        lean_header="import PhysLean",
    )

    row = module.run(_sample())

    assert row.parse_ok is True
    assert row.theorem_decl.startswith("theorem t")
    assert row.proof_body == ""
    assert row.plan == "Solve for a"
    assert row.used_facts == ["h", "hm"]


def test_direct_formalize_rejects_missing_theorem_decl(tmp_path: Path) -> None:
    prompt_path = tmp_path / "Z_direct_formalize.txt"
    prompt_path.write_text("__TASK_Z_DIRECT_FORMALIZE__", encoding="utf-8")
    module = ModuleZDirectFormalize(
        model_client=StaticDirectClient('{"theorem_decl":"","plan":"bad"}'),
        prompt_path=prompt_path,
        lean_header="import PhysLean",
    )

    row = module.run(_sample())

    assert row.parse_ok is False
    assert row.error is not None
    assert "theorem_decl_missing" in row.error
