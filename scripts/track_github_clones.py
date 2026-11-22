#!/usr/bin/env python3
"""Track GitHub clone traffic for this repo over time.

GitHub's traffic API (repos/{owner}/{repo}/traffic/clones) only reports a
rolling 14-day window, and requires push access to the repo - it resets as
days age out, so this appends each day's numbers into a history file
instead of querying it fresh every time. Without that, older days are lost
for good once they fall off GitHub's window.

Run locally (writes to data/github_clones_history.json, gitignored):
    python scripts/track_github_clones.py
    python scripts/track_github_clones.py --summary   # print only, no fetch

Run in CI against a committed file (see .github/workflows/track-traffic.yml):
    python scripts/track_github_clones.py --history-file .github/traffic/clones_history.json

No non-stdlib dependencies on purpose, so CI doesn't need to install this
project's requirements.txt just to run a weekly traffic snapshot. Requires
the `gh` CLI, authenticated as a user/token with push access to the repo.
"""
import argparse
import json
import os
import subprocess
from pathlib import Path

REPO = "barakyac/personal_job_hunter"


def _default_history_file() -> Path:
    base = Path(os.environ.get("JOB_HUNTER_DATA_DIR") or Path(__file__).resolve().parent.parent / "data")
    return base / "github_clones_history.json"


def load_history(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_history(path: Path, history: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(history, indent=2, sort_keys=True), encoding="utf-8")


def fetch_traffic() -> dict:
    result = subprocess.run(
        ["gh", "api", f"repos/{REPO}/traffic/clones"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"gh api call failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def merge(history: dict, traffic: dict) -> dict:
    for day in traffic.get("clones", []):
        date_key = day["timestamp"][:10]
        # GitHub re-reports the same day while it's still in the trailing
        # 14-day window - keep the latest numbers it gives for that day
        # rather than the first ones seen, since a day isn't "final" until
        # it ages out of the window.
        history[date_key] = {"count": day["count"], "uniques": day["uniques"]}
    return history


def print_summary(history: dict) -> None:
    if not history:
        print("No clone data recorded yet. Run without --summary to fetch some.")
        return
    total_clones = sum(d["count"] for d in history.values())
    # Upper-bound estimate only: GitHub's "uniques" is anonymized per day,
    # not a stable identity across days, so the same person cloning on two
    # different days is counted twice here - there's no way to get a true
    # distinct-people total from this API.
    unique_estimate = sum(d["uniques"] for d in history.values())
    print(f"Days tracked: {len(history)} ({min(history)} to {max(history)})")
    print(f"Total clones: {total_clones}")
    print(f"Unique-cloners estimate (upper bound, see note below): {unique_estimate}")
    print()
    print("Note: GitHub only reports anonymized unique visitors per day, not a stable")
    print("identity across days - someone who clones on two different days is counted")
    print("twice in the estimate above. There's no way to get a true distinct-person")
    print("total from GitHub's traffic API.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--summary", action="store_true", help="print the summary without fetching new data")
    parser.add_argument(
        "--history-file", type=Path, default=None,
        help="where to store the merged history (default: data/github_clones_history.json)",
    )
    args = parser.parse_args()
    history_file = args.history_file or _default_history_file()

    history = load_history(history_file)
    if not args.summary:
        history = merge(history, fetch_traffic())
        save_history(history_file, history)
    print_summary(history)


if __name__ == "__main__":
    main()
