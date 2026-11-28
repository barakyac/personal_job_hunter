from datetime import date

import streamlit as st

from src import fit_analysis, job_extract, layout, ollama_client, storage


def _unverified_fields_warning(fields: dict) -> str:
    """The warning to show when job_extract couldn't verify some of its
    output against the source text (see job_extract.unverified_fields) -
    empty string when everything checked out, so callers can just
    `if warning: st.warning(warning)`."""
    unverified = fields.get("unverified")
    if not unverified:
        return ""
    return (
        f"Couldn't verify {', '.join(unverified)} against the posting text - "
        "worth a second look before applying."
    )


def _fit_score_sort_key(record: dict) -> float:
    try:
        return -float(record.get("fit_score"))
    except (TypeError, ValueError):
        return float("inf")  # not yet scored - sorts after every scored position


def _move_to_applied(records: list[dict], choice: int, applied_date, status: str) -> dict:
    moved = records.pop(choice)
    moved.pop("posting_status", None)
    moved["date_applied"] = applied_date.isoformat()
    moved["status"] = status

    storage.save_saved(records)

    applied = storage.load_applied()
    applied.append(moved)
    storage.save_applied(applied)
    return moved


def _find_record(record: dict) -> tuple[list[dict], int | None]:
    """Reload Saved Positions fresh and locate `record` in it, so every
    row action works off current on-disk state instead of a snapshot
    captured when the page was rendered (another row's action, or a
    concurrent edit, may have already changed indices)."""
    records = storage.load_saved()
    idx = storage.find_record_index(
        records, record.get("company", ""), record.get("title", ""), record.get("link", "")
    )
    return records, idx


@st.dialog("Mark applied")
def _mark_applied_dialog(record: dict, row_key: str) -> None:
    st.write(f"Mark **{record.get('company') or 'Unknown company'} - {record.get('title') or 'Untitled'}** as applied?")
    applied_date = st.date_input("Date applied", value=date.today(), key=f"mark_applied_date_{row_key}")
    status = st.selectbox(
        "Initial stage", options=storage.STATUS_OPTIONS, index=0, key=f"mark_applied_status_{row_key}"
    )
    if st.button("Mark applied", key=f"confirm_mark_applied_{row_key}", type="primary"):
        records, idx = _find_record(record)
        if idx is None:
            st.error("Couldn't find this position anymore - it may have changed.")
            return
        moved = _move_to_applied(records, idx, applied_date, status)
        st.success(f"Moved {moved['company']} to Applied Positions.")
        st.rerun()


def _analyze_one(record: dict) -> None:
    resume_text = storage.load_resume()
    if not resume_text.strip():
        st.error("Add a resume on the Profile page first.")
        return
    records, idx = _find_record(record)
    if idx is None:
        st.warning("Couldn't find this position anymore - it may have changed.")
        return
    try:
        with st.spinner(f"Analyzing {record.get('company', '?')}..."):
            result = fit_analysis.analyze(resume_text, records[idx])
    except ollama_client.OllamaError as exc:
        st.error(str(exc))
        return
    records[idx].update(result)
    storage.save_saved(records)
    st.success(f"Scored {records[idx].get('company', 'this position')}.")
    st.rerun()


def _toggle_closed(record: dict) -> None:
    records, idx = _find_record(record)
    if idx is None:
        return
    current = records[idx].get("posting_status", storage.POSTING_STATUS_OPEN)
    records[idx]["posting_status"] = (
        storage.POSTING_STATUS_OPEN if current == storage.POSTING_STATUS_CLOSED else storage.POSTING_STATUS_CLOSED
    )
    storage.save_saved(records)
    st.rerun()


@st.dialog("Edit saved position")
def _edit_saved_dialog(record: dict, row_key: str) -> None:
    company = st.text_input("Company", value=record.get("company", ""), key=f"edit_saved_company_{row_key}")
    title = st.text_input("Title", value=record.get("title", ""), key=f"edit_saved_title_{row_key}")
    link = st.text_input("Link", value=record.get("link", ""), key=f"edit_saved_link_{row_key}")
    loc_col, salary_col = st.columns(2)
    with loc_col:
        location = st.text_input("Location", value=record.get("location", ""), key=f"edit_saved_location_{row_key}")
    with salary_col:
        salary = st.text_input("Salary", value=record.get("salary", ""), key=f"edit_saved_salary_{row_key}")
    notes = st.text_area("Notes", value=record.get("notes", ""), key=f"edit_saved_notes_{row_key}", height=100)
    description = st.text_area(
        "Job description", value=record.get("description", ""), key=f"edit_saved_description_{row_key}", height=150
    )

    if st.button("Save", key=f"save_edit_saved_{row_key}", type="primary"):
        records, idx = _find_record(record)
        if idx is None:
            st.error("Couldn't find this position anymore - it may have changed.")
            return
        records[idx].update({
            "company": company.strip(), "title": title.strip(), "link": link.strip(),
            "location": location.strip(), "salary": salary.strip(),
            "notes": notes, "description": description,
        })
        storage.save_saved(records)
        st.success("Saved.")
        st.rerun()


