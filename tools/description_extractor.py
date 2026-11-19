#!/usr/bin/env python3
"""Backfill a saved/applied position's description from its posting link.

Two steps, since some job boards (LinkedIn included) block a plain scripted
fetch with a bot-check response - fetch_posting_text() then returns "":

    # 1. Try fetching descriptions automatically for records that have a
    #    link but no description yet. Lists whatever couldn't be fetched.
    python tools/description_extractor.py scan saved

    # 2. For each link `scan` couldn't reach, open it in a logged-in
    #    browser (e.g. Claude in Chrome), copy the posting text, and write
    #    it in directly:
    python tools/description_extractor.py set saved --company Acme \
        --title "Backend Engineer" --description "Full job description..."
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import fit_analysis, storage

_LOADERS = {"saved": storage.load_saved, "applied": storage.load_applied}
_SAVERS = {"saved": storage.save_saved, "applied": storage.save_applied}


def _needs_description(record: dict) -> bool:
    return bool(record.get("link")) and not (record.get("description") or "").strip()


def scan(kind: str, open_only: bool) -> None:
    loader, saver = _LOADERS[kind], _SAVERS[kind]
    records = loader()
    fetched = 0
    pending = []
    for record in records:
        if open_only and kind == "saved" and record.get("posting_status") != storage.POSTING_STATUS_OPEN:
            continue
        if not _needs_description(record):
            continue
        text = fit_analysis.fetch_posting_text(record["link"])
        if text:
            record["description"] = text
            fetched += 1
        else:
            pending.append(record)

    if fetched:
        saver(records)
    print(f"Fetched {fetched} description(s) automatically.")
    if pending:
        print("Needs manual extraction (open the link in a logged-in browser, then re-run with `set`):")
        for record in pending:
            print(f"  - {record.get('company', '?')} / {record.get('title', '?')} -> {record['link']}")


def set_description(kind: str, company: str, title: str, link: str, description: str) -> None:
    loader, saver = _LOADERS[kind], _SAVERS[kind]
    records = loader()
    idx = storage.find_record_index(records, company, title, link)
    if idx is None:
        print(f"No unique match for company={company!r} title={title!r} in {kind}. Nothing updated.")
        return
    records[idx]["description"] = description
    saver(records)
    print(f"Updated description for {records[idx]['company']} - {records[idx].get('title', '')}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    scan_parser = sub.add_parser("scan", help="Try fetching descriptions automatically; list what's left")
    scan_parser.add_argument("kind", choices=["saved", "applied"])
    scan_parser.add_argument(
        "--all", action="store_true",
        help="include closed postings too (saved only; default is open-for-applications only)",
    )

    set_parser = sub.add_parser("set", help="Write a manually-extracted description onto one record")
    set_parser.add_argument("kind", choices=["saved", "applied"])
    set_parser.add_argument("--company", required=True)
    set_parser.add_argument("--title", default="")
    set_parser.add_argument("--link", default="")
    set_parser.add_argument("--description", required=True)

    args = parser.parse_args()

    if args.command == "scan":
        scan(args.kind, open_only=not args.all)
    else:
        set_description(args.kind, args.company, args.title, args.link, args.description)


if __name__ == "__main__":
    main()
