from datetime import date, datetime

import streamlit as st

from src import chat_view, layout, storage

# Stages where "time since applied" is a meaningful follow-up signal - once
# a position has reached a final outcome there's nothing left to follow up
# on, so OUTCOME_STATUSES cards never show this line.
_FOLLOW_UP_AFTER_DAYS = 10

# st.dialog's built-in widths top out well short of the viewport, so this
# forces the dialog panel itself to cover the whole window; everything else
# (backdrop, header with title + X, Esc/outside-click dismiss, dark theme
# colors) comes from st.dialog for free.
_FULLSCREEN_DIALOG_CSS = """
<style>
/* [data-testid="stDialog"] is the full-viewport backdrop wrapper, already
   fixed/inset-0 by default; the actual visible panel is its first child
   (an emotion-generated class with no stable testid), which is what needs
   resizing to fill the viewport instead of Streamlit's centered "large". */
div[data-testid="stDialog"] > div:first-child {
    width: 100vw !important;
    max-width: 100vw !important;
    height: 100vh !important;
    max-height: 100vh !important;
}
/* Scoped to the call-notes field's own key-derived class (not a bare
   "textarea" selector) so it doesn't also stretch the Assistant chat's
   input box, which is now embedded in this same dialog. */
div[data-testid="stDialog"] div[class*="st-key-call_notes_"] textarea {
    min-height: 65vh !important;
}
</style>
"""


def _save_call_details(index: int) -> None:
    """Single combined save for the Call details dialog, wired as the Save
    button's `on_click` callback - not called from inside the button's own
    `if st.button(...)` block. Streamlit runs `on_click` callbacks before
    the rest of the script (and its widgets) are (re-)instantiated for this
    run; writing to a widget's `st.session_state` key is only legal before
    that widget exists for the run, so this has to happen in the callback,
    not in the handler block below the text_area/button that already
    created those keys this run (that ordering used to raise
    StreamlitWidgetAlreadyInstantiatedError on every click).

    The dialog used to split this into two buttons - "Log a new call"
    (prepend a dated entry) and "Save call notes" (save the free-edit box) -
    which meant filling in both the "What happened" box and hand-editing
    Full history in the same sitting needed two separate clicks, and it was
    easy to click only one and lose the other edit. One button now does
    both: if "What happened" has text, it's prepended as a new dated entry
    on top of the Full history box's current value (not what's on disk) -
    using the box's current, possibly hand-edited text as the base, same
    string field (so the Table view and existing records need no
    migration). Reading both text areas and the date from session_state
    (rather than taking them as arguments) is what lets this run as a
    callback: a callback fires from the widget's own on_click wiring, with
    no access to local variables from a script body it runs before.

    Also pushes the result back into the "Full history" text_area's own
    session_state key, and clears the "What happened" box's. Once a
    text_area's key is already in session_state, Streamlit ignores the
    `value=` it's rendered with on every later rerun - without this, the
    Full history box would keep showing whatever it last displayed, out of
    sync with the entry just saved, and a later click would silently
    overwrite it with that stale text."""
    applied = storage.load_applied()
    new_notes = st.session_state.get(f"new_call_notes_{index}", "")
    call_date = st.session_state.get(f"new_call_date_{index}") or date.today()
    full_history = st.session_state.get(f"call_notes_{index}", "")
    base = (full_history or "").strip()
    if new_notes.strip():
        entry = f"### {call_date.isoformat()}\n{new_notes.strip()}"
        updated = f"{entry}\n\n{base}" if base else entry
    else:
        updated = base
    applied[index]["call_notes"] = updated
    try:
        storage.save_applied(applied)
    except OSError as exc:
        # st.error() from inside a fragment-scoped on_click callback is a
        # pattern Streamlit doesn't actually support: it renders at the top
        # of the whole app behind this still-open dialog, not inside the
        # fragment, so the user would likely never see it. Stash the
        # message instead and let the fragment body render it below, on
        # this same rerun, after this callback has already run.
        st.session_state[f"call_notes_error_{index}"] = str(exc)
        return
    st.session_state.pop(f"call_notes_error_{index}", None)
    st.session_state[f"call_notes_{index}"] = updated
    st.session_state[f"new_call_notes_{index}"] = ""


@st.fragment
def _call_notes_editor(index: int) -> None:
    """The notes half of the Call details dialog, scoped to its own
    fragment so Save only reruns this piece - not the whole dialog. A plain
    `st.rerun()` here would rerun the entire script, which is also how
    Streamlit closes an st.dialog, taking the Assistant/Job description
    panel in chat_col down with it even though neither has anything to do
    with saving a note - the fragment scoping keeps the dialog open and
    chat_col alone. No explicit rerun is needed for Save itself: its
    on_click callback (_save_call_details) runs before this fragment's
    widgets are (re-)instantiated for the run the click triggers, so the
    Full history box already reflects the merged text by the time it's
    drawn in that same run."""
    applied = storage.load_applied()
    record = applied[index]

    add_date_col, add_notes_col = st.columns([1, 3])
    with add_date_col:
        st.date_input("Date", value=date.today(), key=f"new_call_date_{index}")
    with add_notes_col:
        st.text_area(
            "What happened", key=f"new_call_notes_{index}", height=68,
            label_visibility="collapsed", placeholder="What happened on this call? (optional)",
        )

    st.divider()
    st.caption("Full history (edit directly if needed)")
    st.text_area(
        "Call details",
        value=record.get("call_notes", ""),
        height=350,
        key=f"call_notes_{index}",
        label_visibility="collapsed",
    )
    error = st.session_state.pop(f"call_notes_error_{index}", None)
    if error:
        st.error(f"Could not save your call notes: {error}")
    st.button(
        "Save", key=f"save_call_details_{index}", type="primary", use_container_width=True,
        on_click=_save_call_details, args=(index,),
    )


