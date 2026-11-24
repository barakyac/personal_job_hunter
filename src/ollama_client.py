import json

import requests

OLLAMA_URL = "http://localhost:11434/api/chat"
DEFAULT_MODEL = "qwen3.5:9b"

# Qwen3.5's own recommended sampling settings for non-thinking mode (think=False
# below) - without these, calls fall back to Ollama's generic defaults instead.
NON_THINKING_OPTIONS = {"temperature": 0.7, "top_p": 0.8, "top_k": 20}


class OllamaError(Exception):
    pass


def _post(payload: dict, timeout: int) -> str:
    try:
        resp = requests.post(OLLAMA_URL, json=payload, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise OllamaError(f"Could not reach Ollama at {OLLAMA_URL} (is `ollama serve` running?): {exc}") from exc

    return resp.json().get("message", {}).get("content", "")


def chat_json(system: str, user: str, model: str = DEFAULT_MODEL, timeout: int = 300) -> dict:
    content = _post(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "format": "json",
            "stream": False,
            # Keep the model resident between calls instead of the default
            # 5-minute idle unload, which forces a slow reload (~9GB) on
            # every call after a gap.
            "keep_alive": "30m",
            # Qwen3.5 is a "thinking" model by default - it emits a whole
            # internal reasoning pass (a separate "thinking" field) before
            # the actual answer, which this app never reads anyway (only
            # "content" below) and which was the actual cause of 300s+
            # timeouts on larger prompts like fit scoring. Turning it off
            # dropped a trivial call from ~9s to ~0.2s locally.
            "think": False,
            "options": NON_THINKING_OPTIONS,
        },
        timeout,
    )
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise OllamaError(f"Ollama returned non-JSON content: {content!r}") from exc


def chat(messages: list[dict], model: str = DEFAULT_MODEL, timeout: int = 300) -> str:
    """Free-form conversational chat (no forced JSON output). Returns the
    assistant's reply text for a multi-turn `messages` list, e.g.
    [{"role": "system", ...}, {"role": "user", ...}, {"role": "assistant", ...}, ...]."""
    return _post(
        {
            "model": model,
            "messages": messages,
            "stream": False,
            "keep_alive": "30m",
            "think": False,
            "options": NON_THINKING_OPTIONS,
        },
        timeout,
    )
