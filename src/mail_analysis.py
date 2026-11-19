from src import ollama_client, storage

# Classifying a handful of short emails against a fixed list of statuses is
# much closer to job_extract's "simple structured copying" than to
# fit_analysis's open-ended judgment call - the 4b model is ~3x faster than
# ollama_client.DEFAULT_MODEL (9b) and was fine on this narrower task, which
# matters a lot once "Analyze all" is looping it over every company serially.
DEFAULT_MODEL = "qwen3.5:4b"

SYSTEM_PROMPT = (
    "You are a precise job-application assistant. You read a short batch of emails "
    "about one job application and identify what stage, if any, they clearly show the "
    "application has reached. Be conservative - generic LinkedIn job-alert noise or an "
    "automated 'we received your application' confirmation shows no stage on its own."
)

STATUS_OPTIONS = storage.STATUS_OPTIONS

# Bare status names are ambiguous to a model with no context on this user's
# pipeline - e.g. it previously read a "screening interview" email as a move
# from First Call to Interview, when a screening call *is* this user's First
# Call stage and Interview means something further along. Spelling out what
# each stage actually covers fixes that misclassification at the source.
STATUS_DEFINITIONS = {
    "Applied": "Application submitted; no human contact yet (job-alert or ATS auto-confirmation only).",
    "First Call": "The initial screening call/interview with a recruiter or hiring manager - by phone or "
    "video. Anything called a 'screening call', 'screening interview', or 'intro call' belongs here, "
    "even if the email itself uses the word 'interview'.",
    "Assignment / Home Test": "A take-home assignment, coding challenge, or technical test done outside a call.",
    "Interview": "A further interview beyond the initial screening call - e.g. a technical, panel, "
    "onsite, or hiring-manager interview with the team.",
    "Reference Check": "References are being checked, typically near the end of the process.",
    "Offer": "An offer has been made.",
    "Rejected": "The application was rejected, or the candidate was told they will not move forward.",
    "Withdrawn": "The candidate withdrew from consideration.",
}


def build_prompt(company: str, messages: list[dict]) -> str:
    """Note: deliberately doesn't mention the application's current status -
    see analyze_company_mail for why the model is kept out of that
    comparison entirely."""
    mail_lines = "\n\n".join(
        f"Subject: {m['subject']}\nFrom: {m['sender']}\nDate: {m['date']}\nSnippet: {m['snippet']}"
        for m in messages
    )
    status_lines = "\n".join(f"- {s}: {STATUS_DEFINITIONS[s]}" for s in STATUS_OPTIONS)
    return f"""Company: {company}

Possible stages (pick the one whose definition best matches what the emails describe):
{status_lines}

Emails found for this company:
{mail_lines}

Based only on these emails, what stage does the hiring process show, if any clear signal is present?
Respond ONLY with JSON in this exact shape:
{{"implied_status": "<one of the possible stages these specific emails show, or empty string if there is no clear signal beyond generic job-alert noise>", "reason": "<one sentence citing what in the emails shows this>"}}"""


def analyze_company_mail(
    company: str, current_status: str, messages: list[dict], model: str = DEFAULT_MODEL
) -> dict:
    """Decide whether a company's matched emails show a status change.

    A rejection is caught first, deterministically, via the same keyword
    heuristic (gmail_client.looks_like_rejection) that already drives the
    "N email(s) look like a rejection" banner - not via the model. Missing
    a rejection is the single worst failure mode here (the user keeps
    thinking they're still in process), and with "think" disabled for
    speed the 4b model was demonstrably unreliable on exactly this case:
    across repeated runs it sometimes wrote a "reason" that correctly
    paraphrased an obvious rejection email while still reporting no status
    signal at all. Re-enabling "think" fixed that but made a single call
    take anywhere from ~50s to 120s+ - unworkable for "Analyze all" looping
    over every company. The keyword check is instant, free, and exactly as
    trustworthy as the banner the user already relies on.

    Every other transition (First Call, Interview, Assignment, ...) still
    goes through the model, which only has to classify what the emails
    show (not also compare it against current_status - seemed to help, see
    build_prompt) - a best-effort pass for progressions that are lower-
    stakes to occasionally miss, not caught by a comparable heuristic, and
    still recoverable via the per-company "Analyze with AI" button.

    Returns {"action": "update_status"|"none", "new_status": str, "reason": str} -
    never writes anything; the caller decides whether to act on it."""
    if not messages:
        return {"action": "none", "new_status": "", "reason": ""}

    if current_status not in storage.OUTCOME_STATUSES:
        rejection_msg = next((m for m in messages if m.get("looks_like_rejection")), None)
        if rejection_msg:
            return {
                "action": "update_status",
                "new_status": "Rejected",
                "reason": f"This email looks like a rejection: \"{rejection_msg['subject']}\"",
            }

    prompt = build_prompt(company, messages)
    result = ollama_client.chat_json(SYSTEM_PROMPT, prompt, model=model)
    if not isinstance(result, dict):
        return {"action": "none", "new_status": "", "reason": ""}

    raw_status = (result.get("implied_status") or "").strip()
    status_by_lower = {s.lower(): s for s in STATUS_OPTIONS}
    implied_status = status_by_lower.get(raw_status.lower(), "")

    # "Applied" is the pipeline's baseline/entry stage - no real email ever
    # legitimately moves an application backward to it once it's further
    # along, so a model answer of "Applied" here is indistinguishable from
    # it defaulting to the first item in the possible-stages list when it
    # actually has no real signal (observed live: it called an already-
    # Rejected application's unrelated job-alert noise "Applied" even while
    # its own "reason" said there was no stage signal at all). Treat it the
    # same as an empty implied_status rather than let it regress anything.
    if implied_status == "Applied":
        implied_status = ""

    if implied_status and implied_status != current_status:
        action, new_status = "update_status", implied_status
    else:
        action, new_status = "none", ""

    return {
        "action": action,
        "new_status": new_status,
        "reason": result.get("reason", ""),
    }
