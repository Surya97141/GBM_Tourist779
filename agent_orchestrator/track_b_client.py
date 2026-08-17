"""Real TrackBClient implementation, wired to track_B_CV/main.py's
FastAPI app. Exercises the actual /detect-crowd endpoint (model load,
preprocessing, request/response validation included) without needing a
separately running server.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fastapi.testclient import TestClient

from agent_orchestrator.orchestrator import TrackBClient
from track_B_CV.main import app as track_b_app


class HttpTrackBClient(TrackBClient):
    def __init__(self):
        self._client = TestClient(track_b_app)

    def detect(self, image_bytes: bytes, destination_id: str) -> dict:
        response = self._client.post(
            "/detect-crowd",
            files={"file": ("photo.jpg", image_bytes, "image/jpeg")},
            data={"destination_id": destination_id},
        )
        response.raise_for_status()
        return response.json()
