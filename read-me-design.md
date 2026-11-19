# Design System Documentation

Component docs for the job-hunter Streamlit dashboard, covering patterns repeated across `src/saved_view.py`, `src/resume_view.py`, and `src/mail_view.py`.

## Component: Save / Apply Action Buttons

### Description
The row of action buttons on the Saved Positions page (`src/saved_view.py`) that move a job posting through its lifecycle: save edits, score fit against the resume, close a posting, and promote it to Applied Positions. These aren't a single reusable widget — they're a consistent *pattern* of `st.button` + `st.rerun()` repeated across the page, each gated by its own disabled/empty-state logic.

### Variants
| Variant | Use When |
|---------|----------|
| `type="primary"` (filled) | The single most likely next action in a section — "Save changes", "Move to Applied Positions" |
| Default (outlined) | Secondary/parallel actions — "Calculate fit", "Close" |

### Props / Properties
| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `key` | str | — | Always unique per row (`f"close_posting_{i}"`) to avoid Streamlit widget collisions in a loop |
| `type` | `"primary"` \| `"secondary"` | secondary | Picks the filled vs. outlined variant |
| `disabled` | bool | `False` | Used instead of hiding the button so layout doesn't shift (e.g. nothing applicable) |

### States
| State | Visual | Behavior |
|-------|--------|----------|
| Default | Outlined/filled per variant | — |
| Hover/Active | Streamlit default | — |
| Disabled | Dimmed, no pointer | Non-interactive (e.g. "Use uploaded file" before a file is chosen) |
| Loading | Replaced by `st.spinner`/`st.progress` + `st.empty()` status text | Long-running Ollama calls show per-item progress, not a spinner on the button itself |
| Success/Error | Button unchanged; `st.success`/`st.warning`/`st.error` rendered below, then `st.rerun()` | Feedback is a toast-like message, not inline on the button |

### Accessibility
- **Role**: native HTML `<button>` via Streamlit — standard button semantics, no custom ARIA needed
- **Keyboard**: Tab to focus, Enter/Space to activate — Streamlit default, no overrides in this codebase
- **Screen reader**: Announced by its visible label text (e.g. "Calculate fit (Ollama llama3)") — the model name is baked into the label itself so screen-reader users get the same information sighted users do, rather than relying on a tooltip

### Do's and Don'ts
| ✅ Do | ❌ Don't |
|------|---------|
| Disable a button when its action can't currently apply (`disabled=new_status == current_status`) | Hide the button entirely, which shifts layout and hides *why* it's unavailable |
| Pair every mutating button with `storage.save_*()` then `st.rerun()` so the UI reflects the new on-disk state immediately | Mutate `st.session_state` only and skip `st.rerun()`, leaving stale data on screen |
| Put the model name in the label when an LLM call is involved (`f"Calculate fit (Ollama {ollama_client.DEFAULT_MODEL})"`) | Make a silent background call the user can't attribute to a cost/model |
| Show progress per-item for batch actions (`st.progress` + `st.empty()` status text) | Block on one spinner for a multi-item batch with no incremental feedback |

### Code Example
```python
if st.button(f"Calculate fit (Ollama {ollama_client.DEFAULT_MODEL})", key="calc_fit_saved_btn"):
    ...
    for n, i in enumerate(targets):
        ...
        storage.save_saved(records)   # saved incrementally, not just at the end
        progress.progress((n + 1) / len(targets))
    st.rerun()
```

---

## Component: Fit Score Display

### Description
Read-only presentation of an AI-generated resume-to-job fit assessment (`fit_score` 1–10 + `fit_notes` free text), shown on Saved Positions (editable, via `st.data_editor`) and Personal Work Info / `_render_fit_list` (card view). Written once by `fit_analysis.analyze()` and never hand-edited except through the data editor's numeric column.

### Variants
| Variant | Use When |
|---------|----------|
| Editable grid cell (`NumberColumn`/`TextColumn` in `st.data_editor`) | Saved Positions table — user can see and manually override the score |
| Read-only card (`_render_fit_list` in `resume_view.py`) | Fit review lists (Saved Positions, First Call applications) where editing isn't the point |

### Props / Properties
| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `fit_score` | int (1–10) or `None`/`""` | unset | Stored in the record JSON; `NumberColumn(min_value=1, max_value=10, step=1)` in the editor |
| `fit_notes` | str | `""` | Free-text rationale from the model, rendered via `st.caption` |

### States
| State | Visual | Behavior |
|-------|--------|----------|
| Not yet scored | No "Fit score" line; caption reads "No fit analysis yet — ask Claude to analyze this one against your resume." | Sorts last in Saved Positions (`_fit_score_sort_key` returns `inf`) |
| Scored | `Fit score: **N**` + notes caption | Sorts by score descending within its open/closed group |
| Analyzing (batch) | Score cell unchanged; page shows `st.progress` + "Analyzing {company} - {title}..." status text | Each record is saved right after its own analysis completes, so a crash mid-batch keeps earlier results |
| Error (one job in batch) | `st.warning(f"{company}: {exc}")` after the batch | Does not stop the rest of the batch — collected and shown at the end |

