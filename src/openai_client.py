import os

import openai

DEFAULT_MODEL = "gpt-4o"


class OpenAIError(Exception):
    pass


def chat(messages: list[dict], model: str = DEFAULT_MODEL, timeout: float = 300) -> str:
    if not os.environ.get("OPENAI_API_KEY"):
        raise OpenAIError("Set the OPENAI_API_KEY environment variable to use ChatGPT.")

    client = openai.OpenAI(timeout=timeout)

    try:
        response = client.chat.completions.create(model=model, messages=messages)
    except openai.AuthenticationError as exc:
        raise OpenAIError("ChatGPT rejected the API key - check OPENAI_API_KEY.") from exc
    except openai.RateLimitError as exc:
        raise OpenAIError("ChatGPT API rate limit hit - try again shortly.") from exc
    except openai.APIStatusError as exc:
        raise OpenAIError(f"ChatGPT API error: {exc}") from exc
    except openai.APIConnectionError as exc:
        raise OpenAIError(f"Could not reach the ChatGPT API: {exc}") from exc

    return response.choices[0].message.content or ""
