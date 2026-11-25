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


def test_save_call_details_updates_the_right_record():
    # The dialog's own click-to-save round trip can't be driven through
    # AppTest: a widget interaction inside an already-open st.dialog doesn't
    # re-trigger its handler on a later .run() (AppTest doesn't simulate the
    # fragment-scoped rerun real Streamlit uses for in-dialog interactions).
    # So the save logic is tested directly as the plain function it is.
    from src import board_view

    storage.save_applied(
        [
            {"company": "Acme", "title": "Backend", "status": "Applied"},
            {"company": "Globex", "title": "Backend", "status": "Applied"},
        ]
    )

    board_view._save_call_details(1, date.today(), "", "Spoke with the recruiter, next step is a tech screen.")

    records = storage.load_applied()
    assert "call_notes" not in records[0]
    assert records[1]["call_notes"] == "Spoke with the recruiter, next step is a tech screen."


def test_save_call_details_prepends_new_entry_onto_full_history():
    # Same AppTest limitation as above - exercise the plain function the
    # single "Save" button calls directly.
    from src import board_view

    storage.save_applied(
        [{"company": "Acme", "title": "Backend", "status": "Applied", "call_notes": "### 2026-11-01\nFirst screen, went well."}]
    )

    board_view._save_call_details(
        0, date(2026, 11, 15), "Second call, got a take-home assignment.",
        "### 2026-11-01\nFirst screen, went well.",
    )

    records = storage.load_applied()
    assert records[0]["call_notes"] == (
        "### 2026-11-15\nSecond call, got a take-home assignment.\n\n"
        "### 2026-11-01\nFirst screen, went well."
    )


def test_save_call_details_on_a_record_with_no_prior_notes():
    from src import board_view

    storage.save_applied([{"company": "Acme", "title": "Backend", "status": "Applied"}])

    board_view._save_call_details(0, date(2026, 11, 15), "Quick intro call.", "")

    records = storage.load_applied()
    assert records[0]["call_notes"] == "### 2026-11-15\nQuick intro call."


def test_save_call_details_prepends_onto_a_hand_edit_not_yet_saved_to_disk():
    # Regression guard: the combined Save button must use the Full history
    # box's current (possibly just hand-edited) text as the base for the new
    # entry, not whatever's still on disk - otherwise typing a correction
    # into Full history and logging a new call in the same visit would
    # silently discard that correction.
    from src import board_view

    storage.save_applied(
        [{"company": "Acme", "title": "Backend", "status": "Applied", "call_notes": "### 2026-11-01\nFirst screen, went well."}]
    )

    board_view._save_call_details(
        0, date(2026, 11, 15), "Second call, got a take-home assignment.",
        "### 2026-11-01\nFirst screen, went well (hand-edited correction).",
    )

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
    # the new text into that session_state key itself, logging a call
    # during an already-open dialog would leave the box showing the
    # pre-call text - and a later click would overwrite the just-logged
    # entry with that stale text.
    storage.save_applied(
        [{"company": "Acme", "title": "Backend", "status": "Interview", "call_notes": "### 2026-11-01\nFirst screen, went well."}]
    )

    def _dialog_with_a_save_flag():
        # Mirrors the real script order inside _call_notes_dialog: the
        # "Save" button's handler (_save_call_details) runs, using the Full
        # history text_area's current session-state value as the base, then
        # control reaches that same text_area further down in the same
        # script - exactly what a real rerun after that button click does,
        # just without needing to click through AppTest's dialog (which
        # doesn't replay a dialog's own button handlers - see the note on
        # test_save_call_details_updates_the_right_record above).
        import streamlit as st
        from datetime import date

        from src import board_view

        if st.session_state.get("do_save"):
            current_full_history = st.session_state.get(
                "call_notes_0", "### 2026-11-01\nFirst screen, went well."
            )
            board_view._save_call_details(
                0, date(2026, 11, 15), "Second call, got a take-home assignment.", current_full_history,
            )
        board_view._call_notes_dialog(0)

    at = AppTest.from_function(_dialog_with_a_save_flag).run()
    assert at.text_area(key="call_notes_0").value == "### 2026-11-01\nFirst screen, went well."

    at.session_state["do_save"] = True
    at.run()

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
