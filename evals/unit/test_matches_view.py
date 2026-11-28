from streamlit.testing.v1 import AppTest

from src import job_search_client, storage


def _render():
    from src import matches_view

    matches_view.render()


def _seed():
    storage.save_matched([
        {"company": "Low", "title": "Backend", "link": "https://low.example", "source": storage.MATCH_SOURCE_GMAIL,
         "match_status": storage.MATCH_STATUS_NEW, "fit_score": 3, "fit_notes": "", "date_found": "2026-11-20"},
        {"company": "High", "title": "Backend", "link": "https://high.example",
         "source": storage.MATCH_SOURCE_LINKEDIN, "match_status": storage.MATCH_STATUS_NEW, "fit_score": 9,
         "fit_notes": "great", "date_found": "2026-11-21", "description": "desc"},
        {"company": "Gone", "title": "Backend", "link": "https://gone.example", "source": storage.MATCH_SOURCE_GMAIL,
         "match_status": storage.MATCH_STATUS_DISMISSED, "fit_score": None, "date_found": "2026-11-21"},
    ])


def test_scanning_gmail_shows_the_new_match_in_the_same_run(monkeypatch):
    # Regression guard: render() used to load `matches` before the Scan/
    # Search buttons in _render_header ran, so a successful scan's new
    # record (and the "Added N new match(es)" message above it) wasn't
    # reflected in the toolbar counts or the card list until an unrelated
    # later rerun. render() now re-reads `matches` after the header runs.
    from src import gmail_client, job_matching

    monkeypatch.setattr(gmail_client, "is_connected", lambda: True)
    monkeypatch.setattr(
        job_matching, "gmail_alert_candidates",
        lambda on_progress=None: (
            [{"company": "Fresh", "title": "Backend Engineer", "link": "https://fresh.example"}], [],
        ),
    )

    at = AppTest.from_function(_render).run()
    at = at.button(key="match_scan_gmail_btn").click().run()

    assert not at.exception
    assert any("Added 1 new match" in s.value for s in at.success)
    assert any("Fresh" in md.value for md in at.markdown)


def test_empty_state_renders():
    at = AppTest.from_function(_render).run()
    assert not at.exception
    assert any("No matches yet" in i.value for i in at.info)


def test_new_matches_sorted_best_fit_first_and_dismissed_hidden():
    _seed()
    at = AppTest.from_function(_render).run()
    assert not at.exception
    markdown = [m.value for m in at.markdown if "font-weight:700" in m.value]
    assert len(markdown) == 2
    assert "High" in markdown[0] and "Low" in markdown[1]


def test_description_button_shown_only_when_present():
    _seed()
    at = AppTest.from_function(_render).run()
    assert not at.exception
    buttons = [b for b in at.button if b.key and b.key.startswith("match_description_")]
    # Only "High" has a description; "Low" and "Gone" (dismissed, hidden) do not.
    assert len(buttons) == 1


def test_description_button_opens_a_dialog_with_the_full_text():
    _seed()
    at = AppTest.from_function(_render).run()
    button = next(b for b in at.button if b.key and b.key.startswith("match_description_"))
    at = button.click().run()

    assert not at.exception
    assert any("desc" in m.value for m in at.markdown)
    assert any("High" in m.value and "Backend" in m.value for m in at.markdown)


def test_why_you_match_dialog_shows_evidence_backed_sections():
    storage.save_matched([{
        "company": "High", "title": "Backend", "link": "https://high.example",
        "source": storage.MATCH_SOURCE_LINKEDIN, "match_status": storage.MATCH_STATUS_NEW, "fit_score": 9,
        "fit_notes": "great", "fit_matched": "Python: 5 years on resume",
        "fit_required_gaps": "AWS required; resume only shows GCP",
        "fit_preferred_gaps": "Kubernetes preferred; not on resume",
        "fit_unknowns": "On-call experience not mentioned",
    }])
    at = AppTest.from_function(_render).run()
    button = next(b for b in at.button if b.key and b.key.startswith("match_score_open_"))
    at = button.click().run()

    assert not at.exception
    text = "\n".join(m.value for m in at.markdown)
    assert "Python: 5 years" in text
    assert "AWS required" in text
    assert "Kubernetes preferred" in text
    assert "On-call experience not mentioned" in text


