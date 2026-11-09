"""
Router: /stats
  GET /stats/summary          — tổng quan: tổng log, camera, vehicle, watchlist
  GET /stats/daily            — số lượng nhận dạng theo ngày (N ngày gần nhất)
  GET /stats/top-plates       — top biển số xuất hiện nhiều nhất
  GET /stats/camera-activity  — số lần nhận dạng theo từng camera
"""

from datetime import datetime, timedelta, timezone, date as _date
from typing import List

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, cast, Date, case, distinct
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.recognition_log import RecognitionLog
from app.models.camera import Camera
from app.models.vehicle import Vehicle
from app.models.watchlist import Watchlist
from app.dependencies import get_current_user
from app.models.user import User
from pydantic import BaseModel

router = APIRouter(prefix="/stats", tags=["Stats"])


# ── Response schemas (nội bộ, không cần file riêng) ──────────────────────────

class SummaryResponse(BaseModel):
    total_logs: int
    total_cameras: int
    active_cameras: int
    total_vehicles: int
    blacklist_count: int            # số plate DISTINCT đang nằm trong BLACKLIST
    whitelist_count: int            # số plate DISTINCT đang nằm trong WHITELIST
    vehicles_in_watchlist: int      # plate DISTINCT có mặt ở BẤT KỲ category nào


class DailyStatItem(BaseModel):
    date: str           # "YYYY-MM-DD"
    total: int
    success: int
    failed: int
    pending: int


class TopPlateItem(BaseModel):
    plate_text: str
    count: int


class CameraActivityItem(BaseModel):
    camera_id: int
    camera_name: str
    total: int


# ─────────────────────────────────────────────────────────────────────────────
# GET /stats/summary
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/summary", response_model=SummaryResponse, summary="Tổng quan hệ thống")
def summary(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    # Đếm DISTINCT plate để tránh over-count khi 1 biển có nhiều entries.
    # vehicles_in_watchlist là plate distinct ở MỌI category — frontend tính
    # "Bình thường" = total_vehicles - vehicles_in_watchlist (đúng cả khi 1 biển
    # nằm trong cả BLACKLIST lẫn WHITELIST, không bị trừ 2 lần).
    return SummaryResponse(
        total_logs=db.query(func.count(RecognitionLog.id)).scalar() or 0,
        total_cameras=db.query(func.count(Camera.id)).scalar() or 0,
        active_cameras=db.query(func.count(Camera.id)).filter(Camera.status == "ACTIVE").scalar() or 0,
        total_vehicles=db.query(func.count(Vehicle.plate_number)).scalar() or 0,
        blacklist_count=db.query(func.count(distinct(Watchlist.plate_number)))
            .filter(Watchlist.category == "BLACKLIST").scalar() or 0,
        whitelist_count=db.query(func.count(distinct(Watchlist.plate_number)))
            .filter(Watchlist.category == "WHITELIST").scalar() or 0,
        vehicles_in_watchlist=db.query(func.count(distinct(Watchlist.plate_number))).scalar() or 0,
    )


# ─────────────────────────────────────────────────────────────────────────────
# GET /stats/daily
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/daily", response_model=List[DailyStatItem], summary="Thống kê theo ngày")
def daily_stats(
    days: int = Query(7, ge=1, le=90, description="Số ngày gần nhất cần thống kê"),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    today = datetime.now(timezone.utc).date()
    # `days=7` ⇒ 7 điểm bao gồm hôm nay: [today-6 .. today]
    start_date = today - timedelta(days=days - 1)

    rows = (
        db.query(
            cast(RecognitionLog.timestamp, Date).label("date"),
            func.count().label("total"),
            func.sum(case((RecognitionLog.status == "SUCCESS", 1), else_=0)).label("success"),
            func.sum(case((RecognitionLog.status == "FAILED",  1), else_=0)).label("failed"),
            func.sum(case((RecognitionLog.status == "PENDING", 1), else_=0)).label("pending"),
        )
        .filter(cast(RecognitionLog.timestamp, Date) >= start_date)
        .group_by(cast(RecognitionLog.timestamp, Date))
        .all()
    )

    # Index theo date để bù những ngày trống → chart liên tục, không đứt đoạn.
    by_date: dict[_date, DailyStatItem] = {
        row.date: DailyStatItem(
            date=str(row.date),
            total=row.total,
            success=row.success or 0,
            failed=row.failed or 0,
            pending=row.pending or 0,
        )
        for row in rows
    }

    return [
        by_date.get(
            start_date + timedelta(days=i),
            DailyStatItem(
                date=str(start_date + timedelta(days=i)),
                total=0, success=0, failed=0, pending=0,
            ),
        )
        for i in range(days)
    ]


# ─────────────────────────────────────────────────────────────────────────────
# GET /stats/top-plates
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/top-plates", response_model=List[TopPlateItem], summary="Top biển số xuất hiện nhiều nhất")
def top_plates(
    limit: int = Query(10, ge=1, le=50),
    days: int = Query(30, ge=1, le=365, description="Giới hạn trong N ngày gần nhất"),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    since = datetime.now(timezone.utc) - timedelta(days=days)

    rows = (
        db.query(
            RecognitionLog.plate_text,
            func.count().label("count"),
        )
        .filter(
            RecognitionLog.timestamp >= since,
            RecognitionLog.plate_text != "",
            RecognitionLog.status == "SUCCESS",
        )
        .group_by(RecognitionLog.plate_text)
        .order_by(func.count().desc())
        .limit(limit)
        .all()
    )

    return [TopPlateItem(plate_text=row.plate_text, count=row.count) for row in rows]


# ─────────────────────────────────────────────────────────────────────────────
# GET /stats/camera-activity
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/camera-activity",
    response_model=List[CameraActivityItem],
    summary="Hoạt động nhận dạng theo từng camera",
)
def camera_activity(
    days: int = Query(7, ge=1, le=90),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    since = datetime.now(timezone.utc) - timedelta(days=days)

    rows = (
        db.query(
            Camera.id.label("camera_id"),
            Camera.camera_name,
            func.count(RecognitionLog.id).label("total"),
        )
        .outerjoin(RecognitionLog, RecognitionLog.camera_id == Camera.id)
        .filter(
            (RecognitionLog.timestamp >= since) | (RecognitionLog.timestamp.is_(None))
        )
        .group_by(Camera.id, Camera.camera_name)
        .order_by(func.count(RecognitionLog.id).desc())
        .all()
    )

    return [
        CameraActivityItem(camera_id=row.camera_id, camera_name=row.camera_name, total=row.total)
        for row in rows
    ]