from datetime import date

import streamlit as st

from src import fit_analysis, job_extract, ollama_client, storage


def render() -> None:
    st.header("Saved Positions")
    st.caption("Roles you're considering but haven't applied to yet.")

    saved = storage.load_saved()
    # Closed postings sort to the end by default - everything still open
    # (what the user actually needs to act on) stays up top, in its
    # original relative order (Python's sort is stable).
    saved = sorted(saved, key=lambda r: r.get("posting_status") == storage.POSTING_STATUS_CLOSED)

    closed_count = sum(1 for r in saved if r.get("posting_status") == storage.POSTING_STATUS_CLOSED)
    hide_closed = False
    if closed_count:
        hide_closed = st.toggle(f"Hide closed postings ({closed_count})", value=True, key="hide_closed_postings")

    # Hidden rows never reach the editor, so they can't be edited here -
    # they're carried through untouched and reattached wherever `edited` is
    # turned back into a full record list, so hiding them never drops them
    # from storage.
    visible = [r for r in saved if not (hide_closed and r.get("posting_status") == storage.POSTING_STATUS_CLOSED)]
    hidden = [r for r in saved if hide_closed and r.get("posting_status") == storage.POSTING_STATUS_CLOSED]

    def records_from_editor(edited_df) -> list[dict]:
        return storage.from_dataframe(edited_df, date_cols=["date_saved"]) + hidden

    df = storage.to_dataframe(visible, storage.SAVED_COLUMNS, date_cols=["date_saved"])

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
            "date_saved": st.column_config.DateColumn("Date Saved", default=date.today()),
            "notes": st.column_config.TextColumn("Notes"),
            "description": st.column_config.TextColumn("Job Description", width="large"),
            "fit_score": st.column_config.NumberColumn("Fit Score", min_value=1, max_value=10, step=1),
            "fit_notes": st.column_config.TextColumn("Fit Notes", width="large"),
        },
    )

    unsaved = not edited.equals(df)

    col_save, col_calc, col_paste = st.columns(3)
    with col_save:
        if st.button("Save changes", key="save_saved_btn", type="primary"):
            records = records_from_editor(edited)
            storage.save_saved(records)
            st.success(f"Saved {len(records)} position(s).")
            st.rerun()
        if unsaved:
            st.caption("Unsaved changes")
    with col_calc:
        if st.button(f"Calculate fit (Ollama {ollama_client.DEFAULT_MODEL})", key="calc_fit_saved_btn"):
            records = records_from_editor(edited)
            resume_text = storage.load_resume()
            targets = [i for i, r in enumerate(records) if r.get("fit_score") in (None, "")]
            if not resume_text.strip():
                st.error("Add a resume on the Personal Work Info tab first.")
            elif not records:
                st.info("Add a saved position above first.")
            elif not targets:
                st.info("Every saved position already has a fit score.")
            else:
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
                        # Each position is scored and saved on its own, one
                        # at a time - not all held back for a single save
                        # at the end, so progress survives an interruption
                        # and earlier results are visible right away.
                        records[i]["fit_score"] = result["fit_score"]
                        records[i]["fit_notes"] = result["fit_notes"]
                        storage.save_saved(records)
                    progress.progress((n + 1) / len(targets))

                progress.empty()
                status_box.empty()
                for error in errors:
                    st.warning(error)
                st.success(f"Analyzed {len(targets) - len(errors)} of {len(targets)} position(s).")
                st.rerun()
    with col_paste:
        with st.popover("Paste job description to create a saved position"):
            # Keys are versioned (like resume_view's supporting-document
            # uploader) so a successful create can clear the fields by
            # advancing to a fresh, empty widget instead of reusing one
            # Streamlit won't let us overwrite via session_state after it's
            # already been instantiated this run.
            paste_version = st.session_state.get("paste_popover_version", 0)
            link = st.text_input("Job link :red[*]", key=f"paste_description_link_{paste_version}")
            pasted = st.text_area(
                "Job description :red[*]", height=200, key=f"paste_description_text_{paste_version}"
            )
            if st.button(f"Create (Ollama {job_extract.DEFAULT_MODEL})", key="create_from_paste_btn"):
                if not link.strip():
                    st.error("Add the job link first.")
                elif not pasted.strip():
                    st.error("Paste a job description first.")
                else:
                    try:
                        with st.spinner(f"Extracting fields with Ollama {job_extract.DEFAULT_MODEL}..."):
                            fields = job_extract.extract_fields(pasted)
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
                            "description": pasted,
                        })
                        storage.save_saved(records)
                        st.session_state["paste_popover_version"] = paste_version + 1
                        st.success(f"Added {fields['company'] or 'position'} to Saved Positions.")
                        st.rerun()

    st.divider()
    st.subheader("Close a posting")
    st.caption("Quickly mark a saved posting as no longer accepting applications.")

    records_for_status = records_from_editor(edited)
    open_records = [
        (i, r) for i, r in enumerate(records_for_status)
        if r.get("posting_status", storage.POSTING_STATUS_OPEN) != storage.POSTING_STATUS_CLOSED
    ]
    if not open_records:
        st.caption("No open postings.")
    else:
        for i, r in open_records:
            close_col, label_col = st.columns([1, 6])
            with close_col:
                if st.button("Close", key=f"close_posting_{i}"):
                    records_for_status[i]["posting_status"] = storage.POSTING_STATUS_CLOSED
                    storage.save_saved(records_for_status)
                    st.success(f"Marked {r['company']} as closed for applications.")
                    st.rerun()
            with label_col:
                st.write(f"{r['company']} — {r['title'] or 'Untitled'}")

    st.divider()
    st.subheader("Mark a position as applied")

    records = records_from_editor(edited)
    if not records:
        st.info("Add a saved position above to move it into Applied Positions.")
        return

    labels = [f"{r['company']} — {r['title'] or 'Untitled'}" for r in records]
    choice = st.selectbox("Position", options=range(len(records)), format_func=lambda i: labels[i])

    col1, col2 = st.columns(2)
    with col1:
        applied_date = st.date_input("Date applied", value=date.today(), key="move_applied_date")
    with col2:
        status = st.selectbox("Status", options=storage.STATUS_OPTIONS, index=0, key="move_status")

    if st.button("Move to Applied Positions", type="primary"):
        moved = records.pop(choice)
        moved.pop("posting_status", None)
        moved["date_applied"] = applied_date.isoformat()
        moved["status"] = status

        storage.save_saved(records)

        applied = storage.load_applied()
        applied.append(moved)
        storage.save_applied(applied)

        st.success(f"Moved {moved['company']} to Applied Positions.")
        st.rerun()
