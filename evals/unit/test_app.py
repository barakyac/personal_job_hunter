from pathlib import Path

from streamlit.testing.v1 import AppTest

APP_PATH = Path(__file__).resolve().parent.parent.parent / "app.py"


def test_assistant_visible_by_default():
    at = AppTest.from_file(str(APP_PATH)).run()
    assert not at.exception
    assert at.chat_input
    assert not any(b.key == "show_assistant_btn" for b in at.button)


def test_hide_assistant_removes_chat_and_shows_restore_button():
    at = AppTest.from_file(str(APP_PATH)).run()
    at.button(key="hide_assistant_btn").click().run()

    assert not at.exception
    assert not at.chat_input
    assert any(b.key == "show_assistant_btn" for b in at.button)


def test_show_assistant_button_restores_chat():
    at = AppTest.from_file(str(APP_PATH)).run()
    at.button(key="hide_assistant_btn").click().run()
    at.button(key="show_assistant_btn").click().run()

    assert not at.exception
    assert at.chat_input
    assert not any(b.key == "show_assistant_btn" for b in at.button)
