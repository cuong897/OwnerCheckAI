from sqlalchemy import Column, Integer, String, Boolean, DateTime, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum

from app.database import Base


class UserRole(str, enum.Enum):
    USER = "USER"
    ADMIN = "ADMIN"


class User(Base):
    __tablename__ = "users"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    username        = Column(String(64), nullable=False, unique=True, index=True)
    hashed_password = Column(String(255), nullable=False)
    role            = Column(Enum(UserRole), nullable=False, default=UserRole.USER)
    is_active       = Column(Boolean, nullable=False, default=True)
    created_at      = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relationship
    verified_logs = relationship("RecognitionLog", back_populates="verifier", foreign_keys="RecognitionLog.verified_by")

    def __repr__(self) -> str:
        return f"<User id={self.id} username={self.username!r} role={self.role}>"