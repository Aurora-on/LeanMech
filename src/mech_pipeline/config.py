from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml


MAX_SAMPLE_CONCURRENCY = 10
DEFAULT_LOCAL_ARCHIVE_ROOT = "F:/AI4Mechanics/datasets/archive"
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
    bench_path: str = r"F:/AI4Mechanics/coding/Lean4PHYS/LeanPhysBench/LeanPhysBench_v0.json"
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
    physlean_dir: str = r"F:/AI4Mechanics/PhysLean-master"
    mechlib_dir: str = r"F:/AI4Mechanics/coding/MechLib"
    timeout_s: int = 120
    strict_blocklist: list[str] = field(default_factory=lambda: ["sorry", "admit", "axiom"])
    lean_header: str = "import PhysLean"
    preflight_enabled: bool = True
    route_policy: str = "auto_by_import"
    default_backend: str = "mechlib"
    route_fallback: bool = True


@dataclass
class KnowledgeConfig:
    enabled: bool = True
    mechlib_dir: str = r"F:/AI4Mechanics/coding/MechLib"
    scope: str = "mechanics_si"
    top_k: int = 6
    cache_path: str = "tmp/mechlib_index.jsonl"
    inject_modules: list[str] = field(default_factory=lambda: ["B"])
    context_source: str = "hybrid"
    summary_corpus_path: str = r"F:/AI4Mechanics/coding/MechLib/theorem_corpus.jsonl"
    summary_injection_mode: str = "domain_full"
    always_include_core_tags: list[str] = field(default_factory=lambda: ["SI", "Units"])


@dataclass
class StatementConfig:
    library_target: str = "mechlib"
    with_mechlib_context: bool = True
    feedback_loop_enabled: bool = True
    max_revision_rounds: int = 1


@dataclass
class SemanticConfig:
    pass_threshold: float = 0.7


@dataclass
class ProofConfig:
    max_attempts: int = 2


@dataclass
class PromptConfig:
    dir: str = "prompts"
    a_extract_ir: str = "A_extract_ir.txt"
    b_generate_statements: str = "B_generate_statements.txt"
    b_revise_statements: str = "B_revise_statements.txt"
    d_semantic_rank: str = "D_semantic_rank.txt"
    e_plan_proof: str = "E_plan_proof.txt"
    e_generate_proof: str = "E_generate_proof.txt"
    e_repair_proof: str = "E_repair_proof.txt"


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
        proof=ProofConfig(**merged["proof"]),
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
    if cfg.proof.max_attempts <= 0:
        raise ValueError("proof.max_attempts must be > 0")
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
        "prompts.dir": cfg.prompts.dir,
        "output.output_dir": cfg.output.output_dir,
        "output.runs_dir": cfg.output.runs_dir,
    }
    for field_name, value in path_like_fields.items():
        if _looks_like_mojibake(value):
            raise ValueError(
                f"{field_name} contains likely mojibake; resave the config as UTF-8 and fix the path text"
            )
