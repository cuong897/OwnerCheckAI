"""
Router: /events
Endpoints:
  GET /events/alerts  — Server-Sent Events stream (admin) cho cảnh báo BLACKLIST realtime.

SSE format:
  event: blacklist_match
  data: {"plate_text": "...", "camera_id": ..., ...}

Frontend ví dụ:
  const es = new EventSource("/events/alerts", { withCredentials: true });
  es.addEventListener("blacklist_match", e => console.log(JSON.parse(e.data)));
"""

import asyncio
import json
import logging
from typing import AsyncIterator

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
import redis.asyncio as redis_asyncio

from app.config import settings
from app.queue import ALERTS_BLACKLIST_CHANNEL, RECOGNITION_EVENTS_CHANNEL
from app.dependencies import require_admin_flex, get_current_user_flex
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/events", tags=["Events"])

HEARTBEAT_INTERVAL_SECONDS = 15  # < nginx default proxy_read_timeout (60s)


async def _alert_stream(request: Request) -> AsyncIterator[str]:
    client = redis_asyncio.Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        db=settings.REDIS_DB,
        decode_responses=True,
    )
    pubsub = client.pubsub()
    await pubsub.subscribe(ALERTS_BLACKLIST_CHANNEL)
    logger.info("SSE client subscribed to %s", ALERTS_BLACKLIST_CHANNEL)

    try:
        # Initial comment để flush headers
        yield ": connected\n\n"

        while True:
            if await request.is_disconnected():
                logger.info("SSE client disconnected")
                break

            try:
                message = await asyncio.wait_for(
                    pubsub.get_message(ignore_subscribe_messages=True),
                    timeout=HEARTBEAT_INTERVAL_SECONDS,
                )
            except asyncio.TimeoutError:
                # Heartbeat — comment line, không trigger event handler client
                yield ": heartbeat\n\n"
                continue

            if message is None:
                continue

            try:
                payload = message["data"]
                # Đảm bảo JSON hợp lệ — nếu lỗi parse, vẫn forward raw
                json.loads(payload)
                event_type = "blacklist_match"
                yield f"event: {event_type}\ndata: {payload}\n\n"
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                logger.warning("Skipping malformed pubsub message: %s", exc)
                continue
    finally:
        try:
            await pubsub.unsubscribe(ALERTS_BLACKLIST_CHANNEL)
            await pubsub.aclose()
            await client.aclose()
        except Exception as exc:
            logger.warning("Error closing SSE pubsub: %s", exc)


@router.get(
    "/alerts",
    summary="SSE stream cảnh báo BLACKLIST realtime [ADMIN]",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def sse_alerts(
    request: Request,
    _: User = Depends(require_admin_flex),
):
    return StreamingResponse(
        _alert_stream(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering cho SSE
            "Connection": "keep-alive",
        },
    )


async def _recognition_stream(
    request: Request,
    camera_id: int | None,
) -> AsyncIterator[str]:
    """Forward mọi recognition event; filter theo camera_id nếu được truyền."""
    client = redis_asyncio.Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        db=settings.REDIS_DB,
        decode_responses=True,
    )
    pubsub = client.pubsub()
    await pubsub.subscribe(RECOGNITION_EVENTS_CHANNEL)
    logger.info("SSE client subscribed to %s (camera_id=%s)", RECOGNITION_EVENTS_CHANNEL, camera_id)

    try:
        yield ": connected\n\n"

        while True:
            if await request.is_disconnected():
                break

            try:
                message = await asyncio.wait_for(
                    pubsub.get_message(ignore_subscribe_messages=True),
                    timeout=HEARTBEAT_INTERVAL_SECONDS,
                )
            except asyncio.TimeoutError:
                yield ": heartbeat\n\n"
                continue

            if message is None:
                continue

            try:
                payload = message["data"]
                parsed = json.loads(payload)
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                logger.warning("Skipping malformed recognition pubsub message: %s", exc)
                continue

            if camera_id is not None and parsed.get("camera_id") != camera_id:
                continue

            yield f"event: recognition\ndata: {payload}\n\n"
    finally:
        try:
            await pubsub.unsubscribe(RECOGNITION_EVENTS_CHANNEL)
            await pubsub.aclose()
            await client.aclose()
        except Exception as exc:
            logger.warning("Error closing SSE pubsub: %s", exc)


@router.get(
    "/recognitions",
    summary="SSE stream kết quả nhận diện realtime (filter theo camera_id)",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def sse_recognitions(
    request: Request,
    camera_id: int | None = Query(None, ge=1, description="Chỉ nhận event của camera này"),
    _: User = Depends(get_current_user_flex),
):
    return StreamingResponse(
        _recognition_stream(request, camera_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
