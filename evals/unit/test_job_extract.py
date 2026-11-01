import pytest

from src import job_extract, ollama_client


def test_build_prompt_includes_posting_text():
    prompt = job_extract.build_prompt("We are hiring a Backend Engineer at Acme.")
    assert "We are hiring a Backend Engineer at Acme." in prompt


def test_build_prompt_instructs_stealth_startup_fallback():
    prompt = job_extract.build_prompt("Some posting")
    assert "Stealth Startup" in prompt


def test_extract_fields_returns_model_values(monkeypatch):
    def fake_chat_json(system, user, model=job_extract.DEFAULT_MODEL):
        return {"company": "Acme", "title": "Backend Engineer", "location": "Remote", "salary": "100k"}

    monkeypatch.setattr(ollama_client, "chat_json", fake_chat_json)

    fields = job_extract.extract_fields("posting text")

    assert fields == {
        "company": "Acme",
        "title": "Backend Engineer",
        "location": "Remote",
        "salary": "100k",
    }


def test_extract_fields_defaults_missing_keys_to_empty_string(monkeypatch):
    monkeypatch.setattr(ollama_client, "chat_json", lambda system, user, model=job_extract.DEFAULT_MODEL: {})

    fields = job_extract.extract_fields("posting text")

    assert fields == {"company": "", "title": "", "location": "", "salary": ""}


def test_extract_fields_treats_null_values_as_empty_string(monkeypatch):
    def fake_chat_json(system, user, model=job_extract.DEFAULT_MODEL):
        return {"company": None, "title": "Backend Engineer", "location": None, "salary": None}

    monkeypatch.setattr(ollama_client, "chat_json", fake_chat_json)

    fields = job_extract.extract_fields("posting text")

    assert fields["company"] == ""
    assert fields["title"] == "Backend Engineer"
    assert fields["location"] == ""
    assert fields["salary"] == ""


def test_extract_fields_uses_its_own_default_model(monkeypatch):
    seen_models = []

    def fake_chat_json(system, user, model=job_extract.DEFAULT_MODEL):
        seen_models.append(model)
        return {}

    monkeypatch.setattr(ollama_client, "chat_json", fake_chat_json)

    job_extract.extract_fields("posting text")

    assert seen_models == [job_extract.DEFAULT_MODEL]
    assert job_extract.DEFAULT_MODEL != ollama_client.DEFAULT_MODEL


def test_extract_fields_propagates_ollama_error(monkeypatch):
    def raising_chat_json(system, user, model=job_extract.DEFAULT_MODEL):
        raise ollama_client.OllamaError("unreachable")

    monkeypatch.setattr(ollama_client, "chat_json", raising_chat_json)

    with pytest.raises(ollama_client.OllamaError):
        job_extract.extract_fields("posting text")
