import json
import os
from pathlib import Path

import requests
import streamlit as st
from cryptography.fernet import Fernet
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

# Read-only scopes only - this client must never be able to send, modify, or
# delete mail. Do not widen this list, and do not add a send/modify/delete
# call anywhere in this module. "openid"/userinfo.email just identify the
# signed-in address; gmail.readonly is the only mail-data scope.
SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/gmail.readonly",
]

AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URI = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"

# The app's own OAuth client (Web application type), configured once by
# whoever runs this app - see README's "Developer setup" section. Never
# asked of an end user.
CLIENT_ID_ENV_VAR = "GOOGLE_OAUTH_CLIENT_ID"
CLIENT_SECRET_ENV_VAR = "GOOGLE_OAUTH_CLIENT_SECRET"
REDIRECT_URI_ENV_VAR = "GOOGLE_OAUTH_REDIRECT_URI"
DEFAULT_REDIRECT_URI = "http://localhost:8501"

# Key for encrypting the saved token at rest (see save_token/_load_credentials).
# Must be a Fernet key, e.g. generated with:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
TOKEN_ENCRYPTION_KEY_ENV_VAR = "GMAIL_TOKEN_ENCRYPTION_KEY"

# Same reload-safe override pattern as storage.py's JOB_HUNTER_DATA_DIR -
# read fresh on every import so tests can point these at a throwaway dir.
DATA_DIR = Path(os.environ.get("JOB_HUNTER_DATA_DIR") or Path(__file__).resolve().parent.parent / "data")
TOKEN_FILE = DATA_DIR / "gmail_token.json"

# Local, gitignored (covered by data/*) fallback for the three values above
# when there's no .streamlit/secrets.toml - written by the in-app "Set up
# Gmail connection" form (see save_oauth_config), never by hand.
CONFIG_FILE = DATA_DIR / "gmail_oauth_config.json"

LOCALHOST_HOSTNAMES = {"localhost", "127.0.0.1", "::1"}

# Used to flag a matched email as a likely rejection, so the UI can surface
# it without the user having to open and read every result.
REJECTION_KEYWORDS = [
    "unfortunately",
    "we regret",
    "regret to inform",
    "not moving forward",
    "will not be moving forward",
    "other candidates",
    "decided to move forward with other",
    "not selected",
    "not be proceeding",
    "position has been filled",
]

# New-opportunity alert emails (job boards / recruiters), not tied to a
# specific applied company.
NEW_OPPORTUNITY_FROM_NAMES = ['"LinkedIn Job Alerts"', '"Glassdoor Jobs"']


class GmailError(Exception):
    pass


class GmailAuthError(GmailError):
    pass


class GmailConfigError(GmailError):
    """Invalid input to the in-app Gmail setup form (bad client ID/secret),
    as opposed to a runtime auth problem."""

    pass


def _load_persisted_config() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _get_secret(key: str) -> str | None:
    """Read from st.secrets first (the documented way to configure this
    app's OAuth client), then an env var (same pattern as the Anthropic/
    OpenAI keys, and what tests monkeypatch), then the locally-saved config
    file written by the in-app setup form. st.secrets raises when no
    secrets.toml exists at all, which just means "not set here"."""
    try:
        value = st.secrets.get(key)
    except Exception:
        value = None
    return value or os.environ.get(key) or _load_persisted_config().get(key)


def scope_string() -> str:
    return " ".join(SCOPES)


def client_id() -> str | None:
    return _get_secret(CLIENT_ID_ENV_VAR)


def client_secret() -> str | None:
    return _get_secret(CLIENT_SECRET_ENV_VAR)


def redirect_uri() -> str:
    return _get_secret(REDIRECT_URI_ENV_VAR) or DEFAULT_REDIRECT_URI


def token_encryption_key() -> str | None:
    return _get_secret(TOKEN_ENCRYPTION_KEY_ENV_VAR)


def is_app_configured() -> bool:
    """Whether the app operator has set up this app's own OAuth client and
    the key used to encrypt saved tokens at rest. Distinct from
    is_connected(): this is a one-time developer step, not something each
    end user does."""
    return bool(client_id() and client_secret() and token_encryption_key())


def is_connected() -> bool:
    return TOKEN_FILE.exists()


