from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import mech_pipeline.cli as cli
import pytest
from mech_pipeline.cli import main
from mech_pipeline.types import (
    CompileCheckResult,
    GroundingResult,
    ProofCheckResult,
    SemanticRankResult,
    StatementCandidate,
)


def _write_archive(archive_root: Path, sample_count: int = 1) -> None:
    (archive_root / "output_description_part1").mkdir(parents=True, exist_ok=True)
    for idx in range(1, sample_count + 1):
        (archive_root / "output_description_part1" / f"1-{idx}.md").write_text(
            f"A {idx}kg ball is pushed by a {idx}N force. Find its acceleration.",
            encoding="utf-8",
        )


def _write_config(
    tmp_path: Path,
    *,
    tag: str,
    extra_yaml: str = "",
    limit: int = 1,
    sample_count: int = 1,
) -> tuple[Path, Path]:
    archive_root = tmp_path / "archive"
    _write_archive(archive_root, sample_count=sample_count)
    config_path = tmp_path / f"{tag}.yaml"
    output_latest = tmp_path / "latest"
    runs_dir = tmp_path / "runs"
    config_path.write_text(
        f"""
dataset:
  source: local_archive
  limit: {limit}
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


def test_revision_feedback_includes_compile_and_semantic_details() -> None:
    candidates = [
        StatementCandidate(
            sample_id="s1",
            candidate_id="c1",
            lean_header="import MechLib",
            theorem_decl="theorem c1 : True",
            plan="bad theorem",
        )
    ]
    compile_rows = [
        CompileCheckResult(
            sample_id="s1",
            candidate_id="c1",
            compile_pass=False,
            syntax_ok=True,
            elaboration_ok=False,
            error_type="elaboration_failure",
            stderr_digest="Function expected at averageVelocity",
            log_path=None,
            sub_error_type="wrong_api_shape",
            failure_tags=["wrong_api_shape"],
            failure_summary="Applied averageVelocity with the wrong function shape.",
            stderr_excerpt="Function expected at averageVelocity",
            error_line=11,
            error_message="Function expected at",
            error_snippet="Function expected at averageVelocity",
            failure_details={},
        )
    ]
    semantic = SemanticRankResult(
        sample_id="s1",
        selected_candidate_id="c1",
        selected_theorem_decl="theorem c1 : True",
        semantic_pass=False,
        ranking=[
            {
                "candidate_id": "c1",
                "semantic_score": 0.2,
                "semantic_pass": False,
                "sub_error_type": "wrong_target",
                "failure_tags": ["wrong_target"],
                "failure_summary": "The theorem solves the wrong target quantity.",
                "semantic_reason": "The target should be acceleration, not displacement.",
                "back_translation_text": "This theorem states a displacement relation.",
                "mismatch_fields": ["unknown_target"],
                "missing_or_incorrect_translations": ["The problem asks for acceleration."],
                "suggested_fix_direction": "Restate the conclusion so it solves for acceleration.",
                "hard_gate_reasons": ["target_mismatch"],
                "semantic_rank_score": 0.2,
            }
        ],
        error="semantic_drift",
    )

    feedback = json.loads(
        cli._build_revision_feedback(
            retry_reason="semantic_fail",
            candidates=candidates,
            compile_results=compile_rows,
            semantic=semantic,
        )
    )

    assert feedback["retry_reason"] == "semantic_fail"
    row = feedback["candidates"][0]
    assert row["sub_error_type"] == "wrong_api_shape"
    assert row["failure_summary"] == "Applied averageVelocity with the wrong function shape."
    assert row["semantic_sub_error_type"] == "wrong_target"
    assert row["mismatch_fields"] == ["unknown_target"]
    assert row["missing_or_incorrect_translations"] == ["The problem asks for acceleration."]
    assert row["suggested_fix_direction"] == "Restate the conclusion so it solves for acceleration."


def test_cli_smoke_local_text(tmp_path: Path, capsys) -> None:
    config_path, output_latest = _write_config(tmp_path, tag="test-run")
    code = main(["run", "--config", str(config_path)])
    captured = capsys.readouterr()
    assert code == 0
    assert (output_latest / "metrics.json").exists()
    assert (output_latest / "analysis.md").exists()
    assert (output_latest / "sample_summary.jsonl").exists()
    assert (output_latest / "lean_exports" / "README.md").exists()
    assert (output_latest / "lean_exports" / "index.json").exists()
    exported = list((output_latest / "lean_exports" / "problems").glob("*.lean"))
    assert len(exported) == 1
    assert "progress: 0/1 completed, sample_concurrency=1" in captured.out
    assert "progress: 1/1 completed, sample=archive-1-1" in captured.out
    assert "progress: 1/1 completed" in captured.out


def test_cli_rejects_sample_concurrency_above_upper_bound(tmp_path: Path) -> None:
    config_path, _output_latest = _write_config(tmp_path, tag="test-sample-concurrency-too-high")
    with pytest.raises(ValueError, match=r"runtime.sample_concurrency must be <= 10"):
        main(["run", "--config", str(config_path), "--sample-concurrency", "11"])


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
    lakefile_text = (export_root / "lakefile.toml").read_text(encoding="utf-8")

    manifest = json.loads((export_root / "lake-manifest.json").read_text(encoding="utf-8"))
    package_names = {pkg["name"] for pkg in manifest["packages"]}
    assert "MechLib" in package_names
    assert "mathlib" in package_names
    assert "aesop" in package_names
    assert 'name = "mathlib"' in lakefile_text
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


def test_cli_accepts_fewer_than_four_statement_candidates_when_they_are_usable(tmp_path: Path, monkeypatch) -> None:
    config_path, output_latest = _write_config(tmp_path, tag="test-single-usable-candidate")

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
                    candidate_id="c1",
                    lean_header="import PhysLean",
                    theorem_decl="theorem usable_candidate (F m a : Real) (hm : m ≠ 0) (h : F = m * a) : a = F / m",
                    round_index=round_index,
                    source_round_index=(round_index - 1) if round_index > 0 else None,
                )
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
                    compile_pass=True,
                    syntax_ok=True,
                    elaboration_ok=True,
                    error_type=None,
                    stderr_digest="",
                    log_path=None,
                )
                for candidate in candidates
            ]

    class StubModuleD:
        def __init__(self, *args, **kwargs) -> None:
            _ = (args, kwargs)

        def run(
            self,
            grounding: GroundingResult,
            candidates: list[StatementCandidate],
            compile_checks: list[CompileCheckResult],
            **kwargs,
        ) -> SemanticRankResult:
            _ = (grounding, compile_checks, kwargs)
            return SemanticRankResult(
                sample_id=candidates[0].sample_id,
                selected_candidate_id="c1",
                selected_theorem_decl=candidates[0].theorem_decl,
                semantic_pass=True,
                ranking=[
                    {
                        "candidate_id": "c1",
                        "semantic_score": 0.95,
                        "semantic_pass": True,
                        "semantic_reason": "aligned",
                        "back_translation_text": "usable statement",
                        "hard_gate_reasons": [],
                        "semantic_rank_score": 0.95,
                    }
                ],
                error=None,
            )

    class StubModuleE:
        def __init__(self, *args, **kwargs) -> None:
            _ = (args, kwargs)

        def run(self, grounding: GroundingResult, selected_candidate: StatementCandidate | None, run_dir: Path, **kwargs):
            _ = (grounding, run_dir, kwargs)
            assert selected_candidate is not None
            return [], ProofCheckResult(
                sample_id=selected_candidate.sample_id,
                proof_success=True,
                attempts_used=1,
                selected_candidate_id=selected_candidate.candidate_id,
                error_type=None,
                final_log_path=None,
            )

    monkeypatch.setattr(cli, "ModuleA", StubModuleA)
    monkeypatch.setattr(cli, "ModuleB", StubModuleB)
    monkeypatch.setattr(cli, "ModuleC", StubModuleC)
    monkeypatch.setattr(cli, "ModuleD", StubModuleD)
    monkeypatch.setattr(cli, "ModuleE", StubModuleE)

    code = cli.main(["run", "--config", str(config_path)])
    assert code == 0

    summary_rows = _read_jsonl(output_latest / "sample_summary.jsonl")
    assert summary_rows[0]["statement_generation_ok"] is True
    assert summary_rows[0]["end_to_end_ok"] is True


def test_cli_runs_samples_concurrently_and_preserves_output_order(tmp_path: Path, monkeypatch, capsys) -> None:
    config_path, output_latest = _write_config(
        tmp_path,
        tag="test-sample-concurrency",
        limit=2,
        sample_count=2,
    )
    barrier = threading.Barrier(2, timeout=2)
    thread_names: set[str] = set()
    lock = threading.Lock()
    call_log: list[tuple[str, int]] = []

    class StubModuleA:
        def __init__(self, *args, **kwargs) -> None:
            _ = (args, kwargs)

        def run(self, sample) -> GroundingResult:
            with lock:
                thread_names.add(threading.current_thread().name)
            barrier.wait()
            if sample.sample_id.endswith("1-1"):
                time.sleep(0.05)
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

        def run(self, grounding: GroundingResult, **kwargs) -> list[StatementCandidate]:
            round_index = int(kwargs.get("round_index", 0))
            with lock:
                call_log.append((grounding.sample_id, round_index))
            return [
                StatementCandidate(
                    sample_id=grounding.sample_id,
                    candidate_id=f"c{i}",
                    lean_header="import PhysLean",
                    theorem_decl=(
                        f"theorem {grounding.sample_id.replace('-', '_')}_round_{round_index}_candidate_{i} "
                        "(a F m : Real) (hm : m != 0) (h : F = m * a) : a = F / m"
                    ),
                    assumptions=[],
                    plan=f"{grounding.sample_id} round {round_index} plan {i}",
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
                    compile_pass=True,
                    syntax_ok=True,
                    elaboration_ok=True,
                    error_type=None,
                    stderr_digest="",
                    log_path=None,
                )
                for candidate in candidates
            ]

    class StubModuleD:
        def __init__(self, *args, **kwargs) -> None:
            _ = (args, kwargs)

        def run(self, grounding: GroundingResult, candidates: list[StatementCandidate], compile_checks: list[CompileCheckResult], **kwargs) -> SemanticRankResult:
            _ = (compile_checks, kwargs)
            round_index = candidates[0].round_index
            if grounding.sample_id.endswith("1-1") and round_index == 0:
                return SemanticRankResult(
                    sample_id=grounding.sample_id,
                    selected_candidate_id="c1",
                    selected_theorem_decl=candidates[0].theorem_decl,
                    semantic_pass=False,
                    ranking=[
                        {
                            "candidate_id": "c1",
                            "semantic_score": 0.2,
                            "semantic_pass": False,
                            "semantic_reason": "needs retry",
                            "back_translation_text": "retry this sample only",
                            "hard_gate_reasons": ["target_mismatch"],
                            "semantic_rank_score": 0.2,
                        }
                    ],
                    error="semantic_drift",
                )
            return SemanticRankResult(
                sample_id=grounding.sample_id,
                selected_candidate_id="c2",
                selected_theorem_decl=candidates[1].theorem_decl,
                semantic_pass=True,
                ranking=[
                    {
                        "candidate_id": "c2",
                        "semantic_score": 0.95,
                        "semantic_pass": True,
                        "semantic_reason": "aligned",
                        "back_translation_text": "correct acceleration law",
                        "hard_gate_reasons": [],
                        "semantic_rank_score": 0.95,
                    }
                ],
                selected_backend="physlean",
                error=None,
            )

    class StubModuleE:
        def __init__(self, *args, **kwargs) -> None:
            _ = (args, kwargs)

        def run(self, grounding: GroundingResult, selected_candidate: StatementCandidate | None, run_dir: Path, mechlib_context: str = "(none)"):
            _ = (run_dir, mechlib_context)
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

    code = cli.main(["run", "--config", str(config_path), "--sample-concurrency", "2"])
    captured = capsys.readouterr()
    assert code == 0
    assert len(thread_names) == 2

    summary_rows = _read_jsonl(output_latest / "sample_summary.jsonl")
    statement_rows = _read_jsonl(output_latest / "statement_candidates.jsonl")
    proof_rows = _read_jsonl(output_latest / "proof_checks.jsonl")
    readme_text = (output_latest / "README.md").read_text(encoding="utf-8")

    assert [row["sample_id"] for row in summary_rows] == ["archive-1-1", "archive-1-2"]
    assert summary_rows[0]["feedback_loop_used"] is True
    assert summary_rows[0]["final_round_index"] == 1
    assert summary_rows[1]["feedback_loop_used"] is False
    assert summary_rows[1]["final_round_index"] == 0
    assert len(statement_rows) == 12
    assert sum(1 for row in statement_rows if row["sample_id"] == "archive-1-1") == 8
    assert sum(1 for row in statement_rows if row["sample_id"] == "archive-1-2") == 4
    assert [row["round_index"] for row in proof_rows] == [1, 0]
    assert "- sample_concurrency: 2" in readme_text
    assert "**MechLib Retrieval**" not in readme_text
    assert "log=" not in readme_text
    assert "final_log_path" not in readme_text
    assert call_log.count(("archive-1-1", 0)) == 1
    assert call_log.count(("archive-1-1", 1)) == 1
    assert call_log.count(("archive-1-2", 0)) == 1
    assert "progress: 0/2 completed, sample_concurrency=2" in captured.out
    first_done = captured.out.index("progress: 1/2 completed, sample=archive-1-2")
    second_done = captured.out.index("progress: 2/2 completed, sample=archive-1-1")
    assert first_done < second_done
    assert "progress: 2/2 completed" in captured.out


def test_cli_reports_progress_before_failure(tmp_path: Path, monkeypatch, capsys) -> None:
    config_path, _output_latest = _write_config(
        tmp_path,
        tag="test-progress-failure",
        limit=2,
        sample_count=2,
    )

    class StubModuleA:
        def __init__(self, *args, **kwargs) -> None:
            _ = (args, kwargs)

        def run(self, sample) -> GroundingResult:
            if sample.sample_id.endswith("1-2"):
                time.sleep(0.05)
                raise RuntimeError("boom")
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
                    theorem_decl=f"theorem ok_{round_index}_{i} (a : Real) : a = a",
                    round_index=round_index,
                    source_round_index=(round_index - 1) if round_index > 0 else None,
                )
                for i in range(1, 5)
            ]

    class StubModuleC:
        def __init__(self, *args, **kwargs) -> None:
            _ = (args, kwargs)

        def run(self, sample_id: str, candidates: list[StatementCandidate], run_dir: Path) -> list[CompileCheckResult]:
            _ = (sample_id, run_dir)
            return [
                CompileCheckResult(
                    sample_id=candidate.sample_id,
                    candidate_id=candidate.candidate_id,
                    compile_pass=True,
                    syntax_ok=True,
                    elaboration_ok=True,
                    error_type=None,
                    stderr_digest="",
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
                semantic_pass=True,
                ranking=[
                    {
                        "candidate_id": "c1",
                        "semantic_score": 0.9,
                        "semantic_pass": True,
                        "semantic_reason": "aligned",
                        "back_translation_text": "aligned",
                        "hard_gate_reasons": [],
                        "semantic_rank_score": 0.9,
                    }
                ],
                error=None,
            )

    class StubModuleE:
        def __init__(self, *args, **kwargs) -> None:
            _ = (args, kwargs)

        def run(self, grounding: GroundingResult, selected_candidate: StatementCandidate | None, run_dir: Path, mechlib_context: str = "(none)"):
            _ = (run_dir, mechlib_context)
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

    with pytest.raises(RuntimeError, match="boom"):
        cli.main(["run", "--config", str(config_path), "--sample-concurrency", "2"])
    captured = capsys.readouterr()
    assert "progress: 1/2 completed, sample=archive-1-1" in captured.out
    assert "progress: failed after 1/2 completed, sample=archive-1-2" in captured.out


def test_cli_writes_environment_health_into_outputs(tmp_path: Path, monkeypatch) -> None:
    config_path, output_latest = _write_config(
        tmp_path,
        tag="test-environment-health",
        extra_yaml="""
lean:
  enabled: true
  preflight_enabled: true
""".strip(),
    )

    class StubRunner:
        def preflight_details(self) -> dict[str, object]:
            return {
                "ok": True,
                "error_type": None,
                "message": "ok: physlean+mechlib",
                "environment_health": "dirty_packages",
                "environment_warnings": ["warning: batteries: repository 'X' has local changes"],
            }

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
                    candidate_id="c1",
                    lean_header="import PhysLean",
                    theorem_decl="theorem ok (F m a : Real) : a = F / m",
                    round_index=round_index,
                )
            ]

    class StubModuleC:
        def __init__(self, *args, **kwargs) -> None:
            _ = (args, kwargs)

        def run(self, sample_id: str, candidates: list[StatementCandidate], run_dir: Path) -> list[CompileCheckResult]:
            _ = (sample_id, candidates, run_dir)
            return [
                CompileCheckResult(
                    sample_id="archive-1-1",
                    candidate_id="c1",
                    compile_pass=True,
                    syntax_ok=True,
                    elaboration_ok=True,
                    error_type=None,
                    stderr_digest="",
                    log_path=None,
                )
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
                semantic_pass=True,
                ranking=[{"candidate_id": "c1", "semantic_score": 0.9, "semantic_pass": True, "semantic_reason": "aligned", "back_translation_text": "aligned", "hard_gate_reasons": [], "semantic_rank_score": 0.9}],
                error=None,
            )

    class StubModuleE:
        def __init__(self, *args, **kwargs) -> None:
            _ = (args, kwargs)

        def run(self, grounding: GroundingResult, selected_candidate: StatementCandidate | None, run_dir: Path, mechlib_context: str = "(none)"):
            _ = (run_dir, mechlib_context)
            return [], ProofCheckResult(
                sample_id=grounding.sample_id,
                proof_success=True,
                attempts_used=1,
                selected_candidate_id=selected_candidate.candidate_id if selected_candidate else None,
                error_type=None,
                final_log_path=None,
            )

    monkeypatch.setattr(cli, "_build_lean_runner", lambda cfg: StubRunner())
    monkeypatch.setattr(cli, "_build_worker_modules", lambda cfg, prompt_dir: (StubModuleA(), StubModuleB(), StubModuleC(), StubModuleD(), StubModuleE()))

    code = cli.main(["run", "--config", str(config_path)])
    assert code == 0

    readme_text = (output_latest / "README.md").read_text(encoding="utf-8")
    analysis_text = (output_latest / "analysis.md").read_text(encoding="utf-8")
    config_payload = json.loads((output_latest / "config.json").read_text(encoding="utf-8"))

    assert "- environment_health: dirty_packages" in readme_text
    assert "## Runtime Environment" in analysis_text
    assert "- environment_health: dirty_packages" in analysis_text
    assert config_payload["preflight"]["environment_health"] == "dirty_packages"


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


def test_cli_feedback_loop_honors_two_revision_rounds(tmp_path: Path, monkeypatch) -> None:
    config_path, output_latest = _write_config(
        tmp_path,
        tag="test-feedback-loop-two-rounds",
        extra_yaml="""
statement:
  feedback_loop_enabled: true
  max_revision_rounds: 2
""".strip(),
    )
    call_log: list[dict[str, object]] = []

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
            _ = (sample_id, run_dir)
            return [
                CompileCheckResult(
                    sample_id=candidate.sample_id,
                    candidate_id=candidate.candidate_id,
                    compile_pass=True,
                    syntax_ok=True,
                    elaboration_ok=True,
                    error_type=None,
                    stderr_digest="",
                    log_path=None,
                )
                for candidate in candidates
            ]

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
            _ = (grounding, compile_checks, problem_text, mechlib_context)
            round_index = candidates[0].round_index
            if round_index < 2:
                return SemanticRankResult(
                    sample_id=candidates[0].sample_id,
                    selected_candidate_id="c1",
                    selected_theorem_decl=candidates[0].theorem_decl,
                    semantic_pass=False,
                    ranking=[
                        {
                            "candidate_id": "c1",
                            "semantic_score": 0.3,
                            "semantic_pass": False,
                            "semantic_reason": f"round {round_index} still wrong target",
                            "back_translation_text": "wrong target",
                            "hard_gate_reasons": ["target_mismatch"],
                            "semantic_rank_score": 0.3,
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
                        "semantic_score": 0.95,
                        "semantic_pass": True,
                        "semantic_reason": "aligned after two revisions",
                        "back_translation_text": "correct acceleration law",
                        "hard_gate_reasons": [],
                        "semantic_rank_score": 0.95,
                    }
                ],
                selected_backend="physlean",
                error=None,
            )

    class StubModuleE:
        def __init__(self, *args, **kwargs) -> None:
            _ = (args, kwargs)

        def run(self, grounding: GroundingResult, selected_candidate: StatementCandidate | None, run_dir: Path, mechlib_context: str = "(none)"):
            _ = (run_dir, mechlib_context)
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

    code = cli.main(["run", "--config", str(config_path)])
    assert code == 0
    assert [row["round_index"] for row in call_log] == [0, 1, 2]
    assert call_log[1]["previous_candidates_count"] == 4
    assert call_log[2]["previous_candidates_count"] == 4
    assert '"retry_reason": "semantic_fail"' in str(call_log[1]["revision_feedback"])
    assert '"retry_reason": "semantic_fail"' in str(call_log[2]["revision_feedback"])

    semantic_rows = _read_jsonl(output_latest / "semantic_rank.jsonl")
    summary_rows = _read_jsonl(output_latest / "sample_summary.jsonl")
    proof_rows = _read_jsonl(output_latest / "proof_checks.jsonl")

    assert len(semantic_rows) == 3
    assert semantic_rows[0]["retry_triggered"] is True
    assert semantic_rows[1]["retry_triggered"] is True
    assert semantic_rows[2]["retry_triggered"] is False
    assert summary_rows[0]["feedback_loop_used"] is True
    assert summary_rows[0]["final_round_index"] == 2
    assert proof_rows[0]["round_index"] == 2
