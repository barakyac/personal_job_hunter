#!/usr/bin/env python3
"""List every posting already tracked (Matching Jobs, Saved Jobs, Applied
Positions), for Claude to check a LinkedIn/Google search-results listing
against before opening each card - see .claude/skills/find-matching-jobs.

A canonical-link match in this list means "don't bother opening it, it's
already here." A company+title match alone is only a possible duplicate
(the same company can have more than one open role with the same title) -
worth opening to check, not worth skipping outright. The real,
authoritative dedup still happens at write time in scripts/add_match.py.

    python scripts/list_tracked.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import job_matching


def main() -> None:
    rows = job_matching.tracked_identities()
    if not rows:
        print("Nothing tracked yet.")
        return
    for row in rows:
        print(f"{row['where']:7} | {row['company']} | {row['title']} | {row['canonical_link'] or row['link']}")
    print(f"\n{len(rows)} tracked posting(s).")


if __name__ == "__main__":
    main()
