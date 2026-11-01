---
name: debug
description: Diagnose a failure in this job hunter dashboard - app crashes, a provider (Ollama/Claude/ChatGPT) chat error, a failing test, or bad/missing data in a view. Use when the user reports something broken, pastes an error or traceback from this app, or asks why something isn't working.
---

# Debugging personal_job_hunter

Narrow down which of this app's moving parts is actually at fault before
guessing. Check in this order - most failures in this repo trace back to one
of these.

## 1. Is it a provider (LLM) failure?

Symptoms: chat assistant error banner, `OllamaError`, `AnthropicError`,
`OpenAIError`, or a timeout.

- **Ollama**: check it's actually running and reachable -
  `curl -m 5 http://localhost:11434/api/tags`. If that hangs or refuses,
  `ollama serve` isn't up (`pgrep -fl ollama`) or the model isn't loaded. A
  `read timeout=300` with no response usually means the daemon wasn't up
  yet or the first request forced a slow model load, not a code bug -
  retry once the daemon responds to `/api/tags` quickly.
- **Claude / ChatGPT**: check the matching key
  (`ANTHROPIC_API_KEY` / `OPENAI_API_KEY`) is actually set in `.env` or the
  process env, not just referenced in the UI's "enter key" form. See
  `src/anthropic_client.py` / `src/openai_client.py` for how each error is
  wrapped before it reaches `src/chat_view.py`.
- Check `src/chat_view.py`'s `PROVIDERS` dict to confirm which module/model
  the failing provider actually routes through.

## 2. Is it a data/storage issue?

Symptoms: a position missing, duplicate entries, a view showing stale data.

- All data lives as JSON under `data/` (`saved_positions.json`,
  `applied_positions.json`, `resume.md`) via `src/storage.py` - read that
  module's load/save functions rather than assuming a database exists.
  There isn't one.
- `src/storage.find_record_index` is what dedupes/matches records by link or
  company+title; a "duplicate" bug report is usually a mismatch there
  (e.g. case sensitivity, or an ambiguous match with no title given).

## 3. Is it a test failure?

- Run the specific test verbosely: `pytest evals/unit/test_X.py -vv`.
- If a test passes alone but fails in the full suite (or vice versa),
  suspect Streamlit `AppTest` module-reload breaking test isolation - see
  the `JOB_HUNTER_DATA_DIR` pattern in `evals/unit/conftest.py` before
  assuming the production code is wrong.
- `evals/llm/` tests call the real Ollama model and are slow/skipped when
  Ollama isn't reachable - a failure there first needs step 1 ruled out.

## 4. Is it an app-startup / Streamlit issue?

- Run it directly to see the real traceback instead of a screenshot:
  `streamlit run app.py` (check `.streamlit/config.toml` for any toolbar
  settings that might be hiding errors).
- If it only fails in Docker, compare against a local `streamlit run` first
  - the container has no access to `localhost:11434` (Ollama) by default,
  so the Claude/ChatGPT providers are the only ones that work there without
  extra `--add-host` networking (see the Docker section of `README.md`).

## Reporting back

State what you checked and ruled out, then the actual root cause - don't
just paste the traceback back at the user. If multiple things could explain
it, say which is most likely and how to confirm.
