"""
Stream ingestor: đọc RTSP từ tất cả camera ACTIVE, tách thành 2 luồng:

  • PREVIEW (CAMERA_PREVIEW_FPS): publish JPEG vào Redis pub/sub channel
    `camera:stream:{id}` → MJPEG endpoint stream về client.
  • AI (CAMERA_AI_FPS): upload JPEG vào MinIO inbox/, push job vào Redis Stream
    `recognition:queue` → worker xử lý.

Mỗi camera 1 thread riêng. Re-discover bảng cameras mỗi N giây để pick up thay đổi.

Run:
  python -m app.stream_ingestor.main
"""

import io
import os
import signal
import socket
import logging
import threading
import uuid
from typing import Dict, Tuple

import cv2
import redis
from minio import Minio

from app.config import settings
from app.database import SessionLocal
from app.models.camera import Camera
from app.queue import push_recognition_job

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("stream_ingestor")

INSTANCE_NAME = os.getenv("INGESTOR_NAME") or f"{socket.gethostname()}-{os.getpid()}"

# User_id để gắn lên job — ingestor là "system", không phải user thật.
SYSTEM_USER_ID = 0


# ── Helpers ─────────────────────────────────────────────────────────────────

def _stream_channel(camera_id: int) -> str:
    return f"camera:stream:{camera_id}"


def _get_binary_redis() -> redis.Redis:
    """Client riêng cho frame bytes — KHÔNG decode_responses."""
    return redis.Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        db=settings.REDIS_DB,
        decode_responses=False,
    )


def _get_minio() -> Minio:
    return Minio(
        settings.MINIO_ENDPOINT,
        access_key=settings.MINIO_ACCESS_KEY,
        secret_key=settings.MINIO_SECRET_KEY,
        secure=settings.MINIO_SECURE,
    )


def _discover_cameras() -> Dict[int, str]:
    """Trả về {camera_id: rtsp_url} cho camera ACTIVE có rtsp_url."""
    db = SessionLocal()
    try:
        rows = (
            db.query(Camera.id, Camera.rtsp_url)
            .filter(Camera.status == "ACTIVE")
            .filter(Camera.rtsp_url.isnot(None))
            .all()
        )
        return {cid: url for cid, url in rows if url and url.strip()}
    finally:
        db.close()


# ── Per-camera loop ─────────────────────────────────────────────────────────

