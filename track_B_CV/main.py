import io
import cv2
import numpy as np
from fastapi import FastAPI, File, UploadFile, Form
from PIL import Image
from ultralytics import YOLO

app = FastAPI(title="ML Service - Track A & B")

# FIX 3: CrowdHuman-fine-tuned weights instead of plain COCO-trained yolov8n.pt
# Better at detecting people in dense, overlapping crowd scenes.
model = YOLO("yolov8n_best.pt")


def preprocess_image(image_bytes: bytes) -> np.ndarray:
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    imgbgr = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
    h, w = imgbgr.shape[:2]
    if max(h, w) > 640:  # autosize
        scale = 640 / max(h, w)
        imgbgr = cv2.resize(imgbgr, (int(w * scale), int(h * scale)))
    gray = cv2.cvtColor(imgbgr, cv2.COLOR_BGR2GRAY)
    if np.mean(gray) < 80:
        lab = cv2.cvtColor(imgbgr, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        l_enhanced = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(l)
        imgbgr = cv2.cvtColor(cv2.merge((l_enhanced, a, b)), cv2.COLOR_LAB2BGR)
    return imgbgr


def determine_crowd_level(count: int) -> str:
    if count <= 5:
        return "LOW"
    elif count <= 15:
        return "MEDIUM"
    elif count <= 35:
        return "HIGH"
    else:
        return "VERY_HIGH"


@app.get("/")
def health_check():
    return {"status": "running", "service": "SIH ML Engine"}


@app.post("/detect-crowd")
async def detect_crowd(
    file: UploadFile = File(...),
    # FIX 1: destination_id is now required. Without this, a crowd reading
    # has nowhere to attach itself in the Barrier State Store, and Track A
    # can never know which place this result belongs to.
    destination_id: str = Form(...),
):
    try:
        contents = await file.read()
        processed_img = preprocess_image(contents)
        results = model.predict(
            source=processed_img, classes=[0], conf=0.20, verbose=False
        )
        boxes = results[0].boxes
        estimated_count = len(boxes) if boxes is not None else 0
        crowd_level = determine_crowd_level(estimated_count)

        # TODO (Phase 2, Backend owner): write this result into the
        # shared Barrier State Store here, keyed by destination_id, e.g.
        # barrier_store.set(destination_id, crowd_level, ttl_minutes=30)

        return {
            "status": "success",
            "destination_id": destination_id,
            "estimated_count": estimated_count,
            "crowd_level": crowd_level,
            "confidence_scores": [round(float(c), 2) for c in boxes.conf.tolist()]
            if boxes
            else [],
        }
    except Exception as e:

        # FIX 2: on failure, report "unknown" — not "LOW". A crashed
        # detection is NOT the same as a verified empty scene. Reporting
        # "LOW" here could silently mask a genuinely dangerous crowd.
        return {
            "status": "fallback",
            "destination_id": destination_id,
            "estimated_count": None,
            "crowd_level": "unknown",
            "error_message": str(e),
        }