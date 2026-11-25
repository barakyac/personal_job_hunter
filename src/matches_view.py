"""Matching Jobs page: jobs found for you, from Gmail job alerts, Google Jobs
search and Claude browsing LinkedIn/Google in Chrome, ranked by fit against
your resume. Save the ones you like to Saved Jobs, dismiss the rest."""

import hashlib
import html

import streamlit as st

from src import gmail_client, job_matching, job_search_client, layout, ollama_client, storage

STATUS_FILTER_KEY = "matches_status_filter"


def _preformatted(text: str) -> str:
    """Render text in a modal with its original line breaks/paragraphs
    intact - plain st.write/st.markdown collapses single newlines like any
    other markdown, which mangles job descriptions and fit explanations
    that rely on line breaks for structure. Escaped first since this is
    external text (scraped postings, model output) going into raw HTML."""
    return f'<div style="white-space:pre-wrap;">{html.escape(text)}</div>'


@st.dialog("Job description")
def _description_dialog(record: dict) -> None:
    st.markdown(f"**{record.get('company') or 'Unknown company'} - {record.get('title') or 'Untitled'}**")
    st.markdown(_preformatted(record.get("description") or ""), unsafe_allow_html=True)


@st.dialog("Why you match")
def _fit_explanation_dialog(record: dict) -> None:
    st.markdown(f"**{record.get('company') or 'Unknown company'} - {record.get('title') or 'Untitled'}**")
    score = record.get("fit_score")
    if score not in (None, ""):
        st.markdown(f"Fit score: **{score}**/10")
    st.markdown(_preformatted(record.get("fit_notes") or ""), unsafe_allow_html=True)


@st.dialog("Already tracked")
def _conflict_dialog(record: dict, where: str, intent: str) -> None:
    """Shown whenever "Save job"/"Add to Applications" is clicked on a
    match that's already tracked somewhere (Saved or Applied) - save_to_
    saved_jobs/apply_to_applied_jobs never guess which bucket is right on
    their own; it's always this dialog's call, left to the user."""
    bucket = "Saved Jobs" if where == "saved" else "Applied Positions"
    target = "Saved Jobs" if intent == "save" else "Applied Positions"
    key = _row_key(record)
    st.write(
        f"**{record.get('company') or 'This job'} - {record.get('title') or 'Untitled'}** is already in "
        f"**{bucket}**."
    )
    if st.button(f"Keep it in {bucket} (just fix the label here)", key=f"conflict_sync_{key}",
                 use_container_width=True):
        job_matching.mark_status_from_reality(record)
        st.rerun()
    if st.button(f"Also add it to {target}", key=f"conflict_force_{key}", use_container_width=True):
        if intent == "save":
            job_matching.save_to_saved_jobs(record, force=True)
        else:
            job_matching.apply_to_applied_jobs(record, force=True)
        st.rerun()


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
    for error in counts.get("score_errors", []):
        st.warning(error)


def _render_profile_editor(profile: dict) -> None:
    """Collapsible editor for the match profile. Reads fresh from disk on
    every rerun (including the one a form submit triggers), so callers that
    need the profile just call storage.load_match_profile() directly rather
    than depending on this function's return value."""
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


def _fit_tier(score) -> str:
    """Presentational only - buckets a score into a color tier for the
    clickable score button. Never used for filtering/sorting/scoring."""
    try:
        value = float(score)
    except (TypeError, ValueError):
        return "low"
    if value >= 8:
        return "good"
    if value >= 5:
        return "ok"
    return "low"


