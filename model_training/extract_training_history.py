"""Pulls the real training history out of yolov8n_best.pt and plots it.

Ultralytics checkpoints keep the full per-epoch training log inside the
.pt file itself (train_results), not just the final weights - this reads
that directly rather than re-deriving or approximating anything. Anyone
can rerun this against the same checkpoint and get identical graphs.

Run from the repo root:
    python model_training/extract_training_history.py
"""

import json
from pathlib import Path

import matplotlib.pyplot as plt
import torch

REPO_ROOT = Path(__file__).resolve().parent.parent
CHECKPOINT_PATH = REPO_ROOT / "track_B_CV" / "yolov8n_best.pt"
OUTPUT_DIR = Path(__file__).resolve().parent / "outputs"


def load_checkpoint() -> dict:
    return torch.load(CHECKPOINT_PATH, map_location="cpu", weights_only=False)


def plot_losses(results: dict, out_path: Path) -> None:
    epochs = results["epoch"]
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(epochs, results["train/box_loss"], label="box_loss")
    ax.plot(epochs, results["train/cls_loss"], label="cls_loss")
    ax.plot(epochs, results["train/dfl_loss"], label="dfl_loss")
    ax.set_xlabel("epoch")
    ax.set_ylabel("training loss")
    ax.set_title("yolov8n_best.pt — training loss over 100 epochs (real logged values)")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def plot_accuracy(results: dict, out_path: Path) -> None:
    epochs = results["epoch"]
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(epochs, results["metrics/precision(B)"], label="precision")
    ax.plot(epochs, results["metrics/recall(B)"], label="recall")
    ax.plot(epochs, results["metrics/mAP50(B)"], label="mAP50")
    ax.plot(epochs, results["metrics/mAP50-95(B)"], label="mAP50-95")
    ax.set_xlabel("epoch")
    ax.set_ylabel("score")
    ax.set_title("yolov8n_best.pt — validation accuracy over 100 epochs (real logged values)")
    ax.set_ylim(0, 1)
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def main() -> None:
    ckpt = load_checkpoint()
    results = ckpt["train_results"]

    OUTPUT_DIR.mkdir(exist_ok=True)
    plot_losses(results, OUTPUT_DIR / "training_loss.png")
    plot_accuracy(results, OUTPUT_DIR / "validation_accuracy.png")

    summary = {
        "trained": ckpt["date"],
        "ultralytics_version": ckpt["version"],
        "epochs": ckpt["train_args"]["epochs"],
        "batch_size": ckpt["train_args"]["batch"],
        "image_size": ckpt["train_args"]["imgsz"],
        "final_metrics": ckpt["train_metrics"],
        "class_names": ckpt["model"].names,
    }
    with open(OUTPUT_DIR / "training_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)

    print(f"trained {summary['epochs']} epochs on {summary['trained']}")
    print(f"final mAP50: {summary['final_metrics']['metrics/mAP50(B)']:.3f}")
    print(f"final mAP50-95: {summary['final_metrics']['metrics/mAP50-95(B)']:.3f}")
    print(f"final precision: {summary['final_metrics']['metrics/precision(B)']:.3f}")
    print(f"final recall: {summary['final_metrics']['metrics/recall(B)']:.3f}")
    print(f"wrote {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
