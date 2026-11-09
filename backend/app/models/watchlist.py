from sqlalchemy import Column, Integer, String, Text, DateTime, Enum, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum

from app.database import Base


class WatchlistCategory(str, enum.Enum):
    BLACKLIST = "BLACKLIST"
    WHITELIST = "WHITELIST"


class Watchlist(Base):
    __tablename__ = "watchlists"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    plate_number = Column(
        String(20),
        ForeignKey("vehicles.plate_number", ondelete="RESTRICT", onupdate="CASCADE"),
        nullable=False,
        index=True,
    )
    category     = Column(Enum(WatchlistCategory), nullable=False, index=True)
    owner_name   = Column(String(100), nullable=True)
    note         = Column(Text, nullable=True)
    created_by   = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at   = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relationship
    vehicle = relationship("Vehicle", back_populates="watchlist_entries")

    def __repr__(self) -> str:
        return f"<Watchlist id={self.id} plate={self.plate_number!r} category={self.category}>"