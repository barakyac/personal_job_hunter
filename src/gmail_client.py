import base64
import json
import os
import re
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

def data_dir() -> Path:
    """Resolved fresh on every call, like src/storage.py's data_dir() of the
    same name - see that function's docstring for why a module-level
    constant computed once at import time is a trap."""
    return Path(os.environ.get("JOB_HUNTER_DATA_DIR") or Path(__file__).resolve().parent.parent / "data")


def token_file() -> Path:
    return data_dir() / "gmail_token.json"


def config_file() -> Path:
    """Local, gitignored (covered by data/*) fallback for the three OAuth
    values above when there's no .streamlit/secrets.toml - written by the
    in-app "Set up Gmail connection" form (see save_oauth_config), never by
    hand."""
    return data_dir() / "gmail_oauth_config.json"


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

# Phrases that show up in an ATS's "we got your application" auto-reply,
# regardless of which company sent it - used to find applications that
# were never added to this app at all (as opposed to build_company_query,
# which only ever looks at companies already tracked here).
APPLICATION_RECEIVED_PHRASES = [
    "thank you for applying",
    "thanks for applying",
    "we received your application",
    "your application has been received",
    "application received",
    "application has been submitted",
]


class GmailError(Exception):
    pass


class GmailAuthError(GmailError):
    pass


class GmailConfigError(GmailError):
    """Invalid input to the in-app Gmail setup form (bad client ID/secret),
    as opposed to a runtime auth problem."""

    pass


def _load_persisted_config() -> dict:
    if not config_file().exists():
        return {}
    try:
        return json.loads(config_file().read_text(encoding="utf-8"))
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
    return token_file().exists()


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
    return config_file().exists()


def save_oauth_config(raw_client_id: str, raw_client_secret: str) -> None:
    """Validate and persist the app operator's Google OAuth client
    credentials to config_file(), generating a token-encryption key if one
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

    data_dir().mkdir(parents=True, exist_ok=True)
    config_file().write_text(json.dumps(config), encoding="utf-8")


def clear_oauth_config() -> None:
    """"Reset Gmail setup": clear the locally-saved OAuth client config and
    any saved token, since a token is only usable with the client/key it
    was created under. Leaves st.secrets/env-based config (a real deployed
    setup) untouched - there's nothing in config_file() to clear in that
    case."""
    config_file().unlink(missing_ok=True)
    token_file().unlink(missing_ok=True)


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
    data_dir().mkdir(parents=True, exist_ok=True)
    token_file().write_bytes(_fernet().encrypt(creds.to_json().encode("utf-8")))


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
    if not token_file().exists():
        raise GmailAuthError(
            "Gmail isn't connected yet. Click \"Connect with Google\" on the Mail Tracking page."
        )
    fernet = _fernet()
    try:
        info = json.loads(fernet.decrypt(token_file().read_bytes()).decode("utf-8"))
        creds = Credentials.from_authorized_user_info(info, SCOPES)
    except Exception as exc:
        # A corrupted or undecryptable token is just as unusable as a
        # revoked one - clear it so the user sees "Connect with Google"
        # again instead of hitting this same error on every page load.
        token_file().unlink(missing_ok=True)
        raise GmailAuthError(EXPIRED_CONNECTION_MESSAGE) from exc

    if creds.expired:
        if not creds.refresh_token:
            token_file().unlink(missing_ok=True)
            raise GmailAuthError(EXPIRED_CONNECTION_MESSAGE)
        try:
            creds.refresh(Request())
        except RefreshError as exc:
            # Covers a revoked grant (invalid_grant) as well as any other
            # refresh failure - from the user's side both just mean
            # reconnecting is required.
            token_file().unlink(missing_ok=True)
            raise GmailAuthError(EXPIRED_CONNECTION_MESSAGE) from exc
        _write_encrypted_token(creds)
    return creds


def disconnect() -> None:
    """Revoke the saved token with Google (best-effort - a failed/offline
    revoke call, or a token that's already undecryptable, never blocks
    clearing local state) and delete it locally. The app's own OAuth client
    config (secrets/env) is untouched, since that's this app's registration
    with Google, not the user's personal grant."""
    if not token_file().exists():
        return
    try:
        info = json.loads(_fernet().decrypt(token_file().read_bytes()).decode("utf-8"))
        creds = Credentials.from_authorized_user_info(info, SCOPES)
        token = creds.refresh_token or creds.token
        if token:
            requests.post(REVOKE_URL, params={"token": token}, timeout=5)
    except Exception:
        pass
    token_file().unlink(missing_ok=True)


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


