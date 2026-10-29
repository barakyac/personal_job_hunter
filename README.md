# Job Hunter Dashboard

A personal Streamlit dashboard for tracking job search activity: positions
saved for later and positions applied to, each with dates and links.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
streamlit run app.py
```

## Data

Positions are stored as JSON, no database required:

- `data/saved_positions.json` — roles you're considering, with the date saved.
- `data/applied_positions.json` — roles you've applied to, with date applied
  and status (Applied, Interviewing, Offer, Rejected, Withdrawn).

Edit entries directly in the app's tables, or move a saved position to
Applied Positions with the "Move to Applied Positions" action on the Saved
Positions page.

## Adding entries by sharing a link with Claude

Give Claude a job posting URL in chat ("save this" or "I applied to this") and
it will fetch the page, pull out the company and title, and append the entry
for you via:

```bash
python scripts/add_entry.py saved --company "..." --title "..." --link "..." [--location ...] [--salary ...]
python scripts/add_entry.py applied --company "..." --title "..." --link "..." --status Applied
```

It skips adding a link that's already tracked (in either file) unless you
pass `--force`.

## Testing

```bash
pip install -r requirements-dev.txt
pytest evals/unit          # fast, deterministic, runs in CI
pytest evals/llm -m llm    # calls your local Ollama model; skipped if it's not running
```

GitHub Actions (`.github/workflows/ci.yml`) runs `evals/unit` on every push and
PR. `evals/llm` isn't run in CI since it needs a local Ollama instance.

## Pages

- **Dashboard** — counts by status and two charts: cumulative applications
  over time, and a breakdown by status.
- **Saved Positions** — editable table of saved roles (add/edit/delete rows
  directly), plus a control to move a role into Applied Positions.
- **Applied Positions** — editable table of applied roles, including status.
