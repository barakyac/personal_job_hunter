import datetime as dt

import streamlit as st

from src import gmail_client, job_extract, mail_analysis, ollama_client, storage

SCAN_RESULTS_KEY = "gmail_scan_results"
OPPORTUNITIES_KEY = "gmail_new_opportunities"
CONNECTED_EMAIL_KEY = "gmail_connected_email"
LAST_SYNC_KEY = "gmail_last_sync"
ANALYSIS_KEY = "gmail_mail_analysis"
OPPORTUNITY_ACTIONS_KEY = "gmail_opportunity_actions"
UNLISTED_KEY = "gmail_unlisted_applications"
UNLISTED_ACTIONS_KEY = "gmail_unlisted_actions"


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
            for key in (SCAN_RESULTS_KEY, OPPORTUNITIES_KEY, CONNECTED_EMAIL_KEY, LAST_SYNC_KEY, ANALYSIS_KEY, OPPORTUNITY_ACTIONS_KEY, UNLISTED_KEY, UNLISTED_ACTIONS_KEY):
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
            for key in (SCAN_RESULTS_KEY, OPPORTUNITIES_KEY, CONNECTED_EMAIL_KEY, LAST_SYNC_KEY, ANALYSIS_KEY, OPPORTUNITY_ACTIONS_KEY, UNLISTED_KEY, UNLISTED_ACTIONS_KEY):
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
        # A fresh scan may contain different emails than whatever an earlier
        # "Analyze with AI" suggestion was based on - drop stale suggestions
        # rather than leave an approvable button whose reasoning no longer
        # matches what's on screen.
        st.session_state.pop(ANALYSIS_KEY, None)


def _scan_opportunities() -> None:
    with st.spinner("Checking for new job opportunity emails..."):
        try:
            service = gmail_client.get_service()
        except gmail_client.GmailAuthError as exc:
            st.warning(str(exc))
            st.session_state[OPPORTUNITIES_KEY] = None
            return
        try:
            known_companies = [r.get("company", "") for r in storage.load_applied()] + [
                r.get("company", "") for r in storage.load_saved()
            ]
            st.session_state[OPPORTUNITIES_KEY] = gmail_client.search_messages(
                gmail_client.build_new_opportunities_query(known_companies), service=service, max_results=10
            )
            st.session_state[LAST_SYNC_KEY] = _now_label()
        except gmail_client.GmailError as exc:
            st.error(str(exc))
            st.session_state[OPPORTUNITIES_KEY] = None


def _scan_unlisted_applications(known_companies: list[str]) -> None:
    """Find application-confirmation mail about companies this app doesn't
    track at all (neither Applied nor Saved), then classify each match one
    at a time with Ollama - the keyword-based Gmail query is just a first
    pass, so a message only counts if the model can actually pull a company
    name out of it. Unlike _scan_applications/_scan_opportunities (cheap
    metadata-only reads), this one calls Ollama per match, so it's manual,
    not auto-run."""
    with st.spinner("Scanning Gmail for applications not tracked here..."):
        try:
            service = gmail_client.get_service()
        except gmail_client.GmailAuthError as exc:
            st.warning(str(exc))
            st.session_state[UNLISTED_KEY] = None
            return
        except gmail_client.GmailError as exc:
            st.error(str(exc))
            st.session_state[UNLISTED_KEY] = None
            return

        query = gmail_client.build_unlisted_applications_query(known_companies)
        try:
            messages = gmail_client.search_messages(query, service=service, max_results=15)
        except gmail_client.GmailError as exc:
            st.session_state[UNLISTED_KEY] = exc
            st.session_state[LAST_SYNC_KEY] = _now_label()
            return

    classified = []
    if messages:
        progress = st.progress(0.0)
        status_box = st.empty()
        for n, msg in enumerate(messages):
            status_box.text(f"Classifying: {msg['subject']}...")
            try:
                fields = job_extract.extract_fields(f"{msg['subject']}\n{msg['snippet']}")
            except ollama_client.OllamaError:
                fields = {"company": "", "title": "", "location": "", "salary": ""}
            # The Gmail query's -subject:"Company" exclusion only catches
            # a company named in the subject line - a lot of ATS auto-
            # replies use a generic subject ("We Got It: Thanks for
            # applying...") and only name the company in the body. Now that
            # extraction has pulled the real company name out of that body
            # text, re-check it against what's already tracked.
            if fields.get("company") and not _company_already_tracked(fields["company"]):
                classified.append({"msg": msg, "fields": fields})
            progress.progress((n + 1) / len(messages))
        progress.empty()
        status_box.empty()

    st.session_state[UNLISTED_KEY] = classified
    st.session_state[LAST_SYNC_KEY] = _now_label()


