import streamlit as st

from src import storage


def render(
    stages: list[str] | None = None,
    title: str = "Applied Positions",
    caption: str = "Applied positions grouped by stage. Change a card's stage to move it.",
    empty_message: str = "No applied positions yet. Add one from the Saved Positions or Edit Applications page.",
) -> None:
    stages = stages or storage.STATUS_OPTIONS

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

                    new_stage = st.selectbox(
                        "Stage",
                        options=storage.STATUS_OPTIONS,
                        index=storage.STATUS_OPTIONS.index(stage),
                        key=f"board_stage_{i}",
                        label_visibility="collapsed",
                    )
                    if new_stage != stage:
                        applied[i]["status"] = new_stage
                        storage.save_applied(applied)
                        st.rerun()
