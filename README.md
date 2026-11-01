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
it will fetch the page, pull out the company, title, and full job description,
and append the entry for you via:

```bash
python scripts/add_entry.py saved --company "..." --title "..." --link "..." [--location ...] [--salary ...] [--description "..."]
python scripts/add_entry.py applied --company "..." --title "..." --link "..." --status Applied [--description "..."]
```

The job description is stored with the entry and reused by "Calculate fit"
instead of re-fetching the page.

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

## Docker / CD

`.github/workflows/cd.yml` runs unit evals, then builds and pushes an image to
`ghcr.io/<owner>/<repo>` (tagged `latest` and with the commit SHA) on every
push to `main`.

To run the image yourself:

```bash
docker build -t job-hunter .
docker run -p 8501:8501 \
  -e ANTHROPIC_API_KEY=... \
  -e OPENAI_API_KEY=... \
  -v "$(pwd)/data:/app/data" \
  job-hunter
```

Note: the Ollama chat provider needs `http://localhost:11434` reachable from
inside the container (e.g. `--add-host=host.docker.internal:host-gateway`
and point `ollama_client.OLLAMA_URL` at it) — it won't work out of the box in
Docker. Use the Claude/ChatGPT provider instead when running containerized.

## Pages

- **Saved Positions** — editable table of saved roles (add/edit/delete rows
  directly), plus a control to move a role into Applied Positions.
- **Applied Positions** — editable table of applied roles, including status.
