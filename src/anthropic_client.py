import os

import anthropic

DEFAULT_MODEL = "claude-opus-5-5"


class AnthropicError(Exception):
    pass


def _split_system(messages: list[dict]) -> tuple[str, list[dict]]:
    """Claude's API takes the system prompt as its own `system` param, not a
    "system"-role message - split one out of an Ollama/OpenAI-style list."""
    system_parts = []
    convo = []
    for m in messages:
        if m["role"] == "system":
            system_parts.append(m["content"])
        else:
            convo.append(m)
    return "\n\n".join(system_parts), convo


def chat(messages: list[dict], model: str = DEFAULT_MODEL, timeout: float = 300) -> str:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise AnthropicError("Set the ANTHROPIC_API_KEY environment variable to use Claude.")

    system, convo = _split_system(messages)
    client = anthropic.Anthropic(timeout=timeout)

    try:
        # claude-opus-5-5 opts in to the server-side refusal fallback by
        # default per Anthropic's current guidance, so a safety decline
        # retries on a fallback model instead of just stopping.
        response = client.beta.messages.create(
            model=model,
            max_tokens=16000,
            system=system,
            messages=convo,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.AuthenticationError as exc:
        raise AnthropicError("Claude rejected the API key - check ANTHROPIC_API_KEY.") from exc
    except anthropic.RateLimitError as exc:
        raise AnthropicError("Claude API rate limit hit - try again shortly.") from exc
    except anthropic.APIStatusError as exc:
        raise AnthropicError(f"Claude API error: {exc}") from exc
    except anthropic.APIConnectionError as exc:
        raise AnthropicError(f"Could not reach the Claude API: {exc}") from exc

    if response.stop_reason == "refusal":
        return "Claude declined to answer this one."

    return next((b.text for b in response.content if b.type == "text"), "")
