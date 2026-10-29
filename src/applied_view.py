from datetime import date

import streamlit as st

from src import storage


def render() -> None:
    st.header("Edit Applications")
    st.caption("Bulk-editable table of applied roles, with current status. See Applied Positions for the stage-by-stage board.")

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
            "link": st.column_config.LinkColumn("Link"),
            "location": st.column_config.TextColumn("Location"),
            "salary": st.column_config.TextColumn("Salary"),
            "date_saved": st.column_config.DateColumn("Date Saved"),
            "date_applied": st.column_config.DateColumn("Date Applied", default=date.today()),
            "status": st.column_config.SelectboxColumn(
                "Status", options=storage.STATUS_OPTIONS, default="Applied"
            ),
            "notes": st.column_config.TextColumn("Notes"),
        },
    )

    if st.button("Save changes", key="save_applied_btn"):
        records = storage.from_dataframe(edited, date_cols=["date_saved", "date_applied"])
        for record in records:
            if not record.get("status"):
                record["status"] = "Applied"
        storage.save_applied(records)
        st.success(f"Saved {len(records)} position(s).")
        st.rerun()
