import httpx2
import pytest

from src import anthropic_client


class _Block:
    def __init__(self, type, text=None):
        self.type = type
        self.text = text


class _Response:
    def __init__(self, text, stop_reason="end_turn"):
        self.content = [_Block("text", text)]
        self.stop_reason = stop_reason


class _Messages:
    def __init__(self, result):
        self._result = result
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class _Beta:
    def __init__(self, messages):
        self.messages = messages


class _FakeClient:
    def __init__(self, result, **kwargs):
        self.beta = _Beta(_Messages(result))


def _fake_anthropic_factory(result, holder=None):
    def _make(**kwargs):
        client = _FakeClient(result)
        if holder is not None:
            holder["client"] = client
        return client

    return _make


def test_chat_raises_when_api_key_missing(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(anthropic_client.AnthropicError, match="ANTHROPIC_API_KEY"):
        anthropic_client.chat([{"role": "user", "content": "hi"}])


def test_chat_returns_text_from_response(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(
        anthropic_client.anthropic,
        "Anthropic",
        _fake_anthropic_factory(_Response("Here's some advice.")),
    )

    result = anthropic_client.chat([{"role": "user", "content": "Any tips?"}])

    assert result == "Here's some advice."


def test_chat_splits_system_message_and_sets_fallback_params(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    holder = {}
    monkeypatch.setattr(
        anthropic_client.anthropic, "Anthropic", _fake_anthropic_factory(_Response("ok"), holder)
    )

    messages = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "Hi"},
        {"role": "assistant", "content": "Hello!"},
        {"role": "user", "content": "Any tips?"},
    ]
    anthropic_client.chat(messages, model="claude-opus-5-5")

    kwargs = holder["client"].beta.messages.last_kwargs
    assert kwargs["system"] == "You are helpful."
    assert kwargs["messages"] == [
        {"role": "user", "content": "Hi"},
        {"role": "assistant", "content": "Hello!"},
        {"role": "user", "content": "Any tips?"},
    ]
    assert kwargs["model"] == "claude-opus-5-5"
    assert kwargs["betas"] == ["server-side-fallback-2026-07-01"]
    assert kwargs["fallbacks"] == "default"


def test_chat_returns_decline_message_on_refusal(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(
        anthropic_client.anthropic,
        "Anthropic",
        _fake_anthropic_factory(_Response("", stop_reason="refusal")),
    )

    result = anthropic_client.chat([{"role": "user", "content": "..."}])

    assert "declined" in result.lower()


def test_chat_wraps_authentication_error(monkeypatch):
    import anthropic as anthropic_sdk

    monkeypatch.setenv("ANTHROPIC_API_KEY", "bad-key")
    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    resp = httpx2.Response(401, request=req)
    err = anthropic_sdk.AuthenticationError("bad key", response=resp, body=None)
    monkeypatch.setattr(anthropic_client.anthropic, "Anthropic", _fake_anthropic_factory(err))

    with pytest.raises(anthropic_client.AnthropicError, match="ANTHROPIC_API_KEY"):
        anthropic_client.chat([{"role": "user", "content": "hi"}])


def test_chat_wraps_connection_error(monkeypatch):
    import anthropic as anthropic_sdk

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    err = anthropic_sdk.APIConnectionError(message="boom", request=req)
    monkeypatch.setattr(anthropic_client.anthropic, "Anthropic", _fake_anthropic_factory(err))

    with pytest.raises(anthropic_client.AnthropicError, match="Could not reach"):
        anthropic_client.chat([{"role": "user", "content": "hi"}])
