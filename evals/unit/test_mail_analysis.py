from src import mail_analysis, ollama_client, storage

MESSAGES = [
    {
        "subject": "Update on your application",
        "sender": "Acme HR <hr@acme.example>",
        "date": "Mon, 1 Jan 2026 10:00:00 +0000",
        "snippet": "Unfortunately we will not be moving forward with your application.",
    }
]


def test_build_prompt_includes_company_and_messages():
    prompt = mail_analysis.build_prompt("Acme", MESSAGES)
    assert "Acme" in prompt
    assert "Update on your application" in prompt
    assert "hr@acme.example" in prompt
    assert all(status in prompt for status in storage.STATUS_OPTIONS)


def test_build_prompt_does_not_leak_current_status():
    """The model is deliberately kept out of the current-vs-implied status
    comparison (see analyze_company_mail) - the prompt must not even
    mention a current status, only ask what the emails show."""
    prompt = mail_analysis.build_prompt("Acme", MESSAGES)
    assert "current status" not in prompt.lower()
    assert "implied_status" in prompt


def test_analyze_company_mail_returns_none_when_no_messages():
    result = mail_analysis.analyze_company_mail("Acme", "Applied", [])
    assert result == {"action": "none", "new_status": "", "reason": ""}


def test_analyze_company_mail_flags_an_implied_status_different_from_current(monkeypatch):
    def fake_chat_json(system, user, model=ollama_client.DEFAULT_MODEL):
        return {"implied_status": "Rejected", "reason": "Clear rejection email."}

    monkeypatch.setattr(ollama_client, "chat_json", fake_chat_json)

    result = mail_analysis.analyze_company_mail("Acme", "Applied", MESSAGES)

    assert result["action"] == "update_status"
    assert result["new_status"] == "Rejected"
    assert result["reason"] == "Clear rejection email."


def test_analyze_company_mail_rejects_unknown_status(monkeypatch):
    def fake_chat_json(system, user, model=ollama_client.DEFAULT_MODEL):
        return {"implied_status": "Ghosted", "reason": "made up status"}

    monkeypatch.setattr(ollama_client, "chat_json", fake_chat_json)

    result = mail_analysis.analyze_company_mail("Acme", "Applied", MESSAGES)

    assert result["action"] == "none"
    assert result["new_status"] == ""


def test_analyze_company_mail_treats_same_status_as_no_change(monkeypatch):
    """Regression guard for the original bug: the model used to be asked
    to compare against current_status itself and often got this exact case
    wrong (e.g. explaining a rejection in "reason" but still returning
    action: "none" for an *actual* change). Now the model only reports what
    it sees, and the current-vs-implied comparison is plain Python, so this
    "already there" case is trivially correct and the "different" case
    (tested above) can no longer silently fail the same way."""
    def fake_chat_json(system, user, model=ollama_client.DEFAULT_MODEL):
        return {"implied_status": "Applied", "reason": "nothing new"}

    monkeypatch.setattr(ollama_client, "chat_json", fake_chat_json)

    result = mail_analysis.analyze_company_mail("Acme", "Applied", MESSAGES)

    assert result["action"] == "none"
    assert result["new_status"] == ""


def test_analyze_company_mail_passes_through_no_signal(monkeypatch):
    def fake_chat_json(system, user, model=ollama_client.DEFAULT_MODEL):
        return {"implied_status": "", "reason": "just a LinkedIn alert"}

    monkeypatch.setattr(ollama_client, "chat_json", fake_chat_json)

    result = mail_analysis.analyze_company_mail("Acme", "Applied", MESSAGES)

    assert result["action"] == "none"
    assert result["reason"] == "just a LinkedIn alert"


def test_analyze_company_mail_accepts_case_insensitive_status(monkeypatch):
    def fake_chat_json(system, user, model=ollama_client.DEFAULT_MODEL):
        return {"implied_status": "rejected", "reason": "lowercase from the model"}

    monkeypatch.setattr(ollama_client, "chat_json", fake_chat_json)

    result = mail_analysis.analyze_company_mail("Acme", "Applied", MESSAGES)

    assert result["action"] == "update_status"
    assert result["new_status"] == "Rejected"


def test_analyze_company_mail_handles_non_dict_response(monkeypatch):
    def fake_chat_json(system, user, model=ollama_client.DEFAULT_MODEL):
        return ["unexpected", "list"]

    monkeypatch.setattr(ollama_client, "chat_json", fake_chat_json)

    result = mail_analysis.analyze_company_mail("Acme", "Applied", MESSAGES)

    assert result == {"action": "none", "new_status": "", "reason": ""}


