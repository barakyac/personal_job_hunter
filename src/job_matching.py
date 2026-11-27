"""Matching Jobs: collect candidate postings from several sources into one
list (data/matched_jobs.json), skip anything already tracked, score each
against the resume, and let the user promote a match to Saved Jobs or
dismiss it.

Sources:
- Gmail job-alert emails (LinkedIn Job Alerts / Glassdoor) - the closest the
  app itself can get to LinkedIn's own "jobs that match your profile",
  since LinkedIn's recommendations page needs a signed-in browser.
- Google Jobs via SerpAPI (src/job_search_client.py).
- Claude browsing LinkedIn/Google in the user's own Chrome, adding matches
  with scripts/add_match.py (see .claude/skills/find-matching-jobs).

Everything here works on plain dicts and goes through storage, so the view
and the CLI script share one code path.
"""

import datetime as dt
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from src import fit_analysis, gmail_client, job_extract, ollama_client, storage

# LinkedIn job links come in several shapes for the same posting
# (/jobs/view/<id>/, /comm/jobs/view/<id>?trackingId=..., ?currentJobId=<id>
# on the recommendations page). The numeric id is the only stable part.
_LINKEDIN_JOB_ID_RE = re.compile(r"linkedin\.com/(?:comm/)?jobs/view/(?:[^/?#]*-)?(\d+)", re.IGNORECASE)
_LINKEDIN_CURRENT_JOB_RE = re.compile(r"[?&]currentJobId=(\d+)", re.IGNORECASE)

# Query params that only track where a click came from - never part of
# which posting a link points at.
_TRACKING_PARAMS = {"trackingid", "refid", "trk", "utm_source", "utm_medium", "utm_campaign", "utm_term",
                    "utm_content", "lipi", "midtoken", "midsig", "eid", "otptoken", "ref", "src", "source"}

# A years-of-experience mention near any of these words is a preference,
# not a requirement - "3+ years preferred" must never count as what the
# posting requires.
_EXPERIENCE_PREFERENCE_MARKERS_RE = re.compile(
    r"\b(preferred|nice[\s-]to[\s-]have|a\s+plus|is\s+a\s+plus|bonus|desirable|ideally|advantage)\b",
    re.IGNORECASE,
)
# A years-of-experience mention near any of these is scoped to one named
# technology, not the posting's overall requirement - "5+ years focused on
# .NET Core/C#" is about .NET, not the role as a whole.
_EXPERIENCE_TECH_SCOPE_MARKERS_RE = re.compile(
    r"\bfocused on\b|\bspecifically (?:in|with)\b|\bexperience (?:with|in|using)\s+[A-Z]",
)
# Matches the shapes postings actually use for a required-years figure:
# "5+ years", "3-5 years"/"3 to 5 years" (only the lower bound matters -
# see extract_required_years), "minimum of 5 years"/"at least 5 years", and
# a plain "5 years" as a fallback for postings that drop the "+".
_EXPERIENCE_YEARS_PATTERNS = [
    re.compile(r"(\d{1,2})\s*\+\s*years?", re.IGNORECASE),           # "5+ years"
    re.compile(r"\+\s*(\d{1,2})\s*years?", re.IGNORECASE),           # "+5 years" (leading plus)
    re.compile(r"(\d{1,2})\s*(?:-|–|to)\s*(\d{1,2})\s*\+?\s*years?", re.IGNORECASE),
    re.compile(r"(?:minimum(?:\s+of)?|at least|min\.?)\s*(\d{1,2})\s*years?", re.IGNORECASE),
    re.compile(r"(\d{1,2})\s*years?\s+of\s+experience", re.IGNORECASE),
]
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.;\n])\s+")


def canonical_link(link: str) -> str:
    """A comparable form of a job link, so the same posting found by two
    sources (a Gmail alert's /comm/ tracking link and Claude's /jobs/view/
    link, say) is recognized as one."""
    link = (link or "").strip()
    if not link:
        return ""
    match = _LINKEDIN_JOB_ID_RE.search(link) or _LINKEDIN_CURRENT_JOB_RE.search(link)
    if match and "linkedin.com" in link.lower():
        return f"https://www.linkedin.com/jobs/view/{match.group(1)}/"
    parts = urlsplit(link)
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query) if k.lower() not in _TRACKING_PARAMS])
    host = parts.netloc.lower().removeprefix("www.")
    return urlunsplit((parts.scheme.lower() or "https", host, parts.path.rstrip("/"), query, ""))


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _identity(record: dict) -> tuple[str, str]:
    return _norm(record.get("company", "")), _norm(record.get("title", ""))