def test_card_shows_closed_posting_status():
    storage.save_matched([{
        "company": "Gone Corp", "title": "Backend", "link": "https://gone-corp.example",
        "source": storage.MATCH_SOURCE_LINKEDIN, "match_status": storage.MATCH_STATUS_NEW,
        "posting_status": storage.POSTING_STATUS_CLOSED,
    }])
    at = AppTest.from_function(_render).run()
    assert not at.exception
    assert any(storage.POSTING_STATUS_CLOSED in m.value for m in at.markdown)


def test_card_hides_posting_status_when_open():
    storage.save_matched([{
        "company": "Fine Corp", "title": "Backend", "link": "https://fine-corp.example",
        "source": storage.MATCH_SOURCE_LINKEDIN, "match_status": storage.MATCH_STATUS_NEW,
        "posting_status": storage.POSTING_STATUS_OPEN,
    }])
    at = AppTest.from_function(_render).run()
    assert not at.exception
    assert not any(storage.POSTING_STATUS_OPEN in m.value for m in at.markdown)


def test_save_button_moves_match_to_saved_jobs():
    _seed()
    at = AppTest.from_function(_render).run()
    save_btn = next(b for b in at.button if b.key and b.key.startswith("match_save_"))
    save_btn.click().run()
    assert not at.exception
    assert [r["company"] for r in storage.load_saved()] == ["High"]


def test_apply_button_moves_match_to_applied_positions():
    _seed()
    at = AppTest.from_function(_render).run()
    apply_btn = next(b for b in at.button if b.key and b.key.startswith("match_apply_"))
    apply_btn.click().run()
    assert not at.exception
    assert [r["company"] for r in storage.load_applied()] == ["High"]


def test_save_button_opens_a_conflict_dialog_even_for_the_same_bucket():
    # "High" is already in Saved Jobs outside the Matching Jobs flow (same
    # bucket as the button just clicked). save_to_saved_jobs still must not
    # decide anything on its own - the dialog always gets the call.
    _seed()
    storage.save_saved([{"company": "High", "title": "Backend", "link": "https://high.example"}])

    at = AppTest.from_function(_render).run()
    save_btn = next(b for b in at.button if b.key and b.key.startswith("match_save_"))
    at = save_btn.click().run()

    assert not at.exception
    assert len(storage.load_saved()) == 1
    assert any("already in" in m.value and "Saved Jobs" in m.value for m in at.markdown)
    assert [r["match_status"] for r in storage.load_matched() if r["company"] == "High"] == [
        storage.MATCH_STATUS_NEW
    ]


def test_save_button_opens_a_conflict_dialog_instead_of_mislabeling_an_applied_match():
    # "High" is already in Applied Positions outside the Matching Jobs
    # flow; clicking "Save job" must not silently relabel it as merely
    # Saved (see job_matching.save_to_saved_jobs) - it should ask.
    _seed()
    storage.save_applied([{"company": "High", "title": "Backend", "link": "https://high.example"}])

    at = AppTest.from_function(_render).run()
    save_btn = next(b for b in at.button if b.key and b.key.startswith("match_save_"))
    at = save_btn.click().run()

    assert not at.exception
    assert storage.load_saved() == []
    assert any("already in" in m.value and "Applied Positions" in m.value for m in at.markdown)
    assert [r["match_status"] for r in storage.load_matched() if r["company"] == "High"] == [
        storage.MATCH_STATUS_NEW
    ]


def test_apply_button_opens_a_conflict_dialog_instead_of_mislabeling_a_saved_match():
    _seed()
    storage.save_saved([{"company": "High", "title": "Backend", "link": "https://high.example"}])

    at = AppTest.from_function(_render).run()
    apply_btn = next(b for b in at.button if b.key and b.key.startswith("match_apply_"))
    at = apply_btn.click().run()

    assert not at.exception
    assert storage.load_applied() == []
    assert any("already in" in m.value and "Saved Jobs" in m.value for m in at.markdown)
    assert [r["match_status"] for r in storage.load_matched() if r["company"] == "High"] == [
        storage.MATCH_STATUS_NEW
    ]


def test_same_bucket_conflict_dialog_does_not_offer_to_create_a_duplicate():
    # Regression test: "High" is tagged New in Matching Jobs but a separate
    # Applied record for the same company+title already exists (added some
    # other way) - tracked_elsewhere() reports "applied", and clicking "Add
    # to Applications" (also targeting Applied) used to offer "Also add it
    # to Applied Positions", which would create an actual second Applied
    # record for one real job rather than resolve anything.
    _seed()
    storage.save_applied([{"company": "High", "title": "Backend", "link": "https://high.example"}])

    at = AppTest.from_function(_render).run()
    apply_btn = next(b for b in at.button if b.key and b.key.startswith("match_apply_"))
    at = apply_btn.click().run()

    assert not at.exception
    assert any("already in" in m.value and "Applied Positions" in m.value for m in at.markdown)
    assert not any(b.label == "Also add it to Applied Positions" for b in at.button)
    assert any("would just create a duplicate" in c.value for c in at.caption)
    assert any(b.label.startswith("Keep it in Applied Positions") for b in at.button)
    assert len(storage.load_applied()) == 1


