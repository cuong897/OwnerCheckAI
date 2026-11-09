import shutil
import sys
from pathlib import Path

import yaml
from ultralytics import YOLO

REPO_ROOT = Path(__file__).resolve().parents[3]
PARAMS_FILE = REPO_ROOT / "params.yaml"


def _load_params() -> dict:
    with open(PARAMS_FILE, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)["detector"]


def train_model() -> Path:
    params = _load_params()

    data_yaml = REPO_ROOT / params["data_yaml"]
    pretrained = REPO_ROOT / params["pretrained"]
    output_dir = REPO_ROOT / params["output_dir"]
    weights_out = REPO_ROOT / params["weights_out"]
    run_name = params["run_name"]
    train_cfg = params["train"]

    if not pretrained.exists():
        sys.exit(f"[ERROR] Pretrained không tồn tại: {pretrained}. Chạy `dvc pull` trước.")
    if not data_yaml.exists():
        sys.exit(f"[ERROR] dataYOLO.yaml không tồn tại: {data_yaml}")

    model = YOLO(str(pretrained))
    model.train(
        data=str(data_yaml),
        epochs=train_cfg["epochs"],
        imgsz=train_cfg["imgsz"],
        batch=train_cfg["batch"],
        workers=train_cfg["workers"],
        device=train_cfg["device"],
        project=str(output_dir),
        name=run_name,
        exist_ok=train_cfg["exist_ok"],
        seed=train_cfg["seed"],
    )

    best_weight = output_dir / run_name / "weights" / "best.pt"
    if not best_weight.exists():
        sys.exit(f"[ERROR] Không tìm thấy best.pt sau training: {best_weight}")

    weights_out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(best_weight, weights_out)
    print(f"[OK] Best model → {weights_out}")
    return weights_out


if __name__ == "__main__":
    train_model()
