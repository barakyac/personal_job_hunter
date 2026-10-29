import pytest

from src import storage


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """Redirect storage paths into a throwaway dir so unit tests never touch
    the real data/ (your actual resume, applications, saved jobs, ...)."""
    data_dir = tmp_path / "data"
    monkeypatch.setattr(storage, "DATA_DIR", data_dir)
    monkeypatch.setattr(storage, "SAVED_FILE", data_dir / "saved_positions.json")
    monkeypatch.setattr(storage, "APPLIED_FILE", data_dir / "applied_positions.json")
    monkeypatch.setattr(storage, "RESUME_FILE", data_dir / "resume.md")
    monkeypatch.setattr(storage, "PERSONAL_DIR", data_dir / "personal")
    monkeypatch.setattr(storage, "PERSONAL_CONTEXT_FILE", data_dir / "personal_context.md")
