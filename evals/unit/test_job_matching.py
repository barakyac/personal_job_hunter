import json

import pytest

from scripts import add_match, list_tracked, update_posting_status
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


# --- extract_required_years / passes_experience_filter ---------------------

@pytest.mark.parametrize("description,expected", [
    ("Looking for someone with 3+ years of backend experience.", 3),
    ("We'd like 3-5 years of relevant experience.", 3),
    ("3 to 5 years of relevant experience.", 3),
    ("4-6 years in a similar role.", 4),
    ("6+ years of hands-on backend work.", 6),
    ("2+ years of backend development.", 2),
    ("7+ years of backend development.", 7),
    ("At least 5 years of professional experience.", 5),
    ("Minimum of 5 years professional experience.", 5),
    # Real posting (Melio): leading-plus form - the "+" comes before the
    # digit, not after. A real regex gap this run caught: the original
    # patterns only recognized "5+ years", not "+5 years".
    ("+5 years of professional experience as a software engineer.", 5),
    ("5 years of experience in software development.", 5),
    ("", None),
    (None, None),
    ("A great team and a ping pong table.", None),
])
def test_extract_required_years_basic_shapes(description, expected):
    assert job_matching.extract_required_years(description) == expected


def test_extract_required_years_ignores_a_preferred_only_mention():
    text = "3+ years of Kubernetes experience preferred."
    assert job_matching.extract_required_years(text) is None


def test_extract_required_years_falls_back_to_a_required_mention_elsewhere():
    text = "2+ years of Kubernetes experience preferred. 5+ years of backend experience required."
    assert job_matching.extract_required_years(text) == 5


def test_extract_required_years_prefers_overall_over_tech_specific_in_same_sentence():
    # Real example (LSports posting): the headline figure is about the role
    # as a whole; the second figure is scoped to one named technology.
    text = ("Seasoned Developer: 6+ years of software development experience, "
            "with at least 5+ years focused on .NET Core/C#.")
    assert job_matching.extract_required_years(text) == 6


def test_extract_required_years_skips_a_lone_tech_specific_mention():
    text = "5+ years focused on Kubernetes administration."
    assert job_matching.extract_required_years(text) is None


def _profile(**overrides):
    return {**storage.DEFAULT_MATCH_PROFILE, **overrides}


def test_passes_experience_filter_always_true_when_no_bounds_set():
    candidate = {"description": "20+ years required."}
    assert job_matching.passes_experience_filter(candidate, _profile()) == (True, None, "")


@pytest.mark.parametrize("description,expected_years,expected_pass", [
    ("3+ years of experience.", 3, True),
    ("3-5 years of experience.", 3, True),
    ("4-6 years of experience.", 4, True),
    ("6+ years of experience.", 6, True),
    ("2+ years of experience.", 2, False),
    ("7+ years of experience.", 7, False),
])
def test_passes_experience_filter_inclusive_bounds(description, expected_years, expected_pass):
    profile = _profile(min_experience_years=3, max_experience_years=6)
    passes, years, reason = job_matching.passes_experience_filter({"description": description}, profile)
    assert (passes, years) == (expected_pass, expected_years)
    if not expected_pass:
        assert reason == "out_of_range"


def test_passes_experience_filter_reports_ambiguous_when_filter_active():
    profile = _profile(min_experience_years=3, max_experience_years=6)
    passes, years, reason = job_matching.passes_experience_filter({"description": "Great team culture."}, profile)
    assert (passes, years, reason) == (False, None, "ambiguous_or_missing")


def test_passes_experience_filter_only_min_set_is_open_ended_above():
    profile = _profile(min_experience_years=3, max_experience_years=None)
    assert job_matching.passes_experience_filter({"description": "20+ years of experience."}, profile)[0] is True
    assert job_matching.passes_experience_filter({"description": "1+ years of experience."}, profile)[0] is False


