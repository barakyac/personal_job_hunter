"""Matching Jobs page: jobs found for you, from Gmail job alerts, Google Jobs
search and Claude browsing LinkedIn/Google in Chrome, ranked by fit against
your resume. Save the ones you like to Saved Jobs, dismiss the rest."""

import hashlib

import streamlit as st

from src import gmail_client, job_matching, job_search_client, layout, ollama_client, storage

STATUS_FILTER_KEY = "matches_status_filter"


@st.dialog("Job description")
def _description_dialog(record: dict) -> None:
    st.markdown(f"**{record.get('company') or 'Unknown company'} - {record.get('title') or 'Untitled'}**")
    st.write(record.get("description") or "")


def _row_key(record: dict) -> str:
    basis = job_matching.canonical_link(record.get("link", "")) or "|".join(job_matching._identity(record))
    return hashlib.md5(basis.encode("utf-8")).hexdigest()[:12]


def _fit_sort_key(record: dict) -> float:
    try:
        return -float(record.get("fit_score"))
    except (TypeError, ValueError):
        return float("inf")


def _split_list(text: str) -> list[str]:
    return [part.strip() for part in text.replace("\n", ",").split(",") if part.strip()]


def _report(counts: dict, label: str) -> None:
    bits = []
    if counts["already_tracked"]:
        bits.append(f"{counts['already_tracked']} already tracked")
    if counts["filtered"]:
        bits.append(f"{counts['filtered']} excluded by your keywords")
    suffix = f" (skipped {', '.join(bits)})" if bits else ""
    if counts["added"]:
        st.success(f"Added {counts['added']} new match(es) from {label}{suffix}.")
    else:
        st.info(f"No new matches from {label}{suffix}.")


def _render_profile() -> dict:
    profile = storage.load_match_profile()
    empty = not profile["titles"]
    with st.expander("What counts as a match", expanded=empty):
        st.caption(
            "Used for the Google Jobs search and by Claude when it browses LinkedIn and Google for you. "
            "Fit scores always come from your resume on the Profile page."
        )
        with st.form("match_profile_form", border=False):
            titles = st.text_input(
                "Target titles (comma-separated)", value=", ".join(profile["titles"]),
                placeholder="Backend Engineer, AI Infrastructure Engineer", key="match_titles",
            )
            location = st.text_input(
                "Location", value=profile["location"], placeholder="Tel Aviv, Israel", key="match_location"
            )
            keywords = st.text_input(
                "Keywords to add to searches", value=", ".join(profile["keywords"]),
                placeholder="Python, distributed systems", key="match_keywords",
            )
            excludes = st.text_input(
                "Exclude jobs mentioning", value=", ".join(profile["exclude_keywords"]),
                placeholder="frontend, team lead", key="match_excludes",
            )
            if st.form_submit_button("Save profile", type="primary"):
                profile = {
                    "titles": _split_list(titles),
                    "location": location.strip(),
                    "keywords": _split_list(keywords),
                    "exclude_keywords": _split_list(excludes),
                }
                storage.save_match_profile(profile)
                st.success("Saved.")
    return profile


def _scan_gmail(profile: dict) -> None:
    if not gmail_client.is_connected():
        st.error("Connect Gmail on the Mail Inbox page first.")
        return
    progress = st.progress(0.0)
    status_box = st.empty()

    def on_progress(n, total, msg):
        status_box.text(f"Reading {msg['subject']}...")
        progress.progress((n + 1) / max(total, 1))

    try:
        candidates, errors = job_matching.gmail_alert_candidates(on_progress=on_progress)
    except (gmail_client.GmailAuthError, gmail_client.GmailError) as exc:
        progress.empty()
        status_box.empty()
        st.error(str(exc))
        return
    progress.empty()
    status_box.empty()
    for error in errors:
        st.warning(error)
    _report(job_matching.add_candidates(candidates, storage.MATCH_SOURCE_GMAIL, profile), "job-alert emails")


def _search_google(profile: dict) -> None:
    queries = job_matching.search_queries(profile)
    if not queries:
        st.error("Add at least one target title under \"What counts as a match\" first.")
        return
    candidates = []
    with st.spinner(f"Searching Google Jobs ({len(queries)} search(es))..."):
        for query in queries:
            try:
                candidates.extend(job_search_client.search_jobs(query, profile["location"]))
            except job_search_client.JobSearchError as exc:
                st.warning(f"{query}: {exc}")
    _report(job_matching.add_candidates(candidates, storage.MATCH_SOURCE_GOOGLE, profile), "Google Jobs")


def _score(targets: list[dict]) -> None:
    if not targets:
        st.info("Every new match already has a fit score.")
        return
    progress = st.progress(0.0)
    status_box = st.empty()

    def on_progress(n, total, job):
        status_box.text(f"Scoring {job.get('company', '?')} - {job.get('title', '')}...")
        progress.progress(n / max(total, 1))

    errors = job_matching.score_matches(targets, on_progress=on_progress)
    progress.empty()
    status_box.empty()
    for error in errors:
        st.warning(error)
    if len(errors) < len(targets):
        st.success(f"Scored {len(targets) - len(errors)} of {len(targets)} match(es).")
        st.rerun()


