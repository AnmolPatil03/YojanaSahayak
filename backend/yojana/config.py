"""Application settings loaded from environment, `.env` and `config/*.yaml`."""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from dotenv import dotenv_values
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)(?::-([^}]*))?\}")


def find_root() -> Path:
    """Locate the project root (the directory holding `config/providers.yaml`)."""
    explicit = os.environ.get("YOJANA_ROOT")
    if explicit:
        return Path(explicit).resolve()
    for parent in [Path.cwd(), *Path(__file__).resolve().parents]:
        if (parent / "config" / "providers.yaml").is_file():
            return parent
    return Path.cwd()


ROOT = find_root()


class ProviderConfig(BaseModel):
    """One OpenAI-compatible LLM provider entry from `providers.yaml`."""

    name: str
    label: str | None = None
    base_url: str
    api_key_env: str | None = None
    model: str
    rpm: int | None = None
    tpm: int | None = None
    rpd: int | None = None
    tpd: int | None = None
    max_input_tokens: int = 8000
    max_output_tokens: int = 1024
    supports_json_mode: bool = False
    trains_on_free_tier_data: bool = False
    enabled: bool = True
    offline: bool = False
    requires_key: bool = True
    timeout_s: float = 45.0
    extra_headers: dict[str, str] = Field(default_factory=dict)

    @property
    def display_name(self) -> str:
        return self.label or self.name


class EmbeddingConfig(BaseModel):
    model: str = "intfloat/multilingual-e5-small"
    backend: Literal["torch", "onnx"] = "torch"
    batch_size: int = 32
    query_prefix: str = "query: "
    passage_prefix: str = "passage: "
    max_seq_length: int = 512


class RerankerConfig(BaseModel):
    model: str = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
    backend: Literal["torch", "onnx"] = "torch"
    batch_size: int = 16
    max_length: int = 512


class ChunkingConfig(BaseModel):
    max_tokens: int = 300
    overlap: float = 0.15
    min_tokens: int = 40


class RetrievalConfig(BaseModel):
    """Retrieval pipeline switches; every stage can be toggled for ablations."""

    mode: Literal["dense", "bm25", "hybrid"] = "hybrid"
    rerank: bool = True
    contextual_headers: bool = True
    query_rewrite: bool = True
    dense_top_k: int = 30
    bm25_top_k: int = 30
    rrf_k: int = 60
    rerank_candidates: int = 20
    final_top_k: int = 5
    abstain_threshold: float = 0.15
    dense_abstain_threshold: float = 0.78
    store_plain_vectors: bool = True
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    reranker: RerankerConfig = Field(default_factory=RerankerConfig)
    chunking: ChunkingConfig = Field(default_factory=ChunkingConfig)


class SourceConfig(BaseModel):
    name: str
    enabled: bool = True
    sitemap: str | None = None
    start_urls: list[str] = Field(default_factory=list)
    allow_patterns: list[str] = Field(default_factory=list)
    max_pages: int = 50
    render_js: bool = False


class ScraperConfig(BaseModel):
    user_agent: str = "YojanaSahayakBot/0.1 (educational research crawler)"
    min_delay_s: float = 2.0
    timeout_s: float = 30.0
    sources: list[SourceConfig] = Field(default_factory=list)

    @field_validator("min_delay_s")
    @classmethod
    def _at_least_two_seconds(cls, value: float) -> float:
        return max(value, 2.0)


def _expand_env(value: Any, env: dict[str, str]) -> Any:
    if isinstance(value, str):
        return _ENV_PATTERN.sub(lambda m: env.get(m.group(1)) or (m.group(2) or ""), value)
    if isinstance(value, list):
        return [_expand_env(v, env) for v in value]
    if isinstance(value, dict):
        return {k: _expand_env(v, env) for k, v in value.items()}
    return value


def load_yaml(path: Path, env: dict[str, str] | None = None) -> Any:
    """Read a YAML file, expanding `${VAR}` and `${VAR:-default}` references."""
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return _expand_env(data, env if env is not None else merged_env())


def merged_env(root: Path = ROOT) -> dict[str, str]:
    """Process environment layered over `.env`; real environment variables win."""
    values = {k: v for k, v in dotenv_values(root / ".env").items() if v}
    values.update({k: v for k, v in os.environ.items() if v})
    return values


class Settings(BaseSettings):
    """Runtime settings. Environment variables use the `YOJANA_` prefix."""

    model_config = SettingsConfigDict(
        env_prefix="YOJANA_",
        env_file=str(ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    root_dir: Path = ROOT
    log_level: str = "INFO"
    llm_cache_enabled: bool = True
    llm_cache_ttl_hours: float = 168.0
    allow_unreviewed_rules: bool = False
    warmup_models: bool = True
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    max_history_turns: int = 6

    @property
    def config_dir(self) -> Path:
        return self.root_dir / "config"

    @property
    def data_dir(self) -> Path:
        return self.root_dir / "data"

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def processed_dir(self) -> Path:
        return self.data_dir / "processed"

    @property
    def index_dir(self) -> Path:
        return self.data_dir / "index"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def eval_dir(self) -> Path:
        return self.data_dir / "eval"

    @property
    def sample_dir(self) -> Path:
        return self.data_dir / "sample"

    @property
    def reports_dir(self) -> Path:
        return self.root_dir / "reports"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def env(self) -> dict[str, str]:
        return merged_env(self.root_dir)

    def secret(self, name: str | None) -> str | None:
        """Look up a secret by environment variable name."""
        if not name:
            return None
        return self.env().get(name) or None

    def providers(self) -> list[ProviderConfig]:
        raw = load_yaml(self.config_dir / "providers.yaml", self.env())
        return [ProviderConfig.model_validate(p) for p in raw.get("providers", [])]

    def retrieval(self) -> RetrievalConfig:
        return RetrievalConfig.model_validate(
            load_yaml(self.config_dir / "retrieval.yaml", self.env())
        )

    def scraper(self) -> ScraperConfig:
        return ScraperConfig.model_validate(load_yaml(self.config_dir / "sources.yaml", self.env()))

    def ensure_dirs(self) -> None:
        for path in (
            self.raw_dir,
            self.processed_dir,
            self.index_dir,
            self.cache_dir,
            self.reports_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings instance."""
    return Settings()
