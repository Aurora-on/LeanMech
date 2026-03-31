from __future__ import annotations

import json
from pathlib import Path

import mech_pipeline.cli as cli
from mech_pipeline.cli import main
from mech_pipeline.types import (
    CompileCheckResult,
    GroundingResult,
    ProofCheckResult,
    SemanticRankResult,
    StatementCandidate,
)


def _write_archive(archive_root: Path) -> None:
    (archive_root / "output_description_part1").mkdir(parents=True, exist_ok=True)
    (archive_root / "output_description_part1" / "1-1.md").write_text(
        "A 1kg ball is pushed by a 1N force. Find its acceleration.",
        encoding="utf-8",
    )


def _write_config(tmp_path: Path, *, tag: str, extra_yaml: str = "") -> tuple[Path, Path]:
    archive_root = tmp_path / "archive"
    _write_archive(archive_root)
    config_path = tmp_path / f"{tag}.yaml"
    output_latest = tmp_path / "latest"
    runs_dir = tmp_path / "runs"
    config_path.write_text(
        f"""
dataset:
  source: local_archive
  limit: 1
  local_archive:
    root: "{archive_root.as_posix()}"
    mode: text_only
model:
  provider: mock
  model_id: mock-test
knowledge:
  enabled: false
lean:
  enabled: false
  preflight_enabled: false
statement:
  feedback_loop_enabled: true
  max_revision_rounds: 1
output:
  output_dir: "{output_latest.as_posix()}"
  runs_dir: "{runs_dir.as_posix()}"
  tag: "{tag}"
{extra_yaml}
""",
        encoding="utf-8",
    )
    return config_path, output_latest


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_cli_smoke_local_text(tmp_path: Path) -> None:
    config_path, output_latest = _write_config(tmp_path, tag="test-run")
    code = main(["run", "--config", str(config_path)])
    assert code == 0
    assert (output_latest / "metrics.json").exists()
    assert (output_latest / "analysis.md").exists()
    assert (output_latest / "sample_summary.jsonl").exists()
    assert (output_latest / "lean_exports" / "README.md").exists()
    assert (output_latest / "lean_exports" / "index.json").exists()
    exported = list((output_latest / "lean_exports" / "problems").glob("*.lean"))
    assert len(exported) == 1


def test_cli_exports_lean_workspace_files_when_mechlib_paths_exist(tmp_path: Path) -> None:
    mechlib_dir = tmp_path / "MechLib"
    physlean_dir = tmp_path / "PhysLean"
    (mechlib_dir / "lean-toolchain").parent.mkdir(parents=True, exist_ok=True)
    (mechlib_dir / "lean-toolchain").write_text("leanprover/lean4:v4.26.0\n", encoding="utf-8")
    (mechlib_dir / "lakefile.toml").write_text('name = "MechLib"\n', encoding="utf-8")
    (physlean_dir / ".lake" / "packages" / "mathlib").mkdir(parents=True, exist_ok=True)
    (physlean_dir / ".lake" / "packages" / "mathlib" / "lakefile.lean").write_text("-- mathlib\n", encoding="utf-8")
    (physlean_dir / ".lake" / "packages" / "aesop").mkdir(parents=True, exist_ok=True)
    (physlean_dir / ".lake" / "packages" / "aesop" / "lakefile.toml").write_text('name = "aesop"\n', encoding="utf-8")

    config_path, output_latest = _write_config(
        tmp_path,
        tag="test-lean-exports-workspace",
        extra_yaml=f"""
lean:
  enabled: false
  preflight_enabled: false
  physlean_dir: "{physlean_dir.as_posix()}"
  mechlib_dir: "{mechlib_dir.as_posix()}"
""".strip(),
    )
    code = main(["run", "--config", str(config_path)])
    assert code == 0

    export_root = output_latest / "lean_exports"
    assert (export_root / "lean-toolchain").exists()
    assert (export_root / "lakefile.toml").exists()
    assert (export_root / "lake-manifest.json").exists()
    assert (export_root / "RunArtifacts.lean").exists()

    manifest = json.loads((export_root / "lake-manifest.json").read_text(encoding="utf-8"))
    package_names = {pkg["name"] for pkg in manifest["packages"]}
    assert "MechLib" in package_names
    assert "mathlib" in package_names
    assert "aesop" in package_names
    assert "Open this `lean_exports/` folder as a Lean workspace." in (export_root / "README.md").read_text(
        encoding="utf-8"
    )


