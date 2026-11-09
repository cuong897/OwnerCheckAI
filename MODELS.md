# Model Registry — OwnerCheckAI

Tài liệu này là **single source of truth** cho mọi mô hình đang vận hành trong hệ thống. Mỗi version model phải được ghi nhận ở đây kèm dataset, hyperparams, metrics và git/dvc commit hash.

Quy ước version: `vMAJOR.MINOR`
- `MAJOR` bump khi đổi architecture hoặc thay tập train (lineage thay đổi).
- `MINOR` bump khi retrain trên cùng kiến trúc nhưng có chỉnh hyperparams / thêm data.

---

## 1. Detector — `best_detector.pt` (YOLOv8m fine-tuned)

| Field | Giá trị |
|---|---|
| Task | Object detection — 1 class `license_plate` |
| Architecture | YOLOv8m (Ultralytics) |
| Input | 640×640 RGB |
| Output | bbox + confidence |
| Production conf threshold | 0.5 (`pipeline.det_conf`) |
| Pretrained backbone | `yolov8m.pt` (Ultralytics release, COCO) |
| File | `AI_Engine/modelLPdetector/models/best_detector.pt` |
| DVC pointer | `AI_Engine/modelLPdetector/models/best_detector.pt.dvc` |

### Version history

| Version | Date | Dataset (commit) | Hyperparams | mAP@50 | mAP@50:95 | Notes |
|---|---|---|---|---|---|---|
| v1.0 | 2026-05-15 | Biển VN nội bộ (~3.5k ảnh) | epochs=50, imgsz=640, batch=16 | _xem `metrics/detector.json`_ | _xem `metrics/detector.json`_ | Bản đầu — phục vụ demo cuối kỳ |

### Tái lập

```bash
dvc pull                                    # kéo dataset + pretrained
dvc repro train_detector eval_detector      # train + đo metrics
dvc metrics show                            # xem mAP/precision/recall
git add metrics/detector.json AI_Engine/modelLPdetector/models/best_detector.pt.dvc
git commit -m "chore(model): bump detector to vX.Y"
dvc push                                    # upload weight mới
```

---

## 2. OCR — PaddleOCR PP-OCRv3 Recognition

| Field | Giá trị |
|---|---|
| Task | Text recognition (CTC + SAR MultiHead) |
| Architecture | SVTR_LCNet + MobileNetV1Enhance backbone |
| Input | 48×320 RGB |
| Output | text + confidence |
| Production score threshold | 0.7 (`pipeline.ocr_score`) |
| Pretrained | `best_accuracy.pdparams` từ PP-OCRv3 latin release |
| Inference files | `AI_Engine/modelOCR/models/pretrained/rec_model/inference/*` |
| DVC pointers | `inference.pdmodel.dvc`, `inference.pdiparams.dvc` |

### Version history

| Version | Date | Dataset | Hyperparams | exact_match | alnum_match | char_acc | Notes |
|---|---|---|---|---|---|---|---|
| v0 (pretrained) | upstream | PP-OCRv3 latin | — | _xem `metrics/ocr.json`_ | _xem `metrics/ocr.json`_ | _xem `metrics/ocr.json`_ | Chạy thẳng pretrained, chưa fine-tune |

### Fine-tune trên data biển số VN

```bash
# 1. Clone PaddleOCR repo (chỉ 1 lần)
git clone https://github.com/PaddlePaddle/PaddleOCR.git AI_Engine/modelOCR/PaddleOCR

# 2. Đảm bảo dataset đã có (train/labels.txt + valid/labels.txt + ảnh)
ls AI_Engine/modelOCR/datasets/train/labels.txt

# 3. Sửa hyperparams trong params.yaml (ocr.train.*)
# 4. Chạy pipeline
dvc repro train_ocr eval_ocr
dvc metrics show

# 5. Export inference từ checkpoint mới
cd AI_Engine/modelOCR/PaddleOCR
python tools/export_model.py \
  -c ../configs/rec_config.yml \
  -o Global.pretrained_model=../models/finetuned/rec_model/best_accuracy \
     Global.save_inference_dir=../models/pretrained/rec_model/inference

# 6. Bump DVC pointer
cd ../../..
dvc add AI_Engine/modelOCR/models/pretrained/rec_model/inference/inference.pdmodel \
        AI_Engine/modelOCR/models/pretrained/rec_model/inference/inference.pdiparams
dvc push
git commit -am "chore(model): bump OCR to vX.Y"
```

---

## 3. Embedder — ResNet18 feature extractor

| Field | Giá trị |
|---|---|
| Task | Image embedding cho similarity search (Qdrant) |
| Architecture | ResNet18 (torchvision, fc=Identity) |
| Input | 224×224 RGB |
| Output | 512-d vector, L2-normalized |
| Dataset | _không train lại_ — dùng pretrained ImageNet |
| File | _on-demand load qua `torchvision.models.resnet18(weights="IMAGENET1K_V1")`_ |

Không có file weight riêng — torch sẽ cache vào `~/.cache/torch/hub/checkpoints/`. Không cần DVC tracking; chỉ pin version `torch==2.4.x` + `torchvision==0.19.x` trong `backend/requirements.txt`.

---

## 4. Dataset registry

> Dataset hiện **không** commit vào git (xem `.gitignore` — `images/`, `labels/`). Để tái lập kết quả train, dataset cần được tracked qua DVC trên một thành viên có data gốc:

```bash
dvc add AI_Engine/modelLPdetector/datasets/train \
        AI_Engine/modelLPdetector/datasets/valid \
        AI_Engine/modelOCR/datasets/train \
        AI_Engine/modelOCR/datasets/valid
dvc push
git add **/datasets/*.dvc
git commit -m "chore(data): track LPR + OCR datasets via DVC"
```

| Dataset | Format | Nguồn | Size (ảnh) | Phiên bản hiện tại |
|---|---|---|---|---|
| Detector / train | YOLO txt | tự thu thập + augmentation | ~3000 | _untracked — cần `dvc add`_ |
| Detector / valid | YOLO txt | tự thu thập | ~500 | _untracked_ |
| OCR / train | PaddleOCR txt (`path\tlabel`) | crop từ detector output | ~5000 | _untracked_ |
| OCR / valid | PaddleOCR txt | crop từ detector output | ~500 | _untracked_ |

---

## 5. Pipeline reproducibility — TL;DR

| Câu hỏi | Trả lời |
|---|---|
| Hyperparams ở đâu? | [`params.yaml`](params.yaml) (tập trung 1 chỗ) |
| Pipeline stages? | [`dvc.yaml`](dvc.yaml) — `train_detector → eval_detector`, `train_ocr → eval_ocr` |
| Metrics? | `metrics/detector.json`, `metrics/ocr.json` (track bằng `dvc metrics`) |
| Weight version control? | DVC + MinIO bucket `dvc-store` |
| Data version control? | DVC (cần `dvc add` trên máy có data) |
| Rerun toàn bộ pipeline? | `dvc repro` |
| So sánh model cũ vs mới? | `dvc metrics diff HEAD~1` |
| Quay lại model version cũ? | `git checkout <commit> && dvc checkout` |