def find_tracked(candidate: dict, matched: list[dict] | None = None) -> str | None:
    """Where this candidate already lives: "saved", "applied", "matched", or
    None. Matches by canonical link first, then by company + title (a
    company alone isn't enough - one company often has several open roles
    worth seeing separately)."""
    link = canonical_link(candidate.get("link", ""))
    identity = _identity(candidate)
    has_identity = all(identity)
    groups = [
        ("saved", storage.load_saved()),
        ("applied", storage.load_applied()),
        ("matched", storage.load_matched() if matched is None else matched),
    ]
    for where, records in groups:
        for r in records:
            if link and canonical_link(r.get("link", "")) == link:
                return where
            if has_identity and _identity(r) == identity:
                return where
    return None


def tracked_identities() -> list[dict]:
    """Every already-tracked posting (Matching Jobs, Saved Jobs, Applied
    Positions) as a light {where, company, title, link, canonical_link} row
    - for the find-matching-jobs skill to check a search-results listing
    against *before* spending time opening each card. A canonical_link match
    is a certain duplicate (the same posting, however it was found); a
    company+title match alone is only a possible one, since one company can
    open more than one role with the same title. This never decides
    anything on its own - add_candidates()/find_tracked() still run their
    own check at write time and are the real authority."""
    rows = []
    for where, records in (
        ("matched", storage.load_matched()),
        ("saved", storage.load_saved()),
        ("applied", storage.load_applied()),
    ):
        for r in records:
            rows.append({
                "where": where,
                "company": r.get("company", ""),
                "title": r.get("title", ""),
                "link": r.get("link", ""),
                "canonical_link": canonical_link(r.get("link", "")),
            })
    return rows


def _clean_candidate(candidate: dict, source: str) -> dict:
    record = {col: "" for col in storage.MATCHED_COLUMNS}
    for col in storage.MATCHED_COLUMNS:
        value = candidate.get(col)
        if value is not None:
            record[col] = value.strip() if isinstance(value, str) else value
    record["source"] = record["source"] or source
    record["date_found"] = record["date_found"] or dt.date.today().isoformat()
    record["match_status"] = storage.MATCH_STATUS_NEW
    record["fit_score"] = candidate.get("fit_score")
    # A candidate only ever reaches here because whoever found it checked
    # the posting was open (the find-matching-jobs skill skips closed ones
    # outright) - so this is a real confirmation, not a default/guess.
    record["posting_status"] = record["posting_status"] or storage.POSTING_STATUS_OPEN
    record["posting_checked_at"] = record["posting_checked_at"] or dt.date.today().isoformat()
    return record


def extract_required_years(description: str) -> int | None:
    """The posting's stated *overall* required minimum years of experience,
    or None when it isn't stated or isn't clear enough to say. Deliberately
    narrow, not a general NLP reading of the posting:

    - Only counts a mention sentence-scoped away from preference markers
      ("preferred", "nice to have", "a plus", ...) - those describe what's
      wanted, not what's required.
    - Only counts a mention not locally scoped to one named technology
      ("5+ years focused on .NET Core/C#" is about .NET, not the role as a
      whole) - checked in a window around the match, not the whole
      sentence, so an earlier *overall* figure in the same sentence (as in
      "6+ years of software development experience, with at least 5+ years
      focused on .NET Core/C#") is still counted even though a later
      clause in that same sentence is tech-scoped.
    - For a range ("3-5 years"), only the lower bound is used - see
      job_matching's callers for why (the configured bounds compare against
      the posting's minimum, not its maximum).
    - Picks whichever qualifying mention appears first in reading order,
      on the assumption postings state the headline requirement before any
      narrower caveat.
    """
    if not description:
        return None
    best_years, best_pos, offset = None, None, 0
    for sentence in _SENTENCE_SPLIT_RE.split(description):
        sentence_start = offset
        offset += len(sentence) + 1
        if _EXPERIENCE_PREFERENCE_MARKERS_RE.search(sentence):
            continue
        for pattern in _EXPERIENCE_YEARS_PATTERNS:
            for m in pattern.finditer(sentence):
                window = sentence[max(0, m.start() - 60):m.end() + 20]
                if _EXPERIENCE_TECH_SCOPE_MARKERS_RE.search(window):
                    continue
                absolute_pos = sentence_start + m.start()
                if best_pos is None or absolute_pos < best_pos:
                    best_years, best_pos = int(m.group(1)), absolute_pos
    return best_years


