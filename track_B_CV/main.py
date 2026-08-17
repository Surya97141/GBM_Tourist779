
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import io
import cv2
from fastapi import FastAPI, File, Form,UploadFile
from fastapi.responses import Response
import numpy as np
from PIL import Image
from ultralytics import YOLO

from shared.barrier_store import barrier_store

app = FastAPI(title=" ML Service - Track A & B")
model = YOLO("yolov8n_best.pt")


def preprocess_image(image_bytes: bytes) -> np.ndarray:
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    imgbgr = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)

    h, w = imgbgr.shape[:2]
    if max(h, w) > 640:
        scale = 640 / max(h, w)
        imgbgr = cv2.resize(imgbgr, (int(w * scale), int(h * scale)))
    gray = cv2.cvtColor(imgbgr, cv2.COLOR_BGR2GRAY)
    if np.mean(gray) < 80:
        lab = cv2.cvtColor(imgbgr, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        l_enhanced = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(
            l
        )
        imgbgr = cv2.cvtColor(
            cv2.merge((l_enhanced, a, b)), cv2.COLOR_LAB2BGR
        )

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


def drawgrid(image: np.ndarray) -> np.ndarray:
    grid_img = image.copy()
    h, w, _ = grid_img.shape
    gridclr = (0, 0, 255)
    thickness = 3
    cv2.line(grid_img, (w // 3, 0), (w // 3, h), gridclr, thickness)
    cv2.line(grid_img, (2 * w // 3, 0), (2 * w // 3, h), gridclr, thickness)
    cv2.line(grid_img, (0, h // 3), (w, h // 3), gridclr, thickness)
    cv2.line(grid_img, (0, 2 * h // 3), (w, 2 * h // 3), gridclr, thickness)
    return grid_img


@app.get("/")
def home():
    return {"message": "crowd detection api is running"}


@app.post("/detect-crowd")
async def detect_crowd( destination_id:str=Form(...),file: UploadFile = File(...)):
    try:
        contents = await file.read()
        processed_img = preprocess_image(contents)

        results = model.predict(
            source=processed_img, classes=[0], conf=0.35, verbose=False
        )

        boxes = results[0].boxes
        estimated_count = len(boxes) if boxes is not None else 0
        crowd_level = determine_crowd_level(estimated_count)
        barrier_store.set(destination_id, crowd_level, estimated_count)

        return {
            "status": "success",
            "destination_id": destination_id,
            "estimated_count": estimated_count,
            "crowd_level": crowd_level,
            "confidence_scores": (
                [round(float(c), 2) for c in boxes.conf.tolist()]
                if boxes is not None and len(boxes) > 0
                else []
            ),
        }

    except Exception as e:
        return {
            "status": "fallback",
            "destination_id":destination_id,
            "estimated_count": None,
            "crowd_level": "unknown",
            "error_message": str(e),
        }


@app.post("/detect-image")
async def detect_image(file: UploadFile = File(...)):
    contents = await file.read()
    processed_img = preprocess_image(contents)
    results = model.predict(
        source=processed_img, classes=[0], conf=0.35, verbose=False
    )
    annote_img = drawgrid(results[0].plot())
    _, encoded_img = cv2.imencode(".jpg", annote_img)
    return Response(content=encoded_img.tobytes(), media_type="image/jpeg")

       