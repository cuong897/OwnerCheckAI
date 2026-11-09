"""
Đánh giá PaddleOCR recognition trên tập valid của AI_Engine/modelOCR/datasets,
xuất metrics JSON cho DVC.

Đo accuracy theo 3 cấp:
  - exact:  text dự đoán khớp 100% với label (đã upper/strip)
  - alnum:  khớp sau khi loại bỏ ký tự không alphanumeric (xóa '-', '.', space)
  - char:   trung bình character-level (1 - normalized Levenshtein)
"""
import json
import sys
from pathlib import Path

import cv2
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
PARAMS_FILE = REPO_ROOT / "params.yaml"
METRICS_FILE = REPO_ROOT / "metrics" / "ocr.json"

sys.path.insert(0, str(REPO_ROOT))
from AI_Engine.modelOCR.src.modelOCR import PaddleOCRReader  # noqa: E402


def _levenshtein(a: str, b: str) -> int:
    if len(a) < len(b):
        a, b = b, a
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(cur[-1] + 1, prev[j] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _normalize(text: str) -> str:
    return "".join(ch for ch in text.upper() if ch.isalnum())


def evaluate() -> dict:
    params = yaml.safe_load(PARAMS_FILE.read_text(encoding="utf-8"))["ocr"]
    inference_dir = REPO_ROOT / params["inference_dir"]
    dict_path = REPO_ROOT / params["dict_path"]
    score_threshold = params["eval"]["score_threshold"]

    valid_root = REPO_ROOT / "AI_Engine" / "modelOCR" / "datasets" / "valid"
    labels_file = valid_root / "labels.txt"
    images_root = valid_root / "images"

    if not labels_file.exists():
        sys.exit(f"[ERROR] labels.txt không tồn tại: {labels_file}")
    if not inference_dir.exists():
        sys.exit(f"[ERROR] OCR inference dir không tồn tại: {inference_dir}. Chạy `dvc pull`.")

    reader = PaddleOCRReader(
        model_path=str(inference_dir),
        dict_path=str(dict_path),
        score_threshold=score_threshold,
        use_gpu=params["inference"]["use_gpu"],
    )

    total = 0
    exact_hits = 0
    alnum_hits = 0
    char_acc_sum = 0.0

    for line in labels_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rel_path, label = line.split("\t", 1)
        img_path = images_root.parent / rel_path if "/" in rel_path else images_root / rel_path
        if not img_path.exists():
            continue
        img = cv2.imread(str(img_path))
        if img is None:
            continue

        pred = reader.predict(img).get("text", "")
        gt = label.strip()

        total += 1
        if pred.upper() == gt.upper():
            exact_hits += 1
        if _normalize(pred) == _normalize(gt):
            alnum_hits += 1
        max_len = max(len(pred), len(gt), 1)
        char_acc_sum += 1.0 - _levenshtein(pred.upper(), gt.upper()) / max_len

    if total == 0:
        sys.exit("[ERROR] Không có ảnh nào để eval. Kiểm tra dataset/valid.")

    metrics = {
        "total": total,
        "exact_match": exact_hits / total,
        "alnum_match": alnum_hits / total,
        "char_accuracy": char_acc_sum / total,
        "score_threshold": score_threshold,
    }

    METRICS_FILE.parent.mkdir(parents=True, exist_ok=True)
    METRICS_FILE.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(f"[OK] Metrics → {METRICS_FILE}")
    print(json.dumps(metrics, indent=2))
    return metrics


if __name__ == "__main__":
    evaluate()
