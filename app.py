import streamlit as st

from src import applied_view, board_view, resume_view, saved_view
from src import storage

st.set_page_config(page_title="Job Hunter Dashboard", layout="wide")

PAGES = {
    "Applied Positions": lambda: board_view.render(
        stages=storage.PIPELINE_STATUSES,
        title="Applied Positions",
        caption="Active applications grouped by stage. Change a card's stage to move it.",
    ),
    "Final Outcome": lambda: board_view.render(
        stages=storage.OUTCOME_STATUSES,
        title="Final Outcome",
        caption="Applications that have reached a final outcome.",
        empty_message="No applications have reached a final outcome yet.",
    ),
    "Saved Positions": saved_view.render,
    "Edit Applications": applied_view.render,
    "Personal Work Info": resume_view.render,
}

st.sidebar.title("Job Hunter")
page = st.sidebar.radio("Go to", list(PAGES.keys()))

PAGES[page]()
