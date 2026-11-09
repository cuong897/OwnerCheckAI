"""
Adapter cho LPR pipeline (bọc pipeline_real.py — LicensePlatePipeline thật).

Backend worker (app/worker/main.py) gọi như sau:
  pipeline = LPRPipeline()              # no-arg init
  response = pipeline.run(image_bytes)  # bytes / base64 / np.ndarray
  for plate in response.plates:
      plate.text          # str
      plate.box           # list[int]
      plate.conf_detect   # float
      plate.crop_bytes    # bytes | None  (JPEG cho UI hiển thị ảnh biển)
      plate.embedding     # list[float] | None

Adapter giải quyết 3 mismatch giữa pipeline V2 thật và interface backend:

  1. Constructor mismatch
     V2 cần (detector_path, ocr_model_path, ocr_dict_path, det_conf, ocr_score,
     use_gpu). Backend gọi LPRPipeline() no-arg. Adapter inject paths + flags từ
     env, fallback default tới file weight trong AI_Engine/.

  2. Quality check quá strict cho RTSP
     ImageQuality.assess() reject frame có blur < 100 → loại bỏ phần lớn frame
     RTSP nén lossy. Adapter monkey-patch luôn trả is_valid=True khi
     AI_SKIP_QUALITY=1.

  3. PaddleOCR det=False chỉ đọc 1 dòng
     V2 config det=False → đọc biển ôtô 1 dòng OK, nhưng biển xe máy 2 dòng
     (49-E1 / 222.22) chỉ đọc được dòng dưới. Adapter monkey-patch
     reader.predict gọi PaddleOCR với det=True + concat dòng top→bottom.

  4. PlateDeskewer ép aspect 4.3:1 cho biển vuông xe máy
     V2 deskewer init target_width=470, target_height=110 → biển vuông sau
     deskew bị méo + crop mất text. Adapter override run flow: OCR trực tiếp
     trên raw crop (PaddleOCR det=True tự segment text, không cần deskew).

Output:
  • LPRResponse.plates[i].text  : full string từ PaddleOCR (đa dòng concat)
  • crop_bytes                  : JPEG encode bbox để bật MinIO upload + UI
  • embedding                   : None (V2 chưa hỗ trợ embedding)

Env vars (đặt trong .env):
  AI_DETECTOR_PATH    default: AI_Engine/modelLPdetector/models/best_detector.pt
  AI_OCR_MODEL_DIR    default: AI_Engine/modelOCR/models/pretrained/rec_model/inference
  AI_OCR_DICT         default: AI_Engine/modelOCR/models/latin_dict.txt
  AI_DET_CONF         default: 0.5  (hạ xuống cho biển nhỏ/mờ)
  AI_OCR_SCORE        default: 0.5
  AI_USE_GPU          default: 0  (1 nếu có GPU NVIDIA + paddlepaddle-gpu)
  AI_SKIP_QUALITY     default: 1  (bypass blur check cho RTSP)
"""

import logging
import os
from dataclasses import dataclass, field
from typing import List, Optional, Union

import cv2
import numpy as np

from .embedder import embed_crop

logger = logging.getLogger(__name__)


# ── Default paths (relative to AI_Engine/ trong container WORKDIR /app) ─────
_AI_ROOT = os.path.dirname(os.path.abspath(__file__))

_DETECTOR_PATH = os.getenv(
    "AI_DETECTOR_PATH",
    os.path.join(_AI_ROOT, "modelLPdetector/models/best_detector.pt"),
)
_OCR_MODEL_DIR = os.getenv(
    "AI_OCR_MODEL_DIR",
    os.path.join(_AI_ROOT, "modelOCR/models/pretrained/rec_model/inference"),
)
_OCR_DICT = os.getenv(
    "AI_OCR_DICT",
    os.path.join(_AI_ROOT, "modelOCR/models/latin_dict.txt"),
)
_DET_CONF = float(os.getenv("AI_DET_CONF", "0.5"))
_OCR_SCORE = float(os.getenv("AI_OCR_SCORE", "0.5"))
_USE_GPU = os.getenv("AI_USE_GPU", "0") == "1"
_SKIP_QUALITY = os.getenv("AI_SKIP_QUALITY", "1") == "1"


