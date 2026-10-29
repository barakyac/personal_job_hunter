"""LLM evals for fit scoring - these call the real local Ollama model, so
they're slow and non-deterministic. They auto-skip when Ollama isn't
reachable, so they never block CI; run them locally with:

    pytest evals/llm -m llm
"""
import socket
from urllib.parse import urlparse

import pytest

from src import fit_analysis, ollama_client

pytestmark = pytest.mark.llm

RESUME = """
Senior backend engineer, 8 years of Python, built distributed systems at
scale, led a team of 5, deep experience with Kafka, Postgres, and AWS.
"""

STRONG_JOB = {
    "company": "Acme",
    "title": "Senior Backend Engineer",
    "notes": "Looking for a senior Python backend engineer with distributed "
             "systems and Kafka experience to lead a small team.",
}

WEAK_JOB = {
    "company": "Globex",
    "title": "Junior Frontend Developer",
    "notes": "Entry-level React developer, 0-1 years of experience, no "
             "backend work involved.",
}


def _ollama_reachable() -> bool:
    url = urlparse(ollama_client.OLLAMA_URL)
    try:
        with socket.create_connection((url.hostname, url.port), timeout=1):
            return True
    except OSError:
        return False


@pytest.fixture(autouse=True)
def skip_if_ollama_unreachable():
    if not _ollama_reachable():
        pytest.skip(f"Ollama not reachable at {ollama_client.OLLAMA_URL}")


def test_fit_score_is_a_valid_shape():
    result = fit_analysis.analyze_with_posting_text(RESUME, STRONG_JOB, "")
    assert isinstance(result["fit_score"], (int, float))
    assert 1 <= result["fit_score"] <= 10
    assert result["fit_notes"].strip()


def test_strong_match_scores_at_least_as_high_as_weak_match():
    strong = fit_analysis.analyze_with_posting_text(RESUME, STRONG_JOB, "")
    weak = fit_analysis.analyze_with_posting_text(RESUME, WEAK_JOB, "")
    assert strong["fit_score"] >= weak["fit_score"]
