---
name: secrets-check
description: Check this job hunter dashboard's working tree, staged changes, or a specific diff for API keys, personal data, or other secrets about to be committed or pushed. Use before committing/pushing, or when the user asks to check for leaked secrets, exposed keys, or whether personal data is safe.
---

# Secrets check for personal_job_hunter

This repo has two categories of things that must never reach a commit:
API keys (`.env`) and the user's actual personal job-search data (`data/`).
Both are gitignored already - this skill is about catching the ways that
protection can be bypassed, not re-explaining that they're ignored.

## Steps

1. **Check what's actually staged/tracked**, not just `.gitignore` intent:
   ```bash
   git status
   git ls-files .env data/ 2>/dev/null
   ```
   `git ls-files` returning anything for `.env` or `data/*` (other than
   `data/.gitkeep`) means it was force-added at some point and *is* tracked
   despite the ignore rule - that's the critical case, not a false alarm.

2. **Check staged content for hardcoded keys**, not just whole-file adds:
   ```bash
   git diff --staged | grep -iE "sk-[a-zA-Z0-9]{10,}|anthropic|openai.*key|api[_-]?key\s*=\s*['\"]"
   ```
   A key pasted directly into source (e.g. debugging with a literal string
   instead of `os.environ`) won't be caught by `.gitignore` at all.

3. **Check `.dockerignore` stays in sync with `.gitignore`.** Both must
   exclude `.env` and `data/*` (`!data/.gitkeep` kept) - a Docker build
   context that includes `.env` or real `data/` content bakes secrets into
   an image layer, which is worse than a git commit since
   `.github/workflows/cd.yml` pushes images to a registry (`ghcr.io`).

4. **Check `evals/` and `scripts/` for accidental real-data fixtures.**
   Tests should use synthetic data via `JOB_HUNTER_DATA_DIR` /
   `JOB_HUNTER_ENV_FILE` overrides (see `evals/unit/conftest.py`), never a
   copy of the user's real resume or application history checked in as a
   test fixture.

5. **If this is pre-push**, also run `git log --stat origin/main..HEAD` to
   check commits already made on the branch, not just the current diff -
   a secret added and later "removed" in a later commit is still in history
   and already a problem by the time it's pushed.

## If something is found

Stop and tell the user exactly what was found and where (file:line or
commit), rather than silently fixing it - a tracked secret may need
rotation (for an API key) or `git filter-repo`/history rewrite (if already
pushed), both of which are the user's call, not something to do
unilaterally.
