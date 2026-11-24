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


def test_save_button_moves_match_to_saved_jobs():
    _seed()
    at = AppTest.from_function(_render).run()
    save_btn = next(b for b in at.button if b.key and b.key.startswith("match_save_"))
    save_btn.click().run()
    assert not at.exception
    assert [r["company"] for r in storage.load_saved()] == ["High"]


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
    at.button[[b.label for b in at.button].index("Save profile")].click().run()
    assert not at.exception
    profile = storage.load_match_profile()
    assert profile["titles"] == ["Backend Engineer", "AI Infrastructure Engineer"]
    assert profile["location"] == "Tel Aviv, Israel"
    assert profile["exclude_keywords"] == ["frontend"]
