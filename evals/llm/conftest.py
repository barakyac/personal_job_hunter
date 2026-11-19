import pytest


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """Keep these evals deterministic and off your real data - fit_analysis
    reads personal_context.md as part of every prompt, so without this an
    eval run would silently mix in your real supporting docs.

    storage.data_dir() resolves JOB_HUNTER_DATA_DIR fresh on every call (see
    its docstring), so setting the env var here is sufficient on its own."""
    data_dir = tmp_path / "data"
    monkeypatch.setenv("JOB_HUNTER_DATA_DIR", str(data_dir))
