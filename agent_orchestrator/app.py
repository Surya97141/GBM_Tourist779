"""Single entrypoint tying Track B, the orchestrator, Track A, and Track C
into one request path. Run with:
    uvicorn agent_orchestrator.app:app --reload
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv

load_dotenv(REPO_ROOT / ".env")

from fastapi import FastAPI, File, Form, UploadFile

from agent_orchestrator.orchestrator import check_staleness, orchestrate
from agent_orchestrator.track_b_client import HttpTrackBClient
from agent_orchestrator.track_c_client import GroqTrackCClient

app = FastAPI(title="Tourist Crowd Recommendation Service")

track_b_client = HttpTrackBClient()
track_c_client = GroqTrackCClient()

MAX_UPLOAD_BYTES = 10 * 1024 * 1024


@app.get("/")
def health_check():
    return {"status": "running", "service": "agent orchestrator"}


@app.post("/recommend")
async def recommend(
    destination_id: str = Form(...),
    file: UploadFile = File(...),
    preference: str | None = Form(None),
):
    if not destination_id.strip():
        return {"status": "invalid_request", "message": "destination_id is required"}

    if not (file.content_type or "").startswith("image/"):
        return {"status": "invalid_request", "message": "file must be an image"}

    image_bytes = await file.read()

    if not image_bytes:
        return {"status": "invalid_request", "message": "uploaded file is empty"}

    if len(image_bytes) > MAX_UPLOAD_BYTES:
        return {"status": "invalid_request", "message": "uploaded file is too large"}

    staleness = check_staleness(destination_id, track_b_client)
    fresh_reading = None
    if staleness["needs_remeasure"]:
        fresh_reading = track_b_client.detect(image_bytes, destination_id)

    return orchestrate(
        destination_id,
        track_b_client,
        track_c_client,
        fresh_reading=fresh_reading,
        user_preference=preference,
    )
