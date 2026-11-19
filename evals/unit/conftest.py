import hashlib
from pathlib import Path

import pytest

from src import chat_view, gmail_client, storage

# Captured now, before any test's fixture can set JOB_HUNTER_DATA_DIR /
# JOB_HUNTER_ENV_FILE - always the real project data/ directory and .env
# file, since storage.data_dir()/chat_view.env_path() are resolved fresh
# from the env var on every call rather than cached at import time.
_REAL_DATA_DIR = storage.data_dir()
_REAL_ENV_PATH = chat_view.env_path()


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

    storage.data_dir()/gmail_client.data_dir()/chat_view.env_path() all
    resolve JOB_HUNTER_DATA_DIR / JOB_HUNTER_ENV_FILE fresh on every call
    (see storage.data_dir()'s docstring) rather than caching a path at
    import time, so setting the env vars here is sufficient on its own -
    no module-attribute patching needed, and it holds up across whatever
    reload Streamlit's AppTest triggers between runs.
    """
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JOB_HUNTER_DATA_DIR", str(data_dir))
    # Isolate from whatever the developer machine running this test suite
    # has configured for the real app - tests set these explicitly per test.
    monkeypatch.delenv(gmail_client.CLIENT_ID_ENV_VAR, raising=False)
    monkeypatch.delenv(gmail_client.CLIENT_SECRET_ENV_VAR, raising=False)
    monkeypatch.delenv(gmail_client.REDIRECT_URI_ENV_VAR, raising=False)
    monkeypatch.delenv(gmail_client.TOKEN_ENCRYPTION_KEY_ENV_VAR, raising=False)
    # _get_secret() checks st.secrets before env vars - without this, a real
    # .streamlit/secrets.toml on the machine running the tests (e.g. the
    # developer's own OAuth config) would leak into test results instead of
    # the env vars tests set explicitly.
    monkeypatch.setattr(gmail_client.st, "secrets", {})

    env_file = tmp_path / "test.env"
    monkeypatch.setenv("JOB_HUNTER_ENV_FILE", str(env_file))
