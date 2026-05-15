from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

MAX_SAMPLE_CONCURRENCY = 10
_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORKSPACE_ROOT = _REPO_ROOT.parent
DEFAULT_LOCAL_ARCHIVE_ROOT = str(_WORKSPACE_ROOT / "archive")
DEFAULT_LEAN4PHYS_BENCH = str(_WORKSPACE_ROOT / "Lean4PHYS" / "LeanPhysBench" / "LeanPhysBench_v0.json")
DEFAULT_PHYSLIB_DIR = str(_WORKSPACE_ROOT / "physlib")
DEFAULT_MECHLIB_DIR = str(_WORKSPACE_ROOT / "MechLib")
DEFAULT_MECHLIB_CORPUS = str(_WORKSPACE_ROOT / "MechLib" / "corpus" / "theorem_corpus.jsonl")
DEFAULT_MECHLIB_DECL_CORPUS = str(_WORKSPACE_ROOT / "MechLib" / "corpus" / "decl_corpus_enriched.jsonl")
DEFAULT_MECHLIB_LAW_SCHEMA_CORPUS = str(_WORKSPACE_ROOT / "MechLib" / "corpus" / "law_schema_corpus.jsonl")
DEFAULT_MECHLIB_PROBLEM_SCHEMA_CORPUS = str(_WORKSPACE_ROOT / "MechLib" / "corpus" / "problem_schema_corpus.jsonl")
DEFAULT_MECHLIB_CONCEPT_CORPUS = str(_WORKSPACE_ROOT / "MechLib" / "corpus" / "concept_corpus.jsonl")
DEFAULT_MECHLIB_ALIAS_MAP = str(_WORKSPACE_ROOT / "MechLib" / "corpus" / "alias_map.jsonl")
DEFAULT_MECHLIB_ALIGNMENT_INDEX = str(_WORKSPACE_ROOT / "MechLib" / "corpus" / "decl_to_spec_index.json")
_MOJIBAKE_SUSPECT_FRAGMENTS = (
    "鏁版嵁",
    "褰掓",
    "閺佺増",
    "瑜版帗",
    "鈩",
    "鈫",
    "鈭",
    "锛",
    "銆",
    "\ufffd",
)


@dataclass
class LocalArchiveConfig:
    root: str = DEFAULT_LOCAL_ARCHIVE_ROOT
    mode: str = "text_only"


@dataclass
class Lean4PhysConfig:
    bench_path: str = DEFAULT_LEAN4PHYS_BENCH
    category: str = "mechanics"
    level: str | None = None


@dataclass
class DatasetConfig:
    source: str = "lean4phys"
    limit: int = 10
    category: str = "Mechanics"
    sample_policy: str = "index_head"
    seed: int = 42
    phyx_urls: list[str] = field(
        default_factory=lambda: [
            "https://hf-mirror.com/datasets/Cloudriver/PhyX/resolve/main/data_llms_eval/PhyX_mini_MC.parquet",
            "https://huggingface.co/datasets/Cloudriver/PhyX/resolve/main/data_llms_eval/PhyX_mini_MC.parquet",
        ]
    )
    local_archive: LocalArchiveConfig = field(default_factory=LocalArchiveConfig)
    lean4phys: Lean4PhysConfig = field(default_factory=Lean4PhysConfig)
    single_image_only_for_mvp: bool = True


@dataclass
class ModelConfig:
    provider: str = "mock"
    model_id: str | None = "mock-mechanics-v1"
    base_url: str | None = None
    api_key: str | None = None
    api_key_env: str = "OPENAI_API_KEY"
    supports_vision: bool = True
    timeout_s: int = 60
    max_retries: int = 2
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class LeanConfig:
    enabled: bool = True
    physlean_dir: str = DEFAULT_PHYSLIB_DIR
    mechlib_dir: str = DEFAULT_MECHLIB_DIR
    timeout_s: int = 240
    strict_blocklist: list[str] = field(default_factory=lambda: ["sorry", "admit", "axiom"])
    lean_header: str = "import Physlib"
    preflight_enabled: bool = True
    route_policy: str = "auto_by_import"
    default_backend: str = "mechlib"
    route_fallback: bool = True


