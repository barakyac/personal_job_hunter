from src import fit_analysis, ollama_client, storage


def test_build_prompt_includes_resume_and_job_fields():
    prompt = fit_analysis.build_prompt(
        "My resume", {"company": "Acme", "title": "Backend Engineer"}, ""
    )
    assert "My resume" in prompt
    assert "Acme" in prompt
    assert "Backend Engineer" in prompt
    assert "ADDITIONAL CONTEXT" not in prompt


def test_build_prompt_includes_personal_context_when_present():
    storage.save_personal_context("Certified Kubernetes Admin")
    prompt = fit_analysis.build_prompt("My resume", {"company": "Acme"}, "")
    assert "ADDITIONAL CONTEXT" in prompt
    assert "Certified Kubernetes Admin" in prompt


def test_build_prompt_includes_posting_text_when_present():
    prompt = fit_analysis.build_prompt("resume", {"company": "Acme"}, "Posting body text")
    assert "Posting body text" in prompt


def test_analyze_many_updates_records_in_place(monkeypatch):
    def fake_chat_json(system, user, model=ollama_client.DEFAULT_MODEL):
        return {"score": 8, "notes": "Strong match."}

    monkeypatch.setattr(ollama_client, "chat_json", fake_chat_json)
    monkeypatch.setattr(fit_analysis, "fetch_posting_text", lambda link, timeout=10: "")

    records = [{"company": "Acme", "link": ""}, {"company": "Globex", "link": ""}]
    errors = fit_analysis.analyze_many("resume", records, [0, 1])

    assert errors == []
    assert records[0]["fit_score"] == 8
    assert records[0]["fit_notes"] == "Strong match."
    assert records[1]["fit_score"] == 8


def test_analyze_many_collects_errors_without_raising(monkeypatch):
    def raising_chat_json(system, user, model=ollama_client.DEFAULT_MODEL):
        raise ollama_client.OllamaError("unreachable")

    monkeypatch.setattr(ollama_client, "chat_json", raising_chat_json)
    monkeypatch.setattr(fit_analysis, "fetch_posting_text", lambda link, timeout=10: "")

    records = [{"company": "Acme", "link": ""}]
    errors = fit_analysis.analyze_many("resume", records, [0])

    assert len(errors) == 1
    assert "Acme" in errors[0]
    assert "fit_score" not in records[0]
