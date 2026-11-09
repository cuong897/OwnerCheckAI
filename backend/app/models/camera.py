from sqlalchemy import Column, Integer, String, DateTime, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum

from app.database import Base


class CameraStatus(str, enum.Enum):
    ACTIVE   = "ACTIVE"
    INACTIVE = "INACTIVE"


class Camera(Base):
    __tablename__ = "cameras"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    camera_name = Column(String(128), nullable=False)
    location    = Column(String(255), nullable=True)
    rtsp_url    = Column(String(500), nullable=True)
    status      = Column(Enum(CameraStatus), nullable=False, default=CameraStatus.ACTIVE)
    created_at  = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relationship — passive_deletes: để DB FK (ON DELETE SET NULL) tự xử lý,
    # không load 80k+ logs vào memory khi xoá camera.
    logs = relationship("RecognitionLog", back_populates="camera", passive_deletes=True)

    def __repr__(self) -> str:
        return f"<Camera id={self.id} name={self.camera_name!r} status={self.status}>"