### Accessibility
- **Role**: Plain text/markdown — no custom widget, so no ARIA role needed beyond what `st.markdown`/`st.caption` produce
- **Keyboard**: In the editable grid, standard `st.data_editor` cell navigation (arrow keys, Tab, Enter to edit)
- **Screen reader**: Announced as plain text: "Fit score: 8" then the notes caption — no icon-only or color-only signal, so nothing is lost without sight

### Do's and Don'ts
| ✅ Do | ❌ Don't |
|------|---------|
| Treat `None`/`""` as "not yet scored" with `fit_score in (None, "")`, not `0`, since 0 isn't a valid score | Default an unscored job to `0`, which would sort it as the *worst* fit instead of unscored |
| Skip already-closed/already-scored records in batch targets (`saved_view.py:85-88`) | Re-score a closed posting or burn an Ollama call re-analyzing something already scored |
| Save after each item in a batch, not only at the end | Hold all results in memory and lose everything on an interrupted batch |

### Code Example
```python
fit_score = record.get("fit_score")
if fit_score not in (None, ""):
    st.markdown(f"Fit score: **{fit_score}**")
st.caption(fit_notes or "No fit analysis yet — ask Claude to analyze this one against your resume.")
```

---

## Component: Mail-Match Job Alert Card

### Description
The per-message card in Mail Tracking (`src/mail_view.py`, `_render_opportunity`) that shows one Gmail job-alert email and lets the user add it as a Saved Position or dismiss it — the same pattern repeats (with different copy/state) for `_render_unlisted_application` (untracked application emails) and `_render_message` (per-company scan results).

### Variants
| Variant | Use When |
|---------|----------|
| Job-alert opportunity (`_render_opportunity`) | A new job-posting digest email not yet tracked anywhere — offers "Add to Saved Positions" |
| Unlisted application (`_render_unlisted_application`) | An application-confirmation email for a company not tracked at all — offers "Add to Applied Positions" directly (skips Saved, since the application was already sent) |
| Plain message (`_render_message`) | A scan hit for an already-tracked company, shown inside that company's expander — no action buttons, just the email with a ⚠️ prefix if it looks like a rejection |

### Props / Properties
| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `msg["subject"] / ["sender"] / ["date"] / ["snippet"]` | str | — | Rendered as markdown bold subject + sender/date line + caption snippet |
| `msg["looks_like_rejection"]` | bool | `False` | Prefixes the subject with "⚠️ " |
| action state (`OPPORTUNITY_ACTIONS_KEY` / `UNLISTED_ACTIONS_KEY`) | `"added"` \| `"skipped"` \| `"dismissed"` \| unset | unset | Per-message session-state flag that permanently swaps the card's action row for a static caption once resolved |

### States
| State | Visual | Behavior |
|-------|--------|----------|
| Pending (unset) | "Not yet tracked - add it as a new saved position, or dismiss it." + Add/Dismiss buttons | Both buttons live |
| Added | Caption only: "Added to Saved Positions." | No buttons — action is terminal for this message |
| Skipped (already tracked) | Caption: "Already tracked in Saved or Applied Positions - not added again." | Set automatically inside `_add_opportunity_as_saved` when the company is already known, not by user choice |
| Dismissed | Caption: "Dismissed." | No buttons — terminal, same as Added |
| Loading (single add) | Button row replaced by `st.spinner(f"Extracting fields with Ollama {job_extract.DEFAULT_MODEL}...")` | Only while that one card's extraction call is in flight |
| Loading (bulk add) | Page-level `st.progress` + status text above all cards | One pass over every pending card; per-card buttons stay inert until it completes and reruns |

### Accessibility
- **Role**: Markdown text block + two native buttons — no custom ARIA
- **Keyboard**: Tab/Enter on Add/Dismiss buttons, standard Streamlit focus order top-to-bottom
- **Screen reader**: Subject line is read with the "⚠️ " prefix as literal text when `looks_like_rejection` is true — relies on the emoji being spoken or at least not suppressing the rest of the line; no separate `aria-label` carries the warning semantically

### Do's and Don'ts
| ✅ Do | ❌ Don't |
|------|---------|
| Make "added"/"skipped"/"dismissed" terminal (hide the buttons once set) so a user can't double-add the same email | Leave Add/Dismiss live after an action — risks duplicate records on a rerun |
| Re-check `_company_already_tracked()` at action time, not just at query time, since a digest email can be about a different company than the Gmail search assumed | Trust the Gmail query's own exclusion filter as the sole guard against duplicates |
| Fall back to an empty `link` rather than block the add when the posting-link lookup fails (`except Exception: link = ""`) | Raise and lose the whole "add as saved position" action over a best-effort link fetch failing |
| Use `f"...{id}"`-suffixed keys per message so cards in a loop don't collide | Reuse a bare key like `"add_opportunity_btn"` across all cards in the loop |

