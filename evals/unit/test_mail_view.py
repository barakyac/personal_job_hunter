from cryptography.fernet import Fernet
from streamlit.testing.v1 import AppTest

from src import gmail_client, job_extract, mail_analysis, ollama_client, storage


def _render_mail():
    from src import mail_view

    mail_view.render()


def _connect() -> None:
    """Mark Gmail as already connected for tests that only care about the
    post-connect scan flow."""
    gmail_client.DATA_DIR.mkdir(parents=True, exist_ok=True)
    gmail_client.TOKEN_FILE.write_text("{}", encoding="utf-8")


def _configure_app(monkeypatch) -> None:
    monkeypatch.setenv(gmail_client.CLIENT_ID_ENV_VAR, "client-id")
    monkeypatch.setenv(gmail_client.CLIENT_SECRET_ENV_VAR, "client-secret")
    monkeypatch.setenv(gmail_client.TOKEN_ENCRYPTION_KEY_ENV_VAR, Fernet.generate_key().decode())


def _fake_authorize_button(results: dict | None = None):
    """Stand in for mail_view._authorize_button, whose real implementation
    drives a browser popup via a custom Streamlit component that AppTest
    can't click. Tests instead control what a completed (or not-yet-
    completed) popup would return, keyed by the component `key` ("
    connect_gmail_oauth" / "reconnect_gmail_oauth") - defaulting to "not
    clicked yet" (None). A configured result is consumed (popped) on first
    return, like the real component's result does after a popup completes -
    otherwise a rerun after a successful connect would "click" the same
    button again on every subsequent run and loop forever."""
    results = dict(results or {})

    def _fake(label, key):
        return results.pop(key, None)

    return _fake


def test_shows_connect_with_google_button_when_not_connected(monkeypatch):
    _configure_app(monkeypatch)
    from src import mail_view

    monkeypatch.setattr(mail_view, "_authorize_button", _fake_authorize_button())

    at = AppTest.from_function(_render_mail).run()

    assert not at.exception
    assert any("Connect Gmail" in s.value for s in at.subheader)
    assert not at.text_input
    assert not any("Google Cloud Console" in c.value for c in at.caption)


def test_shows_friendly_error_when_app_not_configured():
    at = AppTest.from_function(_render_mail).run()

    assert not at.exception
    assert any("app owner" in e.value for e in at.error)
    assert not any("Google Cloud Console" in e.value for e in at.error)


def test_connect_popup_result_saves_token_and_reaches_connected_state(monkeypatch):
    _configure_app(monkeypatch)
    from src import mail_view

    monkeypatch.setattr(
        mail_view,
        "_authorize_button",
        _fake_authorize_button(
            {"connect_gmail_oauth": {"token": {"access_token": "at1", "refresh_token": "rt1"}}}
        ),
    )
    monkeypatch.setattr(gmail_client, "get_service", lambda: "fake-service")
    monkeypatch.setattr(gmail_client, "get_connected_email", lambda service=None: "me@gmail.com")
    monkeypatch.setattr(gmail_client, "search_messages", lambda *a, **k: [])

    at = AppTest.from_function(_render_mail).run()

    assert not at.exception
    assert gmail_client.TOKEN_FILE.exists()


def test_connect_popup_shows_friendly_error_when_no_refresh_token(monkeypatch):
    _configure_app(monkeypatch)
    from src import mail_view

    monkeypatch.setattr(
        mail_view,
        "_authorize_button",
        _fake_authorize_button({"connect_gmail_oauth": {"token": {"access_token": "at1"}}}),
    )

    at = AppTest.from_function(_render_mail).run()

    assert not at.exception
    assert any("refresh token" in e.value for e in at.error)
    assert not gmail_client.TOKEN_FILE.exists()


def test_status_bar_shows_connected_email(monkeypatch):
    _connect()
    from src import mail_view

    monkeypatch.setattr(mail_view, "_authorize_button", _fake_authorize_button(None))
    monkeypatch.setattr(gmail_client, "get_service", lambda: "fake-service")
    monkeypatch.setattr(gmail_client, "get_connected_email", lambda service=None: "me@gmail.com")
    monkeypatch.setattr(gmail_client, "search_messages", lambda *a, **k: [])

    at = AppTest.from_function(_render_mail).run()

    assert not at.exception
    assert any("me@gmail.com" in c.value for c in at.caption)
    assert any(b.label == "Disconnect Gmail" for b in at.button)


def test_status_bar_degrades_gracefully_when_profile_lookup_fails(monkeypatch):
    _connect()
    from src import mail_view

    monkeypatch.setattr(mail_view, "_authorize_button", _fake_authorize_button(None))
    monkeypatch.setattr(gmail_client, "get_service", lambda: "fake-service")

    def fake_get_connected_email(service=None):
        raise gmail_client.GmailError("quota exceeded")

    monkeypatch.setattr(gmail_client, "get_connected_email", fake_get_connected_email)
    monkeypatch.setattr(gmail_client, "search_messages", lambda *a, **k: [])

    at = AppTest.from_function(_render_mail).run()

    assert not at.exception
    assert any(c.value == "Connected" for c in at.caption)


def test_reconnect_popup_result_reruns_and_stays_connected(monkeypatch):
    _connect()
    _configure_app(monkeypatch)
    from src import mail_view

    monkeypatch.setattr(
        mail_view,
        "_authorize_button",
        _fake_authorize_button(
            {"reconnect_gmail_oauth": {"token": {"access_token": "at2", "refresh_token": "rt2"}}}
        ),
    )
    monkeypatch.setattr(gmail_client, "get_service", lambda: "fake-service")
    monkeypatch.setattr(gmail_client, "get_connected_email", lambda service=None: "me@gmail.com")
    monkeypatch.setattr(gmail_client, "search_messages", lambda *a, **k: [])

    at = AppTest.from_function(_render_mail).run()

    assert not at.exception
    decrypted = gmail_client._fernet().decrypt(gmail_client.TOKEN_FILE.read_bytes())
    assert "rt2" in decrypted.decode("utf-8")


def test_disconnect_button_clears_connection_and_shows_connect_form(monkeypatch):
    _connect()
    from src import mail_view

    monkeypatch.setattr(mail_view, "_authorize_button", _fake_authorize_button(None))
    monkeypatch.setattr(gmail_client, "get_service", lambda: "fake-service")
    monkeypatch.setattr(gmail_client, "get_connected_email", lambda service=None: "me@gmail.com")
    monkeypatch.setattr(gmail_client, "search_messages", lambda *a, **k: [])

    def fake_disconnect():
        gmail_client.TOKEN_FILE.unlink(missing_ok=True)

    monkeypatch.setattr(gmail_client, "disconnect", fake_disconnect)

    at = AppTest.from_function(_render_mail).run()
    at.button(key="disconnect_gmail_btn").click().run()

    assert not at.exception
    assert not gmail_client.TOKEN_FILE.exists()
    assert any("Connect Gmail" in s.value for s in at.subheader)


def test_shows_placeholder_when_no_applied_positions(monkeypatch):
    _connect()
    from src import mail_view

    monkeypatch.setattr(mail_view, "_authorize_button", _fake_authorize_button(None))
    monkeypatch.setattr(gmail_client, "get_service", lambda: "fake-service")
    monkeypatch.setattr(gmail_client, "get_connected_email", lambda service=None: "me@gmail.com")
    monkeypatch.setattr(gmail_client, "search_messages", lambda *a, **k: [])

    at = AppTest.from_function(_render_mail).run()

    assert not at.exception
    assert any("No applied positions yet" in i.value for i in at.info)
    assert not any(b.key == "scan_gmail_btn" for b in at.button)


