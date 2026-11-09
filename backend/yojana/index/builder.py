"""Keeps the LanceDB and BM25 indexes in step with the processed chunks."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from yojana.config import Settings
from yojana.index.bm25 import BM25Index
from yojana.index.embedder import Embedder
from yojana.index.store import VectorStore
from yojana.ingest.models import Chunk
from yojana.ingest.pipeline import load_chunks

logger = logging.getLogger(__name__)

BM25_FILE = "bm25.json"
BM25_PLAIN_FILE = "bm25_plain.json"
VECTORS_DIR = "lancedb"


class IndexBuilder:
    """Applies chunk additions and removals to the dense and sparse indexes."""

    def __init__(self, settings: Settings, embedder: Embedder | None = None) -> None:
        self.settings = settings
        self.retrieval = settings.retrieval()
        self._embedder = embedder
        self._store: VectorStore | None = None

    @property
    def embedder(self) -> Embedder:
        if self._embedder is None:
            self._embedder = Embedder(
                self.retrieval.embedding, cache_folder=self.settings.cache_dir / "models"
            )
        return self._embedder

    @property
    def store(self) -> VectorStore:
        if self._store is None:
            self._store = VectorStore(self.settings.index_dir / VECTORS_DIR)
        return self._store

    def apply_changes(self, new_chunks: Sequence[Chunk], removed_ids: Sequence[str]) -> None:
        """Embed and upsert new chunks, and delete removed ones from the vector store."""
        if removed_ids:
            self.store.delete(list(removed_ids))
        if not new_chunks:
            return
        logger.info("Embedding %d chunks", len(new_chunks))
        vectors = self.embedder.encode_passages([c.embed_text for c in new_chunks])
        plain = (
            self.embedder.encode_passages([c.text for c in new_chunks])
            if self.retrieval.store_plain_vectors
            else None
        )
        self.store.upsert(list(new_chunks), vectors, plain)

    def rebuild_dense(self) -> int:
        """Re-embed every chunk; used after changing the embedding model."""
        chunks = load_chunks(self.settings.processed_dir)
        self.store.reset()
        self.apply_changes(chunks, [])
        return len(chunks)

    def rebuild_sparse(self) -> int:
        """Rebuild both BM25 variants (with and without contextual headers)."""
        chunks = load_chunks(self.settings.processed_dir)
        ids = [c.chunk_id for c in chunks]
        BM25Index.build(ids, [c.embed_text for c in chunks]).save(
            self.settings.index_dir / BM25_FILE
        )
        BM25Index.build(ids, [c.text for c in chunks]).save(
            self.settings.index_dir / BM25_PLAIN_FILE
        )
        return len(chunks)
