from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class CameraBase(BaseModel):
    camera_name: str = Field(..., max_length=100, examples=["Camera Cổng A"])
    location: Optional[str] = Field(None, max_length=255, examples=["Tầng 1 - Toà nhà B"])
    rtsp_url: Optional[str] = Field(
        None,
        max_length=500,
        examples=["rtsp://user:pass@192.168.1.10:554/Streaming/Channels/101"],
    )
    status: Optional[str] = Field("ACTIVE", pattern="^(ACTIVE|INACTIVE)$")


class CameraCreate(CameraBase):
    pass


class CameraUpdate(BaseModel):
    camera_name: Optional[str] = Field(None, max_length=100)
    location: Optional[str] = Field(None, max_length=255)
    rtsp_url: Optional[str] = Field(None, max_length=500)
    status: Optional[str] = Field(None, pattern="^(ACTIVE|INACTIVE)$")


class CameraResponse(CameraBase):
    id: int
    created_at: datetime

    model_config = {"from_attributes": True}