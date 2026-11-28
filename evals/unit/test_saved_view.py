from datetime import date

from streamlit.testing.v1 import AppTest

from src import fit_analysis, job_extract, saved_view, storage


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


def test_fit_help_shows_truncated_notes_even_with_no_fit_detail_fields():
    # Regression guard: _fit_tooltip() returns exactly fit_notes back for a
    # record with no matched/required_gaps/preferred_gaps/unknowns fields
    # (e.g. one scored before those fields existed) - comparing that
    # against the full notes (rather than the truncated `preview` actually
    # shown on the card) used to suppress the hover tooltip entirely for
    # long notes, leaving no way to read the rest.
    long_notes = "A" * 200
    record = {"fit_notes": long_notes}
    preview = long_notes[:107] + "..."

    assert saved_view._fit_help(record, preview) == long_notes


def test_fit_help_is_none_when_nothing_is_truncated():
    record = {"fit_notes": "Short note."}
    assert saved_view._fit_help(record, "Short note.") is None


def test_unverified_fields_warning_lists_the_flagged_fields():
    from src import saved_view

    warning = saved_view._unverified_fields_warning({"unverified": ["location", "salary"]})

    assert "location" in warning
    assert "salary" in warning


def test_unverified_fields_warning_is_empty_when_nothing_flagged():
    from src import saved_view

    assert saved_view._unverified_fields_warning({"unverified": []}) == ""
    assert saved_view._unverified_fields_warning({}) == ""


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


def test_paste_popover_fetches_description_from_link_when_left_blank(monkeypatch):
    """The core of "save a position from just a link": leaving the
    description blank fetches the posting text automatically instead of
    requiring it to be pasted by hand."""
    monkeypatch.setattr(fit_analysis, "fetch_posting_text", lambda link: "We are Acme, hiring a Backend Engineer.")
    monkeypatch.setattr(
        job_extract,
        "extract_fields",
        lambda description: {
            "company": "Acme", "title": "Backend Engineer", "location": "Remote", "salary": "100k"
        },
    )

    at = AppTest.from_function(_render_saved).run()
    at.text_input(key="paste_description_link_0").set_value("https://acme.example/jobs/1")
    at.button(key="create_from_paste_btn").click().run()

    assert not at.exception
    records = storage.load_saved()
    assert len(records) == 1
    assert records[0]["company"] == "Acme"
    assert records[0]["description"] == "We are Acme, hiring a Backend Engineer."
    assert records[0]["link"] == "https://acme.example/jobs/1"


def test_paste_popover_prefers_a_pasted_description_over_fetching(monkeypatch):
    """A pasted description is the fallback for sites that block a plain
    fetch (LinkedIn, Workday, ...) - it must win over auto-fetching, and
    fetch_posting_text must not even be called when one was pasted."""
    def fail_if_called(link):
        raise AssertionError("fetch_posting_text should not be called when a description was pasted")

    monkeypatch.setattr(fit_analysis, "fetch_posting_text", fail_if_called)
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
    assert storage.load_saved()[0]["description"] == "We are Acme, hiring."


def test_paste_popover_shows_error_when_the_link_cant_be_fetched_and_nothing_was_pasted(monkeypatch):
    monkeypatch.setattr(fit_analysis, "fetch_posting_text", lambda link: "")

    at = AppTest.from_function(_render_saved).run()
    at.text_input(key="paste_description_link_0").set_value("https://linkedin.com/jobs/view/123")
    at.button(key="create_from_paste_btn").click().run()

    assert not at.exception
    assert storage.load_saved() == []
    assert any("Couldn't fetch that page automatically" in e.value for e in at.error)


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


def test_mark_applied_button_opens_dialog_without_moving():
    storage.save_saved([{"company": "Acme", "title": "Backend", "link": "", "date_saved": "2026-01-01"}])

    at = AppTest.from_function(_render_saved).run()
    at.button(key="mark_applied_row_Acme_Backend_0").click().run()

    assert not at.exception
    # Still in Saved Positions - a single click only opens the dialog, it
    # doesn't move the record yet (see saved_view._mark_applied_dialog).
    assert storage.load_applied() == []
    assert at.button(key="confirm_mark_applied_Acme_Backend_0") is not None


def test_move_to_applied_transfers_record():
    from src import saved_view

    storage.save_saved([{"company": "Acme", "title": "Backend", "link": "", "date_saved": "2026-01-01"}])
    records = storage.load_saved()

    saved_view._move_to_applied(records, 0, date(2026, 1, 2), "Applied")

    assert storage.load_saved() == []
    applied = storage.load_applied()
    assert len(applied) == 1
    assert applied[0]["company"] == "Acme"
    assert applied[0]["status"] == "Applied"
    assert applied[0]["date_applied"] == "2026-01-02"


