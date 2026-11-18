import datetime as dt

import streamlit as st

from src import gmail_client, storage

SCAN_RESULTS_KEY = "gmail_scan_results"
OPPORTUNITIES_KEY = "gmail_new_opportunities"
CONNECTED_EMAIL_KEY = "gmail_connected_email"
LAST_SYNC_KEY = "gmail_last_sync"


def _friendly_auth_error(message: str) -> str:
    """Translate common failures into a message a non-technical user can
    act on, instead of a raw library/HTTP error."""
    lowered = message.lower()
    if "timeout" in lowered or "timed out" in lowered or "connection" in lowered:
        return "Couldn't reach Google - check your network connection and try again."
    return message


def _now_label() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M")


def _authorize_button(label: str, key: str):
    """Render Google's OAuth sign-in popup (via streamlit-oauth) and return
    its result - None until the user finishes in the popup. Kept in its own
    function so tests can fake the outcome instead of driving a real browser
    popup."""
    from streamlit_oauth import OAuth2Component

    oauth2 = OAuth2Component(
        gmail_client.client_id(),
        gmail_client.client_secret(),
        gmail_client.AUTH_URI,
        gmail_client.TOKEN_URI,
        gmail_client.TOKEN_URI,
        gmail_client.REVOKE_URL,
    )
    return oauth2.authorize_button(
        name=label,
        icon="https://www.google.com/favicon.ico",
        redirect_uri=gmail_client.redirect_uri(),
        scope=gmail_client.scope_string(),
        extras_params={"access_type": "offline", "prompt": "consent"},
        pkce="S256",
        key=key,
    )


def _handle_authorize_result(result) -> bool:
    """Save the token from a completed OAuth popup. Returns True when a new
    connection was made, so the caller knows to rerun."""
    if not result:
        return False
    try:
        gmail_client.save_token(result["token"])
    except gmail_client.GmailAuthError as exc:
        st.error(_friendly_auth_error(str(exc)))
        return False
    st.session_state.pop(CONNECTED_EMAIL_KEY, None)
    st.success("Gmail connected.")
    return True


def _render_setup_form() -> None:
    """One-time, operator-only form to configure this app's own Google
    OAuth client without hand-editing secrets.toml/.env. Only ever shown
    to someone browsing from the same machine the app runs on (see
    gmail_client.is_localhost_request) - a visitor to a deployed copy
    always sees the plain "not configured" message in render() instead."""
    st.subheader("Set up Gmail connection")
    st.caption(
        "One-time setup for whoever runs this app - create this app's own Google OAuth "
        "client, then paste its ID and secret below. They're saved locally "
        f"({gmail_client.CONFIG_FILE.name}, gitignored) and never shown again."
    )
    with st.expander("Google Cloud Console steps", expanded=True):
        st.markdown(
            "1. Enable the **Gmail API** for a Google Cloud project.\n"
            "2. **Google Auth Platform → Audience**: set user type to **External**.\n"
            "3. **Google Auth Platform → Data Access**: add these two scopes "
            "(`.../auth/userinfo.email` is the first row on that page; for "
            "`.../auth/gmail.readonly`, type `gmail.readonly` in the Filter box at the "
            'top to find it - its description reads "View your email messages and '
            'settings").\n'
            "4. **Google Auth Platform → Clients**: create a **Web application** OAuth "
            "client, and add this exact URI to **both** \"Authorised JavaScript "
            'origins" and "Authorised redirect URIs":'
        )
        st.code(gmail_client.redirect_uri(), language=None)
        st.markdown(
            "Then copy the resulting **Client ID** and **Client Secret** into the form "
            "below.\n\n"
            "5. **Google Auth Platform → Audience**: click **Publish app**. Do **not** "
            'submit for verification - you (and anyone else, up to 100 users total) will '
            'see Google\'s "Google hasn\'t verified this app" warning the first time you '
            'connect; click **Advanced → Go to Mail Tracking (unsafe)** to proceed. That\'s '
            "expected for a personal, unverified app. If you'd rather stay in **Testing** "
            "instead of publishing, add each Gmail address that should be able to connect "
            "under **Test users** on that same Audience page - otherwise \"Connect with "
            'Google" will fail for everyone.'
        )

    with st.form("gmail_oauth_setup_form", border=False):
        client_id_input = st.text_input(
            "Google OAuth Client ID",
            placeholder="xxxxxxxxxxxx.apps.googleusercontent.com",
            key="gmail_setup_client_id_input",
        )
        client_secret_input = st.text_input(
            "Google OAuth Client Secret", type="password", key="gmail_setup_client_secret_input"
        )
        submitted = st.form_submit_button("Save", key="gmail_setup_submit_btn")

    if submitted:
        try:
            gmail_client.save_oauth_config(client_id_input, client_secret_input)
        except gmail_client.GmailConfigError as exc:
            st.error(str(exc))
        else:
            st.success("Gmail app configured.")
            st.rerun()


