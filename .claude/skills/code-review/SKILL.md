---
name: code-review
description: Review a diff or set of changes in this job hunter dashboard against the project's own conventions (test coverage, provider parity, data privacy, CI/CD) before it's committed or pushed. Use when the user asks to review code, check a diff, or sanity-check changes before committing in this repo.
---

# Code review for personal_job_hunter

This is a solo Streamlit app with one real reviewer (the user), so this
review focuses on things that are easy to miss rather than generic style
nitpicks. Run `git diff` (staged + unstaged) and `git status` first to see
the actual scope.

## Checklist

1. **Test coverage.** Every `src/<name>.py` the diff touches should have a
   matching `evals/unit/test_<name>.py` updated or added (see the
   `check-missing-tests` skill for the full mapping and current gaps).
   New behavior with no new/updated test is the single most common miss.

2. **Provider parity.** `src/ollama_client.py`, `src/anthropic_client.py`,
   and `src/openai_client.py` all expose the same shape (`chat`,
   `chat_json`, their own `*Error` class) and are wired into
   `src/chat_view.py`'s `PROVIDERS` dict. A change to one provider's
   interface that isn't mirrored in the others (or in the tests for all
   three) will silently break the dropdown for the other two.

3. **Data privacy.** `data/*` (resume, saved/applied positions, fetched
   postings under `data/agent/`) and `.env` are gitignored on purpose -
   this is personal job-search data and API keys. Run the `secrets-check`
   skill if the diff touches anything under `data/`, `.env`, or
   `.dockerignore`/`.gitignore` themselves.

4. **Streamlit `AppTest` isolation.** Tests that drive views through
   `streamlit.testing.v1.AppTest` can reload modules mid-test and bypass
   `monkeypatch`. Confirm new tests in `evals/unit` use the
   `JOB_HUNTER_DATA_DIR` env var / session guard fixture pattern already
   used in `evals/unit/conftest.py` rather than raw `monkeypatch.setattr`
   on storage paths.

5. **CI/CD stays truthful.** If the diff adds a new `src/` module, a new
   dependency, or changes how the app starts, check whether
   `.github/workflows/ci.yml`, `.github/workflows/cd.yml`, or the
   `Dockerfile` need a matching update (e.g. a new entry in
   `requirements.txt` that the Dockerfile's `pip install` step will pick up
   automatically, vs. a new env var the container needs at runtime).

6. **Run the suite.** `pytest evals/unit -v` - this is exactly what CI runs
   on push/PR; a diff that doesn't pass it locally won't pass there either.

## Reporting

Report findings the same way the built-in `code-review` skill does: most
severe first, with file:line, what's actually wrong, and the concrete
failure scenario - not style preferences. If nothing survives scrutiny, say
so plainly instead of padding the list.
