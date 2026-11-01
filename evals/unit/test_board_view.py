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