def test_auto_scans_on_first_render_without_a_button_click(monkeypatch):
    _connect()
    from src import mail_view

    monkeypatch.setattr(mail_view, "_authorize_button", _fake_authorize_button(None))
    storage.save_applied(
        [
            {"company": "Acme", "title": "Backend", "status": "Applied"},
            {"company": "Globex", "title": "Frontend", "status": "Applied"},
        ]
    )
    monkeypatch.setattr(gmail_client, "get_service", lambda: "fake-service")
    monkeypatch.setattr(gmail_client, "get_connected_email", lambda service=None: "me@gmail.com")

    def fake_search(query, service=None, max_results=5):
        if query == '"Acme"':
            return [
                {
                    "id": "1",
                    "thread_id": "t1",
                    "subject": "Update on your application",
                    "sender": "hr@acme.com",
                    "date": "Mon, 1 Jan 2026",
                    "snippet": "Unfortunately, we will not be moving forward.",
                    "looks_like_rejection": True,
                }
            ]
        return []

    monkeypatch.setattr(gmail_client, "search_messages", fake_search)

    at = AppTest.from_function(_render_mail).run()

    assert not at.exception
    # Results are already visible without clicking "Rescan applications".
    assert any("look like a rejection" in w.value for w in at.warning)
    assert any("Update on your application" in m.value for m in at.markdown)
    assert any("No matching emails found." in c.value for c in at.caption)
    # A sync timestamp was recorded after the auto-scan.
    assert any("Last synced" in c.value for c in at.caption)


def test_scan_shows_auth_warning_when_token_invalid(monkeypatch):
    _connect()
    from src import mail_view

    monkeypatch.setattr(mail_view, "_authorize_button", _fake_authorize_button(None))
    storage.save_applied([{"company": "Acme", "title": "Backend", "status": "Applied"}])
    monkeypatch.setattr(gmail_client, "get_connected_email", lambda service=None: "me@gmail.com")

    def fake_get_service():
        raise gmail_client.GmailAuthError('Click "Reconnect" on the Mail Tracking page.')

    monkeypatch.setattr(gmail_client, "get_service", fake_get_service)

    at = AppTest.from_function(_render_mail).run()

    assert not at.exception
    assert any("Reconnect" in w.value for w in at.warning)


def test_rescan_applications_button_triggers_another_scan(monkeypatch):
    _connect()
    from src import mail_view

    monkeypatch.setattr(mail_view, "_authorize_button", _fake_authorize_button(None))
    storage.save_applied([{"company": "Acme", "title": "Backend", "status": "Applied"}])
    monkeypatch.setattr(gmail_client, "get_service", lambda: "fake-service")
    monkeypatch.setattr(gmail_client, "get_connected_email", lambda service=None: "me@gmail.com")

    call_count = {"acme": 0}

    def fake_search(query, service=None, max_results=5):
        if query == '"Acme"':
            call_count["acme"] += 1
        return []

    monkeypatch.setattr(gmail_client, "search_messages", fake_search)

    at = AppTest.from_function(_render_mail).run()
    assert call_count["acme"] == 1  # auto-scanned once on first render

    at.button(key="scan_gmail_btn").click().run()

    assert not at.exception
    assert call_count["acme"] == 2


def test_new_opportunities_section_auto_scans_and_shows_alert_banner(monkeypatch):
    _connect()
    from src import mail_view

    monkeypatch.setattr(mail_view, "_authorize_button", _fake_authorize_button(None))
    monkeypatch.setattr(gmail_client, "get_service", lambda: "fake-service")
    monkeypatch.setattr(gmail_client, "get_connected_email", lambda service=None: "me@gmail.com")

    def fake_search(query, service=None, max_results=5):
        return [
            {
                "id": "1",
                "thread_id": "t1",
                "subject": "Backend Engineer at Acme",
                "sender": "LinkedIn Job Alerts",
                "date": "Mon, 1 Jan 2026",
                "snippet": "New job alert",
                "looks_like_rejection": False,
            }
        ]

    monkeypatch.setattr(gmail_client, "search_messages", fake_search)

    at = AppTest.from_function(_render_mail).run()

    assert not at.exception
    assert any("new job-alert email" in i.value for i in at.info)
    assert any("Backend Engineer at Acme" in m.value for m in at.markdown)


def test_new_opportunities_shows_placeholder_when_none_found(monkeypatch):
    _connect()
    from src import mail_view

    monkeypatch.setattr(mail_view, "_authorize_button", _fake_authorize_button(None))
    monkeypatch.setattr(gmail_client, "get_service", lambda: "fake-service")
    monkeypatch.setattr(gmail_client, "get_connected_email", lambda service=None: "me@gmail.com")
    monkeypatch.setattr(gmail_client, "search_messages", lambda *a, **k: [])

    at = AppTest.from_function(_render_mail).run()

    assert not at.exception
    assert any("No new job-alert emails found." in c.value for c in at.caption)


def test_scan_surfaces_a_per_company_gmail_error(monkeypatch):
    _connect()
    from src import mail_view

    monkeypatch.setattr(mail_view, "_authorize_button", _fake_authorize_button(None))
    storage.save_applied([{"company": "Acme", "title": "Backend", "status": "Applied"}])
    monkeypatch.setattr(gmail_client, "get_service", lambda: "fake-service")
    monkeypatch.setattr(gmail_client, "get_connected_email", lambda service=None: "me@gmail.com")

    def fake_search(query, service=None, max_results=5):
        raise gmail_client.GmailError("Gmail search failed: quota exceeded")

    monkeypatch.setattr(gmail_client, "search_messages", fake_search)

    at = AppTest.from_function(_render_mail).run()

    assert not at.exception
    assert any("quota exceeded" in e.value for e in at.error)


def test_authorize_button_requests_offline_consent_with_exact_scopes(monkeypatch):
    _configure_app(monkeypatch)
    from src import mail_view

    captured = {}

    class _FakeOAuth2Component:
        def __init__(self, *args, **kwargs):
            captured["init_args"] = args

        def authorize_button(self, **kwargs):
            captured["authorize_kwargs"] = kwargs
            return None

    monkeypatch.setattr("streamlit_oauth.OAuth2Component", _FakeOAuth2Component)

    mail_view._authorize_button("Connect with Google", "connect_gmail_oauth")

    kwargs = captured["authorize_kwargs"]
    assert kwargs["scope"] == gmail_client.scope_string()
    assert kwargs["scope"] == " ".join(
        [
            "openid",
            "https://www.googleapis.com/auth/userinfo.email",
            "https://www.googleapis.com/auth/gmail.readonly",
        ]
    )
    assert kwargs["extras_params"] == {"access_type": "offline", "prompt": "consent"}


def test_scan_clears_connection_and_shows_expired_message_on_revoked_token(monkeypatch):
    _connect()
    from src import mail_view

    monkeypatch.setattr(mail_view, "_authorize_button", _fake_authorize_button(None))
    storage.save_applied([{"company": "Acme", "title": "Backend", "status": "Applied"}])
    monkeypatch.setattr(gmail_client, "get_connected_email", lambda service=None: "me@gmail.com")

    def fake_get_service():
        raise gmail_client.GmailAuthError(gmail_client.EXPIRED_CONNECTION_MESSAGE)

    monkeypatch.setattr(gmail_client, "get_service", fake_get_service)

    at = AppTest.from_function(_render_mail).run()

    assert not at.exception
    assert any("Your Gmail connection expired" in w.value for w in at.warning)
    assert not any(e.value for e in at.error)  # a friendly message, not a stack trace


