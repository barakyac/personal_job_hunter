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
    return f"""RESUME:
{resume_text}
{context_block}

JOB POSTING:
Company: {job.get('company', '')}
Title: {job.get('title', '')}
Location: {job.get('location', '')}
Salary: {job.get('salary', '')}
Notes: {job.get('notes', '')}{posting_line}

Rate how well this candidate's resume fits this job, 1-10 (10 = excellent match).
Respond ONLY with JSON in this exact shape:
{{"score": <integer 1-10>, "notes": "<2-4 sentences: concrete strengths and concrete gaps>"}}"""


def analyze_with_posting_text(
    resume_text: str, job: dict, posting_text: str, model: str = ollama_client.DEFAULT_MODEL
) -> dict:
    """Score a job given posting text that's already been fetched (e.g. by the agent
    via WebFetch, for sites a plain GET request can't reach)."""
    prompt = build_prompt(resume_text, job, posting_text)
    result = ollama_client.chat_json(SYSTEM_PROMPT, prompt, model=model)
    return {"fit_score": result.get("score"), "fit_notes": result.get("notes", "")}


def analyze(resume_text: str, job: dict, model: str = ollama_client.DEFAULT_MODEL) -> dict:
    posting_text = fetch_posting_text(job.get("link", ""))
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
        records[i]["fit_score"] = result["fit_score"]
        records[i]["fit_notes"] = result["fit_notes"]
    return errors
