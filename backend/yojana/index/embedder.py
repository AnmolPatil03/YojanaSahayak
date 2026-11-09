"""Multilingual sentence embeddings on CPU, loaded lazily and cached per query."""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from yojana.config import EmbeddingConfig

logger = logging.getLogger(__name__)

ModelFactory = Callable[[EmbeddingConfig], Any]


def _load_sentence_transformer(cfg: EmbeddingConfig, cache_folder: Path | None) -> Any:
    from sentence_transformers import SentenceTransformer

    kwargs: dict[str, Any] = {"device": "cpu", "backend": cfg.backend}
    if cache_folder is not None:
        kwargs["cache_folder"] = str(cache_folder)
    model = SentenceTransformer(cfg.model, **kwargs)
    model.max_seq_length = cfg.max_seq_length
    return model


class Embedder:
    """Wraps a SentenceTransformer with the E5 `query:` / `passage:` prefixes.

    The model is loaded on first use so that importing the package, running tests,
    or serving cached answers never pays the start-up cost.
    """

    def __init__(
        self,
        cfg: EmbeddingConfig,
        *,
        cache_folder: Path | None = None,
        factory: ModelFactory | None = None,
        query_cache_size: int = 512,
    ) -> None:
        self.cfg = cfg
        self._cache_folder = cache_folder
        self._factory = factory
        self._model: Any = None
        self._lock = threading.Lock()
        self._query_cache: OrderedDict[str, np.ndarray] = OrderedDict()
        self._query_cache_size = query_cache_size

    @property
    def model(self) -> Any:
        if self._model is None:
            with self._lock:
                if self._model is None:
                    logger.info("Loading embedding model %s (%s)", self.cfg.model, self.cfg.backend)
                    self._model = (
                        self._factory(self.cfg)
                        if self._factory
                        else _load_sentence_transformer(self.cfg, self._cache_folder)
                    )
        return self._model

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def _encode(self, texts: Sequence[str]) -> np.ndarray:
        vectors = self.model.encode(
            list(texts),
            batch_size=self.cfg.batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=len(texts) > 200,
        )
        return np.asarray(vectors, dtype=np.float32)

    def encode_passages(self, texts: Sequence[str]) -> np.ndarray:
        """Embed passages in batches; returns an (n, dim) float32 array of unit vectors."""
        if not texts:
            return np.zeros((0, self.dimension), dtype=np.float32)
        return self._encode([self.cfg.passage_prefix + t for t in texts])

    def encode_query(self, text: str) -> np.ndarray:
        """Embed one query, reusing the result for repeated queries."""
        cached = self._query_cache.get(text)
        if cached is not None:
            self._query_cache.move_to_end(text)
            return cached
        vector = self._encode([self.cfg.query_prefix + text])[0]
        self._query_cache[text] = vector
        if len(self._query_cache) > self._query_cache_size:
            self._query_cache.popitem(last=False)
        return vector

    @property
    def dimension(self) -> int:
        getter = getattr(self.model, "get_sentence_embedding_dimension", None)
        if callable(getter):
            dim = getter()
            if dim:
                return int(dim)
        return int(self._encode(["dimension probe"]).shape[1])

    def warmup(self) -> None:
        self.encode_query("warmup")
