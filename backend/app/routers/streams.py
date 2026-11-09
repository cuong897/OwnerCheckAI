"""
Router: /streams
  GET /streams/cameras/{camera_id}  — MJPEG live preview của camera.

MJPEG format (multipart/x-mixed-replace):
  --frame
  Content-Type: image/jpeg
  Content-Length: N
  <blank line>
  [JPEG bytes]
  <blank line>
  --frame
  ...

Frontend dùng đơn giản:
  <img src="/streams/cameras/1" />
"""

import asyncio
import logging
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
import redis.asyncio as redis_asyncio

from app.config import settings
from app.database import get_db
from app.models.camera import Camera
from app.dependencies import get_current_user_flex
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/streams", tags=["Streams"])

BOUNDARY = "frame"


def _channel(camera_id: int) -> str:
    return f"camera:stream:{camera_id}"


async def _mjpeg_iter(camera_id: int, request: Request) -> AsyncIterator[bytes]:
    client = redis_asyncio.Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        db=settings.REDIS_DB,
        decode_responses=False,  # frame bytes
    )
    pubsub = client.pubsub()
    await pubsub.subscribe(_channel(camera_id))
    logger.info("MJPEG client subscribed: camera %d", camera_id)

    try:
        while True:
            if await request.is_disconnected():
                logger.info("MJPEG client disconnected: camera %d", camera_id)
                break

            try:
                msg = await asyncio.wait_for(
                    pubsub.get_message(ignore_subscribe_messages=True),
                    timeout=10.0,
                )
            except asyncio.TimeoutError:
                # Không có frame trong 10s — vẫn keep alive, không break
                continue

            if msg is None:
                continue

            jpeg: bytes = msg["data"]
            if not isinstance(jpeg, (bytes, bytearray)):
                continue

            yield (
                b"--" + BOUNDARY.encode() + b"\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n"
                + jpeg
                + b"\r\n"
            )
    finally:
        try:
            await pubsub.unsubscribe(_channel(camera_id))
            await pubsub.aclose()
            await client.aclose()
        except Exception as exc:
            logger.warning("MJPEG cleanup failed for camera %d: %s", camera_id, exc)


@router.get(
    "/cameras/{camera_id}",
    summary="MJPEG live preview của camera",
    response_class=StreamingResponse,
    responses={200: {"content": {"multipart/x-mixed-replace": {}}}},
)
async def camera_stream(
    camera_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user_flex),
):
    cam = db.query(Camera).filter(Camera.id == camera_id).first()
    if not cam:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Camera id={camera_id} không tồn tại.",
        )
    if cam.status != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Camera id={camera_id} đang {cam.status}.",
        )

    return StreamingResponse(
        _mjpeg_iter(camera_id, request),
        media_type=f"multipart/x-mixed-replace; boundary={BOUNDARY}",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
