from datetime import date

from streamlit.testing.v1 import AppTest

from src import storage


def _render_pipeline_board():
    from src import board_view, storage

    board_view.render(
        stages=storage.PIPELINE_STATUSES,
        title="Applied Positions",
        caption="Active applications grouped by stage. Change a card's stage to move it.",
    )


def _render_outcome_board():
    from src import board_view, storage

    board_view.render(
        stages=storage.OUTCOME_STATUSES,
        title="Final Outcome",
        caption="Applications that have reached a final outcome.",
        empty_message="No applications have reached a final outcome yet.",
    )


def test_board_shows_empty_message_with_no_applied_positions():
    at = AppTest.from_function(_render_pipeline_board).run()
    assert not at.exception
    assert any("No applied positions yet" in i.value for i in at.info)


def test_outcome_board_shows_empty_message_when_nothing_has_reached_a_final_outcome():
    # Regression guard: the empty-state check used to test `not applied`
    # globally, so a pipeline-stage record (e.g. "Applied") suppressed the
    # Final Outcome board's empty message even though no record was
    # actually in an outcome stage.
    storage.save_applied([{"company": "Acme", "title": "Backend", "status": "Applied"}])

    at = AppTest.from_function(_render_outcome_board).run()

    assert not at.exception
    assert any("No applications have reached a final outcome yet." in i.value for i in at.info)


def test_outcome_board_hides_empty_message_once_something_reaches_an_outcome():
    storage.save_applied([{"company": "Acme", "title": "Backend", "status": "Offer"}])

    at = AppTest.from_function(_render_outcome_board).run()

    assert not at.exception
    assert not any("No applications have reached a final outcome yet." in i.value for i in at.info)


def test_moving_card_to_rejected_captures_previous_stage():
    storage.save_applied([{"company": "Acme", "title": "Backend", "status": "First Call"}])

    at = AppTest.from_function(_render_pipeline_board).run()
    at.selectbox(key="board_stage_0").select("Rejected").run()

    records = storage.load_applied()
    assert records[0]["status"] == "Rejected"
    assert records[0]["rejected_from_stage"] == "First Call"


def test_outcome_board_displays_rejected_from_stage():
    storage.save_applied(
        [{"company": "Acme", "title": "Backend", "status": "Rejected", "rejected_from_stage": "Interview"}]
    )

    at = AppTest.from_function(_render_outcome_board).run()

    assert not at.exception
    assert any("Rejected from: Interview" in c.value for c in at.caption)


def test_moving_card_out_of_rejected_clears_rejected_from_stage():
    storage.save_applied(
        [{"company": "Acme", "title": "Backend", "status": "Rejected", "rejected_from_stage": "Interview"}]
    )

    at = AppTest.from_function(_render_outcome_board).run()
    at.selectbox(key="board_stage_0").select("Offer").run()

    records = storage.load_applied()
    assert records[0]["status"] == "Offer"
    assert "rejected_from_stage" not in records[0]


def test_in_a_call_button_shown_for_every_pipeline_stage():
    storage.save_applied(
        [
            {"company": "Acme", "title": "Backend", "status": "Applied"},
            {"company": "Globex", "title": "Backend", "status": "Interview"},
        ]
    )

    at = AppTest.from_function(_render_pipeline_board).run()
    assert not at.exception

    in_a_call_keys = {b.key for b in at.button if b.key and b.key.startswith("in_a_call_btn_")}
    assert in_a_call_keys == {"in_a_call_btn_0", "in_a_call_btn_1"}


def test_in_a_call_dialog_opens_with_existing_notes_prefilled():
    storage.save_applied(
        [{"company": "Acme", "title": "Backend", "status": "Applied", "call_notes": "Earlier note."}]
    )

    at = AppTest.from_function(_render_pipeline_board).run()
    at.button(key="in_a_call_btn_0").click().run()

    assert not at.exception
    assert at.text_area(key="call_notes_0").value == "Earlier note."
    assert at.button(key="save_call_details_0") is not None


def _render_call_notes_editor(index: int = 0):
    from src import board_view

    board_view._call_notes_editor(index)