def test_passes_experience_filter_only_max_set_is_open_ended_below():
    profile = _profile(min_experience_years=None, max_experience_years=5)
    assert job_matching.passes_experience_filter({"description": "0+ years of experience."}, profile)[0] is True
    assert job_matching.passes_experience_filter({"description": "6+ years of experience."}, profile)[0] is False


def test_extract_required_years_counts_an_earlier_required_clause_despite_a_later_preferred_one():
    # Regression test: the preference-marker check used to run over the
    # whole sentence, so a trailing "preferred" clause disqualified an
    # earlier, clearly-required figure in the same sentence.
    text = "6+ years of backend experience required, with 2+ years of Kubernetes preferred."
    assert job_matching.extract_required_years(text) == 6


def test_passes_experience_filter_a_candidate_with_no_description_always_passes():
    # Gmail job-alert candidates never carry a description (see
    # gmail_alert_candidates) - unlike a real posting whose text just
    # doesn't mention years, there's no text here to judge at all, so this
    # must not be treated the same as "ambiguous_or_missing" (which would
    # silently drop every Gmail-sourced candidate once a filter is active).
    profile = _profile(min_experience_years=3, max_experience_years=6)
    assert job_matching.passes_experience_filter({}, profile) == (True, None, "")
    assert job_matching.passes_experience_filter({"description": ""}, profile) == (True, None, "")
    assert job_matching.passes_experience_filter({"description": "   "}, profile) == (True, None, "")


def test_add_candidates_does_not_drop_a_description_less_candidate_when_experience_filter_is_active():
    profile = _profile(min_experience_years=3, max_experience_years=6)
    counts = job_matching.add_candidates([_job(description="")], "src", profile)
    assert counts["added"] == 1
    assert counts["experience_filtered"] == 0 and counts["experience_unknown"] == 0
    assert storage.load_matched()[0]["required_years_min"] == ""


def test_add_candidates_applies_the_experience_filter_and_stamps_required_years():
    profile = _profile(min_experience_years=3, max_experience_years=6)
    counts = job_matching.add_candidates(
        [
            _job(link="a", description="3+ years of backend experience."),
            _job(company="Out", link="b", description="2+ years of backend experience."),
            _job(company="Unclear", link="c", description="Great ping pong table."),
        ],
        "src", profile,
    )
    assert counts["added"] == 1
    assert counts["experience_filtered"] == 1
    assert counts["experience_unknown"] == 1
    [record] = storage.load_matched()
    assert record["required_years_min"] == 3


def test_add_candidates_skips_experience_filter_entirely_when_not_configured():
    counts = job_matching.add_candidates(
        [_job(description="2+ years of backend experience.")], "src", storage.DEFAULT_MATCH_PROFILE,
    )
    assert counts["added"] == 1
    assert counts["experience_filtered"] == 0 and counts["experience_unknown"] == 0
    assert storage.load_matched()[0]["required_years_min"] == ""


# --- match profile: experience bounds persistence ---------------------------

def test_match_profile_experience_bounds_roundtrip():
    storage.save_match_profile({
        "titles": ["Backend Engineer"], "min_experience_years": 3, "max_experience_years": 6,
    })
    loaded = storage.load_match_profile()
    assert loaded["min_experience_years"] == 3
    assert loaded["max_experience_years"] == 6


def test_match_profile_experience_bounds_default_to_no_limit():
    assert storage.load_match_profile()["min_experience_years"] is None
    assert storage.load_match_profile()["max_experience_years"] is None


def test_existing_profile_without_experience_fields_has_no_filter():
    # Simulates a profile saved before this feature existed.
    storage.save_match_profile({"titles": ["Backend Engineer"], "location": "Tel Aviv"})
    loaded = storage.load_match_profile()
    assert loaded["min_experience_years"] is None
    assert loaded["max_experience_years"] is None


def test_match_profile_min_fit_score_roundtrip():
    storage.save_match_profile({"titles": ["Backend Engineer"], "min_fit_score": 6})
    assert storage.load_match_profile()["min_fit_score"] == 6


def test_match_profile_min_fit_score_defaults_to_no_limit():
    assert storage.load_match_profile()["min_fit_score"] is None