def test_move_to_applied_drops_posting_status():
    # "Open/Closed for applications" describes the job posting, not this
    # user's own pipeline stage (APPLIED_COLUMNS' separate "status") - it
    # has no meaning once the position has moved to Applied.
    from src import saved_view

    storage.save_saved([{
        "company": "Acme", "title": "Backend", "link": "",
        "posting_status": storage.POSTING_STATUS_OPEN, "date_saved": "2026-01-01",
    }])
    records = storage.load_saved()

    saved_view._move_to_applied(records, 0, date(2026, 1, 2), "Applied")

    applied = storage.load_applied()
    assert "posting_status" not in applied[0]


def test_mark_closed_button_marks_position_closed():
    storage.save_saved([{
        "company": "Acme", "title": "Backend", "link": "",
        "posting_status": storage.POSTING_STATUS_OPEN, "date_saved": "2026-01-01",
    }])

    at = AppTest.from_function(_render_saved).run()
    close_button = next(b for b in at.button if b.key == "toggle_closed_row_Acme_Backend_0")
    close_button.click().run()

    assert not at.exception
    saved = storage.load_saved()
    assert len(saved) == 1
    assert saved[0]["posting_status"] == storage.POSTING_STATUS_CLOSED


def test_unknown_posting_status_shows_a_caption_without_disabling_actions():
    storage.save_saved([{
        "company": "Acme", "title": "Backend", "link": "",
        "posting_status": storage.POSTING_STATUS_UNKNOWN, "date_saved": "2026-01-01",
    }])

    at = AppTest.from_function(_render_saved).run()

    assert not at.exception
    assert any("Couldn't confirm it's still open" in c.value for c in at.caption)
    # Unlike a confirmed-closed posting, "unknown" is informational only -
    # it must never disable row actions the way a confirmed closed does.
    assert not next(b for b in at.button if b.key == "mark_applied_row_Acme_Backend_0").disabled


def test_bulk_edit_round_trip_preserves_fit_detail_and_checked_at_fields():
    # Regression guard: to_dataframe/from_dataframe round-trip only keeps
    # whatever's in storage.SAVED_COLUMNS - a field left out of that list
    # would be silently dropped the moment someone clicks "Save changes"
    # without even touching the grid.
    storage.save_saved([{
        "company": "Acme", "title": "Backend", "link": "", "date_saved": "2026-01-01",
        "posting_status": storage.POSTING_STATUS_CLOSED, "posting_checked_at": "2026-11-20",
        "fit_matched": "Python: matches", "fit_required_gaps": "AWS: gap",
        "fit_preferred_gaps": "K8s: gap", "fit_unknowns": "On-call: unknown",
    }])

    at = AppTest.from_function(_render_saved).run()
    at.button(key="save_saved_btn").click().run()

    assert not at.exception
    [saved] = storage.load_saved()
    assert saved["posting_checked_at"] == "2026-11-20"
    assert saved["fit_matched"] == "Python: matches"
    assert saved["fit_required_gaps"] == "AWS: gap"
    assert saved["fit_preferred_gaps"] == "K8s: gap"
    assert saved["fit_unknowns"] == "On-call: unknown"


def test_closed_posting_hidden_by_default_toggle():
    storage.save_saved([{
        "company": "Acme", "title": "Backend", "link": "",
        "posting_status": storage.POSTING_STATUS_CLOSED, "date_saved": "2026-01-01",
    }])

    at = AppTest.from_function(_render_saved).run()

    assert not at.exception
    # Hide-closed defaults to on, so the only (closed) row isn't rendered
    # at all - no row-action buttons for it should exist.
    assert not any(b.key and b.key.startswith("mark_applied_row_") for b in at.button)
    assert any("No saved positions match the current filters." in c.value for c in at.caption)


def test_overflow_menu_offers_reopen_for_a_closed_position_when_shown():
    storage.save_saved([
        {"company": "Acme", "title": "Backend", "link": "", "posting_status": storage.POSTING_STATUS_OPEN,
         "date_saved": "2026-01-01"},
        {"company": "Globex", "title": "Frontend", "link": "", "posting_status": storage.POSTING_STATUS_CLOSED,
         "date_saved": "2026-01-01"},
    ])

    at = AppTest.from_function(_render_saved).run()
    at = at.toggle(key="hide_closed_postings").set_value(False).run()

    assert not at.exception
    acme_row = "Acme_Backend_0"
    globex_row = "Globex_Frontend_1"
    assert any(b.key == f"toggle_closed_row_{acme_row}" and b.label == "Mark closed" for b in at.button)
    assert any(b.key == f"toggle_closed_row_{globex_row}" and b.label == "Reopen" for b in at.button)
    # Closed postings can't be marked applied or re-analyzed from the row.
    assert next(b for b in at.button if b.key == f"mark_applied_row_{globex_row}").disabled


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


def test_sorts_by_fit_score_descending_with_unscored_last():
    storage.save_saved([
        {"company": "Low", "title": "A", "link": "", "date_saved": "2026-01-01", "fit_score": 3},
        {"company": "Unscored", "title": "B", "link": "", "date_saved": "2026-01-01"},
        {"company": "High", "title": "C", "link": "", "date_saved": "2026-01-01", "fit_score": 9},
    ])

    at = AppTest.from_function(_render_saved).run()
    at.button(key="save_saved_btn").click().run()

    assert not at.exception
    assert [r["company"] for r in storage.load_saved()] == ["High", "Low", "Unscored"]


