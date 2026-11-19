from datetime import date

import streamlit as st

from src import storage


def render(show_header: bool = True) -> None:
    if show_header:
        st.header("Edit Applications")
        st.caption("Bulk-editable table of applied roles, with current status. See the Board view for the stage-by-stage layout.")

    applied = storage.load_applied()
    df = storage.to_dataframe(
        applied, storage.APPLIED_COLUMNS, date_cols=["date_saved", "date_applied"]
    )

    edited = st.data_editor(
        df,
        num_rows="dynamic",
        width="stretch",
        key="applied_editor",
        column_config={
            "company": st.column_config.TextColumn("Company", required=True),
            "title": st.column_config.TextColumn("Title"),
            "link": st.column_config.LinkColumn("Link", display_text="Open ↗"),
            "location": st.column_config.TextColumn("Location"),
            "salary": st.column_config.TextColumn("Salary"),
            "date_saved": st.column_config.DateColumn("Date Saved"),
            "date_applied": st.column_config.DateColumn("Date Applied", default=date.today()),
            "status": st.column_config.SelectboxColumn(
                "Status", options=storage.STATUS_OPTIONS, default="Applied"
            ),
            "rejected_from_stage": st.column_config.TextColumn(
                "Rejected From", disabled=True
            ),
            "notes": st.column_config.TextColumn("Notes"),
            "call_notes": st.column_config.TextColumn("Call Notes", width="large"),
            "description": st.column_config.TextColumn("Job Description", width="large"),
        },
    )

    unsaved = not edited.equals(df)

    if st.button("Save changes", key="save_applied_btn", type="primary"):
        records = storage.from_dataframe(edited, date_cols=["date_saved", "date_applied"])
        for record in records:
            if not record.get("status"):
                record["status"] = "Applied"
        storage.save_applied(records)
        st.success(f"Saved {len(records)} position(s).")
        st.rerun()
    if unsaved:
        st.caption("Unsaved changes")
