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


def extract_fields(description: str, model: str = DEFAULT_MODEL) -> dict:
    """Pull company/title/location/salary out of pasted job description text."""
    prompt = build_prompt(description)
    result = ollama_client.chat_json(SYSTEM_PROMPT, prompt, model=model)
    return {
        "company": result.get("company", "") or "",
        "title": result.get("title", "") or "",
        "location": result.get("location", "") or "",
        "salary": result.get("salary", "") or "",
    }
