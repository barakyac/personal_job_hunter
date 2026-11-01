---
description: Run a combined code-review, secrets-check, missing-tests, and ui-change pass over only uncommitted/staged changes plus commits on this branch not on main (read-only).
---

# New-changes review

This reviews **only what's new on this branch**, not the whole codebase.
Review only - do not edit any file as part of this command.

## Establish scope

Run both of these and concatenate their output - together they're the full
scope:

```bash
git diff HEAD          # uncommitted + staged changes, working tree vs last commit
git diff main...HEAD   # commits on the current branch that aren't on main
```

(If the current branch *is* main, the second command is empty - that's
expected, not an error.)

If both commands produce no output, there is nothing to review: say so
plainly and stop, don't launch the reviewers.

Otherwise, state the combined diff plainly before continuing - the four
reviewers launched next are fresh agents and need the actual diff text (or
the exact commands above) restated verbatim in their prompts, not a
reference back to this output.

## Run the review

Load the `combined-review` skill with the Skill tool and follow it against
the diff just established.
