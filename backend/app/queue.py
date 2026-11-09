"""
Redis Streams queue cho recognition jobs.

Stream:   `recognition:queue`
Group:    `workers`
Job state lưu ở Redis hash `job:{job_id}` với TTL JOB_STATE_TTL_SECONDS.

State schema (JSON-encoded trong field "data"):
  {
    "status":  "pending" | "processing" | "done" | "failed",
    "created_at":  ISO timestamp,
    "updated_at":  ISO timestamp,
    "result":  {...},          # khi status == "done"
    "error":   "...",          # khi status == "failed"
  }
"""

import json
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional

import redis

from app.config import settings

logger = logging.getLogger(__name__)


ALERTS_BLACKLIST_CHANNEL = "alerts:blacklist"
RECOGNITION_EVENTS_CHANNEL = "events:recognition"
AI_STATUS_KEY = "ai:status"


_client: Optional[redis.Redis] = None


def get_redis() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=settings.REDIS_DB,
            decode_responses=True,
        )
    return _client


def init_queue() -> None:
    """Tạo consumer group nếu chưa có. Gọi lúc startup."""
    r = get_redis()
    try:
        r.xgroup_create(
            name=settings.RECOGNITION_STREAM,
            groupname=settings.RECOGNITION_GROUP,
            id="0",
            mkstream=True,
        )
        logger.info("Created consumer group '%s' on stream '%s'.",
                    settings.RECOGNITION_GROUP, settings.RECOGNITION_STREAM)
    except redis.ResponseError as exc:
        if "BUSYGROUP" in str(exc):
            logger.info("Consumer group '%s' already exists.", settings.RECOGNITION_GROUP)
        else:
            raise


def _state_key(job_id: str) -> str:
    return f"job:{job_id}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def push_recognition_job(camera_id: int, minio_key: str, user_id: int) -> str:
    """
    Thêm job vào queue. Trả về job_id.
    Đồng thời khởi tạo state `pending` trong Redis.
    """
    job_id = uuid.uuid4().hex
    r = get_redis()

    state = {
        "status": "pending",
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    r.hset(_state_key(job_id), mapping={"data": json.dumps(state)})
    r.expire(_state_key(job_id), settings.JOB_STATE_TTL_SECONDS)

    r.xadd(
        settings.RECOGNITION_STREAM,
        {
            "job_id": job_id,
            "camera_id": str(camera_id),
            "minio_key": minio_key,
            "user_id": str(user_id),
        },
        maxlen=settings.RECOGNITION_STREAM_MAXLEN,
        approximate=True,
    )
    logger.info("Enqueued job %s for camera %s.", job_id, camera_id)
    return job_id


def get_job_state(job_id: str) -> Optional[dict]:
    r = get_redis()
    raw = r.hget(_state_key(job_id), "data")
    if raw is None:
        return None
    return json.loads(raw)


def set_job_state(job_id: str, **patch) -> None:
    """Merge patch vào state hiện tại, cập nhật `updated_at`, refresh TTL."""
    r = get_redis()
    raw = r.hget(_state_key(job_id), "data")
    state = json.loads(raw) if raw else {}
    state.update(patch)
    state["updated_at"] = _now_iso()
    r.hset(_state_key(job_id), mapping={"data": json.dumps(state)})
    r.expire(_state_key(job_id), settings.JOB_STATE_TTL_SECONDS)


def publish_alert(channel: str, payload: dict) -> int:
    """Publish JSON payload lên Redis pub/sub channel. Trả về số subscriber nhận được."""
    r = get_redis()
    return r.publish(channel, json.dumps(payload))


# ── AI pipeline status (worker → backend handshake) ─────────────────────────

def set_ai_status(payload: dict) -> None:
    """Worker gọi sau khi init pipeline. Backend đọc qua /health/ai."""
    r = get_redis()
    payload = {**payload, "updated_at": _now_iso()}
    r.set(AI_STATUS_KEY, json.dumps(payload))


def get_ai_status() -> Optional[dict]:
    r = get_redis()
    raw = r.get(AI_STATUS_KEY)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def touch_ai_status_job() -> None:
    """Cập nhật last_job_at mà không ghi đè các field khác."""
    status = get_ai_status()
    if not status:
        return
    status["last_job_at"] = _now_iso()
    r = get_redis()
    r.set(AI_STATUS_KEY, json.dumps(status))