def test_shows_setup_form_when_not_configured_and_on_localhost(monkeypatch):
    monkeypatch.setattr(gmail_client, "is_localhost_request", lambda: True)
    from src import mail_view

    monkeypatch.setattr(mail_view, "_authorize_button", _fake_authorize_button())

    at = AppTest.from_function(_render_mail).run()

    assert not at.exception
    assert any("Set up Gmail connection" in s.value for s in at.subheader)
    assert any("gmail_setup_client_id_input" in w.key for w in at.text_input)
    assert not any("app owner" in e.value for e in at.error)


def test_setup_form_hidden_from_non_localhost_visitor(monkeypatch):
    monkeypatch.setattr(gmail_client, "is_localhost_request", lambda: False)
    from src import mail_view

    monkeypatch.setattr(mail_view, "_authorize_button", _fake_authorize_button())

    at = AppTest.from_function(_render_mail).run()

    assert not at.exception
    assert not at.text_input
    assert any("app owner" in e.value for e in at.error)
    assert any("locally" in e.value for e in at.error)


def test_setup_form_shows_validation_error_for_bad_client_id(monkeypatch):
    monkeypatch.setattr(gmail_client, "is_localhost_request", lambda: True)
    from src import mail_view

    monkeypatch.setattr(mail_view, "_authorize_button", _fake_authorize_button())

    at = AppTest.from_function(_render_mail).run()
    at.text_input(key="gmail_setup_client_id_input").set_value("not-a-real-client-id")
    at.text_input(key="gmail_setup_client_secret_input").set_value("some-secret")
    at.button(key="gmail_setup_submit_btn").click().run()

    assert not at.exception
    assert any("apps.googleusercontent.com" in e.value for e in at.error)
    assert not gmail_client.has_persisted_config()


def test_setup_form_save_configures_app_and_shows_connect_button_without_restart(monkeypatch):
    monkeypatch.setattr(gmail_client, "is_localhost_request", lambda: True)
    from src import mail_view

    monkeypatch.setattr(mail_view, "_authorize_button", _fake_authorize_button())

    at = AppTest.from_function(_render_mail).run()
    at.text_input(key="gmail_setup_client_id_input").set_value("123.apps.googleusercontent.com")
    at.text_input(key="gmail_setup_client_secret_input").set_value("shh-secret")
    at = at.button(key="gmail_setup_submit_btn").click().run()

    assert not at.exception
    assert gmail_client.is_app_configured()
    # Takes effect immediately in this same run - no restart needed - and the
    # normal "Connect with Google" flow is now available.
    assert any("Connect Gmail" in s.value for s in at.subheader)
    assert not at.text_input


def test_reset_control_hidden_when_nothing_persisted(monkeypatch):
    monkeypatch.setattr(gmail_client, "is_localhost_request", lambda: True)
    from src import mail_view

    monkeypatch.setattr(mail_view, "_authorize_button", _fake_authorize_button())

    at = AppTest.from_function(_render_mail).run()

    assert not at.exception
    assert not any(b.label == "Reset Gmail setup" for b in at.button)


def test_reset_control_hidden_from_non_localhost_visitor(monkeypatch):
    gmail_client.save_oauth_config("123.apps.googleusercontent.com", "shh-secret")
    monkeypatch.setattr(gmail_client, "is_localhost_request", lambda: False)
    from src import mail_view

    monkeypatch.setattr(mail_view, "_authorize_button", _fake_authorize_button())

    at = AppTest.from_function(_render_mail).run()

    assert not at.exception
    assert not any(b.label == "Reset Gmail setup" for b in at.button)


def test_reset_control_clears_config_and_returns_to_setup_form(monkeypatch):
    gmail_client.save_oauth_config("123.apps.googleusercontent.com", "shh-secret")
    monkeypatch.setattr(gmail_client, "is_localhost_request", lambda: True)
    from src import mail_view

    monkeypatch.setattr(mail_view, "_authorize_button", _fake_authorize_button())

    at = AppTest.from_function(_render_mail).run()
    at.expander[0].expanded = True
    at = at.button(key="reset_gmail_setup_btn").click().run()

    assert not at.exception
    assert not gmail_client.has_persisted_config()
    assert not gmail_client.is_app_configured()
    assert any("Set up Gmail connection" in s.value for s in at.subheader)


def _connect_with_acme_email(monkeypatch) -> None:
    """Connect Gmail, save one applied position at Acme in "Applied" status,
    and make the auto-scan return a single email for it - the common setup
    for the "Analyze with AI" tests below."""
    _connect()
    from src import mail_view

    monkeypatch.setattr(mail_view, "_authorize_button", _fake_authorize_button(None))
    storage.save_applied([{"company": "Acme", "title": "Backend", "status": "Applied"}])
    monkeypatch.setattr(gmail_client, "get_service", lambda: "fake-service")
    monkeypatch.setattr(gmail_client, "get_connected_email", lambda service=None: "me@gmail.com")

    def fake_search(query, service=None, max_results=5):
        if query == '"Acme"':
            return [
                {
                    "subject": "Update on your application",
                    "sender": "hr@acme.com",
                    "date": "Mon, 1 Jan 2026",
                    "snippet": "Unfortunately, we will not be moving forward.",
                    "looks_like_rejection": True,
                }
            ]
        return []

    monkeypatch.setattr(gmail_client, "search_messages", fake_search)


def test_analyze_button_shows_approve_and_dismiss_for_a_suggested_status_change(monkeypatch):
    _connect_with_acme_email(monkeypatch)

    def fake_analyze(company, current_status, messages, model=ollama_client.DEFAULT_MODEL):
        assert company == "Acme"
        assert current_status == "Applied"
        return {"action": "update_status", "new_status": "Rejected", "reason": "Clear rejection."}

    monkeypatch.setattr(mail_analysis, "analyze_company_mail", fake_analyze)

    at = AppTest.from_function(_render_mail).run()
    at.expander[0].expanded = True
    at = at.button(key="analyze_mail_Acme").click().run()

    assert not at.exception
    assert any("Applied" in i.value and "Rejected" in i.value for i in at.info)
    assert any(b.key == "approve_status_Acme_panel" for b in at.button)
    assert any(b.key == "dismiss_status_Acme_panel" for b in at.button)
    # Nothing is written until the user approves.
    assert storage.load_applied()[0]["status"] == "Applied"


def test_approving_a_suggestion_updates_the_applied_record(monkeypatch):
    _connect_with_acme_email(monkeypatch)

    def fake_analyze(company, current_status, messages, model=ollama_client.DEFAULT_MODEL):
        return {"action": "update_status", "new_status": "Rejected", "reason": "Clear rejection."}

    monkeypatch.setattr(mail_analysis, "analyze_company_mail", fake_analyze)

    at = AppTest.from_function(_render_mail).run()
    at.expander[0].expanded = True
    at = at.button(key="analyze_mail_Acme").click().run()
    at = at.button(key="approve_status_Acme_panel").click().run()

    assert not at.exception
    applied = storage.load_applied()
    assert applied[0]["status"] == "Rejected"
    assert applied[0]["rejected_from_stage"] == "Applied"
    assert not any(b.key == "approve_status_Acme_panel" for b in at.button)


