"""
Router: /watchlists
  GET    /watchlists          — danh sách (filter: category, plate_number)
  POST   /watchlists          — thêm vào watchlist     [ADMIN]
  GET    /watchlists/{id}     — chi tiết
  PATCH  /watchlists/{id}     — cập nhật               [ADMIN]
  DELETE /watchlists/{id}     — xoá                    [ADMIN]
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.watchlist import Watchlist
from app.models.vehicle import Vehicle
from app.schemas.watchlist import WatchlistCreate, WatchlistUpdate, WatchlistResponse
from app.dependencies import get_current_user, require_admin
from app.models.user import User
from app.utils.plate import normalize_plate

router = APIRouter(prefix="/watchlists", tags=["Watchlists"])


@router.get("", response_model=List[WatchlistResponse], summary="Danh sách watchlist")
def list_watchlists(
    category: Optional[str] = Query(None, pattern="^(BLACKLIST|WHITELIST)$"),
    plate_number: Optional[str] = Query(None, description="Tìm kiếm biển số (LIKE)"),
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    q = db.query(Watchlist)
    if category:
        q = q.filter(Watchlist.category == category)
    if plate_number:
        q = q.filter(Watchlist.plate_number.ilike(f"%{plate_number}%"))
    return q.offset(offset).limit(limit).all()


@router.post(
    "",
    response_model=WatchlistResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Thêm vào watchlist [ADMIN]",
)
def create_watchlist(
    body: WatchlistCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    # Chuẩn hoá để khớp với format worker dùng khi insert log (tránh BLACKLIST không match)
    plate = normalize_plate(body.plate_number)
    if not plate:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="plate_number rỗng sau khi chuẩn hoá.",
        )

    # Không cho phép cùng 1 biển số xuất hiện trong cả BLACKLIST lẫn WHITELIST
    existing = db.query(Watchlist).filter(Watchlist.plate_number == plate).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Biển số '{plate}' đã có trong {existing.category}. "
                "Xoá hoặc cập nhật bản ghi cũ trước khi thêm mới."
            ),
        )

    # Auto-upsert vehicle: nếu biển số chưa có trong bảng vehicles thì tự tạo
    # (FK watchlists.plate_number -> vehicles.plate_number). Cần owner_name vì
    # vehicles.owner_name NOT NULL ở DB.
    vehicle = db.query(Vehicle).filter(Vehicle.plate_number == plate).first()
    if vehicle is None:
        if not body.owner_name:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Biển số '{plate}' chưa có trong danh sách xe. "
                    "Vui lòng nhập tên chủ xe (owner_name) để hệ thống tự tạo bản ghi xe mới."
                ),
            )
        vehicle = Vehicle(plate_number=plate, owner_name=body.owner_name)
        db.add(vehicle)
        db.flush()

    entry = Watchlist(
        plate_number=plate,
        category=body.category,
        owner_name=body.owner_name,
        note=body.note,
        created_by=current_user.id,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


@router.get("/{entry_id}", response_model=WatchlistResponse, summary="Chi tiết watchlist entry")
def get_watchlist(
    entry_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    entry = db.query(Watchlist).filter(Watchlist.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail=f"Watchlist id={entry_id} không tồn tại.")
    return entry


@router.patch(
    "/{entry_id}",
    response_model=WatchlistResponse,
    summary="Cập nhật watchlist entry [ADMIN]",
)
def update_watchlist(
    entry_id: int,
    body: WatchlistUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    entry = db.query(Watchlist).filter(Watchlist.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail=f"Watchlist id={entry_id} không tồn tại.")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(entry, field, value)
    db.commit()
    db.refresh(entry)
    return entry


@router.delete(
    "/{entry_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Xoá watchlist entry [ADMIN]",
)
def delete_watchlist(
    entry_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    entry = db.query(Watchlist).filter(Watchlist.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail=f"Watchlist id={entry_id} không tồn tại.")
    db.delete(entry)
    db.commit()