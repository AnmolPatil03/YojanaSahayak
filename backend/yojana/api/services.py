"""Long-lived objects shared by the API routes."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field

from yojana.agent.orchestrator import Orchestrator
from yojana.config import Settings
from yojana.index.store import ChunkStore
from yojana.ingest.registry import SchemeRegistry
from yojana.llm.gateway import LLMGateway
from yojana.retrieve.hybrid import HybridRetriever
from yojana.rules import RulesStore

logger = logging.getLogger(__name__)


@dataclass
class IngestJob:
    state: str = "idle"
    started_at: str | None = None
    finished_at: str | None = None
    report: dict[str, object] | None = None
    error: str | None = None


@dataclass
class Services:
    """Holds the gateway, indexes and orchestrator. `reload()` picks up new ingestion."""

    settings: Settings
    gateway: LLMGateway
    retriever: HybridRetriever
    registry: SchemeRegistry
    rules: RulesStore
    orchestrator: Orchestrator = field(init=False)
    ingest_job: IngestJob = field(default_factory=IngestJob)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self) -> None:
        self.orchestrator = Orchestrator(
            gateway=self.gateway,
            retriever=lambda: self.retriever,
            registry=lambda: self.registry,
            rules=self.rules,
            allow_unreviewed=self.settings.allow_unreviewed_rules,
            history_turns=self.settings.max_history_turns,
        )

    @classmethod
    def build(cls, settings: Settings) -> Services:
        settings.ensure_dirs()
        return cls(
            settings=settings,
            gateway=LLMGateway.from_settings(settings),
            retriever=HybridRetriever.from_settings(settings),
            registry=SchemeRegistry.load(settings.processed_dir / "schemes.json"),
            rules=RulesStore(settings.processed_dir / "rules"),
        )

    @property
    def chunks(self) -> ChunkStore:
        return self.retriever.chunks

    def reload(self) -> None:
        """Reload indexes and the registry, keeping loaded models warm."""
        with self._lock:
            fresh = HybridRetriever.from_settings(self.settings)
            fresh.embedder = self.retriever.embedder or fresh.embedder
            fresh.reranker = self.retriever.reranker or fresh.reranker
            self.retriever = fresh
            self.registry = SchemeRegistry.load(self.settings.processed_dir / "schemes.json")
        logger.info(
            "Reloaded indexes: %d schemes, %d chunks", len(self.registry), len(fresh.chunks)
        )

    def warmup(self) -> None:
        if not self.retriever.ready:
            return
        try:
            self.retriever.warmup()
            logger.info("Models warmed up")
        except Exception as exc:
            logger.warning("Model warm-up failed: %s", exc)
