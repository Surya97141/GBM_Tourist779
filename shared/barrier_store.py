"""In-memory TTL store for live crowd readings.

Track B writes readings here after each detection. Track A and the
orchestrator read from it to decide whether a destination is currently
barriered and whether a reading is still fresh enough to trust.
"""

import threading
from datetime import datetime, timedelta, timezone

DEFAULT_TTL_MINUTES = 30


class BarrierStore:
    def __init__(self):
        self._entries: dict[str, dict] = {}
        self._lock = threading.Lock()

    def set(
        self,
        destination_id: str,
        crowd_level: str,
        estimated_count: int | None = None,
        ttl_minutes: int = DEFAULT_TTL_MINUTES,
    ) -> None:
        with self._lock:
            self._entries[destination_id] = {
                "destination_id": destination_id,
                "crowd_level": crowd_level,
                "estimated_count": estimated_count,
                "timestamp": datetime.now(timezone.utc),
                "ttl_minutes": ttl_minutes,
                # Reserved for a future footfall-trend feature (multi-frame
                # tracking, not single-photo detection). Intentionally left
                # empty here so the schema doesn't need to change shape later.
                "recent_readings": [],
            }

    def get(self, destination_id: str) -> dict | None:
        with self._lock:
            entry = self._entries.get(destination_id)
            if entry is None or self._is_expired(entry):
                return None
            return dict(entry)

    def is_fresh(self, destination_id: str, max_age_minutes: int) -> bool:
        with self._lock:
            entry = self._entries.get(destination_id)
            if entry is None:
                return False
            age = datetime.now(timezone.utc) - entry["timestamp"]
            return age <= timedelta(minutes=max_age_minutes)

    @staticmethod
    def _is_expired(entry: dict) -> bool:
        age = datetime.now(timezone.utc) - entry["timestamp"]
        return age > timedelta(minutes=entry["ttl_minutes"])


# Shared singleton — Track B, Track A, and the orchestrator all read/write
# the same store within one process.
barrier_store = BarrierStore()