@dataclass
class PlateResult:
    box: List[int] = field(default_factory=lambda: [0, 0, 0, 0])
    text: str = ""
    conf_detect: float = 0.0
    crop_bytes: Optional[bytes] = None
    embedding: Optional[List[float]] = None


@dataclass
class LPRResponse:
    plates: List[PlateResult] = field(default_factory=list)


class LPRPipeline:
    """
    No-arg wrapper around AI_Engine.pipeline_real.LicensePlatePipeline.

    Exposes:
      • self.mode         — "full" | "detect_only" | "dead"
      • self.init_error   — chuỗi mô tả lỗi init nếu mode != "full"
      • self.weight_paths — dict các đường dẫn weight đang dùng
    """

    def __init__(self, *args, **kwargs) -> None:
        logger.info(
            "LPRPipeline init — use_gpu=%s det_conf=%s ocr_score=%s",
            _USE_GPU, _DET_CONF, _OCR_SCORE,
        )
        self._real = None
        self._detector_only = None
        self.mode: str = "dead"
        self.init_error: Optional[str] = None
        self.weight_paths = {
            "detector": _DETECTOR_PATH,
            "ocr_model_dir": _OCR_MODEL_DIR,
            "ocr_dict": _OCR_DICT,
        }

        try:
            from .pipeline_real import LicensePlatePipeline
            self._real = LicensePlatePipeline(
                detector_path=_DETECTOR_PATH,
                ocr_model_path=_OCR_MODEL_DIR,
                ocr_dict_path=_OCR_DICT,
                det_conf=_DET_CONF,
                ocr_score=_OCR_SCORE,
                use_gpu=_USE_GPU,
            )
            if _SKIP_QUALITY:
                self._real.quality.assess = lambda img: {"is_valid": True, "reason": "skipped"}
                logger.info("LPRPipeline quality check SKIPPED (AI_SKIP_QUALITY=1)")
            self._patch_ocr_multiline()
            self.mode = "full"
            logger.info("LPRPipeline ready — mode=full")
        except Exception as exc:
            self.init_error = f"full init failed: {exc!r}"
            logger.warning(
                "LPRPipeline full init failed (%r). Fallback sang detection-only — "
                "OCR sẽ KHÔNG hoạt động, log sẽ được tạo với plate_text rỗng để admin verify thủ công.",
                exc,
            )
            self._real = None
            try:
                from .modelLPdetector.src.modelYOLO import YOLODetector
                from .preprocess.First.decoder import ImageDecoder
                from .preprocess.Last.plate_crop import PlateCropper
                self._detector_only = {
                    "detector": YOLODetector(model_path=_DETECTOR_PATH, conf_threshold=_DET_CONF),
                    "decoder": ImageDecoder(),
                    "cropper": PlateCropper(padding_ratio=0.05),
                }
                self.mode = "detect_only"
                logger.warning("LPRPipeline ready — mode=detect_only (NO OCR)")
            except Exception as exc2:
                self.init_error = f"full+detect-only init failed: {exc!r} / {exc2!r}"
                logger.error(
                    "LPRPipeline FATAL: detector cũng fail (%r). Pipeline DEAD — "
                    "tất cả job sẽ trả về plates=[] và mark FAILED.",
                    exc2,
                )

    def run(self, image_data: Union[bytes, str, np.ndarray]) -> LPRResponse:
        if self.mode == "full":
            return self._run_full(image_data)
        if self.mode == "detect_only":
            return self._run_detect_only(image_data)
        return LPRResponse(plates=[])

    # ── Full pipeline path ──────────────────────────────────────────────────
    def _run_full(self, image_data) -> LPRResponse:
        """
        Override flow gốc (crop→enhance→deskew→ocr) — deskewer ép aspect 4.3:1
        làm hỏng biển vuông xe máy. Detect → crop raw → OCR thẳng. PaddleOCR
        det=True tự segment đa dòng nên không cần deskew.
        """
        img = self._decode_for_crop(image_data)
        if img is None:
            return LPRResponse(plates=[])

        try:
            detections = self._real.detector.predict(img)
        except Exception as exc:
            logger.error("LPRPipeline detect error: %r", exc)
            return LPRResponse(plates=[])

        plates: List[PlateResult] = []
        for det in detections:
            bbox = det.get("bbox")
            if bbox is None:
                continue
            box = [int(v) for v in bbox]

            crop = self._real.cropper.crop(img, bbox)
            if crop is None:
                continue

            try:
                ocr_out = self._real.reader.predict(crop)
                text = str(ocr_out.get("text", "") or "")
            except Exception as exc:
                logger.error("LPRPipeline ocr error: %r", exc)
                text = ""

            plates.append(
                PlateResult(
                    box=box,
                    text=text,
                    conf_detect=float(det.get("conf", 0.0)),
                    crop_bytes=_crop_jpeg(img, box),
                    embedding=embed_crop(crop),
                )
            )
        return LPRResponse(plates=plates)

    # ── Detection-only fallback (no OCR weights) ────────────────────────────
    def _run_detect_only(self, image_data) -> LPRResponse:
        """
        OCR không khả dụng — chỉ detect được vị trí biển. Trả về PlateResult
        với text="" để worker bypass enrich, tạo PENDING log cho admin verify
        thủ công thay vì gán text giả (trước đây là "???").
        """
        d = self._detector_only
        img = self._decode_for_crop(image_data)
        if img is None:
            return LPRResponse(plates=[])
        try:
            detections = d["detector"].predict(img)
        except Exception as exc:
            logger.error("LPRPipeline detect error: %r", exc)
            return LPRResponse(plates=[])

        plates: List[PlateResult] = []
        for det in detections:
            bbox = det.get("bbox")
            if bbox is None:
                continue
            box = [int(v) for v in bbox]
            crop = d["cropper"].crop(img, bbox)
            plates.append(
                PlateResult(
                    box=box,
                    text="",
                    conf_detect=float(det.get("conf", 0.0)),
                    crop_bytes=_crop_jpeg(img, box),
                    embedding=embed_crop(crop) if crop is not None else None,
                )
            )
        return LPRResponse(plates=plates)

    def _patch_ocr_multiline(self) -> None:
        """
        Override PaddleOCRReader.predict gọi PaddleOCR với det=True (text
        detection bật) → đọc được biển nhiều dòng. Sắp các dòng theo y rồi
        concat top→bottom giữ thứ tự đọc của con người.
        """
        reader = self._real.reader
        score_threshold = reader.score_threshold

        def predict_multiline(image, score=None):
            if image is None:
                return {"text": "", "score": 0.0}
            thr = score if score is not None else score_threshold
            raw = reader.model.ocr(image, det=True, cls=False)
            if not raw or not raw[0]:
                return {"text": "", "score": 0.0}

            items = []
            for entry in raw[0]:
                box, (text, conf) = entry
                if float(conf) < thr:
                    continue
                y_mean = sum(pt[1] for pt in box) / len(box)
                items.append((y_mean, text.strip().upper(), float(conf)))

            if not items:
                return {"text": "", "score": 0.0}

            items.sort(key=lambda t: t[0])  # top → bottom
            combined = " ".join(t for _, t, _ in items)
            avg_score = sum(c for _, _, c in items) / len(items)
            return {"text": combined, "score": avg_score}

        reader.predict = predict_multiline
        logger.info("LPRPipeline OCR patched: det=True multi-line mode")

    @staticmethod
    def _decode_for_crop(data) -> Optional[np.ndarray]:
        """Decode chỉ cho mục đích crop. Cheap so với pipeline AI."""
        if isinstance(data, np.ndarray):
            return data
        if isinstance(data, (bytes, bytearray)):
            arr = np.frombuffer(bytes(data), dtype=np.uint8)
            return cv2.imdecode(arr, cv2.IMREAD_COLOR)
        return None


def _crop_jpeg(image: np.ndarray, box: List[int], quality: int = 85) -> Optional[bytes]:
    try:
        h, w = image.shape[:2]
        x1, y1, x2, y2 = box
        x1, x2 = max(0, min(x1, x2)), min(w, max(x1, x2))
        y1, y2 = max(0, min(y1, y2)), min(h, max(y1, y2))
        if x2 - x1 < 2 or y2 - y1 < 2:
            return None
        crop = image[y1:y2, x1:x2]
        ok, buf = cv2.imencode(".jpg", crop, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
        return buf.tobytes() if ok else None
    except Exception:
        return None