def passes_experience_filter(candidate: dict, profile: dict) -> tuple[bool, int | None, str]:
    """Whether a candidate's stated required experience fits the profile's
    configured (min, max) years bounds, inclusively. Returns (passes,
    required_years, reason) - reason is only meaningful when passes is
    False, for the caller to report *why*:

    - "" when there's no active filter (both bounds unset) - always passes.
    - "out_of_range" when a required-years figure was found but falls
      outside the configured bounds.
    - "ambiguous_or_missing" when the filter is active but the posting's
      required years couldn't be determined - never silently included or
      silently dropped without a reason, since neither "assume it fits"
      nor "assume it doesn't" is actually true here.
    """
    min_years = profile.get("min_experience_years")
    max_years = profile.get("max_experience_years")
    if min_years is None and max_years is None:
        return True, None, ""
    required = extract_required_years(candidate.get("description", ""))
    if required is None:
        return False, None, "ambiguous_or_missing"
    lo = min_years if min_years is not None else 0
    hi = max_years if max_years is not None else float("inf")
    if lo <= required <= hi:
        return True, required, ""
    return False, required, "out_of_range"


def passes_profile_filters(candidate: dict, profile: dict) -> bool:
    """Drop a candidate whose title hits one of the profile's exclude
    keywords (e.g. "senior", "frontend", "team lead"). Title-only,
    deliberately: a description is full of incidental mentions that don't
    describe the role itself (a Backend Engineer posting that happens to
    say "reports to the Team Lead", or "mentor Jr engineers as a Senior
    member of the team") - matching against the whole text excluded
    otherwise-good, in-range candidates on exactly this kind of false
    positive."""
    excludes = [_norm(k) for k in profile.get("exclude_keywords", []) if _norm(k)]
    if not excludes:
        return True
    haystack = _norm(candidate.get("title", ""))
    return not any(k in haystack for k in excludes)


def add_candidates(candidates: list[dict], source: str, profile: dict | None = None) -> dict:
    """Append new candidates to matched_jobs.json, then immediately fit-score
    whichever of them don't already carry a score, so a match never sits
    unscored just because no one has clicked "Score fit" yet. Returns
    counts: {"added": n, "already_tracked": n, "filtered": n, "invalid": n,
    "experience_filtered": n, "experience_unknown": n, "score_errors": [...]}.
    A candidate needs at least a company or a link to be kept."""
    profile = profile if profile is not None else storage.load_match_profile()
    matched = storage.load_matched()
    counts = {
        "added": 0, "already_tracked": 0, "filtered": 0, "invalid": 0,
        "experience_filtered": 0, "experience_unknown": 0, "score_errors": [],
    }
    added_records = []
    for raw in candidates:
        if not (raw.get("company") or "").strip() and not (raw.get("link") or "").strip():
            counts["invalid"] += 1
            continue
        if find_tracked(raw, matched):
            counts["already_tracked"] += 1
            continue
        if not passes_profile_filters(raw, profile):
            counts["filtered"] += 1
            continue
        exp_ok, required_years, exp_reason = passes_experience_filter(raw, profile)
        if not exp_ok:
            counts["experience_unknown" if exp_reason == "ambiguous_or_missing" else "experience_filtered"] += 1
            continue
        record = _clean_candidate(raw, source)
        if required_years is not None:
            record["required_years_min"] = required_years
        matched.append(record)
        added_records.append(record)
        counts["added"] += 1
    if counts["added"]:
        storage.save_matched(matched)
        unscored = [r for r in added_records if r.get("fit_score") in (None, "")]
        if unscored:
            counts["score_errors"] = score_matches(unscored)
    return counts


def _find_index(records: list[dict], record: dict) -> int | None:
    link = canonical_link(record.get("link", ""))
    for i, r in enumerate(records):
        if link and canonical_link(r.get("link", "")) == link:
            return i
    identity = _identity(record)
    for i, r in enumerate(records):
        if _identity(r) == identity:
            return i
    return None