@dataclass
class KnowledgeConfig:
    enabled: bool = True
    mechlib_dir: str = DEFAULT_MECHLIB_DIR
    scope: str = "mechanics_si"
    top_k: int = 6
    evidence_top_k: int = 8
    cache_path: str = "tmp/mechlib_index.jsonl"
    inject_modules: list[str] = field(default_factory=lambda: ["B"])
    context_source: str = "hybrid"
    structured_context_enabled: bool = True
    summary_corpus_path: str = DEFAULT_MECHLIB_CORPUS
    enriched_corpus_enabled: bool = True
    decl_corpus_path: str = DEFAULT_MECHLIB_DECL_CORPUS
    law_schema_corpus_path: str = DEFAULT_MECHLIB_LAW_SCHEMA_CORPUS
    problem_schema_corpus_path: str = DEFAULT_MECHLIB_PROBLEM_SCHEMA_CORPUS
    concept_corpus_path: str = DEFAULT_MECHLIB_CONCEPT_CORPUS
    alias_map_path: str = DEFAULT_MECHLIB_ALIAS_MAP
    alignment_index_path: str = DEFAULT_MECHLIB_ALIGNMENT_INDEX
    lean_check_decls: bool = True
    summary_injection_mode: str = "domain_full"
    always_include_core_tags: list[str] = field(default_factory=lambda: ["SI", "Units"])


@dataclass
class StatementConfig:
    library_target: str = "mechlib"
    with_mechlib_context: bool = True
    feedback_loop_enabled: bool = True
    max_revision_rounds: int = 1
    generation_mode: str = "minimal_skeleton"
    allow_explicit_gap_laws: bool = True
    forbid_derived_equation_hypotheses: bool = True
    require_hypothesis_provenance: bool = True
    require_evidence_binding: bool = True
    max_model_ir_candidates: int = 2
    max_sketch_steps: int = 12
    minimal_feedback_scope: str = "routed_stage"
    b_minimal_llm_enabled: bool = False
    b_minimal_llm_on_retry: bool = True
    compact_minimal_prompts: bool = True


@dataclass
class SemanticConfig:
    pass_threshold: float = 0.7


@dataclass
class LLMGuidedSearchConfig:
    enabled: bool = True
    max_nodes: int = 80
    max_depth: int = 16
    max_llm_calls: int = 12
    proposals_per_call: int = 5
    probe_timeout_s: int | None = 120
    max_probe_checks: int = 80
    max_no_progress_nodes: int = 12
    max_wall_clock_s_per_sample: int | None = 1800
    max_action_chars: int = 1200
    max_failed_actions_kept: int = 20
    final_replay_required: bool = True
    deterministic_obligation_replay_first: bool = True
    deterministic_side_conditions_first: bool = True
    allow_gap_assisted_proof: bool = False
    require_verified_decl_use: bool = True
    require_all_proof_obligations_covered: bool = True
    allow_llm_subgoals: bool = True
    allow_llm_rewrite_actions: bool = True
    allow_llm_algebra_actions: bool = True
    forbid_sorry: bool = True
    forbid_admit: bool = True
    forbid_axiom: bool = True
    forbid_set_option: bool = True
    allow_physical_positive_hypothesis_augmentation: bool = True
    physical_positive_types: list[str] = field(
        default_factory=lambda: [
            "Mass",
            "Length",
            "Time",
            "Speed",
            "Velocity",
            "Acceleration",
            "Force",
            "Energy",
            "Work",
            "Power",
            "Momentum",
            "Torque",
            "AngularMomentum",
            "MomentOfInertia",
            "Frequency",
        ]
    )
    max_added_positive_hypotheses: int = 8
    require_augmented_theorem_compile: bool = True


@dataclass
class ProofConfig:
    mode: str = "auto"
    legacy_fallback_enabled: bool = False
    max_attempts: int = 2
    llm_guided_search: LLMGuidedSearchConfig = field(default_factory=LLMGuidedSearchConfig)


@dataclass
class SolutionRendererConfig:
    enabled: bool = True
    natural_language_enabled: bool = False
    repair_on_audit_fail: bool = True
    max_trace_steps_for_prompt: int = 24
    max_prompt_chars: int = 8000
    max_natural_solution_chars_in_readme: int = 2400


