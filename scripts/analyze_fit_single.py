#!/usr/bin/env python3
"""Score one saved/applied position against the resume using local Ollama.

Meant to be invoked by Claude after fetching the job posting itself (e.g. via
WebFetch, for sites like LinkedIn that block a plain GET request) and saving
that text to a file:

    python scripts/analyze_fit_single.py saved --company Acme --title "Backend Engineer" \
        --posting-text-file /tmp/posting.txt

If --posting-text-file is omitted, falls back to fetching the record's link
with a plain HTTP GET (works for simple sites, not JS-heavy or login-gated ones).
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import fit_analysis, ollama_client, storage


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=["saved", "applied"])
    parser.add_argument("--company", required=True)
    parser.add_argument("--title", default="")
    parser.add_argument("--link", default="")
    parser.add_argument("--posting-text-file", default=None)
    parser.add_argument("--model", default=ollama_client.DEFAULT_MODEL)
    args = parser.parse_args()

    resume_text = storage.load_resume()
    if not resume_text.strip():
        print("No resume on file (data/resume.md is empty). Add one first.")
        return

    loader = storage.load_saved if args.kind == "saved" else storage.load_applied
    saver = storage.save_saved if args.kind == "saved" else storage.save_applied

    records = loader()
    idx = storage.find_record_index(records, args.company, args.title, args.link)
    if idx is None:
        print(f"No unique match for company={args.company!r} title={args.title!r} in {args.kind}.")
        return

    job = records[idx]

    if args.posting_text_file:
        posting_text = Path(args.posting_text_file).read_text(encoding="utf-8")
    else:
        posting_text = fit_analysis.fetch_posting_text(job.get("link", ""))

    try:
        result = fit_analysis.analyze_with_posting_text(resume_text, job, posting_text, model=args.model)
    except ollama_client.OllamaError as exc:
        print(f"FAILED: {exc}")
        return

    records[idx]["fit_score"] = result["fit_score"]
    records[idx]["fit_notes"] = result["fit_notes"]
    saver(records)

    print(f"score={result['fit_score']}")
    print(result["fit_notes"])


if __name__ == "__main__":
    main()
