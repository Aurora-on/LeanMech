from __future__ import annotations

import re
from pathlib import Path

from mech_pipeline.model.base import ModelClient
from mech_pipeline.modules import ModuleA, ModuleB, ModuleD, ModuleE
from mech_pipeline.types import (
    CanonicalSample,
    CompileCheckResult,
    GroundingResult,
    ModelResponse,
    StatementCandidate,
)


class SpyModelClient(ModelClient):
    def __init__(self) -> None:
        self.model_id = "spy-model"
        self.supports_vision = False
        self.prompts: list[str] = []

    def generate_text(self, prompt: str, **kwargs) -> ModelResponse:
        self.prompts.append(prompt)
        if "__TASK_A_EXTRACT_IR__" in prompt:
            return ModelResponse(
                text=(
                    '{"objects":[],"known_quantities":[{"symbol":"m"}],'
                    '"unknown_target":{"symbol":"a","description":"acceleration"},'
                    '"units":[{"symbol":"a","unit":"m/s^2"}],"constraints":[],'
                    '"relations":["F = m * a"],"physical_laws":["NewtonSecondLaw"],'
                    '"assumptions":[],"diagram_information":[],"goal_statement":"solve a",'
                    '"coordinate_system":"x","reference_frame":"ground","simplifications":[],'
                    '"symbol_table":{"a":"acceleration"}}'
                )
            )
        if "__TASK_B_GENERATE_STATEMENTS__" in prompt:
            return ModelResponse(
                text=(
                    '{"candidates":['
                    '{"candidate_id":"c1","lean_header":"import PhysLean","theorem_decl":"theorem t1 (a : Real) : a = a","assumptions":[]},'
                    '{"candidate_id":"c2","lean_header":"import PhysLean","theorem_decl":"theorem t2 (a : Real) : a = a","assumptions":[]},'
                    '{"candidate_id":"c3","lean_header":"import PhysLean","theorem_decl":"theorem t3 (a : Real) : a = a","assumptions":[]},'
                    '{"candidate_id":"c4","lean_header":"import PhysLean","theorem_decl":"theorem t4 (a : Real) : a = a","assumptions":[]}'
                    "]}"
                )
            )
        if "__TASK_D_SEMANTIC_RANK__" in prompt:
            ids = re.findall(r'"candidate_id"\s*:\s*"([^"]+)"', prompt)
            unique_ids: list[str] = []
            for cid in ids:
                if cid not in unique_ids:
                    unique_ids.append(cid)
            if not unique_ids:
                unique_ids = ["c1"]
            rows = ",".join(
                (
                    '{"candidate_id":"%s","back_translation":"%s","semantic_score":0.8,'
                    '"semantic_pass":true,"reason":"ok"}'
                )
                % (cid, cid)
                for cid in unique_ids
            )
            return ModelResponse(text='{"results":[' + rows + "]}")
        if "__TASK_E_GENERATE_PROOF__" in prompt or "__TASK_E_REPAIR_PROOF__" in prompt:
            return ModelResponse(text='{"proof_body":"rfl","strategy":"direct","used_facts":["rfl"]}')
        return ModelResponse(text="{}")

    def generate_multimodal(self, prompt: str, images_b64: list[str], **kwargs) -> ModelResponse:
        self.prompts.append(prompt)
        return self.generate_text(prompt, **kwargs)


class FakeLeanRunner:
    def verify_proof(
        self,
        *,
        sample_id: str,
        candidate_id: str,
        lean_header: str,
        theorem_decl: str,
        proof_body: str,
        run_dir: Path,
    ) -> dict[str, object]:
        _ = (sample_id, candidate_id, lean_header, theorem_decl, proof_body, run_dir)
        return {
            "compile_pass": True,
            "strict_pass": True,
            "error_type": None,
            "stderr_digest": "",
            "log_path": None,
        }


def _write_prompt(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_prompt_rendering_does_not_leak_gold_answer(tmp_path: Path) -> None:
    secret = "SECRET_GOLD_ANSWER_DO_NOT_LEAK"
    client = SpyModelClient()

    prompt_a = _write_prompt(
        tmp_path / "A.txt",
        "__TASK_A_EXTRACT_IR__\n{{problem_text}}\n{{options_text}}\n{{image_description}}",
    )
    prompt_b = _write_prompt(
        tmp_path / "B.txt",
        "__TASK_B_GENERATE_STATEMENTS__\n{{problem_ir_json}}",
    )
    prompt_d = _write_prompt(
        tmp_path / "D.txt",
        "__TASK_D_SEMANTIC_RANK__\n{{problem_text}}\n{{problem_ir_json}}\n{{candidate_payload_json}}",
    )
    prompt_e_gen = _write_prompt(
        tmp_path / "E_gen.txt",
        "__TASK_E_GENERATE_PROOF__\n{{theorem_decl}}\n{{problem_ir_json}}",
    )
    prompt_e_repair = _write_prompt(
        tmp_path / "E_repair.txt",
        "__TASK_E_REPAIR_PROOF__\n{{theorem_decl}}\n{{problem_ir_json}}\n{{previous_proof}}\n{{previous_error}}",
    )

    sample = CanonicalSample(
        sample_id="s1",
        source="unit_test",
        problem_text=f"Given m and F, solve acceleration.\nAnswer: {secret}",
        options=[],
        gold_answer=secret,
    )

    module_a = ModuleA(client, "spy-model", prompt_a)
    grounding_a = module_a.run(sample)
    assert grounding_a.parse_ok
    assert client.prompts, "Module A should send one prompt"
    assert secret not in client.prompts[-1]

    grounding = GroundingResult(
        sample_id="s1",
        model_id="spy-model",
        problem_ir={
            **(grounding_a.problem_ir or {}),
            "not_allowed_key": secret,
        },
        parse_ok=True,
        raw_response="",
        error=None,
    )

    module_b = ModuleB(client, prompt_b)
    candidates = module_b.run(grounding)
    assert len(candidates) == 4
    assert secret not in client.prompts[-1]

    compile_rows = [
        CompileCheckResult(
            sample_id="s1",
            candidate_id=c.candidate_id,
            compile_pass=True,
            syntax_ok=True,
            elaboration_ok=True,
            error_type=None,
            stderr_digest="",
            log_path=None,
        )
        for c in candidates
    ]

    module_d = ModuleD(client, prompt_d, pass_threshold=0.6)
    _ = module_d.run(
        grounding=grounding,
        candidates=candidates,
        compile_checks=compile_rows,
        problem_text=f"Prompt text\nAnswer: {secret}",
    )
    assert secret not in client.prompts[-1]

    module_e = ModuleE(
        model_client=client,
        lean_runner=FakeLeanRunner(),
        prompt_generate_path=prompt_e_gen,
        prompt_repair_path=prompt_e_repair,
        max_attempts=1,
    )
    attempts, check = module_e.run(grounding=grounding, selected_candidate=candidates[0], run_dir=tmp_path)
    assert attempts
    assert check.proof_success is True
    assert secret not in client.prompts[-1]