def _analyze_company(company: str, messages: list[dict]) -> None:
    """Ask Ollama whether this company's emails show a status change, and
    stash the suggestion in session state - nothing is written to storage
    until the user approves it in _render_analysis."""
    applied = storage.load_applied()
    index = storage.find_record_index(applied, company)
    if index is None:
        st.session_state.setdefault(ANALYSIS_KEY, {})[company] = {
            "action": "none",
            "error": "Can't match this to a single application record (none, or more than one, "
            f"found for '{company}') - update its status manually instead.",
            "blocking": True,
        }
        return

    current_status = applied[index].get("status") or "Applied"
    with st.spinner(f"Asking Ollama about {company}..."):
        try:
            suggestion = mail_analysis.analyze_company_mail(company, current_status, messages)
        except ollama_client.OllamaError as exc:
            suggestion = {"action": "none", "error": str(exc), "blocking": False}
    suggestion["current_status"] = current_status
    st.session_state.setdefault(ANALYSIS_KEY, {})[company] = suggestion


def _apply_suggestion(company: str, new_status: str, current_status: str) -> bool:
    """Write the approved status change. Returns False (and leaves storage
    untouched) if the underlying record can no longer be matched - e.g. it
    was edited or removed elsewhere between analyzing and approving."""
    applied = storage.load_applied()
    index = storage.find_record_index(applied, company)
    st.session_state.get(ANALYSIS_KEY, {}).pop(company, None)
    if index is None:
        return False
    if new_status == "Rejected":
        applied[index]["rejected_from_stage"] = current_status
    elif current_status == "Rejected":
        applied[index].pop("rejected_from_stage", None)
    applied[index]["status"] = new_status
    storage.save_applied(applied)
    return True


def _render_manual_status_control(company: str) -> None:
    """A direct status update for this company's application, independent
    of AI analysis - for when the user has already read the emails
    themselves and just wants to move the pipeline stage, or when the AI
    can't match the record (see the "update its status manually instead"
    message in _analyze_company)."""
    applied = storage.load_applied()
    index = storage.find_record_index(applied, company)
    if index is None:
        st.caption(
            "Can't match this to a single application record - update its status on the "
            "Edit Applications page instead."
        )
        return

    current_status = applied[index].get("status") or "Applied"
    status_col, button_col = st.columns([3, 1])
    with status_col:
        new_status = st.selectbox(
            "Update status",
            options=storage.STATUS_OPTIONS,
            index=storage.STATUS_OPTIONS.index(current_status),
            key=f"manual_status_{company}",
            label_visibility="collapsed",
        )
    with button_col:
        if st.button("Update", key=f"manual_status_btn_{company}", disabled=new_status == current_status):
            _apply_suggestion(company, new_status, current_status)
            st.success(f"{company} moved to {new_status}.")
            st.rerun()


def _analyze_all_companies(companies: list[str], results: dict) -> None:
    """Run _analyze_company for each given company (already filtered to
    ones worth asking Ollama about), so the user can review every
    suggestion in one place instead of opening each company's expander and
    clicking "Analyze with AI" one at a time."""
    analyzable = [(c, results[c]) for c in companies if isinstance(results.get(c), list) and results.get(c)]
    if not analyzable:
        return
    progress = st.progress(0.0)
    status_box = st.empty()
    for n, (company, messages) in enumerate(analyzable):
        status_box.text(f"Analyzing {company}...")
        _analyze_company(company, messages)
        progress.progress((n + 1) / len(analyzable))
    progress.empty()
    status_box.empty()


