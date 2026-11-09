from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # JWT
    SECRET_KEY: str                             # openssl rand -hex 32
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # Database
    DATABASE_URL: str                           # postgresql+psycopg2://user:pass@host/db
    DEBUG: bool = False

    # MinIO
    MINIO_ENDPOINT: str                         # vd: localhost:9000
    MINIO_ACCESS_KEY: str
    MINIO_SECRET_KEY: str
    MINIO_BUCKET: str = "plates"
    MINIO_SECURE: bool = False                  # True nếu dùng HTTPS

    # Qdrant
    QDRANT_HOST: str = "qdrant"                 # tên service trong docker-compose
    QDRANT_PORT: int = 6333

    # Redis (queue + cache)
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0

    # Recognition queue
    RECOGNITION_STREAM: str = "recognition:queue"
    RECOGNITION_GROUP: str = "workers"
    RECOGNITION_CONSUMER: str = "worker-1"
    JOB_STATE_TTL_SECONDS: int = 3600
    # Cap stream length — khi worker không kịp drain, frame cũ bị trim để
    # luôn xử lý frame gần đây nhất. ~500 ≈ 50s queue ở 5fps×2cam.
    RECOGNITION_STREAM_MAXLEN: int = 500
    # Skip job nếu frame quá cũ (ms). Tránh worker churn qua queue backlog
    # rồi panel AI hiện kết quả lệch hẳn so với live stream.
    RECOGNITION_MAX_AGE_MS: int = 3000

    # Camera stream ingestor
    CAMERA_PREVIEW_FPS: int = 10        # Frame rate publish lên Redis pub/sub cho MJPEG preview
    CAMERA_AI_FPS: int = 2              # Frame rate đẩy vào AI queue (worker xử lý)
    CAMERA_JPEG_QUALITY: int = 80       # 0-100
    RTSP_RECONNECT_BACKOFF_SECONDS: int = 5
    CAMERA_DISCOVERY_INTERVAL_SECONDS: int = 30

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()