### Code Example
```python
action = st.session_state.get(OPPORTUNITY_ACTIONS_KEY, {}).get(msg["id"])
if action == "added":
    st.caption("Added to Saved Positions.")
    return
...
if st.button(f"Add to Saved Positions (Ollama {job_extract.DEFAULT_MODEL})", key=f"add_opportunity_{msg['id']}"):
    with st.spinner(f"Extracting fields with Ollama {job_extract.DEFAULT_MODEL}..."):
        company, added = _add_opportunity_as_saved(msg)
    st.rerun()
```

---

## Cross-cutting observation

All three components share the same **button → mutate storage → `st.rerun()`** idiom and the same **session-state action-flag** idiom for "already handled" cards — neither is factored into a shared helper, so each view reimplements it slightly differently (e.g. `saved_view.py`'s close/apply buttons don't use an action-flag pattern at all, relying on the record disappearing from `open_records` instead). Worth a shared convention doc if a fourth place needs this. **Still open** — see Audit Action 2 below.

---

## System Audit (2026-11-19)

**Components reviewed:** 11 | **Issues found:** 7 | **Score at audit time:** 72/100

Scope: `app.py` and all `src/*_view.py` modules. Tokens are centralized well (`storage.STATUS_COLORS`, `storage.POSTING_STATUS_OPTIONS`) — zero hardcoded hex colors outside `storage.py`. The gaps were mostly in copy/verb consistency, column-layout consistency, and one safety pattern (destructive actions with no confirmation step).

### Naming Consistency
| Issue | Components | Recommendation |
|-------|------------|----------------|
| Inconsistent verb for "add this record to a list" | "Add to Saved Positions" (mail_view), "Add to Applied Positions" (mail_view), "Move to Applied Positions" (saved_view) | **"Add to \<destination\>"** when the source is external (email); **"Move to \<destination\>"** only when it leaves another tracked list (Saved → Applied). Current usage already follows this split — documented here so new buttons don't drift. |
| `st.header` as page title vs `st.subheader` reused for both major sections *and* minor inline counters | `mail_view.py` | Acceptable as-is — `st.subheader` means "section," not "important text." Noted so it isn't reached for emphasis instead. |
| Three different column ratios for the same "label + narrow action" layout: `[4, 1]` vs `[3, 1]` vs the reversed `[1, 6]` | `resume_view.py`, `mail_view.py`, `saved_view.py` | **Fixed**: `saved_view.py`'s close-posting row now uses `[4, 1]` with label-then-action order, matching `resume_view.py`'s remove-document row. `mail_view.py`'s `[3, 1]` status+submit row was left alone — it's a select+submit form row, not this label/action display pattern. |

### Token Coverage
| Category | Defined | Hardcoded Values Found |
|----------|---------|----------------------|
| Colors | `storage.STATUS_COLORS` (8 values) + 1 theme `primaryColor` | 0 outside `storage.py` |
| Spacing | Not formalized — `st.columns([...])` ratios chosen ad hoc | 6 remaining distinct ratio literals across files (down from 7 after the fix above) |
| Typography | None custom — relies on Streamlit's built-in scale | 0, aside from two deliberate, commented CSS overrides (`board_view.py` dialog width, `app.py` floating button position) |

### Priority Actions
1. **Fixed** — Added a confirmation dialog (reusing the `@st.dialog` pattern already established by `board_view.py`'s call-notes dialog) before three previously one-click, irreversible actions:
   - "Disconnect Gmail" → `mail_view._confirm_disconnect_dialog()` / `mail_view._disconnect_gmail()`
   - "Reset Gmail setup" → `mail_view._confirm_reset_dialog()` / `mail_view._reset_gmail_setup()`
   - "Remove" supporting document → `resume_view._confirm_remove_dialog()` / `resume_view._remove_personal_file()`

   Each destructive action was extracted into its own plain function so it stays unit-testable directly — AppTest can't drive a click-to-confirm round trip *inside* an already-open `st.dialog` (same limitation `board_view.py`'s own tests already document), so each dialog now has one test asserting it opens without acting, and one test asserting the extracted function performs the action.
2. **Open** — Collapse the repeated "button → mutate storage → `st.rerun()`" and "session-state action-flag" idioms into shared helpers (see Cross-cutting observation above). Not done in this pass — it's a broader refactor across every view file, not a targeted fix, and deserves its own review rather than riding along with an audit.
3. **Fixed** — Standardized the wide-label/narrow-action column ratio to `[4, 1]`, label-then-action order; `saved_view.py`'s close-posting row was the outlier and now matches.
