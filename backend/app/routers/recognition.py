"""
Endpoints:
  POST  /recognition/process            — accept ảnh base64, push job vào queue, trả 202 + job_id
  GET   /recognition/jobs/{job_id}      — poll trạng thái + kết quả job
  GET   /recognition/logs               — danh sách logs (filter: camera_id, plate_text, status)
  GET   /recognition/logs/{id}          — chi tiết một log
  GET   /recognition/logs/{id}/image    — proxy ảnh crop của log từ MinIO (hợp lệ cho <img>)
  PATCH /recognition/logs/{id}/verify   — xác minh thủ công biển số
"""

import io
import uuid
import base64
import logging
from typing import Optional, List
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy.orm import Session
from sqlalchemy import desc
from minio import Minio
from minio.error import S3Error

from app.database import get_db
from app.config import settings
from app.models.recognition_log import RecognitionLog
from app.models.camera import Camera
from app.schemas.recognition import (
    RecognitionRequest,
    PlateResultSchema,
    RecognitionLogVerify,
    RecognitionLogResponse,
    JobAcceptedResponse,
    JobStatusResponse,
)
from app.dependencies import get_current_user, get_current_user_flex
from app.models.user import User
from app.queue import push_recognition_job, get_job_state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/recognition", tags=["Recognition"])


# ── Singleton MinIO client ────────────────────────────────────────────────────
_minio_client: Optional[Minio] = None


def get_minio() -> Minio:
    global _minio_client
    if _minio_client is None:
        _minio_client = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )
        if not _minio_client.bucket_exists(settings.MINIO_BUCKET):
            _minio_client.make_bucket(settings.MINIO_BUCKET)
            logger.info("MinIO: bucket '%s' created.", settings.MINIO_BUCKET)
    return _minio_client


def _looks_like_file_path(s: str) -> bool:
    return ("/" in s or "\\" in s) and len(s) < 512


def _upload_inbox(minio: Minio, image_bytes: bytes) -> str:
    """Upload ảnh gốc vào bucket dưới prefix inbox/. Trả về object key."""
    key = f"inbox/{uuid.uuid4().hex}.jpg"
    minio.put_object(
        settings.MINIO_BUCKET,
        key,
        data=io.BytesIO(image_bytes),
        length=len(image_bytes),
        content_type="image/jpeg",
    )
    return key


# ─────────────────────────────────────────────────────────────────────────────
# POST /recognition/process — enqueue job, return 202
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/process",
    response_model=JobAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Enqueue ảnh để xử lý nền — trả về job_id ngay",
)
def process_image(
    body: RecognitionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    minio: Minio = Depends(get_minio),
):
    """
    Luồng (đồng bộ phần này nhanh, AI chạy nền):
      1. Validate camera tồn tại + ACTIVE.
      2. Decode base64 → upload ảnh vào MinIO `inbox/`.
      3. Push job vào Redis Stream.
      4. Trả 202 + job_id. Client poll GET /recognition/jobs/{job_id}.
    """
    camera: Optional[Camera] = db.query(Camera).filter(Camera.id == body.camera_id).first()
    if not camera:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Camera id={body.camera_id} không tồn tại.",
        )
    if camera.status != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Camera id={body.camera_id} đang INACTIVE.",
        )

    if _looks_like_file_path(body.image_data):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Worker chạy trong container không truy cập được file path host — gửi base64.",
        )

    try:
        image_bytes = base64.b64decode(body.image_data, validate=True)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="image_data không phải base64 hợp lệ.",
        )

    try:
        minio_key = _upload_inbox(minio, image_bytes)
    except S3Error as exc:
        logger.exception("MinIO upload failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Không upload được ảnh vào object storage.",
        )

    job_id = push_recognition_job(
        camera_id=body.camera_id,
        minio_key=minio_key,
        user_id=current_user.id,
    )
    return JobAcceptedResponse(job_id=job_id, status="pending")