# --- add_candidates --------------------------------------------------------

def test_add_candidates_appends_new_with_defaults():
    # No resume is configured in this test, so the auto-score pass that
    # add_candidates now runs on every newly added, not-yet-scored match
    # short-circuits with this one message instead of calling Ollama.
    # MATCH_SOURCE_GOOGLE (SerpAPI) is never opened before being added -
    # see test_add_candidates_stamps_open_only_for_a_verified_source below
    # for the one source where "confirmed open" is actually true.
    counts = job_matching.add_candidates([_job()], storage.MATCH_SOURCE_GOOGLE)
    assert counts == {
        "added": 1, "already_tracked": 0, "filtered": 0, "invalid": 0,
        "experience_filtered": 0, "experience_unknown": 0,
        "score_errors": ["Add your resume on the Profile page first - fit is scored against it."],
    }
    [record] = storage.load_matched()
    assert record["source"] == storage.MATCH_SOURCE_GOOGLE
    assert record["match_status"] == storage.MATCH_STATUS_NEW
    assert record["date_found"]
    assert set(storage.MATCHED_COLUMNS) <= set(record)
    # Nobody actually opened this posting before adding it (it came from a
    # search API, not the skill browsing LinkedIn) - stamping it Open would
    # be a guess apply_posting_check()'s no-downgrade rule would then
    # protect forever, so it's Unknown until a real re-check happens.
    assert record["posting_status"] == storage.POSTING_STATUS_UNKNOWN
    assert not record["posting_checked_at"]


def test_add_candidates_stamps_open_only_for_a_verified_source():
    # The find-matching-jobs skill (Claude in Chrome) is the only path that
    # actually opens a posting and confirms it's still accepting
    # applications before adding it - see .claude/skills/find-matching-jobs
    # step 7. Only its two sources get a real "confirmed open" default.
    counts = job_matching.add_candidates([_job()], storage.MATCH_SOURCE_LINKEDIN)
    assert counts["added"] == 1
    [record] = storage.load_matched()
    assert record["posting_status"] == storage.POSTING_STATUS_OPEN
    assert record["posting_checked_at"]


def test_add_candidates_leaves_an_explicit_posting_status_alone():
    counts = job_matching.add_candidates(
        [_job(posting_status=storage.POSTING_STATUS_CLOSED)], storage.MATCH_SOURCE_LINKEDIN
    )
    assert counts["added"] == 1
    [record] = storage.load_matched()
    assert record["posting_status"] == storage.POSTING_STATUS_CLOSED


def test_add_candidates_auto_scores_new_matches_against_the_resume(monkeypatch):
    storage.save_resume("Experienced backend engineer.")
    monkeypatch.setattr(
        fit_analysis, "analyze", lambda resume, job, model=None: {"fit_score": 8, "fit_notes": "Great fit."}
    )
    counts = job_matching.add_candidates([_job()], "src")
    assert counts["score_errors"] == []
    [record] = storage.load_matched()
    assert record["fit_score"] == 8
    assert record["fit_notes"] == "Great fit."


def test_add_candidates_does_not_rescore_a_candidate_that_already_has_a_fit_score(monkeypatch):
    storage.save_resume("Experienced backend engineer.")
    analyze_calls = []
    monkeypatch.setattr(
        fit_analysis, "analyze",
        lambda resume, job, model=None: analyze_calls.append(job) or {"fit_score": 1, "fit_notes": "x"},
    )
    job_matching.add_candidates([_job(fit_score=9, fit_notes="pre-scored")], "src")
    assert analyze_calls == []
    [record] = storage.load_matched()
    assert record["fit_score"] == 9
    assert record["fit_notes"] == "pre-scored"


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


def test_same_company_and_title_but_a_different_real_link_is_a_new_match():
    # Regression guard: find_tracked() used to treat any company+title
    # match as a certain duplicate, even when both postings carry a real,
    # different link - silently dropping a second open role with the same
    # title at the same company (the thing tracked_identities()'s own
    # docstring says is only a "possible" duplicate, not a certain one).
    job_matching.add_candidates([_job(link="https://acme.example/jobs/1")], "src")
    counts = job_matching.add_candidates([_job(link="https://acme.example/jobs/2")], "src")
    assert counts["added"] == 1
    assert counts["already_tracked"] == 0
    assert len(storage.load_matched()) == 2


