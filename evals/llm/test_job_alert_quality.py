"""LLM evals for job-alert extraction - these call the real local Ollama
model, so they're slow and non-deterministic. They auto-skip when Ollama
isn't reachable, so they never block CI; run them locally with:

    pytest evals/llm -m llm

Fixtures below are the 6 real job-alert emails that produced Saved
Positions during live use on 2026-11-19, 2 of which were wrong (see
evals/unit/test_job_extract.py for the regression detail and the
deterministic fix for the Glassdoor-digest shape). All 6 are kept here as a
live end-to-end check - including the 2 Glassdoor ones, which don't call
the model at all but are worth re-confirming at this level too - so a
future change to extract_opportunity_fields (prompt wording, model choice,
regex) gets caught against real-world input, not just the hand-trimmed
unit fixtures.
"""
import socket
from urllib.parse import urlparse

import pytest

from src import job_extract, ollama_client

pytestmark = pytest.mark.llm


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


REAL_OPPORTUNITY_EMAILS = [
    pytest.param(
        "QA Automation Engineer at Questar Auto Technologies and 10 more jobs in Tel Aviv-Yafo for you. Apply Now.",
        'עידור מחשבים בע"מ is hiring',
        "Questar Auto Technologies",
        id="questar-glassdoor-digest",
    ),
    pytest.param(
        "monday.com is hiring: AI Context & Data Engineering Manager, BigBrain",
        "monday.com AI Context & Data Engineering Manager, BigBrain: Help every person and every agent at monday.com...",
        "monday.com",
        id="monday-linkedin-digest",
    ),
    pytest.param(
        "Mars Security is hiring: Senior Software Engineer",
        "Mars Security Senior Software Engineer: About Mars SecurityMars Security is an...",
        "Mars Security",
        id="mars-security-linkedin-digest",
    ),
    pytest.param(
        "Buildots Field Capture Technician",
        "Buildots Field Capture Technician: About BuildotsBuildots is the world's most...",
        "Buildots",
        id="buildots-no-separator",
    ),
    pytest.param(
        "Software Engineer at Check Point Software Technologies and 10 more jobs in Tel Aviv-Yafo for you. Apply Now.",
        "Apple is hiring",
        "Check Point Software Technologies",
        id="check-point-glassdoor-digest",
    ),
    pytest.param(
        "NVIDIA is hiring: Senior Software Developer",
        "NVIDIA Senior Software Developer: We are looking for an enthusiastic software...",
        "NVIDIA",
        id="nvidia-linkedin-digest",
    ),
]


@pytest.mark.parametrize("subject, snippet, expected_company", REAL_OPPORTUNITY_EMAILS)
def test_extracts_correct_company_from_real_opportunity_email(subject, snippet, expected_company):
    fields = job_extract.extract_opportunity_fields(subject, snippet)
    assert fields["company"] == expected_company
