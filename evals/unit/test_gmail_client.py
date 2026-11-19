import json

import pytest
from cryptography.fernet import Fernet

from src import gmail_client


def _set_encryption_key(monkeypatch, key: bytes | None = None) -> bytes:
    key = key or Fernet.generate_key()
    monkeypatch.setenv(gmail_client.TOKEN_ENCRYPTION_KEY_ENV_VAR, key.decode())
    return key


def _write_encrypted_token(path, key: bytes, payload: bytes = b"{}") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(Fernet(key).encrypt(payload))


def test_build_company_query():
    assert gmail_client.build_company_query("Acme Corp") == '"Acme Corp"'
    assert gmail_client.build_company_query("  ") == ""


def test_build_new_opportunities_query():
    query = gmail_client.build_new_opportunities_query(newer_than_days=7)
    assert "newer_than:7d" in query
    assert 'from:("LinkedIn Job Alerts")' in query
    assert 'from:("Glassdoor Jobs")' in query


def test_build_new_opportunities_query_excludes_known_companies():
    query = gmail_client.build_new_opportunities_query(["Jeen.ai", "Koda.security"])
    assert '-subject:"Jeen.ai"' in query
    assert '-subject:"Koda.security"' in query


def test_build_unlisted_applications_query_excludes_known_companies():
    query = gmail_client.build_unlisted_applications_query(["Acme", "Globex"], newer_than_days=30)
    assert "newer_than:30d" in query
    assert '"thank you for applying"' in query
    assert '-subject:"Acme"' in query
    assert '-subject:"Globex"' in query


def test_build_unlisted_applications_query_skips_blank_company_names():
    query = gmail_client.build_unlisted_applications_query(["", "  ", "Acme"])
    assert query.count('-subject:"') == 1
    assert '-subject:"Acme"' in query


def test_looks_like_rejection():
    assert gmail_client.looks_like_rejection("Unfortunately, we will not be moving forward.")
    assert gmail_client.looks_like_rejection("We've decided to move forward with other candidates.")
    assert not gmail_client.looks_like_rejection("Thanks for applying! We'll be in touch.")


def test_requested_scopes_are_exactly_openid_email_and_gmail_readonly():
    """This app requests exactly these three scopes - no more, no less -
    so the OAuth consent screen only ever lists what's actually needed."""
    assert gmail_client.SCOPES == [
        "openid",
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/gmail.readonly",
    ]


def test_scopes_are_exactly_read_only():
    """Enforces the read-only constraint at the OAuth-scope level: the
    requested scopes must include gmail.readonly and nothing broader."""
    assert "https://www.googleapis.com/auth/gmail.readonly" in gmail_client.SCOPES
    forbidden = ["send", "modify", "compose", "insert", "mail.google.com", "settings"]
    for scope in gmail_client.SCOPES:
        lowered = scope.lower()
        for bad in forbidden:
            assert bad not in lowered, f"scope {scope!r} looks broader than read-only ({bad!r})"


def test_scope_string_joins_scopes_with_spaces():
    assert gmail_client.scope_string() == " ".join(gmail_client.SCOPES)


def test_module_exposes_no_write_capability():
    """Enforces the read-only constraint: this client must never be able to
    send, modify, delete, or trash mail."""
    names = [name.lower() for name in dir(gmail_client)]
    for keyword in ("send", "modify", "delete", "trash"):
        assert not any(keyword in name for name in names), f"found a '{keyword}'-like capability in gmail_client"


def test_is_connected_false_when_no_token():
    assert not gmail_client.is_connected()


def test_is_connected_true_when_token_file_exists():
    gmail_client.data_dir().mkdir(parents=True, exist_ok=True)
    gmail_client.token_file().write_text("{}", encoding="utf-8")

    assert gmail_client.is_connected()


def test_is_app_configured_false_when_nothing_set():
    assert not gmail_client.is_app_configured()


