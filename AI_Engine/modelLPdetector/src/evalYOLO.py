"""
Đánh giá YOLO LP-detector trên tập val/test, ghi metrics ra JSON
để DVC track theo từng version (xem `dvc metrics show`).
"""
import json
import sys
from pathlib import Path

import yaml
from ultralytics import YOLO

REPO_ROOT = Path(__file__).resolve().parents[3]
PARAMS_FILE = REPO_ROOT / "params.yaml"
METRICS_FILE = REPO_ROOT / "metrics" / "detector.json"


def evaluate() -> dict:
    params = yaml.safe_load(PARAMS_FILE.read_text(encoding="utf-8"))["detector"]
    weights = REPO_ROOT / params["weights_out"]
    data_yaml = REPO_ROOT / params["data_yaml"]
    eval_cfg = params["eval"]

    if not weights.exists():
        sys.exit(f"[ERROR] Weights chưa tồn tại: {weights}. Chạy `dvc repro train_detector` trước.")

    model = YOLO(str(weights))
    results = model.val(
        data=str(data_yaml),
        imgsz=eval_cfg["imgsz"],
        conf=eval_cfg["conf_threshold"],
        iou=eval_cfg["iou_threshold"],
        split=eval_cfg["split"],
        verbose=False,
    )

    metrics = {
        "mAP50": float(results.box.map50),
        "mAP50_95": float(results.box.map),
        "precision": float(results.box.mp),
        "recall": float(results.box.mr),
        "num_images": int(results.box.nc) if hasattr(results.box, "nc") else None,
        "conf_threshold": eval_cfg["conf_threshold"],
        "iou_threshold": eval_cfg["iou_threshold"],
    }

    METRICS_FILE.parent.mkdir(parents=True, exist_ok=True)
    METRICS_FILE.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(f"[OK] Metrics → {METRICS_FILE}")
    print(json.dumps(metrics, indent=2))
    return metrics


if __name__ == "__main__":
    evaluate()