def _render_card(record: dict) -> None:
    key = _row_key(record)
    status = record.get("match_status") or storage.MATCH_STATUS_NEW
    with st.container(border=True, key=f"jh-match-card-{key}"):
        with st.container(key=f"jh-match-row-{key}"):
            cols = st.columns(
                [0.35, 4.0, 0.8, 1.7, 1.6, 1.6, 0.6, 2.0, 0.6], gap="small", vertical_alignment="center"
            )
            icon_col, info_col, score_col, why_col, desc_col, open_col, save_col, apply_col, dismiss_col = cols
            with icon_col:
                st.markdown(layout.company_mark(record.get("company", "")), unsafe_allow_html=True)
            with info_col:
                meta = [b for b in [
                    f'<span class="jh-match-company" style="font-weight:700;">'
                    f'{record.get("company") or "Unknown company"}</span>',
                    record.get("location"), record.get("salary"), record.get("source"), record.get("date_found"),
                ] if b]
                st.markdown(
                    f'<div class="jh-match-title">{record.get("title") or "Untitled"}</div>'
                    f'<div class="jh-match-meta">{" · ".join(meta)}</div>',
                    unsafe_allow_html=True,
                )
            with score_col:
                score = record.get("fit_score")
                if score not in (None, ""):
                    with st.container(key=f"jh-match-score-{_fit_tier(score)}-{key}"):
                        if st.button(f"{score}/10", key=f"match_score_open_{key}", help="Why you match"):
                            _fit_explanation_dialog(record)
                else:
                    st.caption("Not scored")
            with why_col:
                if record.get("fit_notes"):
                    if st.button(
                        "Why you match", key=f"match_why_{key}", icon=":material/comment:",
                        help="Show the full match explanation",
                    ):
                        _fit_explanation_dialog(record)
            with desc_col:
                if record.get("description"):
                    if st.button(
                        "Job description", key=f"match_description_{key}", icon=":material/description:",
                        help="View the full job description",
                    ):
                        _description_dialog(record)
            with open_col:
                if record.get("link"):
                    st.link_button(
                        "Open posting", record["link"], icon=":material/open_in_new:",
                        help="Open the original job posting",
                    )
            with save_col:
                if status == storage.MATCH_STATUS_SAVED:
                    st.caption("Saved")
                elif status == storage.MATCH_STATUS_APPLIED:
                    st.caption("Applied")
                else:
                    if st.button("", key=f"match_save_{key}", icon=":material/bookmark_border:", help="Save job"):
                        conflict = job_matching.tracked_elsewhere(record)
                        if conflict:
                            _conflict_dialog(record, conflict, "save")
                        else:
                            job_matching.save_to_saved_jobs(record)
                            st.toast(f"Saved {record.get('company') or 'job'} to Saved Jobs.")
                            st.rerun()
            with apply_col:
                if status == storage.MATCH_STATUS_NEW:
                    if st.button("Add to Applications", key=f"match_apply_{key}", type="primary"):
                        conflict = job_matching.tracked_elsewhere(record)
                        if conflict:
                            _conflict_dialog(record, conflict, "apply")
                        else:
                            job_matching.apply_to_applied_jobs(record)
                            st.toast(f"Added {record.get('company') or 'job'} to Applied Positions.")
                            st.rerun()
            with dismiss_col:
                if status == storage.MATCH_STATUS_DISMISSED:
                    if st.button("", key=f"match_restore_{key}", icon=":material/restore:",
                                 help="Restore to New"):
                        job_matching.set_status(record, storage.MATCH_STATUS_NEW)
                        st.rerun()
                elif status == storage.MATCH_STATUS_NEW:
                    if st.button("", key=f"match_dismiss_{key}", icon=":material/close:", help="Dismiss"):
                        job_matching.set_status(record, storage.MATCH_STATUS_DISMISSED)
                        st.rerun()


def _render_header(profile: dict, unscored: list[dict]) -> None:
    title_col, actions_col = st.columns([2.2, 3], vertical_alignment="center")
    with title_col:
        st.markdown('<div class="jh-page-title">Matching Jobs</div>', unsafe_allow_html=True)
        st.caption("Best-fit roles from job-alert emails, Google Jobs and LinkedIn - ranked for your resume.")
    with actions_col:
        google_ready = job_search_client.is_configured()
        scan_col, search_col, score_col, info_col = st.columns([1.5, 1.5, 1.9, 0.5], vertical_alignment="center")
        with scan_col:
            if st.button("Scan job-alert emails", key="match_scan_gmail_btn", use_container_width=True):
                _scan_gmail(profile)
        with search_col:
            if st.button(
                "Search Google Jobs", key="match_search_google_btn", use_container_width=True,
                disabled=not google_ready,
                help=None if google_ready else f"Set {job_search_client.API_KEY_ENV_VAR} to enable (serpapi.com).",
            ):
                _search_google(profile)
        with score_col:
            if st.button(
                f"Score fit (Ollama {ollama_client.DEFAULT_MODEL})", key="match_score_btn",
                use_container_width=True, disabled=not unscored,
            ):
                _score(unscored)
        with info_col:
            with st.popover("ℹ️", help="About LinkedIn matches"):
                st.caption(
                    "LinkedIn recommendations: ask Claude to *find matching jobs*. It browses LinkedIn in "
                    "your Chrome and adds them here."
                )


def render() -> None:
    with st.container(key="matches_page"):
        profile = storage.load_match_profile()
        matches = storage.load_matched()
        unscored = [r for r in matches if r.get("match_status", storage.MATCH_STATUS_NEW) == storage.MATCH_STATUS_NEW
                    and r.get("fit_score") in (None, "")]

        _render_header(profile, unscored)
        _render_profile_editor(profile)

        counts = {s: sum(1 for r in matches if (r.get("match_status") or storage.MATCH_STATUS_NEW) == s)
                  for s in storage.MATCH_STATUS_OPTIONS}
        with st.container(key="matches_toolbar"):
            filter_cols = st.columns([3.6, 1.1, 0.8], gap="small", vertical_alignment="center")
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
                min_fit = st.number_input(
                    "Min fit", min_value=0, max_value=10, value=0, step=1, key="matches_min_fit"
                )

        visible = [r for r in matches if (r.get("match_status") or storage.MATCH_STATUS_NEW) == status_filter]
        if source_filter:
            visible = [r for r in visible if r.get("source") in source_filter]
        if min_fit:
            visible = [
                r for r in visible if r.get("fit_score") not in (None, "") and float(r["fit_score"]) >= min_fit
            ]
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
                _render_card(record)