def test_dismissing_a_suggestion_leaves_status_unchanged(monkeypatch):
    _connect_with_acme_email(monkeypatch)

    def fake_analyze(company, current_status, messages, model=ollama_client.DEFAULT_MODEL):
        return {"action": "update_status", "new_status": "Rejected", "reason": "Clear rejection."}

    monkeypatch.setattr(mail_analysis, "analyze_company_mail", fake_analyze)

    at = AppTest.from_function(_render_mail).run()
    at.expander[0].expanded = True
    at = at.button(key="analyze_mail_Acme").click().run()
    at = at.button(key="dismiss_status_Acme_panel").click().run()

    assert not at.exception
    assert storage.load_applied()[0]["status"] == "Applied"
    assert not any(b.key == "approve_status_Acme_panel" for b in at.button)


def test_analyze_shows_caption_when_ai_finds_no_change(monkeypatch):
    _connect_with_acme_email(monkeypatch)

    def fake_analyze(company, current_status, messages, model=ollama_client.DEFAULT_MODEL):
        return {"action": "none", "new_status": "", "reason": "Just an automated notice."}

    monkeypatch.setattr(mail_analysis, "analyze_company_mail", fake_analyze)

    at = AppTest.from_function(_render_mail).run()
    at.expander[0].expanded = True
    at = at.button(key="analyze_mail_Acme").click().run()

    assert not at.exception
    assert any("no status change" in i.value for i in at.info)
    assert not any(b.key == "approve_status_Acme_panel" for b in at.button)


def test_analyze_shows_warning_when_ollama_unreachable(monkeypatch):
    _connect_with_acme_email(monkeypatch)

    def raising_analyze(company, current_status, messages, model=ollama_client.DEFAULT_MODEL):
        raise ollama_client.OllamaError("Could not reach Ollama")

    monkeypatch.setattr(mail_analysis, "analyze_company_mail", raising_analyze)

    at = AppTest.from_function(_render_mail).run()
    at.expander[0].expanded = True
    at = at.button(key="analyze_mail_Acme").click().run()

    assert not at.exception
    assert any("Could not reach Ollama" in w.value for w in at.warning)


def test_analyze_warns_when_company_has_no_single_matching_record(monkeypatch):
    _connect()
    from src import mail_view

    monkeypatch.setattr(mail_view, "_authorize_button", _fake_authorize_button(None))
    storage.save_applied(
        [
            {"company": "Acme", "title": "Backend", "status": "Applied"},
            {"company": "Acme", "title": "Frontend", "status": "First Call"},
        ]
    )
    monkeypatch.setattr(gmail_client, "get_service", lambda: "fake-service")
    monkeypatch.setattr(gmail_client, "get_connected_email", lambda service=None: "me@gmail.com")
    monkeypatch.setattr(
        gmail_client,
        "search_messages",
        lambda query, service=None, max_results=5: (
            [
                {
                    "subject": "Update on your application",
                    "sender": "hr@acme.com",
                    "date": "Mon, 1 Jan 2026",
                    "snippet": "Thanks for applying.",
                    "looks_like_rejection": False,
                }
            ]
            if query == '"Acme"'
            else []
        ),
    )

    def fail_if_called(company, current_status, messages, model=ollama_client.DEFAULT_MODEL):
        raise AssertionError("analyze_company_mail should not be called when the record is ambiguous")

    monkeypatch.setattr(mail_analysis, "analyze_company_mail", fail_if_called)

    at = AppTest.from_function(_render_mail).run()
    at.expander[0].expanded = True
    at = at.button(key="analyze_mail_Acme").click().run()

    assert not at.exception
    assert any("more than one" in e.value for e in at.error)


def test_approving_a_non_rejected_status_does_not_touch_rejected_from_stage(monkeypatch):
    _connect_with_acme_email(monkeypatch)

    def fake_analyze(company, current_status, messages, model=ollama_client.DEFAULT_MODEL):
        return {"action": "update_status", "new_status": "First Call", "reason": "They scheduled a call."}

    monkeypatch.setattr(mail_analysis, "analyze_company_mail", fake_analyze)

    at = AppTest.from_function(_render_mail).run()
    at.expander[0].expanded = True
    at = at.button(key="analyze_mail_Acme").click().run()
    at = at.button(key="approve_status_Acme_panel").click().run()

    assert not at.exception
    applied = storage.load_applied()
    assert applied[0]["status"] == "First Call"
    assert "rejected_from_stage" not in applied[0]


def test_approving_a_status_change_off_rejected_clears_rejected_from_stage(monkeypatch):
    _connect()
    from src import mail_view

    monkeypatch.setattr(mail_view, "_authorize_button", _fake_authorize_button(None))
    storage.save_applied(
        [{"company": "Acme", "title": "Backend", "status": "Rejected", "rejected_from_stage": "Applied"}]
    )
    monkeypatch.setattr(gmail_client, "get_service", lambda: "fake-service")
    monkeypatch.setattr(gmail_client, "get_connected_email", lambda service=None: "me@gmail.com")
    monkeypatch.setattr(
        gmail_client,
        "search_messages",
        lambda query, service=None, max_results=5: (
            [
                {
                    "subject": "We'd like to reconsider your application",
                    "sender": "hr@acme.com",
                    "date": "Mon, 1 Jan 2026",
                    "snippet": "We'd like to move forward after all.",
                    "looks_like_rejection": False,
                }
            ]
            if query == '"Acme"'
            else []
        ),
    )

    def fake_analyze(company, current_status, messages, model=ollama_client.DEFAULT_MODEL):
        assert current_status == "Rejected"
        return {"action": "update_status", "new_status": "Interview", "reason": "They reversed course."}

    monkeypatch.setattr(mail_analysis, "analyze_company_mail", fake_analyze)

    at = AppTest.from_function(_render_mail).run()
    at.expander[0].expanded = True
    at = at.button(key="analyze_mail_Acme").click().run()
    at = at.button(key="approve_status_Acme_panel").click().run()

    assert not at.exception
    applied = storage.load_applied()
    assert applied[0]["status"] == "Interview"
    assert "rejected_from_stage" not in applied[0]


def test_rescanning_clears_a_pending_suggestion(monkeypatch):
    _connect_with_acme_email(monkeypatch)

    def fake_analyze(company, current_status, messages, model=ollama_client.DEFAULT_MODEL):
        return {"action": "update_status", "new_status": "Rejected", "reason": "Clear rejection."}

    monkeypatch.setattr(mail_analysis, "analyze_company_mail", fake_analyze)

    at = AppTest.from_function(_render_mail).run()
    at.expander[0].expanded = True
    at = at.button(key="analyze_mail_Acme").click().run()
    assert any(b.key == "approve_status_Acme_panel" for b in at.button)

    at.expander[0].expanded = True
    at = at.button(key="scan_gmail_btn").click().run()

    assert not at.exception
    assert not any(b.key == "approve_status_Acme_panel" for b in at.button)


def test_approving_when_record_vanished_since_analyze_shows_warning_and_writes_nothing(monkeypatch):
    _connect_with_acme_email(monkeypatch)

    def fake_analyze(company, current_status, messages, model=ollama_client.DEFAULT_MODEL):
        return {"action": "update_status", "new_status": "Rejected", "reason": "Clear rejection."}

    monkeypatch.setattr(mail_analysis, "analyze_company_mail", fake_analyze)

    at = AppTest.from_function(_render_mail).run()
    at.expander[0].expanded = True
    at = at.button(key="analyze_mail_Acme").click().run()

    # The applied record is removed out from under the pending suggestion
    # (e.g. edited on another tab) before the user clicks Approve.
    storage.save_applied([])

    at = at.button(key="approve_status_Acme_panel").click().run()

    assert not at.exception
    assert storage.load_applied() == []