def _camera_loop(camera_id: int, rtsp_url: str, stop_event: threading.Event) -> None:
    r = _get_binary_redis()
    minio = _get_minio()
    channel = _stream_channel(camera_id)

    preview_interval = 1.0 / max(1, settings.CAMERA_PREVIEW_FPS)
    ai_every_n = max(1, settings.CAMERA_PREVIEW_FPS // max(1, settings.CAMERA_AI_FPS))
    jpeg_params = [int(cv2.IMWRITE_JPEG_QUALITY), settings.CAMERA_JPEG_QUALITY]

    logger.info("camera %d: loop start (rtsp=%s, preview=%dfps, ai=%dfps, ai_every_n=%d)",
                camera_id, rtsp_url, settings.CAMERA_PREVIEW_FPS, settings.CAMERA_AI_FPS, ai_every_n)

    frame_count = 0

    while not stop_event.is_set():
        cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass  # not all backends support this

        if not cap.isOpened():
            logger.warning("camera %d: cannot open RTSP, retry in %ds",
                           camera_id, settings.RTSP_RECONNECT_BACKOFF_SECONDS)
            cap.release()
            if stop_event.wait(settings.RTSP_RECONNECT_BACKOFF_SECONDS):
                break
            continue

        logger.info("camera %d: connected", camera_id)

        # Reader thread: drain RTSP liên tục, chỉ giữ frame mới nhất. Tách khỏi
        # processor để cap.read() không kéo lùi cả pipeline khi source chậm
        # (HEVC nặng / publisher push < realtime) → MediaMTX sẽ không tích buffer.
        latest_slot: Dict[str, object] = {"frame": None}
        latest_lock = threading.Lock()
        reader_dead = threading.Event()

        def _reader() -> None:
            while not stop_event.is_set() and not reader_dead.is_set():
                ok, frame = cap.read()
                if not ok or frame is None:
                    reader_dead.set()
                    return
                with latest_lock:
                    latest_slot["frame"] = frame

        reader_thread = threading.Thread(
            target=_reader, name=f"cam-{camera_id}-reader", daemon=True
        )
        reader_thread.start()

        try:
            while not stop_event.is_set() and not reader_dead.is_set():
                # Sleep với khả năng interrupt; trả True nếu stop được set.
                if stop_event.wait(preview_interval):
                    break

                with latest_lock:
                    frame = latest_slot["frame"]
                    latest_slot["frame"] = None  # consume — tránh xử lại frame cũ

                if frame is None:
                    continue  # source chậm hơn preview FPS, chờ tick sau

                ok, buf = cv2.imencode(".jpg", frame, jpeg_params)
                if not ok:
                    continue
                jpeg_bytes = buf.tobytes()

                # 1) Publish cho MJPEG preview
                try:
                    r.publish(channel, jpeg_bytes)
                except Exception as exc:
                    logger.warning("camera %d: publish failed: %s", camera_id, exc)

                # 2) Mỗi N frame: gửi cho AI queue
                frame_count += 1
                if frame_count % ai_every_n == 0:
                    try:
                        key = f"inbox/cam{camera_id}/{uuid.uuid4().hex}.jpg"
                        minio.put_object(
                            settings.MINIO_BUCKET,
                            key,
                            data=io.BytesIO(jpeg_bytes),
                            length=len(jpeg_bytes),
                            content_type="image/jpeg",
                        )
                        push_recognition_job(
                            camera_id=camera_id,
                            minio_key=key,
                            user_id=SYSTEM_USER_ID,
                        )
                    except Exception as exc:
                        logger.warning("camera %d: AI submit failed: %s", camera_id, exc)
        finally:
            reader_dead.set()
            cap.release()
            reader_thread.join(timeout=5)

        if reader_dead.is_set() and not stop_event.is_set():
            logger.warning("camera %d: read failed, reconnect in %ds",
                           camera_id, settings.RTSP_RECONNECT_BACKOFF_SECONDS)
            if stop_event.wait(settings.RTSP_RECONNECT_BACKOFF_SECONDS):
                break

    logger.info("camera %d: loop stopped", camera_id)


# ── Main supervisor ─────────────────────────────────────────────────────────

def run() -> None:
    main_stop = threading.Event()

    def _handle_signal(signum, _frame):
        logger.info("Got signal %d, shutting down all camera threads", signum)
        main_stop.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    threads: Dict[int, Tuple[threading.Thread, threading.Event]] = {}
    logger.info("Stream ingestor '%s' starting", INSTANCE_NAME)

    # MinIO bucket ensure (worker cũng tạo, nhưng phòng khi ingestor chạy trước)
    try:
        m = _get_minio()
        if not m.bucket_exists(settings.MINIO_BUCKET):
            m.make_bucket(settings.MINIO_BUCKET)
            logger.info("Created MinIO bucket '%s'", settings.MINIO_BUCKET)
    except Exception as exc:
        logger.warning("MinIO bucket check failed (worker sẽ retry): %s", exc)

    while not main_stop.is_set():
        try:
            current = _discover_cameras()
        except Exception as exc:
            logger.exception("camera discovery failed: %s", exc)
            if main_stop.wait(10):
                break
            continue

        # Start mới
        for cid, url in current.items():
            if cid not in threads:
                stop_ev = threading.Event()
                t = threading.Thread(
                    target=_camera_loop,
                    args=(cid, url, stop_ev),
                    name=f"cam-{cid}",
                    daemon=True,
                )
                t.start()
                threads[cid] = (t, stop_ev)
                logger.info("started thread for camera %d", cid)

        # Dừng camera đã bị xoá hoặc INACTIVE
        for cid in list(threads.keys()):
            if cid not in current:
                _, ev = threads.pop(cid)
                ev.set()
                logger.info("requested stop for camera %d", cid)

        # Sleep với interrupt check
        if main_stop.wait(settings.CAMERA_DISCOVERY_INTERVAL_SECONDS):
            break

    # Graceful shutdown
    logger.info("Stopping %d camera threads", len(threads))
    for _, ev in threads.values():
        ev.set()
    for cid, (t, _) in threads.items():
        t.join(timeout=10)
    logger.info("Stream ingestor '%s' stopped", INSTANCE_NAME)


if __name__ == "__main__":
    run()
