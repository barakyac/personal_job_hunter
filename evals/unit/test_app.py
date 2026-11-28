from pathlib import Path

from streamlit.testing.v1 import AppTest

APP_PATH = Path(__file__).resolve().parent.parent.parent / "app.py"

NAV_PAGES = ["Applications", "Matching Jobs", "Saved Jobs", "Mail Inbox", "Profile"]


def test_assistant_hidden_by_default():
    at = AppTest.from_file(str(APP_PATH)).run()
    assert not at.exception
    assert not at.chat_input
    assert any(b.key == "nav_ask_assistant" for b in at.button)


def test_ask_assistant_button_opens_the_panel():
    at = AppTest.from_file(str(APP_PATH)).run()
    at.button(key="nav_ask_assistant").click().run()

    assert not at.exception
    assert at.chat_input


def test_hide_button_inside_panel_closes_it():
    at = AppTest.from_file(str(APP_PATH)).run()
    at.button(key="nav_ask_assistant").click().run()
    at.button(key="hide_assistant_btn").click().run()

    assert not at.exception
    assert not at.chat_input


def test_assistant_state_survives_navigating_to_another_page():
    at = AppTest.from_file(str(APP_PATH)).run()
    at.button(key="nav_ask_assistant").click().run()
    at = at.button(key="nav_Saved Jobs").click().run()

    assert not at.exception
    assert at.chat_input


def test_every_nav_page_renders_without_error():
    # Regression guard: a page present in PAGES but broken (or a page
    # that's supposed to be wired in but silently isn't) should fail here.
    for page in NAV_PAGES:
        at = AppTest.from_file(str(APP_PATH)).run()
        at = at.button(key=f"nav_{page}").click().run()
        assert not at.exception, f"page {page!r} raised: {at.exception}"


def test_settings_button_opens_without_error():
    at = AppTest.from_file(str(APP_PATH)).run()
    at.button(key="nav_settings_btn").click().run()
    assert not at.exception
