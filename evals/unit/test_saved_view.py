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

    at.text_input(key="paste_description_link_0").set_value("https://acme.example/jobs/1")
    at.text_area(key="paste_description_text_0").set_value("We are Acme, hiring a Backend Engineer.")
    at.button(key="create_from_paste_btn").click().run()

    assert not at.exception
    records = storage.load_saved()
    assert len(records) == 1
    assert records[0]["company"] == "Acme"
    assert records[0]["title"] == "Backend Engineer"
    assert records[0]["location"] == "Remote"
    assert records[0]["salary"] == "100k"
    assert records[0]["description"] == "We are Acme, hiring a Backend Engineer."
    assert records[0]["link"] == "https://acme.example/jobs/1"
    assert records[0]["posting_status"] == storage.POSTING_STATUS_OPEN


def test_paste_popover_clears_its_fields_after_a_successful_create(monkeypatch):
    monkeypatch.setattr(
        job_extract,
        "extract_fields",
        lambda description: {"company": "Acme", "title": "Backend", "location": "", "salary": ""},
    )

    at = AppTest.from_function(_render_saved).run()
    at.text_input(key="paste_description_link_0").set_value("https://acme.example/jobs/1")
    at.text_area(key="paste_description_text_0").set_value("We are Acme, hiring.")
    at.button(key="create_from_paste_btn").click().run()

    assert not at.exception
    # A fresh (unversioned-forward) widget should render empty, not keep the
    # just-submitted link/description around for the next paste.
    assert at.text_input(key="paste_description_link_1").value == ""
    assert at.text_area(key="paste_description_text_1").value == ""


def test_paste_popover_rejects_missing_link():
    at = AppTest.from_function(_render_saved).run()

    at.text_area(key="paste_description_text_0").set_value("We are Acme.")
    at.button(key="create_from_paste_btn").click().run()

    assert not at.exception
    assert storage.load_saved() == []
    assert any("Add the job link first" in e.value for e in at.error)


def test_paste_popover_rejects_empty_description():
    at = AppTest.from_function(_render_saved).run()

    at.text_input(key="paste_description_link_0").set_value("https://acme.example/jobs/1")
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
    at.text_input(key="paste_description_link_0").set_value("https://acme.example/jobs/1")
    at.text_area(key="paste_description_text_0").set_value("Some posting")
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


def test_move_to_applied_positions_drops_posting_status():
    # "Open/Closed for applications" describes the job posting, not this
    # user's own pipeline stage (APPLIED_COLUMNS' separate "status") - it
    # has no meaning once the position has moved to Applied.
    storage.save_saved([{
        "company": "Acme", "title": "Backend", "link": "",
        "posting_status": storage.POSTING_STATUS_OPEN, "date_saved": "2026-01-01",
    }])

    at = AppTest.from_function(_render_saved).run()
    move_button = next(b for b in at.button if b.label == "Move to Applied Positions")
    move_button.click().run()

    assert not at.exception
    applied = storage.load_applied()
    assert "posting_status" not in applied[0]


def test_close_posting_button_marks_position_closed():
    storage.save_saved([{
        "company": "Acme", "title": "Backend", "link": "",
        "posting_status": storage.POSTING_STATUS_OPEN, "date_saved": "2026-01-01",
    }])

    at = AppTest.from_function(_render_saved).run()
    close_button = next(b for b in at.button if b.key == "close_posting_0")
    close_button.click().run()

    assert not at.exception
    saved = storage.load_saved()
    assert len(saved) == 1
    assert saved[0]["posting_status"] == storage.POSTING_STATUS_CLOSED


def test_close_posting_button_hidden_once_closed():
    storage.save_saved([{
        "company": "Acme", "title": "Backend", "link": "",
        "posting_status": storage.POSTING_STATUS_CLOSED, "date_saved": "2026-01-01",
    }])

    at = AppTest.from_function(_render_saved).run()

    assert not at.exception
    assert not any(b.key == "close_posting_0" for b in at.button)
    assert any("No open postings" in c.value for c in at.caption)


def test_close_posting_only_shows_buttons_for_open_positions():
    storage.save_saved([
        {"company": "Acme", "title": "Backend", "link": "", "posting_status": storage.POSTING_STATUS_OPEN,
         "date_saved": "2026-01-01"},
        {"company": "Globex", "title": "Frontend", "link": "", "posting_status": storage.POSTING_STATUS_CLOSED,
         "date_saved": "2026-01-01"},
    ])

    at = AppTest.from_function(_render_saved).run()

    assert not at.exception
    assert any(b.key == "close_posting_0" for b in at.button)
    assert not any(b.key == "close_posting_1" for b in at.button)


