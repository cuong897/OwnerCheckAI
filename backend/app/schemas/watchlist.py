from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class WatchlistBase(BaseModel):
    plate_number: str = Field(..., max_length=20, examples=["51F-123.45"])
    category: str = Field(..., pattern="^(BLACKLIST|WHITELIST)$", examples=["BLACKLIST"])
    owner_name: Optional[str] = Field(None, max_length=100)
    note: Optional[str] = None


class WatchlistCreate(WatchlistBase):
    pass


class WatchlistUpdate(BaseModel):
    category: Optional[str] = Field(None, pattern="^(BLACKLIST|WHITELIST)$")
    owner_name: Optional[str] = Field(None, max_length=100)
    note: Optional[str] = None


class WatchlistResponse(WatchlistBase):
    id: int
    created_at: datetime

    model_config = {"from_attributes": True}