@st.dialog("Call details", width="large")
def _call_notes_dialog(index: int) -> None:
    applied = storage.load_applied()
    record = applied[index]

    notes_col, chat_col = st.columns([2, 1], gap="large")

    with notes_col:
        _call_notes_editor(index)

    with chat_col:
        panel = st.segmented_control(
            "Panel", ["Assistant", "Job description"], default="Assistant",
            key=f"call_dialog_panel_{index}", label_visibility="collapsed",
        )
        panel = panel or "Assistant"
        if panel == "Assistant":
            chat_view.render()
        else:
            st.subheader("Job description")
            description = record.get("description") or ""
            if description.strip():
                st.text_area(
                    "Job description", value=description, height=500,
                    key=f"call_dialog_description_{index}", disabled=True,
                    label_visibility="collapsed",
                )
            else:
                st.caption("No job description saved for this position yet.")


def _save_record_fields(index: int, fields: dict) -> None:
    applied = storage.load_applied()
    applied[index].update(fields)
    storage.save_applied(applied)


@st.dialog("Application details", width="large")
def _card_details_dialog(index: int) -> None:
    applied = storage.load_applied()
    record = applied[index]

    st.markdown(f"**{record.get('company') or 'Unknown company'}**")
    st.caption(record.get("title") or "Untitled")

    link = st.text_input("Posting link", value=record.get("link", ""), key=f"details_link_{index}")
    loc_col, salary_col = st.columns(2)
    with loc_col:
        location = st.text_input("Location", value=record.get("location", ""), key=f"details_location_{index}")
    with salary_col:
        salary = st.text_input("Salary", value=record.get("salary", ""), key=f"details_salary_{index}")
    notes = st.text_area("Notes", value=record.get("notes", ""), key=f"details_notes_{index}", height=100)
    description = st.text_area(
        "Job description", value=record.get("description", ""), key=f"details_description_{index}", height=150
    )

    if st.button("Save details", key=f"save_details_{index}", type="primary"):
        _save_record_fields(index, {
            "link": link, "location": location, "salary": salary,
            "notes": notes, "description": description,
        })
        st.rerun()


def _follow_up_hint(record: dict, stage: str) -> tuple[str, str] | None:
    """Follow-up nudge computed purely from fields the data already has -
    there's no dedicated "next interview date" or interaction-log field in
    the model, so this uses the two signals that do exist:

    - `status` other than "Applied" already means a recruiter interaction
      is in motion (a call/assignment/interview is scheduled or just
      happened) - scheduling rule: never suggest a follow-up once the
      pipeline has moved past the initial "sent, waiting to hear back"
      stage, since there's nothing to chase.
    - `call_notes` being non-empty, even while still in "Applied", is
      evidence an interaction already happened that the stage field alone
      doesn't capture (e.g. a quick screening call before the stage was
      updated) - that's the "latest relevant recruiter interaction" this
      prefers. There's no timestamp on it, though, so its presence alone
      suppresses the hint rather than being used to compute elapsed time.
      With no such evidence, `date_applied` (falling back to `date_saved`)
      is the only timestamp available, so that's the fallback basis.

    Returns (label, tooltip) so the reference date can be shown without
    cluttering the badge text itself."""
    if stage != "Applied":
        return None
    if (record.get("call_notes") or "").strip():
        return None
    date_str = record.get("date_applied") or record.get("date_saved")
    if not date_str:
        return None
    try:
        reference_date = datetime.fromisoformat(str(date_str)).date()
    except ValueError:
        return None
    days = (date.today() - reference_date).days
    if days < _FOLLOW_UP_AFTER_DAYS:
        return None
    label = f"Follow-up suggested · {days} day{'s' if days != 1 else ''}"
    tooltip = f"Applied on {reference_date.isoformat()}, no logged call since"
    return label, tooltip


