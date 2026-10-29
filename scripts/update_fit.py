#!/usr/bin/env python3
"""Write a fit score/notes onto a saved or applied position.

Meant to be invoked by Claude after comparing data/resume.md against a job
posting, e.g.:

    python scripts/update_fit.py saved --company Acme --title "Backend Engineer" \
        --fit-score 8 --fit-notes "Strong match on Go + distributed systems; no cloud cert."
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import storage


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=["saved", "applied"])
    parser.add_argument("--company", required=True)
    parser.add_argument("--title", default="")
    parser.add_argument("--link", default="")
    parser.add_argument("--fit-score", required=True)
    parser.add_argument("--fit-notes", required=True)
    args = parser.parse_args()

    loader = storage.load_saved if args.kind == "saved" else storage.load_applied
    saver = storage.save_saved if args.kind == "saved" else storage.save_applied

    records = loader()
    idx = storage.find_record_index(records, args.company, args.title, args.link)

    if idx is None:
        print(f"No unique match for company={args.company!r} title={args.title!r} in {args.kind}. Nothing updated.")
        return

    records[idx]["fit_score"] = args.fit_score
    records[idx]["fit_notes"] = args.fit_notes
    saver(records)

    print(f"Updated fit for {records[idx]['company']} - {records[idx].get('title', '')}")


if __name__ == "__main__":
    main()
