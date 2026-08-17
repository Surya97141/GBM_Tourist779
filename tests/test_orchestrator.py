import json
from pathlib import Path

from shared.barrier_store import barrier_store
from agent_orchestrator.orchestrator import (
    TrackBClient,
    TrackCClient,
    check_and_widen_radius,
    check_confidence,
    check_staleness,
    orchestrate,
    should_ask_preference,
)

DESTINATIONS_PATH = Path(__file__).resolve().parent.parent / "track_A_filtering" / "destinations.json"


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
        return f"{recommendation['name']} is a fine alternative."


def _destination_ids():
    with open(DESTINATIONS_PATH, encoding="utf-8") as f:
        return [d["destination_id"] for d in json.load(f)]


# --- check_staleness ---

def test_check_staleness_no_reading_needs_remeasure():
    result = check_staleness("dest_002", FakeTrackBClient())
    assert result == {"fresh": False, "needs_remeasure": True, "current_reading": None}


def test_check_staleness_fresh_reading():
    barrier_store.set("dest_002", "LOW", estimated_count=1)
    result = check_staleness("dest_002", FakeTrackBClient())
    assert result["fresh"] is True
    assert result["needs_remeasure"] is False
    assert result["current_reading"]["crowd_level"] == "LOW"


# --- check_confidence ---

def test_check_confidence_empty_scores_is_sufficient():
    assert check_confidence({"confidence_scores": []}) == {"sufficient": True}


def test_check_confidence_missing_key_is_sufficient():
    assert check_confidence({}) == {"sufficient": True}


def test_check_confidence_low_average_is_insufficient():
    result = check_confidence({"confidence_scores": [0.1, 0.2]})
    assert result["sufficient"] is False
    assert "0.15" in result["reason"]


def test_check_confidence_high_average_is_sufficient():
    assert check_confidence({"confidence_scores": [0.8, 0.9]}) == {"sufficient": True}


# --- check_and_widen_radius ---

def test_widen_radius_not_needed_when_default_has_results():
    result = check_and_widen_radius("dest_001")
    assert result["radius_used"] == 20
    assert result["radius_expanded"] is False
    assert len(result["recommendations"]) > 0


def test_widen_radius_retries_once_when_default_is_empty():
    for dest_id in _destination_ids():
        barrier_store.set(dest_id, "VERY_HIGH", estimated_count=100)

    result = check_and_widen_radius("dest_021")
    assert result["radius_used"] == 40
    assert result["radius_expanded"] is True


# --- should_ask_preference ---

def test_should_ask_preference_clear_winner():
    scores = [{"final_score": 0.8}, {"final_score": 0.68}, {"final_score": 0.64}]
    assert should_ask_preference(scores) is False


def test_should_ask_preference_many_tied():
    scores = [{"final_score": 0.80}, {"final_score": 0.79}, {"final_score": 0.78}, {"final_score": 0.77}]
    assert should_ask_preference(scores) is True


def test_should_ask_preference_empty_list():
    assert should_ask_preference([]) is False


# --- orchestrate: all six outcomes ---

def test_orchestrate_needs_remeasure():
    result = orchestrate("dest_002", FakeTrackBClient(), FakeTrackCClient())
    assert result["status"] == "needs_remeasure"


def test_orchestrate_needs_second_photo():
    reading = {"destination_id": "dest_003", "crowd_level": "HIGH", "confidence_scores": [0.1, 0.2]}
    result = orchestrate("dest_003", FakeTrackBClient(), FakeTrackCClient(), fresh_reading=reading)
    assert result["status"] == "needs_second_photo"


def test_orchestrate_not_barriered():
    reading = {"destination_id": "dest_003", "crowd_level": "LOW", "confidence_scores": [0.9]}
    result = orchestrate("dest_003", FakeTrackBClient(), FakeTrackCClient(), fresh_reading=reading)
    assert result["status"] == "not_barriered"


def test_orchestrate_detection_failed():
    reading = {"destination_id": "dest_004", "crowd_level": "unknown", "error_message": "timed out"}
    result = orchestrate("dest_004", FakeTrackBClient(), FakeTrackCClient(), fresh_reading=reading)
    assert result["status"] == "detection_failed"
    assert result["message"] == "timed out"


def test_orchestrate_unknown_destination():
    reading = {"destination_id": "dest_ghost", "crowd_level": "VERY_HIGH", "confidence_scores": [0.9]}
    result = orchestrate("dest_ghost", FakeTrackBClient(), FakeTrackCClient(), fresh_reading=reading)
    assert result["status"] == "unknown_destination"


def test_orchestrate_no_alternatives_found():
    for dest_id in _destination_ids():
        barrier_store.set(dest_id, "VERY_HIGH", estimated_count=100)

    reading = {"destination_id": "dest_021", "crowd_level": "VERY_HIGH", "confidence_scores": [0.9]}
    result = orchestrate("dest_021", FakeTrackBClient(), FakeTrackCClient(), fresh_reading=reading)

    assert result["status"] == "no_alternatives_found"
    assert result["radius_expanded"] is True


def test_orchestrate_success():
    reading = {"destination_id": "dest_001", "crowd_level": "VERY_HIGH", "confidence_scores": [0.8, 0.9]}
    result = orchestrate("dest_001", FakeTrackBClient(), FakeTrackCClient(), fresh_reading=reading)

    assert result["status"] == "success"
    assert len(result["recommendations"]) > 0
    for rec in result["recommendations"]:
        assert "explanation" in rec
