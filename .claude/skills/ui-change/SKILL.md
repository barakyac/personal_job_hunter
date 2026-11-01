---
name: ui-change
description: Review a Streamlit UI change in this job hunter dashboard (a view in src/*_view.py, app.py, or .streamlit/config.toml) against the app's established UI conventions - layout, messaging, confirmation safety, and chart styling. Use when the user asks to review a UI/UX change, a new view, or whether a screen matches the rest of the app.
---

# UI-change review for personal_job_hunter

This is a small Streamlit app with no design system or visual test tooling -
consistency is enforced by eye, against the patterns already established
across `src/*_view.py`. This skill is about reviewing a UI change for
"does this feel like the rest of the app and not surprise the user",
not pixel-level design.

## What to check

1. **Page structure.** Views open with `st.header(...)`, often a
   `st.caption(...)` underneath explaining the page, and use `st.divider()`
   between distinct sections (see `resume_view.render`). A new view that
   skips the header/caption pattern,
   or uses `st.title` where every other page uses `st.header`, will look
   inconsistent.

2. **Feedback messages.** The app consistently uses `st.error(...)` for a
   rejected action (missing input, upstream failure), `st.success(...)`
   after a successful write, `st.info(...)` for an empty/neutral state, and
   `st.warning(...)` for a partial failure inside a batch (see
   `resume_view._run_batch_analysis`). A new action that silently succeeds
   or fails without one of these, or that reuses `st.error` for a non-error
   empty state, breaks that convention.

3. **Destructive and bulk actions get confirmation or are easy to undo.**
   `board_view`'s stage-change dropdown and `saved_view`'s "Move to Applied
   Positions" are the existing bar: no raw silent-delete button. A new
   "Remove"/"Delete" action should match `resume_view.render`'s pattern
   (plain button, immediate but clearly-labeled, single record) rather than
   introducing a new unconfirmed bulk-delete.

4. **State mutations trigger `st.rerun()` when the layout needs to reflect
   it immediately** (adding/removing a list item, moving a record between
   files) - see the `st.rerun()` call sites in `saved_view.py`,
   `board_view.py`, `applied_view.py`, `chat_view.py`, `resume_view.py`. A
   mutation with no rerun that leaves stale widgets on screen until the next
   natural rerun is a bug, not a style choice.

5. **Widget keys are stable and collision-free**, especially inside loops
   over records (`f"remove_personal_{path.name}"`,
   `f"in_a_call_btn_{i}"`-style per-record keys). A new per-record widget
   with no unique key, or a key derived from something that can collide
   (e.g. company name alone when duplicates are allowed), will cause
   Streamlit state to leak between rows.

6. **Status colors come from `storage.STATUS_COLORS`**, not an ad hoc
   value - `board_view.py` already pulls stage-card colors from there. A
   new piece of UI that needs a status-identity color (a badge, a chart, a
   chip) should reuse that dict rather than inventing its own. There are no
   charts in the app right now (Plotly was only used by the since-removed
   dashboard page) - if one is added back, follow the `dataviz` skill's
   palette workflow and keep it in its own `_style_layout`-style helper
   rather than inlining styling into the render function.

7. **The floating "Show Assistant" button's CSS hack
   (`div.st-key-show_assistant_btn` in `app.py`) is the one place fixed
   positioning is used.** A new UI element reaching for `unsafe_allow_html`
   / fixed CSS positioning to solve a layout problem is a smell - check
   whether `st.columns`/`st.container(border=True)` would do it the way
   every other view already does.

8. **Labels and placeholders read like the rest of the app**: short,
   direct, no trailing periods on button labels, `st.caption` used for
   secondary explanatory text rather than cramming it into the label itself.

## Reporting

Findings are about *inconsistency with the existing app*, not generic UX
best practice - cite the existing view/line the change diverges from, not
just "this could be better." If the change is small and plainly in line
with existing patterns, say so briefly rather than inventing nitpicks.
