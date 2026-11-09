"""
Worker consumer cho recognition queue.

Vòng lặp:
  1. XREADGROUP từ stream `recognition:queue` (block 5s).
  2. Với mỗi job: download ảnh từ MinIO → LPRPipeline.run() → lưu RecognitionLog + Qdrant.
  3. Cập nhật job state trong Redis (done | failed).
  4. XACK message.

Run:
  python -m app.worker.main
"""

import io
import os
import re
import socket
import signal
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from minio import Minio
from minio.error import S3Error

from app.config import settings
from app.database import SessionLocal
from app.models.recognition_log import RecognitionLog
from app.models.vehicle import Vehicle
from app.models.watchlist import Watchlist
from app.qdrant import upsert_embedding
from app.queue import (
    get_redis,
    init_queue,
    set_job_state,
    publish_alert,
    set_ai_status,
    touch_ai_status_job,
    ALERTS_BLACKLIST_CHANNEL,
    RECOGNITION_EVENTS_CHANNEL,
)
from app.utils.plate import normalize_plate

from AI_Engine.pipeline import LPRPipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("worker")

CONSUMER_NAME = os.getenv("WORKER_NAME") or f"{socket.gethostname()}-{os.getpid()}"

# Wrapper giữ tên cũ để khỏi sửa nhiều call site (workers code path còn cũ).
_extract_plate = normalize_plate


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


_shutdown = False


def _handle_signal(signum, _frame):
    global _shutdown
    logger.info("Received signal %s — shutting down after current job.", signum)
    _shutdown = True


# ── Singletons ──────────────────────────────────────────────────────────────
_pipeline: Optional[LPRPipeline] = None
_minio: Optional[Minio] = None


def _get_pipeline() -> LPRPipeline:
    global _pipeline
    if _pipeline is None:
        logger.info("Loading LPRPipeline...")
        _pipeline = LPRPipeline()
    return _pipeline


def _get_minio() -> Minio:
    global _minio
    if _minio is None:
        _minio = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )
    return _minio


# ── Job handler ─────────────────────────────────────────────────────────────

def _download_image(minio: Minio, key: str) -> bytes:
    response = minio.get_object(settings.MINIO_BUCKET, key)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


def _delete_inbox(minio: Minio, key: str) -> None:
    """Xoá frame inbox sau khi đã xử lý xong. Inbox/ là tạm — nếu không xoá
    thì bucket phình ~22GB/ngày ở 5fps × 2 camera."""
    try:
        minio.remove_object(settings.MINIO_BUCKET, key)
    except Exception as exc:
        logger.warning("Failed to delete inbox key %s: %s", key, exc)


# Endpoint browser dùng để tải ảnh crop. Mặc định localhost:9000 (MinIO map ra
# host trong docker-compose); ghi đè bằng env nếu deploy thật.
PUBLIC_MINIO_ENDPOINT = os.getenv("PUBLIC_MINIO_ENDPOINT", "localhost:9000")


def _presign(minio: Minio, key: str) -> str:
    """Presigned GET URL — browser truy cập được dù bucket private. Hostname nội
    bộ minio:9000 được thay bằng PUBLIC_MINIO_ENDPOINT để client reach được."""
    signed = minio.presigned_get_object(
        settings.MINIO_BUCKET,
        key,
        expires=timedelta(hours=24),
    )
    return signed.replace(settings.MINIO_ENDPOINT, PUBLIC_MINIO_ENDPOINT, 1)


def _upload_crop(minio: Minio, crop_bytes: bytes, plate_text: str) -> Optional[str]:
    if not crop_bytes:
        return None
    try:
        # Tránh khoảng trắng / ký tự lạ trong plate_text khi làm path key
        safe_plate = re.sub(r"[^A-Z0-9._-]", "_", plate_text)
        key = f"plates/{safe_plate}/{uuid.uuid4().hex}.jpg"
        minio.put_object(
            settings.MINIO_BUCKET,
            key,
            data=io.BytesIO(crop_bytes),
            length=len(crop_bytes),
            content_type="image/jpeg",
        )
        return _presign(minio, key)
    except S3Error as exc:
        logger.warning("Crop upload failed for plate '%s': %s", plate_text, exc)
        return None


