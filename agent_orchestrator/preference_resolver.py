"""Resolves a tie between near-equally-ranked recommendations using
free-text user preference via Groq. Fails soft - returns None if Groq is
unavailable or its reply can't be matched back to a real candidate, so
the caller can fall back to asking the user directly instead.
"""

from agent_orchestrator.groq_client import complete


def resolve_tie(tied_candidates: list, user_preference: str) -> dict | None:
    options = "\n".join(
        f"{i}. {c['name']} ({c['category']}, {c['distance_km']:.1f} km away)"
        for i, c in enumerate(tied_candidates)
    )
    prompt = (
        f'A tourist said they want: "{user_preference}"\n\n'
        "Which of these numbered options best matches what they're after? "
        "Reply with only the number, nothing else.\n\n"
        f"{options}"
    )

    result = complete(prompt, max_tokens=10)
    if result is None:
        return None

    digits = "".join(ch for ch in result if ch.isdigit())
    if not digits:
        return None

    index = int(digits)
    if 0 <= index < len(tied_candidates):
        return tied_candidates[index]
    return None