def test_is_app_configured_false_when_encryption_key_missing(monkeypatch):
    monkeypatch.setenv(gmail_client.CLIENT_ID_ENV_VAR, "client-id")
    monkeypatch.setenv(gmail_client.CLIENT_SECRET_ENV_VAR, "client-secret")

    assert not gmail_client.is_app_configured()


def test_is_app_configured_true_when_env_vars_set(monkeypatch):
    monkeypatch.setenv(gmail_client.CLIENT_ID_ENV_VAR, "client-id")
    monkeypatch.setenv(gmail_client.CLIENT_SECRET_ENV_VAR, "client-secret")
    _set_encryption_key(monkeypatch)

    assert gmail_client.is_app_configured()
    assert gmail_client.client_id() == "client-id"
    assert gmail_client.client_secret() == "client-secret"


def test_secrets_take_priority_over_env_vars(monkeypatch):
    monkeypatch.setenv(gmail_client.CLIENT_ID_ENV_VAR, "from-env")
    monkeypatch.setattr(gmail_client.st, "secrets", {gmail_client.CLIENT_ID_ENV_VAR: "from-secrets"})

    assert gmail_client.client_id() == "from-secrets"


def test_redirect_uri_defaults_when_not_configured():
    assert gmail_client.redirect_uri() == gmail_client.DEFAULT_REDIRECT_URI


def test_redirect_uri_overridable_via_env(monkeypatch):
    monkeypatch.setenv(gmail_client.REDIRECT_URI_ENV_VAR, "https://example.com/callback")

    assert gmail_client.redirect_uri() == "https://example.com/callback"


def test_save_token_raises_when_no_refresh_token(monkeypatch):
    monkeypatch.setenv(gmail_client.CLIENT_ID_ENV_VAR, "client-id")
    monkeypatch.setenv(gmail_client.CLIENT_SECRET_ENV_VAR, "client-secret")

    with pytest.raises(gmail_client.GmailAuthError, match="refresh token"):
        gmail_client.save_token({"access_token": "at1"})

    assert not gmail_client.token_file().exists()


def test_save_token_raises_when_encryption_key_not_configured(monkeypatch):
    monkeypatch.setenv(gmail_client.CLIENT_ID_ENV_VAR, "client-id")
    monkeypatch.setenv(gmail_client.CLIENT_SECRET_ENV_VAR, "client-secret")

    with pytest.raises(gmail_client.GmailAuthError, match=gmail_client.TOKEN_ENCRYPTION_KEY_ENV_VAR):
        gmail_client.save_token({"access_token": "at1", "refresh_token": "rt1"})

    assert not gmail_client.token_file().exists()


def test_save_token_writes_encrypted_credentials_file(monkeypatch):
    monkeypatch.setenv(gmail_client.CLIENT_ID_ENV_VAR, "client-id")
    monkeypatch.setenv(gmail_client.CLIENT_SECRET_ENV_VAR, "client-secret")
    key = _set_encryption_key(monkeypatch)

    gmail_client.save_token({"access_token": "at1", "refresh_token": "super-secret-rt"})

    assert gmail_client.token_file().exists()
    raw = gmail_client.token_file().read_bytes()
    # Not plaintext on disk.
    assert b"super-secret-rt" not in raw
    with pytest.raises(Exception):
        json.loads(raw)

    saved = json.loads(Fernet(key).decrypt(raw))
    assert saved["refresh_token"] == "super-secret-rt"
    assert saved["client_id"] == "client-id"
    assert saved["client_secret"] == "client-secret"
    assert saved["scopes"] == gmail_client.SCOPES


def test_get_service_raises_when_not_authorized():
    with pytest.raises(gmail_client.GmailAuthError):
        gmail_client.get_service()


class _FakeCreds:
    def __init__(self, expired, refresh_token, token="access-token", raise_on_refresh=False):
        self.expired = expired
        self.refresh_token = refresh_token
        self.token = token
        self._raise_on_refresh = raise_on_refresh
        self.refreshed = False

    def refresh(self, request):
        if self._raise_on_refresh:
            raise gmail_client.RefreshError("boom")
        self.refreshed = True

    def to_json(self):
        return json.dumps({"ok": True})


