import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
PARAMS_FILE = REPO_ROOT / "params.yaml"


def _load_params() -> dict:
    with open(PARAMS_FILE, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)["ocr"]


def train_model() -> Path:
    params = _load_params()

    config_path = REPO_ROOT / params["config"]
    paddleocr_dir = REPO_ROOT / params["paddleocr_dir"]
    pretrained = REPO_ROOT / (params["pretrained"] + ".pdparams")
    finetuned_dir = REPO_ROOT / params["finetuned_dir"]
    train_cfg = params["train"]

    for name, path in [
        ("config", config_path),
        ("pretrained weights", pretrained),
        ("PaddleOCR repo", paddleocr_dir),
    ]:
        if not path.exists():
            sys.exit(f"[ERROR] {name} không tồn tại: {path}")

    finetuned_dir.mkdir(parents=True, exist_ok=True)
    train_script = paddleocr_dir / "tools" / "train.py"
    if not train_script.exists():
        sys.exit(
            f"[ERROR] Không thấy PaddleOCR train script: {train_script}\n"
            "  → git clone https://github.com/PaddlePaddle/PaddleOCR.git "
            f"{paddleocr_dir}"
        )

    # Override hyperparams qua flag -o của PaddleOCR (không cần sửa file YAML).
    overrides = [
        "-o",
        f"Global.epoch_num={train_cfg['epoch_num']}",
        f"Global.pretrained_model={pretrained.with_suffix('')}",
        f"Global.save_model_dir={finetuned_dir}",
        f"Train.loader.batch_size_per_card={train_cfg['batch_size']}",
        f"Optimizer.lr.learning_rate={train_cfg['learning_rate']}",
        f"Optimizer.lr.warmup_epoch={train_cfg['warmup_epoch']}",
        f"Global.max_text_length={train_cfg['max_text_length']}",
    ]

    cmd = [sys.executable, str(train_script), "-c", str(config_path), *overrides]
    print(f"[INFO] {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(paddleocr_dir), check=False)
    if result.returncode != 0:
        sys.exit(result.returncode)

    best = finetuned_dir / "best_accuracy.pdparams"
    if best.exists():
        print(f"[OK] Best model → {best}")
    else:
        print(f"[WARNING] Không tìm thấy best_accuracy.pdparams sau training tại {finetuned_dir}")
    return finetuned_dir


if __name__ == "__main__":
    train_model()
