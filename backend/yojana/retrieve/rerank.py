"""Cross-encoder reranking on CPU."""

from __future__ import annotations

import logging
import math
import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from yojana.config import RerankerConfig

logger = logging.getLogger(__name__)

ModelFactory = Callable[[RerankerConfig], Any]


def _load_cross_encoder(cfg: RerankerConfig, cache_folder: Path | None) -> Any:
    import torch
    from sentence_transformers import CrossEncoder

    kwargs: dict[str, Any] = {
        "device": "cpu",
        "backend": cfg.backend,
        "max_length": cfg.max_length,
        # Raw logits from this model are unbounded; a sigmoid gives 0..1 scores so
        # one abstention threshold works across queries.
        "activation_fn": torch.nn.Sigmoid(),
    }
    if cache_folder is not None:
        kwargs["cache_folder"] = str(cache_folder)
    return CrossEncoder(cfg.model, **kwargs)


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-value))


class Reranker:
    """Scores (query, passage) pairs and keeps the best `top_n`."""

    def __init__(
        self,
        cfg: RerankerConfig,
        *,
        cache_folder: Path | None = None,
        factory: ModelFactory | None = None,
    ) -> None:
        self.cfg = cfg
        self._cache_folder = cache_folder
        self._factory = factory
        self._model: Any = None
        self._lock = threading.Lock()

    @property
    def model(self) -> Any:
        if self._model is None:
            with self._lock:
                if self._model is None:
                    logger.info("Loading reranker %s (%s)", self.cfg.model, self.cfg.backend)
                    self._model = (
                        self._factory(self.cfg)
                        if self._factory
                        else _load_cross_encoder(self.cfg, self._cache_folder)
                    )
        return self._model

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        """Relevance in [0, 1] for each passage."""
        if not passages:
            return []
        raw = self.model.predict(
            [(query, p) for p in passages],
            batch_size=self.cfg.batch_size,
            show_progress_bar=False,
        )
        scores = [float(s) for s in list(raw)]
        if any(s < 0.0 or s > 1.0 for s in scores):
            scores = [_sigmoid(s) for s in scores]
        return scores

    def rerank(
        self, query: str, candidates: Sequence[tuple[str, str]], top_n: int
    ) -> list[tuple[str, float]]:
        """Return the `top_n` (id, score) pairs from `(id, text)` candidates."""
        scores = self.score(query, [text for _, text in candidates])
        ranked = sorted(
            zip((cid for cid, _ in candidates), scores, strict=True),
            key=lambda item: -item[1],
        )
        return ranked[:top_n]

    def warmup(self) -> None:
        self.score("warmup", ["warmup passage"])
