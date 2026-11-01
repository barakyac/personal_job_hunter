from streamlit.testing.v1 import AppTest

from src import ollama_client, storage


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