def test_load_credentials_refreshes_expired_token(monkeypatch):
    key = _set_encryption_key(monkeypatch)
    _write_encrypted_token(gmail_client.token_file(), key)
    fake_creds = _FakeCreds(expired=True, refresh_token="r1")
    monkeypatch.setattr(
        gmail_client.Credentials, "from_authorized_user_info", staticmethod(lambda *a, **k: fake_creds)
    )

    result = gmail_client._load_credentials()

    assert result is fake_creds
    assert fake_creds.refreshed
    decrypted = Fernet(key).decrypt(gmail_client.token_file().read_bytes())
    assert decrypted == json.dumps({"ok": True}).encode("utf-8")


def test_load_credentials_raises_and_clears_token_when_refresh_fails(monkeypatch):
    key = _set_encryption_key(monkeypatch)
    _write_encrypted_token(gmail_client.token_file(), key)
    fake_creds = _FakeCreds(expired=True, refresh_token="r1", raise_on_refresh=True)
    monkeypatch.setattr(
        gmail_client.Credentials, "from_authorized_user_info", staticmethod(lambda *a, **k: fake_creds)
    )

    with pytest.raises(gmail_client.GmailAuthError, match="connection expired"):
        gmail_client._load_credentials()

    # A revoked/expired refresh token (invalid_grant) is cleared locally
    # rather than left around to fail the same way on every page load.
    assert not gmail_client.token_file().exists()


def test_load_credentials_raises_and_clears_token_when_expired_without_refresh_token(monkeypatch):
    key = _set_encryption_key(monkeypatch)
    _write_encrypted_token(gmail_client.token_file(), key)
    fake_creds = _FakeCreds(expired=True, refresh_token=None)
    monkeypatch.setattr(
        gmail_client.Credentials, "from_authorized_user_info", staticmethod(lambda *a, **k: fake_creds)
    )

    with pytest.raises(gmail_client.GmailAuthError, match="connection expired"):
        gmail_client._load_credentials()

    assert not gmail_client.token_file().exists()


def test_load_credentials_returns_valid_token_unchanged(monkeypatch):
    key = _set_encryption_key(monkeypatch)
    _write_encrypted_token(gmail_client.token_file(), key)
    fake_creds = _FakeCreds(expired=False, refresh_token="r1")
    monkeypatch.setattr(
        gmail_client.Credentials, "from_authorized_user_info", staticmethod(lambda *a, **k: fake_creds)
    )

    result = gmail_client._load_credentials()

    assert result is fake_creds
    assert not fake_creds.refreshed


def test_load_credentials_raises_missing_key_config_without_deleting_token(monkeypatch):
    # TOKEN_ENCRYPTION_KEY_ENV_VAR intentionally left unset.
    _write_encrypted_token(gmail_client.token_file(), Fernet.generate_key())

    with pytest.raises(gmail_client.GmailAuthError, match=gmail_client.TOKEN_ENCRYPTION_KEY_ENV_VAR):
        gmail_client._load_credentials()

    # A missing operator config, not a bad/revoked token - don't discard it.
    assert gmail_client.token_file().exists()


def test_load_credentials_raises_and_clears_token_when_undecryptable(monkeypatch):
    _set_encryption_key(monkeypatch)
    gmail_client.data_dir().mkdir(parents=True, exist_ok=True)
    gmail_client.token_file().write_bytes(b"not-a-valid-fernet-token")

    with pytest.raises(gmail_client.GmailAuthError, match="connection expired"):
        gmail_client._load_credentials()

    assert not gmail_client.token_file().exists()


def test_get_service_builds_client(monkeypatch):
    monkeypatch.setattr(gmail_client, "_load_credentials", lambda: "fake-creds")
    sentinel = object()
    monkeypatch.setattr("googleapiclient.discovery.build", lambda *a, **k: sentinel)

    assert gmail_client.get_service() is sentinel


