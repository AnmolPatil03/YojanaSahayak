"""LanceDB vector store plus an in-memory chunk lookup."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from pathlib import Path

import numpy as np
import pyarrow as pa

from yojana.ingest.models import Chunk
from yojana.ingest.pipeline import load_chunks

logger = logging.getLogger(__name__)

TABLE = "chunks"
VECTOR = "vector"
VECTOR_PLAIN = "vector_plain"


def sql_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def sql_in(column: str, values: Iterable[str]) -> str:
    return f"{column} IN ({', '.join(sql_quote(v) for v in values)})"


class ChunkStore:
    """All chunks keyed by id, loaded from `data/processed/chunks.jsonl`."""

    def __init__(self, chunks: Iterable[Chunk]) -> None:
        self._chunks = {c.chunk_id: c for c in chunks}

    @classmethod
    def load(cls, processed_dir: Path) -> ChunkStore:
        return cls(load_chunks(processed_dir))

    def get(self, chunk_id: str) -> Chunk | None:
        return self._chunks.get(chunk_id)

    def all(self) -> list[Chunk]:
        return list(self._chunks.values())

    def by_scheme(self, scheme_id: str, section: str | None = None) -> list[Chunk]:
        return [
            c
            for c in self._chunks.values()
            if c.scheme_id == scheme_id and (section is None or c.section == section)
        ]

    def __len__(self) -> int:
        return len(self._chunks)

    def __contains__(self, chunk_id: object) -> bool:
        return chunk_id in self._chunks


class VectorStore:
    """Chunk embeddings in an embedded LanceDB table.

    Each row holds the vector of the chunk with its contextual header and, when
    enabled, a second vector of the bare chunk text for the header ablation.
    """

    def __init__(self, path: Path) -> None:
        import lancedb

        path.mkdir(parents=True, exist_ok=True)
        self._db = lancedb.connect(str(path))
        self._table = self._open()

    def _open(self):  # type: ignore[no-untyped-def]
        try:
            return self._db.open_table(TABLE)
        except (FileNotFoundError, ValueError):
            return None

    @staticmethod
    def _schema(dim: int, with_plain: bool) -> pa.Schema:
        fields = [
            pa.field("chunk_id", pa.string()),
            pa.field("scheme_id", pa.string()),
            pa.field("state", pa.string()),
            pa.field("category", pa.string()),
            pa.field("section", pa.string()),
            pa.field("language", pa.string()),
            pa.field(VECTOR, pa.list_(pa.float32(), dim)),
        ]
        if with_plain:
            fields.append(pa.field(VECTOR_PLAIN, pa.list_(pa.float32(), dim)))
        return pa.schema(fields)

    @property
    def has_plain_vectors(self) -> bool:
        return self._table is not None and VECTOR_PLAIN in self._table.schema.names

    def count(self) -> int:
        return 0 if self._table is None else int(self._table.count_rows())

    def upsert(
        self,
        chunks: Sequence[Chunk],
        vectors: np.ndarray,
        plain_vectors: np.ndarray | None = None,
    ) -> None:
        """Insert or replace rows for `chunks`."""
        if not chunks:
            return
        with_plain = plain_vectors is not None
        rows = []
        for i, chunk in enumerate(chunks):
            row = {
                "chunk_id": chunk.chunk_id,
                "scheme_id": chunk.scheme_id,
                "state": chunk.state,
                "category": chunk.category,
                "section": chunk.section,
                "language": chunk.language,
                VECTOR: vectors[i].astype(np.float32).tolist(),
            }
            if with_plain:
                row[VECTOR_PLAIN] = plain_vectors[i].astype(np.float32).tolist()
            rows.append(row)
        if self._table is None:
            schema = self._schema(int(vectors.shape[1]), with_plain)
            self._table = self._db.create_table(TABLE, data=rows, schema=schema)
            return
        if with_plain != self.has_plain_vectors:
            raise ValueError(
                "Existing index and new rows disagree on plain vectors; re-run ingestion "
                "with --force after changing store_plain_vectors."
            )
        self.delete([c.chunk_id for c in chunks])
        self._table.add(rows)

    def delete(self, chunk_ids: Sequence[str]) -> None:
        if self._table is None or not chunk_ids:
            return
        for start in range(0, len(chunk_ids), 500):
            self._table.delete(sql_in("chunk_id", chunk_ids[start : start + 500]))

    def reset(self) -> None:
        if self._table is not None:
            self._db.drop_table(TABLE)
            self._table = None

    def search(
        self,
        vector: np.ndarray,
        k: int,
        where: str | None = None,
        *,
        plain: bool = False,
    ) -> list[tuple[str, float]]:
        """Top-k (chunk_id, cosine similarity) pairs, filtered before the search."""
        if self._table is None:
            return []
        column = VECTOR_PLAIN if plain and self.has_plain_vectors else VECTOR
        query = (
            self._table.search(vector.astype(np.float32).tolist(), vector_column_name=column)
            .distance_type("cosine")
            .select(["chunk_id"])
            .limit(k)
        )
        if where:
            query = query.where(where, prefilter=True)
        return [(row["chunk_id"], 1.0 - float(row["_distance"])) for row in query.to_list()]