def _render_reset_setup_control() -> None:
    if not (gmail_client.is_localhost_request() and gmail_client.has_persisted_config()):
        return
    with st.expander("Gmail setup (advanced)"):
        st.caption(
            "Clears the locally-saved OAuth client ID/secret and encryption key, and "
            "disconnects any connected Gmail account, so you can redo the one-time setup."
        )
        if st.button("Reset Gmail setup", key="reset_gmail_setup_btn"):
            gmail_client.clear_oauth_config()
            for key in (SCAN_RESULTS_KEY, OPPORTUNITIES_KEY, CONNECTED_EMAIL_KEY, LAST_SYNC_KEY):
                st.session_state.pop(key, None)
            st.rerun()


def _render_connect_section() -> None:
    st.subheader("Connect Gmail")
    if not gmail_client.is_app_configured():
        if gmail_client.is_localhost_request():
            _render_setup_form()
        else:
            st.error(
                "Gmail sign-in isn't available yet - the app owner needs to set it up "
                "(only possible when running this app locally)."
            )
        return
    st.caption(
        'Grants read-only access only (gmail.readonly) - click "Connect with Google" to open '
        "Google's own sign-in page, pick your account, and grant access. This app can never "
        "send, modify, or delete your email."
    )
    result = _authorize_button("Connect with Google", "connect_gmail_oauth")
    if _handle_authorize_result(result):
        st.rerun()


def _render_status_bar() -> None:
    if CONNECTED_EMAIL_KEY not in st.session_state:
        try:
            st.session_state[CONNECTED_EMAIL_KEY] = gmail_client.get_connected_email()
        except gmail_client.GmailError:
            st.session_state[CONNECTED_EMAIL_KEY] = None

    email = st.session_state.get(CONNECTED_EMAIL_KEY)
    status = f"Connected as **{email}**" if email else "Connected"
    st.caption(status)

    reconnect_col, disconnect_col = st.columns(2)
    with reconnect_col:
        result = _authorize_button("Reconnect", "reconnect_gmail_oauth")
        if _handle_authorize_result(result):
            st.rerun()
    with disconnect_col:
        if st.button("Disconnect Gmail", key="disconnect_gmail_btn"):
            gmail_client.disconnect()
            for key in (SCAN_RESULTS_KEY, OPPORTUNITIES_KEY, CONNECTED_EMAIL_KEY, LAST_SYNC_KEY):
                st.session_state.pop(key, None)
            st.rerun()


def _scan_applications(companies: list[str]) -> None:
    with st.spinner("Scanning Gmail for updates on your applications..."):
        try:
            service = gmail_client.get_service()
        except gmail_client.GmailAuthError as exc:
            st.warning(str(exc))
            st.session_state[SCAN_RESULTS_KEY] = None
            return
        except gmail_client.GmailError as exc:
            st.error(str(exc))
            st.session_state[SCAN_RESULTS_KEY] = None
            return

        results: dict[str, list[dict] | Exception] = {}
        for company in companies:
            query = gmail_client.build_company_query(company)
            try:
                results[company] = gmail_client.search_messages(query, service=service)
            except gmail_client.GmailError as exc:
                results[company] = exc
        st.session_state[SCAN_RESULTS_KEY] = results
        st.session_state[LAST_SYNC_KEY] = _now_label()