def _render_pending_suggestions() -> None:
    """Compact, top-of-page review list of every pending "update status"
    suggestion - a short approve-or-dismiss pass over every company at
    once, instead of opening each one's expander individually. Uses its
    own widget-key suffix so it can coexist with the same suggestion also
    being shown (and actionable) inside that company's expander below."""
    suggestions = st.session_state.get(ANALYSIS_KEY, {})
    pending = [c for c, s in suggestions.items() if s.get("action") == "update_status"]
    if not pending:
        return

    st.subheader(f"Needs Update ({len(pending)})")
    st.caption("Nothing is written until you approve a suggestion.")
    for company in pending:
        with st.container(border=True):
            st.markdown(f"**{company}**")
            _render_analysis(company, key_suffix="summary")
    st.divider()


def _render_analysis(company: str, key_suffix: str = "panel") -> None:
    suggestion = st.session_state.get(ANALYSIS_KEY, {}).get(company)
    if not suggestion:
        return

    if suggestion.get("error"):
        if suggestion.get("blocking"):
            st.error(suggestion["error"])
        else:
            st.warning(suggestion["error"])
        return

    if suggestion.get("action") != "update_status":
        st.info("AI review: no status change found in these emails.")
        return

    new_status = suggestion["new_status"]
    current_status = suggestion["current_status"]
    st.info(
        f"AI suggests moving this application from **{current_status}** to "
        f"**{new_status}**: {suggestion.get('reason', '')}"
    )
    approve_col, dismiss_col = st.columns(2)
    with approve_col:
        if st.button(f"Approve - set to {new_status}", key=f"approve_status_{company}_{key_suffix}"):
            if _apply_suggestion(company, new_status, current_status):
                st.success(f"{company} moved to {new_status}.")
            else:
                st.warning(
                    f"Couldn't update {company} - its application record changed since this "
                    "suggestion was generated. Update its status manually instead."
                )
            st.rerun()
    with dismiss_col:
        if st.button("Dismiss", key=f"dismiss_status_{company}_{key_suffix}"):
            st.session_state.get(ANALYSIS_KEY, {}).pop(company, None)
            st.rerun()


def _render_message(msg: dict) -> None:
    prefix = "⚠️ " if msg["looks_like_rejection"] else ""
    st.markdown(f"**{prefix}{msg['subject']}**  \n{msg['sender']} - {msg['date']}")
    st.caption(msg["snippet"])
    st.divider()


def _company_already_tracked(company: str) -> bool:
    """True if `company` already appears in Saved or Applied Positions
    (case-insensitive). The opportunities Gmail query already excludes
    known companies by name (see build_new_opportunities_query), but this
    is the backstop for an extracted name that doesn't match it exactly,
    or an opportunities list that's gone stale in session state."""
    company = (company or "").strip().lower()
    if not company:
        return False
    tracked = (storage.load_saved(), storage.load_applied())
    return any((r.get("company") or "").strip().lower() == company for records in tracked for r in records)


def _add_opportunity_as_saved(msg: dict) -> tuple[str, bool]:
    """Pull company/title/location/salary out of a job-alert email's
    subject+snippet with Ollama and add it as a new Saved Position. The
    job-posting link isn't in that metadata+snippet (search_messages never
    reads the body), so it's fetched separately via
    gmail_client.get_message_link() - a one-off full-body read of just this
    message, done only because the user chose to add it. If that lookup
    fails or finds nothing, the record is still added with an empty link
    for the user to fill in. Raises ollama_client.OllamaError on failure to
    extract fields; writes nothing to storage or session state in that
    case. Does not rerun - callers (single or bulk) decide when to do that.

    Returns (company, was_added) - was_added is False, and nothing is
    written, when the company is already tracked in Saved or Applied
    Positions."""
    fields = job_extract.extract_fields(f"{msg['subject']}\n{msg['snippet']}")
    company = fields["company"]

    if _company_already_tracked(company):
        st.session_state.setdefault(OPPORTUNITY_ACTIONS_KEY, {})[msg["id"]] = "skipped"
        return company, False

    try:
        # Best-effort - a failure here (auth, API, or an unexpected shape
        # in a real-world email body) must never block adding the position
        # itself, so it falls back to an empty link rather than raising.
        link = gmail_client.get_message_link(msg["id"], company=company, title=fields["title"])
    except Exception:
        link = ""

    records = storage.load_saved()
    records.append({
        "company": company,
        "title": fields["title"],
        "link": link,
        "location": fields["location"],
        "salary": fields["salary"],
        "date_saved": dt.date.today().isoformat(),
        "notes": f"From job-alert email: {msg['subject']}",
        "description": msg["snippet"],
    })
    storage.save_saved(records)
    st.session_state.setdefault(OPPORTUNITY_ACTIONS_KEY, {})[msg["id"]] = "added"
    return company, True