def test_conflict_dialog_never_offers_to_force_save_an_applied_match_back_to_saved():
    # Regression test (Critical): "High" is already in Applied Positions.
    # Clicking "Save job" on the Matching Jobs card used to offer "Also add
    # it to Saved Jobs", which would copy an in-flight application back
    # into Saved Jobs - a backward stage move. That force option must
    # never be shown for this direction, only the label-sync option.
    _seed()
    storage.save_applied([{"company": "High", "title": "Backend", "link": "https://high.example"}])

    at = AppTest.from_function(_render).run()
    save_btn = next(b for b in at.button if b.key and b.key.startswith("match_save_"))
    at = save_btn.click().run()

    assert not at.exception
    assert not any(b.label == "Also add it to Saved Jobs" for b in at.button)
    assert any("would move it backward" in c.value for c in at.caption)
    assert storage.load_saved() == []


def test_dismiss_button_hides_match():
    _seed()
    at = AppTest.from_function(_render).run()
    dismiss = [b for b in at.button if b.key and b.key.startswith("match_dismiss_")]
    dismiss[0].click().run()
    assert not at.exception
    statuses = {r["company"]: r["match_status"] for r in storage.load_matched()}
    assert statuses["High"] == storage.MATCH_STATUS_DISMISSED


def test_google_button_disabled_without_key(monkeypatch):
    monkeypatch.delenv(job_search_client.API_KEY_ENV_VAR, raising=False)
    at = AppTest.from_function(_render).run()
    assert at.button(key="match_search_google_btn").disabled


def test_saving_profile_persists_lists():
    at = AppTest.from_function(_render).run()
    at.text_input(key="match_titles").set_value("Backend Engineer, AI Infrastructure Engineer")
    at.text_input(key="match_location").set_value("Tel Aviv, Israel")
    at.text_input(key="match_excludes").set_value("frontend")
    at.button[[b.label for b in at.button].index("Save search settings")].click().run()
    assert not at.exception
    profile = storage.load_match_profile()
    assert profile["titles"] == ["Backend Engineer", "AI Infrastructure Engineer"]
    assert profile["location"] == "Tel Aviv, Israel"
    assert profile["exclude_keywords"] == ["frontend"]


def test_saving_profile_persists_experience_bounds():
    at = AppTest.from_function(_render).run()
    at.number_input(key="match_min_years").set_value(3)
    at.number_input(key="match_max_years").set_value(6)
    at.button[[b.label for b in at.button].index("Save search settings")].click().run()

    assert not at.exception
    profile = storage.load_match_profile()
    assert profile["min_experience_years"] == 3
    assert profile["max_experience_years"] == 6


def test_experience_bounds_persist_after_reload():
    storage.save_match_profile(
        {**storage.DEFAULT_MATCH_PROFILE, "min_experience_years": 3, "max_experience_years": 6}
    )
    at = AppTest.from_function(_render).run()
    assert not at.exception
    assert at.number_input(key="match_min_years").value == 3
    assert at.number_input(key="match_max_years").value == 6


def test_saving_profile_rejects_min_greater_than_max():
    at = AppTest.from_function(_render).run()
    at.number_input(key="match_min_years").set_value(6)
    at.number_input(key="match_max_years").set_value(3)
    at = at.button[[b.label for b in at.button].index("Save search settings")].click().run()

    assert not at.exception
    assert any("Min years must be" in e.value for e in at.error)
    # The invalid combination must never be persisted.
    profile = storage.load_match_profile()
    assert profile["min_experience_years"] is None
    assert profile["max_experience_years"] is None


def test_saving_profile_with_untouched_experience_fields_means_no_limit():
    # AppTest's NumberInput.set_value(None) can't simulate clearing an
    # already-populated field back to blank (a harness limitation, not an
    # app one) - this instead confirms the natural blank-by-default path:
    # submitting the form without ever touching the experience fields saves
    # no limit, same as before this feature existed.
    at = AppTest.from_function(_render).run()
    assert at.number_input(key="match_min_years").value is None
    assert at.number_input(key="match_max_years").value is None

    at.text_input(key="match_titles").set_value("Backend Engineer")
    at.button[[b.label for b in at.button].index("Save search settings")].click().run()

    assert not at.exception
    profile = storage.load_match_profile()
    assert profile["min_experience_years"] is None
    assert profile["max_experience_years"] is None