def is_localhost_request() -> bool:
    """Whether the current browser session is connecting from the same
    machine this app is running on. Gates the in-app Gmail setup form so a
    visitor to a deployed copy of this app can't (re)configure its OAuth
    client - only an operator sitting at the machine running it can.
    Defaults to False (deny) whenever this can't be determined, e.g.
    outside a real browser session."""
    try:
        if st.context.ip_address in LOCALHOST_HOSTNAMES:
            return True
    except Exception:
        pass
    try:
        host = (st.context.headers.get("host") or "").split(":")[0].lower()
    except Exception:
        host = ""
    return host in LOCALHOST_HOSTNAMES


def has_persisted_config() -> bool:
    return CONFIG_FILE.exists()


def save_oauth_config(raw_client_id: str, raw_client_secret: str) -> None:
    """Validate and persist the app operator's Google OAuth client
    credentials to CONFIG_FILE, generating a token-encryption key if one
    isn't already configured anywhere (secrets/env/this file). Takes effect
    immediately for the rest of this process and across restarts, since
    _get_secret() reads this file as its last fallback on every call - no
    separate "apply" step or env var needed."""
    client_id_value = (raw_client_id or "").strip()
    client_secret_value = (raw_client_secret or "").strip()

    if not client_id_value.endswith(".apps.googleusercontent.com"):
        raise GmailConfigError(
            'The Client ID should end in ".apps.googleusercontent.com" - double check you '
            "copied the OAuth client ID (not the client secret or something else)."
        )
    if not client_secret_value:
        raise GmailConfigError("The Client Secret can't be empty.")

    config = _load_persisted_config()
    config[CLIENT_ID_ENV_VAR] = client_id_value
    config[CLIENT_SECRET_ENV_VAR] = client_secret_value
    if not token_encryption_key():
        config[TOKEN_ENCRYPTION_KEY_ENV_VAR] = Fernet.generate_key().decode("utf-8")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config), encoding="utf-8")


def clear_oauth_config() -> None:
    """"Reset Gmail setup": clear the locally-saved OAuth client config and
    any saved token, since a token is only usable with the client/key it
    was created under. Leaves st.secrets/env-based config (a real deployed
    setup) untouched - there's nothing in CONFIG_FILE to clear in that
    case."""
    CONFIG_FILE.unlink(missing_ok=True)
    TOKEN_FILE.unlink(missing_ok=True)


def _fernet() -> Fernet:
    """The symmetric key the saved token is encrypted with, so a copy of
    data/gmail_token.json is useless without this app's own secrets."""
    key = token_encryption_key()
    if not key:
        raise GmailAuthError(
            f"Gmail sign-in isn't available yet - the app owner needs to set {TOKEN_ENCRYPTION_KEY_ENV_VAR} "
            "(see the Developer setup section in README.md) before this works."
        )
    try:
        return Fernet(key.encode("utf-8"))
    except Exception as exc:
        raise GmailAuthError(
            f"{TOKEN_ENCRYPTION_KEY_ENV_VAR} isn't a valid Fernet key. Generate one with: "
            'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
        ) from exc


def _write_encrypted_token(creds: Credentials) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_bytes(_fernet().encrypt(creds.to_json().encode("utf-8")))


def save_token(token: dict) -> None:
    """Build a refreshable Credentials object from the token dict returned
    by streamlit-oauth's authorize_button, and save it (encrypted) as this
    app's Gmail session."""
    refresh_token = token.get("refresh_token")
    if not refresh_token:
        raise GmailAuthError(
            "Google didn't return a refresh token. Remove this app's access on the Google "
            "Account permissions page (myaccount.google.com/permissions), then try \"Connect "
            "with Google\" again."
        )
    creds = Credentials(
        token=token.get("access_token"),
        refresh_token=refresh_token,
        token_uri=TOKEN_URI,
        client_id=client_id(),
        client_secret=client_secret(),
        scopes=SCOPES,
    )
    _write_encrypted_token(creds)


EXPIRED_CONNECTION_MESSAGE = 'Your Gmail connection expired, click "Connect with Google" again.'


