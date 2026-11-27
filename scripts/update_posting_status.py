#!/usr/bin/env python3
"""Record the outcome of checking whether a tracked posting is still open -
see the find-matching-jobs skill's "Re-checking postings already tracked"
section. Never hand-edit matched_jobs.json/saved_positions.json for this:
this script enforces that a failed check (sign-in wall, CAPTCHA, timeout)
can never downgrade an earlier Open/Closed confirmation or refresh its
timestamp - only a successful check can set Open or Closed.

    python scripts/update_posting_status.py matched --company Acme --title "Backend Engineer" \
        --link https://www.linkedin.com/jobs/view/123/ --result closed
    python scripts/update_posting_status.py saved --company Acme --result unknown
"""
import argparse
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import job_matching, storage

KINDS = {
    "matched": (storage.load_matched, storage.save_matched),
    "saved": (storage.load_saved, storage.save_saved),
}
# "unknown" means the check itself failed (sign-in wall, CAPTCHA, timeout) -
# it never establishes anything, so it maps to confirmed=None.
RESULTS = {"open": "open", "closed": "closed", "unknown": None}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("kind", choices=sorted(KINDS))
    parser.add_argument("--company", required=True)
    parser.add_argument("--title", default="")
    parser.add_argument("--link", default="")
    parser.add_argument(
        "--result", choices=sorted(RESULTS), required=True,
        help="what the check actually established - 'unknown' for a failed check",
    )
    args = parser.parse_args(argv)

    loader, saver = KINDS[args.kind]
    records = loader()
    idx = storage.find_record_index(records, args.company, args.title, args.link)
    if idx is None:
        print(f"No unique match for company={args.company!r} title={args.title!r} in {args.kind}. Nothing updated.")
        return

    before = records[idx].get("posting_status")
    job_matching.apply_posting_check(records[idx], RESULTS[args.result], dt.date.today().isoformat())
    saver(records)

    after = records[idx]["posting_status"]
    if args.result == "unknown" and after == before:
        print(f"{records[idx]['company']}: kept {before!r} - a failed check never overwrites a confirmed status.")
    else:
        print(f"{records[idx]['company']}: posting_status={after}")


if __name__ == "__main__":
    main()