def test_get_service_wraps_build_errors(monkeypatch):
    monkeypatch.setattr(gmail_client, "_load_credentials", lambda: "fake-creds")

    def _boom(*a, **k):
        raise RuntimeError("no network")

    monkeypatch.setattr("googleapiclient.discovery.build", _boom)

    with pytest.raises(gmail_client.GmailError):
        gmail_client.get_service()


class _FakeProfileResource:
    def __init__(self, response=None, error=None):
        self._response = response
        self._error = error

    def getProfile(self, userId):
        return self

    def execute(self):
        if self._error:
            raise self._error
        return self._response


class _FakeProfileService:
    def __init__(self, response=None, error=None):
        self._users = _FakeProfileResource(response, error)

    def users(self):
        return self._users


def test_get_connected_email_returns_profile_address():
    service = _FakeProfileService(response={"emailAddress": "me@gmail.com"})

    assert gmail_client.get_connected_email(service=service) == "me@gmail.com"


def test_get_connected_email_wraps_errors():
    service = _FakeProfileService(error=RuntimeError("no network"))

    with pytest.raises(gmail_client.GmailError):
        gmail_client.get_connected_email(service=service)


def test_disconnect_does_nothing_when_not_connected():
    gmail_client.disconnect()  # no token file - should not raise

    assert not gmail_client.token_file().exists()


def test_disconnect_revokes_and_deletes_local_token(monkeypatch):
    key = _set_encryption_key(monkeypatch)
    _write_encrypted_token(gmail_client.token_file(), key)
    fake_creds = _FakeCreds(expired=False, refresh_token="r1", token="access-token")
    monkeypatch.setattr(
        gmail_client.Credentials, "from_authorized_user_info", staticmethod(lambda *a, **k: fake_creds)
    )

    revoked = {}

    def fake_post(url, params=None, timeout=None):
        revoked["url"] = url
        revoked["token"] = params.get("token")

    monkeypatch.setattr(gmail_client.requests, "post", fake_post)

    gmail_client.disconnect()

    assert not gmail_client.token_file().exists()
    assert revoked == {"url": gmail_client.REVOKE_URL, "token": "r1"}


def test_disconnect_still_deletes_token_when_revoke_fails(monkeypatch):
    key = _set_encryption_key(monkeypatch)
    _write_encrypted_token(gmail_client.token_file(), key)
    fake_creds = _FakeCreds(expired=False, refresh_token="r1")
    monkeypatch.setattr(
        gmail_client.Credentials, "from_authorized_user_info", staticmethod(lambda *a, **k: fake_creds)
    )

    def fake_post(url, params=None, timeout=None):
        raise RuntimeError("offline")

    monkeypatch.setattr(gmail_client.requests, "post", fake_post)

    gmail_client.disconnect()

    assert not gmail_client.token_file().exists()


def test_disconnect_deletes_token_even_when_undecryptable(monkeypatch):
    """No encryption key configured (or a corrupted file) must never block
    clearing the local token - revocation is best-effort."""
    gmail_client.data_dir().mkdir(parents=True, exist_ok=True)
    gmail_client.token_file().write_bytes(b"opaque-bytes")

    def fake_post(*a, **k):
        raise AssertionError("should not attempt to revoke an undecryptable token")

    monkeypatch.setattr(gmail_client.requests, "post", fake_post)

    gmail_client.disconnect()

    assert not gmail_client.token_file().exists()


class _FakeExecutable:
    def __init__(self, response):
        self._response = response

    def execute(self):
        return self._response


class _FakeMessagesResource:
    def __init__(self, list_response, get_responses):
        self._list_response = list_response
        self._get_responses = get_responses

    def list(self, **kwargs):
        return _FakeExecutable(self._list_response)

    def get(self, **kwargs):
        return _FakeExecutable(self._get_responses[kwargs["id"]])


class _FakeService:
    def __init__(self, list_response, get_responses):
        self._messages_resource = _FakeMessagesResource(list_response, get_responses)

    def users(self):
        return self

    def messages(self):
        return self._messages_resource