def test_dismissed_match_is_not_re_added():
    job_matching.add_candidates([_job()], "src")
    job_matching.set_status(_job(), storage.MATCH_STATUS_DISMISSED)
    counts = job_matching.add_candidates([_job()], "src")
    assert counts["already_tracked"] == 1


def test_exclude_keywords_filter_title_only():
    profile = {**storage.DEFAULT_MATCH_PROFILE, "exclude_keywords": ["Frontend"]}
    counts = job_matching.add_candidates(
        [_job(title="Frontend Engineer", link="a"), _job(company="C", link="c")],
        "src", profile,
    )
    assert counts["filtered"] == 1 and counts["added"] == 1


def test_exclude_keywords_do_not_match_an_incidental_description_mention():
    # Regression guard: this used to exclude a posting just because its
    # description happened to mention "the Team Lead" or "a Senior member
    # of the team" in passing - not because the role itself was senior or
    # a team-lead position. See job_matching.passes_profile_filters.
    profile = {**storage.DEFAULT_MATCH_PROFILE, "exclude_keywords": ["Senior", "Team Lead"]}
    counts = job_matching.add_candidates(
        [_job(title="Backend Engineer", link="a",
              description="Take ownership of tasks, with guidance from the Team Lead."),
         _job(company="B", title="Backend Engineer", link="b",
              description="Mentor Jr engineers as a Senior member of the team.")],
        "src", profile,
    )
    assert counts["filtered"] == 0 and counts["added"] == 2


def test_candidate_without_company_or_link_is_invalid():
    counts = job_matching.add_candidates([{"title": "Engineer"}], "src")
    assert counts["invalid"] == 1
    assert storage.load_matched() == []


def test_candidate_with_only_a_company_is_invalid():
    # Regression guard: a candidate with a company but no title and no
    # link used to be accepted. Two such candidates are indistinguishable
    # to find_tracked()/_row_key (same empty identity, no link) - on the
    # Matching Jobs page that collided into the same Streamlit widget key
    # and crashed the whole page, rather than merely being unscoreable.
    counts = job_matching.add_candidates([{"company": "Acme"}], "src")
    assert counts["invalid"] == 1
    assert storage.load_matched() == []


# --- save / status ---------------------------------------------------------

def test_save_to_saved_jobs_copies_and_marks_saved():
    job_matching.add_candidates(
        [_job(fit_score=8, fit_notes="good", source_detail="LinkedIn: picks")], storage.MATCH_SOURCE_LINKEDIN
    )
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


# --- tracked_identities (pre-browse dedup) ----------------------------------

def test_tracked_identities_covers_all_three_buckets():
    job_matching.add_candidates([_job()], "src")
    storage.save_saved([{"company": "S Co", "title": "SRE", "link": "https://s.example/1"}])
    storage.save_applied([{"company": "A Co", "title": "QA", "link": "https://a.example/1"}])

    rows = job_matching.tracked_identities()
    assert {(r["where"], r["company"]) for r in rows} == {
        ("matched", "Acme"), ("saved", "S Co"), ("applied", "A Co"),
    }


def test_tracked_identities_canonical_link_matches_the_authoritative_dedup():
    job_matching.add_candidates(
        [_job(link="https://www.linkedin.com/comm/jobs/view/42?trk=x")], "src"
    )
    [row] = job_matching.tracked_identities()
    assert row["canonical_link"] == job_matching.canonical_link("https://www.linkedin.com/jobs/view/42/")


# --- apply_posting_check (unknown-availability + non-regression) -----------

def test_apply_posting_check_records_a_confirmed_open():
    record = {}
    job_matching.apply_posting_check(record, "open", "2026-11-26")
    assert record == {"posting_status": storage.POSTING_STATUS_OPEN, "posting_checked_at": "2026-11-26"}