def test_closed_postings_sort_to_the_end_by_default():
    # AppTest can't read st.data_editor's rendered grid directly, so this
    # round-trips through an unmodified "Save changes" click instead: the
    # editor hands back rows in the same order it was given, so the saved
    # order reflects what the grid displayed.
    storage.save_saved([
        {"company": "Closed Co", "title": "A", "link": "", "posting_status": storage.POSTING_STATUS_CLOSED,
         "date_saved": "2026-01-01"},
        {"company": "Open Co", "title": "B", "link": "", "posting_status": storage.POSTING_STATUS_OPEN,
         "date_saved": "2026-01-01"},
    ])

    at = AppTest.from_function(_render_saved).run()
    at.button(key="save_saved_btn").click().run()

    assert not at.exception
    assert [r["company"] for r in storage.load_saved()] == ["Open Co", "Closed Co"]


def test_hide_closed_toggle_not_shown_when_nothing_is_closed():
    storage.save_saved([{"company": "Acme", "title": "Backend", "link": "", "date_saved": "2026-01-01"}])

    at = AppTest.from_function(_render_saved).run()

    assert not at.exception
    assert not any(t.key == "hide_closed_postings" for t in at.toggle)


def test_hide_closed_toggle_defaults_to_on():
    storage.save_saved([
        {"company": "Open Co", "title": "A", "link": "", "posting_status": storage.POSTING_STATUS_OPEN,
         "date_saved": "2026-01-01"},
        {"company": "Closed Co", "title": "B", "link": "", "posting_status": storage.POSTING_STATUS_CLOSED,
         "date_saved": "2026-01-01"},
    ])

    at = AppTest.from_function(_render_saved).run()

    assert not at.exception
    assert at.toggle(key="hide_closed_postings").value is True

    # A plain, unmodified save should still write both back - the default
    # hide is a display-only filter, never a silent drop of closed rows.
    at.button(key="save_saved_btn").click().run()
    assert {r["company"] for r in storage.load_saved()} == {"Open Co", "Closed Co"}


def test_hide_closed_toggle_filters_table_but_keeps_closed_rows_on_save():
    storage.save_saved([
        {"company": "Open Co", "title": "A", "link": "", "posting_status": storage.POSTING_STATUS_OPEN,
         "date_saved": "2026-01-01"},
        {"company": "Closed Co", "title": "B", "link": "", "posting_status": storage.POSTING_STATUS_CLOSED,
         "date_saved": "2026-01-01"},
    ])

    at = AppTest.from_function(_render_saved).run()
    at = at.toggle(key="hide_closed_postings").set_value(True).run()

    assert not at.exception
    at.button(key="save_saved_btn").click().run()

    assert not at.exception
    saved = storage.load_saved()
    assert {r["company"] for r in saved} == {"Open Co", "Closed Co"}
    closed = next(r for r in saved if r["company"] == "Closed Co")
    assert closed["posting_status"] == storage.POSTING_STATUS_CLOSED


def test_calculate_fit_requires_a_resume():
    storage.save_saved([{"company": "Acme", "title": "Backend", "link": "", "date_saved": "2026-01-01"}])

    at = AppTest.from_function(_render_saved).run()
    at.button(key="calc_fit_saved_btn").click().run()

    assert not at.exception
    assert any("Add a resume" in e.value for e in at.error)
    assert storage.load_saved()[0].get("fit_score") in (None, "")


def test_calculate_fit_scores_every_saved_position_one_by_one(monkeypatch):
    from src import fit_analysis

    storage.save_resume("My resume")
    storage.save_saved(
        [
            {"company": "Acme", "title": "Backend", "link": "", "date_saved": "2026-01-01"},
            {"company": "Globex", "title": "Frontend", "link": "", "date_saved": "2026-01-02"},
        ]
    )

    scored = []

    def fake_analyze(resume_text, job, model=None):
        scored.append(job["company"])
        return {"fit_score": 8, "fit_notes": "Strong match."}

    monkeypatch.setattr(fit_analysis, "analyze", fake_analyze)

    at = AppTest.from_function(_render_saved).run()
    at = at.button(key="calc_fit_saved_btn").click().run()

    assert not at.exception
    # Looped one position at a time (not a single batched call).
    assert scored == ["Acme", "Globex"]
    saved = storage.load_saved()
    assert all(r["fit_score"] == 8 and r["fit_notes"] == "Strong match." for r in saved)