# ─────────────────────────────────────────────────────────────────────────────
# GET /recognition/jobs/{job_id}
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/jobs/{job_id}",
    response_model=JobStatusResponse,
    summary="Poll trạng thái job nhận dạng",
)
def get_job(
    job_id: str,
    _: User = Depends(get_current_user),
):
    state = get_job_state(job_id)
    if state is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job id={job_id} không tồn tại hoặc đã hết hạn (TTL {settings.JOB_STATE_TTL_SECONDS}s).",
        )
    result = state.get("result") or {}
    plates_raw = result.get("plates") if state.get("status") == "done" else None
    plates = [PlateResultSchema(**p) for p in plates_raw] if plates_raw else None
    return JobStatusResponse(
        job_id=job_id,
        status=state.get("status", "unknown"),
        created_at=state.get("created_at"),
        updated_at=state.get("updated_at"),
        plates=plates,
        log_ids=result.get("log_ids") if state.get("status") == "done" else None,
        process_time=result.get("process_time") if state.get("status") == "done" else None,
        error=state.get("error"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# GET /recognition/logs
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/logs",
    response_model=List[RecognitionLogResponse],
    summary="Danh sách recognition logs",
)
def list_logs(
    camera_id: Optional[int] = Query(None, description="Lọc theo camera"),
    plate_text: Optional[str] = Query(None, description="Lọc theo biển số (LIKE)"),
    log_status: Optional[str] = Query(
        None, alias="status", pattern="^(SUCCESS|FAILED|PENDING)$"
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(RecognitionLog).order_by(desc(RecognitionLog.timestamp))
    if camera_id is not None:
        q = q.filter(RecognitionLog.camera_id == camera_id)
    if plate_text:
        q = q.filter(RecognitionLog.plate_text.ilike(f"%{plate_text}%"))
    if log_status:
        q = q.filter(RecognitionLog.status == log_status)
    return q.offset(offset).limit(limit).all()


# ─────────────────────────────────────────────────────────────────────────────
# GET /recognition/logs/{log_id}
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/logs/{log_id}",
    response_model=RecognitionLogResponse,
    summary="Chi tiết một recognition log",
)
def get_log(
    log_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    log = db.query(RecognitionLog).filter(RecognitionLog.id == log_id).first()
    if not log:
        raise HTTPException(status_code=404, detail=f"Log id={log_id} không tồn tại.")
    return log


# ─────────────────────────────────────────────────────────────────────────────
# GET /recognition/logs/{log_id}/image — proxy ảnh từ MinIO
# ─────────────────────────────────────────────────────────────────────────────
# Lý do tồn tại: image_url lưu trong DB là presigned URL trỏ tới localhost:9000.
# Trình duyệt từ máy khác / qua reverse-proxy không reach được, và việc swap
# hostname sau khi sign có thể làm sai signature trên một số setup MinIO.
# Endpoint này streams ảnh qua backend bằng hostname nội bộ — luôn hoạt động.

def _extract_minio_key(image_url: str) -> str:
    """
    image_url có thể là:
      - URL đầy đủ:  http://host:port/<bucket>/<key>?X-Amz-...
      - Bare key:    plates/30A12345/abc.jpg
    """
    parsed = urlparse(image_url)
    if not parsed.scheme:
        return image_url.lstrip("/")
    path = parsed.path.lstrip("/")
    bucket_prefix = f"{settings.MINIO_BUCKET}/"
    if path.startswith(bucket_prefix):
        return path[len(bucket_prefix):]
    return path


@router.get(
    "/logs/{log_id}/image",
    summary="Stream ảnh crop của log (proxy MinIO)",
    response_class=Response,
    responses={200: {"content": {"image/jpeg": {}}}},
)
def get_log_image(
    log_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user_flex),
    minio: Minio = Depends(get_minio),
):
    log = db.query(RecognitionLog).filter(RecognitionLog.id == log_id).first()
    if not log:
        raise HTTPException(status_code=404, detail=f"Log id={log_id} không tồn tại.")
    if not log.image_url:
        raise HTTPException(status_code=404, detail="Log này chưa có ảnh.")

    key = _extract_minio_key(log.image_url)

    try:
        obj = minio.get_object(settings.MINIO_BUCKET, key)
        try:
            data = obj.read()
        finally:
            obj.close()
            obj.release_conn()
    except S3Error as exc:
        logger.warning("MinIO fetch failed for log %d, key %s: %s", log_id, key, exc)
        raise HTTPException(status_code=404, detail="Không tìm thấy ảnh trong storage.")

    return Response(
        content=data,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=86400"},
    )


# ─────────────────────────────────────────────────────────────────────────────
# PATCH /recognition/logs/{log_id}/verify
# ─────────────────────────────────────────────────────────────────────────────

@router.patch(
    "/logs/{log_id}/verify",
    response_model=RecognitionLogResponse,
    summary="Xác minh thủ công biển số",
)
def verify_log(
    log_id: int,
    body: RecognitionLogVerify,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    ADMIN: verify bất kỳ log nào.
    USER: chỉ verify khi body.verified_by == current_user.id.
    """
    log = db.query(RecognitionLog).filter(RecognitionLog.id == log_id).first()
    if not log:
        raise HTTPException(status_code=404, detail=f"Log id={log_id} không tồn tại.")

    if current_user.role != "ADMIN" and current_user.id != body.verified_by:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Không có quyền xác minh log này.",
        )

    log.is_manual_verified = True
    log.verified_plate_text = body.verified_plate_text.strip().upper()
    log.verified_by = body.verified_by
    db.commit()
    db.refresh(log)
    return log