def test_apply_posting_check_records_a_confirmed_closed():
    record = {"posting_status": storage.POSTING_STATUS_OPEN, "posting_checked_at": "2026-11-20"}
    job_matching.apply_posting_check(record, "closed", "2026-11-26")
    assert record["posting_status"] == storage.POSTING_STATUS_CLOSED
    assert record["posting_checked_at"] == "2026-11-26"


def test_apply_posting_check_sets_unknown_when_nothing_was_ever_confirmed():
    record = {}
    job_matching.apply_posting_check(record, None, "2026-11-26")
    assert record == {"posting_status": storage.POSTING_STATUS_UNKNOWN, "posting_checked_at": "2026-11-26"}


def test_apply_posting_check_never_downgrades_a_confirmed_open_to_unknown():
    record = {"posting_status": storage.POSTING_STATUS_OPEN, "posting_checked_at": "2026-11-20"}
    job_matching.apply_posting_check(record, None, "2026-11-26")
    # A failed check (sign-in wall, CAPTCHA, timeout) must never overwrite
    # an earlier real confirmation, or its timestamp - a later failure
    # proves nothing about whether the earlier confirmation still holds.
    assert record["posting_status"] == storage.POSTING_STATUS_OPEN
    assert record["posting_checked_at"] == "2026-11-20"


def test_apply_posting_check_never_downgrades_a_confirmed_closed_to_unknown():
    record = {"posting_status": storage.POSTING_STATUS_CLOSED, "posting_checked_at": "2026-11-20"}
    job_matching.apply_posting_check(record, None, "2026-11-26")
    assert record["posting_status"] == storage.POSTING_STATUS_CLOSED
    assert record["posting_checked_at"] == "2026-11-20"


def test_save_to_saved_jobs_preserves_a_non_open_posting_status():
    # Regression guard: this used to hard-code "Open for applications" on
    # every save, silently erasing a real Closed/Unknown confirmation the
    # moment the user saved the match.
    job_matching.add_candidates([_job()], "src")
    records = storage.load_matched()
    job_matching.apply_posting_check(records[0], "closed", "2026-11-20")
    storage.save_matched(records)

    assert job_matching.save_to_saved_jobs(_job()) is True
    [saved] = storage.load_saved()
    assert saved["posting_status"] == storage.POSTING_STATUS_CLOSED
    assert saved["posting_checked_at"] == "2026-11-20"


# --- scripts/list_tracked.py, scripts/update_posting_status.py -------------

def test_list_tracked_script_runs_without_error(capsys):
    job_matching.add_candidates([_job()], "src")
    list_tracked.main()
    out = capsys.readouterr().out
    assert "Acme" in out and "1 tracked posting" in out


def test_list_tracked_script_handles_nothing_tracked(capsys):
    list_tracked.main()
    assert "Nothing tracked yet." in capsys.readouterr().out


def test_update_posting_status_script_updates_matched():
    job_matching.add_candidates([_job()], "src")
    update_posting_status.main(["matched", "--company", "Acme", "--title", "Backend Engineer", "--result", "closed"])
    [record] = storage.load_matched()
    assert record["posting_status"] == storage.POSTING_STATUS_CLOSED
    assert record["posting_checked_at"]


def test_update_posting_status_script_unknown_never_overwrites_a_confirmed_status(capsys):
    job_matching.add_candidates([_job()], storage.MATCH_SOURCE_LINKEDIN)  # stamped Open at add time
    update_posting_status.main(["matched", "--company", "Acme", "--title", "Backend Engineer", "--result", "unknown"])
    [record] = storage.load_matched()
    assert record["posting_status"] == storage.POSTING_STATUS_OPEN
    assert "never overwrites" in capsys.readouterr().out


def test_update_posting_status_script_reports_no_match(capsys):
    update_posting_status.main(["matched", "--company", "Nobody", "--result", "open"])
    assert "Nothing updated" in capsys.readouterr().out
    assert storage.load_matched() == []