def _connect_with_one_opportunity(monkeypatch) -> None:
    """Connect Gmail with no applied positions, and make the opportunities
    auto-scan return a single job-alert email - the common setup for the
    opportunity "Add to Saved Positions" / "Dismiss" tests below."""
    _connect()
    from src import mail_view

    monkeypatch.setattr(mail_view, "_authorize_button", _fake_authorize_button(None))
    monkeypatch.setattr(gmail_client, "get_service", lambda: "fake-service")
    monkeypatch.setattr(gmail_client, "get_connected_email", lambda service=None: "me@gmail.com")
    monkeypatch.setattr(
        gmail_client,
        "search_messages",
        lambda query, service=None, max_results=5: [
            {
                "id": "opp-1",
                "thread_id": "t1",
                "subject": "Backend Engineer at Acme",
                "sender": "LinkedIn Job Alerts",
                "date": "Mon, 1 Jan 2026",
                "snippet": "New job alert for you",
                "looks_like_rejection": False,
            }
        ],
    )


def test_opportunity_shows_add_and_dismiss_buttons(monkeypatch):
    _connect_with_one_opportunity(monkeypatch)

    at = AppTest.from_function(_render_mail).run()

    assert not at.exception
    assert any(b.key == "add_opportunity_opp-1" for b in at.button)
    assert any(b.key == "dismiss_opportunity_opp-1" for b in at.button)
    assert any("Not yet tracked" in c.value for c in at.caption)


def test_adding_opportunity_creates_saved_position_and_marks_added(monkeypatch):
    _connect_with_one_opportunity(monkeypatch)

    monkeypatch.setattr(
        job_extract,
        "extract_fields",
        lambda description, model=job_extract.DEFAULT_MODEL: {
            "company": "Acme", "title": "Backend Engineer", "location": "Remote", "salary": ""
        },
    )

    at = AppTest.from_function(_render_mail).run()
    at = at.button(key="add_opportunity_opp-1").click().run()

    assert not at.exception
    saved = storage.load_saved()
    assert len(saved) == 1
    assert saved[0]["company"] == "Acme"
    assert saved[0]["title"] == "Backend Engineer"
    assert saved[0]["link"] == ""
    assert "Backend Engineer at Acme" in saved[0]["notes"]
    assert not any(b.key == "add_opportunity_opp-1" for b in at.button)
    assert any("Added to Saved Positions" in c.value for c in at.caption)


def test_adding_opportunity_fetches_link_from_message_body(monkeypatch):
    _connect_with_one_opportunity(monkeypatch)

    monkeypatch.setattr(
        job_extract,
        "extract_fields",
        lambda description, model=job_extract.DEFAULT_MODEL: {
            "company": "Acme", "title": "Backend Engineer", "location": "Remote", "salary": ""
        },
    )
    monkeypatch.setattr(
        gmail_client, "get_message_link", lambda msg_id, service=None, company="", title="": "https://acme.example/jobs/42"
    )

    at = AppTest.from_function(_render_mail).run()
    at = at.button(key="add_opportunity_opp-1").click().run()

    assert not at.exception
    saved = storage.load_saved()
    assert saved[0]["link"] == "https://acme.example/jobs/42"


def test_adding_opportunity_falls_back_to_blank_link_when_lookup_fails(monkeypatch):
    _connect_with_one_opportunity(monkeypatch)

    monkeypatch.setattr(
        job_extract,
        "extract_fields",
        lambda description, model=job_extract.DEFAULT_MODEL: {
            "company": "Acme", "title": "Backend Engineer", "location": "Remote", "salary": ""
        },
    )

    def raising_get_link(msg_id, service=None, company="", title=""):
        raise gmail_client.GmailError("boom")

    monkeypatch.setattr(gmail_client, "get_message_link", raising_get_link)

    at = AppTest.from_function(_render_mail).run()
    at = at.button(key="add_opportunity_opp-1").click().run()

    assert not at.exception
    saved = storage.load_saved()
    assert saved[0]["link"] == ""


def test_dismissing_opportunity_hides_action_buttons_without_saving(monkeypatch):
    _connect_with_one_opportunity(monkeypatch)

    at = AppTest.from_function(_render_mail).run()
    at = at.button(key="dismiss_opportunity_opp-1").click().run()

    assert not at.exception
    assert storage.load_saved() == []
    assert not any(b.key == "add_opportunity_opp-1" for b in at.button)
    assert any("Dismissed" in c.value for c in at.caption)


def test_adding_opportunity_shows_error_when_ollama_unreachable(monkeypatch):
    _connect_with_one_opportunity(monkeypatch)

    def raising_extract(description, model=job_extract.DEFAULT_MODEL):
        raise ollama_client.OllamaError("Could not reach Ollama")

    monkeypatch.setattr(job_extract, "extract_fields", raising_extract)

    at = AppTest.from_function(_render_mail).run()
    at = at.button(key="add_opportunity_opp-1").click().run()

    assert not at.exception
    assert any("Could not reach Ollama" in e.value for e in at.error)
    assert storage.load_saved() == []


def _connect_with_two_companies(monkeypatch) -> None:
    """Connect Gmail with two applied positions (Acme, Globex), each with
    one matched email - the common setup for the "Analyze all" tests."""
    _connect()
    from src import mail_view

    monkeypatch.setattr(mail_view, "_authorize_button", _fake_authorize_button(None))
    storage.save_applied(
        [
            {"company": "Acme", "title": "Backend", "status": "Applied"},
            {"company": "Globex", "title": "Frontend", "status": "Applied"},
        ]
    )
    monkeypatch.setattr(gmail_client, "get_service", lambda: "fake-service")
    monkeypatch.setattr(gmail_client, "get_connected_email", lambda service=None: "me@gmail.com")

    def fake_search(query, service=None, max_results=5):
        if query in ('"Acme"', '"Globex"'):
            return [
                {
                    "subject": "Update on your application",
                    "sender": "hr@example.com",
                    "date": "Mon, 1 Jan 2026",
                    "snippet": "Some update.",
                    "looks_like_rejection": False,
                }
            ]
        return []

    monkeypatch.setattr(gmail_client, "search_messages", fake_search)


def test_analyze_all_button_hidden_when_no_matching_emails(monkeypatch):
    _connect()
    from src import mail_view

    monkeypatch.setattr(mail_view, "_authorize_button", _fake_authorize_button(None))
    storage.save_applied([{"company": "Acme", "title": "Backend", "status": "Applied"}])
    monkeypatch.setattr(gmail_client, "get_service", lambda: "fake-service")
    monkeypatch.setattr(gmail_client, "get_connected_email", lambda service=None: "me@gmail.com")
    monkeypatch.setattr(gmail_client, "search_messages", lambda *a, **k: [])

    at = AppTest.from_function(_render_mail).run()

    assert not at.exception
    assert not any(b.key == "analyze_all_mail_btn" for b in at.button)


def test_analyze_all_analyzes_every_company_and_shows_pending_summary(monkeypatch):
    _connect_with_two_companies(monkeypatch)

    def fake_analyze(company, current_status, messages, model=ollama_client.DEFAULT_MODEL):
        if company == "Acme":
            return {"action": "update_status", "new_status": "Rejected", "reason": "Clear rejection."}
        return {"action": "none", "new_status": "", "reason": "Nothing new."}

    monkeypatch.setattr(mail_analysis, "analyze_company_mail", fake_analyze)

    at = AppTest.from_function(_render_mail).run()
    at = at.button(key="analyze_all_mail_btn").click().run()

    assert not at.exception
    assert any("Needs Update (1)" in s.value for s in at.subheader)
    assert any(b.key == "approve_status_Acme_summary" for b in at.button)
    # Globex found no change, so it shouldn't clutter the summary.
    assert not any(b.key == "approve_status_Globex_summary" for b in at.button)


