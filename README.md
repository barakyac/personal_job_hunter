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

## Matching Jobs

The "Matching Jobs" page collects jobs that match your profile from three
sources into one list (`data/matched_jobs.json`), separate from Saved Jobs so
a scan never floods it:

- **Job-alert emails.** "Scan job-alert emails" reads your recent LinkedIn Job
  Alerts and Glassdoor emails through the same read-only Gmail connection as
  Mail Inbox.
- **Google Jobs.** "Search Google Jobs" runs one search per target title
  through SerpAPI's `google_jobs` engine. Set `SERPAPI_API_KEY` in `.env` or
  `.streamlit/secrets.toml`. Google's own Custom Search JSON API is closed to
  new customers and shuts down on January 1, 2027, so it isn't used.
- **Claude in Chrome.** Ask Claude to "find matching jobs". The
  `find-matching-jobs` skill (`.claude/skills/`) has it browse LinkedIn's
  "Top job picks for you", LinkedIn search and Google in your own signed-in
  Chrome, then add what it finds with:
  ```bash
  python scripts/add_match.py --source linkedin --json data/agent/matches_linkedin.json
  python scripts/add_match.py --source google --company "..." --title "..." --link "..." [--description "..."]
  ```

Set your target titles, location, extra keywords and exclude keywords under
"What counts as a match". Anything already in Matching Jobs, Saved Jobs or
Applied is skipped, including a match you dismissed. LinkedIn's different
link shapes for one posting are treated as the same job. "Score fit" rates
new matches against your resume with the same Ollama prompt Saved Jobs
uses. "Save job" copies a match into Saved Jobs, keeping its description and
fit score.

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
  -e SERPAPI_API_KEY=... \
  -e GOOGLE_OAUTH_CLIENT_ID=... \
  -e GOOGLE_OAUTH_CLIENT_SECRET=... \
  -e GOOGLE_OAUTH_REDIRECT_URI=... \
  -e GMAIL_TOKEN_ENCRYPTION_KEY=... \
  -v "$(pwd)/data:/app/data" \
  job-hunter
```

Note: the Ollama chat provider needs `http://localhost:11434` reachable from
inside the container (e.g. `--add-host=host.docker.internal:host-gateway`
and point `ollama_client.OLLAMA_URL` at it) — it won't work out of the box in
Docker. Use the Claude/ChatGPT provider instead when running containerized.

## Mail Tracking (Gmail, read-only)

The "Mail Tracking" page scans Gmail for messages about companies you've
applied to (flagging ones that look like rejections) and for new job-alert
emails (LinkedIn Job Alerts, Glassdoor Jobs), so you can spot updates
without leaving the dashboard. It connects via Google's own OAuth sign-in
(a popup opened by the "Connect with Google" button) and only ever
requests the `gmail.readonly` scope (plus `openid`/`email` to show which
address is connected) — it cannot send, modify, or delete anything. Once
connected, it scans automatically on page load and surfaces a banner at
the top when it finds a likely rejection or a new opportunity; a "Rescan"
button on each section refreshes on demand. The status bar shows the
connected address and when it last synced, with "Reconnect" (re-authorize
after an expired/revoked token) and "Disconnect Gmail" actions.

As an end user, all you do is click "Connect with Google" in the popup —
no Google Cloud project, OAuth client, or file upload required of you.
That's a one-time step the app operator (below) does once for the app
itself.

This app runs as a personal Google OAuth app: published ("In production")
but intentionally never submitted for Google's verification review. See
the note below on what that means for who can connect.

### Developer setup (one-time, not shown to end users)

Before anyone can click "Connect with Google," the app operator configures
this app's own OAuth client, using Google Cloud Console's **Google Auth
Platform** section:

1. In [Google Cloud Console](https://console.cloud.google.com/), create a
   project (or use an existing one) and enable the **Gmail API**.
2. Go to **Google Auth Platform → Audience** and choose the **External**
   user type (unless you're on Google Workspace).
3. Go to **Google Auth Platform → Data Access** and add two scopes:
   `.../auth/userinfo.email` (the first row on that page) and
   `.../auth/gmail.readonly` — type `gmail.readonly` into the Filter box at
   the top of the scope picker to find it; its description reads "View
   your email messages and settings".
4. Go to **Google Auth Platform → Clients**, and create an OAuth client ID
   of type **Web application** (not Desktop — `streamlit-oauth` drives the
   consent flow from the browser via a redirect URI, not a local loopback
   server). Add the exact URL this app runs at — `http://localhost:8501`
   for local dev, or your deployed app's URL — to **both** "Authorised
   JavaScript origins" and "Authorised redirect URIs". Google issues a
   client ID and client secret; copy both.
5. Generate a token-encryption key and put all three values in
   `.streamlit/secrets.toml` (gitignored):
   ```bash
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```
   ```toml
   GOOGLE_OAUTH_CLIENT_ID = "..."
   GOOGLE_OAUTH_CLIENT_SECRET = "..."
   GOOGLE_OAUTH_REDIRECT_URI = "http://localhost:8501"  # must match step 4 exactly
   GMAIL_TOKEN_ENCRYPTION_KEY = "..."  # output of the command above
   ```
   `GOOGLE_OAUTH_REDIRECT_URI` defaults to `http://localhost:8501` if
   unset; the other three have no default. Env vars (`.env`, or `-e` in
   Docker) of the same names also work as a fallback — `st.secrets` is
   just read first. The "Connect with Google" button won't work until all
   three are set — `GMAIL_TOKEN_ENCRYPTION_KEY` is what each user's saved
   Gmail token is encrypted with at rest (`data/gmail_token.json`, already
   gitignored).
6. Go to **Google Auth Platform → Audience** and click **Publish app**.
   **Do not** click "Prepare for verification" / "Submit for verification"
   — see below for why that's intentionally skipped. If you'd rather stay
   in **Testing** for now, add each Gmail address that should be able to
   connect under **Test users** on that same Audience page instead —
   skipping both publishing and test users means "Connect with Google"
   will fail for everyone.

**On Google's verification requirement — who can actually connect:**
`gmail.readonly` is a Google "restricted" scope, and this app is published
but unverified:
- Every user (including you) will see Google's **"Google hasn't verified
  this app"** warning the first time they click "Connect with Google."
  Click **Advanced → Go to Mail Tracking (unsafe)** to proceed — this is
  expected for an unverified app and doesn't mean anything is actually
  wrong.
- Google caps unverified apps requesting a restricted/sensitive scope at
  **under 100 users total**, regardless of publishing status — fine for
  personal or small-group use, not for a public launch.
- Publishing ("In production" instead of "Testing") means you don't have
  to add each Gmail address as an explicit test user, and refresh tokens
  don't expire on Testing's ~7-day cycle.
- Actually passing Google's verification (to remove the warning for
  everyone) needs a privacy policy, a demo video, and likely a third-party
  CASA security assessment — out of scope for personal use, which is why
  step 6 above stops at "Publish" and never submits for review.

## Pages

- **Saved Positions** — editable table of saved roles (add/edit/delete rows
  directly), plus a control to move a role into Applied Positions.
- **Applied Positions** — editable table of applied roles, including status.
- **Mail Tracking** — read-only scan of Gmail for application updates and
  new job-alert emails.