def test_saving_profile_persists_min_fit_score():
    at = AppTest.from_function(_render).run()
    at.number_input(key="match_min_fit_score").set_value(6)
    at.button[[b.label for b in at.button].index("Save filtering settings")].click().run()

    assert not at.exception
    assert storage.load_match_profile()["min_fit_score"] == 6


def test_min_fit_score_persists_after_reload():
    storage.save_match_profile({**storage.DEFAULT_MATCH_PROFILE, "min_fit_score": 6})
    at = AppTest.from_function(_render).run()
    assert not at.exception
    assert at.number_input(key="match_min_fit_score").value == 6


def test_profile_min_fit_score_sets_the_toolbar_filter_default_and_hides_low_scores():
    # min_fit_score only ever pre-fills the toolbar's own "Min fit" number
    # input (session-only, like status/source) - it never touches what
    # add_candidates() collects, so this is the one place it should have
    # any visible effect: the match list itself.
    storage.save_match_profile({**storage.DEFAULT_MATCH_PROFILE, "min_fit_score": 6})
    _seed()
    at = AppTest.from_function(_render).run()
    assert not at.exception
    assert at.number_input(key="matches_min_fit").value == 6
    markdown = [m.value for m in at.markdown if "font-weight:700" in m.value]
    assert len(markdown) == 1 and "High" in markdown[0]


def test_min_fit_score_unset_does_not_filter_the_toolbar_by_default():
    _seed()
    at = AppTest.from_function(_render).run()
    assert not at.exception
    assert at.number_input(key="matches_min_fit").value == 0
    markdown = [m.value for m in at.markdown if "font-weight:700" in m.value]
    assert len(markdown) == 2


def test_min_fit_filter_does_not_hide_an_unscored_match():
    # Regression test: the filter used to drop any match whose fit_score
    # was None/"" the moment a threshold was active - contradicting its own
    # documented behavior ("hides already-scored matches below this
    # score"). An unscored match (Ollama down, no resume yet) should stay
    # visible, not disappear.
    storage.save_matched([
        {"company": "Scored", "title": "Backend", "link": "https://scored.example",
         "source": storage.MATCH_SOURCE_LINKEDIN, "match_status": storage.MATCH_STATUS_NEW, "fit_score": 2},
        {"company": "Unscored", "title": "Backend", "link": "https://unscored.example",
         "source": storage.MATCH_SOURCE_LINKEDIN, "match_status": storage.MATCH_STATUS_NEW, "fit_score": None},
    ])
    at = AppTest.from_function(_render).run()
    at.number_input(key="matches_min_fit").set_value(6)
    at = at.run()

    assert not at.exception
    markdown = [m.value for m in at.markdown if "font-weight:700" in m.value]
    assert len(markdown) == 1 and "Unscored" in markdown[0]


def test_min_fit_filter_does_not_crash_on_a_non_numeric_stored_score():
    storage.save_matched([
        {"company": "Weird", "title": "Backend", "link": "https://weird.example",
         "source": storage.MATCH_SOURCE_LINKEDIN, "match_status": storage.MATCH_STATUS_NEW, "fit_score": "8/10"},
    ])
    at = AppTest.from_function(_render).run()
    at.number_input(key="matches_min_fit").set_value(6)
    at = at.run()

    assert not at.exception
    markdown = [m.value for m in at.markdown if "font-weight:700" in m.value]
    assert len(markdown) == 1 and "Weird" in markdown[0]


def test_card_escapes_html_in_scraped_fields():
    storage.save_matched([
        {"company": "<b>Acme</b> & Co", "title": "<script>alert(1)</script>",
         "link": "https://acme.example", "source": storage.MATCH_SOURCE_LINKEDIN,
         "match_status": storage.MATCH_STATUS_NEW},
    ])
    at = AppTest.from_function(_render).run()
    assert not at.exception
    html_blob = "\n".join(m.value for m in at.markdown)
    assert "<script>alert(1)</script>" not in html_blob
    assert "<b>Acme</b> & Co" not in html_blob
    assert "&lt;script&gt;" in html_blob
    assert "&lt;b&gt;Acme&lt;/b&gt; &amp; Co" in html_blob