def test_approving_from_the_summary_updates_storage_and_clears_the_summary(monkeypatch):
    _connect_with_two_companies(monkeypatch)

    def fake_analyze(company, current_status, messages, model=ollama_client.DEFAULT_MODEL):
        if company == "Acme":
            return {"action": "update_status", "new_status": "Rejected", "reason": "Clear rejection."}
        return {"action": "none", "new_status": "", "reason": "Nothing new."}

    monkeypatch.setattr(mail_analysis, "analyze_company_mail", fake_analyze)

    at = AppTest.from_function(_render_mail).run()
    at = at.button(key="analyze_all_mail_btn").click().run()
    at = at.button(key="approve_status_Acme_summary").click().run()

    assert not at.exception
    applied = storage.load_applied()
    acme = next(r for r in applied if r["company"] == "Acme")
    assert acme["status"] == "Rejected"
    assert not any("Needs Update" in s.value for s in at.subheader)


def test_analyze_all_includes_companies_already_in_a_terminal_status(monkeypatch):
    """"Analyze all" re-checks every applied company with matched emails,
    including ones already marked Offer/Rejected/Withdrawn - an application
    can still get follow-up mail worth surfacing after it's "resolved"."""
    _connect()
    from src import mail_view

    monkeypatch.setattr(mail_view, "_authorize_button", _fake_authorize_button(None))
    storage.save_applied(
        [
            {"company": "Acme", "title": "Backend", "status": "Applied"},
            {"company": "Globex", "title": "Frontend", "status": "Rejected", "rejected_from_stage": "Applied"},
        ]
    )
    monkeypatch.setattr(gmail_client, "get_service", lambda: "fake-service")
    monkeypatch.setattr(gmail_client, "get_connected_email", lambda service=None: "me@gmail.com")
    monkeypatch.setattr(
        gmail_client,
        "search_messages",
        lambda query, service=None, max_results=5: (
            [
                {
                    "subject": "Update",
                    "sender": "hr@example.com",
                    "date": "Mon, 1 Jan 2026",
                    "snippet": "Some update.",
                    "looks_like_rejection": False,
                }
            ]
            if query in ('"Acme"', '"Globex"')
            else []
        ),
    )

    analyzed = []

    def fake_analyze(company, current_status, messages, model=mail_analysis.DEFAULT_MODEL):
        analyzed.append(company)
        return {"action": "none", "new_status": "", "reason": ""}

    monkeypatch.setattr(mail_analysis, "analyze_company_mail", fake_analyze)

    at = AppTest.from_function(_render_mail).run()
    at = at.button(key="analyze_all_mail_btn").click().run()

    assert not at.exception
    assert sorted(analyzed) == ["Acme", "Globex"]


def _connect_with_two_opportunities(monkeypatch) -> None:
    """Connect Gmail with no applied positions, and make the opportunities
    auto-scan return two job-alert emails - the common setup for the "Save
    all as Saved Positions" tests below."""
    _connect()
    from src import mail_view

    monkeypatch.setattr(mail_view, "_authorize_button", _fake_authorize_button(None))
    monkeypatch.setattr(gmail_client, "get_service", lambda: "fake-service")
    monkeypatch.setattr(gmail_client, "get_connected_email", lambda service=None: "me@gmail.com")
    monkeypatch.setattr(
        gmail_client,
        "search_messages",
        lambda query, service=None, max_results=5: [
            {
                "id": "opp-1",
                "thread_id": "t1",
                "subject": "Backend Engineer at Acme",
                "sender": "LinkedIn Job Alerts",
                "date": "Mon, 1 Jan 2026",
                "snippet": "New job alert for you",
                "looks_like_rejection": False,
            },
            {
                "id": "opp-2",
                "thread_id": "t2",
                "subject": "Frontend Engineer at Globex",
                "sender": "LinkedIn Job Alerts",
                "date": "Tue, 2 Jan 2026",
                "snippet": "Another job alert",
                "looks_like_rejection": False,
            },
        ],
    )


def test_save_all_button_hidden_when_no_opportunities(monkeypatch):
    _connect()
    from src import mail_view

    monkeypatch.setattr(mail_view, "_authorize_button", _fake_authorize_button(None))
    monkeypatch.setattr(gmail_client, "get_service", lambda: "fake-service")
    monkeypatch.setattr(gmail_client, "get_connected_email", lambda service=None: "me@gmail.com")
    monkeypatch.setattr(gmail_client, "search_messages", lambda *a, **k: [])

    at = AppTest.from_function(_render_mail).run()

    assert not at.exception
    assert not any(b.key == "add_all_opportunities_btn" for b in at.button)


def test_save_all_adds_every_pending_opportunity(monkeypatch):
    _connect_with_two_opportunities(monkeypatch)

    monkeypatch.setattr(
        job_extract,
        "extract_fields",
        lambda description, model=job_extract.DEFAULT_MODEL: {
            "company": "Acme" if "Acme" in description else "Globex",
            "title": "Engineer",
            "location": "",
            "salary": "",
        },
    )

    at = AppTest.from_function(_render_mail).run()
    at = at.button(key="add_all_opportunities_btn").click().run()

    assert not at.exception
    saved = storage.load_saved()
    assert {r["company"] for r in saved} == {"Acme", "Globex"}
    assert not any(b.key == "add_opportunity_opp-1" for b in at.button)
    assert not any(b.key == "add_opportunity_opp-2" for b in at.button)
    assert not any(b.key == "add_all_opportunities_btn" for b in at.button)


def test_save_all_skips_already_handled_opportunities(monkeypatch):
    _connect_with_two_opportunities(monkeypatch)

    at = AppTest.from_function(_render_mail).run()
    at = at.button(key="dismiss_opportunity_opp-2").click().run()

    requested = []

    def fake_extract(description, model=job_extract.DEFAULT_MODEL):
        requested.append(description)
        return {"company": "Acme", "title": "Engineer", "location": "", "salary": ""}

    monkeypatch.setattr(job_extract, "extract_fields", fake_extract)

    at = at.button(key="add_all_opportunities_btn").click().run()

    assert not at.exception
    assert len(requested) == 1
    assert "Acme" in requested[0]
    saved = storage.load_saved()
    assert len(saved) == 1
    assert saved[0]["company"] == "Acme"


def test_save_all_continues_past_a_failure_and_reports_it(monkeypatch):
    _connect_with_two_opportunities(monkeypatch)

    def flaky_extract(description, model=job_extract.DEFAULT_MODEL):
        if "Acme" in description:
            raise ollama_client.OllamaError("Could not reach Ollama")
        return {"company": "Globex", "title": "Engineer", "location": "", "salary": ""}

    monkeypatch.setattr(job_extract, "extract_fields", flaky_extract)

    at = AppTest.from_function(_render_mail).run()
    at = at.button(key="add_all_opportunities_btn").click().run()

    assert not at.exception
    saved = storage.load_saved()
    assert len(saved) == 1
    assert saved[0]["company"] == "Globex"
    # The failed one is still actionable individually.
    assert any(b.key == "add_opportunity_opp-1" for b in at.button)


