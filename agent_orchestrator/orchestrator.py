"""Decision layer sitting above Track B (CV), Track A (recommendations),
and Track C (NLP explanation). It doesn't detect or rank anything itself -
it decides when to call into the pieces that do, and how to adapt when
their output isn't good enough to act on directly.

Track B and Track C aren't callable as real code yet, so this module
defines the interface contracts they're expected to satisfy (TrackBClient,
TrackCClient) instead of faking their behavior.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent_orchestrator.config import (
    BARRIER_STALENESS_MINUTES,
    EQUAL_RANK_CANDIDATE_THRESHOLD,
    EQUAL_RANK_SCORE_MARGIN,
    LOW_CONFIDENCE_THRESHOLD,
    RADIUS_KM_DEFAULT,
    RADIUS_KM_WIDENED,
)
from agent_orchestrator.preference_resolver import resolve_tie
from shared.barrier_store import barrier_store
from track_A_filtering.recommend import get_recommendations


class TrackBClient:
    """Interface contract for Track B (live crowd detection). Track B owns
    the implementation (see track_B_CV/main.py's /detect-crowd endpoint) -
    the orchestrator only depends on this shape. A real client needs to be
    supplied by the caller once Track B exposes one; nothing in this module
    talks to a model directly.
    """

    def detect(self, image_bytes: bytes, destination_id: str) -> dict:
        """
        Args:
            image_bytes: raw bytes of a user-submitted photo.
            destination_id: the destination the photo was taken at.

        Returns, on a successful detection:
            {
                "status": "success",
                "destination_id": str,
                "estimated_count": int,
                "crowd_level": "LOW" | "MEDIUM" | "HIGH" | "VERY_HIGH",
                "confidence_scores": list[float],
            }

        Returns, if detection itself fails:
            {
                "status": "fallback",
                "destination_id": str,
                "estimated_count": None,
                "crowd_level": "unknown",
                "error_message": str,
            }
        """
        raise NotImplementedError(
            "TrackBClient has no real implementation yet - pass a client that "
            "wraps Track B's actual detection call."
        )


class TrackCClient:
    """Interface contract for Track C (plain-language explanation). Track C
    owns the implementation; the orchestrator only depends on this shape.
    """

    def explain(self, recommendation: dict) -> str:
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
        raise NotImplementedError(
            "TrackCClient has no real implementation yet - pass a client that "
            "wraps Track C's actual explanation call."
        )


def check_staleness(destination_id: str, track_b_client: TrackBClient) -> dict:
    """Check whether the cached barrier reading for destination_id is still
    fresh enough to act on.

    track_b_client is accepted here but not called - getting a fresh
    reading needs an actual photo, which this function has no access to.
    It only reports whether a remeasurement is needed; the caller (who has
    the image) is the one that actually calls track_b_client.detect().

    Returns:
        {
            "fresh": bool,
            "needs_remeasure": bool,
            "current_reading": dict | None,
        }
    """
    current_reading = barrier_store.get(destination_id)
    fresh = current_reading is not None and barrier_store.is_fresh(
        destination_id, BARRIER_STALENESS_MINUTES
    )
    return {
        "fresh": fresh,
        "needs_remeasure": not fresh,
        "current_reading": current_reading,
    }


def check_confidence(barrier_reading: dict) -> dict:
    """Decide whether a barrier reading's detection confidence is high
    enough to act on.

    Zero detections isn't ambiguous - there's nothing uncertain about "we
    found nobody" - so an empty (or missing) confidence_scores list counts
    as sufficient, not as low confidence.

    Returns:
        {"sufficient": True} or
        {"sufficient": False, "reason": "..."}
    """
    scores = barrier_reading.get("confidence_scores") or []
    if not scores:
        return {"sufficient": True}

    avg_confidence = sum(scores) / len(scores)
    if avg_confidence < LOW_CONFIDENCE_THRESHOLD:
        return {
            "sufficient": False,
            "reason": f"average confidence {avg_confidence:.2f} is below the {LOW_CONFIDENCE_THRESHOLD} threshold",
        }
    return {"sufficient": True}


def check_and_widen_radius(origin_destination_id: str) -> dict:
    """Run get_recommendations() at the default radius; if that comes back
    empty, retry once at the widened radius. Never retries more than once.

    Returns the get_recommendations() result plus "radius_used" and
    "radius_expanded" so the caller can be transparent about whether
    widening happened.
    """
    result = get_recommendations(origin_destination_id, radius_km=RADIUS_KM_DEFAULT)
    if result["recommendations"]:
        return {**result, "radius_used": RADIUS_KM_DEFAULT, "radius_expanded": False}

    widened = get_recommendations(origin_destination_id, radius_km=RADIUS_KM_WIDENED)
    return {**widened, "radius_used": RADIUS_KM_WIDENED, "radius_expanded": True}


def should_ask_preference(recommendations: list) -> bool:
    """Rule-based tie check: True only when more than
    EQUAL_RANK_CANDIDATE_THRESHOLD recommendations sit within
    EQUAL_RANK_SCORE_MARGIN of the top final_score.
    """
    if not recommendations:
        return False

    top_score = max(r["final_score"] for r in recommendations)
    tied = [r for r in recommendations if top_score - r["final_score"] <= EQUAL_RANK_SCORE_MARGIN]
    return len(tied) > EQUAL_RANK_CANDIDATE_THRESHOLD


def orchestrate(
    destination_id: str,
    track_b_client: TrackBClient,
    track_c_client: TrackCClient,
    fresh_reading: dict | None = None,
    user_preference: str | None = None,
) -> dict:
    """Tie the decision points together for one destination.

    fresh_reading is for the case where the caller already ran
    track_b_client.detect() themselves (because check_staleness said a
    remeasurement was needed) and is now handing the result back in.

    user_preference is free text like "somewhere quieter" - only used
    when should_ask_preference() would otherwise stop and ask. If Groq
    can resolve the tie from it, that candidate is promoted to the top of
    the results; if not (no preference given, no API key configured, the
    call fails), behavior is unchanged from before this existed.
    """
    staleness = check_staleness(destination_id, track_b_client)

    if staleness["needs_remeasure"] and fresh_reading is None:
        return {
            "status": "needs_remeasure",
            "destination_id": destination_id,
            "message": "no fresh barrier reading available - call track_b_client.detect() and retry with fresh_reading set",
        }

    reading = fresh_reading if fresh_reading is not None else staleness["current_reading"]

    confidence = check_confidence(reading)
    if not confidence["sufficient"]:
        return {
            "status": "needs_second_photo",
            "destination_id": destination_id,
            "reason": confidence["reason"],
        }

    crowd_level = reading.get("crowd_level")
    if crowd_level == "unknown":
        return {
            "status": "detection_failed",
            "destination_id": destination_id,
            "message": reading.get("error_message", "Track B could not process this photo"),
        }

    if crowd_level not in ("HIGH", "VERY_HIGH"):
        return {
            "status": "not_barriered",
            "destination_id": destination_id,
            "crowd_level": crowd_level,
        }

    try:
        radius_result = check_and_widen_radius(destination_id)
    except ValueError:
        return {
            "status": "unknown_destination",
            "destination_id": destination_id,
        }

    recommendations = radius_result["recommendations"]

    if not recommendations:
        return {
            "status": "no_alternatives_found",
            "destination_id": destination_id,
            "radius_used": radius_result["radius_used"],
            "radius_expanded": radius_result["radius_expanded"],
        }

    if should_ask_preference(recommendations):
        resolved = resolve_tie(recommendations, user_preference) if user_preference else None
        if resolved is None:
            return {
                "status": "needs_preference",
                "destination_id": destination_id,
                "candidates": recommendations,
            }
        recommendations = [resolved] + [r for r in recommendations if r is not resolved]

    explained = [
        {**rec, "explanation": track_c_client.explain(rec)} for rec in recommendations
    ]

    return {
        "status": "success",
        "destination_id": destination_id,
        "radius_used": radius_result["radius_used"],
        "radius_expanded": radius_result["radius_expanded"],
        "recommendations": explained,
    }


if __name__ == "__main__":
    class FakeTrackBClient(TrackBClient):
        def detect(self, image_bytes, destination_id):
            return {
                "status": "success",
                "destination_id": destination_id,
                "estimated_count": 40,
                "crowd_level": "VERY_HIGH",
                "confidence_scores": [0.8, 0.75, 0.9],
            }

    class FakeTrackCClient(TrackCClient):
        def explain(self, recommendation):
            return (
                f"{recommendation['name']} is a similar {recommendation['category'].lower()} "
                f"nearby and isn't crowded right now."
            )

    fake_b = FakeTrackBClient()
    fake_c = FakeTrackCClient()

    print(" scenario 1: no cached reading, no fresh_reading -> needs_remeasure ")
    print(orchestrate("dest_002", fake_b, fake_c))

    print("\n scenario 2: fresh_reading with low confidence -> needs_second_photo ")
    low_confidence_reading = {
        "destination_id": "dest_003",
        "crowd_level": "HIGH",
        "estimated_count": 12,
        "confidence_scores": [0.1, 0.2],
    }
    print(orchestrate("dest_003", fake_b, fake_c, fresh_reading=low_confidence_reading))

    print("\n--- scenario 3: fresh_reading, confident, VERY_HIGH -> success ---")
    good_reading = {
        "destination_id": "dest_001",
        "crowd_level": "VERY_HIGH",
        "estimated_count": 40,
        "confidence_scores": [0.8, 0.75, 0.9],
    }
    print(orchestrate("dest_001", fake_b, fake_c, fresh_reading=good_reading))

    print("\n--- scenario 4: destination_id not in destinations.json -> unknown_destination ---")
    bogus_reading = {
        "destination_id": "dest_does_not_exist",
        "crowd_level": "VERY_HIGH",
        "estimated_count": 40,
        "confidence_scores": [0.8, 0.75, 0.9],
    }
    print(orchestrate("dest_does_not_exist", fake_b, fake_c, fresh_reading=bogus_reading))

    print("\n--- scenario 5: everything nearby barriered even at widened radius -> no_alternatives_found ---")
    import json as _json

    for d in _json.load(open("track_A_filtering/destinations.json", encoding="utf-8")):
        barrier_store.set(d["destination_id"], "VERY_HIGH", estimated_count=100)
    isolated_reading = {
        "destination_id": "dest_021",
        "crowd_level": "VERY_HIGH",
        "estimated_count": 100,
        "confidence_scores": [0.9],
    }
    print(orchestrate("dest_021", fake_b, fake_c, fresh_reading=isolated_reading))

    print("\n--- scenario 6: Track B's own detection failed -> detection_failed ---")
    failed_reading = {
        "destination_id": "dest_004",
        "crowd_level": "unknown",
        "estimated_count": None,
        "error_message": "model inference timed out",
    }
    print(orchestrate("dest_004", fake_b, fake_c, fresh_reading=failed_reading))
