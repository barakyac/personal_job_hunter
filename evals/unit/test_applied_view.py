from streamlit.testing.v1 import AppTest

from src import storage


def _render_applied():
    from src import applied_view

    applied_view.render()


def test_render_does_not_crash_when_fit_fields_are_entirely_missing():
    # Regression: this is the exact shape that crashed Streamlit's data_editor
    # before the to_dataframe dtype fix (a record with no fit_score/fit_notes
    # key at all, so the whole column came back NaN/float64).
    storage.save_applied([{"company": "Acme", "title": "Backend", "status": "Applied"}])

    at = AppTest.from_function(_render_applied).run()

    assert not at.exception


def test_save_changes_roundtrips_existing_records_unchanged():
    storage.save_applied(
        [{"company": "Acme", "title": "Backend", "status": "Applied", "date_applied": "2026-01-01"}]
    )

    at = AppTest.from_function(_render_applied).run()
    at.button(key="save_applied_btn").click().run()

    assert not at.exception
    records = storage.load_applied()
    assert len(records) == 1
    assert records[0]["company"] == "Acme"
    assert records[0]["status"] == "Applied"
