import pytest

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


def test_build_prompt_includes_the_stated_required_years_when_present():
    prompt = fit_analysis.build_prompt("resume", {"company": "Acme", "required_years_min": 5}, "")
    assert "Stated required experience: 5+ years" in prompt


def test_build_prompt_omits_the_required_years_line_when_absent():
    prompt = fit_analysis.build_prompt("resume", {"company": "Acme"}, "")
    assert "Stated required experience" not in prompt


def test_build_prompt_distinguishes_unmentioned_from_confirmed_gaps():
    prompt = fit_analysis.build_prompt("resume", {"company": "Acme"}, "")
    assert "required_gaps" in prompt and "preferred_gaps" in prompt and "unknowns" in prompt
    assert "not mentioned" in prompt.lower()


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


def test_analyze_with_posting_text_joins_evidence_lists_into_text_fields(monkeypatch):
    def fake_chat_json(system, user, model=ollama_client.DEFAULT_MODEL):
        return {
            "score": 7, "notes": "Decent overall.",
            "matched": ["Python: 5 years on resume vs posting's 3+ requirement"],
            "required_gaps": ["Posting requires AWS; resume only shows GCP"],
            "preferred_gaps": ["Kubernetes preferred; resume doesn't show it"],
            "unknowns": ["Posting asks about on-call experience; resume doesn't say"],
        }

    monkeypatch.setattr(ollama_client, "chat_json", fake_chat_json)

    result = fit_analysis.analyze_with_posting_text("resume", {"company": "Acme"}, "posting text")

    assert result["fit_score"] == 7
    assert "Python: 5 years" in result["fit_matched"]
    assert "AWS" in result["fit_required_gaps"]
    assert "Kubernetes" in result["fit_preferred_gaps"]
    assert "on-call" in result["fit_unknowns"]


def test_analyze_with_posting_text_handles_missing_evidence_lists_gracefully(monkeypatch):
    # The model's instructed to always return these keys, but a bare score/
    # notes response (like the rest of this test file's older-style mocks)
    # must not blow up - every field just comes back empty.
    monkeypatch.setattr(ollama_client, "chat_json", lambda *a, **k: {"score": 5, "notes": "ok"})

    result = fit_analysis.analyze_with_posting_text("resume", {"company": "Acme"}, "")

    assert result["fit_matched"] == ""
    assert result["fit_required_gaps"] == ""
    assert result["fit_preferred_gaps"] == ""
    assert result["fit_unknowns"] == ""


def test_analyze_with_posting_text_raises_ollama_error_on_a_malformed_evidence_field(monkeypatch):
    # Regression test: a scalar instead of a list for one of the evidence
    # fields (a real risk from a local model under format:"json") used to
    # raise a bare TypeError from inside _join_items's iteration - caught
    # nowhere, indistinguishable from an unrelated bug, and (via
    # job_matching.score_matches's loop) silently aborting every other
    # record still waiting to be scored in the same batch.
    monkeypatch.setattr(
        ollama_client, "chat_json", lambda *a, **k: {"score": 5, "notes": "ok", "matched": True}
    )

    with pytest.raises(ollama_client.OllamaError, match="Expected a list"):
        fit_analysis.analyze_with_posting_text("resume", {"company": "Acme"}, "")


def test_analyze_uses_stored_description_without_fetching(monkeypatch):
    def fail_if_called(link, timeout=10):
        raise AssertionError("fetch_posting_text should not be called when description is stored")

    captured_prompts = []

    def fake_chat_json(system, user, model=ollama_client.DEFAULT_MODEL):
        captured_prompts.append(user)
        return {"score": 7, "notes": "ok"}

    monkeypatch.setattr(fit_analysis, "fetch_posting_text", fail_if_called)
    monkeypatch.setattr(ollama_client, "chat_json", fake_chat_json)

    job = {"company": "Acme", "link": "https://acme.example/job", "description": "Stored posting text"}
    fit_analysis.analyze("resume", job)

    assert "Stored posting text" in captured_prompts[0]


def test_analyze_fetches_when_no_description_stored(monkeypatch):
    monkeypatch.setattr(fit_analysis, "fetch_posting_text", lambda link, timeout=10: "Freshly fetched text")

    captured_prompts = []

    def fake_chat_json(system, user, model=ollama_client.DEFAULT_MODEL):
        captured_prompts.append(user)
        return {"score": 7, "notes": "ok"}

    monkeypatch.setattr(ollama_client, "chat_json", fake_chat_json)

    job = {"company": "Acme", "link": "https://acme.example/job"}
    fit_analysis.analyze("resume", job)

    assert "Freshly fetched text" in captured_prompts[0]


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