def _add_all_opportunities(opportunities: list[dict]) -> None:
    """Add every not-yet-handled job-alert email as a Saved Position in one
    pass, so the user doesn't have to click "Add to Saved Positions" on
    each one individually."""
    pending = [
        msg for msg in opportunities
        if st.session_state.get(OPPORTUNITY_ACTIONS_KEY, {}).get(msg["id"]) not in ("added", "dismissed", "skipped")
    ]
    if not pending:
        return

    progress = st.progress(0.0)
    status_box = st.empty()
    errors = []
    added_count = 0
    skipped_count = 0
    for n, msg in enumerate(pending):
        status_box.text(f"Adding {msg['subject']}...")
        try:
            _, added = _add_opportunity_as_saved(msg)
        except ollama_client.OllamaError as exc:
            errors.append(f"{msg['subject']}: {exc}")
        else:
            added_count += added
            skipped_count += not added
        progress.progress((n + 1) / len(pending))
    progress.empty()
    status_box.empty()

    for error in errors:
        st.warning(error)
    if added_count:
        st.success(f"Added {added_count} of {len(pending)} job alert(s) to Saved Positions.")
    if skipped_count:
        plural = "y" if skipped_count == 1 else "ies"
        st.info(f"Skipped {skipped_count} already-tracked compan{plural}.")
    st.rerun()


def _render_opportunity(msg: dict) -> None:
    _render_message(msg)
    action = st.session_state.get(OPPORTUNITY_ACTIONS_KEY, {}).get(msg["id"])
    if action == "added":
        st.caption("Added to Saved Positions.")
        return
    if action == "skipped":
        st.caption("Already tracked in Saved or Applied Positions - not added again.")
        return
    if action == "dismissed":
        st.caption("Dismissed.")
        return

    st.caption("Not yet tracked - add it as a new saved position, or dismiss it.")
    add_col, dismiss_col = st.columns(2)
    with add_col:
        if st.button(f"Add to Saved Positions ({job_extract.DEFAULT_MODEL})", key=f"add_opportunity_{msg['id']}"):
            try:
                with st.spinner(f"Extracting fields with Ollama {job_extract.DEFAULT_MODEL}..."):
                    company, added = _add_opportunity_as_saved(msg)
            except ollama_client.OllamaError as exc:
                st.error(str(exc))
            else:
                if added:
                    st.success(f"Added {company or 'position'} to Saved Positions.")
                else:
                    st.info(f"{company or 'This company'} is already tracked - not added again.")
                st.rerun()
    with dismiss_col:
        if st.button("Dismiss", key=f"dismiss_opportunity_{msg['id']}"):
            st.session_state.setdefault(OPPORTUNITY_ACTIONS_KEY, {})[msg["id"]] = "dismissed"
            st.rerun()


def _add_unlisted_as_applied(item: dict) -> None:
    """Add an untracked application straight into Applied Positions - unlike
    a job-alert opportunity (not yet applied to), this email is itself
    confirmation the application was already sent. Best-effort fetches the
    job posting link out of the message body (see
    gmail_client.get_message_link); falls back to an empty link if that
    fails or finds nothing."""
    msg, fields = item["msg"], item["fields"]
    try:
        # Best-effort, same as _add_opportunity_as_saved - never block
        # adding the position over a link-lookup failure.
        link = gmail_client.get_message_link(msg["id"], company=fields["company"], title=fields["title"])
    except Exception:
        link = ""
    records = storage.load_applied()
    today = dt.date.today().isoformat()
    records.append({
        "company": fields["company"],
        "title": fields["title"],
        "link": link,
        "location": fields["location"],
        "salary": fields["salary"],
        "date_saved": today,
        "date_applied": today,
        "status": "Applied",
        "notes": f"From job-application email: {msg['subject']}",
        "description": msg["snippet"],
    })
    storage.save_applied(records)
    st.session_state.setdefault(UNLISTED_ACTIONS_KEY, {})[msg["id"]] = "added"


