import json
from pathlib import Path

import pytest

from shared.barrier_store import barrier_store
from track_A_filtering.recommend import get_recommendations, haversine_km

DESTINATIONS_PATH = Path(__file__).resolve().parent.parent / "track_A_filtering" / "destinations.json"


def _destination_ids():
    with open(DESTINATIONS_PATH, encoding="utf-8") as f:
        return [d["destination_id"] for d in json.load(f)]


def test_haversine_same_point_is_zero():
    assert haversine_km(26.9855, 75.8513, 26.9855, 75.8513) == pytest.approx(0.0, abs=1e-9)


def test_haversine_known_distance():
    # roughly Amber Fort to City Palace, Jaipur - a few km apart
    d = haversine_km(26.9855, 75.8513, 26.9258, 75.8237)
    assert 5 < d < 10


def test_get_recommendations_shape():
    result = get_recommendations("dest_001")

    assert result["origin_destination_id"] == "dest_001"
    assert isinstance(result["recommendations"], list)
    assert len(result["recommendations"]) <= 3

    for rec in result["recommendations"]:
        assert set(rec.keys()) == {
            "destination_id", "name", "category",
            "similarity_score", "distance_km", "final_score",
        }


def test_get_recommendations_excludes_origin():
    result = get_recommendations("dest_001")
    ids = [r["destination_id"] for r in result["recommendations"]]
    assert "dest_001" not in ids


def test_get_recommendations_excludes_barriered_candidates():
    baseline = get_recommendations("dest_001")
    top_id = baseline["recommendations"][0]["destination_id"]

    barrier_store.set(top_id, "VERY_HIGH", estimated_count=100)
    result = get_recommendations("dest_001")

    assert top_id not in [r["destination_id"] for r in result["recommendations"]]


def test_get_recommendations_unknown_destination_raises():
    with pytest.raises(ValueError):
        get_recommendations("dest_does_not_exist")


def test_returns_empty_list_when_everything_is_barriered():
    for dest_id in _destination_ids():
        barrier_store.set(dest_id, "VERY_HIGH", estimated_count=100)

    result = get_recommendations("dest_021", radius_km=40)
    assert result["recommendations"] == []
