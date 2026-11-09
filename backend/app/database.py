
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session
from typing import Generator

from app.config import settings



engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,        # tự kiểm tra connection trước khi dùng
    pool_size=10,              # số connection giữ sẵn trong pool
    max_overflow=20,           # số connection tạm thêm khi pool đầy
    echo=settings.DEBUG,       # log SQL ra console khi DEBUG=True
)


# ── Base class cho tất cả ORM models ─────────────────────────────────────────

class Base(DeclarativeBase):
    pass



SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
)


# ── Dependency cho FastAPI ────────────────────────────────────────────────────

def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()



def init_db() -> None:
    from app.models import user, camera, vehicle, watchlist, recognition_log  # noqa: F401
    Base.metadata.create_all(bind=engine)