"""Live camera overlay for demo purposes only.

Not part of the API — this opens a local window against a live video feed
so the detection model can be shown working in real time at a venue. The
live loop itself still runs its own private inference purely for display
and never touches shared/barrier_store.py directly.

One manual exception: pressing S sends the current frame as a real HTTP
request to the actual running orchestrator service, so a judge can see
the real pipeline's answer for one frame on demand. That's the only path
that reaches barrier_store, and only when explicitly triggered - nothing
about the rest of this script's behavior changes because of it.

Run from this directory:
    python live_demo.py
Press ESC to quit. Press a number key to pick which destination this
camera currently represents. Press S to submit the current frame to the
real pipeline (agent_orchestrator/app.py must already be running - see
RECOMMEND_ENDPOINT and DEMO_DESTINATIONS below).
"""

import json
import os
import threading
import time

import cv2
import requests
from ultralytics import YOLO

from main import determine_crowd_level, drawgrid

STREAM_URL = "http://10.118.197.253:8080/video"

RECOMMEND_ENDPOINT = "http://127.0.0.1:8000/recommend"

DEMO_DESTINATIONS = [
    ("dest_001", "Amber Fort"),
    ("dest_006", "Jaigarh Fort"),
    ("dest_003", "Hawa Mahal"),
    ("dest_012", "Johari Bazaar"),
    ("dest_009", "Birla Mandir"),
]
SELECT_KEYS = {ord(str(i + 1)): i for i in range(len(DEMO_DESTINATIONS))}

MODEL_WEIGHTS = "yolov8n_best.pt"
PERSON_CLASS = [0]
CONF_THRESHOLD = 0.35
ESC_KEY = 27
SUBMIT_KEY = ord("s")
SUBMIT_TIMEOUT_SECONDS = 15
SUBMIT_MESSAGE_SECONDS = 4

MIN_WEIGHTS_BYTES = 1_000_000

if os.path.exists(MODEL_WEIGHTS) and os.path.getsize(MODEL_WEIGHTS) < MIN_WEIGHTS_BYTES:
    print(
        f"warning: {MODEL_WEIGHTS} is only {os.path.getsize(MODEL_WEIGHTS)} bytes - "
        f"looks like a placeholder, not real weights. YOLO() will likely fall back "
        f"to downloading a different model instead of failing loudly."
    )

model = YOLO(MODEL_WEIGHTS)


def draw_readout(frame, count, crowd_level):
    text = f"Count: {count}  Level: {crowd_level}"
    cv2.putText(
        frame, text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2, cv2.LINE_AA
    )
    return frame


