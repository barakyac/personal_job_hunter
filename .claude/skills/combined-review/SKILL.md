---
name: combined-review
description: Shared process for running code-review, secrets-check, check-missing-tests, and ui-change as four parallel review passes over a scope already established in this conversation, merged into one deduped report. Loaded by /general-reviewer and /new-changes-reviewer after each has stated its own scope - don't invoke this without a scope already on the table.
---

# Combined review process

Runs four independent review passes over whatever scope was just stated in
this conversation (a file list for a full-codebase review, or diff text for
a changes-only review) and merges them into one report. Review only -
nothing here edits, creates, or deletes a file.

## 1. Launch four parallel reviewers

In a single message, launch four `general-purpose` agents with the `Agent`
tool (one call each, sent together so they run concurrently - never one at
a time). Each is a fresh agent with no memory of this conversation, so
restate the scope in full inside every prompt rather than referencing "the
files we discussed." All four get the same scope; only the skill each one
loads differs:

- **Reviewer A** - loads the `code-review` skill.
- **Reviewer B** - loads the `secrets-check` skill.
- **Reviewer C** - loads the `check-missing-tests` skill, with one explicit
  override on top of it: report gaps and say what the missing test(s)
  should cover, but do **not** write any test code - even though that
  skill's own "if asked to fix gaps" branch exists, this review hasn't been
  asked for that.
- **Reviewer D** - loads the `ui-change` skill. If the scope touches no
  `src/*_view.py`, `app.py`, or `.streamlit/` file, it should say so and
  report nothing rather than manufacturing a finding.

Every agent's prompt must spell out:
1. The exact scope - the file list, or the actual diff text (or the exact
   `git diff` command to run), not a paraphrase.
2. "Load the `<skill-name>` skill with the Skill tool first, then follow
   it." (name only that one skill).
3. "Read-only review - do not edit, create, or delete any file."
4. The fields to return per finding: `file`, `line` (or range), `severity`,
   `what's wrong`, `why it matters`, `suggested fix` - a short structured
   list, not prose - plus this severity scale:
   - **Critical** - a confirmed bug that breaks behavior, a tracked/leaked
     secret, or a real security vulnerability.
   - **Warning** - a likely-but-unconfirmed bug, a meaningful gap in
     foundational logic (e.g. `storage.py`, a provider client), or an
     inconsistency that will mislead a user or future reader.
   - **Suggestion** - a minor inconsistency, thin (not missing) coverage,
     or a nice-to-have.

## 2. Merge the four reports

1. Flatten every returned finding into one list.
2. **Dedupe.** Two findings are the same finding if they point at the same
   file and the same underlying issue, even when two different skills
   caught it independently (e.g. `secrets-check` and `code-review` both
   flag a hardcoded key at the same line) - keep one, drop the rest,
   preferring whichever has the more specific suggested fix.
3. Group what remains by severity (Critical, then Warning, then
   Suggestion); within a group, put foundational files (`storage.py`,
   provider clients, CI/CD config) ahead of thin UI-only findings.

## 3. Report

```
## Summary
<2-3 sentences: overall verdict for this scope, and the headline risk if any>

## Critical
- **<file>:<line>** - <what's wrong>. <why it matters>. Fix: <suggested fix>
(or "None." if empty)

## Warning
...(same shape, or "None.")

## Suggestion
...(same shape, or "None.")
```

If all four agents come back clean, say that plainly in the summary rather
than padding the list with invented nitpicks.