def test_search_messages_parses_results_and_flags_rejections():
    list_response = {"messages": [{"id": "1"}, {"id": "2"}]}
    get_responses = {
        "1": {
            "id": "1",
            "threadId": "t1",
            "snippet": "Thanks for applying",
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Your application"},
                    {"name": "From", "value": "hr@acme.com"},
                    {"name": "Date", "value": "Mon, 1 Jan 2026 10:00:00"},
                ]
            },
        },
        "2": {
            "id": "2",
            "threadId": "t2",
            "snippet": "Unfortunately, we will not be moving forward.",
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Update on your application"},
                    {"name": "From", "value": "hr@acme.com"},
                    {"name": "Date", "value": "Tue, 2 Jan 2026 10:00:00"},
                ]
            },
        },
    }
    service = _FakeService(list_response, get_responses)

    messages = gmail_client.search_messages('"Acme"', service=service)

    assert len(messages) == 2
    assert messages[0] == {
        "id": "1",
        "thread_id": "t1",
        "subject": "Your application",
        "sender": "hr@acme.com",
        "date": "Mon, 1 Jan 2026 10:00:00",
        "snippet": "Thanks for applying",
        "looks_like_rejection": False,
    }
    assert messages[1]["looks_like_rejection"] is True


def test_search_messages_no_results():
    service = _FakeService({"messages": []}, {})

    assert gmail_client.search_messages('"Acme"', service=service) == []


def test_search_messages_empty_query_returns_empty_without_calling_api():
    assert gmail_client.search_messages("", service=object()) == []


def _b64(text: str) -> str:
    import base64

    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii")


def test_get_message_link_extracts_url_from_plain_text_body():
    payload = {
        "mimeType": "text/plain",
        "body": {"data": _b64("See the posting: https://acme.example/jobs/42 - good luck!")},
    }
    service = _FakeService({}, {"1": {"id": "1", "payload": payload}})

    assert gmail_client.get_message_link("1", service=service) == "https://acme.example/jobs/42"


def test_get_message_link_extracts_url_from_html_part_and_skips_footer_links():
    payload = {
        "mimeType": "multipart/alternative",
        "parts": [
            {
                "mimeType": "text/html",
                "body": {
                    "data": _b64(
                        '<a href="https://acme.example/unsubscribe">Unsubscribe</a>'
                        '<a href="https://acme.example/jobs/42">View job</a>'
                    )
                },
            }
        ],
    }
    service = _FakeService({}, {"1": {"id": "1", "payload": payload}})

    assert gmail_client.get_message_link("1", service=service) == "https://acme.example/jobs/42"


def test_get_message_link_returns_empty_string_when_no_link_found():
    payload = {"mimeType": "text/plain", "body": {"data": _b64("No links here.")}}
    service = _FakeService({}, {"1": {"id": "1", "payload": payload}})

    assert gmail_client.get_message_link("1", service=service) == ""


def test_get_message_link_disambiguates_digest_email_by_company_proximity():
    # A LinkedIn-style digest bundling two different jobs in one email -
    # only the job-board-shaped link closest to the requested company's
    # mention should be returned, not just the first one in the body.
    body = (
        "Senior Engineer\nAcme\nView job: https://www.linkedin.com/comm/jobs/view/111/?trk=a\n\n"
        "Backend Engineer\nGlobex\nView job: https://www.linkedin.com/comm/jobs/view/222/?trk=b\n"
    )
    payload = {"mimeType": "text/plain", "body": {"data": _b64(body)}}
    service = _FakeService({}, {"1": {"id": "1", "payload": payload}})

    assert gmail_client.get_message_link("1", service=service, company="Acme") == (
        "https://www.linkedin.com/comm/jobs/view/111/?trk=a"
    )
    assert gmail_client.get_message_link("1", service=service, company="Globex") == (
        "https://www.linkedin.com/comm/jobs/view/222/?trk=b"
    )


