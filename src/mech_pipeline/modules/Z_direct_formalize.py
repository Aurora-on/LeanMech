from __future__ import annotations

from pathlib import Path

from mech_pipeline.llm_schemas import DirectFormalizationPayload
from mech_pipeline.prompting import load_template, render_template
from mech_pipeline.response_parser import ResponseParseError, parse_json_model
from mech_pipeline.types import CanonicalSample, DirectFormalizationResult
from mech_pipeline.utils import normalize_lean_text

DEFAULT_PROMPT = """__TASK_Z_DIRECT_FORMALIZE__
You are a direct Lean4 autoformalization baseline for mechanics problems.
You must convert the problem directly into one Lean theorem in a single response.

Output JSON only:
{
  "theorem_decl": "theorem ... : ...",
  "plan": "...",
  "used_facts": ["..."]
}

Rules:
1. Do not output any import statements or Lean header.
2. Do not output multiple theorems.
3. Do not output `sorry`, `admit`, or `axiom`.
4. The theorem must be a single valid Lean theorem declaration.
5. Do not output any proof.
6. Use direct algebraic formalization over binders when uncertain.
7. Prefer `Real`-based statements unless the problem clearly requires another type.
8. Keep the theorem semantically aligned with the original problem. Do not replace the problem with a trivial theorem.

Problem name:
{{sample_name}}

Problem text:
{{problem_text}}

Options:
{{options_text}}

Fixed Lean environment:
The evaluator will prepend the following header automatically:
import PhysLean
open PhysLean
"""


def _normalize_text(value: str) -> str:
    return normalize_lean_text(str(value or "").strip())


class ModuleZDirectFormalize:
    def __init__(self, model_client, prompt_path: Path, lean_header: str) -> None:
        self.model_client = model_client
        self.prompt = load_template(prompt_path, DEFAULT_PROMPT)
        self.lean_header = normalize_lean_text(lean_header).strip()

    def run(self, sample: CanonicalSample) -> DirectFormalizationResult:
        options_text = "\n".join(sample.options) if sample.options else "(none)"
        prompt = render_template(
            self.prompt,
            {
                "sample_name": str(sample.meta.get("name") or sample.sample_id),
                "problem_text": sample.problem_text,
                "options_text": options_text,
            },
        )

        raw = ""
        try:
            resp = self.model_client.generate_text(prompt)
            raw = resp.text
        except Exception as exc:
            return DirectFormalizationResult(
                sample_id=sample.sample_id,
                lean_header=self.lean_header,
                theorem_decl="",
                proof_body="",
                parse_ok=False,
                raw_response=raw,
                error=f"{type(exc).__name__}: {exc}",
            )

        try:
            parsed = parse_json_model(raw, DirectFormalizationPayload)
        except ResponseParseError as exc:
            return DirectFormalizationResult(
                sample_id=sample.sample_id,
                lean_header=self.lean_header,
                theorem_decl="",
                proof_body="",
                parse_ok=False,
                raw_response=raw,
                error=f"direct_generation_parse_failed: {exc}",
            )

        theorem_decl = _normalize_text(parsed.theorem_decl)
        proof_body = _normalize_text(parsed.proof_body or "")
        if not theorem_decl:
            return DirectFormalizationResult(
                sample_id=sample.sample_id,
                lean_header=self.lean_header,
                theorem_decl=theorem_decl,
                proof_body="",
                parse_ok=False,
                raw_response=raw,
                error="direct_generation_parse_failed: theorem_decl_missing",
                plan=_normalize_text(parsed.plan or "") or None,
                used_facts=[_normalize_text(x) for x in parsed.used_facts if _normalize_text(x)],
            )

        return DirectFormalizationResult(
            sample_id=sample.sample_id,
            lean_header=self.lean_header,
            theorem_decl=theorem_decl,
            proof_body=proof_body,
            parse_ok=True,
            raw_response=raw,
            error=None,
            plan=_normalize_text(parsed.plan or "") or None,
            used_facts=[_normalize_text(x) for x in parsed.used_facts if _normalize_text(x)],
        )
