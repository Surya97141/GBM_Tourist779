from shared.barrier_store import barrier_store


def test_set_then_get_roundtrip():
    barrier_store.set("dest_001", "HIGH", estimated_count=20)
    reading = barrier_store.get("dest_001")

    assert reading["destination_id"] == "dest_001"
    assert reading["crowd_level"] == "HIGH"
    assert reading["estimated_count"] == 20
    assert reading["recent_readings"] == []


def test_get_missing_destination_returns_none():
    assert barrier_store.get("dest_never_set") is None


def test_is_fresh_true_immediately_after_set():
    barrier_store.set("dest_002", "LOW", estimated_count=1)
    assert barrier_store.is_fresh("dest_002", max_age_minutes=30) is True


def test_is_fresh_false_for_missing_destination():
    assert barrier_store.is_fresh("dest_never_set", max_age_minutes=30) is False


def test_expired_reading_is_not_returned_by_get():
    barrier_store.set("dest_003", "HIGH", estimated_count=10, ttl_minutes=-1)
    assert barrier_store.get("dest_003") is None


def test_is_fresh_ignores_the_entrys_own_ttl():
    # is_fresh() only compares against the max_age_minutes argument, never
    # the entry's own ttl_minutes - so an entry get() already treats as
    # expired can still report fresh here if max_age_minutes is more
    # lenient than the entry's ttl_minutes. check_staleness() in the
    # orchestrator is safe from this because it always calls get() first
    # and short-circuits on None before consulting is_fresh() - but this
    # method isn't safe to call on its own. Asserting the real behavior
    # here rather than silently editing shared/barrier_store.py, which is
    # off-limits this session.
    barrier_store.set("dest_003", "HIGH", estimated_count=10, ttl_minutes=-1)
    assert barrier_store.is_fresh("dest_003", max_age_minutes=30) is True


def test_set_overwrites_previous_reading():
    barrier_store.set("dest_004", "LOW", estimated_count=2)
    barrier_store.set("dest_004", "VERY_HIGH", estimated_count=50)

    reading = barrier_store.get("dest_004")
    assert reading["crowd_level"] == "VERY_HIGH"
    assert reading["estimated_count"] == 50
