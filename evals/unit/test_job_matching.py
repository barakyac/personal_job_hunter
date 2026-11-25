import json

import pytest

from scripts import add_match
from src import fit_analysis, gmail_client, job_extract, job_matching, job_search_client, ollama_client, storage


def _job(**overrides):
    base = {"company": "Acme", "title": "Backend Engineer", "link": "https://acme.example/jobs/1",
            "location": "Tel Aviv", "description": "Python, Azure, distributed systems"}
    return {**base, **overrides}


# --- canonical_link --------------------------------------------------------

@pytest.mark.parametrize("link", [
    "https://www.linkedin.com/jobs/view/4012345678/",
    "https://www.linkedin.com/comm/jobs/view/4012345678?trackingId=abc&refId=xyz",
    "https://il.linkedin.com/jobs/view/backend-engineer-at-acme-4012345678",
    "https://www.linkedin.com/jobs/collections/recommended/?currentJobId=4012345678",
])
def test_linkedin_link_shapes_collapse_to_one(link):
    assert job_matching.canonical_link(link) == "https://www.linkedin.com/jobs/view/4012345678/"


def test_tracking_params_and_trailing_slash_are_ignored():
    a = job_matching.canonical_link("https://www.Acme.example/jobs/1/?utm_source=google&gh_jid=7")
    b = job_matching.canonical_link("https://acme.example/jobs/1?gh_jid=7")
    assert a == b


def test_empty_link_stays_empty():
    assert job_matching.canonical_link("") == ""


# --- add_candidates --------------------------------------------------------

def test_add_candidates_appends_new_with_defaults():
    counts = job_matching.add_candidates([_job()], storage.MATCH_SOURCE_GOOGLE)
    assert counts == {"added": 1, "already_tracked": 0, "filtered": 0, "invalid": 0}
    [record] = storage.load_matched()
    assert record["source"] == storage.MATCH_SOURCE_GOOGLE
    assert record["match_status"] == storage.MATCH_STATUS_NEW
    assert record["date_found"]
    assert set(storage.MATCHED_COLUMNS) <= set(record)


def test_add_candidates_skips_duplicates_within_matches_by_link_shape():
    job_matching.add_candidates([_job(link="https://www.linkedin.com/comm/jobs/view/42?trk=x")], "x")
    counts = job_matching.add_candidates(
        [_job(company="Other", title="Other", link="https://www.linkedin.com/jobs/view/42/")], "y"
    )
    assert counts["already_tracked"] == 1
    assert len(storage.load_matched()) == 1


def test_add_candidates_skips_jobs_already_saved_or_applied():
    storage.save_saved([{"company": "Acme", "title": "Backend Engineer", "link": ""}])
    storage.save_applied([{"company": "Beta", "title": "SRE", "link": "https://beta.example/1"}])
    counts = job_matching.add_candidates(
        [_job(link="https://acme.example/other"), _job(company="X", title="Y", link="https://beta.example/1")],
        "src",
    )
    assert counts["already_tracked"] == 2
    assert storage.load_matched() == []


def test_same_company_different_title_is_a_new_match():
    job_matching.add_candidates([_job()], "src")
    counts = job_matching.add_candidates([_job(title="Data Engineer", link="https://acme.example/jobs/2")], "src")
    assert counts["added"] == 1


def test_dismissed_match_is_not_re_added():
    job_matching.add_candidates([_job()], "src")
    job_matching.set_status(_job(), storage.MATCH_STATUS_DISMISSED)
    counts = job_matching.add_candidates([_job()], "src")
    assert counts["already_tracked"] == 1


def test_exclude_keywords_filter_title_and_description():
    profile = {**storage.DEFAULT_MATCH_PROFILE, "exclude_keywords": ["Frontend", "relocation"]}
    counts = job_matching.add_candidates(
        [_job(title="Frontend Engineer", link="a"), _job(company="B", description="Requires relocation", link="b"),
         _job(company="C", link="c")],
        "src", profile,
    )
    assert counts["filtered"] == 2 and counts["added"] == 1


def test_candidate_without_company_or_link_is_invalid():
    counts = job_matching.add_candidates([{"title": "Engineer"}], "src")
    assert counts["invalid"] == 1
    assert storage.load_matched() == []


# --- save / status ---------------------------------------------------------

