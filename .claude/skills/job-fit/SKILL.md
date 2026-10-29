---
name: job-fit
description: Analyze how well the user's resume fits a saved job or a First Call application in this job hunter dashboard, then write a fit score and notes back into the position's JSON record. Use when the user asks to check fit, analyze a job, or review how they match a saved position or an application in First Call stage.
---

# Job fit analysis

This project (`personal_job_hunter`) tracks saved and applied positions as
JSON (`data/saved_positions.json`, `data/applied_positions.json`) and keeps
the user's resume as plain text/Markdown at `data/resume.md`. Fit scoring is
done locally by Ollama (`qwen3.5:9b` by default) - your job is to fetch the
*actual* job posting (the local script's plain HTTP GET can't get past
LinkedIn and other JS-heavy/login-gated sites) and hand that text to Ollama.

## Steps

1. **Read the resume.** `data/resume.md`. If it's empty, tell the user to
   fill it in on the Personal Work Info tab first (or paste it in chat) and stop.
2. **Identify the position.** The user will name a company (and maybe a
   title). Find it in `data/saved_positions.json` or
   `data/applied_positions.json` (match by company, case-insensitive).
3. **Fetch the real posting.** If the record has a `link`, fetch it with
   WebFetch, prompting it to return the full job description (requirements,
   responsibilities, seniority). If WebFetch can't get past a login wall
   (common on LinkedIn), say so and fall back to scoring on company/title/
   location/notes alone - don't silently guess at the posting's contents.
4. **Save the fetched text to a file** in this project's agent data dir,
   `data/agent/postings/<company>.txt` (lowercase, spaces as `_`). This keeps
   a durable record of what was actually fetched instead of a throwaway temp
   file, so a later re-score or a human check can see exactly what Ollama saw.
5. **Score it with Ollama.** Run:
   ```bash
   python scripts/analyze_fit_single.py <saved|applied> --company "<company>" --title "<title>" \
     --posting-text-file data/agent/postings/<company>.txt
   ```
   Use the `saved` or `applied` list depending on where the position lives.
   This prints the score and notes, and writes `fit_score`/`fit_notes` onto
   the matching record (matched by company, falling back to company+title if
   ambiguous). If you skipped step 3-4 (no link, or fetch failed), omit
   `--posting-text-file` and the script falls back to its own plain GET.
6. **Report back** the score and a one-line summary in chat, and mention
   whether the score was based on the real posting or just the saved
   metadata - the full notes are also visible on the Personal Work Info tab.

## Batch mode

If the user asks to analyze "all saved jobs" or "everything in First Call",
loop steps 2-6 for each matching record. First Call applications are entries
in `data/applied_positions.json` with `"status": "First Call"`. For a large
batch where fetching every link individually would be slow, it's fine to ask
the user whether they want full-posting accuracy (slower) or a quick pass on
saved metadata only (use `scripts/analyze_fit_ollama.py <saved|applied>`,
which does the whole batch with its own plain-GET fetch, no WebFetch).