def apply_posting_check(record: dict, confirmed: str | None, checked_at: str) -> None:
    """Write the outcome of checking whether a posting is still open, in
    place on `record`. `confirmed` is "open", "closed", or None (the check
    failed - sign-in wall, CAPTCHA, timeout, couldn't tell). A failed check
    only ever sets Unknown when there's no existing Open/Closed confirmation
    to protect - it never downgrades one, and never bumps its timestamp, so
    a real prior confirmation always outranks a later failed attempt."""
    if confirmed == "open":
        record["posting_status"] = storage.POSTING_STATUS_OPEN
        record["posting_checked_at"] = checked_at
    elif confirmed == "closed":
        record["posting_status"] = storage.POSTING_STATUS_CLOSED
        record["posting_checked_at"] = checked_at
    elif record.get("posting_status") not in (storage.POSTING_STATUS_OPEN, storage.POSTING_STATUS_CLOSED):
        record["posting_status"] = storage.POSTING_STATUS_UNKNOWN
        record["posting_checked_at"] = checked_at


def set_status(record: dict, status: str) -> bool:
    records = storage.load_matched()
    idx = _find_index(records, record)
    if idx is None:
        return False
    records[idx]["match_status"] = status
    storage.save_matched(records)
    return True


def tracked_elsewhere(record: dict) -> str | None:
    """Where this match is already tracked - "saved" or "applied" - or None
    if it isn't tracked anywhere yet. The view checks this before calling
    save_to_saved_jobs/apply_to_applied_jobs, so it can put the choice to
    the user (via a dialog) instead of those functions silently deciding
    anything on their own."""
    records = storage.load_matched()
    idx = _find_index(records, record)
    if idx is None:
        return None
    match = records[idx]
    others = [r for i, r in enumerate(records) if i != idx]
    where = find_tracked(match, matched=others)
    return where if where in ("saved", "applied") else None


def mark_status_from_reality(record: dict) -> bool:
    """Correct a match's status tag to reflect where it's actually already
    tracked (Saved or Applied), without copying or duplicating anything.
    This is the "keep it where it is" choice when the user resolves a
    tracked_elsewhere conflict."""
    records = storage.load_matched()
    idx = _find_index(records, record)
    if idx is None:
        return False
    match = records[idx]
    others = [r for i, r in enumerate(records) if i != idx]
    where = find_tracked(match, matched=others)
    if where not in ("saved", "applied"):
        return False
    records[idx]["match_status"] = storage.MATCH_STATUS_SAVED if where == "saved" else storage.MATCH_STATUS_APPLIED
    storage.save_matched(records)
    return True


def save_to_saved_jobs(record: dict, force: bool = False) -> bool:
    """Copy a match into Saved Jobs (keeping its description and fit
    score, so "Calculate fit" there doesn't redo the work) and mark the
    match Saved. Writes and changes nothing, returning False, when the
    posting is already tracked (Saved or Applied) and `force` isn't set -
    the caller must have checked tracked_elsewhere() first and let the
    user decide, via mark_status_from_reality() or force=True, rather than
    this guessing on its own."""
    records = storage.load_matched()
    idx = _find_index(records, record)
    if idx is None:
        return False
    match = records[idx]
    others = [r for i, r in enumerate(records) if i != idx]
    where = find_tracked(match, matched=others)
    if where in ("saved", "applied") and not force:
        return False

    saved = storage.load_saved()
    source_line = f"Found via {match.get('source', '')}"
    if match.get("source_detail"):
        source_line += f": {match['source_detail']}"
    saved.append({
        "company": match.get("company", ""),
        "title": match.get("title", ""),
        "link": match.get("link", ""),
        "location": match.get("location", ""),
        "salary": match.get("salary", ""),
        # Carries over whatever was actually established for this match -
        # never reset to Open, which would silently erase a real Closed/
        # Unknown confirmation the moment it's saved.
        "posting_status": match.get("posting_status") or storage.POSTING_STATUS_OPEN,
        "posting_checked_at": match.get("posting_checked_at", ""),
        "date_saved": dt.date.today().isoformat(),
        "notes": source_line,
        "description": match.get("description", ""),
        "fit_score": match.get("fit_score"),
        "fit_notes": match.get("fit_notes", ""),
        "fit_matched": match.get("fit_matched", ""),
        "fit_required_gaps": match.get("fit_required_gaps", ""),
        "fit_preferred_gaps": match.get("fit_preferred_gaps", ""),
        "fit_unknowns": match.get("fit_unknowns", ""),
        "required_years_min": match.get("required_years_min"),
    })
    storage.save_saved(saved)
    records[idx]["match_status"] = storage.MATCH_STATUS_SAVED
    storage.save_matched(records)
    return True