@dataclass
class PromptConfig:
    dir: str = "prompts"
    a_extract_ir: str = "A_extract_ir.txt"
    a2_model_ir: str = "A2_model_ir.txt"
    controlled_sketch: str = "controlled_sketch.txt"
    b_generate_statements: str = "B_generate_statements.txt"
    b_generate_minimal_skeleton: str = "B_generate_minimal_skeleton.txt"
    b_revise_statements: str = "B_revise_statements.txt"
    d_semantic_rank: str = "D_semantic_rank.txt"
    e_plan_proof: str = "E_plan_proof.txt"
    e_generate_proof: str = "E_generate_proof.txt"
    e_repair_proof: str = "E_repair_proof.txt"
    e_strategy_controller: str = "E_strategy_controller.md"
    solution_renderer: str = "F_solution_renderer.md"


@dataclass
class OutputConfig:
    output_dir: str = "outputs/latest"
    runs_dir: str = "runs"
    tag: str | None = "baseline-v1"


@dataclass
class RuntimeConfig:
    sample_concurrency: int = 1


@dataclass
class PipelineConfig:
    dataset: DatasetConfig = field(default_factory=DatasetConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    lean: LeanConfig = field(default_factory=LeanConfig)
    knowledge: KnowledgeConfig = field(default_factory=KnowledgeConfig)
    statement: StatementConfig = field(default_factory=StatementConfig)
    semantic: SemanticConfig = field(default_factory=SemanticConfig)
    proof: ProofConfig = field(default_factory=ProofConfig)
    solution_renderer: SolutionRendererConfig = field(default_factory=SolutionRendererConfig)
    prompts: PromptConfig = field(default_factory=PromptConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _merge_dict(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dict(merged[key], value)
        else:
            merged[key] = value
    return merged


def _looks_like_mojibake(text: str) -> bool:
    return any(fragment in text for fragment in _MOJIBAKE_SUSPECT_FRAGMENTS)


def load_config(path: Path) -> PipelineConfig:
    if not path.exists():
        raise FileNotFoundError(f"Config file does not exist: {path}")

    with path.open("r", encoding="utf-8-sig") as f:
        payload = yaml.safe_load(f) or {}
    if not isinstance(payload, dict):
        raise ValueError("Config root must be a mapping")

    defaults = PipelineConfig()
    merged = _merge_dict(defaults.to_dict(), payload)
    cfg = PipelineConfig(
        dataset=DatasetConfig(
            **{
                **merged["dataset"],
                "local_archive": LocalArchiveConfig(**merged["dataset"]["local_archive"]),
                "lean4phys": Lean4PhysConfig(**merged["dataset"]["lean4phys"]),
            }
        ),
        model=ModelConfig(**merged["model"]),
        lean=LeanConfig(**merged["lean"]),
        knowledge=KnowledgeConfig(**merged["knowledge"]),
        statement=StatementConfig(**merged["statement"]),
        semantic=SemanticConfig(**merged["semantic"]),
        proof=ProofConfig(
            **{
                **merged["proof"],
                "llm_guided_search": LLMGuidedSearchConfig(**merged["proof"]["llm_guided_search"]),
            }
        ),
        solution_renderer=SolutionRendererConfig(**merged["solution_renderer"]),
        prompts=PromptConfig(**merged["prompts"]),
        output=OutputConfig(**merged["output"]),
        runtime=RuntimeConfig(**merged["runtime"]),
    )
    validate_config(cfg)
    return cfg


def validate_config(cfg: PipelineConfig) -> None:
    if cfg.dataset.source not in {"local_archive", "phyx", "lean4phys"}:
        raise ValueError("dataset.source must be one of {'local_archive', 'phyx', 'lean4phys'}")
    if cfg.dataset.local_archive.mode not in {"text_only", "image_text"}:
        raise ValueError("dataset.local_archive.mode must be one of {'text_only', 'image_text'}")
    if cfg.dataset.sample_policy not in {"index_head", "seed_random"}:
        raise ValueError("dataset.sample_policy must be one of {'index_head', 'seed_random'}")
    if cfg.dataset.limit <= 0:
        raise ValueError("dataset.limit must be > 0")
    if not cfg.dataset.phyx_urls:
        raise ValueError("dataset.phyx_urls must not be empty")
    if cfg.model.timeout_s <= 0:
        raise ValueError("model.timeout_s must be > 0")
    if cfg.model.max_retries < 0:
        raise ValueError("model.max_retries must be >= 0")
    if cfg.lean.timeout_s <= 0:
        raise ValueError("lean.timeout_s must be > 0")
    if not cfg.lean.lean_header.strip():
        raise ValueError("lean.lean_header must not be empty")
    if cfg.lean.route_policy not in {"auto_by_import", "force_physlean", "force_mechlib"}:
        raise ValueError("lean.route_policy must be one of {'auto_by_import', 'force_physlean', 'force_mechlib'}")
    if cfg.lean.default_backend not in {"physlean", "mechlib"}:
        raise ValueError("lean.default_backend must be one of {'physlean', 'mechlib'}")
    if cfg.knowledge.scope not in {"mechanics", "mechanics_si", "all"}:
        raise ValueError("knowledge.scope must be one of {'mechanics', 'mechanics_si', 'all'}")
    if cfg.knowledge.top_k <= 0:
        raise ValueError("knowledge.top_k must be > 0")
    if cfg.knowledge.evidence_top_k <= 0:
        raise ValueError("knowledge.evidence_top_k must be > 0")
    if cfg.knowledge.context_source not in {"hybrid", "summary_only", "source_only"}:
        raise ValueError("knowledge.context_source must be one of {'hybrid', 'summary_only', 'source_only'}")
    if cfg.knowledge.summary_injection_mode not in {"domain_full"}:
        raise ValueError("knowledge.summary_injection_mode must be one of {'domain_full'}")
    valid_inject = {"B", "D", "E"}
    inject = {x.strip().upper() for x in cfg.knowledge.inject_modules}
    if not inject.issubset(valid_inject):
        raise ValueError("knowledge.inject_modules must be subset of {'B', 'D', 'E'}")
    if not cfg.knowledge.always_include_core_tags:
        raise ValueError("knowledge.always_include_core_tags must not be empty")
    if cfg.statement.library_target not in {"mechlib", "physlean", "auto"}:
        raise ValueError("statement.library_target must be one of {'mechlib', 'physlean', 'auto'}")
    if cfg.statement.max_revision_rounds < 0:
        raise ValueError("statement.max_revision_rounds must be >= 0")
    if cfg.statement.generation_mode not in {"legacy_candidate", "minimal_skeleton"}:
        raise ValueError("statement.generation_mode must be one of {'legacy_candidate', 'minimal_skeleton'}")
    if cfg.statement.minimal_feedback_scope not in {"routed_stage", "sketch_and_b", "all_downstream", "none", "b_only"}:
        raise ValueError(
            "statement.minimal_feedback_scope must be one of "
            "{'routed_stage', 'sketch_and_b', 'all_downstream', 'none', 'b_only'}"
        )
    if cfg.statement.max_model_ir_candidates <= 0:
        raise ValueError("statement.max_model_ir_candidates must be > 0")
    if cfg.statement.max_sketch_steps <= 0:
        raise ValueError("statement.max_sketch_steps must be > 0")
    if cfg.proof.max_attempts <= 0:
        raise ValueError("proof.max_attempts must be > 0")
    if cfg.proof.mode not in {"auto", "legacy_full_proof", "llm_guided_search"}:
        raise ValueError("proof.mode must be one of {'auto', 'legacy_full_proof', 'llm_guided_search'}")
    search = cfg.proof.llm_guided_search
    if search.max_nodes <= 0:
        raise ValueError("proof.llm_guided_search.max_nodes must be > 0")
    if search.max_depth <= 0:
        raise ValueError("proof.llm_guided_search.max_depth must be > 0")
    if search.max_llm_calls < 0:
        raise ValueError("proof.llm_guided_search.max_llm_calls must be >= 0")
    if search.proposals_per_call <= 0:
        raise ValueError("proof.llm_guided_search.proposals_per_call must be > 0")
    if search.probe_timeout_s is not None and search.probe_timeout_s <= 0:
        raise ValueError("proof.llm_guided_search.probe_timeout_s must be > 0 when set")
    if search.max_probe_checks <= 0:
        raise ValueError("proof.llm_guided_search.max_probe_checks must be > 0")
    if search.max_no_progress_nodes <= 0:
        raise ValueError("proof.llm_guided_search.max_no_progress_nodes must be > 0")
    if search.max_wall_clock_s_per_sample is not None and search.max_wall_clock_s_per_sample <= 0:
        raise ValueError("proof.llm_guided_search.max_wall_clock_s_per_sample must be > 0 when set")
    if search.max_action_chars <= 0:
        raise ValueError("proof.llm_guided_search.max_action_chars must be > 0")
    if search.max_failed_actions_kept < 0:
        raise ValueError("proof.llm_guided_search.max_failed_actions_kept must be >= 0")
    if cfg.solution_renderer.max_trace_steps_for_prompt <= 0:
        raise ValueError("solution_renderer.max_trace_steps_for_prompt must be > 0")
    if cfg.solution_renderer.max_prompt_chars <= 0:
        raise ValueError("solution_renderer.max_prompt_chars must be > 0")
    if cfg.solution_renderer.max_natural_solution_chars_in_readme <= 0:
        raise ValueError("solution_renderer.max_natural_solution_chars_in_readme must be > 0")
    if cfg.semantic.pass_threshold < 0 or cfg.semantic.pass_threshold > 1:
        raise ValueError("semantic.pass_threshold must be in [0, 1]")
    if cfg.runtime.sample_concurrency <= 0:
        raise ValueError("runtime.sample_concurrency must be >= 1")
    if cfg.runtime.sample_concurrency > MAX_SAMPLE_CONCURRENCY:
        raise ValueError(f"runtime.sample_concurrency must be <= {MAX_SAMPLE_CONCURRENCY}")
    path_like_fields = {
        "dataset.local_archive.root": cfg.dataset.local_archive.root,
        "dataset.lean4phys.bench_path": cfg.dataset.lean4phys.bench_path,
        "lean.physlean_dir": cfg.lean.physlean_dir,
        "lean.mechlib_dir": cfg.lean.mechlib_dir,
        "knowledge.mechlib_dir": cfg.knowledge.mechlib_dir,
        "knowledge.cache_path": cfg.knowledge.cache_path,
        "knowledge.summary_corpus_path": cfg.knowledge.summary_corpus_path,
        "knowledge.decl_corpus_path": cfg.knowledge.decl_corpus_path,
        "knowledge.law_schema_corpus_path": cfg.knowledge.law_schema_corpus_path,
        "knowledge.problem_schema_corpus_path": cfg.knowledge.problem_schema_corpus_path,
        "knowledge.concept_corpus_path": cfg.knowledge.concept_corpus_path,
        "knowledge.alias_map_path": cfg.knowledge.alias_map_path,
        "knowledge.alignment_index_path": cfg.knowledge.alignment_index_path,
        "prompts.dir": cfg.prompts.dir,
        "output.output_dir": cfg.output.output_dir,
        "output.runs_dir": cfg.output.runs_dir,
    }
    for field_name, value in path_like_fields.items():
        if _looks_like_mojibake(value):
            raise ValueError(
                f"{field_name} contains likely mojibake; resave the config as UTF-8 and fix the path text"
            )


def select_proof_execution_mode(proof: ProofConfig, candidate: object | None) -> str:
    """Resolve the proof backend mode without changing legacy ModuleE behavior."""
    if proof.mode == "legacy_full_proof":
        return "legacy_full_proof"
    if proof.mode == "llm_guided_search":
        if proof.llm_guided_search.enabled:
            return "llm_guided_search"
        if proof.legacy_fallback_enabled:
            return "legacy_full_proof"
        return "llm_guided_search"

    generation_mode = str(getattr(candidate, "generation_mode", "") or "")
    skeleton_mode = bool(getattr(candidate, "skeleton_mode", False)) or generation_mode == "minimal_skeleton"
    if skeleton_mode and proof.llm_guided_search.enabled:
        return "llm_guided_search"
    return "legacy_full_proof"
