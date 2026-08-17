import io

from fastapi.testclient import TestClient
from PIL import Image

from agent_orchestrator.app import app
from shared.barrier_store import barrier_store

client = TestClient(app)


def _fake_photo():
    img = Image.new("RGB", (100, 100), color=(200, 200, 200))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    buf.seek(0)
    return buf


def test_recommend_full_path_with_preseeded_reading():
    barrier_store.set("dest_001", "VERY_HIGH", estimated_count=40)

    response = client.post(
        "/recommend",
        data={"destination_id": "dest_001"},
        files={"file": ("photo.jpg", _fake_photo(), "image/jpeg")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert len(body["recommendations"]) > 0
    assert "explanation" in body["recommendations"][0]


def test_recommend_real_detection_writes_to_barrier_store():
    response = client.post(
        "/recommend",
        data={"destination_id": "dest_010"},
        files={"file": ("photo.jpg", _fake_photo(), "image/jpeg")},
    )

    assert response.status_code == 200
    assert barrier_store.get("dest_010") is not None


def test_recommend_unknown_destination():
    barrier_store.set("dest_ghost", "VERY_HIGH", estimated_count=40)

    response = client.post(
        "/recommend",
        data={"destination_id": "dest_ghost"},
        files={"file": ("photo.jpg", _fake_photo(), "image/jpeg")},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "unknown_destination"


def test_recommend_rejects_non_image_upload():
    response = client.post(
        "/recommend",
        data={"destination_id": "dest_001"},
        files={"file": ("notes.txt", io.BytesIO(b"not a photo"), "text/plain")},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "invalid_request"


def test_recommend_rejects_empty_upload():
    response = client.post(
        "/recommend",
        data={"destination_id": "dest_001"},
        files={"file": ("photo.jpg", io.BytesIO(b""), "image/jpeg")},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "invalid_request"
