"""Turns the real results.csv from train_demo_run.py's training run into
the same style of graphs as extract_training_history.py - reads logged
numbers directly, plots nothing that wasn't actually recorded during the
run.

Run after train_demo_run.py has finished:
    python model_training/plot_demo_run.py
"""

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

RUN_DIR = Path(__file__).resolve().parent / ".train_run" / "runs" / "detect" / "person_finetune_demo"
OUTPUT_DIR = Path(__file__).resolve().parent / "outputs"


def main() -> None:
    results = pd.read_csv(RUN_DIR / "results.csv")
    results.columns = [c.strip() for c in results.columns]

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(results["epoch"], results["train/box_loss"], label="box_loss")
    ax.plot(results["epoch"], results["train/cls_loss"], label="cls_loss")
    ax.plot(results["epoch"], results["train/dfl_loss"], label="dfl_loss")
    ax.set_xlabel("epoch")
    ax.set_ylabel("training loss")
    ax.set_title("Demo run — training loss over 15 epochs (this machine, this session)")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "demo_run_loss.png", dpi=150)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(results["epoch"], results["metrics/precision(B)"], label="precision")
    ax.plot(results["epoch"], results["metrics/recall(B)"], label="recall")
    ax.plot(results["epoch"], results["metrics/mAP50(B)"], label="mAP50")
    ax.plot(results["epoch"], results["metrics/mAP50-95(B)"], label="mAP50-95")
    ax.set_xlabel("epoch")
    ax.set_ylabel("score")
    ax.set_title("Demo run — validation accuracy over 15 epochs (this machine, this session)")
    ax.set_ylim(0, 1)
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "demo_run_accuracy.png", dpi=150)
    plt.close(fig)

    last = results.iloc[-1]
    print(f"final mAP50: {last['metrics/mAP50(B)']:.3f}")
    print(f"final mAP50-95: {last['metrics/mAP50-95(B)']:.3f}")
    print(f"final precision: {last['metrics/precision(B)']:.3f}")
    print(f"final recall: {last['metrics/recall(B)']:.3f}")
    print(f"wrote {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
