import json

import requests

OLLAMA_URL = "http://localhost:11434/api/chat"
DEFAULT_MODEL = "qwen3.5:9b"


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
        },
        timeout,
    )
