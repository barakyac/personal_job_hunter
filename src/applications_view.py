"""Applications: combines what used to be three separate pages (Applied
Positions board, Edit Applications table, Final Outcome board) into one
section with local Active/Completed and Board/Table controls, per the
top-nav redesign. board_view.render() and applied_view.render() are reused
unmodified/near-unmodified so their existing tests keep targeting them
directly - this module only adds the toolbar, the quick "Add application"
dialog, and the compact Completed list."""

from datetime import date

import streamlit as st

from src import applied_view, board_view, layout, storage


def _create_application(company: str, title: str, link: str, location: str, date_applied, status: str) -> None:
    records = storage.load_applied()
    records.append({
        "company": company.strip(),
        "title": title.strip(),
        "link": link.strip(),
        "location": location.strip(),
        "date_saved": date_applied.isoformat(),
        "date_applied": date_applied.isoformat(),
        "status": status,
        "notes": "",
    })
    storage.save_applied(records)


@st.dialog("Add application")
def _add_application_dialog() -> None:
    company = st.text_input("Company :red[*]", key="add_app_company")
    title = st.text_input("Title", key="add_app_title")
    link = st.text_input("Posting link", key="add_app_link")
    location = st.text_input("Location", key="add_app_location")
    date_applied = st.date_input("Date applied", value=date.today(), key="add_app_date")
    status = st.selectbox("Stage", options=storage.STATUS_OPTIONS, index=0, key="add_app_status")

    if st.button("Add application", key="confirm_add_application_btn", type="primary"):
        if not company.strip():
            st.error("Company is required.")
            return
        _create_application(company, title, link, location, date_applied, status)
        st.success(f"Added {company.strip()}.")
        st.rerun()


_OUTCOME_FILTERS = {
    "All": storage.OUTCOME_STATUSES,
    "Offers": ["Offer"],
    "Rejected": ["Rejected"],
    "Withdrawn": ["Withdrawn"],
}


def _render_completed() -> None:
    applied = storage.load_applied()
    outcomes = [r for r in applied if (r.get("status") or "") in storage.OUTCOME_STATUSES]

    counts = {
        label: sum(1 for r in outcomes if (r.get("status") or "") in stages)
        for label, stages in _OUTCOME_FILTERS.items()
    }
    choice = st.segmented_control(
        "Outcome filter", list(_OUTCOME_FILTERS), default="All", key="completed_outcome_filter"
    )
    chosen_label = choice or "All"
    st.caption(" · ".join(f"{label} ({counts[label]})" for label in _OUTCOME_FILTERS))
    stages = _OUTCOME_FILTERS[chosen_label]

    rows = [r for r in outcomes if (r.get("status") or "") in stages]
    if not rows:
        st.info("No applications in this filter yet.")
        return

    for r in rows:
        with st.container(border=True):
            cols = st.columns([3, 1.4, 1.6, 1.6, 1])
            with cols[0]:
                st.markdown(
                    layout.company_mark(r.get("company", ""))
                    + f'<span style="font-weight:700;">{r.get("company") or "Unknown company"}</span>'
                    + f' - {r.get("title") or "Untitled"}',
                    unsafe_allow_html=True,
                )
            with cols[1]:
                color = storage.STATUS_COLORS.get(r.get("status"), "#898781")
                st.markdown(
                    f'<span class="jh-badge" style="background:{color}22;color:{color};">{r.get("status")}</span>',
                    unsafe_allow_html=True,
                )
            with cols[2]:
                st.caption(r.get("date_applied") or "")
            with cols[3]:
                st.caption(f"From: {r.get('rejected_from_stage')}" if r.get("rejected_from_stage") else "")
            with cols[4]:
                if r.get("link"):
                    st.markdown(f"[Open ↗]({r['link']})")


def render() -> None:
    if layout.page_header(
        "Applications",
        "Track active applications and review final outcomes.",
        primary_label="Add application",
        primary_key="add_application_btn",
    ):
        _add_application_dialog()

    active_applied = storage.load_applied()
    stage_counts = {
        s: sum(1 for r in active_applied if (r.get("status") or "Applied") == s)
        for s in storage.PIPELINE_STATUSES
    }
    any_stage_empty = any(c == 0 for c in stage_counts.values())

    # Active/Completed, Board/Table, and Hide empty stages all live in one
    # compact toolbar row - View and Hide-empty only matter in Active mode
    # (and Hide-empty only once Board is the chosen view), so their columns
    # just render nothing when not relevant rather than reflowing the row.
    toolbar = st.columns([1.1, 1.0, 1.7, 3.2], gap="small", vertical_alignment="center")
    with toolbar[0]:
        tab = st.segmented_control(
            "Status", ["Active", "Completed"], default="Active",
            key="applications_status_tab", label_visibility="collapsed",
        )
        tab = tab or "Active"

    view = "Board"
    hide_empty = False
    if tab == "Active":
        with toolbar[1]:
            view = st.segmented_control(
                "View", ["Board", "Table"], default="Board",
                key="applications_view_mode", label_visibility="collapsed",
            )
            view = view or "Board"
        if view == "Board" and any_stage_empty:
            with toolbar[2]:
                hide_empty = st.toggle(
                    "Hide empty stages", value=False, key="applications_hide_empty_stages"
                )

    if tab == "Completed":
        _render_completed()
        return

    if view == "Table":
        applied_view.render(show_header=False)
    else:
        board_view.render(
            stages=storage.PIPELINE_STATUSES,
            title="Applied Positions",
            caption="Active applications grouped by stage. Change a card's stage to move it.",
            show_header=False,
            hide_empty=hide_empty,
        )