def _scan_opportunities() -> None:
    with st.spinner("Checking for new job opportunity emails..."):
        try:
            service = gmail_client.get_service()
        except gmail_client.GmailAuthError as exc:
            st.warning(str(exc))
            st.session_state[OPPORTUNITIES_KEY] = None
            return
        try:
            st.session_state[OPPORTUNITIES_KEY] = gmail_client.search_messages(
                gmail_client.build_new_opportunities_query(), service=service, max_results=10
            )
            st.session_state[LAST_SYNC_KEY] = _now_label()
        except gmail_client.GmailError as exc:
            st.error(str(exc))
            st.session_state[OPPORTUNITIES_KEY] = None


def _render_message(msg: dict) -> None:
    prefix = "⚠️ " if msg["looks_like_rejection"] else ""
    st.markdown(f"**{prefix}{msg['subject']}**  \n{msg['sender']} - {msg['date']}")
    st.caption(msg["snippet"])
    st.divider()


def render() -> None:
    st.header("Mail Tracking")
    st.caption(
        "Read-only: scans Gmail for messages about your applied companies and for new "
        "job-alert emails. This view never sends, modifies, or deletes email."
    )
    _render_reset_setup_control()

    if not gmail_client.is_connected():
        _render_connect_section()
        return

    _render_status_bar()

    applied = storage.load_applied()
    companies = sorted(
        {(r.get("company") or "").strip() for r in applied if (r.get("company") or "").strip()}
    )

    # Auto-scan once per session as soon as Gmail is connected, so results
    # (and any rejection/opportunity alerts) show up without a manual click.
    if companies and SCAN_RESULTS_KEY not in st.session_state:
        _scan_applications(companies)
    if OPPORTUNITIES_KEY not in st.session_state:
        _scan_opportunities()

    col1, col2 = st.columns(2)
    with col1:
        if companies and st.button("Rescan applications", key="scan_gmail_btn"):
            _scan_applications(companies)
    with col2:
        if st.button("Rescan job alerts", key="scan_opportunities_btn"):
            _scan_opportunities()

    # Rendered after any scan above has had a chance to run this pass, so a
    # fresh sync shows up immediately instead of a run behind.
    last_sync = st.session_state.get(LAST_SYNC_KEY)
    if last_sync:
        st.caption(f"Last synced {last_sync}")

    results = st.session_state.get(SCAN_RESULTS_KEY)
    opportunities = st.session_state.get(OPPORTUNITIES_KEY)

    rejection_count = sum(
        1
        for company_result in (results or {}).values()
        if isinstance(company_result, list)
        for msg in company_result
        if msg["looks_like_rejection"]
    )
    if rejection_count:
        st.warning(f"⚠️ {rejection_count} email(s) below look like a rejection - take a look.")
    if isinstance(opportunities, list) and opportunities:
        st.info(f"📬 {len(opportunities)} new job-alert email(s) found below.")

    if not companies:
        st.info("No applied positions yet - add some on the Applied Positions page.")
    elif results:
        st.subheader("Applied companies")
        for company in companies:
            company_result = results.get(company)
            with st.expander(company):
                if isinstance(company_result, Exception):
                    st.error(str(company_result))
                elif not company_result:
                    st.caption("No matching emails found.")
                else:
                    for msg in company_result:
                        _render_message(msg)

    if isinstance(opportunities, Exception):
        st.error(str(opportunities))
    elif isinstance(opportunities, list):
        st.subheader("New job opportunities")
        if not opportunities:
            st.caption("No new job-alert emails found.")
        else:
            for msg in opportunities:
                _render_message(msg)