@st.dialog("Remove this saved position?")
def _confirm_remove_dialog(record: dict, row_key: str) -> None:
    st.write(f"This permanently removes **{record.get('company') or 'Unknown company'} - {record.get('title') or 'Untitled'}** from Saved Positions.")
    confirm_col, cancel_col = st.columns(2)
    with confirm_col:
        if st.button("Remove", key=f"confirm_remove_saved_{row_key}", type="primary"):
            records, idx = _find_record(record)
            if idx is not None:
                records.pop(idx)
                storage.save_saved(records)
            st.rerun()
    with cancel_col:
        if st.button("Cancel", key=f"cancel_remove_saved_{row_key}"):
            st.rerun()


def _render_add_job_popover() -> None:
    with st.popover("Add job", use_container_width=True):
        # Keys are versioned (like resume_view's supporting-document
        # uploader) so a successful create can clear the fields by
        # advancing to a fresh, empty widget instead of reusing one
        # Streamlit won't let us overwrite via session_state after it's
        # already been instantiated this run.
        paste_version = st.session_state.get("paste_popover_version", 0)
        link = st.text_input("Job link :red[*]", key=f"paste_description_link_{paste_version}")
        pasted = st.text_area(
            "Job description (optional - leave blank to fetch it from the link automatically)",
            height=200,
            key=f"paste_description_text_{paste_version}",
        )
        if st.button(f"Create (Ollama {job_extract.DEFAULT_MODEL})", key="create_from_paste_btn"):
            if not link.strip():
                st.error("Add the job link first.")
            else:
                # A pasted description always wins - some sites (LinkedIn,
                # Workday job boards, ...) block a plain scripted GET
                # request and fetch_posting_text comes back empty, so
                # pasting it by hand is the fallback for exactly those.
                description = pasted.strip()
                if not description:
                    with st.spinner("Fetching the job posting..."):
                        description = fit_analysis.fetch_posting_text(link.strip())
                if not description:
                    st.error(
                        "Couldn't fetch that page automatically - some sites (LinkedIn, Workday "
                        "job boards, ...) block a plain request. Paste the job description above "
                        "instead."
                    )
                else:
                    try:
                        with st.spinner(f"Extracting fields with Ollama {job_extract.DEFAULT_MODEL}..."):
                            fields = job_extract.extract_fields(description)
                    except ollama_client.OllamaError as exc:
                        st.error(str(exc))
                    else:
                        records = storage.load_saved()
                        records.append({
                            "company": fields["company"],
                            "title": fields["title"],
                            "link": link.strip(),
                            "location": fields["location"],
                            "salary": fields["salary"],
                            "posting_status": storage.POSTING_STATUS_OPEN,
                            "date_saved": date.today().isoformat(),
                            "notes": "",
                            "description": description,
                        })
                        storage.save_saved(records)
                        st.session_state["paste_popover_version"] = paste_version + 1
                        st.success(f"Added {fields['company'] or 'position'} to Saved Positions.")
                        warning = _unverified_fields_warning(fields)
                        if warning:
                            st.warning(warning)
                        st.rerun()


def _fit_tooltip(record: dict) -> str:
    """The full fit breakdown (notes + matched/gaps/unknowns), for the
    truncated preview's hover tooltip - same evidence-backed sections the
    Matching Jobs page shows in its "Why you match" dialog."""
    sections = [
        ("Matches", record.get("fit_matched")),
        ("Required gaps", record.get("fit_required_gaps")),
        ("Preferred gaps", record.get("fit_preferred_gaps")),
        ("Not mentioned in the resume", record.get("fit_unknowns")),
    ]
    parts = [record.get("fit_notes") or ""]
    for label, text in sections:
        if text:
            parts.append(f"{label}:\n{text}")
    return "\n\n".join(p for p in parts if p)


