from datetime import date

import streamlit as st

from src import fit_analysis, ollama_client, storage


def render() -> None:
    st.header("Saved Positions")
    st.caption("Roles you're considering but haven't applied to yet.")

    saved = storage.load_saved()
    df = storage.to_dataframe(saved, storage.SAVED_COLUMNS, date_cols=["date_saved"])

    edited = st.data_editor(
        df,
        num_rows="dynamic",
        width="stretch",
        key="saved_editor",
        column_config={
            "company": st.column_config.TextColumn("Company", required=True),
            "title": st.column_config.TextColumn("Title"),
            "link": st.column_config.LinkColumn("Link"),
            "location": st.column_config.TextColumn("Location"),
            "salary": st.column_config.TextColumn("Salary"),
            "date_saved": st.column_config.DateColumn("Date Saved", default=date.today()),
            "notes": st.column_config.TextColumn("Notes"),
            "fit_score": st.column_config.NumberColumn("Fit Score", min_value=1, max_value=10, step=1),
            "fit_notes": st.column_config.TextColumn("Fit Notes", width="large"),
        },
    )

    col_save, col_calc = st.columns(2)
    with col_save:
        if st.button("Save changes", key="save_saved_btn"):
            records = storage.from_dataframe(edited, date_cols=["date_saved"])
            storage.save_saved(records)
            st.success(f"Saved {len(records)} position(s).")
            st.rerun()
    with col_calc:
        if st.button(f"Calculate fit (Ollama {ollama_client.DEFAULT_MODEL})", key="calc_fit_saved_btn"):
            records = storage.from_dataframe(edited, date_cols=["date_saved"])
            resume_text = storage.load_resume()
            if not resume_text.strip():
                st.error("Add a resume on the Personal Work Info tab first.")
            elif not records:
                st.info("Add a saved position above first.")
            else:
                progress = st.progress(0.0)
                status_box = st.empty()

                def on_progress(n, total, job):
                    status_box.text(f"Analyzing {job.get('company', '?')} - {job.get('title', '')}...")
                    progress.progress(n / total)

                errors = fit_analysis.analyze_many(
                    resume_text, records, list(range(len(records))), on_progress=on_progress
                )
                progress.progress(1.0)
                status_box.empty()
                storage.save_saved(records)
                for error in errors:
                    st.warning(error)
                st.success(f"Analyzed {len(records) - len(errors)} of {len(records)} position(s).")
                st.rerun()

    st.divider()
    st.subheader("Mark a position as applied")

    records = storage.from_dataframe(edited, date_cols=["date_saved"])
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
        moved["date_applied"] = applied_date.isoformat()
        moved["status"] = status

        storage.save_saved(records)

        applied = storage.load_applied()
        applied.append(moved)
        storage.save_applied(applied)

        st.success(f"Moved {moved['company']} to Applied Positions.")
        st.rerun()
