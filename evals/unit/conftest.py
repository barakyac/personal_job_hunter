import hashlib
from pathlib import Path

import pytest

from src import chat_view, storage

# Captured now, before any test's fixture can set JOB_HUNTER_DATA_DIR /
# JOB_HUNTER_ENV_FILE or monkeypatch storage.DATA_DIR - always the real
# project data/ directory and .env file.
_REAL_DATA_DIR = storage.DATA_DIR
_REAL_ENV_PATH = chat_view.ENV_PATH


def _snapshot(data_dir: Path) -> dict[str, str]:
    if not data_dir.exists():
        return {}
    return {
        str(p.relative_to(data_dir)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in data_dir.rglob("*")
        if p.is_file()
    }


def _snapshot_file(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


@pytest.fixture(scope="session", autouse=True)
def guard_real_data_untouched():
    """Fail the whole session if anything writes to the real data/ dir or
    .env file.

    Regression guard: Streamlit's AppTest can reload src/storage.py or
    src/chat_view.py mid-test (e.g. when a view module is imported for the
    first time inside a test, after an earlier test's AppTest run triggered
    a reload), which silently drops the isolation patches below and lets a
    test write to the user's real saved/applied positions or API keys
    instead of a tmp path.
    """
    before = (_snapshot(_REAL_DATA_DIR), _snapshot_file(_REAL_ENV_PATH))
    yield
    after = (_snapshot(_REAL_DATA_DIR), _snapshot_file(_REAL_ENV_PATH))
    assert before == after, (
        "A test wrote to the REAL data/ directory or .env file instead of an isolated tmp "
        "path - check that JOB_HUNTER_DATA_DIR/JOB_HUNTER_ENV_FILE and isolated_data_dir are "
        "taking effect (see src/storage.py, src/chat_view.py, and this file's fixture)."
    )


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """Redirect storage paths into a throwaway dir so unit tests never touch
    the real data/ (your actual resume, applications, saved jobs, ...).

    Sets JOB_HUNTER_DATA_DIR first: Streamlit's AppTest reloads local
    modules (e.g. src/saved_view.py, which only gets imported on its first
    use inside a test) between runs, and a fresh reload re-reads this env
    var rather than inheriting the attribute patches below - those only
    cover code holding a reference to the module object that already
    existed when this fixture ran, not a reload that happens afterward.
    """
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JOB_HUNTER_DATA_DIR", str(data_dir))
    monkeypatch.setattr(storage, "DATA_DIR", data_dir)
    monkeypatch.setattr(storage, "SAVED_FILE", data_dir / "saved_positions.json")
    monkeypatch.setattr(storage, "APPLIED_FILE", data_dir / "applied_positions.json")
    monkeypatch.setattr(storage, "RESUME_FILE", data_dir / "resume.md")
    monkeypatch.setattr(storage, "PERSONAL_DIR", data_dir / "personal")
    monkeypatch.setattr(storage, "PERSONAL_CONTEXT_FILE", data_dir / "personal_context.md")

    env_file = tmp_path / "test.env"
    monkeypatch.setenv("JOB_HUNTER_ENV_FILE", str(env_file))
    monkeypatch.setattr(chat_view, "ENV_PATH", env_file)
