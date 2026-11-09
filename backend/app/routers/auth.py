"""
Router: /auth
Endpoints:
  POST /auth/register  — tạo tài khoản mới
  POST /auth/login     — đăng nhập, trả về JWT
  GET  /auth/me        — lấy thông tin user đang đăng nhập
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from sqlalchemy import func
from jose import JWTError, jwt
import bcrypt

from app.database import get_db
from app.models.user import User
from app.schemas.user import UserCreate, UserResponse, LoginRequest, TokenResponse

# ─────────────────────────────────────────────────────────────────────────────
# Config — đóc từ pydantic-settings trong thực tế
# ─────────────────────────────────────────────────────────────────────────────
# Đặt các giá trị này trong config.py / .env:
#   SECRET_KEY    — chuỗi ngẫu nhiên dài ≥32 ký tự
#   ALGORITHM     — "HS256"
#   ACCESS_TOKEN_EXPIRE_MINUTES — 60
#
# Ở đây import trực tiếp để router tự đứng được:

from app.config import settings   # pydantic-settings object

SECRET_KEY: str = settings.SECRET_KEY
ALGORITHM: str = getattr(settings, "ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES: int = getattr(settings, "ACCESS_TOKEN_EXPIRE_MINUTES", 60)

# ─────────────────────────────────────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────────────────────────────────────

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")
# Optional variant — không tự raise 401 khi thiếu header; dùng cho flex auth (SSE/MJPEG)
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)

router = APIRouter(prefix="/auth", tags=["Auth"])


# ── Password helpers (dùng bcrypt trực tiếp — passlib không tương thích bcrypt>=4.1) ────

def hash_password(plain: str) -> str:
    # bcrypt hard-limit 72 bytes; truncate password dài để không crash
    pw_bytes = plain.encode("utf-8")[:72]
    return bcrypt.hashpw(pw_bytes, bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        pw_bytes = plain.encode("utf-8")[:72]
        return bcrypt.checkpw(pw_bytes, hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ── JWT helpers ──────────────────────────────────────────────────────────────

def create_access_token(subject: str, role: str, expires_delta: Optional[timedelta] = None) -> str:
    """
    Tạo JWT với payload:
      sub  — user id (string)
      role — USER | ADMIN
      exp  — thời điểm hết hạn
    """
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload = {"sub": subject, "role": role, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Decode và verify JWT. Raise HTTPException 401 nếu không hợp lệ."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token không hợp lệ hoặc đã hết hạn.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        sub: Optional[str] = payload.get("sub")
        if sub is None:
            raise credentials_exception
        return payload
    except JWTError:
        raise credentials_exception


# ── Auth dependency — dùng trong các router khác ────────────────────────────

def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """
    FastAPI dependency: giải mã JWT → trả về User ORM object.
    Raise 401 nếu token sai, 403 nếu tài khoản bị vô hiệu hoá.
    """
    payload = decode_access_token(token)
    user_id: int = int(payload["sub"])

    user: Optional[User] = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tài khoản không tồn tại.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tài khoản đã bị vô hiệu hoá.",
        )
    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Dependency bổ sung: chỉ cho phép ADMIN."""
    if current_user.role != "ADMIN":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Chỉ ADMIN mới có quyền thực hiện thao tác này.",
        )
    return current_user


# ── Flex auth: chấp nhận JWT qua Authorization header HOẶC ?token= query ────
#
# Lý do tồn tại: EventSource (SSE) và <img src> (MJPEG) là 2 browser API
# KHÔNG cho phép gửi custom Authorization header. Frontend phải nhúng token
# vào URL `?token=xxx`.
#
# ⚠ Token trong query có thể lộ qua: URL bar, history browser, log nginx,
# Referer header. Chỉ chấp nhận được cho project sinh viên / internal tool.
# Production nên dùng HttpOnly cookie hoặc proxy-based session.

def get_current_user_flex(
    bearer_token: Optional[str] = Depends(oauth2_scheme_optional),
    query_token: Optional[str] = Query(
        None,
        alias="token",
        description="JWT — chỉ dùng khi không gửi qua Authorization header được (EventSource, <img>).",
    ),
    db: Session = Depends(get_db),
) -> User:
    """
    Tương tự get_current_user nhưng ưu tiên header, fallback sang ?token= query.
    Dùng cho /events/alerts và /streams/cameras/{id}.
    """
    token = bearer_token or query_token
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Thiếu token (Authorization header hoặc ?token= query param).",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_access_token(token)
    user_id: int = int(payload["sub"])

    user: Optional[User] = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tài khoản không tồn tại.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tài khoản đã bị vô hiệu hoá.",
        )
    return user


def require_admin_flex(current_user: User = Depends(get_current_user_flex)) -> User:
    """Flex variant của require_admin — cho SSE alerts (admin only)."""
    if current_user.role != "ADMIN":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Chỉ ADMIN mới có quyền thực hiện thao tác này.",
        )
    return current_user


# ─────────────────────────────────────────────────────────────────────────────
# POST /auth/register
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Đăng ký tài khoản mới (USER) — user đầu tiên hệ thống tự động làm ADMIN",
)
def register(body: UserCreate, db: Session = Depends(get_db)):
    # Kiểm tra username đã tồn tại chưa
    if db.query(User).filter(User.username == body.username).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Username '{body.username}' đã được sử dụng.",
        )

    # First-admin bootstrap: nếu hệ thống chưa có ADMIN active nào,
    # user đầu tiên được seed làm ADMIN. Sau đó mọi self-register đều là USER —
    # muốn tạo ADMIN tiếp phải qua POST /users (require_admin).
    admin_count = (
        db.query(func.count(User.id))
        .filter(User.role == "ADMIN", User.is_active.is_(True))
        .scalar()
        or 0
    )
    role = "ADMIN" if admin_count == 0 else "USER"

    user = User(
        username=body.username,
        hashed_password=hash_password(body.password),
        role=role,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ─────────────────────────────────────────────────────────────────────────────
# POST /auth/login
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Đăng nhập — trả về JWT",
)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user: Optional[User] = db.query(User).filter(User.username == body.username).first()

    # Dùng cùng một thông báo lỗi cho cả "không tìm thấy" và "sai mật khẩu"
    # để tránh user enumeration
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Username hoặc mật khẩu không đúng.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tài khoản đã bị vô hiệu hoá.",
        )

    token = create_access_token(subject=str(user.id), role=user.role)
    return TokenResponse(access_token=token, token_type="bearer")


# ─────────────────────────────────────────────────────────────────────────────
# GET /auth/me
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/me",
    response_model=UserResponse,
    summary="Thông tin user đang đăng nhập",
)
def me(current_user: User = Depends(get_current_user)):
    return current_user