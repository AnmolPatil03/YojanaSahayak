from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from yojana.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def tmp_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A throwaway project root with the real config files copied in."""
    shutil.copytree(REPO_ROOT / "config", tmp_path / "config")
    for key in ("GROQ_API_KEY", "GITHUB_TOKEN", "OPENROUTER_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    return tmp_path


@pytest.fixture
def settings(tmp_root: Path) -> Settings:
    s = Settings(root_dir=tmp_root, _env_file=None)
    s.ensure_dirs()
    return s
