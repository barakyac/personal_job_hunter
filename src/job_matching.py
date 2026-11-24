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
    return record


def passes_profile_filters(candidate: dict, profile: dict) -> bool:
    """Drop a candidate whose title/description hits one of the profile's
    exclude keywords (e.g. "senior staff", "frontend", "relocation")."""
    excludes = [_norm(k) for k in profile.get("exclude_keywords", []) if _norm(k)]
    if not excludes:
        return True
    haystack = _norm(f"{candidate.get('title', '')} {candidate.get('description', '')}")
    return not any(k in haystack for k in excludes)


def add_candidates(candidates: list[dict], source: str, profile: dict | None = None) -> dict:
    """Append new candidates to matched_jobs.json. Returns counts:
    {"added": n, "already_tracked": n, "filtered": n, "invalid": n}.
    A candidate needs at least a company or a link to be kept."""
    profile = profile if profile is not None else storage.load_match_profile()
    matched = storage.load_matched()
    counts = {"added": 0, "already_tracked": 0, "filtered": 0, "invalid": 0}
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
        matched.append(_clean_candidate(raw, source))
        counts["added"] += 1
    if counts["added"]:
        storage.save_matched(matched)
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


def set_status(record: dict, status: str) -> bool:
    records = storage.load_matched()
    idx = _find_index(records, record)
    if idx is None:
        return False
    records[idx]["match_status"] = status
    storage.save_matched(records)
    return True


def save_to_saved_jobs(record: dict) -> bool:
    """Copy a match into Saved Jobs (keeping its description and fit
    score, so "Calculate fit" there doesn't redo the work) and mark the
    match Saved. Returns False, writing nothing to Saved Jobs, when the
    posting is already in Saved or Applied."""
    records = storage.load_matched()
    idx = _find_index(records, record)
    if idx is None:
        return False
    match = records[idx]
    others = [r for i, r in enumerate(records) if i != idx]
    where = find_tracked(match, matched=others)
    if where in ("saved", "applied"):
        records[idx]["match_status"] = storage.MATCH_STATUS_SAVED
        storage.save_matched(records)
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
        "posting_status": storage.POSTING_STATUS_OPEN,
        "date_saved": dt.date.today().isoformat(),
        "notes": source_line,
        "description": match.get("description", ""),
        "fit_score": match.get("fit_score"),
        "fit_notes": match.get("fit_notes", ""),
    })
    storage.save_saved(saved)
    records[idx]["match_status"] = storage.MATCH_STATUS_SAVED
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
        records[idx]["fit_score"] = result["fit_score"]
        records[idx]["fit_notes"] = result["fit_notes"]
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
