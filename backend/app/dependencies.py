"""
Re-export auth dependencies từ auth router để các router khác import một chỗ duy nhất.
"""

from app.routers.auth import (
    get_current_user,
    require_admin,
    get_current_user_flex,
    require_admin_flex,
)

__all__ = [
    "get_current_user",
    "require_admin",
    "get_current_user_flex",
    "require_admin_flex",
]