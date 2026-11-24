"""Google Jobs search through SerpAPI's `google_jobs` engine.

Why SerpAPI and not Google's own API: Google's Custom Search JSON API has
been closed to new customers since January 2026 and is discontinued on
January 1, 2027, and it never returned Google's structured job listings
anyway. SerpAPI's google_jobs engine returns the same job cards you see
when you search Google for "<title> jobs" (title, company, location, the
boards it's posted on, the full description), which is exactly the shape
a Matching Jobs candidate needs.

Set SERPAPI_API_KEY (in .env, .streamlit/secrets.toml or the environment).
The free plan covers a modest number of searches a month - one search per
target title per scan.
"""

import os

import requests

SERPAPI_URL = "https://serpapi.com/search.json"
API_KEY_ENV_VAR = "SERPAPI_API_KEY"


class JobSearchError(Exception):
    pass


def api_key() -> str | None:
    try:
        import streamlit as st

        value = st.secrets.get(API_KEY_ENV_VAR)  # type: ignore[union-attr]
        if value:
            return str(value)
    except Exception:
        pass
    return os.environ.get(API_KEY_ENV_VAR) or None


def is_configured() -> bool:
    return bool(api_key())


def _best_link(job: dict) -> str:
    """Prefer the company's own careers page / an ATS over a job board
    mirror, then LinkedIn, then whatever's first, then Google's share link."""
    options = [o for o in job.get("apply_options") or [] if o.get("link")]
    boards = ("linkedin", "indeed", "glassdoor", "ziprecruiter", "monster", "jooble", "talent.com")
    direct = [o for o in options if not any(b in (o.get("title", "") + o["link"]).lower() for b in boards)]
    linkedin = [o for o in options if "linkedin" in o["link"].lower()]
    for group in (direct, linkedin, options):
        if group:
            return group[0]["link"]
    return job.get("share_link", "") or ""


def parse_results(payload: dict, query: str = "") -> list[dict]:
    candidates = []
    for job in payload.get("jobs_results") or []:
        ext = job.get("detected_extensions") or {}
        candidates.append({
            "company": job.get("company_name", "") or "",
            "title": job.get("title", "") or "",
            "location": job.get("location", "") or "",
            "salary": ext.get("salary", "") or "",
            "link": _best_link(job),
            "description": (job.get("description", "") or "")[:6000],
            "source_detail": f"Google Jobs: \"{query}\"" + (f" via {job['via']}" if job.get("via") else ""),
        })
    return candidates


def search_jobs(query: str, location: str = "", timeout: int = 20) -> list[dict]:
    """One Google Jobs search. Returns candidate dicts (company, title,
    location, salary, link, description, source_detail)."""
    key = api_key()
    if not key:
        raise JobSearchError(f"Set {API_KEY_ENV_VAR} to search Google Jobs (get one at serpapi.com).")
    params = {"engine": "google_jobs", "q": query, "api_key": key, "hl": "en"}
    if location.strip():
        params["location"] = location.strip()
    try:
        resp = requests.get(SERPAPI_URL, params=params, timeout=timeout)
    except requests.RequestException as exc:
        raise JobSearchError(f"Could not reach SerpAPI: {exc}") from exc
    try:
        payload = resp.json()
    except ValueError as exc:
        raise JobSearchError(f"SerpAPI returned a non-JSON response (HTTP {resp.status_code}).") from exc
    if payload.get("error"):
        # "Google hasn't returned any results for this query." is an empty
        # result set, not a failure.
        if "hasn't returned any results" in payload["error"]:
            return []
        raise JobSearchError(f"SerpAPI error: {payload['error']}")
    if resp.status_code >= 400:
        raise JobSearchError(f"SerpAPI HTTP {resp.status_code}")
    return parse_results(payload, query)