def test_calculate_fit_surfaces_ollama_error_without_blocking_the_rest(monkeypatch):
    from src import fit_analysis, ollama_client

    storage.save_resume("My resume")
    storage.save_saved(
        [
            {"company": "Acme", "title": "Backend", "link": "", "date_saved": "2026-01-01"},
            {"company": "Globex", "title": "Frontend", "link": "", "date_saved": "2026-01-02"},
        ]
    )

    def flaky_analyze(resume_text, job, model=None):
        if job["company"] == "Acme":
            raise ollama_client.OllamaError("Could not reach Ollama")
        return {"fit_score": 8, "fit_notes": "Strong match."}

    monkeypatch.setattr(fit_analysis, "analyze", flaky_analyze)

    at = AppTest.from_function(_render_saved).run()
    at = at.button(key="calc_fit_saved_btn").click().run()

    assert not at.exception
    saved = storage.load_saved()
    acme = next(r for r in saved if r["company"] == "Acme")
    globex = next(r for r in saved if r["company"] == "Globex")
    assert acme.get("fit_score") in (None, "")
    assert globex["fit_score"] == 8


def test_calculate_fit_shows_info_when_no_saved_positions():
    at = AppTest.from_function(_render_saved).run()
    at.button(key="calc_fit_saved_btn").click().run()

    assert not at.exception
    assert any("Add a saved position" in i.value for i in at.info)


def test_calculate_fit_skips_positions_that_already_have_a_score(monkeypatch):
    from src import fit_analysis

    storage.save_resume("My resume")
    storage.save_saved(
        [
            {"company": "Acme", "title": "Backend", "link": "", "date_saved": "2026-01-01", "fit_score": 5, "fit_notes": "Old."},
            {"company": "Globex", "title": "Frontend", "link": "", "date_saved": "2026-01-02"},
        ]
    )

    scored = []

    def fake_analyze(resume_text, job, model=None):
        scored.append(job["company"])
        return {"fit_score": 9, "fit_notes": "New."}

    monkeypatch.setattr(fit_analysis, "analyze", fake_analyze)

    at = AppTest.from_function(_render_saved).run()
    at = at.button(key="calc_fit_saved_btn").click().run()

    assert not at.exception
    assert scored == ["Globex"]
    saved = storage.load_saved()
    acme = next(r for r in saved if r["company"] == "Acme")
    globex = next(r for r in saved if r["company"] == "Globex")
    assert acme["fit_score"] == 5 and acme["fit_notes"] == "Old."
    assert globex["fit_score"] == 9


def test_calculate_fit_persists_each_position_before_scoring_the_next(monkeypatch):
    from src import fit_analysis

    storage.save_resume("My resume")
    storage.save_saved(
        [
            {"company": "Acme", "title": "Backend", "link": "", "date_saved": "2026-01-01"},
            {"company": "Globex", "title": "Frontend", "link": "", "date_saved": "2026-01-02"},
        ]
    )

    seen_acme_score_before_globex = []

    def fake_analyze(resume_text, job, model=None):
        if job["company"] == "Globex":
            on_disk = next((r for r in storage.load_saved() if r["company"] == "Acme"), None)
            seen_acme_score_before_globex.append(on_disk.get("fit_score") if on_disk else None)
        return {"fit_score": 7, "fit_notes": "ok"}

    monkeypatch.setattr(fit_analysis, "analyze", fake_analyze)

    at = AppTest.from_function(_render_saved).run()
    at = at.button(key="calc_fit_saved_btn").click().run()

    assert not at.exception
    # Acme's score was already written to storage by the time Globex was
    # analyzed - each position is saved separately, not all at the end.
    assert seen_acme_score_before_globex == [7]


def test_calculate_fit_shows_info_when_everything_already_scored(monkeypatch):
    storage.save_resume("My resume")
    storage.save_saved(
        [{"company": "Acme", "title": "Backend", "link": "", "date_saved": "2026-01-01", "fit_score": 5}]
    )

    at = AppTest.from_function(_render_saved).run()
    at = at.button(key="calc_fit_saved_btn").click().run()

    assert not at.exception
    assert any("already has a fit score" in i.value for i in at.info)
