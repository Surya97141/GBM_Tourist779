"""Measures real parameter count, GFLOPs, and inference latency across
YOLOv8 sizes on this machine, to back up why the nano variant was picked
for this project rather than asserting it without evidence.

Downloads yolov8n.pt / yolov8s.pt / yolov8m.pt (Ultralytics' official
COCO-pretrained weights - same architecture family as yolov8n_best.pt,
just not fine-tuned) if not already cached locally. Timing is CPU-only,
matching how this project actually runs, not a GPU benchmark that
wouldn't reflect real deployment conditions.

Run from the repo root:
    python model_training/compare_variants.py
"""

import json
import time
from pathlib import Path

import numpy as np
from ultralytics import YOLO

VARIANTS = ["yolov8n.pt", "yolov8s.pt", "yolov8m.pt"]
WARMUP_RUNS = 2
TIMED_RUNS = 10
OUTPUT_DIR = Path(__file__).resolve().parent / "outputs"


def benchmark(weights: str) -> dict:
    model = YOLO(weights)
    info = model.info(verbose=True)
    layers, params, gradients, gflops = info

    dummy_image = np.random.randint(0, 255, (640, 640, 3), dtype=np.uint8)

    for _ in range(WARMUP_RUNS):
        model.predict(source=dummy_image, verbose=False)

    timings = []
    for _ in range(TIMED_RUNS):
        start = time.perf_counter()
        model.predict(source=dummy_image, verbose=False)
        timings.append(time.perf_counter() - start)

    return {
        "weights": weights,
        "params": params,
        "gflops": round(gflops, 2),
        "avg_inference_ms": round(1000 * sum(timings) / len(timings), 1),
        "min_inference_ms": round(1000 * min(timings), 1),
    }


def main() -> None:
    results = [benchmark(v) for v in VARIANTS]

    OUTPUT_DIR.mkdir(exist_ok=True)
    with open(OUTPUT_DIR / "variant_comparison.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print(f"{'weights':<14}{'params':>12}{'gflops':>10}{'avg ms':>10}{'min ms':>10}")
    for r in results:
        print(f"{r['weights']:<14}{r['params']:>12,}{r['gflops']:>10}{r['avg_inference_ms']:>10}{r['min_inference_ms']:>10}")


if __name__ == "__main__":
    main()