def _upload_miss_frame(minio: Minio, frame_bytes: bytes, camera_id: int) -> Optional[str]:
    """Upload frame gốc khi AI không detect được biển — để user verify thủ công
    trên trang Lịch sử. Key namespace `misses/` tách khỏi `plates/` để có thể
    áp MinIO lifecycle rule (vd: xoá sau 7 ngày) mà không đụng tới plate crops."""
    if not frame_bytes:
        return None
    try:
        key = f"misses/cam{camera_id}/{uuid.uuid4().hex}.jpg"
        minio.put_object(
            settings.MINIO_BUCKET,
            key,
            data=io.BytesIO(frame_bytes),
            length=len(frame_bytes),
            content_type="image/jpeg",
        )
        return _presign(minio, key)
    except S3Error as exc:
        logger.warning("Miss frame upload failed for cam %d: %s", camera_id, exc)
        return None


def _process_job(job_id: str, camera_id: int, minio_key: str) -> dict:
    """
    Pipeline → save log → ENRICH với owner info + watchlist → publish alert nếu BLACKLIST.
    Trả về dict {plates, log_ids, process_time}. Có thể raise.
    """
    minio = _get_minio()
    pipeline = _get_pipeline()

    t0 = time.perf_counter()
    image_bytes = _download_image(minio, minio_key)
    response = pipeline.run(image_bytes)

    plates_out = []
    log_ids = []
    alerts_to_publish = []
    recognitions_to_publish = []

    db = SessionLocal()
    try:
        for plate in response.plates:
            text = _extract_plate(plate.text or "")
            if not text:
                continue

            crop_bytes = getattr(plate, "crop_bytes", None)
            image_url = _upload_crop(minio, crop_bytes, text) if crop_bytes else None

            log = RecognitionLog(
                camera_id=camera_id,
                plate_text=text,
                ocr_confidence=plate.conf_detect,
                image_url=image_url,
                status="SUCCESS",
                is_manual_verified=False,
                retry_count=0,
            )
            db.add(log)
            db.flush()
            log_ids.append(log.id)

            embedding = getattr(plate, "embedding", None)
            if embedding:
                upsert_embedding(
                    log_id=log.id,
                    embedding=embedding,
                    plate_text=text,
                    camera_id=camera_id,
                    timestamp=log.timestamp.isoformat() if log.timestamp else "",
                )

            # ── Enrichment: chủ xe + watchlist ─────────────────────────────────
            vehicle = db.query(Vehicle).filter(Vehicle.plate_number == text).first()
            watchlist = db.query(Watchlist).filter(Watchlist.plate_number == text).first()

            owner_dict = (
                {
                    "registered": True,
                    "owner_name": vehicle.owner_name,
                    "vehicle_type": vehicle.vehicle_type,
                    "brand": vehicle.brand,
                    "color": vehicle.color,
                }
                if vehicle
                else {"registered": False}
            )

            watchlist_dict = None
            is_blacklist = False
            if watchlist:
                category = watchlist.category.value if hasattr(watchlist.category, "value") else str(watchlist.category)
                watchlist_dict = {"category": category, "note": watchlist.note}
                is_blacklist = category == "BLACKLIST"

            plates_out.append({
                "box": list(plate.box),
                "text": text,
                "conf_detect": float(plate.conf_detect),
                "owner": owner_dict,
                "watchlist": watchlist_dict,
                "alert": is_blacklist,
            })

            # Realtime push event cho LiveView (mọi plate, không chỉ blacklist).
            # Defer đến sau db.commit() để không gửi event cho row chưa persist.
            recognitions_to_publish.append({
                "type": "recognition",
                "log_id": log.id,
                "camera_id": camera_id,
                "plate_text": text,
                "conf_detect": float(plate.conf_detect),
                "timestamp": log.timestamp.isoformat() if log.timestamp else "",
                "image_url": image_url,
                "owner": owner_dict,
                "watchlist": watchlist_dict,
                "alert": is_blacklist,
            })

            # Defer publish đến SAU commit để không gửi alert cho row chưa lưu thành công
            if is_blacklist:
                alerts_to_publish.append({
                    "type": "blacklist_match",
                    "plate_text": text,
                    "camera_id": camera_id,
                    "log_id": log.id,
                    "timestamp": log.timestamp.isoformat() if log.timestamp else "",
                    "owner_name": vehicle.owner_name if vehicle else None,
                    "vehicle_type": vehicle.vehicle_type if vehicle else None,
                    "note": watchlist.note,
                    "image_url": image_url,
                })

        if not plates_out:
            miss_url = _upload_miss_frame(minio, image_bytes, camera_id)
            db.add(RecognitionLog(
                camera_id=camera_id,
                plate_text="",
                image_url=miss_url,
                status="PENDING",
                is_manual_verified=False,
                retry_count=0,
            ))

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    # Publish realtime recognition events (cho LiveView SSE)
    for payload in recognitions_to_publish:
        try:
            publish_alert(RECOGNITION_EVENTS_CHANNEL, payload)
        except Exception as exc:
            logger.warning("Failed to publish recognition event for plate %s: %s", payload["plate_text"], exc)

    # Publish alerts sau khi DB đã commit
    for payload in alerts_to_publish:
        try:
            n = publish_alert(ALERTS_BLACKLIST_CHANNEL, payload)
            logger.info("Published BLACKLIST alert for plate %s (subscribers=%d)", payload["plate_text"], n)
        except Exception as exc:
            logger.warning("Failed to publish alert for plate %s: %s", payload["plate_text"], exc)

    return {
        "plates": plates_out,
        "log_ids": log_ids,
        "process_time": round(time.perf_counter() - t0, 4),
    }