def test_update_posting_status_script_matches_a_canonically_equal_link():
    # Regression test: a plain `==` link match would miss this - the stored
    # link carries no tracking params, but the one passed in does, exactly
    # the shape list_tracked.py's own canonical_link output vs. a raw
    # LinkedIn/Gmail link can differ by.
    job_matching.add_candidates([_job(link="https://acme.example/jobs/1")], "src")
    update_posting_status.main([
        "matched", "--company", "Acme",
        "--link", "https://acme.example/jobs/1?utm_source=linkedin&trk=abc", "--result", "closed",
    ])
    [record] = storage.load_matched()
    assert record["posting_status"] == storage.POSTING_STATUS_CLOSED


def test_update_posting_status_script_updates_saved():
    # The "saved" kind (shown as a worked example in the script's own
    # docstring) had no coverage at all - unlike "matched", every other
    # test here exercised.
    storage.save_saved([{"company": "Acme", "title": "Backend Engineer", "link": "https://acme.example/jobs/1"}])
    update_posting_status.main(["saved", "--company", "Acme", "--title", "Backend Engineer", "--result", "closed"])
    [record] = storage.load_saved()
    assert record["posting_status"] == storage.POSTING_STATUS_CLOSED
    assert record["posting_checked_at"]


def test_update_posting_status_script_unknown_never_overwrites_a_confirmed_status_for_saved(capsys):
    storage.save_saved([{
        "company": "Acme", "title": "Backend Engineer", "link": "https://acme.example/jobs/1",
        "posting_status": storage.POSTING_STATUS_OPEN, "posting_checked_at": "2026-11-20",
    }])
    update_posting_status.main(["saved", "--company", "Acme", "--title", "Backend Engineer", "--result", "unknown"])
    [record] = storage.load_saved()
    assert record["posting_status"] == storage.POSTING_STATUS_OPEN
    assert record["posting_checked_at"] == "2026-11-20"
    assert "never overwrites" in capsys.readouterr().out


def test_update_posting_status_script_refuses_to_guess_when_link_matches_nothing():
    # Regression guard: a --link that doesn't match any tracked posting
    # used to silently fall back to company(+title), which could stamp a
    # company's *other* tracked posting with the result meant for an
    # untracked one.
    job_matching.add_candidates([_job(link="https://acme.example/jobs/1")], "src")
    update_posting_status.main([
        "matched", "--company", "Acme", "--link", "https://acme.example/jobs/999-different", "--result", "closed",
    ])
    [record] = storage.load_matched()
    assert record["posting_status"] != storage.POSTING_STATUS_CLOSED


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


def test_save_to_saved_jobs_forced_refuses_an_applied_job_even_so():
    # Regression guard: Applied -> Saved is a backward stage move. force=True
    # must not be able to override that - only mark_status_from_reality()
    # (sync the label, no copy) resolves this conflict.
    job_matching.add_candidates([_job()], "src")
    storage.save_applied([{"company": "Acme", "title": "Backend Engineer", "link": "https://acme.example/jobs/1"}])
    assert job_matching.save_to_saved_jobs(_job(), force=True) is False
    assert storage.load_saved() == []
    assert storage.load_matched()[0]["match_status"] == storage.MATCH_STATUS_NEW


def test_apply_to_applied_jobs_does_not_copy_or_relabel_when_already_saved():
    job_matching.add_candidates([_job()], "src")
    storage.save_saved([{"company": "Acme", "title": "Backend Engineer", "link": "https://acme.example/jobs/1"}])
    assert job_matching.apply_to_applied_jobs(_job()) is False
    assert storage.load_applied() == []
    assert storage.load_matched()[0]["match_status"] == storage.MATCH_STATUS_NEW


