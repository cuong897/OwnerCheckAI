from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


# ── Schema cho API nhận dạng (POST /recognition/process) ──────────────────

class RecognitionRequest(BaseModel):
    """Gửi ảnh dưới dạng base64 hoặc URL để pipeline xử lý."""
    image_data: str = Field(..., description="Base64 string hoặc đường dẫn file ảnh")
    camera_id: int = Field(..., description="ID camera gửi ảnh lên")


class OwnerInfoSchema(BaseModel):
    """Thông tin chủ xe gắn với biển số nhận diện được."""
    registered: bool = Field(..., description="True nếu plate có trong bảng vehicles")
    owner_name: Optional[str] = None
    vehicle_type: Optional[str] = None
    brand: Optional[str] = None
    color: Optional[str] = None


class WatchlistMatchSchema(BaseModel):
    """Plate khớp với entry trong bảng watchlists."""
    category: str = Field(..., description="BLACKLIST | WHITELIST")
    note: Optional[str] = None


class PlateResultSchema(BaseModel):
    box: List[int] = Field(..., description="Toạ độ bounding box [x1, y1, x2, y2]")
    text: str = Field(..., description="Chuỗi biển số sau OCR")
    conf_detect: float = Field(..., ge=0.0, le=1.0, description="Confidence score của YOLO")
    owner: Optional[OwnerInfoSchema] = Field(None, description="Thông tin chủ xe (nếu đăng ký)")
    watchlist: Optional[WatchlistMatchSchema] = Field(None, description="Trùng khớp watchlist (nếu có)")
    alert: bool = Field(False, description="True khi plate có trong BLACKLIST")


class AlertEventSchema(BaseModel):
    """Payload SSE cho channel alerts:blacklist."""
    type: str = Field("blacklist_match", description="Loại alert")
    plate_text: str
    camera_id: int
    log_id: int
    timestamp: str
    owner_name: Optional[str] = None
    vehicle_type: Optional[str] = None
    note: Optional[str] = None
    image_url: Optional[str] = None


class RecognitionResponse(BaseModel):
    success: bool
    message: str
    plates: List[PlateResultSchema]
    process_time: float = Field(..., description="Thời gian xử lý (giây)")


class JobAcceptedResponse(BaseModel):
    """Trả về ngay khi POST /recognition/process — job đã enqueue, chưa xử lý."""
    job_id: str
    status: str = Field("pending", description="pending | processing | done | failed")


class JobStatusResponse(BaseModel):
    """Trả về khi poll GET /recognition/jobs/{job_id}."""
    job_id: str
    status: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    plates: Optional[List[PlateResultSchema]] = None
    log_ids: Optional[List[int]] = None
    process_time: Optional[float] = None
    error: Optional[str] = None


# ── Schema cho bảng recognition_logs ──────────────────────────────────────

class RecognitionLogBase(BaseModel):
    camera_id: Optional[int] = None  # NULL nếu camera đã bị xoá (FK SET NULL)
    plate_text: str = Field(..., max_length=20)
    ocr_confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    image_url: Optional[str] = Field(None, max_length=500)
    status: Optional[str] = Field("SUCCESS", pattern="^(SUCCESS|FAILED|PENDING)$")


class RecognitionLogCreate(RecognitionLogBase):
    camera_id: int  # bắt buộc khi tạo log mới (camera phải tồn tại)


class RecognitionLogVerify(BaseModel):
    """Dùng cho endpoint xác minh thủ công biển số."""
    verified_plate_text: str = Field(..., max_length=20)
    verified_by: int = Field(..., description="ID người dùng xác minh")


class RecognitionLogResponse(RecognitionLogBase):
    id: int
    timestamp: datetime
    is_manual_verified: bool
    verified_plate_text: Optional[str]
    verified_by: Optional[int]
    retry_count: int

    model_config = {"from_attributes": True}