def test_save_to_saved_jobs_copies_and_marks_saved():
    job_matching.add_candidates([_job(fit_score=8, fit_notes="good", source_detail="LinkedIn: picks")], "src")
    assert job_matching.save_to_saved_jobs(_job()) is True

    [saved] = storage.load_saved()
    assert saved["company"] == "Acme"
    assert saved["description"] == "Python, Azure, distributed systems"
    assert saved["fit_score"] == 8
    assert saved["posting_status"] == storage.POSTING_STATUS_OPEN
    assert "LinkedIn: picks" in saved["notes"]
    assert storage.load_matched()[0]["match_status"] == storage.MATCH_STATUS_SAVED


def test_save_to_saved_jobs_does_not_duplicate_an_existing_saved_job():
    # Doesn't duplicate into Saved Jobs, and doesn't touch the status tag
    # either - that's mark_status_from_reality's job, left to the caller.
    job_matching.add_candidates([_job()], "src")
    storage.save_saved([{"company": "Acme", "title": "Backend Engineer", "link": "https://acme.example/jobs/1"}])
    assert job_matching.save_to_saved_jobs(_job()) is False
    assert len(storage.load_saved()) == 1
    assert storage.load_matched()[0]["match_status"] == storage.MATCH_STATUS_NEW


def test_apply_to_applied_jobs_copies_and_marks_applied():
    job_matching.add_candidates([_job(fit_score=8, fit_notes="good", source_detail="LinkedIn: picks")], "src")
    assert job_matching.apply_to_applied_jobs(_job()) is True

    [applied] = storage.load_applied()
    assert applied["company"] == "Acme"
    assert applied["description"] == "Python, Azure, distributed systems"
    assert applied["fit_score"] == 8
    assert applied["status"] == "Applied"
    assert applied["date_applied"]
    assert "LinkedIn: picks" in applied["notes"]
    assert storage.load_matched()[0]["match_status"] == storage.MATCH_STATUS_APPLIED


def test_apply_to_applied_jobs_does_not_duplicate_an_existing_applied_job():
    job_matching.add_candidates([_job()], "src")
    storage.save_applied([{"company": "Acme", "title": "Backend Engineer", "link": "https://acme.example/jobs/1"}])
    assert job_matching.apply_to_applied_jobs(_job()) is False
    assert len(storage.load_applied()) == 1
    assert storage.load_matched()[0]["match_status"] == storage.MATCH_STATUS_NEW


# --- cross-bucket conflicts (Saved vs Applied) ------------------------------

def test_tracked_elsewhere_reports_the_other_bucket():
    job_matching.add_candidates([_job()], "src")
    storage.save_applied([{"company": "Acme", "title": "Backend Engineer", "link": "https://acme.example/jobs/1"}])
    assert job_matching.tracked_elsewhere(_job()) == "applied"


def test_tracked_elsewhere_is_none_when_not_tracked_anywhere():
    job_matching.add_candidates([_job()], "src")
    assert job_matching.tracked_elsewhere(_job()) is None


def test_save_to_saved_jobs_does_not_copy_or_relabel_when_already_applied():
    job_matching.add_candidates([_job()], "src")
    storage.save_applied([{"company": "Acme", "title": "Backend Engineer", "link": "https://acme.example/jobs/1"}])
    assert job_matching.save_to_saved_jobs(_job()) is False
    assert storage.load_saved() == []
    # Regression guard: it must not silently relabel an Applied posting as
    # merely Saved - the user needs to decide via mark_status_from_reality
    # or force=True.
    assert storage.load_matched()[0]["match_status"] == storage.MATCH_STATUS_NEW


def test_save_to_saved_jobs_forced_copies_anyway_despite_the_conflict():
    job_matching.add_candidates([_job()], "src")
    storage.save_applied([{"company": "Acme", "title": "Backend Engineer", "link": "https://acme.example/jobs/1"}])
    assert job_matching.save_to_saved_jobs(_job(), force=True) is True
    assert len(storage.load_saved()) == 1
    assert storage.load_matched()[0]["match_status"] == storage.MATCH_STATUS_SAVED


def test_apply_to_applied_jobs_does_not_copy_or_relabel_when_already_saved():
    job_matching.add_candidates([_job()], "src")
    storage.save_saved([{"company": "Acme", "title": "Backend Engineer", "link": "https://acme.example/jobs/1"}])
    assert job_matching.apply_to_applied_jobs(_job()) is False
    assert storage.load_applied() == []
    assert storage.load_matched()[0]["match_status"] == storage.MATCH_STATUS_NEW


