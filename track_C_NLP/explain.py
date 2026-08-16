"""Turns one of Track A's ranked recommendations into a plain-language
sentence a tourist can actually read. Pure and offline - no model call,
no network dependency, same input always produces the same output.
"""

CATEGORY_PHRASES = {
    "Temple": "a calmer spot for quiet reflection",
    "Heritage": "another piece of the city's history",
    "Monument": "an equally striking landmark",
    "Urban": "a lively spot to explore",
    "Nature": "a green space to unwind in",
    "Wildlife": "an open-air alternative with more room to roam",
    "Cultural": "a cultural experience of its own",
}
DEFAULT_CATEGORY_PHRASE = "a nearby alternative"

TEMPLATES = [
    "{name} is {category_phrase} and {similarity_phrase}. It's {distance_phrase}, and current readings show it isn't crowded.",
    "Consider {name} instead — {distance_phrase} and {similarity_phrase}, it's {category_phrase} without the current crowd.",
    "{name} offers {category_phrase}, {distance_phrase} from here. It's {similarity_phrase}, and it's clear right now.",
]


def _distance_phrase(distance_km: float) -> str:
    if distance_km < 1:
        return "just a short walk away"
    if distance_km < 3:
        return f"a quick {distance_km:.1f} km trip away"
    if distance_km < 8:
        return f"about {distance_km:.1f} km away"
    return f"roughly {distance_km:.0f} km away, a bit further out"


def _similarity_phrase(similarity_score: float) -> str:
    if similarity_score >= 0.6:
        return "a strong match for the kind of experience you were after"
    if similarity_score >= 0.4:
        return "a reasonably similar option"
    return "a change of pace, but still worth considering"


def _category_phrase(category: str) -> str:
    return CATEGORY_PHRASES.get(category, DEFAULT_CATEGORY_PHRASE)


def explain(recommendation: dict) -> str:
    """
    Args:
        recommendation: one entry from get_recommendations()'s
            "recommendations" list, e.g.
            {
                "destination_id": str,
                "name": str,
                "category": str,
                "similarity_score": float,
                "distance_km": float,
                "final_score": float,
            }

    Returns:
        A plain-language explanation string for the end user.
    """
    template_index = sum(ord(c) for c in recommendation["destination_id"]) % len(TEMPLATES)
    template = TEMPLATES[template_index]
    return template.format(
        name=recommendation["name"],
        category_phrase=_category_phrase(recommendation["category"]),
        similarity_phrase=_similarity_phrase(recommendation["similarity_score"]),
        distance_phrase=_distance_phrase(recommendation["distance_km"]),
    )


if __name__ == "__main__":
    samples = [
        {
            "destination_id": "dest_006",
            "name": "Jaigarh Fort",
            "category": "Heritage",
            "similarity_score": 0.7152,
            "distance_km": 0.3,
            "final_score": 0.7962,
        },
        {
            "destination_id": "dest_017",
            "name": "Jawahar Circle Garden",
            "category": "Nature",
            "similarity_score": 0.3842,
            "distance_km": 7.71,
            "final_score": 0.4534,
        },
        {
            "destination_id": "dest_011",
            "name": "Galtaji Temple",
            "category": "Temple",
            "similarity_score": 0.55,
            "distance_km": 12.4,
            "final_score": 0.51,
        },
    ]
    for rec in samples:
        print(explain(rec))
