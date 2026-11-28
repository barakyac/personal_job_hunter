import re

import requests

from src import ollama_client, storage

SYSTEM_PROMPT = (
    "You are a precise, no-nonsense career advisor. You compare a candidate's "
    "resume against a job posting and judge fit honestly - don't inflate scores."
)


def fetch_posting_text(link: str, timeout: int = 10) -> str:
    if not link:
        return ""
    try:
        resp = requests.get(link, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
    except requests.RequestException:
        return ""

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    text = re.sub(r"\n{2,}", "\n\n", soup.get_text(separator="\n")).strip()
    return text[:6000]


def build_prompt(resume_text: str, job: dict, posting_text: str) -> str:
    posting_line = f"\nPosting text (fetched from the link):\n{posting_text}" if posting_text else ""
    personal_context = storage.load_personal_context()
    context_block = (
        f"\nADDITIONAL CONTEXT (cover letters, certifications, notes - supplements the resume):\n{personal_context}"
        if personal_context.strip()
        else ""
    )
    # Set when this match was collected with an experience-years filter
    # active (job_matching.extract_required_years) - a figure already
    # pulled from the posting's own text, not something to re-derive. This
    # is purely informational for scoring: it describes what the posting
    # asks for, never the candidate's own experience, and must not change
    # how honestly the gap against the resume gets reported.
    required_years = job.get("required_years_min")
    years_line = (
        f"\nStated required experience: {required_years}+ years (as extracted from the posting when "
        "this job was collected - always weigh this explicitly against the resume's own years of "
        "relevant experience, and name it in \"matched\"/\"required_gaps\"/\"notes\" as appropriate)."
        if required_years not in (None, "")
        else ""
    )
    return f"""RESUME:
{resume_text}
{context_block}

JOB POSTING:
Company: {job.get('company', '')}
Title: {job.get('title', '')}
Location: {job.get('location', '')}
Salary: {job.get('salary', '')}
Notes: {job.get('notes', '')}{years_line}{posting_line}

Rate how well this candidate's resume fits this job, 1-10 (10 = excellent match).

For every item below, name the specific posting requirement it's about and point to the specific
resume/context evidence behind it (or its explicit absence) - never a vague or generic claim.

- "matched": requirements the posting states that the resume clearly satisfies - say what the posting
  asks for and where the resume shows it.
- "required_gaps": requirements the posting marks as required/must-have that the resume's own content
  actively contradicts or clearly falls short of (e.g. posting wants "5+ years", resume shows 2). Only
  include one here when the resume gives you a concrete reason to believe the candidate falls short -
  never just because the resume stays silent on it.
- "preferred_gaps": the same kind of confirmed shortfall, but for requirements the posting marks as
  preferred/nice-to-have/advantage rather than required.
- "unknowns": requirements the posting states (required or preferred) that the resume simply doesn't
  address either way - neither confirmed nor contradicted. "Not mentioned in the resume" always belongs
  here, never in required_gaps/preferred_gaps - silence is not the same as a confirmed gap.

Respond ONLY with JSON in this exact shape:
{{"score": <integer 1-10>, "notes": "<2-4 sentences: concrete strengths and concrete gaps>",
"matched": ["<requirement>: <evidence>", "..."], "required_gaps": ["..."], "preferred_gaps": ["..."],
"unknowns": ["..."]}}"""


def _join_items(items) -> str:
    """Flatten a list of evidence-backed strings from the model's JSON
    response into one of this app's plain multi-line text fields - same
    storage shape as fit_notes, so every existing dataframe/UI path that
    already handles a text column handles these for free."""
    if not items:
        return ""
    if isinstance(items, str):
        return items
    if not isinstance(items, list):
        # The prompt asks for a list; a model can still emit a bare scalar
        # (e.g. "matched": true) for one field. Iterating over that directly
        # would raise TypeError deep inside analyze_many's loop, indistinguishable
        # from an unrelated bug - raise the same error type callers already
        # catch instead, so one malformed field reports as one error rather
        # than aborting every other record still waiting to be scored.
        raise ollama_client.OllamaError(f"Expected a list of items, got {type(items).__name__}: {items!r}")
    return "\n".join(str(item).strip() for item in items if str(item).strip())


def analyze_with_posting_text(
    resume_text: str, job: dict, posting_text: str, model: str = ollama_client.DEFAULT_MODEL
) -> dict:
    """Score a job given posting text that's already been fetched (e.g. by the agent
    via WebFetch, for sites a plain GET request can't reach)."""
    prompt = build_prompt(resume_text, job, posting_text)
    result = ollama_client.chat_json(SYSTEM_PROMPT, prompt, model=model)
    score = result.get("score")
    try:
        if score is None or not (1 <= float(score) <= 10):
            raise ValueError
    except (TypeError, ValueError):
        # A syntactically valid JSON object missing "score" (or carrying a
        # non-numeric/out-of-range one) is still a malformed response - the
        # prompt asked for an integer 1-10. Without this check, callers would
        # silently store fit_score=None as if scoring had succeeded, instead
        # of this one bad response reporting as the error it actually is.
        raise ollama_client.OllamaError(f"Model response missing a valid \"score\" (1-10): {result!r}")
    return {
        "fit_score": score,
        "fit_notes": result.get("notes", ""),
        "fit_matched": _join_items(result.get("matched")),
        "fit_required_gaps": _join_items(result.get("required_gaps")),
        "fit_preferred_gaps": _join_items(result.get("preferred_gaps")),
        "fit_unknowns": _join_items(result.get("unknowns")),
    }


def analyze(resume_text: str, job: dict, model: str = ollama_client.DEFAULT_MODEL) -> dict:
    posting_text = job.get("description") or fetch_posting_text(job.get("link", ""))
    return analyze_with_posting_text(resume_text, job, posting_text, model=model)


def analyze_many(
    resume_text: str,
    records: list[dict],
    indices: list[int],
    on_progress=None,
    model: str = ollama_client.DEFAULT_MODEL,
) -> list[str]:
    """Analyze records at the given indices in place. Returns error messages for failures."""
    errors = []
    for n, i in enumerate(indices):
        job = records[i]
        if on_progress:
            on_progress(n, len(indices), job)
        try:
            result = analyze(resume_text, job, model=model)
        except ollama_client.OllamaError as exc:
            errors.append(f"{job.get('company', '?')}: {exc}")
            continue
        records[i].update(result)
    return errors