def _exclude_known_companies(query: str, known_companies: list[str]) -> str:
    """Append `-subject:"Company"` exclusions so a search never resurfaces
    mail about a company already tracked (Saved or Applied) in this app.
    Scoped to the subject, not the whole message: every alert/confirmation
    email we've seen names the company in its subject line, and a blanket
    full-text `-"Company"` false-excludes anything that merely mentions a
    tracked company in passing - e.g. a real "thank you for applying" email
    from an unrelated company whose body happens to say "a proud part of
    Google Cloud" got silently dropped once "google" was already tracked."""
    for company in known_companies:
        company = company.strip()
        if company:
            query += f' -subject:"{company}"'
    return query


def build_new_opportunities_query(known_companies: list[str] | None = None, newer_than_days: int = 14) -> str:
    """Gmail search query for job-board alert emails (not tied to a
    specific applied company) from the last `newer_than_days` days -
    excluding `known_companies` so a job you already saved or applied to
    doesn't keep resurfacing here every time the board re-alerts on it."""
    senders = " OR ".join(f"from:({s})" for s in NEW_OPPORTUNITY_FROM_NAMES)
    query = f"({senders}) newer_than:{newer_than_days}d"
    return _exclude_known_companies(query, known_companies or [])


def build_unlisted_applications_query(known_companies: list[str], newer_than_days: int = 30) -> str:
    """Gmail search query for application-confirmation-style mail that
    isn't about a company already tracked in this app - the ones this app
    would otherwise never surface, because every other scan here only
    looks at companies you've already added."""
    phrases = " OR ".join(f'"{p}"' for p in APPLICATION_RECEIVED_PHRASES)
    query = f"({phrases}) newer_than:{newer_than_days}d"
    return _exclude_known_companies(query, known_companies)


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


# Domains/path fragments that show up in a job-alert email's footer or
# tracking pixels, never in the job posting link itself - skipped when
# picking a link out of a message body in get_message_link().
_LINK_SKIP_PATTERNS = [
    "unsubscribe",
    "preferences",
    "optout",
    "opt-out",
    "/legal",
    "/psettings",
    "/privacy",
    "list-manage.com",
    "mailchimp.com",
]

# Non-HTML asset extensions (logos, tracking pixels, stylesheets) that show
# up as plain https:// links in an HTML email body but are never the job
# posting itself.
_ASSET_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp", ".css", ".js", ".woff", ".woff2")

# Known job-board URL shapes (host + path fragment) that point at one
# specific job posting, as opposed to a "manage your alerts" or search link
# that happens to live under the same host. A LinkedIn/Glassdoor digest
# email bundles several jobs in one body, so only a link matching one of
# these is trusted enough to disambiguate by proximity to a company name.
_JOB_BOARD_MARKERS = [
    "linkedin.com/comm/jobs/view/",
    "linkedin.com/jobs/view/",
    "glassdoor.com/partner/joblisting.htm",
    "glassdoor.com/job-listing/",
]

_URL_RE = re.compile(r'https?://[^\s"\'<>]+')


def _decode_body_part(part: dict) -> str:
    data = part.get("body", {}).get("data", "")
    if not data:
        return ""
    try:
        return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _extract_body_text(payload: dict) -> str:
    """Walk a message's MIME parts and concatenate every text/plain and
    text/html part's decoded body. Only used by get_message_link() to pull
    the job-posting URL back out - the text itself is discarded right
    after, never stored or returned."""
    mime_type = payload.get("mimeType", "")
    if mime_type in ("text/plain", "text/html"):
        return _decode_body_part(payload)
    return "\n".join(_extract_body_text(part) for part in payload.get("parts", []) or [])


def _is_skippable_link(url: str) -> bool:
    lowered = url.lower()
    if lowered.split("?", 1)[0].endswith(_ASSET_EXTENSIONS):
        return True
    return any(skip in lowered for skip in _LINK_SKIP_PATTERNS)


def _candidate_links(body_text: str) -> list[tuple[int, str]]:
    """Every URL in the body (with its character offset) that isn't an
    asset/footer/tracking link."""
    candidates = []
    for match in _URL_RE.finditer(body_text):
        url = match.group().rstrip(".,;)")
        if not _is_skippable_link(url):
            candidates.append((match.start(), url))
    return candidates


# Substrings that mark a nearby text match as not being real, visible card
# content, so it's excluded as an anchor in _anchor_positions():
# - "schemas-"/"xmlns": Outlook-compatibility markup repeats
#   xmlns:v="urn:schemas-microsoft-com:vml" once per card in some HTML
#   templates - a false "Microsoft" hit next to every card, not just that
#   company's own.
# - "preheader"/"skip-in-text": a hidden preview-text div (e.g.
#   data-email-preheader="true" or data-skip-in-text="true") often repeats
#   the digest's lead company/title as one combined phrase ("Acme Field
#   Technician") even though the actual card below splits them onto
#   separate lines ("Field Technician" / "Acme") - so this phrase would
#   otherwise only ever match there, never at the real card.
_ANCHOR_EXCLUDE_MARKERS = ("schemas-", "xmlns", "preheader", "skip-in-text")


