import os

import pytest
from streamlit.testing.v1 import AppTest

from src import anthropic_client, ollama_client, openai_client, storage


def _render_chat():
    from src import chat_view

    chat_view.render()


def test_build_context_includes_resume_and_positions():
    from src import chat_view

    storage.save_resume("Experienced backend engineer.")
    storage.save_saved([{"company": "Acme", "title": "Backend Engineer"}])
    storage.save_applied([{"company": "Globex", "title": "SRE", "status": "Interview"}])

    context = chat_view._build_context()

    assert "Experienced backend engineer." in context
    assert "Acme - Backend Engineer" in context
    assert "Globex - SRE (Interview)" in context


def test_build_context_empty_when_nothing_saved():
    from src import chat_view

    assert chat_view._build_context() == ""


def test_chat_renders_without_crashing():
    at = AppTest.from_function(_render_chat).run()
    assert not at.exception
    assert at.chat_input


def test_sending_a_message_calls_ollama_and_renders_reply(monkeypatch):
    captured = {}

    def fake_chat(messages, model=ollama_client.DEFAULT_MODEL, timeout=300):
        captured["messages"] = messages
        return "Here's some advice for your job search."

    monkeypatch.setattr(ollama_client, "chat", fake_chat)

    at = AppTest.from_function(_render_chat).run()
    at.chat_input[0].set_value("Any tips for my next interview?").run()

    assert not at.exception
    assert any("Any tips for my next interview?" in m.value for m in at.markdown)
    assert any("Here's some advice for your job search." in m.value for m in at.markdown)

    # system prompt + the user's message were sent
    assert captured["messages"][0]["role"] == "system"
    assert captured["messages"][-1] == {"role": "user", "content": "Any tips for my next interview?"}


def test_chat_history_persists_across_reruns(monkeypatch):
    monkeypatch.setattr(ollama_client, "chat", lambda messages, model=ollama_client.DEFAULT_MODEL, timeout=300: "Reply.")

    at = AppTest.from_function(_render_chat).run()
    at.chat_input[0].set_value("First question").run()
    at.chat_input[0].set_value("Second question").run()

    assert not at.exception
    assert len(at.session_state["chat_messages"]) == 4


def test_ollama_error_is_shown_instead_of_crashing(monkeypatch):
    def raising_chat(messages, model=ollama_client.DEFAULT_MODEL, timeout=300):
        raise ollama_client.OllamaError("Could not reach Ollama at http://localhost:11434/api/chat")

    monkeypatch.setattr(ollama_client, "chat", raising_chat)

    at = AppTest.from_function(_render_chat).run()
    at.chat_input[0].set_value("Hello").run()

    assert not at.exception
    assert any("Could not reach Ollama" in m.value for m in at.markdown)


def test_no_hide_button_without_on_hide():
    at = AppTest.from_function(_render_chat).run()
    assert not any(b.key == "hide_assistant_btn" for b in at.button)


def test_hide_button_shown_and_invokes_callback_when_on_hide_provided():
    def _render():
        import streamlit as st

        from src import chat_view

        if "hidden" not in st.session_state:
            st.session_state.hidden = False

        def _hide():
            st.session_state.hidden = True

        chat_view.render(on_hide=_hide)

    at = AppTest.from_function(_render).run()
    assert any(b.key == "hide_assistant_btn" for b in at.button)

    at.button(key="hide_assistant_btn").click().run()

    assert not at.exception
    assert at.session_state["hidden"] is True


def test_defaults_to_local_ollama_provider():
    at = AppTest.from_function(_render_chat).run()
    assert not at.exception
    assert at.selectbox(key="assistant_provider").value == "Local (Ollama)"


def test_shows_api_key_form_when_claude_selected_without_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    at = AppTest.from_function(_render_chat).run()
    at.selectbox(key="assistant_provider").select("Claude").run()

    assert not at.exception
    assert at.text_input(key="api_key_input_ANTHROPIC_API_KEY") is not None
    assert at.button(key="api_key_submit_ANTHROPIC_API_KEY") is not None


def test_shows_api_key_form_when_chatgpt_selected_without_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    at = AppTest.from_function(_render_chat).run()
    at.selectbox(key="assistant_provider").select("ChatGPT").run()

    assert not at.exception
    assert at.text_input(key="api_key_input_OPENAI_API_KEY") is not None


def test_no_api_key_form_once_key_is_set(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    at = AppTest.from_function(_render_chat).run()
    at.selectbox(key="assistant_provider").select("Claude").run()

    assert not at.exception
    with pytest.raises(KeyError):
        at.text_input(key="api_key_input_ANTHROPIC_API_KEY")


def test_submitting_api_key_form_saves_to_env_file_and_current_process(monkeypatch):
    from src import chat_view

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    at = AppTest.from_function(_render_chat).run()
    at.selectbox(key="assistant_provider").select("Claude").run()
    at.text_input(key="api_key_input_ANTHROPIC_API_KEY").set_value("sk-ant-test-123")
    at.button(key="api_key_submit_ANTHROPIC_API_KEY").click().run()

    assert not at.exception
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-test-123"
    assert chat_view.ENV_PATH.exists()
    assert "sk-ant-test-123" in chat_view.ENV_PATH.read_text()
    # the form disappears once the key is set
    with pytest.raises(KeyError):
        at.text_input(key="api_key_input_ANTHROPIC_API_KEY")


def test_sending_a_message_routes_to_claude_when_selected(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    captured = {}

    def fake_chat(messages, model=anthropic_client.DEFAULT_MODEL, timeout=300):
        captured["messages"] = messages
        captured["model"] = model
        return "Claude's answer."

    monkeypatch.setattr(anthropic_client, "chat", fake_chat)

    at = AppTest.from_function(_render_chat).run()
    at.selectbox(key="assistant_provider").select("Claude").run()
    at.chat_input[0].set_value("Any tips?").run()

    assert not at.exception
    assert any("Claude's answer." in m.value for m in at.markdown)
    assert captured["model"] == anthropic_client.DEFAULT_MODEL
    assert captured["messages"][-1] == {"role": "user", "content": "Any tips?"}


def test_sending_a_message_routes_to_chatgpt_when_selected(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    captured = {}

    def fake_chat(messages, model=openai_client.DEFAULT_MODEL, timeout=300):
        captured["messages"] = messages
        captured["model"] = model
        return "ChatGPT's answer."

    monkeypatch.setattr(openai_client, "chat", fake_chat)

    at = AppTest.from_function(_render_chat).run()
    at.selectbox(key="assistant_provider").select("ChatGPT").run()
    at.chat_input[0].set_value("Any tips?").run()

    assert not at.exception
    assert any("ChatGPT's answer." in m.value for m in at.markdown)
    assert captured["model"] == openai_client.DEFAULT_MODEL


def test_claude_error_is_shown_instead_of_crashing(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    def raising_chat(messages, model=anthropic_client.DEFAULT_MODEL, timeout=300):
        raise anthropic_client.AnthropicError("Claude rejected the API key - check ANTHROPIC_API_KEY.")

    monkeypatch.setattr(anthropic_client, "chat", raising_chat)

    at = AppTest.from_function(_render_chat).run()
    at.selectbox(key="assistant_provider").select("Claude").run()
    at.chat_input[0].set_value("Hello").run()

    assert not at.exception
    assert any("Claude rejected the API key" in m.value for m in at.markdown)