def test_get_message_link_skips_logo_image_and_uses_joblisting_link():
    payload = {
        "mimeType": "text/html",
        "body": {
            "data": _b64(
                '<img src="https://media.glassdoor.com/sql/123/acme-logo.png">'
                '<a href="https://www.glassdoor.com/partner/jobListing.htm?jobListingId=42">Acme</a>'
            )
        },
    }
    service = _FakeService({}, {"1": {"id": "1", "payload": payload}})

    assert gmail_client.get_message_link("1", service=service) == (
        "https://www.glassdoor.com/partner/jobListing.htm?jobListingId=42"
    )


def test_get_message_link_prefers_title_over_company_when_company_has_several_cards():
    # The same company has two different postings in one digest - the
    # title (unique to one card) must win over company-only proximity,
    # which can't tell the two company-matching cards apart.
    body = (
        "GTM Engineer - RevAI\nAcme\nTel Aviv\nView job: https://www.linkedin.com/comm/jobs/view/111/?trk=a\n\n"
        "Senior Platform Engineer\nAcme\nTel Aviv\nView job: https://www.linkedin.com/comm/jobs/view/222/?trk=b\n"
    )
    payload = {"mimeType": "text/plain", "body": {"data": _b64(body)}}
    service = _FakeService({}, {"1": {"id": "1", "payload": payload}})

    assert gmail_client.get_message_link(
        "1", service=service, company="Acme", title="GTM Engineer - RevAI"
    ) == "https://www.linkedin.com/comm/jobs/view/111/?trk=a"
    assert gmail_client.get_message_link(
        "1", service=service, company="Acme", title="Senior Platform Engineer"
    ) == "https://www.linkedin.com/comm/jobs/view/222/?trk=b"


def test_get_message_link_ignores_title_shared_by_a_different_companys_card():
    # company/title were extracted from a digest subject naming a
    # DIFFERENT company ("X at OtherCo and N more jobs") - title belongs
    # to OtherCo's own card, not Acme's. Trusting title alone would jump
    # to OtherCo's link just because it's closer to that shared title
    # text; this must stick to Acme's own card instead.
    body = (
        "Senior Engineer\nAcme\nView job: https://www.linkedin.com/comm/jobs/view/111/?trk=a\n\n"
        "Backend Engineer\nOtherCo\nView job: https://www.linkedin.com/comm/jobs/view/222/?trk=b\n"
    )
    payload = {"mimeType": "text/plain", "body": {"data": _b64(body)}}
    service = _FakeService({}, {"1": {"id": "1", "payload": payload}})

    assert gmail_client.get_message_link("1", service=service, company="Acme", title="Backend Engineer") == (
        "https://www.linkedin.com/comm/jobs/view/111/?trk=a"
    )


def test_get_message_link_returns_empty_when_ambiguous_and_company_not_found():
    # Two generic (non-job-board-shaped) links and a company name that
    # doesn't appear in the body at all - no safe way to pick, so this
    # must return "" rather than guess.
    body = "https://acme.example/careers https://acme.example/about"
    payload = {"mimeType": "text/plain", "body": {"data": _b64(body)}}
    service = _FakeService({}, {"1": {"id": "1", "payload": payload}})

    assert gmail_client.get_message_link("1", service=service, company="Nonexistent Co") == ""


def test_get_message_link_wraps_api_errors():
    class _RaisingMessages:
        def get(self, **kwargs):
            raise RuntimeError("boom")

    class _RaisingService:
        def users(self):
            return self

        def messages(self):
            return _RaisingMessages()

    with pytest.raises(gmail_client.GmailError):
        gmail_client.get_message_link("1", service=_RaisingService())


class _FakeContext:
    def __init__(self, ip_address=None, headers=None):
        self.ip_address = ip_address
        self.headers = headers or {}


def test_is_localhost_request_true_for_loopback_ip(monkeypatch):
    monkeypatch.setattr(gmail_client.st, "context", _FakeContext(ip_address="127.0.0.1"))

    assert gmail_client.is_localhost_request()


def test_is_localhost_request_true_for_localhost_host_header(monkeypatch):
    monkeypatch.setattr(
        gmail_client.st, "context", _FakeContext(ip_address="unknown", headers={"host": "localhost:8501"})
    )

    assert gmail_client.is_localhost_request()


