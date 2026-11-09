from __future__ import annotations

from pathlib import Path

from yojana.index.bm25 import BM25Index, tokenize


def test_tokenizer_english_lowercases_stems_and_drops_stopwords() -> None:
    assert tokenize("What are the Documents for Scholarships?") == ["document", "scholarship"]


def test_tokenizer_keeps_devanagari_words_whole() -> None:
    assert tokenize("आवश्यक दस्तावेज़ क्या हैं।") == ["आवश्यक", "दस्तावेज़"]
    assert tokenize("किसानों के लिए योजना") == ["किसानों", "योजना"]


def test_tokenizer_handles_mixed_script_and_numbers() -> None:
    assert tokenize("PM-KISAN योजना 2026 के लिए") == ["pm", "kisan", "योजना", "2026"]


def test_tokenizer_nfc_normalisation_matches_decomposed_nukta() -> None:
    composed = "ज़"
    decomposed = "ज़"
    assert tokenize(composed) == tokenize(decomposed)


def test_bm25_ranks_and_filters() -> None:
    index = BM25Index.build(
        ["a", "b", "c"],
        [
            "scholarship for graduate students",
            "seed grant for startup founders",
            "farmer irrigation subsidy in Maharashtra",
        ],
    )
    assert index.search("startup grant", 3)[0][0] == "b"
    assert index.search("scholarship students", 3, allowed={"b", "c"}) == []
    assert index.search("the of and", 3) == []


def test_bm25_hindi_query() -> None:
    index = BM25Index.build(["en", "hi"], ["documents required", "आवश्यक दस्तावेज़ आधार कार्ड"])
    assert index.search("आधार कार्ड", 2)[0][0] == "hi"


def test_bm25_persistence_round_trip(tmp_path: Path) -> None:
    index = BM25Index.build(["a", "b"], ["alpha scheme benefits", "beta scheme eligibility"])
    path = tmp_path / "bm25.json"
    index.save(path)
    loaded = BM25Index.load(path)
    assert loaded.search("eligibility", 1) == index.search("eligibility", 1)
    assert len(BM25Index.load(tmp_path / "missing.json")) == 0