def draw_hint(frame, num_destinations):
    h = frame.shape[0]
    cv2.putText(
        frame, f"1-{num_destinations}: select destination | S: submit | ESC: quit",
        (10, h - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA
    )
    return frame


def draw_selected_destination(frame, destination_id, name):
    text = f"Target: {name} ({destination_id})"
    cv2.putText(
        frame, text, (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 200, 0), 1, cv2.LINE_AA
    )
    return frame


def draw_submit_banner(frame, message):
    cv2.putText(
        frame, message, (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 200, 255), 2, cv2.LINE_AA
    )
    return frame


def submit_current_frame(frame, destination_id):
    ok, encoded = cv2.imencode(".jpg", frame)
    if not ok:
        return {"status": "error", "message": "failed to encode frame as JPEG"}

    try:
        response = requests.post(
            RECOMMEND_ENDPOINT,
            data={"destination_id": destination_id},
            files={"file": ("frame.jpg", encoded.tobytes(), "image/jpeg")},
            timeout=SUBMIT_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.ConnectionError:
        return {
            "status": "error",
            "message": f"could not reach the orchestrator at {RECOMMEND_ENDPOINT} - is agent_orchestrator/app.py running?",
        }
    except requests.exceptions.Timeout:
        return {"status": "error", "message": f"request timed out after {SUBMIT_TIMEOUT_SECONDS}s"}
    except requests.exceptions.RequestException as e:
        return {"status": "error", "message": str(e)}


def summarize_response(response):
    status = response.get("status", "unknown")
    if status == "success":
        count = len(response.get("recommendations", []))
        return f"Sent! {count} alternative(s) found"
    if status == "not_barriered":
        return f"Sent! Not crowded ({response.get('crowd_level', '?')})"
    if status == "no_alternatives_found":
        return "Sent! Crowded, but no alternatives nearby"
    if status == "needs_preference":
        return "Sent! Several good options - ask for a preference"
    if status == "needs_second_photo":
        return "Sent! Confidence too low - retake photo"
    if status == "detection_failed":
        return "Sent! Server-side detection failed"
    if status == "unknown_destination":
        return f"Sent! Unknown destination_id: {response.get('destination_id')}"
    if status == "invalid_request":
        return f"Rejected: {response.get('message', 'invalid request')}"
    if status == "error":
        return f"Failed: {response.get('message', 'unknown error')}"
    return f"Sent! status={status}"


def print_response(response, destination_id):
    print("\n" + "=" * 60)
    print(f"SUBMITTED FRAME -> {RECOMMEND_ENDPOINT}  (destination_id={destination_id})")
    print("-" * 60)
    print(json.dumps(response, indent=2))
    print("=" * 60 + "\n")


class LatestFrameReader:
    """Runs cap.read() continuously on a background thread and keeps only
    the single most recent frame, so the display loop always works on
    whatever is newest instead of working through a backlog. A queue
    would just move the same buffering problem here instead of removing
    it - this keeps exactly one frame around, ever, and it's fine and
    expected for frames to be skipped entirely if inference can't keep up.

    cv2.CAP_PROP_BUFFERSIZE looks like the obvious fix but isn't reliable
    here - it's honored inconsistently on FFMPEG-backed network streams
    specifically, which is what STREAM_URL is, so it doesn't actually
    bound the lag on this kind of source. Hence a thread instead.
    """

    def __init__(self, cap):
        self._cap = cap
        self._lock = threading.Lock()
        self._frame = None
        self._running = True
        self._thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._thread.start()

    def _reader_loop(self):
        while self._running:
            ok, frame = self._cap.read()
            if ok:
                with self._lock:
                    self._frame = frame

    def read(self):
        with self._lock:
            if self._frame is None:
                return False, None
            return True, self._frame.copy()

    def stop(self):
        self._running = False
        self._thread.join()


def main():
    cap = cv2.VideoCapture(STREAM_URL)
    reader = LatestFrameReader(cap)
    selected_index = 0
    banner_message = None
    banner_expires_at = 0.0

    while True:
        ok, frame = reader.read()
        if not ok:
            if cv2.waitKey(1) & 0xFF == ESC_KEY:
                break
            continue

        results = model.predict(source=frame, classes=PERSON_CLASS, conf=CONF_THRESHOLD, verbose=False)
        boxes = results[0].boxes
        count = len(boxes) if boxes is not None else 0
        crowd_level = determine_crowd_level(count)

        destination_id, destination_name = DEMO_DESTINATIONS[selected_index]

        annotated = drawgrid(results[0].plot())
        draw_readout(annotated, count, crowd_level)
        draw_selected_destination(annotated, destination_id, destination_name)
        draw_hint(annotated, len(DEMO_DESTINATIONS))

        if banner_message is not None and time.time() < banner_expires_at:
            draw_submit_banner(annotated, banner_message)

        cv2.imshow("Live Crowd Demo", annotated)

        key = cv2.waitKey(1) & 0xFF
        if key == ESC_KEY:
            break
        if key == SUBMIT_KEY:
            response = submit_current_frame(frame, destination_id)
            print_response(response, destination_id)
            banner_message = summarize_response(response)
            banner_expires_at = time.time() + SUBMIT_MESSAGE_SECONDS
        elif key in SELECT_KEYS:
            selected_index = SELECT_KEYS[key]
            destination_id, destination_name = DEMO_DESTINATIONS[selected_index]
            banner_message = f"Now: {destination_name} ({destination_id})"
            banner_expires_at = time.time() + SUBMIT_MESSAGE_SECONDS

    reader.stop()
    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