def test_save_call_details_updates_the_right_record():
    # Regression test: _save_call_details used to be called directly from
    # inside the Save button's own `if st.button(...)` block, writing to
    # session_state keys that the text_area/button above it had already
    # instantiated this same run - Streamlit raises
    # StreamlitWidgetAlreadyInstantiatedError for that. Driving the real
    # button (now wired as its on_click callback) through AppTest is what
    # actually exercises that failure mode, unlike calling the save
    # function directly as a plain function.
    storage.save_applied(
        [
            {"company": "Acme", "title": "Backend", "status": "Applied"},
            {"company": "Globex", "title": "Backend", "status": "Applied",
             "call_notes": "Spoke with the recruiter, next step is a tech screen."},
        ]
    )

    at = AppTest.from_function(_render_call_notes_editor, kwargs={"index": 1}).run()
    at = at.button(key="save_call_details_1").click().run()

    assert not at.exception
    records = storage.load_applied()
    assert "call_notes" not in records[0]
    assert records[1]["call_notes"] == "Spoke with the recruiter, next step is a tech screen."


def test_save_call_details_shows_an_error_when_saving_fails(monkeypatch):
    # Confirms a save failure surfaces a visible error (rather than just
    # silently discarding the user's typed note) and leaves "What happened"
    # untouched so nothing typed is lost. Does NOT guard the specific bug
    # fixed by stashing the message in session_state instead of calling
    # st.error() directly from inside the on_click callback: AppTest doesn't
    # model Streamlit's in-fragment-callback render-queue restriction, so
    # this test passes identically whether or not that fix is in place -
    # that part can only be confirmed by hand in a running app.
    storage.save_applied([{"company": "Acme", "title": "Backend", "status": "Applied"}])

    def fail_to_save(records):
        raise OSError("disk full")

    monkeypatch.setattr(storage, "save_applied", fail_to_save)

    at = AppTest.from_function(_render_call_notes_editor).run()
    at.text_area(key="new_call_notes_0").set_value("Had a great call today.")
    at = at.button(key="save_call_details_0").click().run()

    assert not at.exception
    assert any("disk full" in e.value for e in at.error)
    assert at.text_area(key="new_call_notes_0").value == "Had a great call today."


def test_save_call_details_prepends_new_entry_onto_full_history():
    storage.save_applied(
        [{"company": "Acme", "title": "Backend", "status": "Applied", "call_notes": "### 2026-11-01\nFirst screen, went well."}]
    )

    at = AppTest.from_function(_render_call_notes_editor).run()
    at.date_input(key="new_call_date_0").set_value(date(2026, 11, 15))
    at.text_area(key="new_call_notes_0").set_value("Second call, got a take-home assignment.")
    at = at.button(key="save_call_details_0").click().run()

    assert not at.exception
    records = storage.load_applied()
    assert records[0]["call_notes"] == (
        "### 2026-11-15\nSecond call, got a take-home assignment.\n\n"
        "### 2026-11-01\nFirst screen, went well."
    )


def test_save_call_details_on_a_record_with_no_prior_notes():
    storage.save_applied([{"company": "Acme", "title": "Backend", "status": "Applied"}])

    at = AppTest.from_function(_render_call_notes_editor).run()
    at.date_input(key="new_call_date_0").set_value(date(2026, 11, 15))
    at.text_area(key="new_call_notes_0").set_value("Quick intro call.")
    at = at.button(key="save_call_details_0").click().run()

    assert not at.exception
    records = storage.load_applied()
    assert records[0]["call_notes"] == "### 2026-11-15\nQuick intro call."


def test_save_call_details_prepends_onto_a_hand_edit_not_yet_saved_to_disk():
    # Regression guard: the combined Save button must use the Full history
    # box's current (possibly just hand-edited) text as the base for the new
    # entry, not whatever's still on disk - otherwise typing a correction
    # into Full history and logging a new call in the same visit would
    # silently discard that correction.
    storage.save_applied(
        [{"company": "Acme", "title": "Backend", "status": "Applied", "call_notes": "### 2026-11-01\nFirst screen, went well."}]
    )

    at = AppTest.from_function(_render_call_notes_editor).run()
    at.text_area(key="call_notes_0").set_value("### 2026-11-01\nFirst screen, went well (hand-edited correction).")
    at.date_input(key="new_call_date_0").set_value(date(2026, 11, 15))
    at.text_area(key="new_call_notes_0").set_value("Second call, got a take-home assignment.")
    at = at.button(key="save_call_details_0").click().run()

    assert not at.exception
    records = storage.load_applied()
    assert records[0]["call_notes"] == (
        "### 2026-11-15\nSecond call, got a take-home assignment.\n\n"
        "### 2026-11-01\nFirst screen, went well (hand-edited correction)."
    )


