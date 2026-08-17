"""Thin wrapper around the Groq API. Every function here fails soft -
returns None on a missing key, a network error, or any API failure - so
callers can drop back to their rule-based path instead of breaking the
request the user is waiting on.
"""

import os

from groq import Groq

from agent_orchestrator.config import GROQ_MODEL

_client = None
_client_checked = False


def _get_client():
    global _client, _client_checked
    if _client_checked:
        return _client

    _client_checked = True
    api_key = os.environ.get("GROQ_API_KEY")
    if api_key:
        _client = Groq(api_key=api_key)
    return _client


def complete(prompt: str, max_tokens: int = 200) -> str | None:
    client = _get_client()
    if client is None:
        return None

    try:
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=0.7,
        )
        return response.choices[0].message.content.strip()
    except Exception:
        return None