def _render_row(record: dict) -> None:
    key = _row_key(record)
    status = record.get("match_status") or storage.MATCH_STATUS_NEW
    with st.container(border=True):
        info_col, fit_col, save_col, apply_col, dismiss_col, desc_col, open_col = st.columns(
            [3, 1.4, 1.0, 1.3, 0.8, 1.1, 0.8]
        )
        with info_col:
            st.markdown(
                layout.company_mark(record.get("company", ""))
                + f'<span style="font-weight:700;">{record.get("company") or "Unknown company"}</span> - '
                + f'<span class="jh-clamp-2">{record.get("title") or "Untitled"}</span>',
                unsafe_allow_html=True,
            )
            meta = [b for b in [record.get("location"), record.get("salary"), record.get("source"),
                                record.get("date_found")] if b]
            if meta:
                st.caption(" · ".join(meta), help=record.get("source_detail") or None)
        with fit_col:
            score = record.get("fit_score")
            if score not in (None, ""):
                st.markdown(f"Fit: **{score}**/10")
                notes = record.get("fit_notes") or ""
                if notes:
                    st.caption(notes if len(notes) <= 110 else notes[:107] + "...",
                               help=notes if len(notes) > 110 else None)
            else:
                st.caption("Not scored yet")
        with save_col:
            if status == storage.MATCH_STATUS_SAVED:
                st.caption("In Saved Jobs")
            elif status == storage.MATCH_STATUS_APPLIED:
                st.caption("In Applied Positions")
            elif st.button("Save job", key=f"match_save_{key}", type="primary"):
                if job_matching.save_to_saved_jobs(record):
                    st.toast(f"Saved {record.get('company') or 'job'} to Saved Jobs.")
                else:
                    st.toast("Already in Saved Jobs or Applied.")
                st.rerun()
        with apply_col:
            if status == storage.MATCH_STATUS_NEW:
                if st.button("Add to Applications", key=f"match_apply_{key}"):
                    if job_matching.apply_to_applied_jobs(record):
                        st.toast(f"Added {record.get('company') or 'job'} to Applied Positions.")
                    else:
                        st.toast("Already in Saved Jobs or Applied.")
                    st.rerun()
        with dismiss_col:
            if status == storage.MATCH_STATUS_DISMISSED:
                if st.button("Restore", key=f"match_restore_{key}"):
                    job_matching.set_status(record, storage.MATCH_STATUS_NEW)
                    st.rerun()
            elif status == storage.MATCH_STATUS_NEW:
                if st.button("Dismiss", key=f"match_dismiss_{key}"):
                    job_matching.set_status(record, storage.MATCH_STATUS_DISMISSED)
                    st.rerun()
        with desc_col:
            if record.get("description") and st.button("Job description", key=f"match_description_{key}"):
                _description_dialog(record)
        with open_col:
            if record.get("link"):
                st.markdown(f"[Open ↗]({record['link']})")


def render() -> None:
    layout.page_header(
        "Matching Jobs",
        "Jobs that match your profile, from job-alert emails, Google Jobs and Claude browsing LinkedIn "
        "for you. Best fit first.",
    )
    profile = _render_profile()

    google_ready = job_search_client.is_configured()
    source_cols = st.columns([1.3, 1.3, 1.6, 2])
    with source_cols[0]:
        if st.button("Scan job-alert emails", key="match_scan_gmail_btn", use_container_width=True):
            _scan_gmail(profile)
    with source_cols[1]:
        if st.button(
            "Search Google Jobs", key="match_search_google_btn", use_container_width=True,
            disabled=not google_ready,
            help=None if google_ready else f"Set {job_search_client.API_KEY_ENV_VAR} to enable (serpapi.com).",
        ):
            _search_google(profile)
    with source_cols[2]:
        matches = storage.load_matched()
        unscored = [r for r in matches if r.get("match_status", storage.MATCH_STATUS_NEW) == storage.MATCH_STATUS_NEW
                    and r.get("fit_score") in (None, "")]
        if st.button(
            f"Score fit (Ollama {ollama_client.DEFAULT_MODEL})", key="match_score_btn",
            use_container_width=True, disabled=not unscored,
        ):
            _score(unscored)
    with source_cols[3]:
        st.caption(
            "LinkedIn recommendations: ask Claude to *find matching jobs*. It browses LinkedIn in your "
            "Chrome and adds them here."
        )

    matches = storage.load_matched()
    counts = {s: sum(1 for r in matches if (r.get("match_status") or storage.MATCH_STATUS_NEW) == s)
              for s in storage.MATCH_STATUS_OPTIONS}
    filter_cols = st.columns([2.5, 2, 1.5])
    with filter_cols[0]:
        status_filter = st.segmented_control(
            "Show", options=storage.MATCH_STATUS_OPTIONS, default=storage.MATCH_STATUS_NEW,
            format_func=lambda s: f"{s} ({counts[s]})", key=STATUS_FILTER_KEY, label_visibility="collapsed",
        ) or storage.MATCH_STATUS_NEW
    with filter_cols[1]:
        source_filter = st.multiselect(
            "Source", options=storage.MATCH_SOURCE_OPTIONS, key="matches_source_filter",
            placeholder="All sources", label_visibility="collapsed",
        )
    with filter_cols[2]:
        min_fit = st.number_input("Min fit", min_value=0, max_value=10, value=0, step=1, key="matches_min_fit")

    visible = [r for r in matches if (r.get("match_status") or storage.MATCH_STATUS_NEW) == status_filter]
    if source_filter:
        visible = [r for r in visible if r.get("source") in source_filter]
    if min_fit:
        visible = [r for r in visible if r.get("fit_score") not in (None, "") and float(r["fit_score"]) >= min_fit]
    visible.sort(key=_fit_sort_key)

    if not matches:
        st.info(
            "No matches yet. Scan your job-alert emails, search Google Jobs, or ask Claude to find "
            "matching jobs on LinkedIn."
        )
    elif not visible:
        st.caption("No matches fit the current filters.")
    else:
        for record in visible:
            _render_row(record)