def _load_credentials() -> Credentials:
    if not TOKEN_FILE.exists():
        raise GmailAuthError(
            "Gmail isn't connected yet. Click \"Connect with Google\" on the Mail Tracking page."
        )
    fernet = _fernet()
    try:
        info = json.loads(fernet.decrypt(TOKEN_FILE.read_bytes()).decode("utf-8"))
        creds = Credentials.from_authorized_user_info(info, SCOPES)
    except Exception as exc:
        # A corrupted or undecryptable token is just as unusable as a
        # revoked one - clear it so the user sees "Connect with Google"
        # again instead of hitting this same error on every page load.
        TOKEN_FILE.unlink(missing_ok=True)
        raise GmailAuthError(EXPIRED_CONNECTION_MESSAGE) from exc

    if creds.expired:
        if not creds.refresh_token:
            TOKEN_FILE.unlink(missing_ok=True)
            raise GmailAuthError(EXPIRED_CONNECTION_MESSAGE)
        try:
            creds.refresh(Request())
        except RefreshError as exc:
            # Covers a revoked grant (invalid_grant) as well as any other
            # refresh failure - from the user's side both just mean
            # reconnecting is required.
            TOKEN_FILE.unlink(missing_ok=True)
            raise GmailAuthError(EXPIRED_CONNECTION_MESSAGE) from exc
        _write_encrypted_token(creds)
    return creds


def disconnect() -> None:
    """Revoke the saved token with Google (best-effort - a failed/offline
    revoke call, or a token that's already undecryptable, never blocks
    clearing local state) and delete it locally. The app's own OAuth client
    config (secrets/env) is untouched, since that's this app's registration
    with Google, not the user's personal grant."""
    if not TOKEN_FILE.exists():
        return
    try:
        info = json.loads(_fernet().decrypt(TOKEN_FILE.read_bytes()).decode("utf-8"))
        creds = Credentials.from_authorized_user_info(info, SCOPES)
        token = creds.refresh_token or creds.token
        if token:
            requests.post(REVOKE_URL, params={"token": token}, timeout=5)
    except Exception:
        pass
    TOKEN_FILE.unlink(missing_ok=True)


def get_service():
    """Build a read-only Gmail API client. The token is scoped to
    gmail.readonly, and this module intentionally exposes no send/modify/
    delete call - never add one."""
    from googleapiclient.discovery import build

    creds = _load_credentials()
    try:
        return build("gmail", "v1", credentials=creds, cache_discovery=False)
    except Exception as exc:
        raise GmailError(f"Could not build Gmail client: {exc}") from exc


def get_connected_email(service=None) -> str:
    """The Gmail address the saved token is authorized for."""
    service = service or get_service()
    try:
        profile = service.users().getProfile(userId="me").execute()
    except Exception as exc:
        raise GmailError(f"Could not read the connected Gmail address: {exc}") from exc
    return profile.get("emailAddress", "")


def looks_like_rejection(text: str) -> bool:
    text = text.lower()
    return any(keyword in text for keyword in REJECTION_KEYWORDS)


def build_company_query(company: str) -> str:
    """Gmail search query matching mail that mentions the given company by
    name, in either the subject or body."""
    company = company.strip()
    return f'"{company}"' if company else ""


def build_new_opportunities_query(newer_than_days: int = 14) -> str:
    """Gmail search query for job-board alert emails (not tied to a
    specific applied company) from the last `newer_than_days` days."""
    senders = " OR ".join(f"from:({s})" for s in NEW_OPPORTUNITY_FROM_NAMES)
    return f"({senders}) newer_than:{newer_than_days}d"


def _parse_message(msg: dict) -> dict:
    headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
    subject = headers.get("Subject", "(no subject)")
    snippet = msg.get("snippet", "")
    return {
        "id": msg.get("id", ""),
        "thread_id": msg.get("threadId", ""),
        "subject": subject,
        "sender": headers.get("From", ""),
        "date": headers.get("Date", ""),
        "snippet": snippet,
        "looks_like_rejection": looks_like_rejection(f"{subject} {snippet}"),
    }


def search_messages(query: str, service=None, max_results: int = 5) -> list[dict]:
    """Read-only search: returns subject/sender/date/snippet for each match.
    Never fetches or exposes the full message body."""
    if not query.strip():
        return []
    service = service or get_service()
    try:
        result = (
            service.users()
            .messages()
            .list(userId="me", q=query, maxResults=max_results)
            .execute()
        )
    except Exception as exc:
        raise GmailError(f"Gmail search failed: {exc}") from exc

    messages = []
    for item in result.get("messages", []):
        try:
            msg = (
                service.users()
                .messages()
                .get(
                    userId="me",
                    id=item["id"],
                    format="metadata",
                    metadataHeaders=["Subject", "From", "Date"],
                )
                .execute()
            )
        except Exception as exc:
            raise GmailError(f"Could not read message {item['id']}: {exc}") from exc
        messages.append(_parse_message(msg))
    return messages