def test_apply_to_applied_jobs_forced_moves_the_saved_record_instead_of_duplicating():
    # Regression guard: forcing Saved -> Applied used to leave the old
    # Saved Jobs record in place while also adding an Applied one, so the
    # same real job ended up tracked in both buckets at once.
    job_matching.add_candidates([_job()], "src")
    storage.save_saved([{"company": "Acme", "title": "Backend Engineer", "link": "https://acme.example/jobs/1"}])
    assert job_matching.apply_to_applied_jobs(_job(), force=True) is True
    assert len(storage.load_applied()) == 1
    assert storage.load_saved() == []
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


def test_set_status_rejects_an_unknown_status():
    # Regression guard: set_status used to write any string straight into
    # match_status with no validation against storage.MATCH_STATUS_OPTIONS
    # - the never-backward/never-arbitrary invariant held only because of
    # which call sites happened to use it, not because the function itself
    # enforced anything.
    job_matching.add_candidates([_job()], "src")
    with pytest.raises(ValueError):
        job_matching.set_status(_job(), "Not a real status")
    assert storage.load_matched()[0]["match_status"] == storage.MATCH_STATUS_NEW


# --- scoring ---------------------------------------------------------------

def test_score_matches_writes_scores_and_reports_errors(monkeypatch):
    storage.save_resume("Backend engineer, Python")

    def fake_analyze(resume, job, model=None):
        if job["company"] == "Broken":
            raise ollama_client.OllamaError("down")
        return {"fit_score": 9, "fit_notes": "strong"}

    # Patched before add_candidates, not after - add_candidates now
    # auto-scores every new, not-yet-scored match itself, so this fake
    # needs to be in place for that first pass too, not just the explicit
    # score_matches call below.
    monkeypatch.setattr(fit_analysis, "analyze", fake_analyze)
    job_matching.add_candidates([_job(), _job(company="Broken", link="https://b.example")], "src")

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
    # Regression guard: a failed link lookup for one message (API error,
    # malformed payload) used to be swallowed into the exact same `link ==
    # ""` as a genuine "no link in this body", with no trace anywhere -
    # the candidate still needs to be added (so one bad message doesn't
    # stop the whole scan), but the failure must be reported, not hidden.
    monkeypatch.setattr(gmail_client, "search_messages",
                        lambda q, service=None, max_results=5: [{"id": "m1", "subject": "s", "snippet": ""}])
    monkeypatch.setattr(job_extract, "extract_opportunity_fields",
                        lambda s, sn: {"company": "Acme", "title": "T", "location": "", "salary": ""})

    def boom(*a, **k):
        raise RuntimeError("body read failed")

    monkeypatch.setattr(gmail_client, "get_message_link", boom)
    candidates, errors = job_matching.gmail_alert_candidates(service=object())
    assert candidates[0]["link"] == ""
    assert any("body read failed" in e for e in errors)


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


def test_search_jobs_rejects_a_non_object_payload(monkeypatch):
    # Regression guard: valid JSON that parses to a non-dict (a bare list,
    # here) used to reach payload.get("error") and raise an unhandled
    # AttributeError instead of JobSearchError - crashing the whole
    # Matching Jobs page instead of showing a per-query st.warning.
    monkeypatch.setenv(job_search_client.API_KEY_ENV_VAR, "k")
    monkeypatch.setattr(job_search_client.requests, "get", lambda *a, **k: _Resp(["unexpected", "list"]))
    with pytest.raises(job_search_client.JobSearchError):
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


def test_add_match_script_reports_experience_filter_outcomes(tmp_path, capsys):
    # Regression guard: the CLI report used to silently omit these two
    # counts even though add_candidates() already tracked them - a live run
    # looked like "0 added, nothing else to explain" instead of naming why.
    storage.save_match_profile(
        {**storage.DEFAULT_MATCH_PROFILE, "min_experience_years": 3, "max_experience_years": 6}
    )
    path = tmp_path / "jobs.json"
    path.write_text(json.dumps([
        _job(link="a", description="2+ years of backend experience."),
        _job(company="B", link="b", description="Great ping pong table."),
    ]), encoding="utf-8")

    add_match.main(["--source", "linkedin", "--json", str(path)])

    out = capsys.readouterr().out
    assert "1 outside the required-experience range" in out
    assert "1 with unclear required experience" in out