class _ForbiddenModuleE:
    def __init__(self, *args, **kwargs) -> None:
        _ = (args, kwargs)

    def run(self, *args, **kwargs):
        _ = (args, kwargs)
        raise AssertionError("ModuleE.run should be skipped when semantic ranking fails")


def test_cli_skips_proof_stage_when_semantic_fails(tmp_path: Path, monkeypatch) -> None:
    config_path, output_latest = _write_config(tmp_path, tag="test-skip-proof")

    class StubModuleA:
        def __init__(self, *args, **kwargs) -> None:
            _ = (args, kwargs)

        def run(self, sample) -> GroundingResult:
            return GroundingResult(
                sample_id=sample.sample_id,
                model_id="stub-a",
                problem_ir={"unknown_target": {"symbol": "a", "description": "acceleration"}},
                parse_ok=True,
                raw_response="",
                error=None,
            )

    class StubModuleB:
        def __init__(self, *args, **kwargs) -> None:
            _ = (args, kwargs)

        def run(self, grounding: GroundingResult, **kwargs) -> list[StatementCandidate]:
            round_index = int(kwargs.get("round_index", 0))
            return [
                StatementCandidate(
                    sample_id=grounding.sample_id,
                    candidate_id=f"c{i}",
                    lean_header="import PhysLean",
                    theorem_decl=f"theorem bad_round_{round_index}_{i} (a : Real) : a = a",
                    round_index=round_index,
                    source_round_index=(round_index - 1) if round_index > 0 else None,
                )
                for i in range(1, 5)
            ]

    class StubModuleC:
        def __init__(self, *args, **kwargs) -> None:
            _ = (args, kwargs)

        def run(self, sample_id: str, candidates: list[StatementCandidate], run_dir: Path) -> list[CompileCheckResult]:
            _ = run_dir
            return [
                CompileCheckResult(
                    sample_id=sample_id,
                    candidate_id=candidate.candidate_id,
                    compile_pass=candidate.candidate_id == "c1",
                    syntax_ok=candidate.candidate_id == "c1",
                    elaboration_ok=candidate.candidate_id == "c1",
                    error_type=None if candidate.candidate_id == "c1" else "missing_import_or_namespace",
                    stderr_digest="" if candidate.candidate_id == "c1" else "unknown constant",
                    log_path=None,
                )
                for candidate in candidates
            ]

    class StubModuleD:
        def __init__(self, *args, **kwargs) -> None:
            _ = (args, kwargs)

        def run(self, grounding: GroundingResult, candidates: list[StatementCandidate], compile_checks: list[CompileCheckResult], **kwargs) -> SemanticRankResult:
            _ = (grounding, compile_checks, kwargs)
            return SemanticRankResult(
                sample_id=candidates[0].sample_id,
                selected_candidate_id="c1",
                selected_theorem_decl=candidates[0].theorem_decl,
                semantic_pass=False,
                ranking=[
                    {
                        "candidate_id": "c1",
                        "semantic_score": 0.1,
                        "semantic_pass": False,
                        "semantic_reason": "trivial goal",
                        "back_translation_text": "tautology",
                        "hard_gate_reasons": ["trivial_goal"],
                        "semantic_rank_score": 0.1,
                    }
                ],
                error="semantic_drift",
            )

    monkeypatch.setattr(cli, "ModuleA", StubModuleA)
    monkeypatch.setattr(cli, "ModuleB", StubModuleB)
    monkeypatch.setattr(cli, "ModuleC", StubModuleC)
    monkeypatch.setattr(cli, "ModuleD", StubModuleD)
    monkeypatch.setattr(cli, "ModuleE", _ForbiddenModuleE)
    code = cli.main(["run", "--config", str(config_path)])
    assert code == 0

    proof_rows = _read_jsonl(output_latest / "proof_checks.jsonl")
    assert len(proof_rows) == 1
    assert proof_rows[0]["error_type"] == "proof_skipped_due_to_semantic_fail"
    assert proof_rows[0]["round_index"] == 1


