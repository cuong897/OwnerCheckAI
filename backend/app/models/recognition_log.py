from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Enum, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum

from app.database import Base


class LogStatus(str, enum.Enum):
    SUCCESS = "SUCCESS"
    FAILED  = "FAILED"
    PENDING = "PENDING"


class RecognitionLog(Base):
    __tablename__ = "recognition_logs"

    id                  = Column(Integer, primary_key=True, autoincrement=True)
    camera_id           = Column(Integer, ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True, index=True)
    plate_text          = Column(String(20), nullable=False, index=True)
    ocr_confidence      = Column(Float, nullable=True)
    image_url           = Column(String(512), nullable=True)
    # plate_embedding đã chuyển sang Qdrant — xem backend/app/qdrant.py
    is_manual_verified  = Column(Boolean, nullable=False, default=False)
    verified_plate_text = Column(String(20), nullable=True)
    verified_by         = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    status              = Column(Enum(LogStatus), nullable=False, default=LogStatus.PENDING, index=True)
    retry_count         = Column(Integer, nullable=False, default=0)
    timestamp           = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)

    # Relationships
    camera   = relationship("Camera", back_populates="logs")
    verifier = relationship("User", back_populates="verified_logs", foreign_keys=[verified_by])

    def __repr__(self) -> str:
        return f"<RecognitionLog id={self.id} plate={self.plate_text!r} status={self.status}>"