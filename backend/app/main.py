from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.routers import auth, users, cameras, vehicles, watchlists, recognition, stats, events, streams
from app.database import init_db
from app.qdrant import init_qdrant
from app.queue import init_queue, get_ai_status


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_db()
    init_qdrant()
    init_queue()
    yield
    # Shutdown (thêm cleanup nếu cần)


app = FastAPI(
    title="OwnerCheckAI",
    description="Hệ thống nhận dạng biển số xe (ALPR)",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(cameras.router)
app.include_router(vehicles.router)
app.include_router(watchlists.router)
app.include_router(recognition.router)
app.include_router(stats.router)
app.include_router(events.router)
app.include_router(streams.router)


@app.get("/health", tags=["Health"])
def health():
    return {"status": "ok"}


@app.get("/health/ai", tags=["Health"])
def health_ai():
    """
    Trạng thái pipeline AI do worker publish lên Redis.
      mode = full         → OCR + detection hoạt động.
      mode = detect_only  → chỉ detect được biển, OCR fail (kiểm tra weight).
      mode = dead         → cả detector cũng fail, mọi job sẽ FAILED.

    Trả 503 nếu mode != "full" hoặc worker chưa publish status (chưa start xong).
    """
    status = get_ai_status()
    if status is None:
        return JSONResponse(
            status_code=503,
            content={"status": "unknown", "detail": "Worker chưa publish ai:status (chưa khởi động xong?)."},
        )
    mode = status.get("mode")
    if mode == "full":
        return {"status": "ok", **status}
    return JSONResponse(
        status_code=503,
        content={"status": "degraded", **status},
    )