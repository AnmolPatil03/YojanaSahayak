from __future__ import annotations

from pathlib import Path

import pytest

from yojana.config import RetrievalConfig, ScraperConfig, Settings, load_yaml


def test_providers_load_in_priority_order(settings: Settings) -> None:
    names = [p.name for p in settings.providers()]
    assert names == ["groq", "github", "openrouter", "gemini", "ollama"]


def test_only_gemini_is_flagged_as_training_on_free_tier(settings: Settings) -> None:
    flagged = {p.name for p in settings.providers() if p.trains_on_free_tier_data}
    assert flagged == {"gemini"}


def test_ollama_url_and_model_come_from_environment(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:9999")
    monkeypatch.setenv("OLLAMA_MODEL", "custom-model:1b")
    ollama = next(p for p in settings.providers() if p.name == "ollama")
    assert ollama.base_url == "http://127.0.0.1:9999/v1"
    assert ollama.model == "custom-model:1b"


def test_ollama_defaults_without_environment(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    ollama = next(p for p in settings.providers() if p.name == "ollama")
    assert ollama.base_url == "http://localhost:11434/v1"
    assert ollama.offline


def test_retrieval_config_matches_defaults(settings: Settings) -> None:
    cfg = settings.retrieval()
    assert isinstance(cfg, RetrievalConfig)
    assert cfg.rrf_k == 60
    assert cfg.rerank_candidates == 20
    assert cfg.final_top_k == 5
    assert cfg.embedding.query_prefix == "query: "


def test_scraper_delay_never_below_two_seconds() -> None:
    assert ScraperConfig(min_delay_s=0.1).min_delay_s == 2.0


def test_env_expansion_in_yaml(tmp_path: Path) -> None:
    path = tmp_path / "x.yaml"
    path.write_text("a: ${FOO}\nb: ${MISSING:-fallback}\nc:\n  - ${FOO}\n", encoding="utf-8")
    assert load_yaml(path, {"FOO": "bar"}) == {"a": "bar", "b": "fallback", "c": ["bar"]}


def test_secret_reads_dotenv_file(tmp_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_root / ".env").write_text("GROQ_API_KEY=from-file\n", encoding="utf-8")
    s = Settings(root_dir=tmp_root, _env_file=None)
    assert s.secret("GROQ_API_KEY") == "from-file"
    monkeypatch.setenv("GROQ_API_KEY", "from-env")
    assert s.secret("GROQ_API_KEY") == "from-env"
