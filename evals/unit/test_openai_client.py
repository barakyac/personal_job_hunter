import httpx2
import pytest

from src import openai_client


class _Message:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.message = _Message(content)


class _Response:
    def __init__(self, content):
        self.choices = [_Choice(content)]


class _Completions:
    def __init__(self, result):
        self._result = result
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class _Chat:
    def __init__(self, completions):
        self.completions = completions


class _FakeClient:
    def __init__(self, result, **kwargs):
        self.chat = _Chat(_Completions(result))


def _fake_openai_factory(result, holder=None):
    def _make(**kwargs):
        client = _FakeClient(result)
        if holder is not None:
            holder["client"] = client
        return client

    return _make


def test_chat_raises_when_api_key_missing(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(openai_client.OpenAIError, match="OPENAI_API_KEY"):
        openai_client.chat([{"role": "user", "content": "hi"}])


def test_chat_returns_text_from_response(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        openai_client.openai, "OpenAI", _fake_openai_factory(_Response("Here's some advice."))
    )

    result = openai_client.chat([{"role": "user", "content": "Any tips?"}])

    assert result == "Here's some advice."


def test_chat_sends_messages_and_model_unchanged(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    holder = {}
    monkeypatch.setattr(
        openai_client.openai, "OpenAI", _fake_openai_factory(_Response("ok"), holder)
    )

    messages = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "Hi"},
    ]
    openai_client.chat(messages, model="gpt-4o")

    kwargs = holder["client"].chat.completions.last_kwargs
    assert kwargs["messages"] == messages
    assert kwargs["model"] == "gpt-4o"


def test_chat_wraps_authentication_error(monkeypatch):
    import openai as openai_sdk

    monkeypatch.setenv("OPENAI_API_KEY", "bad-key")
    req = httpx2.Request("POST", "https://api.openai.com/v1/chat/completions")
    resp = httpx2.Response(401, request=req)
    err = openai_sdk.AuthenticationError("bad key", response=resp, body=None)
    monkeypatch.setattr(openai_client.openai, "OpenAI", _fake_openai_factory(err))

    with pytest.raises(openai_client.OpenAIError, match="OPENAI_API_KEY"):
        openai_client.chat([{"role": "user", "content": "hi"}])


def test_chat_wraps_connection_error(monkeypatch):
    import openai as openai_sdk

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    req = httpx2.Request("POST", "https://api.openai.com/v1/chat/completions")
    err = openai_sdk.APIConnectionError(message="boom", request=req)
    monkeypatch.setattr(openai_client.openai, "OpenAI", _fake_openai_factory(err))

    with pytest.raises(openai_client.OpenAIError, match="Could not reach"):
        openai_client.chat([{"role": "user", "content": "hi"}])
