from streamlit.testing.v1 import AppTest

from src import storage


def _render_applications():
    from src import applications_view

    applications_view.render()


def test_renders_board_by_default_with_no_applications():
    at = AppTest.from_function(_render_applications).run()

    assert not at.exception
    assert any("Applications" in m.value for m in at.markdown)
    assert any("No applied positions yet" in i.value for i in at.info)


def test_add_application_button_opens_dialog_without_creating_anything():
    at = AppTest.from_function(_render_applications).run()
    at.button(key="add_application_btn").click().run()

    assert not at.exception
    assert storage.load_applied() == []
    assert at.text_input(key="add_app_company") is not None
    assert at.button(key="confirm_add_application_btn") is not None


def test_create_application_writes_the_record():
    # The dialog's own click-to-save round trip can't be driven through
    # AppTest (same documented limitation as board_view's call-notes
    # dialog), so the write path is tested as the plain function it is.
    from datetime import date

    from src import applications_view

    applications_view._create_application("Acme", "Backend", "", "Remote", date(2026, 1, 2), "Applied")

    applied = storage.load_applied()
    assert len(applied) == 1
    assert applied[0]["company"] == "Acme"
    assert applied[0]["status"] == "Applied"
    assert applied[0]["date_applied"] == "2026-01-02"


def test_table_view_shows_the_bulk_editor():
    storage.save_applied([{"company": "Acme", "title": "Backend", "status": "Applied"}])

    at = AppTest.from_function(_render_applications).run()
    at = at.segmented_control(key="applications_view_mode").set_value("Table").run()

    assert not at.exception
    assert any(b.key == "save_applied_btn" for b in at.button)


def test_completed_tab_shows_outcome_filters_with_counts():
    storage.save_applied([
        {"company": "Acme", "title": "Backend", "status": "Offer"},
        {"company": "Globex", "title": "Frontend", "status": "Rejected", "rejected_from_stage": "Interview"},
        {"company": "Initech", "title": "SRE", "status": "Applied"},
    ])

    at = AppTest.from_function(_render_applications).run()
    at = at.segmented_control(key="applications_status_tab").set_value("Completed").run()

    assert not at.exception
    assert any("All (2)" in c.value and "Offers (1)" in c.value for c in at.caption)
    assert any("Acme" in m.value for m in at.markdown)
    assert any("Globex" in m.value for m in at.markdown)
    assert not any("Initech" in m.value for m in at.markdown)
    assert any("From: Interview" in c.value for c in at.caption)


def test_completed_tab_offers_filter_narrows_the_list():
    storage.save_applied([
        {"company": "Acme", "title": "Backend", "status": "Offer"},
        {"company": "Globex", "title": "Frontend", "status": "Rejected"},
    ])

    at = AppTest.from_function(_render_applications).run()
    at = at.segmented_control(key="applications_status_tab").set_value("Completed").run()
    at = at.segmented_control(key="completed_outcome_filter").set_value("Offers").run()

    assert not at.exception
    assert any("Acme" in m.value for m in at.markdown)
    assert not any("Globex" in m.value for m in at.markdown)