def _install_feedback_loop_stubs(monkeypatch, *, trigger: str, call_log: list[dict[str, object]]) -> None:
    class StubModuleA:
        def __init__(self, *args, **kwargs) -> None:
            _ = (args, kwargs)

        def run(self, sample) -> GroundingResult:
            return GroundingResult(
                sample_id=sample.sample_id,
                model_id="stub-a",
                problem_ir={
                    "unknown_target": {"symbol": "a", "description": "acceleration"},
                    "known_quantities": [{"symbol": "F"}, {"symbol": "m"}],
                    "physical_laws": ["NewtonSecondLaw"],
                    "assumptions": ["inertial frame"],
                },
                parse_ok=True,
                raw_response="",
                error=None,
            )

    class StubModuleB:
        def __init__(self, *args, **kwargs) -> None:
            _ = (args, kwargs)

        def run(
            self,
            grounding: GroundingResult,
            mechlib_context: str = "(none)",
            revision_feedback: str = "(none)",
            round_index: int = 0,
            previous_candidates: list[StatementCandidate] | None = None,
        ) -> list[StatementCandidate]:
            call_log.append(
                {
                    "round_index": round_index,
                    "revision_feedback": revision_feedback,
                    "previous_candidates_count": len(previous_candidates or []),
                    "mechlib_context": mechlib_context,
                }
            )
            return [
                StatementCandidate(
                    sample_id=grounding.sample_id,
                    candidate_id=f"c{i}",
                    lean_header="import PhysLean",
                    theorem_decl=f"theorem round_{round_index}_candidate_{i} (a F m : Real) : a = F / m",
                    assumptions=[],
                    plan=f"round {round_index} plan {i}",
                    round_index=round_index,
                    source_round_index=(round_index - 1) if round_index > 0 else None,
                )
                for i in range(1, 5)
            ]

    class StubModuleC:
        def __init__(self, *args, **kwargs) -> None:
            _ = (args, kwargs)

        def run(self, sample_id: str, candidates: list[StatementCandidate], run_dir: Path) -> list[CompileCheckResult]:
            _ = run_dir
            round_index = candidates[0].round_index
            rows: list[CompileCheckResult] = []
            for idx, candidate in enumerate(candidates, start=1):
                if round_index == 0 and trigger == "no_compile_pass":
                    compile_pass = False
                    error_type = "missing_import_or_namespace"
                    stderr = f"round0 candidate{idx} unknown constant"
                elif round_index == 0:
                    compile_pass = idx == 1
                    error_type = None if compile_pass else "missing_import_or_namespace"
                    stderr = "" if compile_pass else f"round0 candidate{idx} unknown constant"
                else:
                    compile_pass = True
                    error_type = None
                    stderr = ""
                rows.append(
                    CompileCheckResult(
                        sample_id=sample_id,
                        candidate_id=candidate.candidate_id,
                        compile_pass=compile_pass,
                        syntax_ok=compile_pass,
                        elaboration_ok=compile_pass,
                        error_type=error_type,
                        stderr_digest=stderr,
                        log_path=None,
                    )
                )
            return rows

    class StubModuleD:
        def __init__(self, *args, **kwargs) -> None:
            _ = (args, kwargs)

        def run(
            self,
            grounding: GroundingResult,
            candidates: list[StatementCandidate],
            compile_checks: list[CompileCheckResult],
            problem_text: str | None = None,
            mechlib_context: str = "(none)",
        ) -> SemanticRankResult:
            _ = (grounding, problem_text, mechlib_context)
            round_index = candidates[0].round_index
            if round_index == 0 and trigger == "no_compile_pass":
                return SemanticRankResult(
                    sample_id=candidates[0].sample_id,
                    selected_candidate_id=None,
                    selected_theorem_decl=None,
                    semantic_pass=False,
                    ranking=[],
                    error="semantic_drift",
                )
            if round_index == 0:
                return SemanticRankResult(
                    sample_id=candidates[0].sample_id,
                    selected_candidate_id="c1",
                    selected_theorem_decl=candidates[0].theorem_decl,
                    semantic_pass=False,
                    ranking=[
                        {
                            "candidate_id": "c1",
                            "semantic_score": 0.25,
                            "semantic_pass": False,
                            "semantic_reason": "target mismatch",
                            "back_translation_text": "wrong target",
                            "hard_gate_reasons": ["target_mismatch"],
                            "semantic_rank_score": 0.25,
                        }
                    ],
                    error="semantic_drift",
                )
            return SemanticRankResult(
                sample_id=candidates[0].sample_id,
                selected_candidate_id="c2",
                selected_theorem_decl=candidates[1].theorem_decl,
                semantic_pass=True,
                ranking=[
                    {
                        "candidate_id": "c2",
                        "semantic_score": 0.92,
                        "semantic_pass": True,
                        "semantic_reason": "aligned",
                        "back_translation_text": "correct acceleration law",
                        "hard_gate_reasons": [],
                        "semantic_rank_score": 0.92,
                    }
                ],
                selected_backend="physlean",
                error=None,
            )

    class StubModuleE:
        def __init__(self, *args, **kwargs) -> None:
            _ = (args, kwargs)

        def run(self, grounding: GroundingResult, selected_candidate: StatementCandidate | None, run_dir: Path, mechlib_context: str = "(none)"):
            _ = (grounding, selected_candidate, run_dir, mechlib_context)
            return [], ProofCheckResult(
                sample_id=grounding.sample_id,
                proof_success=True,
                attempts_used=1,
                selected_candidate_id=selected_candidate.candidate_id if selected_candidate else None,
                error_type=None,
                final_log_path=None,
            )

    monkeypatch.setattr(cli, "ModuleA", StubModuleA)
    monkeypatch.setattr(cli, "ModuleB", StubModuleB)
    monkeypatch.setattr(cli, "ModuleC", StubModuleC)
    monkeypatch.setattr(cli, "ModuleD", StubModuleD)
    monkeypatch.setattr(cli, "ModuleE", StubModuleE)


