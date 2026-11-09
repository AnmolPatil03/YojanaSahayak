"""Checks against the real models. They download weights, so CI skips them."""

from __future__ import annotations

import numpy as np
import pytest

from yojana.config import EmbeddingConfig, RerankerConfig
from yojana.index.embedder import Embedder
from yojana.retrieve.rerank import Reranker

pytestmark = pytest.mark.slow


def test_e5_embeddings_are_normalised_and_multilingual() -> None:
    embedder = Embedder(EmbeddingConfig())
    passages = embedder.encode_passages(
        ["Documents required: Aadhaar card and income certificate.", "Seed grant for startups."]
    )
    assert np.allclose(np.linalg.norm(passages, axis=1), 1.0, atol=1e-4)
    hindi = embedder.encode_query("आवश्यक दस्तावेज़ कौन से हैं?")
    assert float(passages[0] @ hindi) > float(passages[1] @ hindi)


def test_cross_encoder_prefers_relevant_passage() -> None:
    reranker = Reranker(RerankerConfig())
    scores = reranker.score(
        "Which documents are needed?",
        ["Documents required: Aadhaar card.", "The weather is pleasant today."],
    )
    assert 0.0 <= min(scores) <= max(scores) <= 1.0
    assert scores[0] > scores[1]
