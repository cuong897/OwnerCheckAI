
FROM python:3.11.9-slim AS builder

WORKDIR /build

COPY backend/requirements.txt ./requirements-api.txt
COPY AI_Engine/requirements.txt ./requirements-ai.txt

RUN pip install --no-cache-dir --prefix=/install \
        -r requirements-api.txt \
        -r requirements-ai.txt


FROM python:3.11.9-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    HOME=/home/appuser \
    MPLCONFIGDIR=/home/appuser/.config/matplotlib \
    YOLO_CONFIG_DIR=/home/appuser/.config/Ultralytics

WORKDIR /app

COPY --from=builder /install /usr/local

# OpenCV cần libGL + libglib2 (ultralytics pull opencv-python full bypass headless).
# ffmpeg cần cho cv2.VideoCapture đọc RTSP đáng tin cậy.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN addgroup --system appgroup && \
    adduser --system --ingroup appgroup --home /home/appuser appuser && \
    mkdir -p /home/appuser/.config/matplotlib \
             /home/appuser/.config/Ultralytics \
             /home/appuser/.paddleocr && \
    chown -R appuser:appgroup /home/appuser

COPY backend/app/ ./app/
COPY AI_Engine/ ./AI_Engine/

RUN chown -R appuser:appgroup /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" \
    || exit 1


CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "2", \
     "--loop", "uvloop", \
     "--log-level", "info"]
