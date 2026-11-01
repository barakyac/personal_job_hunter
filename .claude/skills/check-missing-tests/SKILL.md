---
name: check-missing-tests
description: Audit this job hunter dashboard for src/ modules or functions with no corresponding unit test. Use when the user asks what's missing test coverage, wants a test-coverage audit, or asks whether a recent change has tests.
---

# Finding missing tests in personal_job_hunter

This project has no coverage tool wired in - the convention is simply
`src/<name>.py` <-> `evals/unit/test_<name>.py`, one test file per module,
driven through `streamlit.testing.v1.AppTest` for view modules and plain
unit tests for everything else.

## Steps

1. **List the modules.** `ls src/*.py` (exclude `__init__.py`).
2. **List the test files.** `ls evals/unit/test_*.py`.
3. **Match by name.** `src/foo.py` should have `evals/unit/test_foo.py`.
   Flag any `src/` module with no matching test file at all - that's a
   total gap, not just thin coverage.
4. **For modules that do have a test file**, skim the module's public
   functions/classes against the test file's test names to spot obvious
   untested branches (e.g. an error path, a new parameter, a new provider
   case) rather than assuming a test file means full coverage.
5. **Check `scripts/`.** The CLI scripts (`add_entry.py`,
   `analyze_fit_ollama.py`, `analyze_fit_single.py`, `update_fit.py`) are
   thin wrappers around `src/` functions and are not required to have their
   own tests, but confirm the `src/` logic they call *is* covered - don't
   flag the script itself as a gap.
6. **Don't flag `evals/llm/`** as filling a unit-test gap - it calls the
   real Ollama model and is a different (slower, non-deterministic) tier,
   not a substitute for a deterministic `evals/unit` test.

## Reporting

List gaps as `src/<module>.py` -> no `evals/unit/test_<module>.py`, most
foundational modules first (`storage.py` mattering more than a thin view).
If the user asks you to fix gaps rather than just report them, write tests
following the existing style in a neighboring test file (same fixtures,
same `JOB_HUNTER_DATA_DIR` isolation pattern) rather than introducing a new
testing approach.