def test_analyze_company_mail_defaults_missing_reason_to_empty_string(monkeypatch):
    def fake_chat_json(system, user, model=ollama_client.DEFAULT_MODEL):
        return {"implied_status": ""}

    monkeypatch.setattr(ollama_client, "chat_json", fake_chat_json)

    result = mail_analysis.analyze_company_mail("Acme", "Applied", MESSAGES)

    assert result["reason"] == ""


def test_analyze_company_mail_forwards_model_argument(monkeypatch):
    captured = {}

    def fake_chat_json(system, user, model=ollama_client.DEFAULT_MODEL):
        captured["model"] = model
        return {"implied_status": "", "reason": ""}

    monkeypatch.setattr(ollama_client, "chat_json", fake_chat_json)

    mail_analysis.analyze_company_mail("Acme", "Applied", MESSAGES, model="custom-model")

    assert captured["model"] == "custom-model"


def test_build_prompt_defines_first_call_as_covering_screening_interviews():
    """Regression guard: the model previously read a 'screening interview'
    email as First Call -> Interview, when a screening call/interview *is*
    this app's First Call stage. The prompt must say so explicitly."""
    prompt = mail_analysis.build_prompt("Acme", MESSAGES)
    first_call_line = next(line for line in prompt.splitlines() if line.startswith("- First Call:"))
    assert "screening" in first_call_line.lower()


def test_build_prompt_includes_a_definition_for_every_status():
    prompt = mail_analysis.build_prompt("Acme", MESSAGES)
    for status in storage.STATUS_OPTIONS:
        assert f"- {status}:" in prompt


REJECTION_MESSAGE = {
    "subject": "Thank you for applying for the Backend Engineer position at PAPAYA",
    "sender": "PAPAYA <no-reply@careers.papayagaming.com>",
    "date": "Tue, 20 Oct 2026 10:02:03 +0000",
    "snippet": "After reviewing your experience and qualifications, we decided to move forward with other candidates.",
    "looks_like_rejection": True,
}


def test_analyze_company_mail_catches_rejection_via_keyword_heuristic_without_calling_ollama(monkeypatch):
    """The model was demonstrably unreliable at catching rejections once
    "think" was disabled for speed (see analyze_company_mail's docstring) -
    this case must be decided by the keyword heuristic alone, never Ollama."""
    def fail_if_called(system, user, model=ollama_client.DEFAULT_MODEL):
        raise AssertionError("Ollama should not be called when a rejection is keyword-flagged")

    monkeypatch.setattr(ollama_client, "chat_json", fail_if_called)

    result = mail_analysis.analyze_company_mail("PAPAYA", "Applied", [REJECTION_MESSAGE])

    assert result["action"] == "update_status"
    assert result["new_status"] == "Rejected"
    assert "PAPAYA" in result["reason"]


def test_analyze_company_mail_skips_rejection_shortcut_when_already_in_a_terminal_status(monkeypatch):
    """No point re-flagging a rejection once the application is already
    Rejected/Offer/Withdrawn - falls through to the normal model path."""
    def fake_chat_json(system, user, model=ollama_client.DEFAULT_MODEL):
        return {"implied_status": "", "reason": "nothing new"}

    monkeypatch.setattr(ollama_client, "chat_json", fake_chat_json)

    result = mail_analysis.analyze_company_mail("PAPAYA", "Rejected", [REJECTION_MESSAGE])

    assert result["action"] == "none"


def test_analyze_company_mail_falls_through_to_ollama_when_no_message_looks_like_a_rejection(monkeypatch):
    def fake_chat_json(system, user, model=ollama_client.DEFAULT_MODEL):
        return {"implied_status": "First Call", "reason": "screening call scheduled"}

    monkeypatch.setattr(ollama_client, "chat_json", fake_chat_json)

    result = mail_analysis.analyze_company_mail("Acme", "Applied", MESSAGES)

    assert result["action"] == "update_status"
    assert result["new_status"] == "First Call"


def test_analyze_company_mail_treats_applied_as_no_signal_rather_than_a_regression(monkeypatch):
    """Regression guard: observed live, the model sometimes defaults to
    "Applied" (first in the possible-stages list) even when its own
    "reason" says there's no real stage signal - which would otherwise
    regress an already-further-along application (e.g. Rejected) back to
    the baseline stage. No real email content legitimately does that."""
    def fake_chat_json(system, user, model=ollama_client.DEFAULT_MODEL):
        return {"implied_status": "Applied", "reason": "no specific stage signals present"}

    monkeypatch.setattr(ollama_client, "chat_json", fake_chat_json)

    result = mail_analysis.analyze_company_mail("Acme", "Rejected", MESSAGES)

    assert result["action"] == "none"
    assert result["new_status"] == ""