def test_save_call_details_syncs_the_open_dialogs_full_history_box():
    # Regression test: the Full history text_area's session_state key
    # (call_notes_0) only picks up `value=record.get("call_notes")` the
    # first time it's rendered in a session - once the dialog has been
    # opened once, Streamlit ignores that `value=` on every later rerun and
    # keeps whatever the box last showed. Without _save_call_details pushing
    # the new text into that session_state key itself (from its on_click
    # callback, which runs before this same run's text_area is
    # instantiated), the box would show the pre-call text until a separate
    # rerun, and a later click would overwrite the just-logged entry with
    # that stale text.
    storage.save_applied(
        [{"company": "Acme", "title": "Backend", "status": "Interview", "call_notes": "### 2026-11-01\nFirst screen, went well."}]
    )

    at = AppTest.from_function(_render_call_notes_editor).run()
    at.date_input(key="new_call_date_0").set_value(date(2026, 11, 15))
    at.text_area(key="new_call_notes_0").set_value("Second call, got a take-home assignment.")
    at = at.button(key="save_call_details_0").click().run()

    assert not at.exception
    assert at.text_area(key="call_notes_0").value == (
        "### 2026-11-15\nSecond call, got a take-home assignment.\n\n"
        "### 2026-11-01\nFirst screen, went well."
    )
    assert at.text_area(key="new_call_notes_0").value == ""

    records = storage.load_applied()
    assert records[0]["call_notes"] == (
        "### 2026-11-15\nSecond call, got a take-home assignment.\n\n"
        "### 2026-11-01\nFirst screen, went well."
    )
    # The box the user is looking at must reflect the entry just saved, not
    # the stale pre-save text - otherwise a later click would overwrite the
    # file with that stale text.
    assert at.text_area(key="call_notes_0").value == records[0]["call_notes"]
    assert at.text_area(key="new_call_notes_0").value == ""


def test_card_shows_call_notes_button_that_opens_the_dialog():
    storage.save_applied(
        [{"company": "Acme", "title": "Backend", "status": "Interview", "call_notes": "Great first call."}]
    )

    at = AppTest.from_function(_render_pipeline_board).run()
    assert not at.exception
    assert at.button(key="view_call_notes_btn_0") is not None

    at.button(key="view_call_notes_btn_0").click().run()

    assert not at.exception
    assert at.text_area(key="call_notes_0").value == "Great first call."


def test_hide_empty_stages_toggle_shown_only_when_a_stage_is_empty():
    storage.save_applied([{"company": "Acme", "title": "Backend", "status": "Applied"}])

    at = AppTest.from_function(_render_pipeline_board).run()

    assert not at.exception
    assert any(t.key == "hide_empty_stages_Applied Positions" for t in at.toggle)


def test_hide_empty_stages_toggle_removes_empty_columns():
    storage.save_applied([{"company": "Acme", "title": "Backend", "status": "Applied"}])

    at = AppTest.from_function(_render_pipeline_board).run()
    at = at.toggle(key="hide_empty_stages_Applied Positions").set_value(True).run()

    assert not at.exception
    # Only the "Applied" column (which has a record) should still show its
    # card - the other four pipeline stages are empty and now hidden.
    assert any(b.key == "details_btn_0" for b in at.button)


def test_details_button_opens_dialog_with_editable_fields():
    storage.save_applied(
        [{"company": "Acme", "title": "Backend", "status": "Applied", "notes": "Referred by a friend."}]
    )

    at = AppTest.from_function(_render_pipeline_board).run()
    at.button(key="details_btn_0").click().run()

    assert not at.exception
    assert at.text_area(key="details_notes_0").value == "Referred by a friend."
    assert at.button(key="save_details_0") is not None


def test_call_details_dialog_embeds_the_assistant_chat():
    storage.save_applied([{"company": "Acme", "title": "Backend", "status": "Applied"}])

    at = AppTest.from_function(_render_pipeline_board).run()
    at.button(key="in_a_call_btn_0").click().run()

    assert not at.exception
    assert any("Assistant" in h.value for h in at.subheader)
    assert at.chat_input
    # No "Hide" button inside the popup - that's a main-page-only affordance.
    assert not any(b.key == "hide_assistant_btn" for b in at.button)