def test_manual_status_control_shows_current_status_and_disables_update_until_changed(monkeypatch):
    _connect_with_acme_email(monkeypatch)

    at = AppTest.from_function(_render_mail).run()
    at.expander[0].expanded = True
    at = at.run()

    selectbox = at.selectbox(key="manual_status_Acme")
    assert selectbox.value == "Applied"
    assert at.button(key="manual_status_btn_Acme").disabled


def test_manual_status_control_updates_status_when_changed(monkeypatch):
    _connect_with_acme_email(monkeypatch)

    at = AppTest.from_function(_render_mail).run()
    at.expander[0].expanded = True
    at = at.selectbox(key="manual_status_Acme").set_value("Interview").run()
    at = at.button(key="manual_status_btn_Acme").click().run()

    assert not at.exception
    assert storage.load_applied()[0]["status"] == "Interview"


def test_manual_status_control_sets_rejected_from_stage(monkeypatch):
    _connect_with_acme_email(monkeypatch)

    at = AppTest.from_function(_render_mail).run()
    at.expander[0].expanded = True
    at = at.selectbox(key="manual_status_Acme").set_value("Rejected").run()
    at = at.button(key="manual_status_btn_Acme").click().run()

    assert not at.exception
    applied = storage.load_applied()
    assert applied[0]["status"] == "Rejected"
    assert applied[0]["rejected_from_stage"] == "Applied"


def test_manual_status_control_hidden_when_company_is_ambiguous(monkeypatch):
    _connect()
    from src import mail_view

    monkeypatch.setattr(mail_view, "_authorize_button", _fake_authorize_button(None))
    storage.save_applied(
        [
            {"company": "Acme", "title": "Backend", "status": "Applied"},
            {"company": "Acme", "title": "Frontend", "status": "First Call"},
        ]
    )
    monkeypatch.setattr(gmail_client, "get_service", lambda: "fake-service")
    monkeypatch.setattr(gmail_client, "get_connected_email", lambda service=None: "me@gmail.com")
    monkeypatch.setattr(gmail_client, "search_messages", lambda *a, **k: [])

    at = AppTest.from_function(_render_mail).run()
    at.expander[0].expanded = True
    at = at.run()

    assert not at.exception
    assert not any(b.key == "manual_status_btn_Acme" for b in at.button)
    assert any("Edit Applications page" in c.value for c in at.caption)


def _connect_for_unlisted_scan(monkeypatch) -> None:
    """Connect Gmail with no applied/saved positions - the common setup for
    the "Find untracked applications" tests below."""
    _connect()
    from src import mail_view

    monkeypatch.setattr(mail_view, "_authorize_button", _fake_authorize_button(None))
    monkeypatch.setattr(gmail_client, "get_service", lambda: "fake-service")
    monkeypatch.setattr(gmail_client, "get_connected_email", lambda service=None: "me@gmail.com")


def test_find_untracked_applications_classifies_and_shows_add_dismiss(monkeypatch):
    _connect_for_unlisted_scan(monkeypatch)

    def fake_search(query, service=None, max_results=5):
        if "thank you for applying" in query:
            return [
                {
                    "id": "app-1",
                    "thread_id": "t1",
                    "subject": "Thank you for applying to Acme",
                    "sender": "careers@acme.example",
                    "date": "Mon, 1 Jan 2026",
                    "snippet": "We received your application.",
                    "looks_like_rejection": False,
                }
            ]
        return []

    monkeypatch.setattr(gmail_client, "search_messages", fake_search)
    monkeypatch.setattr(
        job_extract,
        "extract_fields",
        lambda description, model=job_extract.DEFAULT_MODEL: {
            "company": "Acme", "title": "Backend Engineer", "location": "", "salary": ""
        },
    )

    at = AppTest.from_function(_render_mail).run()
    at = at.button(key="scan_unlisted_btn").click().run()

    assert not at.exception
    assert any("Not Yet Tracked (1)" in s.value for s in at.subheader)
    assert any(b.key == "add_unlisted_app-1" for b in at.button)
    assert any(b.key == "dismiss_unlisted_app-1" for b in at.button)
    assert any("Acme" in c.value for c in at.caption)
    # Nothing written until the user approves.
    assert storage.load_applied() == []


def test_adding_untracked_application_creates_applied_record(monkeypatch):
    _connect_for_unlisted_scan(monkeypatch)

    monkeypatch.setattr(
        gmail_client,
        "search_messages",
        lambda query, service=None, max_results=5: (
            [
                {
                    "id": "app-1",
                    "thread_id": "t1",
                    "subject": "Thank you for applying to Acme",
                    "sender": "careers@acme.example",
                    "date": "Mon, 1 Jan 2026",
                    "snippet": "We received your application.",
                    "looks_like_rejection": False,
                }
            ]
            if "thank you for applying" in query
            else []
        ),
    )
    monkeypatch.setattr(
        job_extract,
        "extract_fields",
        lambda description, model=job_extract.DEFAULT_MODEL: {
            "company": "Acme", "title": "Backend Engineer", "location": "Remote", "salary": ""
        },
    )

    at = AppTest.from_function(_render_mail).run()
    at = at.button(key="scan_unlisted_btn").click().run()
    at = at.button(key="add_unlisted_app-1").click().run()

    assert not at.exception
    applied = storage.load_applied()
    assert len(applied) == 1
    assert applied[0]["company"] == "Acme"
    assert applied[0]["title"] == "Backend Engineer"
    assert applied[0]["status"] == "Applied"
    assert applied[0]["date_applied"]
    assert not any(b.key == "add_unlisted_app-1" for b in at.button)


def test_adding_untracked_application_fetches_link_from_message_body(monkeypatch):
    _connect_for_unlisted_scan(monkeypatch)

    monkeypatch.setattr(
        gmail_client,
        "search_messages",
        lambda query, service=None, max_results=5: (
            [
                {
                    "id": "app-1",
                    "thread_id": "t1",
                    "subject": "Thank you for applying to Acme",
                    "sender": "careers@acme.example",
                    "date": "Mon, 1 Jan 2026",
                    "snippet": "We received your application.",
                    "looks_like_rejection": False,
                }
            ]
            if "thank you for applying" in query
            else []
        ),
    )
    monkeypatch.setattr(
        job_extract,
        "extract_fields",
        lambda description, model=job_extract.DEFAULT_MODEL: {
            "company": "Acme", "title": "Backend Engineer", "location": "Remote", "salary": ""
        },
    )
    monkeypatch.setattr(
        gmail_client, "get_message_link", lambda msg_id, service=None, company="", title="": "https://acme.example/jobs/42"
    )

    at = AppTest.from_function(_render_mail).run()
    at = at.button(key="scan_unlisted_btn").click().run()
    at = at.button(key="add_unlisted_app-1").click().run()

    assert not at.exception
    applied = storage.load_applied()
    assert applied[0]["link"] == "https://acme.example/jobs/42"


def test_dismissing_untracked_application_hides_buttons_without_saving(monkeypatch):
    _connect_for_unlisted_scan(monkeypatch)

    monkeypatch.setattr(
        gmail_client,
        "search_messages",
        lambda query, service=None, max_results=5: (
            [
                {
                    "id": "app-1",
                    "thread_id": "t1",
                    "subject": "Thank you for applying to Acme",
                    "sender": "careers@acme.example",
                    "date": "Mon, 1 Jan 2026",
                    "snippet": "We received your application.",
                    "looks_like_rejection": False,
                }
            ]
            if "thank you for applying" in query
            else []
        ),
    )
    monkeypatch.setattr(
        job_extract,
        "extract_fields",
        lambda description, model=job_extract.DEFAULT_MODEL: {
            "company": "Acme", "title": "Backend", "location": "", "salary": ""
        },
    )

    at = AppTest.from_function(_render_mail).run()
    at = at.button(key="scan_unlisted_btn").click().run()
    at = at.button(key="dismiss_unlisted_app-1").click().run()

    assert not at.exception
    assert storage.load_applied() == []
    assert not any(b.key == "add_unlisted_app-1" for b in at.button)