def test_apply_to_applied_jobs_forced_copies_anyway_despite_the_conflict():
    job_matching.add_candidates([_job()], "src")
    storage.save_saved([{"company": "Acme", "title": "Backend Engineer", "link": "https://acme.example/jobs/1"}])
    assert job_matching.apply_to_applied_jobs(_job(), force=True) is True
    assert len(storage.load_applied()) == 1
    assert storage.load_matched()[0]["match_status"] == storage.MATCH_STATUS_APPLIED


def test_mark_status_from_reality_syncs_the_label_without_copying():
    job_matching.add_candidates([_job()], "src")
    storage.save_applied([{"company": "Acme", "title": "Backend Engineer", "link": "https://acme.example/jobs/1"}])
    assert job_matching.mark_status_from_reality(_job()) is True
    assert storage.load_saved() == []
    assert storage.load_matched()[0]["match_status"] == storage.MATCH_STATUS_APPLIED


def test_mark_status_from_reality_is_false_when_not_tracked_anywhere():
    job_matching.add_candidates([_job()], "src")
    assert job_matching.mark_status_from_reality(_job()) is False


# --- scoring ---------------------------------------------------------------

def test_score_matches_writes_scores_and_reports_errors(monkeypatch):
    storage.save_resume("Backend engineer, Python")
    job_matching.add_candidates([_job(), _job(company="Broken", link="https://b.example")], "src")

    def fake_analyze(resume, job, model=None):
        if job["company"] == "Broken":
            raise ollama_client.OllamaError("down")
        return {"fit_score": 9, "fit_notes": "strong"}

    monkeypatch.setattr(fit_analysis, "analyze", fake_analyze)
    errors = job_matching.score_matches(storage.load_matched())
    assert errors == ["Broken: down"]
    scores = {r["company"]: r["fit_score"] for r in storage.load_matched()}
    assert scores == {"Acme": 9, "Broken": None}


def test_score_matches_needs_a_resume():
    job_matching.add_candidates([_job()], "src")
    assert job_matching.score_matches(storage.load_matched())[0].startswith("Add your resume")


# --- gmail source ----------------------------------------------------------

def test_gmail_alert_candidates_extracts_fields_and_link(monkeypatch):
    storage.save_saved([{"company": "Tracked Co", "title": "x"}])
    seen = {}

    def fake_search(query, service=None, max_results=5):
        seen["query"] = query
        return [{"id": "m1", "subject": "Acme is hiring: Backend Engineer", "snippet": "..."}]

    monkeypatch.setattr(gmail_client, "search_messages", fake_search)
    monkeypatch.setattr(job_extract, "extract_opportunity_fields",
                        lambda s, sn: {"company": "Acme", "title": "Backend Engineer", "location": "", "salary": ""})
    monkeypatch.setattr(gmail_client, "get_message_link",
                        lambda mid, service=None, company="", title="": "https://www.linkedin.com/comm/jobs/view/9")

    candidates, errors = job_matching.gmail_alert_candidates(service=object())
    assert errors == []
    assert candidates[0]["link"] == "https://www.linkedin.com/comm/jobs/view/9"
    assert candidates[0]["source_detail"] == "Acme is hiring: Backend Engineer"
    assert '-subject:"Tracked Co"' in seen["query"]


def test_gmail_alert_candidates_keeps_going_without_a_link(monkeypatch):
    monkeypatch.setattr(gmail_client, "search_messages",
                        lambda q, service=None, max_results=5: [{"id": "m1", "subject": "s", "snippet": ""}])
    monkeypatch.setattr(job_extract, "extract_opportunity_fields",
                        lambda s, sn: {"company": "Acme", "title": "T", "location": "", "salary": ""})

    def boom(*a, **k):
        raise RuntimeError("body read failed")

    monkeypatch.setattr(gmail_client, "get_message_link", boom)
    candidates, _ = job_matching.gmail_alert_candidates(service=object())
    assert candidates[0]["link"] == ""


def test_search_queries_combine_titles_and_keywords():
    profile = {**storage.DEFAULT_MATCH_PROFILE, "titles": ["Backend Engineer", " "], "keywords": ["Python", "AI"]}
    assert job_matching.search_queries(profile) == ["Backend Engineer Python AI"]