def apply_to_applied_jobs(record: dict, force: bool = False) -> bool:
    """Copy a match straight into Applied Positions - skipping Saved Jobs -
    for when the user already applied to this posting outside the app, and
    mark the match Applied. Writes and changes nothing, returning False,
    when the posting is already tracked (Saved or Applied) and `force`
    isn't set - see save_to_saved_jobs for why this doesn't guess on its
    own which bucket is right."""
    records = storage.load_matched()
    idx = _find_index(records, record)
    if idx is None:
        return False
    match = records[idx]
    others = [r for i, r in enumerate(records) if i != idx]
    where = find_tracked(match, matched=others)
    if where in ("saved", "applied") and not force:
        return False

    applied = storage.load_applied()
    source_line = f"Found via {match.get('source', '')}"
    if match.get("source_detail"):
        source_line += f": {match['source_detail']}"
    today = dt.date.today().isoformat()
    applied.append({
        "company": match.get("company", ""),
        "title": match.get("title", ""),
        "link": match.get("link", ""),
        "location": match.get("location", ""),
        "salary": match.get("salary", ""),
        "date_saved": today,
        "date_applied": today,
        "status": "Applied",
        "rejected_from_stage": "",
        "notes": source_line,
        "call_notes": "",
        "description": match.get("description", ""),
        "fit_score": match.get("fit_score"),
        "fit_notes": match.get("fit_notes", ""),
        "fit_matched": match.get("fit_matched", ""),
        "fit_required_gaps": match.get("fit_required_gaps", ""),
        "fit_preferred_gaps": match.get("fit_preferred_gaps", ""),
        "fit_unknowns": match.get("fit_unknowns", ""),
        "required_years_min": match.get("required_years_min"),
    })
    storage.save_applied(applied)
    records[idx]["match_status"] = storage.MATCH_STATUS_APPLIED
    storage.save_matched(records)
    return True


def score_matches(records_to_score: list[dict], on_progress=None, model: str = ollama_client.DEFAULT_MODEL) -> list[str]:
    """Fit-score each given match against the resume with the same prompt
    Saved Jobs uses, saving after each one so a failure mid-batch keeps
    earlier results. Returns error messages."""
    resume_text = storage.load_resume()
    if not resume_text.strip():
        return ["Add your resume on the Profile page first - fit is scored against it."]
    errors = []
    for n, target in enumerate(records_to_score):
        if on_progress:
            on_progress(n, len(records_to_score), target)
        try:
            result = fit_analysis.analyze(resume_text, target, model=model)
        except ollama_client.OllamaError as exc:
            errors.append(f"{target.get('company', '?')}: {exc}")
            continue
        records = storage.load_matched()
        idx = _find_index(records, target)
        if idx is None:
            continue
        records[idx].update(result)
        storage.save_matched(records)
    return errors


def known_companies() -> list[str]:
    return [r.get("company", "") for r in storage.load_saved() + storage.load_applied()]


def gmail_alert_candidates(
    service=None, newer_than_days: int = 14, max_results: int = 20, on_progress=None
) -> tuple[list[dict], list[str]]:
    """Turn recent LinkedIn/Glassdoor job-alert emails into candidates.
    Reuses Mail Inbox's own pieces: the same alert query, the same
    subject-first field extraction, and the same one-message body read to
    pull out the posting link. Returns (candidates, errors)."""
    service = service or gmail_client.get_service()
    query = gmail_client.build_new_opportunities_query(known_companies(), newer_than_days=newer_than_days)
    messages = gmail_client.search_messages(query, service=service, max_results=max_results)
    candidates, errors = [], []
    for n, msg in enumerate(messages):
        if on_progress:
            on_progress(n, len(messages), msg)
        try:
            fields = job_extract.extract_opportunity_fields(msg["subject"], msg["snippet"])
        except ollama_client.OllamaError as exc:
            errors.append(f"{msg['subject']}: {exc}")
            continue
        try:
            link = gmail_client.get_message_link(
                msg["id"], service=service, company=fields["company"], title=fields["title"]
            )
        except Exception:
            link = ""
        candidates.append({**fields, "link": link, "source_detail": msg["subject"]})
    return candidates, errors


def search_queries(profile: dict) -> list[str]:
    """One Google Jobs query per target title, with the profile's keywords
    appended - e.g. "Backend Engineer Python AI agents"."""
    keywords = " ".join(k.strip() for k in profile.get("keywords", []) if k.strip())
    titles = [t.strip() for t in profile.get("titles", []) if t.strip()]
    return [f"{t} {keywords}".strip() for t in titles]
