from cryptography.fernet import Fernet
from streamlit.testing.v1 import AppTest

from src import gmail_client, storage


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
