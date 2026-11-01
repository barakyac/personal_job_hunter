import pytest
import requests

from src import ollama_client


class FakeResponse:
    def __init__(self, content: str, status_code: int = 200):
        self._content = content
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")

    def json(self):
        return {"message": {"content": self._content}}


def test_chat_json_returns_parsed_content(monkeypatch):
    def fake_post(url, json, timeout):
        return FakeResponse('{"score": 8, "notes": "Good fit"}')

    monkeypatch.setattr(requests, "post", fake_post)

    result = ollama_client.chat_json("system prompt", "user prompt")

    assert result == {"score": 8, "notes": "Good fit"}


def test_chat_json_sends_expected_payload(monkeypatch):
    captured = {}

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeResponse('{"ok": true}')

    monkeypatch.setattr(requests, "post", fake_post)

    ollama_client.chat_json("system prompt", "user prompt", model="qwen3.5:4b", timeout=42)

    assert captured["url"] == ollama_client.OLLAMA_URL
    assert captured["timeout"] == 42
    assert captured["json"]["model"] == "qwen3.5:4b"
    assert captured["json"]["messages"] == [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "user prompt"},
    ]
    assert captured["json"]["format"] == "json"
    assert captured["json"]["stream"] is False
    assert captured["json"]["keep_alive"] == "30m"


def test_chat_json_defaults_to_default_model(monkeypatch):
    captured = {}

    def fake_post(url, json, timeout):
        captured["model"] = json["model"]
        return FakeResponse("{}")

    monkeypatch.setattr(requests, "post", fake_post)

    ollama_client.chat_json("system prompt", "user prompt")

    assert captured["model"] == ollama_client.DEFAULT_MODEL


def test_chat_json_raises_ollama_error_when_unreachable(monkeypatch):
    def fake_post(url, json, timeout):
        raise requests.ConnectionError("connection refused")

    monkeypatch.setattr(requests, "post", fake_post)

    with pytest.raises(ollama_client.OllamaError, match="Could not reach Ollama"):
        ollama_client.chat_json("system prompt", "user prompt")


def test_chat_json_raises_ollama_error_on_http_error_status(monkeypatch):
    def fake_post(url, json, timeout):
        return FakeResponse("{}", status_code=500)

    monkeypatch.setattr(requests, "post", fake_post)

    with pytest.raises(ollama_client.OllamaError, match="Could not reach Ollama"):
        ollama_client.chat_json("system prompt", "user prompt")


def test_chat_json_raises_ollama_error_on_non_json_content(monkeypatch):
    def fake_post(url, json, timeout):
        return FakeResponse("not valid json")

    monkeypatch.setattr(requests, "post", fake_post)

    with pytest.raises(ollama_client.OllamaError, match="non-JSON content"):
        ollama_client.chat_json("system prompt", "user prompt")


def test_chat_returns_reply_text(monkeypatch):
    def fake_post(url, json, timeout):
        return FakeResponse("Here's some free-form advice.")

    monkeypatch.setattr(requests, "post", fake_post)

    result = ollama_client.chat([{"role": "user", "content": "Any tips?"}])

    assert result == "Here's some free-form advice."


def test_chat_sends_messages_as_is_without_forcing_json_format(monkeypatch):
    captured = {}

    def fake_post(url, json, timeout):
        captured["json"] = json
        return FakeResponse("ok")

    monkeypatch.setattr(requests, "post", fake_post)

    messages = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "Hi"},
        {"role": "assistant", "content": "Hello!"},
        {"role": "user", "content": "Any tips?"},
    ]
    ollama_client.chat(messages, model="qwen3.5:9b")

    assert captured["json"]["messages"] == messages
    assert captured["json"]["model"] == "qwen3.5:9b"
    assert "format" not in captured["json"]
    assert captured["json"]["stream"] is False
    assert captured["json"]["keep_alive"] == "30m"


def test_chat_raises_ollama_error_when_unreachable(monkeypatch):
    def fake_post(url, json, timeout):
        raise requests.ConnectionError("connection refused")

    monkeypatch.setattr(requests, "post", fake_post)

    with pytest.raises(ollama_client.OllamaError, match="Could not reach Ollama"):
        ollama_client.chat([{"role": "user", "content": "Hi"}])