def test_cli_feedback_loop_retries_after_semantic_fail(tmp_path: Path, monkeypatch) -> None:
    config_path, output_latest = _write_config(tmp_path, tag="test-feedback-loop-semantic")
    call_log: list[dict[str, object]] = []
    _install_feedback_loop_stubs(monkeypatch, trigger="semantic_fail", call_log=call_log)

    code = cli.main(["run", "--config", str(config_path)])
    assert code == 0
    assert len(call_log) == 2
    assert call_log[0]["round_index"] == 0
    assert call_log[1]["round_index"] == 1
    assert call_log[1]["previous_candidates_count"] == 4
    assert '"retry_reason": "semantic_fail"' in str(call_log[1]["revision_feedback"])
    assert "target mismatch" in str(call_log[1]["revision_feedback"])
    assert "unknown constant" in str(call_log[1]["revision_feedback"])

    statement_rows = _read_jsonl(output_latest / "statement_candidates.jsonl")
    semantic_rows = _read_jsonl(output_latest / "semantic_rank.jsonl")
    proof_rows = _read_jsonl(output_latest / "proof_checks.jsonl")
    summary_rows = _read_jsonl(output_latest / "sample_summary.jsonl")
    metrics = json.loads((output_latest / "metrics.json").read_text(encoding="utf-8"))

    assert {row["round_index"] for row in statement_rows} == {0, 1}
    assert len(statement_rows) == 8
    assert len(semantic_rows) == 2
    assert semantic_rows[0]["retry_triggered"] is True
    assert semantic_rows[0]["retry_reason"] == "semantic_fail"
    assert semantic_rows[0]["retry_feedback_summary"]
    assert semantic_rows[1]["round_index"] == 1
    assert proof_rows[0]["round_index"] == 1
    assert summary_rows[0]["feedback_loop_used"] is True
    assert summary_rows[0]["final_round_index"] == 1
    assert metrics["lean_compile_success_rate"] == 1.0
    assert metrics["semantic_consistency_pass_rate"] == 1.0
    assert metrics["feedback_loop_used_rate"] == 1.0


def test_cli_feedback_loop_retries_after_no_compile_pass(tmp_path: Path, monkeypatch) -> None:
    config_path, output_latest = _write_config(tmp_path, tag="test-feedback-loop-compile")
    call_log: list[dict[str, object]] = []
    _install_feedback_loop_stubs(monkeypatch, trigger="no_compile_pass", call_log=call_log)

    code = cli.main(["run", "--config", str(config_path)])
    assert code == 0
    assert len(call_log) == 2
    assert '"retry_reason": "no_compile_pass"' in str(call_log[1]["revision_feedback"])
    assert "semantic_not_evaluated_due_to_compile_fail" in str(call_log[1]["revision_feedback"])

    semantic_rows = _read_jsonl(output_latest / "semantic_rank.jsonl")
    summary_rows = _read_jsonl(output_latest / "sample_summary.jsonl")
    metrics = json.loads((output_latest / "metrics.json").read_text(encoding="utf-8"))

    assert semantic_rows[0]["retry_triggered"] is True
    assert semantic_rows[0]["retry_reason"] == "no_compile_pass"
    assert summary_rows[0]["feedback_loop_used"] is True
    assert summary_rows[0]["final_round_index"] == 1
    assert metrics["lean_compile_success_rate"] == 1.0
