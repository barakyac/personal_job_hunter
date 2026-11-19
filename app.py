import streamlit as st
from dotenv import load_dotenv

from src import applications_view, layout, mail_view, resume_view, saved_view

load_dotenv()  # picks up ANTHROPIC_API_KEY / OPENAI_API_KEY / GOOGLE_OAUTH_CLIENT_* from a local .env, if present

st.set_page_config(page_title="Job Hunter Dashboard", layout="wide")

PAGES = {
    "Applications": applications_view.render,
    "Saved Jobs": saved_view.render,
    "Mail Inbox": mail_view.render,
    "Profile": resume_view.render,
}

if layout.CURRENT_PAGE_KEY not in st.session_state:
    st.session_state[layout.CURRENT_PAGE_KEY] = "Applications"
if layout.SHOW_ASSISTANT_KEY not in st.session_state:
    # Closed by default - the assistant is an on-demand panel, not a
    # permanent column, so it shouldn't compete with the board/table for
    # width on first load.
    st.session_state[layout.SHOW_ASSISTANT_KEY] = False

layout.inject_base_css()
layout.render_top_nav(st.session_state[layout.CURRENT_PAGE_KEY])

PAGES[st.session_state[layout.CURRENT_PAGE_KEY]]()

layout.render_assistant_panel()
