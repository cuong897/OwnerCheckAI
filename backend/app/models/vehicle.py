from sqlalchemy import Column, String, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class Vehicle(Base):
    __tablename__ = "vehicles"

    plate_number = Column(String(20), primary_key=True)
    owner_name   = Column(String(128), nullable=True)
    vehicle_type = Column(String(64), nullable=True)
    brand        = Column(String(64), nullable=True)
    color        = Column(String(32), nullable=True)
    created_at   = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at   = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    # Relationship
    watchlist_entries = relationship("Watchlist", back_populates="vehicle")

    def __repr__(self) -> str:
        return f"<Vehicle plate={self.plate_number!r} owner={self.owner_name!r}>"