from dataclasses import dataclass, field
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
# STAGE 1 — Kết quả từ YOLODetector
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class DetectionResult:
    """
    Một biển số được YOLO phát hiện trong ảnh gốc.

    Attributes:
        bbox  : Tọa độ vùng biển số (x1, y1, x2, y2) — pixel, int thuần Python.
        conf  : Độ tin cậy của YOLO (0.0 → 1.0).
        class_id: Class ID (thường = 0 vì chỉ có 1 class 'license_plate').
    """
    bbox    : tuple[int, int, int, int]
    conf    : float
    class_id: int = 0


# ─────────────────────────────────────────────────────────────────────────────
# STAGE 2 — Kết quả từ PaddleOCRReader
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class OCRResult:
    """
    Kết quả đọc ký tự từ ảnh crop biển số.

    Attributes:
        text : Chuỗi ký tự đọc được (vd: "29A-123.45"). "" nếu không đọc được.
        score: Độ tin cậy của OCR (0.0 → 1.0).
    """
    text : str
    score: float


# ─────────────────────────────────────────────────────────────────────────────
# STAGE 3 — Kết quả tổng hợp từ toàn bộ pipeline
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PlateResult:
    """
    Kết quả hoàn chỉnh cho một biển số — đầu ra cuối cùng của pipeline.

    Attributes:
        plate_text    : Chuỗi biển số đọc được (vd: "29A-123.45").
        detection_conf: Độ tin cậy của bước YOLO detect.
        ocr_score     : Độ tin cậy của bước OCR đọc ký tự.
        bbox          : Tọa độ biển số trong ảnh gốc (x1, y1, x2, y2).
        is_valid      : True nếu cả detection_conf và ocr_score đều vượt ngưỡng.
    """
    plate_text    : str
    detection_conf: float
    ocr_score     : float
    bbox          : tuple[int, int, int, int]
    is_valid      : bool = field(init=False)

    # Ngưỡng mặc định — có thể chỉnh tuỳ yêu cầu hệ thống
    DETECTION_THRESHOLD: float = field(default=0.5, init=False, repr=False)
    OCR_THRESHOLD      : float = field(default=0.7, init=False, repr=False)

    def __post_init__(self):
        # Tự tính is_valid ngay sau khi khởi tạo
        self.is_valid = (
            bool(self.plate_text)
            and self.detection_conf >= self.DETECTION_THRESHOLD
            and self.ocr_score      >= self.OCR_THRESHOLD
        )

    def to_dict(self) -> dict:
        """
        Chuyển sang dict — dùng khi cần trả về JSON cho API hoặc log.
        """
        return {
            "plate_text"    : self.plate_text,
            "detection_conf": round(self.detection_conf, 4),
            "ocr_score"     : round(self.ocr_score, 4),
            "bbox"          : self.bbox,
            "is_valid"      : self.is_valid,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Kết quả tổng của toàn bộ ảnh đầu vào (có thể có nhiều biển số)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PipelineResult:
    """
    Tổng hợp tất cả biển số tìm thấy trong một ảnh đầu vào.

    Attributes:
        plates   : Danh sách PlateResult cho từng biển số.
        image_path: Đường dẫn ảnh gốc (tuỳ chọn, dùng cho logging).
    """
    plates    : list[PlateResult] = field(default_factory=list)
    image_path: Optional[str]     = None

    @property
    def valid_plates(self) -> list[PlateResult]:
        """Chỉ trả về các biển số vượt ngưỡng tin cậy."""
        return [p for p in self.plates if p.is_valid]

    @property
    def best_plate(self) -> Optional[PlateResult]:
        """
        Trả về biển số có ocr_score cao nhất trong danh sách hợp lệ.
        Trả về None nếu không có biển số nào hợp lệ.
        """
        if not self.valid_plates:
            return None
        return max(self.valid_plates, key=lambda p: p.ocr_score)

    def to_dict(self) -> dict:
        """Chuyển sang dict cho JSON / logging."""
        return {
            "image_path"  : self.image_path,
            "total_found" : len(self.plates),
            "total_valid" : len(self.valid_plates),
            "plates"      : [p.to_dict() for p in self.plates],
        }