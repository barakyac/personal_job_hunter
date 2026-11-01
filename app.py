import streamlit as st
from dotenv import load_dotenv

from src import applied_view, board_view, chat_view, resume_view, saved_view
from src import storage

load_dotenv()  # picks up ANTHROPIC_API_KEY / OPENAI_API_KEY from a local .env, if present

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

if "show_assistant" not in st.session_state:
    st.session_state.show_assistant = True


def _hide_assistant() -> None:
    st.session_state.show_assistant = False


def _show_assistant() -> None:
    st.session_state.show_assistant = True


st.sidebar.title("Job Hunter")
page = st.sidebar.radio("Go to", list(PAGES.keys()))

if not st.session_state.show_assistant:
    # The native toolbar (Deploy + "...") is hidden via .streamlit/config.toml,
    # so this corner is otherwise empty - render a normal button and pin it
    # there via its key-derived CSS class.
    st.markdown(
        """
        <style>
        div.st-key-show_assistant_btn {
            position: fixed;
            top: 0.75rem;
            right: 1rem;
            z-index: 999999;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.button("Show Assistant", key="show_assistant_btn", on_click=_show_assistant)

if st.session_state.show_assistant:
    main_col, chat_col = st.columns([3, 1], gap="large")
else:
    main_col = st.container()
    chat_col = None

with main_col:
    PAGES[page]()

if chat_col is not None:
    with chat_col:
        chat_view.render(on_hide=_hide_assistant)