def render(
    stages: list[str] | None = None,
    title: str = "Applied Positions",
    caption: str = "Applied positions grouped by stage. Change a card's stage to move it.",
    empty_message: str = "No applied positions yet. Add one from Saved Jobs, or with \"Add application\" above.",
    show_header: bool = True,
    hide_empty: bool | None = None,
) -> None:
    stages = stages or storage.STATUS_OPTIONS

    st.markdown(_FULLSCREEN_DIALOG_CSS, unsafe_allow_html=True)
    if show_header:
        st.header(title)
        st.caption(caption)

    applied = storage.load_applied()

    if not any((r.get("status") or "Applied") in stages for r in applied):
        st.info(empty_message)
        return

    stage_counts = {
        stage: sum(1 for r in applied if (r.get("status") or "Applied") == stage) for stage in stages
    }
    # hide_empty is normally self-managed (own toggle rendered right here) -
    # a caller that already renders this toggle itself, in a shared toolbar
    # alongside other page-level controls, passes the chosen value in and
    # this render() trusts it instead of rendering a second copy.
    if hide_empty is None:
        hide_empty = False
        if any(count == 0 for count in stage_counts.values()):
            hide_empty = st.toggle(
                "Hide empty stages", value=False, key=f"hide_empty_stages_{title}"
            )
    visible_stages = [s for s in stages if not (hide_empty and stage_counts[s] == 0)]

    columns = st.columns(len(visible_stages))

    for col, stage in zip(columns, visible_stages):
        color = storage.STATUS_COLORS[stage]
        indices = [i for i, r in enumerate(applied) if (r.get("status") or "Applied") == stage]

        with col:
            st.markdown(
                f'<span style="display:inline-block;width:8px;height:8px;border-radius:50%;'
                f'background:{color};margin-right:6px;"></span>'
                f'<span style="font-weight:600;">{stage}</span> '
                f'<span style="color:{storage.STATUS_COLORS["Withdrawn"]};">({len(indices)})</span>',
                unsafe_allow_html=True,
            )
            st.markdown(f'<div style="height:2px;background:{color};margin:4px 0 10px 0;"></div>', unsafe_allow_html=True)

            for i in indices:
                record = applied[i]
                with st.container(border=True, key=f"jh-card-{i}"):
                    # The info block (company/title/meta/next-action) is a
                    # single click target that opens the details dialog - an
                    # invisible button sized to exactly this sub-container
                    # (see layout.py's jh-click- CSS), never the action row
                    # below it, so the stage selectbox/link/call button keep
                    # working as their own, independent controls.
                    with st.container(key=f"jh-click-{i}"):
                        st.markdown(
                            layout.company_mark(record.get("company", ""))
                            + f'<span style="font-weight:700;">{record.get("company") or "Unknown company"}</span>',
                            unsafe_allow_html=True,
                        )
                        if record.get("title"):
                            st.markdown(f'<div class="jh-clamp-2">{record["title"]}</div>', unsafe_allow_html=True)
                        meta_bits = [b for b in [record.get("location"), record.get("date_applied")] if b]
                        if meta_bits:
                            st.caption(" · ".join(meta_bits))
                        if stage == "Rejected" and record.get("rejected_from_stage"):
                            st.caption(f"Rejected from: {record['rejected_from_stage']}")
                        hint = _follow_up_hint(record, stage)
                        if hint:
                            label, tooltip = hint
                            st.markdown(
                                f'<span class="jh-next-action" title="{tooltip}" '
                                f'style="background:{color}26;color:{color};">{label}</span>',
                                unsafe_allow_html=True,
                            )
                        if st.button("Open details", key=f"details_btn_{i}"):
                            _card_details_dialog(i)

                    if record.get("call_notes"):
                        # A pop-up dialog rather than an inline expander -
                        # reuses _call_notes_dialog (same one "Log call"
                        # opens) so viewing notes and editing them happen in
                        # the same place instead of two different surfaces.
                        if st.button(
                            "Call notes", key=f"view_call_notes_btn_{i}",
                            icon="💬", help="View call notes",
                            use_container_width=True,
                        ):
                            _call_notes_dialog(i)

                    # The link button needs its own full-width row: its
                    # accessible name/label has to actually read "Open job
                    # posting" for a screen reader (Streamlit's `help`
                    # tooltip isn't exposed as the button's accessible
                    # name), so the visible label is that same text rather
                    # than an icon-only glyph - too wide to share a row with
                    # the other two compact controls.
                    if record.get("link"):
                        st.link_button(
                            "Open job posting", record["link"],
                            icon="↗", help="Open job posting", type="tertiary",
                            use_container_width=True,
                        )

                    action_cols = st.columns([1, 2], vertical_alignment="center")
                    with action_cols[0]:
                        # Opens _call_notes_dialog, a free-text notes field
                        # for a call that already happened (or is in
                        # progress) - not a scheduler, hence "Log", not
                        # "Schedule". Available at every active pipeline
                        # stage, not just "Applied", since calls happen at
                        # any point before a final outcome.
                        if st.button("Log call", key=f"in_a_call_btn_{i}", help="Add notes from a call"):
                            _call_notes_dialog(i)
                    with action_cols[1]:
                        new_stage = st.selectbox(
                            "Stage",
                            options=storage.STATUS_OPTIONS,
                            index=storage.STATUS_OPTIONS.index(stage),
                            key=f"board_stage_{i}",
                            label_visibility="collapsed",
                        )
                        if new_stage != stage:
                            if new_stage == "Rejected":
                                applied[i]["rejected_from_stage"] = stage
                            elif stage == "Rejected":
                                applied[i].pop("rejected_from_stage", None)
                            applied[i]["status"] = new_stage
                            storage.save_applied(applied)
                            st.rerun()
