from streamlit.testing.v1 import AppTest


def _render_nav():
    import streamlit as st

    from src import layout

    if layout.CURRENT_PAGE_KEY not in st.session_state:
        st.session_state[layout.CURRENT_PAGE_KEY] = "Applications"
    layout.inject_base_css()
    layout.render_top_nav(st.session_state[layout.CURRENT_PAGE_KEY])


def test_nav_renders_all_pages_plus_assistant_and_settings():
    at = AppTest.from_function(_render_nav).run()

    assert not at.exception
    for page in ["Applications", "Saved Jobs", "Mail Inbox", "Profile"]:
        assert any(b.key == f"nav_{page}" for b in at.button)
    assert any(b.key == "nav_ask_assistant" for b in at.button)
    assert any(b.key == "nav_settings_btn" for b in at.button)


def test_current_page_button_is_primary():
    at = AppTest.from_function(_render_nav).run()

    applications_btn = next(b for b in at.button if b.key == "nav_Applications")
    saved_btn = next(b for b in at.button if b.key == "nav_Saved Jobs")
    assert applications_btn.proto.type == "primary"
    assert saved_btn.proto.type == "secondary"


def test_settings_dialog_opens_without_error():
    at = AppTest.from_function(_render_nav).run()
    at.button(key="nav_settings_btn").click().run()

    assert not at.exception
    assert any("Assistant providers" in m.value for m in at.markdown)
