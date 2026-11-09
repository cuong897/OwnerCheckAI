"""
Router: /cameras
  GET    /cameras          — danh sách cameras
  POST   /cameras          — tạo camera mới       [ADMIN]
  GET    /cameras/{id}     — chi tiết camera
  PATCH  /cameras/{id}     — cập nhật camera       [ADMIN]
  DELETE /cameras/{id}     — xoá camera            [ADMIN]
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.camera import Camera
from app.schemas.camera import CameraCreate, CameraUpdate, CameraResponse
from app.dependencies import get_current_user, require_admin
from app.models.user import User

router = APIRouter(prefix="/cameras", tags=["Cameras"])


@router.get("", response_model=List[CameraResponse], summary="Danh sách cameras")
def list_cameras(
    status: Optional[str] = Query(None, pattern="^(ACTIVE|INACTIVE)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    q = db.query(Camera)
    if status:
        q = q.filter(Camera.status == status)
    return q.offset(offset).limit(limit).all()


@router.post(
    "",
    response_model=CameraResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Tạo camera mới [ADMIN]",
)
def create_camera(
    body: CameraCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    camera = Camera(**body.model_dump())
    db.add(camera)
    db.commit()
    db.refresh(camera)
    return camera


@router.get("/{camera_id}", response_model=CameraResponse, summary="Chi tiết camera")
def get_camera(
    camera_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    camera = db.query(Camera).filter(Camera.id == camera_id).first()
    if not camera:
        raise HTTPException(status_code=404, detail=f"Camera id={camera_id} không tồn tại.")
    return camera


@router.patch("/{camera_id}", response_model=CameraResponse, summary="Cập nhật camera [ADMIN]")
def update_camera(
    camera_id: int,
    body: CameraUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    camera = db.query(Camera).filter(Camera.id == camera_id).first()
    if not camera:
        raise HTTPException(status_code=404, detail=f"Camera id={camera_id} không tồn tại.")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(camera, field, value)
    db.commit()
    db.refresh(camera)
    return camera


@router.delete(
    "/{camera_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Xoá camera [ADMIN]",
)
def delete_camera(
    camera_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    camera = db.query(Camera).filter(Camera.id == camera_id).first()
    if not camera:
        raise HTTPException(status_code=404, detail=f"Camera id={camera_id} không tồn tại.")
    db.delete(camera)
    db.commit()