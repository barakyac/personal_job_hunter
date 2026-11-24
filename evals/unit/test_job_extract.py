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

    fields = job_extract.extract_fields("Acme is hiring a Backend Engineer in Remote for 100k.")

    assert fields == {
        "company": "Acme",
        "title": "Backend Engineer",
        "location": "Remote",
        "salary": "100k",
        "unverified": [],
    }


def test_extract_fields_defaults_missing_keys_to_empty_string(monkeypatch):
    monkeypatch.setattr(ollama_client, "chat_json", lambda system, user, model=job_extract.DEFAULT_MODEL: {})

    fields = job_extract.extract_fields("posting text")

    assert fields == {"company": "", "title": "", "location": "", "salary": "", "unverified": []}


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


def test_unverified_fields_flags_a_value_with_no_overlap_with_the_source_text():
    fields = {"company": "Acme", "title": "", "location": "", "salary": ""}

    assert job_extract.unverified_fields(fields, "Nothing in here mentions that company.") == ["company"]


def test_unverified_fields_accepts_case_and_punctuation_differences():
    fields = {"company": "Acme, Inc.", "title": "", "location": "", "salary": ""}

    assert job_extract.unverified_fields(fields, "ACME INC is hiring.") == []


def test_unverified_fields_ignores_stealth_startup_placeholder():
    fields = {"company": "Stealth Startup", "title": "", "location": "", "salary": ""}

    assert job_extract.unverified_fields(fields, "A posting that never names the company.") == []


def test_unverified_fields_ignores_empty_values():
    fields = {"company": "", "title": "", "location": "", "salary": ""}

    assert job_extract.unverified_fields(fields, "anything") == []


def test_extract_fields_flags_a_hallucinated_value(monkeypatch):
    def fake_chat_json(system, user, model=job_extract.DEFAULT_MODEL):
        return {"company": "Acme", "title": "Backend Engineer", "location": "Mars", "salary": ""}

    monkeypatch.setattr(ollama_client, "chat_json", fake_chat_json)

    fields = job_extract.extract_fields("Acme is hiring a Backend Engineer.")

    # "Mars" appears nowhere in the posting - the model invented a location.
    assert fields["unverified"] == ["location"]


# Regression fixtures: real job-alert emails that previously produced wrong
# Saved Positions. Both are Glassdoor's digest-alert shape - the subject
# names the one job this email is "about", but Gmail's snippet field is the
# hidden preheader text, which names a *different* job card's company from
# the same digest. Before extract_opportunity_fields's deterministic subject
# parse, feeding subject+snippet through the generic LLM path picked the
# snippet's unrelated company both times: "QA Automation Engineer at Questar
# Auto Technologies..." produced company="<Hebrew company name from the
# snippet>", and "Software Engineer at Check Point Software Technologies..."
# produced company="Apple" (also from the snippet) with an empty title.
QUESTAR_SUBJECT = (
    "QA Automation Engineer at Questar Auto Technologies and 10 more jobs "
    "in Tel Aviv-Yafo for you. Apply Now."
)
QUESTAR_SNIPPET = 'עידור מחשבים בע"מ is hiring'

CHECK_POINT_SUBJECT = (
    "Software Engineer at Check Point Software Technologies and 10 more jobs "
    "in Tel Aviv-Yafo for you. Apply Now."
)
CHECK_POINT_SNIPPET = "Apple is hiring"


def test_extract_opportunity_fields_parses_glassdoor_digest_subject_deterministically(monkeypatch):
    """No Ollama call at all for this shape - see the module comment on
    _GLASSDOOR_DIGEST_RE. monkeypatching chat_json to raise proves it: if
    the code fell back to the LLM path here, this test would fail with an
    OllamaError instead of an assertion mismatch."""

    def raising_chat_json(system, user, model=job_extract.DEFAULT_MODEL):
        raise ollama_client.OllamaError("should not be called for this subject shape")

    monkeypatch.setattr(ollama_client, "chat_json", raising_chat_json)

    fields = job_extract.extract_opportunity_fields(QUESTAR_SUBJECT, QUESTAR_SNIPPET)

    assert fields == {
        "company": "Questar Auto Technologies",
        "title": "QA Automation Engineer",
        "location": "Tel Aviv-Yafo",
        "salary": "",
        "unverified": [],
    }


def test_extract_opportunity_fields_ignores_misleading_glassdoor_snippet(monkeypatch):
    """The snippet names "Apple" - a different job card in the same digest.
    The real bug: that snippet text won the extraction over the subject's
    actual company. Raising from chat_json (never reached for this subject
    shape) also guards against a regression back to the LLM path."""

    def raising_chat_json(system, user, model=job_extract.DEFAULT_MODEL):
        raise ollama_client.OllamaError("should not be called for this subject shape")

    monkeypatch.setattr(ollama_client, "chat_json", raising_chat_json)

    fields = job_extract.extract_opportunity_fields(CHECK_POINT_SUBJECT, CHECK_POINT_SNIPPET)

    assert fields["company"] == "Check Point Software Technologies"
    assert fields["company"] != "Apple"
    assert fields["title"] == "Software Engineer"
    assert fields["location"] == "Tel Aviv-Yafo"


def test_extract_opportunity_fields_falls_back_to_llm_for_non_digest_subject(monkeypatch):
    """A LinkedIn-style "<company> is hiring: <title>" subject (or anything
    else that doesn't match the Glassdoor digest shape) still goes through
    the LLM, with both the subject and snippet passed into the prompt."""
    seen = {}

    def fake_chat_json(system, user, model=job_extract.DEFAULT_MODEL):
        seen["system"] = system
        seen["user"] = user
        return {"company": "Mars Security", "title": "Senior Software Engineer", "location": "", "salary": ""}

    monkeypatch.setattr(ollama_client, "chat_json", fake_chat_json)

    fields = job_extract.extract_opportunity_fields(
        "Mars Security is hiring: Senior Software Engineer",
        "Mars Security Senior Software Engineer: About Mars Security...",
    )

    assert fields == {
        "company": "Mars Security",
        "title": "Senior Software Engineer",
        "location": "",
        "salary": "",
        "unverified": [],
    }
    assert "Mars Security is hiring: Senior Software Engineer" in seen["user"]
    assert "About Mars Security" in seen["user"]
    # The prompt should steer the model toward the subject over the snippet
    # when they conflict - see OPPORTUNITY_SYSTEM_PROMPT.
    assert "snippet" in seen["system"].lower()


def test_extract_opportunity_fields_flags_unverified_value_from_llm_path(monkeypatch):
    monkeypatch.setattr(
        ollama_client,
        "chat_json",
        lambda system, user, model=job_extract.DEFAULT_MODEL: {
            "company": "Mars Security", "title": "Senior Software Engineer", "location": "Jupiter", "salary": ""
        },
    )

    fields = job_extract.extract_opportunity_fields(
        "Mars Security is hiring: Senior Software Engineer",
        "Mars Security Senior Software Engineer: About Mars Security...",
    )

    # "Jupiter" is nowhere in the subject or snippet - the model invented it.
    assert fields["unverified"] == ["location"]