def _render_unlisted_application(item: dict) -> None:
    msg, fields = item["msg"], item["fields"]
    _render_message(msg)
    action = st.session_state.get(UNLISTED_ACTIONS_KEY, {}).get(msg["id"])
    if action == "added":
        st.caption(f"Added to Applied Positions as {fields['company']}.")
        return
    if action == "dismissed":
        st.caption("Dismissed.")
        return

    st.caption(f"Looks like an application to **{fields['company']}** that isn't tracked here yet.")
    add_col, dismiss_col = st.columns(2)
    with add_col:
        if st.button("Add to Applied Positions", key=f"add_unlisted_{msg['id']}"):
            _add_unlisted_as_applied(item)
            st.success(f"Added {fields['company']} to Applied Positions.")
            st.rerun()
    with dismiss_col:
        if st.button("Dismiss", key=f"dismiss_unlisted_{msg['id']}"):
            st.session_state.setdefault(UNLISTED_ACTIONS_KEY, {})[msg["id"]] = "dismissed"
            st.rerun()


def render() -> None:
    st.header("Mail Tracking")
    st.caption(
        "Read-only: scans Gmail for messages about your applied companies, for new "
        "job-alert emails, and for applications you haven't added here yet. This view "
        "never sends, modifies, or deletes email."
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

    col1, col2, col3 = st.columns(3)
    with col1:
        if companies and st.button("Rescan applications", key="scan_gmail_btn"):
            _scan_applications(companies)
    with col2:
        if st.button("Rescan job alerts", key="scan_opportunities_btn"):
            _scan_opportunities()
    with col3:
        if st.button(
            f"Find untracked applications ({job_extract.DEFAULT_MODEL})", key="scan_unlisted_btn"
        ):
            _scan_unlisted_applications(companies + [r.get("company", "") for r in storage.load_saved()])

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

    unlisted = st.session_state.get(UNLISTED_KEY)
    if isinstance(unlisted, Exception):
        st.error(str(unlisted))
    elif isinstance(unlisted, list):
        pending_unlisted = [
            item for item in unlisted
            if st.session_state.get(UNLISTED_ACTIONS_KEY, {}).get(item["msg"]["id"]) not in ("added", "dismissed")
        ]
        st.subheader(f"Not Yet Tracked ({len(pending_unlisted)})")
        if not unlisted:
            st.caption("No untracked application emails found.")
        elif not pending_unlisted:
            st.caption("All clear - every match here has been added or dismissed.")
        else:
            st.caption("Application emails for companies not yet in Saved or Applied Positions.")
            for item in unlisted:
                with st.container(border=True):
                    _render_unlisted_application(item)
        st.divider()

    if not companies:
        st.info("No applied positions yet - add some on the Applied Positions page.")
    elif results:
        analyzable_companies = [c for c in companies if isinstance(results.get(c), list) and results.get(c)]
        if analyzable_companies and st.button(
            f"Analyze all applications with AI ({mail_analysis.DEFAULT_MODEL})", key="analyze_all_mail_btn"
        ):
            _analyze_all_companies(analyzable_companies, results)

        _render_pending_suggestions()

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
                    if st.button(
                        f"Analyze with AI ({mail_analysis.DEFAULT_MODEL})",
                        key=f"analyze_mail_{company}",
                    ):
                        _analyze_company(company, company_result)
                    _render_analysis(company)
                st.divider()
                _render_manual_status_control(company)

    if isinstance(opportunities, Exception):
        st.error(str(opportunities))
    elif isinstance(opportunities, list):
        st.subheader("New job opportunities")
        if not opportunities:
            st.caption("No new job-alert emails found.")
        else:
            pending_opportunities = [
                msg for msg in opportunities
                if st.session_state.get(OPPORTUNITY_ACTIONS_KEY, {}).get(msg["id"])
                not in ("added", "dismissed", "skipped")
            ]
            if pending_opportunities and st.button(
                f"Save all as Saved Positions ({job_extract.DEFAULT_MODEL})", key="add_all_opportunities_btn"
            ):
                _add_all_opportunities(pending_opportunities)
            for msg in opportunities:
                _render_opportunity(msg)
