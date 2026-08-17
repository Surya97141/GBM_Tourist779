from track_C_NLP.explain import explain

SAMPLE = {
    "destination_id": "dest_006",
    "name": "Jaigarh Fort",
    "category": "Heritage",
    "similarity_score": 0.7152,
    "distance_km": 0.3,
    "final_score": 0.7962,
}


def test_explain_mentions_the_destination_name():
    assert "Jaigarh Fort" in explain(SAMPLE)


def test_explain_is_deterministic():
    assert explain(SAMPLE) == explain(SAMPLE)


def test_explain_handles_unknown_category():
    rec = dict(SAMPLE, category="Some New Category")
    result = explain(rec)
    assert "Jaigarh Fort" in result


def test_explain_close_distance_phrasing():
    rec = dict(SAMPLE, distance_km=0.4)
    assert "short walk" in explain(rec)


def test_explain_far_distance_phrasing():
    rec = dict(SAMPLE, distance_km=15.0)
    assert "15 km" in explain(rec)
