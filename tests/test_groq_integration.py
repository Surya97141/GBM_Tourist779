from unittest.mock import patch

from agent_orchestrator.groq_client import complete
from agent_orchestrator.orchestrator import TrackBClient, TrackCClient, orchestrate
from agent_orchestrator.preference_resolver import resolve_tie
from agent_orchestrator.track_c_client import GroqTrackCClient
from track_C_NLP.explain import explain as rule_based_explain

SAMPLE = {
    "destination_id": "dest_006",
    "name": "Jaigarh Fort",
    "category": "Heritage",
    "similarity_score": 0.7152,
    "distance_km": 0.3,
    "final_score": 0.7962,
}

TIED_CANDIDATES = [
    {"destination_id": "dest_a", "name": "Place A", "category": "Heritage", "distance_km": 1.0, "similarity_score": 0.7, "final_score": 0.80},
    {"destination_id": "dest_b", "name": "Place B", "category": "Nature", "distance_km": 2.0, "similarity_score": 0.65, "final_score": 0.79},
    {"destination_id": "dest_c", "name": "Place C", "category": "Temple", "distance_km": 3.0, "similarity_score": 0.6, "final_score": 0.78},
    {"destination_id": "dest_d", "name": "Place D", "category": "Urban", "distance_km": 4.0, "similarity_score": 0.55, "final_score": 0.77},
]


class FakeTrackBClient(TrackBClient):
    def detect(self, image_bytes, destination_id):
        raise AssertionError("should not be called in these tests")


class FakeTrackCClient(TrackCClient):
    def explain(self, recommendation):
        return f"{recommendation['name']} is fine."


# --- complete(): no client available ---
# Patching _get_client() directly rather than relying on GROQ_API_KEY
# being absent from the environment - a real .env may or may not be
# present depending on who's running this suite, and these tests need to
# be true either way.

def test_complete_returns_none_without_a_client():
    with patch("agent_orchestrator.groq_client._get_client", return_value=None):
        assert complete("hello") is None


# --- GroqTrackCClient: falls back cleanly ---

def test_groq_track_c_client_falls_back_without_a_client():
    with patch("agent_orchestrator.groq_client._get_client", return_value=None):
        result = GroqTrackCClient().explain(SAMPLE)
    assert result == rule_based_explain(SAMPLE)


def test_groq_track_c_client_uses_llm_response_when_available():
    with patch("agent_orchestrator.track_c_client.complete", return_value="A lovely quiet fort nearby."):
        result = GroqTrackCClient().explain(SAMPLE)
    assert result == "A lovely quiet fort nearby."


# --- resolve_tie(): falls back cleanly ---

def test_resolve_tie_returns_none_without_a_client():
    with patch("agent_orchestrator.groq_client._get_client", return_value=None):
        assert resolve_tie(TIED_CANDIDATES, "somewhere quiet") is None


def test_resolve_tie_picks_the_indexed_candidate():
    with patch("agent_orchestrator.preference_resolver.complete", return_value="2"):
        result = resolve_tie(TIED_CANDIDATES, "somewhere quiet")
    assert result["destination_id"] == "dest_c"


def test_resolve_tie_handles_garbage_reply():
    with patch("agent_orchestrator.preference_resolver.complete", return_value="I'm not sure!"):
        result = resolve_tie(TIED_CANDIDATES, "somewhere quiet")
    assert result is None


def test_resolve_tie_handles_out_of_range_index():
    with patch("agent_orchestrator.preference_resolver.complete", return_value="99"):
        result = resolve_tie(TIED_CANDIDATES, "somewhere quiet")
    assert result is None


# --- orchestrate(): user_preference threading ---

def test_orchestrate_tie_without_preference_still_asks():
    with patch(
        "agent_orchestrator.orchestrator.check_and_widen_radius",
        return_value={"recommendations": TIED_CANDIDATES, "radius_used": 20, "radius_expanded": False},
    ):
        reading = {"destination_id": "dest_001", "crowd_level": "VERY_HIGH", "confidence_scores": [0.9]}
        result = orchestrate("dest_001", FakeTrackBClient(), FakeTrackCClient(), fresh_reading=reading)

    assert result["status"] == "needs_preference"


def test_orchestrate_tie_with_preference_but_no_groq_client_still_asks():
    with patch(
        "agent_orchestrator.orchestrator.check_and_widen_radius",
        return_value={"recommendations": TIED_CANDIDATES, "radius_used": 20, "radius_expanded": False},
    ), patch("agent_orchestrator.groq_client._get_client", return_value=None):
        reading = {"destination_id": "dest_001", "crowd_level": "VERY_HIGH", "confidence_scores": [0.9]}
        result = orchestrate(
            "dest_001", FakeTrackBClient(), FakeTrackCClient(),
            fresh_reading=reading, user_preference="somewhere quiet",
        )

    assert result["status"] == "needs_preference"


def test_orchestrate_tie_resolved_by_preference_promotes_the_choice():
    with patch(
        "agent_orchestrator.orchestrator.check_and_widen_radius",
        return_value={"recommendations": TIED_CANDIDATES, "radius_used": 20, "radius_expanded": False},
    ), patch("agent_orchestrator.preference_resolver.complete", return_value="2"):
        reading = {"destination_id": "dest_001", "crowd_level": "VERY_HIGH", "confidence_scores": [0.9]}
        result = orchestrate(
            "dest_001", FakeTrackBClient(), FakeTrackCClient(),
            fresh_reading=reading, user_preference="somewhere quiet",
        )

    assert result["status"] == "success"
    assert result["recommendations"][0]["destination_id"] == "dest_c"
    assert len(result["recommendations"]) == len(TIED_CANDIDATES)
