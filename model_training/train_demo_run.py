"""A real, short training run on this machine - not a simulation, not
just inspected metadata from someone else's checkpoint. Demonstrates the
same transfer-learning pipeline yolov8n_best.pt went through: start from
COCO-pretrained yolov8n.pt weights, fine-tune with backprop actually
running, log real per-epoch loss and accuracy.

Uses Ultralytics' coco128 sample set, not the original person-only data
yolov8n_best.pt was trained on - that dataset isn't available in this
environment, so this is a smaller-scope demonstration of the same
mechanics and hyperparameter choices (optimizer=auto, imgsz reduced from
640 to 320 and epochs reduced from 100 to 15 here only for CPU runtime -
everything else follows yolov8n_best.pt's own real recipe, extracted in
extract_training_history.py).

CPU-only on this machine, no GPU. Takes roughly 15-20 minutes for all 15
epochs. Run yourself to reproduce:
    python model_training/train_demo_run.py
"""

from pathlib import Path

from ultralytics import YOLO

RUN_DIR = Path(__file__).resolve().parent / ".train_run"


def main() -> None:
    model = YOLO("yolov8n.pt")
    model.train(
        data="coco128.yaml",
        epochs=15,
        imgsz=320,
        batch=16,
        workers=0,
        verbose=True,
        project=str(RUN_DIR),
        name="person_finetune_demo",
        exist_ok=True,
        plots=True,
        seed=0,
    )


if __name__ == "__main__":
    main()
