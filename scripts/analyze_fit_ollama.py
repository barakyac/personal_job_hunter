#!/usr/bin/env python3
"""Batch-analyze fit for saved (or applied) positions using a local Ollama model.

Requires `ollama serve` running locally with the target model pulled
(default: qwen3.5:9b). Writes fit_score/fit_notes back into the JSON records.

    python scripts/analyze_fit_ollama.py saved
    python scripts/analyze_fit_ollama.py applied --status "First Call"
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import fit_analysis, ollama_client, storage


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=["saved", "applied"], nargs="?", default="saved")
    parser.add_argument("--model", default=ollama_client.DEFAULT_MODEL)
    parser.add_argument("--status", default=None, help="applied only: filter by status, e.g. 'First Call'")
    args = parser.parse_args()

    resume_text = storage.load_resume()
    if not resume_text.strip():
        print("No resume on file (data/resume.md is empty). Add one first.")
        return

    loader = storage.load_saved if args.kind == "saved" else storage.load_applied
    saver = storage.save_saved if args.kind == "saved" else storage.save_applied

    records = loader()
    targets = [
        i for i, r in enumerate(records)
        if not args.status or (r.get("status") or "") == args.status
    ]

    if not targets:
        print(f"No {args.kind} positions to analyze.")
        return

    for i in targets:
        job = records[i]
        label = f"{job.get('company', '?')} - {job.get('title', '')}"
        print(f"Analyzing: {label} ...", end=" ", flush=True)
        try:
            result = fit_analysis.analyze(resume_text, job, model=args.model)
        except ollama_client.OllamaError as exc:
            print(f"FAILED ({exc})")
            continue
        records[i]["fit_score"] = result["fit_score"]
        records[i]["fit_notes"] = result["fit_notes"]
        print(f"score={result['fit_score']}")

    saver(records)
    print("Done.")


if __name__ == "__main__":
    main()
