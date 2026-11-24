import re

from src import ollama_client

# Field extraction is simple structured copying, not judgment - 4b matched 9b's
# output on test postings while running ~3x faster, so it gets its own default
# here rather than sharing ollama_client.DEFAULT_MODEL (used for fit scoring).
DEFAULT_MODEL = "qwen3.5:4b"

SYSTEM_PROMPT = (
    "You extract structured fields from a pasted job posting. "
    "Only use information present in the text - never invent values."
)


def build_prompt(description: str) -> str:
    return f"""JOB POSTING TEXT:
{description}

Extract these fields from the posting above. Respond ONLY with JSON in this exact shape:
{{"company": "<company name; if the posting deliberately withholds it (e.g. a stealth startup or confidential search), use \\"Stealth Startup\\" instead of leaving it blank; empty string only if you truly can't tell either way>",
  "title": "<job title, or empty string if not stated>",
  "location": "<location, or empty string if not stated>",
  "salary": "<salary/compensation if stated, else empty string>"}}"""


def _normalize_fields(result: dict) -> dict:
    return {
        "company": result.get("company", "") or "",
        "title": result.get("title", "") or "",
        "location": result.get("location", "") or "",
        "salary": result.get("salary", "") or "",
    }


_WORD_RE = re.compile(r"[a-z0-9]+")


def _words(text: str) -> set:
    return set(_WORD_RE.findall(text.lower()))


def unverified_fields(fields: dict, source_text: str) -> list[str]:
    """Which of fields' values have no real overlap with source_text - a
    cheap guard against the model inventing a plausible-looking value
    instead of copying one that's actually in the posting/email. Compares
    whole words (case-/punctuation-insensitive) rather than requiring an
    exact substring, since the model is free to reformat things like
    "$120,000-$150,000" into "$120k-$150k". "Stealth Startup" is a
    deliberately synthesized placeholder (see SYSTEM_PROMPT) and is never
    flagged."""
    haystack = _words(source_text)
    flagged = []
    for field, value in fields.items():
        if not value or value == "Stealth Startup":
            continue
        value_words = _words(value)
        if value_words and not value_words & haystack:
            flagged.append(field)
    return flagged


def extract_fields(description: str, model: str = DEFAULT_MODEL) -> dict:
    """Pull company/title/location/salary out of pasted job description
    text. The returned dict also carries "unverified": the names of any
    fields whose value doesn't actually appear in that text (see
    unverified_fields) - callers can use it to flag a value worth a second
    look instead of trusting it outright."""
    prompt = build_prompt(description)
    result = ollama_client.chat_json(SYSTEM_PROMPT, prompt, model=model)
    fields = _normalize_fields(result)
    fields["unverified"] = unverified_fields(fields, description)
    return fields


# Glassdoor's job-alert digest subject names the one job this particular
# email is "about" (even though the body bundles ~10 others), in a fixed
# shape: "<title> at <company> and N more jobs in <location> for you. Apply
# Now." Parsed deterministically, bypassing both the LLM and Gmail's snippet
# field entirely, because that snippet is the email's hidden preheader text
# - which names a *different* job card's company in the same digest, not
# the one in the subject. Feeding that snippet to the LLM alongside the
# subject reliably picked the wrong company: observed live on real alert
# emails, it extracted "Apple" and an unrelated company name for subjects
# that correctly named "Check Point Software Technologies" and "Questar
# Auto Technologies" respectively.
_GLASSDOOR_DIGEST_RE = re.compile(
    r"^(?P<title>.+?)\s+at\s+(?P<company>.+?)\s+and\s+\d+\s+more\s+jobs?\s+in\s+"
    r"(?P<location>.+?)\s+for\s+you\.\s*Apply\s+Now\.?$",
    re.IGNORECASE,
)

OPPORTUNITY_SYSTEM_PROMPT = (
    "You extract structured fields from a job-alert email. The subject line is the most "
    "reliable source of the company and title. The preview snippet is sometimes the "
    "email's hidden preheader text, which can describe a *different* job from the same "
    "digest - ignore the snippet whenever it conflicts with the subject. Only use "
    "information present in the text - never invent values."
)


def build_opportunity_prompt(subject: str, snippet: str) -> str:
    return f"""EMAIL SUBJECT:
{subject}

EMAIL PREVIEW SNIPPET (may describe an unrelated job from the same digest - trust it only when it agrees with the subject):
{snippet}

Extract these fields. Respond ONLY with JSON in this exact shape:
{{"company": "<company name; if the posting deliberately withholds it (e.g. a stealth startup or confidential search), use \\"Stealth Startup\\" instead of leaving it blank; empty string only if you truly can't tell either way>",
  "title": "<job title, or empty string if not stated>",
  "location": "<location, or empty string if not stated>",
  "salary": "<salary/compensation if stated, else empty string>"}}"""


def extract_opportunity_fields(subject: str, snippet: str, model: str = DEFAULT_MODEL) -> dict:
    """Pull company/title/location/salary out of a job-alert email (as
    opposed to extract_fields(), which expects a full pasted job posting).

    Tries the deterministic Glassdoor-digest parse first (see
    _GLASSDOOR_DIGEST_RE) - no LLM call, and immune to the misleading
    snippet issue described there. Every other alert shape (LinkedIn's
    "<company> is hiring: <title>", a bare "<company> <title>" with no
    separator, ...) falls back to the LLM, with a prompt that explicitly
    warns it the snippet may not belong to the subject's job."""
    match = _GLASSDOOR_DIGEST_RE.match(subject.strip())
    if match:
        return {
            "company": match.group("company").strip(),
            "title": match.group("title").strip(),
            "location": match.group("location").strip(),
            "salary": "",
            # Parsed directly out of the subject line itself - nothing to verify.
            "unverified": [],
        }
    prompt = build_opportunity_prompt(subject, snippet)
    result = ollama_client.chat_json(OPPORTUNITY_SYSTEM_PROMPT, prompt, model=model)
    fields = _normalize_fields(result)
    fields["unverified"] = unverified_fields(fields, f"{subject}\n{snippet}")
    return fields