def _fit_help(record: dict, preview: str) -> str | None:
    """None when there's nothing beyond what `preview` (the truncated text
    actually shown on the card) already shows - compared against `preview`,
    not the full fit_notes: a record with no fit-detail fields makes
    _fit_tooltip() return exactly fit_notes back, which would otherwise
    suppress the tooltip even when `preview` had truncated it, leaving long
    notes with no way to read the rest."""
    tooltip = _fit_tooltip(record)
    return tooltip if tooltip != preview else None


def _render_row(record: dict, row_key: str) -> None:
    posting_status = record.get("posting_status", storage.POSTING_STATUS_OPEN)
    closed = posting_status == storage.POSTING_STATUS_CLOSED

    with st.container(border=True):
        info_col, fit_col, applied_col, analyze_col, open_col, more_col = st.columns(
            [3, 1.4, 1.1, 1.1, 0.9, 0.5]
        )
        with info_col:
            st.markdown(
                layout.company_mark(record.get("company", ""))
                + f'<span style="font-weight:700;">{record.get("company") or "Unknown company"}</span> - '
                + f'<span class="jh-clamp-2">{record.get("title") or "Untitled"}</span>',
                unsafe_allow_html=True,
            )
            meta_bits = [b for b in [record.get("location"), record.get("date_saved")] if b]
            if closed:
                meta_bits.append("Closed for applications")
            elif posting_status == storage.POSTING_STATUS_UNKNOWN:
                meta_bits.append("Couldn't confirm it's still open")
            if meta_bits:
                st.caption(" · ".join(meta_bits))

        with fit_col:
            fit_score = record.get("fit_score")
            if fit_score not in (None, ""):
                st.markdown(f"Fit: **{fit_score}**/10")
                notes = record.get("fit_notes") or ""
                if notes:
                    preview = notes if len(notes) <= 110 else notes[:107] + "..."
                    st.caption(preview, help=_fit_help(record, preview))
            else:
                st.caption("Not scored yet")

        with applied_col:
            if st.button("Mark applied", key=f"mark_applied_row_{row_key}", disabled=closed):
                _mark_applied_dialog(record, row_key)

        with analyze_col:
            if st.button("Analyze fit", key=f"analyze_fit_row_{row_key}", disabled=closed):
                _analyze_one(record)

        with open_col:
            if record.get("link"):
                st.markdown(f"[Open ↗]({record['link']})")

        with more_col:
            with st.popover("⋮", key=f"overflow_{row_key}"):
                if st.button("Edit", key=f"edit_row_{row_key}", use_container_width=True):
                    _edit_saved_dialog(record, row_key)
                close_label = "Reopen" if closed else "Mark closed"
                if st.button(close_label, key=f"toggle_closed_row_{row_key}", use_container_width=True):
                    _toggle_closed(record)
                if st.button("Remove", key=f"remove_row_{row_key}", use_container_width=True):
                    _confirm_remove_dialog(record, row_key)


