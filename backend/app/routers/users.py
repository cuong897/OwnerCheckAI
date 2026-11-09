"""
Router: /users — admin quản lý tài khoản.
  GET    /users                       — danh sách users (filter role, is_active)
  POST   /users                       — admin tạo user (có thể set role/is_active)
  GET    /users/{id}                  — chi tiết user
  PATCH  /users/{id}                  — đổi role / disable / re-enable
  DELETE /users/{id}                  — soft delete (set is_active=false)
  POST   /users/{id}/reset-password   — đặt lại mật khẩu (server gen hoặc admin cung cấp)

Self-protection: admin không thể tự demote / disable / xoá chính mình
và hệ thống luôn giữ ≥1 ADMIN active.
"""

import secrets
import string
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models.user import User, UserRole
from app.schemas.user import (
    UserResponse,
    UserAdminCreate,
    UserUpdate,
    PasswordResetRequest,
    PasswordResetResponse,
)
from app.dependencies import require_admin
from app.routers.auth import hash_password

router = APIRouter(prefix="/users", tags=["Users"])


# ── Helpers ─────────────────────────────────────────────────────────────────

def _generate_password(length: int = 12) -> str:
    """Mật khẩu random 12 ký tự — chữ + số + ký hiệu, không gây nhầm lẫn."""
    alphabet = string.ascii_letters + string.digits + "!@#$%&*"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _count_active_admins(db: Session, exclude_id: Optional[int] = None) -> int:
    q = db.query(func.count(User.id)).filter(
        User.role == UserRole.ADMIN,
        User.is_active.is_(True),
    )
    if exclude_id is not None:
        q = q.filter(User.id != exclude_id)
    return q.scalar() or 0


def _get_or_404(db: Session, user_id: int) -> User:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User id={user_id} không tồn tại.",
        )
    return user


# ── GET /users ──────────────────────────────────────────────────────────────

@router.get("", response_model=List[UserResponse], summary="Danh sách users [ADMIN]")
def list_users(
    role: Optional[str] = Query(None, pattern="^(USER|ADMIN)$"),
    is_active: Optional[bool] = Query(None),
    username: Optional[str] = Query(None, description="Tìm theo username (LIKE)"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    q = db.query(User).order_by(User.id)
    if role:
        q = q.filter(User.role == role)
    if is_active is not None:
        q = q.filter(User.is_active.is_(is_active))
    if username:
        q = q.filter(User.username.ilike(f"%{username}%"))
    return q.offset(offset).limit(limit).all()


# ── POST /users ─────────────────────────────────────────────────────────────

@router.post(
    "",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Admin tạo user mới [ADMIN]",
)
def create_user(
    body: UserAdminCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    if db.query(User).filter(User.username == body.username).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Username '{body.username}' đã tồn tại.",
        )
    user = User(
        username=body.username,
        hashed_password=hash_password(body.password),
        role=body.role,
        is_active=body.is_active,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ── GET /users/{id} ─────────────────────────────────────────────────────────

@router.get("/{user_id}", response_model=UserResponse, summary="Chi tiết user [ADMIN]")
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    return _get_or_404(db, user_id)


# ── PATCH /users/{id} ───────────────────────────────────────────────────────

@router.patch("/{user_id}", response_model=UserResponse, summary="Cập nhật user [ADMIN]")
def update_user(
    user_id: int,
    body: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    user = _get_or_404(db, user_id)
    patch = body.model_dump(exclude_unset=True)

    # ── Self-protection ────────────────────────────────────────────────────
    if user.id == current_user.id:
        if "role" in patch and patch["role"] != current_user.role.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Không thể tự đổi role của chính mình.",
            )
        if patch.get("is_active") is False:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Không thể tự disable chính mình.",
            )

    # ── Last-admin guard ───────────────────────────────────────────────────
    will_demote = (
        user.role == UserRole.ADMIN
        and patch.get("role") == "USER"
    )
    will_disable_admin = (
        user.role == UserRole.ADMIN
        and patch.get("is_active") is False
    )
    if will_demote or will_disable_admin:
        if _count_active_admins(db, exclude_id=user.id) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Phải còn ít nhất 1 ADMIN active trong hệ thống.",
            )

    for field, value in patch.items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return user


# ── DELETE /users/{id} ─────────────────────────────────────────────────────

@router.delete(
    "/{user_id}",
    response_model=UserResponse,
    summary="Soft delete user — set is_active=false [ADMIN]",
)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """
    Soft delete để giữ audit trail (verified_by trong recognition_logs).
    Muốn re-enable: PATCH với is_active=true.
    """
    user = _get_or_404(db, user_id)

    if user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Không thể tự xoá chính mình.",
        )
    if user.role == UserRole.ADMIN and _count_active_admins(db, exclude_id=user.id) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Phải còn ít nhất 1 ADMIN active.",
        )

    user.is_active = False
    db.commit()
    db.refresh(user)
    return user


# ── POST /users/{id}/reset-password ────────────────────────────────────────

@router.post(
    "/{user_id}/reset-password",
    response_model=PasswordResetResponse,
    summary="Reset mật khẩu user [ADMIN]",
)
def reset_password(
    user_id: int,
    body: PasswordResetRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """
    Nếu `new_password` rỗng → server gen mật khẩu ngẫu nhiên 12 ký tự.
    Mật khẩu mới trả về trong response — admin **lưu lại ngay**, không có cách lấy lại.
    """
    user = _get_or_404(db, user_id)
    new_password = body.new_password or _generate_password()
    user.hashed_password = hash_password(new_password)
    db.commit()
    return PasswordResetResponse(
        user_id=user.id,
        username=user.username,
        new_password=new_password,
    )