def test_find_untracked_applications_skips_messages_without_a_clear_company(monkeypatch):
    _connect_for_unlisted_scan(monkeypatch)

    monkeypatch.setattr(
        gmail_client,
        "search_messages",
        lambda query, service=None, max_results=5: (
            [
                {
                    "id": "app-2",
                    "thread_id": "t2",
                    "subject": "Some newsletter",
                    "sender": "newsletter@example.com",
                    "date": "Mon, 1 Jan 2026",
                    "snippet": "thank you for applying to our giveaway",
                    "looks_like_rejection": False,
                }
            ]
            if "thank you for applying" in query
            else []
        ),
    )
    monkeypatch.setattr(
        job_extract,
        "extract_fields",
        lambda description, model=job_extract.DEFAULT_MODEL: {
            "company": "", "title": "", "location": "", "salary": ""
        },
    )

    at = AppTest.from_function(_render_mail).run()
    at = at.button(key="scan_unlisted_btn").click().run()

    assert not at.exception
    assert any("No untracked application emails found." in c.value for c in at.caption)
    assert not any(b.key == "add_unlisted_app-2" for b in at.button)


def test_find_untracked_applications_excludes_applied_and_saved_companies(monkeypatch):
    _connect_for_unlisted_scan(monkeypatch)
    storage.save_applied([{"company": "Acme", "title": "Backend", "status": "Applied"}])
    storage.save_saved([{"company": "Initech", "title": "DevOps", "link": "", "date_saved": "2026-01-01"}])

    captured_queries = []

    def fake_search(query, service=None, max_results=5):
        captured_queries.append(query)
        return []

    monkeypatch.setattr(gmail_client, "search_messages", fake_search)

    at = AppTest.from_function(_render_mail).run()
    at.button(key="scan_unlisted_btn").click().run()

    unlisted_query = next(q for q in captured_queries if "thank you for applying" in q)
    assert '-subject:"Acme"' in unlisted_query
    assert '-subject:"Initech"' in unlisted_query


def test_adding_opportunity_already_saved_skips_without_duplicating(monkeypatch):
    _connect_with_one_opportunity(monkeypatch)
    storage.save_saved([{"company": "Acme", "title": "Backend", "link": "", "date_saved": "2026-01-01"}])

    monkeypatch.setattr(
        job_extract,
        "extract_fields",
        lambda description, model=job_extract.DEFAULT_MODEL: {
            "company": "Acme", "title": "Backend Engineer", "location": "", "salary": ""
        },
    )

    at = AppTest.from_function(_render_mail).run()
    at = at.button(key="add_opportunity_opp-1").click().run()

    assert not at.exception
    assert storage.load_saved() == [
        {"company": "Acme", "title": "Backend", "link": "", "date_saved": "2026-01-01"}
    ]
    assert any("Already tracked" in c.value for c in at.caption)
    assert not any(b.key == "add_opportunity_opp-1" for b in at.button)


def test_adding_opportunity_already_applied_skips_without_duplicating(monkeypatch):
    _connect_with_one_opportunity(monkeypatch)
    storage.save_applied([{"company": "Acme", "title": "Backend", "status": "Applied"}])

    monkeypatch.setattr(
        job_extract,
        "extract_fields",
        lambda description, model=job_extract.DEFAULT_MODEL: {
            "company": "Acme", "title": "Backend Engineer", "location": "", "salary": ""
        },
    )

    at = AppTest.from_function(_render_mail).run()
    at = at.button(key="add_opportunity_opp-1").click().run()

    assert not at.exception
    assert storage.load_saved() == []
    assert any("Already tracked" in c.value for c in at.caption)


def test_save_all_skips_already_tracked_companies_without_duplicating(monkeypatch):
    _connect_with_two_opportunities(monkeypatch)
    storage.save_saved([{"company": "Acme", "title": "Backend", "link": "", "date_saved": "2026-01-01"}])

    monkeypatch.setattr(
        job_extract,
        "extract_fields",
        lambda description, model=job_extract.DEFAULT_MODEL: {
            "company": "Acme" if "Acme" in description else "Globex",
            "title": "Engineer",
            "location": "",
            "salary": "",
        },
    )

    at = AppTest.from_function(_render_mail).run()
    at = at.button(key="add_all_opportunities_btn").click().run()

    assert not at.exception
    saved = storage.load_saved()
    assert sorted(r["company"] for r in saved) == ["Acme", "Globex"]
    assert not any(b.key == "add_opportunity_opp-1" for b in at.button)
    assert not any(b.key == "add_opportunity_opp-2" for b in at.button)


def test_opportunities_scan_excludes_already_tracked_companies(monkeypatch):
    _connect()
    from src import mail_view

    monkeypatch.setattr(mail_view, "_authorize_button", _fake_authorize_button(None))
    monkeypatch.setattr(gmail_client, "get_service", lambda: "fake-service")
    monkeypatch.setattr(gmail_client, "get_connected_email", lambda service=None: "me@gmail.com")
    storage.save_applied([{"company": "Acme", "title": "Backend", "status": "Applied"}])
    storage.save_saved([{"company": "Initech", "title": "DevOps", "link": "", "date_saved": "2026-01-01"}])

    captured_queries = []

    def fake_search(query, service=None, max_results=5):
        captured_queries.append(query)
        return []

    monkeypatch.setattr(gmail_client, "search_messages", fake_search)

    at = AppTest.from_function(_render_mail).run()

    opportunities_query = next(q for q in captured_queries if "LinkedIn Job Alerts" in q)
    assert '-subject:"Acme"' in opportunities_query
    assert '-subject:"Initech"' in opportunities_query


def test_find_untracked_applications_filters_out_already_tracked_company_named_only_in_body(monkeypatch):
    """Regression guard: an ATS confirmation with a generic subject (no
    company name in it) isn't caught by the Gmail query's subject-scoped
    exclusion - it must still be filtered once extraction reveals the real
    company name matches one already tracked."""
    _connect_for_unlisted_scan(monkeypatch)
    storage.save_applied([{"company": "Plaee", "title": "Backend", "status": "Applied"}])

    monkeypatch.setattr(
        gmail_client,
        "search_messages",
        lambda query, service=None, max_results=5: (
            [
                {
                    "id": "app-3",
                    "thread_id": "t3",
                    "subject": "We Got It: Thanks for applying for Back End Engineer",
                    "sender": "no-reply@plaee.comeet-notifications.com",
                    "date": "Thu, 29 Oct 2026 15:12:54 +0000",
                    "snippet": "Hi, Thank you for applying for a position at Plaee. We received your information.",
                    "looks_like_rejection": False,
                }
            ]
            if "thank you for applying" in query
            else []
        ),
    )
    monkeypatch.setattr(
        job_extract,
        "extract_fields",
        lambda description, model=job_extract.DEFAULT_MODEL: {
            "company": "Plaee", "title": "Back End Engineer", "location": "", "salary": ""
        },
    )

    at = AppTest.from_function(_render_mail).run()
    at = at.button(key="scan_unlisted_btn").click().run()

    assert not at.exception
    assert any("No untracked application emails found." in c.value for c in at.caption)
    assert not any(b.key == "add_unlisted_app-3" for b in at.button)