def test_closed_postings_still_sort_last_regardless_of_fit_score():
    storage.save_saved([
        {
            "company": "Closed High Score", "title": "A", "link": "", "date_saved": "2026-01-01",
            "fit_score": 10, "posting_status": storage.POSTING_STATUS_CLOSED,
        },
        {"company": "Open Low Score", "title": "B", "link": "", "date_saved": "2026-01-01", "fit_score": 1},
    ])

    at = AppTest.from_function(_render_saved).run()
    at.button(key="save_saved_btn").click().run()

    assert not at.exception
    assert [r["company"] for r in storage.load_saved()] == ["Open Low Score", "Closed High Score"]


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
    storage.save_resume("My resume")

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


def test_calculate_fit_skips_closed_postings(monkeypatch):
    from src import fit_analysis

    storage.save_resume("My resume")
    storage.save_saved(
        [
            {
                "company": "Acme", "title": "Backend", "link": "", "date_saved": "2026-01-01",
                "posting_status": storage.POSTING_STATUS_CLOSED,
            },
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
    assert acme.get("fit_score") in (None, "")


def test_calculate_fit_shows_info_when_only_closed_postings_are_unscored():
    storage.save_resume("My resume")
    storage.save_saved(
        [
            {
                "company": "Acme", "title": "Backend", "link": "", "date_saved": "2026-01-01",
                "posting_status": storage.POSTING_STATUS_CLOSED,
            },
            {"company": "Globex", "title": "Frontend", "link": "", "date_saved": "2026-01-02", "fit_score": 5},
        ]
    )

    at = AppTest.from_function(_render_saved).run()
    at = at.button(key="calc_fit_saved_btn").click().run()

    assert not at.exception
    assert any("already has a fit score" in i.value for i in at.info)
    acme = next(r for r in storage.load_saved() if r["company"] == "Acme")
    assert acme.get("fit_score") in (None, "")


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


def test_analyze_fit_row_button_scores_a_single_position(monkeypatch):
    from src import fit_analysis

    storage.save_resume("My resume")
    storage.save_saved([{"company": "Acme", "title": "Backend", "link": "", "date_saved": "2026-01-01"}])

    monkeypatch.setattr(
        fit_analysis, "analyze", lambda resume_text, job, model=None: {"fit_score": 9, "fit_notes": "Great fit."}
    )

    at = AppTest.from_function(_render_saved).run()
    at.button(key="analyze_fit_row_Acme_Backend_0").click().run()

    assert not at.exception
    saved = storage.load_saved()
    assert saved[0]["fit_score"] == 9
    assert saved[0]["fit_notes"] == "Great fit."


def test_overflow_edit_dialog_saves_changes_to_the_record():
    storage.save_saved([{"company": "Acme", "title": "Backend", "link": "", "date_saved": "2026-01-01"}])

    at = AppTest.from_function(_render_saved).run()
    at.button(key="edit_row_Acme_Backend_0").click().run()

    assert not at.exception
    assert at.text_input(key="edit_saved_company_Acme_Backend_0").value == "Acme"
    assert at.button(key="save_edit_saved_Acme_Backend_0") is not None


def test_overflow_remove_opens_confirmation_dialog_without_removing():
    storage.save_saved([{"company": "Acme", "title": "Backend", "link": "", "date_saved": "2026-01-01"}])

    at = AppTest.from_function(_render_saved).run()
    at.button(key="remove_row_Acme_Backend_0").click().run()

    assert not at.exception
    assert storage.load_saved() != []
    assert at.button(key="confirm_remove_saved_Acme_Backend_0") is not None


def test_search_filters_the_primary_list():
    storage.save_saved([
        {"company": "Acme", "title": "Backend", "link": "", "date_saved": "2026-01-01"},
        {"company": "Globex", "title": "Frontend", "link": "", "date_saved": "2026-01-01"},
    ])

    at = AppTest.from_function(_render_saved).run()
    at = at.text_input(key="saved_search").set_value("acme").run()

    assert not at.exception
    assert any(b.key == "mark_applied_row_Acme_Backend_0" for b in at.button)
    assert not any(b.key and b.key.startswith("mark_applied_row_Globex") for b in at.button)


def test_calculate_fit_shows_info_when_everything_already_scored(monkeypatch):
    storage.save_resume("My resume")
    storage.save_saved(
        [{"company": "Acme", "title": "Backend", "link": "", "date_saved": "2026-01-01", "fit_score": 5}]
    )

    at = AppTest.from_function(_render_saved).run()
    at = at.button(key="calc_fit_saved_btn").click().run()

    assert not at.exception
    assert any("already has a fit score" in i.value for i in at.info)
