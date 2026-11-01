import os
from pathlib import Path
from typing import Callable

import streamlit as st
from dotenv import set_key

from src import anthropic_client, ollama_client, openai_client, storage

# Same reload-safe override pattern as storage.py's JOB_HUNTER_DATA_DIR -
# tests point this at a throwaway file so a key saved via the UI form never
# lands in the real project .env.
ENV_PATH = Path(os.environ.get("JOB_HUNTER_ENV_FILE") or Path(__file__).resolve().parent.parent / ".env")

SYSTEM_PROMPT_TEMPLATE = """You are a helpful assistant built into this user's personal job-hunting \
dashboard. You can help with job search strategy, resume feedback, interview prep, and questions \
about their saved or applied positions - but don't limit yourself to that. Answer general questions \
on any topic the user asks, including during a live call when they need a quick answer. Be concise \
and direct.

{context}"""

SESSION_KEY = "chat_messages"
PROVIDER_SESSION_KEY = "assistant_provider"

# Each provider's "chat" entry is the module itself (not a bound function
# reference), so a monkeypatched module.chat attribute is picked up on every
# call instead of being captured once at import time.
PROVIDERS = {
    "Local (Ollama)": {
        "module": ollama_client,
        "model": ollama_client.DEFAULT_MODEL,
        "error": ollama_client.OllamaError,
        "label": f"Ollama {ollama_client.DEFAULT_MODEL}",
        "needs_key": None,
    },
    "Claude": {
        "module": anthropic_client,
        "model": anthropic_client.DEFAULT_MODEL,
        "error": anthropic_client.AnthropicError,
        "label": f"Claude ({anthropic_client.DEFAULT_MODEL})",
        "needs_key": "ANTHROPIC_API_KEY",
    },
    "ChatGPT": {
        "module": openai_client,
        "model": openai_client.DEFAULT_MODEL,
        "error": openai_client.OpenAIError,
        "label": f"ChatGPT ({openai_client.DEFAULT_MODEL})",
        "needs_key": "OPENAI_API_KEY",
    },
}


def _save_api_key(env_var: str, value: str) -> None:
    """Write env_var to the local .env (gitignored) and apply it to this
    running process immediately, so the provider works without a restart."""
    set_key(str(ENV_PATH), env_var, value)
    os.environ[env_var] = value


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

    provider_name = st.selectbox(
        "Model", options=list(PROVIDERS.keys()), key=PROVIDER_SESSION_KEY
    )
    provider = PROVIDERS[provider_name]
    st.caption(provider["label"])
    env_var = provider["needs_key"]
    if env_var and not os.environ.get(env_var):
        with st.form(key=f"api_key_form_{env_var}", border=False):
            key_value = st.text_input(
                f"{env_var}",
                type="password",
                placeholder=f"Paste your {provider_name} API key",
                key=f"api_key_input_{env_var}",
            )
            submitted = st.form_submit_button(
                f"Save {provider_name} key", key=f"api_key_submit_{env_var}"
            )
            if submitted and key_value.strip():
                _save_api_key(env_var, key_value.strip())
                st.rerun()

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
            with st.spinner(f"Thinking with {provider['label']}..."):
                try:
                    reply = provider["module"].chat(messages, model=provider["model"])
                except provider["error"] as exc:
                    reply = str(exc)
            st.write(reply)

        st.session_state[SESSION_KEY].append({"role": "assistant", "content": reply})