def render() -> None:
    title_col, add_col = st.columns([5, 1.3], vertical_alignment="center")
    with title_col:
        st.markdown('<div class="jh-page-title">Saved Jobs</div>', unsafe_allow_html=True)
        st.caption("Roles you're considering but haven't applied to yet.")
    with add_col:
        _render_add_job_popover()

    saved = storage.load_saved()
    # Closed postings always sort to the end; within each group, highest fit
    # score first (not-yet-scored positions sort last within their group).
    # Always on, not a toggle - the best open matches should be the first
    # thing you see. Ties keep their original relative order (stable sort).
    saved = sorted(
        saved,
        key=lambda r: (r.get("posting_status") == storage.POSTING_STATUS_CLOSED, _fit_score_sort_key(r)),
    )

    closed_count = sum(1 for r in saved if r.get("posting_status") == storage.POSTING_STATUS_CLOSED)
    toolbar_cols = st.columns([2, 2, 1.3])
    hide_closed = False
    with toolbar_cols[0]:
        if closed_count:
            hide_closed = st.toggle(f"Hide closed postings ({closed_count})", value=True, key="hide_closed_postings")
    with toolbar_cols[1]:
        search = st.text_input(
            "Search", placeholder="Search company or title", key="saved_search", label_visibility="collapsed"
        )
    with toolbar_cols[2]:
        if st.button(f"Calculate fit for all (Ollama {ollama_client.DEFAULT_MODEL})", key="calc_fit_saved_btn"):
            _run_bulk_fit_analysis()

    visible = [r for r in saved if not (hide_closed and r.get("posting_status") == storage.POSTING_STATUS_CLOSED)]
    if search.strip():
        q = search.strip().lower()
        visible = [
            r for r in visible
            if q in (r.get("company") or "").lower() or q in (r.get("title") or "").lower()
        ]

    if not saved:
        st.info("Nothing saved yet - add one with \"Add job\" above.")
    elif not visible:
        st.caption("No saved positions match the current filters.")
    else:
        for i, record in enumerate(visible):
            row_key = record.get("link") or f"{record.get('company', '')}_{record.get('title', '')}_{i}"
            _render_row(record, row_key)

    with st.expander("Bulk edit table (advanced)"):
        st.caption("Edit any field directly in the grid, including ones not shown on the cards above.")
        df = storage.to_dataframe(saved, storage.SAVED_COLUMNS, date_cols=["date_saved", "posting_checked_at"])
        edited = st.data_editor(
            df,
            num_rows="dynamic",
            width="stretch",
            key="saved_editor",
            column_config={
                "company": st.column_config.TextColumn("Company", required=True),
                "title": st.column_config.TextColumn("Title"),
                "link": st.column_config.LinkColumn("Link", display_text="Open ↗"),
                "location": st.column_config.TextColumn("Location"),
                "salary": st.column_config.TextColumn("Salary"),
                "posting_status": st.column_config.SelectboxColumn(
                    "Status", options=storage.POSTING_STATUS_OPTIONS, default=storage.POSTING_STATUS_OPEN,
                    required=True,
                ),
                "posting_checked_at": st.column_config.DateColumn("Status Checked"),
                "date_saved": st.column_config.DateColumn("Date Saved", default=date.today()),
                "notes": st.column_config.TextColumn("Notes"),
                "description": st.column_config.TextColumn("Job Description", width="large"),
                "fit_score": st.column_config.NumberColumn("Fit Score", min_value=1, max_value=10, step=1),
                "fit_notes": st.column_config.TextColumn("Fit Notes", width="large"),
                "fit_matched": st.column_config.TextColumn("Matches", width="large"),
                "fit_required_gaps": st.column_config.TextColumn("Required Gaps", width="large"),
                "fit_preferred_gaps": st.column_config.TextColumn("Preferred Gaps", width="large"),
                "fit_unknowns": st.column_config.TextColumn("Not Mentioned In Resume", width="large"),
            },
        )

        unsaved = not edited.equals(df)
        if st.button("Save changes", key="save_saved_btn", type="primary"):
            records = storage.from_dataframe(edited, date_cols=["date_saved", "posting_checked_at"])
            storage.save_saved(records)
            st.success(f"Saved {len(records)} position(s).")
            st.rerun()
        if unsaved:
            st.caption("Unsaved changes")


def _run_bulk_fit_analysis() -> None:
    records = storage.load_saved()
    resume_text = storage.load_resume()
    targets = [
        i for i, r in enumerate(records)
        if r.get("fit_score") in (None, "")
        and r.get("posting_status", storage.POSTING_STATUS_OPEN) != storage.POSTING_STATUS_CLOSED
    ]
    if not resume_text.strip():
        st.error("Add a resume on the Profile page first.")
        return
    if not records:
        st.info("Add a saved position first.")
        return
    if not targets:
        st.info("Every open saved position already has a fit score.")
        return

    progress = st.progress(0.0)
    status_box = st.empty()
    errors = []

    for n, i in enumerate(targets):
        job = records[i]
        status_box.text(f"Analyzing {job.get('company', '?')} - {job.get('title', '')}...")
        try:
            result = fit_analysis.analyze(resume_text, job)
        except ollama_client.OllamaError as exc:
            errors.append(f"{job.get('company', '?')}: {exc}")
        else:
            # Each position is scored and saved on its own, one at a time -
            # not all held back for a single save at the end, so progress
            # survives an interruption and earlier results are visible
            # right away.
            records[i].update(result)
            storage.save_saved(records)
        progress.progress((n + 1) / len(targets))

    progress.empty()
    status_box.empty()
    for error in errors:
        st.warning(error)
    st.success(f"Analyzed {len(targets) - len(errors)} of {len(targets)} position(s).")
    st.rerun()