def test_is_localhost_request_false_for_remote_visitor(monkeypatch):
    monkeypatch.setattr(
        gmail_client.st,
        "context",
        _FakeContext(ip_address="203.0.113.5", headers={"host": "my-app.example.com"}),
    )

    assert not gmail_client.is_localhost_request()


def test_is_localhost_request_false_by_default_without_context(monkeypatch):
    monkeypatch.setattr(gmail_client.st, "context", object())  # no .ip_address/.headers

    assert not gmail_client.is_localhost_request()


def test_save_oauth_config_rejects_bad_client_id():
    with pytest.raises(gmail_client.GmailConfigError, match="apps.googleusercontent.com"):
        gmail_client.save_oauth_config("not-a-real-client-id", "some-secret")

    assert not gmail_client.config_file().exists()


def test_save_oauth_config_rejects_empty_secret():
    with pytest.raises(gmail_client.GmailConfigError, match="Secret"):
        gmail_client.save_oauth_config("123.apps.googleusercontent.com", "   ")

    assert not gmail_client.config_file().exists()


def test_save_oauth_config_persists_and_generates_encryption_key():
    gmail_client.save_oauth_config(
        "  123.apps.googleusercontent.com  ", "  shh-secret  "
    )

    assert gmail_client.has_persisted_config()
    saved = json.loads(gmail_client.config_file().read_text(encoding="utf-8"))
    assert saved[gmail_client.CLIENT_ID_ENV_VAR] == "123.apps.googleusercontent.com"
    assert saved[gmail_client.CLIENT_SECRET_ENV_VAR] == "shh-secret"
    generated_key = saved[gmail_client.TOKEN_ENCRYPTION_KEY_ENV_VAR]
    Fernet(generated_key.encode())  # does not raise - a real usable Fernet key

    # Takes effect immediately, no restart/env var needed.
    assert gmail_client.client_id() == "123.apps.googleusercontent.com"
    assert gmail_client.client_secret() == "shh-secret"
    assert gmail_client.token_encryption_key() == generated_key
    assert gmail_client.is_app_configured()


def test_save_oauth_config_does_not_overwrite_existing_encryption_key(monkeypatch):
    key = _set_encryption_key(monkeypatch)

    gmail_client.save_oauth_config("123.apps.googleusercontent.com", "shh-secret")

    assert gmail_client.token_encryption_key() == key.decode()
    saved = json.loads(gmail_client.config_file().read_text(encoding="utf-8"))
    assert gmail_client.TOKEN_ENCRYPTION_KEY_ENV_VAR not in saved


def test_env_var_and_secrets_take_priority_over_persisted_config(monkeypatch):
    gmail_client.save_oauth_config("123.apps.googleusercontent.com", "file-secret")

    monkeypatch.setenv(gmail_client.CLIENT_SECRET_ENV_VAR, "env-secret")
    assert gmail_client.client_secret() == "env-secret"

    monkeypatch.setattr(gmail_client.st, "secrets", {gmail_client.CLIENT_SECRET_ENV_VAR: "secrets-secret"})
    assert gmail_client.client_secret() == "secrets-secret"


def test_has_persisted_config_false_when_never_saved():
    assert not gmail_client.has_persisted_config()


def test_clear_oauth_config_deletes_config_and_token(monkeypatch):
    gmail_client.save_oauth_config("123.apps.googleusercontent.com", "shh-secret")
    gmail_client.data_dir().mkdir(parents=True, exist_ok=True)
    gmail_client.token_file().write_bytes(b"irrelevant")

    gmail_client.clear_oauth_config()

    assert not gmail_client.has_persisted_config()
    assert not gmail_client.token_file().exists()
    assert not gmail_client.is_app_configured()


def test_clear_oauth_config_does_nothing_when_never_configured():
    gmail_client.clear_oauth_config()  # should not raise

    assert not gmail_client.has_persisted_config()


def test_build_unlisted_applications_query_defaults_to_the_past_month():
    query = gmail_client.build_unlisted_applications_query(["Acme"])
    assert "newer_than:30d" in query
