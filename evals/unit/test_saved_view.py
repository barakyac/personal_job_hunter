from streamlit.testing.v1 import AppTest

from src import job_extract, storage


def _render_saved():
    from src import saved_view

    saved_view.render()


def test_paste_popover_creates_saved_position(monkeypatch):
    monkeypatch.setattr(
        job_extract,
        "extract_fields",
        lambda description: {
            "company": "Acme",
            "title": "Backend Engineer",
            "location": "Remote",
            "salary": "100k",
        },
    )

    at = AppTest.from_function(_render_saved).run()
    assert not at.exception

    at.text_area(key="paste_description_text").set_value("We are Acme, hiring a Backend Engineer.")
    at.button(key="create_from_paste_btn").click().run()

    assert not at.exception
    records = storage.load_saved()
    assert len(records) == 1
    assert records[0]["company"] == "Acme"
    assert records[0]["title"] == "Backend Engineer"
    assert records[0]["location"] == "Remote"
    assert records[0]["salary"] == "100k"
    assert records[0]["description"] == "We are Acme, hiring a Backend Engineer."
    assert records[0]["link"] == ""


def test_paste_popover_rejects_empty_description():
    at = AppTest.from_function(_render_saved).run()

    at.button(key="create_from_paste_btn").click().run()

    assert not at.exception
    assert storage.load_saved() == []
    assert any("Paste a job description first" in e.value for e in at.error)


def test_paste_popover_surfaces_ollama_error(monkeypatch):
    from src import ollama_client

    def raising_extract(description):
        raise ollama_client.OllamaError("Could not reach Ollama")

    monkeypatch.setattr(job_extract, "extract_fields", raising_extract)

    at = AppTest.from_function(_render_saved).run()
    at.text_area(key="paste_description_text").set_value("Some posting")
    at.button(key="create_from_paste_btn").click().run()

    assert not at.exception
    assert storage.load_saved() == []
    assert any("Could not reach Ollama" in e.value for e in at.error)


def test_move_to_applied_positions_transfers_record():
    storage.save_saved([{"company": "Acme", "title": "Backend", "link": "", "date_saved": "2026-01-01"}])

    at = AppTest.from_function(_render_saved).run()
    assert not at.exception

    move_button = next(b for b in at.button if b.label == "Move to Applied Positions")
    move_button.click().run()

    assert not at.exception
    assert storage.load_saved() == []
    applied = storage.load_applied()
    assert len(applied) == 1
    assert applied[0]["company"] == "Acme"
    assert applied[0]["status"] == "Applied"
    assert "date_applied" in applied[0]
