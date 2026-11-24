#!/usr/bin/env python3
"""Add jobs Claude found (browsing LinkedIn or Google in your Chrome) to the
Matching Jobs page. Skips anything already in Matching Jobs, Saved Jobs or
Applied, and anything hitting the profile's exclude keywords.

One job:

    python scripts/add_match.py --source linkedin --company Acme --title "Backend Engineer" \
        --link https://www.linkedin.com/jobs/view/123/ --location "Tel Aviv" \
        --description "Full job description..." --detail "LinkedIn: Top job picks for you"

Many at once, from a JSON file holding a list of objects with the same keys
(company, title, link, location, salary, description, source_detail):

    python scripts/add_match.py --source google --json data/agent/matches.json
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import job_matching, storage

SOURCES = {
    "linkedin": storage.MATCH_SOURCE_LINKEDIN,
    "google": storage.MATCH_SOURCE_GOOGLE_CLAUDE,
}


def main(argv: list[str] | None = None) -> dict:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", choices=sorted(SOURCES), required=True)
    parser.add_argument("--json", help="path to a JSON list of jobs")
    parser.add_argument("--company", default="")
    parser.add_argument("--title", default="")
    parser.add_argument("--link", default="")
    parser.add_argument("--location", default="")
    parser.add_argument("--salary", default="")
    parser.add_argument("--description", default="")
    parser.add_argument("--detail", default="", help="where it was found, e.g. a search query")
    args = parser.parse_args(argv)

    if args.json:
        jobs = json.loads(Path(args.json).read_text(encoding="utf-8"))
        if not isinstance(jobs, list):
            parser.error("--json must contain a list of job objects")
    elif args.company or args.link:
        jobs = [{
            "company": args.company, "title": args.title, "link": args.link, "location": args.location,
            "salary": args.salary, "description": args.description, "source_detail": args.detail,
        }]
    else:
        parser.error("give --json, or at least --company or --link")

    counts = job_matching.add_candidates(jobs, SOURCES[args.source])
    print(
        f"Added {counts['added']} to Matching Jobs; skipped {counts['already_tracked']} already tracked, "
        f"{counts['filtered']} excluded by profile keywords, {counts['invalid']} missing company/link."
    )
    return counts


if __name__ == "__main__":
    main()
