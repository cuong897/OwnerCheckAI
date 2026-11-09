from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class UserCreate(BaseModel):
    """
    Self-register payload. KHÔNG nhận `role` từ client — server tự quyết:
      - User đầu tiên trong hệ thống → ADMIN (bootstrap)
      - Các user sau → USER
    Muốn tạo ADMIN tiếp theo: dùng POST /users (yêu cầu ADMIN đăng nhập).
    """
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=6)


class UserResponse(BaseModel):
    id: int
    username: str
    role: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Admin: user management ──────────────────────────────────────────────────

class UserAdminCreate(BaseModel):
    """Admin tạo user — có thể set role ngay (UserCreate dành cho self-register)."""
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=6)
    role: str = Field("USER", pattern="^(USER|ADMIN)$")
    is_active: bool = True


class UserUpdate(BaseModel):
    """Admin cập nhật user. Tất cả field optional."""
    role: Optional[str] = Field(None, pattern="^(USER|ADMIN)$")
    is_active: Optional[bool] = None


class PasswordResetRequest(BaseModel):
    """Body cho reset-password. Bỏ trống → server generate password ngẫu nhiên."""
    new_password: Optional[str] = Field(None, min_length=6, description="Để trống = auto-generate")


class PasswordResetResponse(BaseModel):
    user_id: int
    username: str
    new_password: str = Field(..., description="Mật khẩu mới — hiển thị 1 lần duy nhất")


# ── Auth ──────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"