from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class VehicleBase(BaseModel):
    plate_number: str = Field(..., max_length=20, examples=["51F-123.45"])
    owner_name: Optional[str] = Field(None, max_length=100)
    vehicle_type: Optional[str] = Field(None, max_length=50, examples=["Ô tô con", "Xe tải"])
    brand: Optional[str] = Field(None, max_length=50, examples=["Toyota", "Honda"])
    color: Optional[str] = Field(None, max_length=20, examples=["Trắng", "Đen"])


class VehicleCreate(VehicleBase):
    pass


class VehicleUpdate(BaseModel):
    owner_name: Optional[str] = Field(None, max_length=100)
    vehicle_type: Optional[str] = Field(None, max_length=50)
    brand: Optional[str] = Field(None, max_length=50)
    color: Optional[str] = Field(None, max_length=20)


class VehicleResponse(VehicleBase):
    created_at: datetime

    model_config = {"from_attributes": True}


class BulkImportSkipped(BaseModel):
    plate_number: str
    reason: str


class BulkImportResponse(BaseModel):
    imported: int = Field(..., description="Số bản ghi insert thành công")
    skipped: list[BulkImportSkipped] = Field(default_factory=list, description="Plate bị bỏ qua + lý do")
    total: int = Field(..., description="Tổng số entry trong request")


# ── Vector similarity search ──────────────────────────────────────────────────

class SimilarSearchRequest(BaseModel):
    image_data: str = Field(
        ...,
        description="Ảnh base64 (không prefix data:image/...). Có thể là ảnh đầy đủ "
                    "(server sẽ detect biển bằng YOLO) hoặc đã crop sẵn.",
    )
    detect: bool = Field(
        True,
        description="True: chạy YOLO detect crops trong ảnh, embed từng crop. "
                    "False: embed ảnh đầu vào trực tiếp như một crop.",
    )
    top_k: int = Field(5, ge=1, le=50)
    score_threshold: Optional[float] = Field(
        None,
        ge=0.0, le=1.0,
        description="Cosine similarity tối thiểu (0..1). None → không lọc.",
    )


class SimilarOwnerInfo(BaseModel):
    registered: bool
    owner_name: Optional[str] = None
    vehicle_type: Optional[str] = None
    brand: Optional[str] = None
    color: Optional[str] = None


class SimilarMatch(BaseModel):
    log_id: int
    score: float = Field(..., description="Cosine similarity (1.0 = identical, 0 = orthogonal)")
    plate_text: Optional[str] = None
    camera_id: Optional[int] = None
    timestamp: Optional[str] = None
    owner: SimilarOwnerInfo


class SimilarDetection(BaseModel):
    box: Optional[list[int]] = Field(None, description="bbox [x1,y1,x2,y2] trong ảnh gốc (None nếu detect=False)")
    conf_detect: Optional[float] = None
    matches: list[SimilarMatch]


class SimilarSearchResponse(BaseModel):
    detections: list[SimilarDetection]
    total_matches: int
    note: Optional[str] = None