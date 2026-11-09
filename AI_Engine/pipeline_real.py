from pathlib import Path
from typing import Union, Optional
import numpy as np

# ── Preprocess / First (chạy trước YOLO) ─────────────────────────────────────
from AI_Engine.preprocess.First.decoder  import ImageDecoder
from AI_Engine.preprocess.First.quality  import ImageQuality

# ── Models ────────────────────────────────────────────────────────────────────
from AI_Engine.modelLPdetector.src.modelYOLO import YOLODetector
from AI_Engine.modelOCR.src.modelOCR         import PaddleOCRReader

# ── Preprocess / Last (chạy sau YOLO, trước OCR) ─────────────────────────────
from AI_Engine.preprocess.Last.plate_crop     import PlateCropper
from AI_Engine.preprocess.Last.plate_deskew   import PlateDeskewer
from AI_Engine.preprocess.Last.plate_enhancer import PlateEnhancer

# ── Schemas ───────────────────────────────────────────────────────────────────
from AI_Engine.schemas import DetectionResult, OCRResult, PlateResult, PipelineResult


class LicensePlatePipeline:
    """
    Pipeline hoàn chỉnh: Ảnh đầu vào → Danh sách biển số đọc được.

    Luồng xử lý:
        Input (path / base64 / bytes / numpy)
            ↓ ImageDecoder
        Raw image (numpy BGR)
            ↓ ImageQuality.assess()
        Kiểm tra chất lượng ảnh
            ↓ YOLODetector.predict()
        Danh sách bbox biển số
            ↓ PlateCropper.crop()
        Ảnh crop từng biển số
            ↓ PlateEnhancer.enhance()
        Ảnh đã tăng cường (sáng / sắc nét)
            ↓ PlateDeskewer.deskew()
        Ảnh đã nắn thẳng
            ↓ PaddleOCRReader.predict()
        Chuỗi ký tự biển số
            ↓
        PipelineResult
    """

    def __init__(
        self,
        detector_path : str,
        ocr_model_path: str,
        ocr_dict_path : str,
        det_conf      : float = 0.5,
        ocr_score     : float = 0.7,
        use_gpu       : bool  = True,
    ):
        """
        Khởi tạo toàn bộ pipeline — load model 1 lần duy nhất.

        Args:
            detector_path : Đường dẫn tới best_detector.pt (YOLO).
            ocr_model_path: Đường dẫn tới thư mục inference model PaddleOCR.
            ocr_dict_path : Đường dẫn tới latin_dict.txt.
            det_conf      : Ngưỡng tin cậy YOLO (default 0.5).
            ocr_score     : Ngưỡng tin cậy OCR  (default 0.7).
            use_gpu       : True nếu có GPU.
        """
        print("[INFO] Khởi tạo pipeline...")

        # ── Preprocess helpers (không cần load weights, khởi tạo nhanh) ───────
        self.decoder  = ImageDecoder()
        self.quality  = ImageQuality()
        self.cropper  = PlateCropper(padding_ratio=0.05)
        self.enhancer = PlateEnhancer()
        self.deskewer = PlateDeskewer(target_width=470, target_height=110)

        # ── Models (load weights — chỉ chạy 1 lần) ───────────────────────────
        self.detector = YOLODetector(
            model_path=detector_path,
            conf_threshold=det_conf,
        )
        self.reader = PaddleOCRReader(
            model_path=ocr_model_path,
            dict_path=ocr_dict_path,
            score_threshold=ocr_score,
            use_gpu=use_gpu,
        )

        print("[INFO] Pipeline sẵn sàng.")

    # ─────────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────────

    def run(
        self,
        input_data: Union[str, bytes, np.ndarray],
        image_path: Optional[str] = None,
    ) -> PipelineResult:
        """
        Chạy toàn bộ pipeline trên một ảnh đầu vào.

        Args:
            input_data: Có thể là:
                        - str       → đường dẫn file ảnh hoặc chuỗi base64
                        - bytes     → raw image bytes
                        - np.ndarray→ ảnh BGR đã đọc sẵn (bỏ qua bước decode)
            image_path: Tuỳ chọn — đường dẫn gốc để lưu vào PipelineResult.

        Returns:
            PipelineResult chứa toàn bộ biển số tìm được.
        """
        # BƯỚC 1 — Decode ảnh đầu vào
        image = self._decode(input_data)
        if image is None:
            print("[WARNING] Không decode được ảnh đầu vào.")
            return PipelineResult(plates=[], image_path=image_path)

        # BƯỚC 2 — Kiểm tra chất lượng ảnh
        quality = self.quality.assess(image)
        if not quality["is_valid"]:
            print(f"[WARNING] Ảnh không đạt chất lượng: {quality['reason']}")
            return PipelineResult(plates=[], image_path=image_path)

        # BƯỚC 3 — YOLO detect vị trí biển số
        detections = self.detector.predict(image)
        if not detections:
            print("[INFO] Không phát hiện biển số nào.")
            return PipelineResult(plates=[], image_path=image_path)

        # BƯỚC 4 — Xử lý từng biển số phát hiện được
        plates = []
        for det in detections:
            plate = self._process_single_plate(image, det)
            if plate is not None:
                plates.append(plate)

        return PipelineResult(plates=plates, image_path=image_path)

    # ─────────────────────────────────────────────────────────────────────────
    # Private helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _decode(self, input_data: Union[str, bytes, np.ndarray]) -> Optional[np.ndarray]:
        """Tự động nhận dạng loại input và decode thành numpy BGR."""
        # Đã là numpy array — dùng luôn, không decode
        if isinstance(input_data, np.ndarray):
            return input_data

        # Bytes → decode trực tiếp từ memory
        if isinstance(input_data, bytes):
            return self.decoder.from_bytes(input_data)

        # String → phân biệt file path và base64
        if isinstance(input_data, str):
            # base64 thường rất dài và chứa ký tự '/' hoặc header 'data:image'
            if input_data.startswith("data:image") or len(input_data) > 260:
                return self.decoder.from_base64(input_data)
            return self.decoder.from_file(input_data)

        print(f"[ERROR] Kiểu input không hỗ trợ: {type(input_data)}")
        return None

    def _process_single_plate(
        self,
        image: np.ndarray,
        det  : dict,
    ) -> Optional[PlateResult]:
        """
        Xử lý một biển số từ bbox YOLO → PlateResult.

        Luồng: crop → enhance → deskew → OCR → PlateResult
        """
        bbox = det["bbox"]          # tuple (x1, y1, x2, y2)
        conf = det["conf"]          # float

        # BƯỚC 4a — Crop vùng biển số
        cropped = self.cropper.crop(image, bbox)
        if cropped is None:
            print(f"[WARNING] Crop thất bại với bbox {bbox}.")
            return None

        # BƯỚC 4b — Tăng cường chất lượng (sáng / sắc nét / khử nhiễu)
        enhanced = self.enhancer.enhance(cropped)
        if enhanced is None:
            enhanced = cropped       # Fallback: dùng ảnh crop gốc nếu enhance lỗi

        # BƯỚC 4c — Nắn thẳng biển số bị nghiêng
        deskewed = self.deskewer.deskew(enhanced)
        if deskewed is None:
            deskewed = enhanced      # Fallback: dùng ảnh enhanced nếu deskew lỗi

        # BƯỚC 4d — OCR đọc ký tự
        ocr_result = self.reader.predict(deskewed)

        return PlateResult(
            plate_text    =ocr_result["text"],
            detection_conf=conf,
            ocr_score     =ocr_result["score"],
            bbox          =bbox,
        )