# --- profile storage -------------------------------------------------------

def test_match_profile_defaults_and_roundtrip():
    assert storage.load_match_profile() == storage.DEFAULT_MATCH_PROFILE
    storage.save_match_profile({"titles": ["Backend Engineer"], "location": "Tel Aviv", "junk": 1})
    loaded = storage.load_match_profile()
    assert loaded["titles"] == ["Backend Engineer"] and loaded["location"] == "Tel Aviv"
    assert "junk" not in loaded and loaded["exclude_keywords"] == []


# --- SerpAPI client --------------------------------------------------------

SERP_PAYLOAD = {
    "jobs_results": [
        {
            "title": "Backend Engineer", "company_name": "Acme", "location": "Tel Aviv-Yafo, Israel",
            "via": "LinkedIn", "description": "Build distributed systems",
            "detected_extensions": {"salary": "₪30K–₪40K a month"},
            "apply_options": [
                {"title": "LinkedIn", "link": "https://www.linkedin.com/jobs/view/1"},
                {"title": "Acme Careers", "link": "https://acme.example/careers/1"},
            ],
        },
        {"title": "SRE", "company_name": "Beta", "share_link": "https://google.com/share/x"},
    ]
}


def test_parse_results_prefers_company_careers_link():
    first, second = job_search_client.parse_results(SERP_PAYLOAD, "backend engineer")
    assert first["link"] == "https://acme.example/careers/1"
    assert first["salary"] == "₪30K–₪40K a month"
    assert "backend engineer" in first["source_detail"] and "LinkedIn" in first["source_detail"]
    assert second["link"] == "https://google.com/share/x"


class _Resp:
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status

    def json(self):
        return self._payload


def test_search_jobs_requires_key(monkeypatch):
    monkeypatch.delenv(job_search_client.API_KEY_ENV_VAR, raising=False)
    with pytest.raises(job_search_client.JobSearchError):
        job_search_client.search_jobs("backend")


def test_search_jobs_sends_query_and_location(monkeypatch):
    monkeypatch.setenv(job_search_client.API_KEY_ENV_VAR, "k")
    captured = {}

    def fake_get(url, params=None, timeout=None):
        captured.update(params)
        return _Resp(SERP_PAYLOAD)

    monkeypatch.setattr(job_search_client.requests, "get", fake_get)
    results = job_search_client.search_jobs("Backend Engineer", "Tel Aviv, Israel")
    assert captured["engine"] == "google_jobs" and captured["location"] == "Tel Aviv, Israel"
    assert len(results) == 2


def test_search_jobs_no_results_is_empty_not_error(monkeypatch):
    monkeypatch.setenv(job_search_client.API_KEY_ENV_VAR, "k")
    monkeypatch.setattr(job_search_client.requests, "get",
                        lambda *a, **k: _Resp({"error": "Google hasn't returned any results for this query."}))
    assert job_search_client.search_jobs("zzz") == []


def test_search_jobs_api_error_raises(monkeypatch):
    monkeypatch.setenv(job_search_client.API_KEY_ENV_VAR, "k")
    monkeypatch.setattr(job_search_client.requests, "get", lambda *a, **k: _Resp({"error": "Invalid API key."}, 401))
    with pytest.raises(job_search_client.JobSearchError, match="Invalid API key"):
        job_search_client.search_jobs("backend")


# --- add_match.py ----------------------------------------------------------

def test_add_match_script_single_job():
    counts = add_match.main(["--source", "linkedin", "--company", "Acme", "--title", "Backend Engineer",
                             "--link", "https://www.linkedin.com/jobs/view/5/", "--detail", "LinkedIn: picks"])
    assert counts["added"] == 1
    [record] = storage.load_matched()
    assert record["source"] == storage.MATCH_SOURCE_LINKEDIN and record["source_detail"] == "LinkedIn: picks"


def test_add_match_script_json_file(tmp_path):
    path = tmp_path / "jobs.json"
    path.write_text(json.dumps([_job(), _job(company="B", link="b"), _job()]), encoding="utf-8")
    counts = add_match.main(["--source", "google", "--json", str(path)])
    assert counts["added"] == 2 and counts["already_tracked"] == 1
    assert {r["source"] for r in storage.load_matched()} == {storage.MATCH_SOURCE_GOOGLE_CLAUDE}