def _anchor_positions(body_lower: str, text: str) -> list[int]:
    """Character offsets of every mention of `text` in the (already
    lowercased) body that looks like real card content rather than
    markup/namespace soup or hidden preview text."""
    text = text.strip().lower()
    if not text:
        return []
    return [
        m.start()
        for m in re.finditer(re.escape(text), body_lower)
        if not any(marker in body_lower[max(0, m.start() - 60): m.end() + 20] for marker in _ANCHOR_EXCLUDE_MARKERS)
    ]


# How close (in characters) a company/title mention must sit to a
# candidate link to count as "belongs to this link's own card" in
# _best_job_link. Wide enough to span one HTML job card's markup, tight
# enough not to reach into a neighboring card in the same digest.
_CARD_WINDOW = 900


def _best_job_link(body_text: str, company: str = "", title: str = "") -> str:
    """Best-effort pick of the one URL in a message body that's this job's
    posting link.

    A LinkedIn/Glassdoor job-alert digest bundles several postings in one
    email, so a link is only trusted there when it matches a known
    job-board URL shape (_JOB_BOARD_MARKERS) - with more than one such
    link, disambiguation requires `company`: without any mention of it in
    the body, there's no safe way to tell the postings apart, so this
    returns "". With it, the link closest to any mention of `company`
    wins (by character distance, over every occurrence of the name, not
    just the first - a digest's hidden preheader text ("Acme is
    hiring...") often repeats it far from the actual job card).

    A single company can still have several different postings in the
    same digest, which `company` alone can't tell apart. `title` helps
    there, but only when it sits within _CARD_WINDOW of the *same* link
    that `company` is also close to - i.e. both signals point at one
    card together. An exact title (e.g. "Software Engineer III") is
    common enough to also be some other company's title in the same
    digest, so title is never trusted as a disambiguator on its own: a
    link with company nearby but title far away, or vice versa, only
    means one of the two fields doesn't belong to this card (a known
    failure mode of the subject line this record's title/company were
    extracted from, e.g. "Software Engineer III at SailPoint ... and 11
    more jobs" naming a different company than the one picked out as
    `company`) - not that this is the right link.

    Outside LinkedIn/Glassdoor (e.g. a direct ATS application-confirmation
    email), there's no known URL shape to check, so a link is only used
    when it's the single remaining candidate after skipping assets/
    footers - with several, this returns "" rather than guess."""
    candidates = _candidate_links(body_text)
    if not candidates:
        return ""

    board_candidates = [
        (pos, url) for pos, url in candidates if any(marker in url.lower() for marker in _JOB_BOARD_MARKERS)
    ]
    if not board_candidates:
        return candidates[0][1] if len(candidates) == 1 else ""
    if len(board_candidates) == 1:
        return board_candidates[0][1]

    body_lower = body_text.lower()
    company_positions = _anchor_positions(body_lower, company)
    if not company_positions:
        return ""

    def nearest_distance(positions: list[int], pos: int) -> float:
        return min((abs(pos - p) for p in positions), default=float("inf"))

    title_positions = _anchor_positions(body_lower, title) if title else []
    if title_positions:
        pos, url = min(
            board_candidates,
            key=lambda c: max(nearest_distance(company_positions, c[0]), nearest_distance(title_positions, c[0])),
        )
        if max(nearest_distance(company_positions, pos), nearest_distance(title_positions, pos)) <= _CARD_WINDOW:
            return url

    return min(board_candidates, key=lambda c: nearest_distance(company_positions, c[0]))[1]


def get_message_link(msg_id: str, service=None, company: str = "", title: str = "") -> str:
    """Fetch one message's full body - the only call in this module that
    does - purely to pull out its job-posting URL (see _best_job_link for
    how). The decoded body text is discarded immediately after and never
    stored or surfaced; only the extracted link is returned (or "" if none
    is found/safe to guess). Call this only for a message the user has
    chosen to add as a Saved/Applied position, never during search/
    listing, which stays metadata+snippet only. `company`/`title`, when
    given, disambiguate a multi-job digest email."""
    service = service or get_service()
    try:
        msg = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
    except Exception as exc:
        raise GmailError(f"Could not read message {msg_id}: {exc}") from exc
    return _best_job_link(_extract_body_text(msg.get("payload", {})), company, title)


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
