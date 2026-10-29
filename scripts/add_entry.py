#!/usr/bin/env python3
"""Append a saved or applied position to the dashboard's JSON files.

Meant to be invoked by Claude on the user's behalf after fetching a job
posting link and extracting the company/title from it, e.g.:

    python scripts/add_entry.py saved --company Acme --title "Backend Engineer" \
        --link https://acme.example/jobs/1 --location Remote --salary "140k"

    python scripts/add_entry.py applied --company Acme --title "Backend Engineer" \
        --link https://acme.example/jobs/1 --status Applied
"""
import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import storage


def existing_link_location(link: str) -> str | None:
    if not link:
        return None
    for record in storage.load_saved():
        if record.get("link") == link:
            return "saved"
    for record in storage.load_applied():
        if record.get("link") == link:
            return "applied"
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=["saved", "applied"])
    parser.add_argument("--company", required=True)
    parser.add_argument("--title", default="")
    parser.add_argument("--link", default="")
    parser.add_argument("--location", default="")
    parser.add_argument("--salary", default="")
    parser.add_argument("--notes", default="")
    parser.add_argument("--date-saved", default=None, help="YYYY-MM-DD, defaults to today")
    parser.add_argument("--date-applied", default=None, help="YYYY-MM-DD, applied only, defaults to today")
    parser.add_argument("--status", default="Applied", choices=storage.STATUS_OPTIONS)
    parser.add_argument("--force", action="store_true", help="add even if the link already exists")
    args = parser.parse_args()

    today = date.today().isoformat()

    if not args.force:
        where = existing_link_location(args.link)
        if where:
            print(f"Skipped: this link is already in {where} positions. Use --force to add anyway.")
            return

    record = {
        "company": args.company,
        "title": args.title,
        "link": args.link,
        "location": args.location,
        "salary": args.salary,
        "notes": args.notes,
    }

    if args.kind == "saved":
        record["date_saved"] = args.date_saved or today
        records = storage.load_saved()
        records.append(record)
        storage.save_saved(records)
    else:
        record["date_saved"] = args.date_saved or ""
        record["date_applied"] = args.date_applied or today
        record["status"] = args.status
        records = storage.load_applied()
        records.append(record)
        storage.save_applied(records)

    print(f"Added to {args.kind}: {args.company} - {args.title or '(no title)'}")


if __name__ == "__main__":
    main()
