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

Possible stages (pick whichever definition(s) best match what the emails describe):
{status_lines}

Emails found for this company:
{mail_lines}

Based only on these emails, what stage(s) does the hiring process show? Usually that's exactly one
stage - list more than one only when different emails genuinely show different stages (e.g. an older
email about an initial screening call and a separate, newer email about a later interview), ordered
most-advanced-first so the user can pick the right one. Leave the list empty if there's no clear signal
beyond generic job-alert noise.
Respond ONLY with JSON in this exact shape:
{{"stages": [{{"status": "<one of the possible stages>", "reason": "<one sentence citing what in the emails shows this>"}}]}}"""


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
    still recoverable via the per-company "Analyze with AI" button. Unlike
    the single, deterministic rejection shortcut, this path can surface
    more than one candidate stage (see "candidates" below) - different
    emails for the same company sometimes show genuinely different stages
    (e.g. an older screening-call email and a separate, newer interview
    email), and picking one on the user's behalf would silently discard
    the other.

    Returns {"action": "update_status"|"none", "new_status": str, "reason": str,
    "candidates": [{"new_status": str, "reason": str}, ...]} - "new_status"/"reason"
    is always candidates[0] (kept for callers that only want the single best
    guess); "candidates" is omitted when action is "none". Never writes
    anything; the caller decides whether to act on it."""
    if not messages:
        return {"action": "none", "new_status": "", "reason": ""}

    if current_status not in storage.OUTCOME_STATUSES:
        rejection_msg = next((m for m in messages if m.get("looks_like_rejection")), None)
        if rejection_msg:
            reason = f"This email looks like a rejection: \"{rejection_msg['subject']}\""
            return {
                "action": "update_status",
                "new_status": "Rejected",
                "reason": reason,
                "candidates": [{"new_status": "Rejected", "reason": reason}],
            }

    prompt = build_prompt(company, messages)
    result = ollama_client.chat_json(SYSTEM_PROMPT, prompt, model=model)
    if not isinstance(result, dict):
        return {"action": "none", "new_status": "", "reason": ""}

    raw_stages = result.get("stages")
    if not isinstance(raw_stages, list):
        raw_stages = []

    status_by_lower = {s.lower(): s for s in STATUS_OPTIONS}
    candidates = []
    seen_statuses = set()
    for entry in raw_stages:
        if not isinstance(entry, dict):
            continue
        raw_status = (entry.get("status") or "").strip()
        status = status_by_lower.get(raw_status.lower(), "")

        # "Applied" is the pipeline's baseline/entry stage - no real email
        # ever legitimately moves an application backward to it once it's
        # further along, so a model answer of "Applied" here is
        # indistinguishable from it defaulting to the first possible-stage
        # when it actually has no real signal (observed live: it called an
        # already-Rejected application's unrelated job-alert noise
        # "Applied" even while its own "reason" said there was no stage
        # signal at all). Drop it rather than let it regress anything.
        # Also drop a stage that's already the current one - nothing to
        # suggest - and any duplicate the model repeated.
        if not status or status == "Applied" or status == current_status or status in seen_statuses:
            continue
        seen_statuses.add(status)
        candidates.append({"new_status": status, "reason": (entry.get("reason") or "").strip()})

    if not candidates:
        return {"action": "none", "new_status": "", "reason": ""}

    return {
        "action": "update_status",
        "new_status": candidates[0]["new_status"],
        "reason": candidates[0]["reason"],
        "candidates": candidates,
    }
