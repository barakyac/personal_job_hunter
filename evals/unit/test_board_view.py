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
    )


def test_board_shows_empty_message_with_no_applied_positions():
    at = AppTest.from_function(_render_pipeline_board).run()
    assert not at.exception
    assert any("No applied positions yet" in i.value for i in at.info)


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


def test_in_a_call_button_only_shown_for_applied_stage():
    storage.save_applied(
        [
            {"company": "Acme", "title": "Backend", "status": "Applied"},
            {"company": "Globex", "title": "Backend", "status": "Interview"},
        ]
    )

    at = AppTest.from_function(_render_pipeline_board).run()
    assert not at.exception

    in_a_call_keys = [b.key for b in at.button if b.key and b.key.startswith("in_a_call_btn_")]
    assert in_a_call_keys == ["in_a_call_btn_0"]


def test_in_a_call_dialog_opens_with_existing_notes_prefilled():
    storage.save_applied(
        [{"company": "Acme", "title": "Backend", "status": "Applied", "call_notes": "Earlier note."}]
    )

    at = AppTest.from_function(_render_pipeline_board).run()
    at.button(key="in_a_call_btn_0").click().run()

    assert not at.exception
    assert at.text_area(key="call_notes_0").value == "Earlier note."
    assert at.button(key="save_call_notes_0") is not None


def test_save_call_notes_updates_the_right_record():
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

    board_view._save_call_notes(1, "Spoke with the recruiter, next step is a tech screen.")

    records = storage.load_applied()
    assert "call_notes" not in records[0]
    assert records[1]["call_notes"] == "Spoke with the recruiter, next step is a tech screen."


def test_card_displays_saved_call_notes():
    storage.save_applied(
        [{"company": "Acme", "title": "Backend", "status": "Interview", "call_notes": "Great first call."}]
    )

    at = AppTest.from_function(_render_pipeline_board).run()

    assert not at.exception
    assert any("Great first call." in m.value for m in at.markdown)


def test_call_details_dialog_embeds_the_assistant_chat():
    storage.save_applied([{"company": "Acme", "title": "Backend", "status": "Applied"}])

    at = AppTest.from_function(_render_pipeline_board).run()
    at.button(key="in_a_call_btn_0").click().run()

    assert not at.exception
    assert any("Assistant" in h.value for h in at.subheader)
    assert at.chat_input
    # No "Hide" button inside the popup - that's a main-page-only affordance.
    assert not any(b.key == "hide_assistant_btn" for b in at.button)
