from typing import Callable

import streamlit as st

from src import ollama_client, storage

SYSTEM_PROMPT_TEMPLATE = """You are a helpful assistant built into this user's personal job-hunting \
dashboard. Help with job search strategy, resume feedback, interview prep, and questions about their \
saved or applied positions. Be concise and direct.

{context}"""

SESSION_KEY = "chat_messages"


def _build_context() -> str:
    resume = storage.load_resume()
    personal_context = storage.load_personal_context()
    saved = storage.load_saved()
    applied = storage.load_applied()

    parts = []
    if resume.strip():
        parts.append(f"RESUME:\n{resume}")
    if personal_context.strip():
        parts.append(f"ADDITIONAL CONTEXT:\n{personal_context}")
    if saved:
        lines = [f"- {r.get('company') or '?'} - {r.get('title', '')}" for r in saved]
        parts.append("SAVED POSITIONS:\n" + "\n".join(lines))
    if applied:
        lines = [
            f"- {r.get('company') or '?'} - {r.get('title', '')} ({r.get('status') or 'Applied'})"
            for r in applied
        ]
        parts.append("APPLIED POSITIONS:\n" + "\n".join(lines))
    return "\n\n".join(parts)


def render(on_hide: Callable[[], None] | None = None) -> None:
    if on_hide:
        header_col, hide_col = st.columns([4, 1])
        with header_col:
            st.subheader("Assistant")
        with hide_col:
            st.button("Hide", key="hide_assistant_btn", on_click=on_hide)
    else:
        st.subheader("Assistant")
    st.caption(f"Ollama {ollama_client.DEFAULT_MODEL}")

    if SESSION_KEY not in st.session_state:
        st.session_state[SESSION_KEY] = []

    history = st.container(height=500)
    for msg in st.session_state[SESSION_KEY]:
        with history.chat_message(msg["role"]):
            st.write(msg["content"])

    prompt = st.chat_input("Ask about your job search...")
    if prompt:
        st.session_state[SESSION_KEY].append({"role": "user", "content": prompt})
        with history.chat_message("user"):
            st.write(prompt)

        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(context=_build_context())
        messages = [{"role": "system", "content": system_prompt}, *st.session_state[SESSION_KEY]]

        with history.chat_message("assistant"):
            with st.spinner(f"Thinking with Ollama {ollama_client.DEFAULT_MODEL}..."):
                try:
                    reply = ollama_client.chat(messages)
                except ollama_client.OllamaError as exc:
                    reply = f"Could not reach Ollama: {exc}"
            st.write(reply)

        st.session_state[SESSION_KEY].append({"role": "assistant", "content": reply})