# ── Main loop ───────────────────────────────────────────────────────────────

def run():
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    init_queue()
    r = get_redis()

    # Eager-init pipeline để biết mode (full / detect_only / dead) trước job đầu,
    # rồi publish status lên Redis cho backend /health/ai đọc.
    pipeline = _get_pipeline()
    set_ai_status({
        "mode": pipeline.mode,
        "init_error": pipeline.init_error,
        "weight_paths": pipeline.weight_paths,
        "consumer": CONSUMER_NAME,
        "started_at": _now_iso(),
        "last_job_at": None,
    })
    if pipeline.mode == "dead":
        logger.error("Pipeline DEAD — worker vẫn chạy nhưng mọi job sẽ FAILED.")
    elif pipeline.mode == "detect_only":
        logger.warning("Pipeline DETECT-ONLY — log được tạo nhưng plate_text rỗng, cần verify thủ công.")

    logger.info("Worker '%s' started (ai_mode=%s), consuming from %s/%s",
                CONSUMER_NAME, pipeline.mode,
                settings.RECOGNITION_STREAM, settings.RECOGNITION_GROUP)

    while not _shutdown:
        try:
            messages = r.xreadgroup(
                groupname=settings.RECOGNITION_GROUP,
                consumername=CONSUMER_NAME,
                streams={settings.RECOGNITION_STREAM: ">"},
                count=1,
                block=5000,
            )
        except Exception as exc:
            logger.exception("xreadgroup failed: %s — retry in 2s", exc)
            time.sleep(2)
            continue

        if not messages:
            continue

        for _stream, entries in messages:
            for message_id, fields in entries:
                job_id = fields.get("job_id")
                minio_key = fields["minio_key"]

                # Freshness check — message_id format "ms-seq" (Redis stream).
                # Job cũ hơn RECOGNITION_MAX_AGE_MS → skip + ACK, không phí
                # CPU trên frame đã quá hạn. Đảm bảo AI panel khớp với live.
                try:
                    msg_ms = int(message_id.split("-", 1)[0])
                    age_ms = int(time.time() * 1000) - msg_ms
                except Exception:
                    age_ms = 0
                if age_ms > settings.RECOGNITION_MAX_AGE_MS:
                    logger.info("Skip stale job %s (age=%dms)", job_id, age_ms)
                    set_job_state(job_id, status="skipped", error=f"stale {age_ms}ms")
                    if minio_key.startswith("inbox/"):
                        _delete_inbox(_get_minio(), minio_key)
                    r.xack(settings.RECOGNITION_STREAM, settings.RECOGNITION_GROUP, message_id)
                    continue

                logger.info("Processing job %s (msg %s)", job_id, message_id)
                set_job_state(job_id, status="processing")
                try:
                    result = _process_job(
                        job_id=job_id,
                        camera_id=int(fields["camera_id"]),
                        minio_key=minio_key,
                    )
                    set_job_state(job_id, status="done", result=result)
                    touch_ai_status_job()
                    logger.info("Job %s done — %d plate(s) in %.3fs",
                                job_id, len(result["plates"]), result["process_time"])
                except Exception as exc:
                    logger.exception("Job %s failed: %s", job_id, exc)
                    set_job_state(job_id, status="failed", error=str(exc))
                finally:
                    # Xoá frame inbox dù success hay fail — không retry,
                    # giữ lại chỉ phình bucket.
                    if minio_key.startswith("inbox/"):
                        _delete_inbox(_get_minio(), minio_key)

                # ACK dù success hay fail — không retry vô hạn.
                # (Có thể nâng cấp: XAUTOCLAIM với delivery_count để retry n lần.)
                r.xack(settings.RECOGNITION_STREAM, settings.RECOGNITION_GROUP, message_id)

    logger.info("Worker '%s' stopped.", CONSUMER_NAME)


if __name__ == "__main__":
    run()
