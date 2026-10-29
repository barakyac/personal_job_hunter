import json

import requests

OLLAMA_URL = "http://localhost:11434/api/chat"
DEFAULT_MODEL = "qwen3.5:9b"


class OllamaError(Exception):
    pass


def chat_json(system: str, user: str, model: str = DEFAULT_MODEL, timeout: int = 300) -> dict:
    try:
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "format": "json",
                "stream": False,
                # Keep the model resident between fit checks instead of the
                # default 5-minute idle unload, which forces a slow reload
                # (~9GB) on every call after a gap.
                "keep_alive": "30m",
            },
            timeout=timeout,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise OllamaError(f"Could not reach Ollama at {OLLAMA_URL} (is `ollama serve` running?): {exc}") from exc

    content = resp.json().get("message", {}).get("content", "")
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise OllamaError(f"Ollama returned non-JSON content: {content!r}") from exc
