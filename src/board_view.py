import streamlit as st

from src import chat_view, storage

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


def _save_call_notes(index: int, call_notes: str) -> None:
    applied = storage.load_applied()
    applied[index]["call_notes"] = call_notes
    storage.save_applied(applied)


@st.dialog("Call details", width="large")
def _call_notes_dialog(index: int) -> None:
    applied = storage.load_applied()
    record = applied[index]

    notes_col, chat_col = st.columns([2, 1], gap="large")

    with notes_col:
        call_notes = st.text_area(
            "Call details",
            value=record.get("call_notes", ""),
            height=500,
            key=f"call_notes_{index}",
            label_visibility="collapsed",
        )

        _, save_col = st.columns([4, 1])
        with save_col:
            if st.button("Save call notes", key=f"save_call_notes_{index}"):
                _save_call_notes(index, call_notes)
                st.rerun()

    with chat_col:
        chat_view.render()


def render(
    stages: list[str] | None = None,
    title: str = "Applied Positions",
    caption: str = "Applied positions grouped by stage. Change a card's stage to move it.",
    empty_message: str = "No applied positions yet. Add one from the Saved Positions or Edit Applications page.",
) -> None:
    stages = stages or storage.STATUS_OPTIONS

    st.markdown(_FULLSCREEN_DIALOG_CSS, unsafe_allow_html=True)
    st.header(title)
    st.caption(caption)

    applied = storage.load_applied()

    if not applied:
        st.info(empty_message)
        return

    columns = st.columns(len(stages))

    for col, stage in zip(columns, stages):
        color = storage.STATUS_COLORS[stage]
        indices = [i for i, r in enumerate(applied) if (r.get("status") or "Applied") == stage]

        with col:
            st.markdown(
                f'<span style="display:inline-block;width:8px;height:8px;border-radius:50%;'
                f'background:{color};margin-right:6px;"></span>'
                f'<span style="font-weight:600;">{stage}</span> '
                f'<span style="color:#898781;">({len(indices)})</span>',
                unsafe_allow_html=True,
            )
            st.markdown(f'<div style="height:2px;background:{color};margin:4px 0 10px 0;"></div>', unsafe_allow_html=True)

            for i in indices:
                record = applied[i]
                with st.container(border=True):
                    st.markdown(f"**{record.get('company') or 'Unknown company'}**")
                    if record.get("title"):
                        st.caption(record["title"])
                    if record.get("link"):
                        st.markdown(f"[Open posting]({record['link']})")
                    meta_bits = [b for b in [record.get("location"), record.get("date_applied")] if b]
                    if meta_bits:
                        st.caption(" · ".join(meta_bits))
                    if stage == "Rejected" and record.get("rejected_from_stage"):
                        st.caption(f"Rejected from: {record['rejected_from_stage']}")
                    if record.get("call_notes"):
                        with st.expander("Call notes"):
                            st.write(record["call_notes"])

                    if stage == "Applied":
                        if st.button("In a call", key=f"in_a_call_btn_{i}"):
                            _call_notes_dialog(i)

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
