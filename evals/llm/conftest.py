import pytest

from src import storage


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """Keep these evals deterministic and off your real data - fit_analysis
    reads personal_context.md as part of every prompt, so without this an
    eval run would silently mix in your real supporting docs."""
    data_dir = tmp_path / "data"
    monkeypatch.setattr(storage, "DATA_DIR", data_dir)
    monkeypatch.setattr(storage, "PERSONAL_DIR", data_dir / "personal")
    monkeypatch.setattr(storage, "PERSONAL_CONTEXT_FILE", data_dir / "personal_context.md")
