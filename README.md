# OwnerCheckAI - Hệ thống nhận diện biển số & tra cứu chủ sở hữu thời gian thực

> **Bài tập lớn - AIT3004-2 “Thực hành phát triển hệ thống Trí tuệ Nhân tạo”**
> Trường Đại học Công nghệ - ĐHQG Hà Nội · Học kỳ 2, năm học 2025–2026
> Use case: phát hiện biển số xe từ camera RTSP, đối chiếu với cơ sở dữ liệu chủ xe + watchlist (BLACKLIST/WHITELIST) và cảnh báo realtime cho admin.

---

## Mục lục

1. [Tổng quan](#1-tổng-quan)
2. [Kiến trúc hệ thống](#2-kiến-trúc-hệ-thống)
3. [Yêu cầu môi trường](#3-yêu-cầu-môi-trường)
4. [Khởi động nhanh - `git clone` + `docker-compose up -d`](#4-khởi-động-nhanh)
5. [Biến môi trường `.env`](#5-biến-môi-trường-env)
6. [Quản lý phiên bản model & dữ liệu (DVC pipeline)](#6-quản-lý-phiên-bản-model--dữ-liệu)
7. [Catalog services](#7-catalog-services)
8. [Database schema](#8-database-schema)
9. [API reference](#9-api-reference)
10. [Luồng xử lý chi tiết](#10-luồng-xử-lý-chi-tiết)
11. [Demo scenarios](#11-demo-scenarios)
12. [Dữ liệu seed & test data](#12-dữ-liệu-seed--test-data)
13. [Troubleshooting](#13-troubleshooting)
14. [Phát triển](#14-phát-triển)
15. [Đối chiếu rubric](#15-đối-chiếu-rubric)
16. [Thành viên nhóm](#16-thành-viên-nhóm)

---

## 1. Tổng quan

### 1.1 Use case

Hệ thống đọc luồng video RTSP từ các camera giám sát, tự động:

1. **Phát hiện biển số** trong từng frame bằng YOLOv8 fine-tune.
2. **Nhận dạng ký tự** bằng PaddleOCR PP-OCRv3 (CTC + SAR MultiHead).
3. **Đối chiếu** với database chủ xe → trả về thông tin owner (tên, hãng, loại xe, màu).
4. **Kiểm tra watchlist** - nếu plate trong BLACKLIST → push cảnh báo qua Server-Sent Events tới admin.
5. **Lưu log** từng lần nhận diện kèm ảnh crop biển số vào MinIO + Postgres.
6. **Đánh chỉ mục vector** mỗi crop biển bằng ResNet18 → Qdrant để tìm xe tương đồng theo ảnh.

### 1.2 Tính năng chính

| Người dùng | Tính năng |
|---|---|
| **User** | Xem live MJPEG kèm bbox + biển nhận diện, lịch sử log, manual verify khi OCR sai, tìm xe tương đồng từ ảnh (vector search) |
| **Admin** | CRUD users / cameras / vehicles / watchlists, bulk import vehicles, realtime BLACKLIST alert, dashboard thống kê |

### 1.3 Tech stack

| Layer | Công nghệ |
|---|---|
| Backend | FastAPI 0.115 · SQLAlchemy 2.0 · Pydantic v2 |
| Frontend | React 18 + Vite 5 · Ant Design 5 · React Query · Recharts |
| AI Engine | YOLOv8m (Ultralytics) · PaddleOCR PP-OCRv3 · PyTorch 2.3 |
| Database | PostgreSQL 15 + `pgvector` + `pg_trgm` (search biển gần đúng) |
| Vector DB | Qdrant v1.11 - embedding 512d, Distance.COSINE |
| Object storage | MinIO (S3-compatible) |
| Queue / Cache | Redis 7.2 - Streams + Pub/Sub + LRU cache (`maxmemory 512mb / allkeys-lru`) |
| Load balancer | nginx 1.26 |
| Stream sim | MediaMTX (file mp4 → RTSP) |
| **Model & data versioning** | **DVC 3.x + MinIO remote (`dvc-store`) + `params.yaml` + `dvc.yaml`** |
| Container | Docker Compose v2 |

---

## 2. Kiến trúc hệ thống

### 2.1 Sơ đồ tổng thể

```mermaid
flowchart TB
    subgraph External
        CAM[📹 RTSP Cameras]
        BROWSER[🌐 Frontend<br/>User + Admin]
    end

    subgraph Edge
        NGINX[nginx :80<br/>Load balancer]
    end

    subgraph Compute
        BACKEND[backend<br/>FastAPI :8000]
        WORKER[worker<br/>AI consumer]
        INGEST[stream-ingestor<br/>RTSP → frames]
    end

    subgraph Storage
        DB[(PostgreSQL<br/>:5432)]
        REDIS[(Redis<br/>:6379<br/>Streams + PubSub)]
        MINIO[(MinIO<br/>:9000<br/>blob + dvc-store)]
        QDRANT[(Qdrant<br/>:6333)]
    end

    BROWSER -->|HTTPS| NGINX
    NGINX -->|/api/| BACKEND
    NGINX -->|/events/| BACKEND
    NGINX -->|/streams/| BACKEND
    NGINX -->|/| BROWSER

    CAM -->|RTSP| INGEST
    INGEST -->|pub/sub<br/>JPEG @10fps| REDIS
    INGEST -->|XADD<br/>recognition:queue| REDIS

    BACKEND -->|SQL| DB
    BACKEND -->|S3 API| MINIO
    BACKEND -->|XADD| REDIS
    BACKEND -->|SUBSCRIBE<br/>alerts:blacklist| REDIS

    WORKER -->|XREADGROUP| REDIS
    WORKER -->|GetObject| MINIO
    WORKER -->|INSERT log| DB
    WORKER -->|Upsert 512d| QDRANT
    WORKER -->|PUBLISH<br/>alerts:blacklist| REDIS
```

### 2.2 Phân tách trách nhiệm

| Service | Vai trò | Stateful? |
|---|---|---|
| `nginx` | Reverse proxy, route theo path | Stateless |
| `frontend` | React SPA build static, serve qua nginx-alpine nội bộ | Stateless |
| `backend` | REST API, auth, validation, SSE | Stateless (scale ngang) |
| `worker` | Consumer Redis Stream, chạy AI inference, ghi DB/Qdrant | Stateless |
| `stream-ingestor` | Đọc RTSP/camera ACTIVE, decode → publish | Stateful (mỗi camera 1 thread) |
| `db` | Postgres single instance | Stateful |
| `redis` | Streams (durable) + pub/sub + LRU cache | Stateful |
| `minio` | Blob: ảnh gốc, crop, **DVC remote `dvc-store`** | Stateful |
| `qdrant` | Vector DB cho plate embeddings | Stateful |
| `mediamtx` | RTSP simulator (demo, không cần camera vật lý) | - |

### 2.3 Nguyên tắc thiết kế

- **Async first** - API trả `202 Accepted` ngay, worker xử lý nền qua Redis Stream. Không block user > 100ms.
- **Stateless compute** - backend/worker scale ngang; toàn bộ state nằm ở DB/Redis/MinIO/Qdrant.
- **Backpressure** - Redis Stream làm buffer giữa ingestor và worker; queue đầy thì drop frame (chấp nhận cho preview).
- **Realtime tách AI** - MJPEG preview (10fps) độc lập với AI pipeline (2fps).
- **Reproducible AI** - `params.yaml` + `dvc.yaml` cho phép rerun đúng stage bị ảnh hưởng khi sửa hyperparams/dataset (xem [section 6](#6-quản-lý-phiên-bản-model--dữ-liệu)).

---

## 3. Yêu cầu môi trường

### 3.1 Phần cứng

| | Tối thiểu | Khuyến nghị |
|---|---|---|
| CPU | 4 cores | 8 cores |
| RAM | 8 GB | 16 GB |
| Disk | 20 GB (image ~6GB + data) | 50 GB |
| GPU | Không bắt buộc - CPU OK | NVIDIA + CUDA 12 → AI throughput ×5-10 |

### 3.2 Phần mềm

- **Docker Desktop** ≥ 24.0 (Windows/Mac) hoặc **Docker Engine** ≥ 24 + **Compose v2** (Linux).
- **Git** ≥ 2.30.
- **DVC ≥ 3.x** với extras `[s3]` để kéo model weights từ MinIO remote - chỉ cần cài host (không cần trong container):
  ```bash
  pip install "dvc[s3]"
  ```
- (Tuỳ chọn) Postman / HTTPie / curl để test API.

### 3.3 Port

Tất cả port nội bộ bind `127.0.0.1`; chỉ port 80 expose ra public qua nginx.

| Port | Service | Public? |
|---|---|---|
| 80 | nginx | ✅ |
| 5432 | postgres | ❌ localhost |
| 6379 | redis | ❌ localhost |
| 9000, 9001 | minio (API + console) | ❌ localhost |
| 6333, 6334 | qdrant (REST + gRPC) | ❌ localhost |
| 8554 | mediamtx (RTSP sim) | ❌ localhost |
| 5050 | pgadmin (`--profile tools`) | ❌ localhost |

---

## 4. Khởi động nhanh

> **Cho giảng viên / người chấm bài:** chỉ cần `git clone` + `docker compose up -d`.
> Image đã pre-build sẵn trên Docker Hub kèm model weights - **không cần `.env`, không cần DVC, không cần build local**.

### 4.1 Chạy nhanh (1 lệnh sau khi clone)

```bash
git clone <repo-url> OwnerCheckAI
cd OwnerCheckAI
docker compose up -d                  # KHÔNG cần tạo .env, KHÔNG cần build
```

Compose sẽ tự pull 2 image custom từ Hub:

| Image | Vai trò | Size (compressed) |
|---|---|---|
| [`dddddd112233/lpr-backend:1.0`](https://hub.docker.com/r/dddddd112233/lpr-backend) | FastAPI + worker + ingestor + AI model weights baked | ~1.8 GB |
| [`dddddd112233/lpr-frontend:1.0`](https://hub.docker.com/r/dddddd112233/lpr-frontend) | React SPA build + nginx serve | ~25 MB |

Cộng với image công cộng: `nginx:1.26-alpine`, `pgvector/pgvector:pg15`, `redis:7.2-alpine`, `qdrant/qdrant:v1.11.0`, `minio/minio:latest`, `minio/mc:latest`, `bluenviron/mediamtx:latest-ffmpeg`.

Lần đầu pull ~**5–10 phút** (tải ~2 GB nén). Lần sau `docker compose up -d` ~30s.

### 4.2 Kiểm tra stack

```bash
docker compose ps                     # tất cả Up (healthy), trừ minio-setup Exit 0
curl http://localhost/health          # → {"status":"ok"}
```

Mở UI <http://localhost/> · Swagger <http://localhost/docs>.

**Tạo admin lần đầu** (DB rỗng - user đầu tiên đăng ký auto thành ADMIN):
```bash
curl -X POST http://localhost/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}'
```

### 4.3 Override config khi cần (production)

Mọi biến môi trường trong [docker-compose.yml](docker-compose.yml) đã có default an toàn cho demo qua `${VAR:-default}`. Nếu muốn đổi mật khẩu / `SECRET_KEY` cho production: tạo file `.env` cạnh `docker-compose.yml`, compose tự nạp và override.

```bash
cp .env.example .env                  # Linux/Mac
# Copy-Item .env.example .env         # Windows PowerShell

# Sau đó sửa các giá trị nhạy cảm:
#   SECRET_KEY=<openssl rand -hex 32>
#   POSTGRES_PASSWORD=<strong-pass>
#   MINIO_ROOT_PASSWORD=<strong-pass>
```

### 4.4 Workflow cho developer (build image từ source code)

Khi sửa code backend/frontend và muốn rebuild image local:

```bash
# Cần DVC để kéo model weights về (~120 MB)
docker compose up -d minio minio-setup
dvc remote modify --local minio access_key_id    "$MINIO_ROOT_USER"
dvc remote modify --local minio secret_access_key "$MINIO_ROOT_PASSWORD"
dvc pull

docker compose build                  # rebuild backend + frontend
docker compose up -d                  # restart với image vừa build
```

`docker-compose.yml` khai báo cả `image:` lẫn `build:` - compose ưu tiên image local nếu có, fallback pull từ Hub.

> Chi tiết DVC + cách bump model version: [section 6](#6-quản-lý-phiên-bản-model--dữ-liệu).

### 4.5 Lệnh hữu ích

```bash
docker compose logs -f worker             # tail log
docker compose restart backend            # reload sau khi sửa code
docker compose down                       # stop tất cả
docker compose down -v                    # + xoá volumes (mất data!)
docker compose --profile tools up -d pgadmin   # bật pgadmin → :5050
```

### 4.6 Dev backend ngoài Docker

Không khuyến khích vì cần torch/opencv/paddle local. Nếu cần:

```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install -r ..\AI_Engine\requirements.txt
docker compose up -d db redis minio qdrant      # service phụ thuộc
$env:PYTHONPATH = "."
uvicorn app.main:app --reload
```

---

## 5. Biến môi trường `.env`

Đầy đủ trong [`.env.example`](.env.example). Tóm tắt nhóm chính:

| Nhóm | Biến |
|---|---|
| DB | `POSTGRES_USER/PASSWORD/DB`, `DATABASE_URL` |
| Auth | `SECRET_KEY`, `ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES` |
| MinIO | `MINIO_ROOT_USER/PASSWORD`, `MINIO_ENDPOINT`, `MINIO_ACCESS/SECRET_KEY`, `MINIO_BUCKET`, `MINIO_SECURE` |
| Qdrant | `QDRANT_HOST/PORT` |
| Redis | `REDIS_HOST/PORT/DB` |
| Camera | `CAMERA_PREVIEW_FPS`, `CAMERA_AI_FPS`, `CAMERA_JPEG_QUALITY`, `JOB_STATE_TTL_SECONDS` |
| pgAdmin | `PGADMIN_EMAIL/PASSWORD` |

> Không commit `.env`. Chỉ commit `.env.example`. Mật khẩu trong file mẫu là **dev defaults** - phải đổi khi deploy.

---

## 6. Quản lý phiên bản model & dữ liệu

Đây là **điểm cộng rubric**: hệ thống ML cần tái lập được khi đổi hyperparams hay retrain - không phải “chạy được trên máy mình là xong”. Tổ chức:

```
params.yaml              ← single source-of-truth cho hyperparams
dvc.yaml                 ← pipeline stages: train → eval → metrics
MODELS.md                ← model registry: version, dataset, metrics, lineage
metrics/*.json           ← output của eval stage (DVC track)
*.dvc, **/*.dvc          ← pointer file (size + md5 + path), commit vào git
.dvc/config              ← remote MinIO bucket `dvc-store`
```

### 6.1 Layout

| File / dir | Role |
|---|---|
| [`params.yaml`](params.yaml) | Hyperparams cho `detector.*`, `ocr.*`, `pipeline.*`, `embedder.*`. DVC track theo key, đổi 1 dòng → rerun đúng stage bị ảnh hưởng. |
| [`dvc.yaml`](dvc.yaml) | Định nghĩa 4 stage: `train_detector`, `eval_detector`, `train_ocr`, `eval_ocr` - kèm deps/outs/params/metrics. |
| [`MODELS.md`](MODELS.md) | Model card: version, dataset, hyperparams, metrics, git/dvc commit. Mỗi lần bump model phải cập nhật. |
| `metrics/detector.json`, `metrics/ocr.json` | Output của eval stage. `dvc metrics show` / `dvc metrics diff` để so sánh giữa version. |
| `.dvc/config` | Remote `minio` trỏ `s3://dvc-store` tại MinIO trong stack (`endpointurl=http://localhost:9000`). |

### 6.2 File `.dvc` đang track

| Pointer (git) | File thực (DVC) | Size |
|---|---|---|
| `yolov8m.pt.dvc` | `yolov8m.pt` (Ultralytics pretrained backbone) | 50 MB |
| `yolo26n.pt.dvc` | `yolo26n.pt` (YOLO nano - alt baseline) | 5 MB |
| `AI_Engine/modelLPdetector/models/best_detector.pt.dvc` | `best_detector.pt` (fine-tuned biển VN) | 50 MB |
| `AI_Engine/modelOCR/models/pretrained/rec_model/inference/inference.pdmodel.dvc` | PaddleOCR rec inference graph | ~1 MB |
| `AI_Engine/modelOCR/models/pretrained/rec_model/inference/inference.pdiparams.dvc` | PaddleOCR rec inference params | ~9 MB |

### 6.3 Kéo weight về (workflow sau khi clone)

```bash
docker compose up -d minio minio-setup
dvc remote modify --local minio access_key_id    "$MINIO_ROOT_USER"
dvc remote modify --local minio secret_access_key "$MINIO_ROOT_PASSWORD"
dvc pull
```

DVC dùng MD5 trong pointer file để verify integrity - file lỗi/thiếu sẽ tự download lại. Sau bước này stack sẵn sàng `docker compose up --build`.

### 6.4 Chạy pipeline tái lập

Pipeline 4 stage được khai báo trong [`dvc.yaml`](dvc.yaml):

```
yolov8m.pt + dataset YOLO  →  train_detector  →  best_detector.pt
                                     ↓
                              eval_detector   →  metrics/detector.json

rec_model pretrained + dataset OCR  →  train_ocr  →  finetuned/rec_model/
                                            ↓
                                       eval_ocr   →  metrics/ocr.json
```

Lệnh quan trọng:

```bash
dvc repro                       # chạy lại stage nào đổi deps/params/code
dvc repro train_detector        # chỉ 1 stage
dvc repro --force eval_ocr      # force rerun bỏ qua cache

dvc metrics show                # bảng metrics hiện tại
dvc metrics diff HEAD~1         # so với commit trước

dvc dag                         # in DAG dependency graph
dvc status                      # cho biết stage nào out-of-date
```

### 6.5 Bump model version

```bash
# 1. Sửa params.yaml (ví dụ tăng epochs 50 → 80)
$EDITOR params.yaml

# 2. Rerun stage bị ảnh hưởng (DVC tự phát hiện)
dvc repro

# 3. Check metrics mới
dvc metrics diff

# 4. Nếu chấp nhận → push weight mới + cập nhật MODELS.md
dvc push
$EDITOR MODELS.md     # bump version, ghi date + metrics + notes
git add params.yaml dvc.yaml dvc.lock MODELS.md metrics/ \
        AI_Engine/modelLPdetector/models/best_detector.pt.dvc
git commit -m "chore(model): bump detector to v1.1 (epochs 80, mAP50 +1.8%)"
```

Người khác chỉ cần `git pull && dvc pull` là có model mới.

### 6.6 Track dataset (lần đầu, trên máy có data)

Dataset images/labels không commit git (`.gitignore`). Để tái lập 100%, thành viên có data gốc cần:

```bash
dvc add AI_Engine/modelLPdetector/datasets/train \
        AI_Engine/modelLPdetector/datasets/valid \
        AI_Engine/modelOCR/datasets/train \
        AI_Engine/modelOCR/datasets/valid
dvc push
git add **/datasets/*.dvc
git commit -m "chore(data): track LPR + OCR datasets"
```

Từ đó người khác `dvc pull` là kéo cả data lẫn weight.

### 6.7 Remote thay thế

Nếu không tiện chạy MinIO trên host (vd. demo nhanh trên máy giảng viên), đổi remote DVC sang Google Drive / S3 / HTTP:

```bash
dvc remote add -d gdrive gdrive://<folder-id>      # cần dvc[gdrive]
dvc remote add -d aws    s3://my-bucket/dvc        # cần AWS creds
dvc remote default gdrive
```

Sửa `.dvc/config` để chốt cấu hình.

> Xem [`MODELS.md`](MODELS.md) cho version history chi tiết của từng model + hướng dẫn fine-tune PaddleOCR end-to-end.

---

## 7. Catalog services

Stack gồm **10 container** (chưa kể `pgadmin` profile riêng):

| Container | Image | Vai trò | Healthcheck |
|---|---|---|---|
| `lpr_nginx` | nginx:1.26-alpine | Reverse proxy port 80 | depends_on backend healthy |
| `lpr_frontend` | build (frontend/Dockerfile) | Static React SPA serve bằng nginx-alpine | - |
| `lpr_backend` | build (backend/Dockerfile) | FastAPI API | `GET /health` |
| `lpr_worker` | build (backend/Dockerfile) | AI consumer Redis Stream | - |
| `lpr_stream_ingestor` | build (backend/Dockerfile) | RTSP → frames | - |
| `lpr_postgres` | pgvector/pgvector:pg15 | DB + pgvector + pg_trgm | `pg_isready` |
| `lpr_redis` | redis:7.2-alpine | Stream + pubsub + LRU cache | `redis-cli ping` |
| `lpr_minio` | minio/minio:latest | Blob + DVC remote | `mc ready local` |
| `lpr_minio_setup` | minio/mc:latest | Bootstrap bucket (run once) | N/A |
| `lpr_qdrant` | qdrant/qdrant:v1.11.0 | Vector DB | - |
| `lpr_mediamtx` | bluenviron/mediamtx:latest-ffmpeg | RTSP simulator | - |

3 container `backend / worker / stream-ingestor` chia sẻ chung 1 Docker image (khác `command:`) để giảm disk + đảm bảo cùng version code.

---

## 8. Database schema

Schema tạo tự động bởi `storage/db/init_db.sql` khi Postgres khởi động lần đầu.

```mermaid
erDiagram
    users ||--o{ recognition_logs : verifies
    users ||--o{ refresh_tokens : owns
    users ||--o{ watchlists : created_by
    cameras ||--o{ recognition_logs : produces
    vehicles ||--o{ watchlists : referenced_by
    users ||--o{ system_logs : audited

    users {
        int id PK
        string username UK
        string password_hash
        string role "ADMIN | MONITOR_STAFF"
        bool is_active
        timestamptz last_login_at
    }
    cameras {
        int id PK
        string camera_name
        string location
        string rtsp_url
        string status "ACTIVE | INACTIVE"
    }
    vehicles {
        string plate_number PK
        string owner_name
        string owner_cccd
        string vehicle_type
        string brand
        string color
    }
    watchlists {
        int id PK
        string plate_number FK
        string category "BLACKLIST | WHITELIST"
        string note
        int created_by FK
    }
    recognition_logs {
        bigint id PK
        int camera_id FK
        string plate_text
        float ocr_confidence
        string image_url
        string status
        int verified_by FK
    }
    refresh_tokens {
        bigint id PK
        int user_id FK
        string token_hash UK
        timestamptz expires_at
        timestamptz revoked_at
    }
    system_logs {
        bigint id PK
        int user_id FK
        string action
        jsonb detail
    }
```

### Index đáng chú ý

- `idx_recognition_plate_trgm` - GIN trigram trên `plate_text` → search `51A123` matches `51A-123.45`.
- `idx_watchlists_blacklist` - partial index BLACKLIST → tăng tốc alert check.
- `idx_recognition_unverified` - partial cho log SUCCESS chưa verify → trang admin review nhanh.
- `idx_system_logs_detail` - GIN trên JSONB cho audit query.

---

## 9. API reference

Swagger UI: <http://localhost/docs> · OpenAPI JSON: <http://localhost/openapi.json>

### 9.1 Tóm tắt endpoint

#### Auth
| Method | Path | Auth | Mô tả |
|---|---|---|---|
| POST | `/auth/register` | ❌ | Self-register. User đầu tiên auto-set role `ADMIN` (bootstrap); từ user thứ hai luôn là `USER`. |
| POST | `/auth/login` | ❌ | Trả JWT (access + refresh) |
| GET | `/auth/me` | ✅ | Current user info |

#### Users (admin)
| Method | Path | Mô tả |
|---|---|---|
| GET | `/users` | List + filter role/is_active/username |
| POST | `/users` | Admin tạo user (set role + is_active) |
| GET/PATCH/DELETE | `/users/{id}` | CRUD |
| POST | `/users/{id}/reset-password` | Reset password (auto-gen hoặc admin nhập) |

#### Cameras / Vehicles / Watchlists
| Resource | List | Get | Create (ADMIN) | Update (ADMIN) | Delete (ADMIN) | Đặc biệt |
|---|---|---|---|---|---|---|
| Cameras | `GET /cameras` | `/cameras/{id}` | `POST /cameras` | `PATCH /cameras/{id}` | `DELETE /cameras/{id}` | — |
| Vehicles | `GET /vehicles` | `/vehicles/{plate}` | `POST /vehicles` | `PATCH /vehicles/{plate}` | `DELETE /vehicles/{plate}` | `POST /vehicles/bulk-import` (max 1000), `POST /vehicles/similar` (vector search) |
| Watchlists | `GET /watchlists` | `/watchlists/{id}` | `POST /watchlists` | `PATCH /watchlists/{id}` | `DELETE /watchlists/{id}` | — |

#### Recognition
| Method | Path | Mô tả |
|---|---|---|
| POST | `/recognition/process` | Enqueue ảnh base64 → `202 + job_id` |
| GET | `/recognition/jobs/{job_id}` | Poll status, plates + owner + alert |
| GET | `/recognition/logs` | List logs + filter |
| GET | `/recognition/logs/{id}` | Detail |
| PATCH | `/recognition/logs/{id}/verify` | Manual verify |

#### Realtime
| Method | Path | Mô tả |
|---|---|---|
| GET `/events/alerts` | (ADMIN) SSE - push `blacklist_match` |
| GET `/streams/cameras/{id}` | MJPEG live preview (`multipart/x-mixed-replace`) |

#### Stats
`GET /stats/summary | /stats/daily | /stats/top-plates | /stats/camera-activity`

### 9.2 Authentication

Hầu hết endpoint require JWT:
```
Authorization: Bearer <access_token>
```

```bash
curl -X POST http://localhost/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"ChangeMe@2024"}'
# → {"access_token":"eyJ...", "token_type":"bearer"}
```

---

## 10. Luồng xử lý chi tiết

### 10.1 Async recognition (upload ảnh)

```mermaid
sequenceDiagram
    actor Client
    participant Backend
    participant MinIO
    participant Redis as Redis Stream
    participant Worker
    participant DB as Postgres
    participant Qdrant

    Client->>Backend: POST /recognition/process<br/>{image_data: base64, camera_id}
    Backend->>Backend: validate + decode base64
    Backend->>MinIO: PUT inbox/{uuid}.jpg
    Backend->>Redis: XADD recognition:queue
    Backend->>Redis: HSET job:{id} pending
    Backend-->>Client: 202 Accepted {job_id}

    Worker->>Redis: XREADGROUP recognition:queue
    Worker->>MinIO: GET inbox/{uuid}.jpg
    Worker->>Worker: LPRPipeline.run(image)<br/>YOLO → crop → OCR
    loop For each plate
        Worker->>MinIO: PUT plates/{plate}/{uuid}.jpg
        Worker->>DB: INSERT recognition_logs
        Worker->>Qdrant: UPSERT 512d embedding
        Worker->>DB: SELECT vehicles + watchlists
        alt is BLACKLIST
            Worker->>Redis: PUBLISH alerts:blacklist
        end
    end
    Worker->>Redis: HSET job:{id} done
    Worker->>Redis: XACK

    loop Polling
        Client->>Backend: GET /recognition/jobs/{job_id}
        Backend-->>Client: {status, plates, owner, alert}
    end
```

### 10.2 RTSP stream realtime

Ingestor discover camera ACTIVE (re-check 30s), mở `cv2.VideoCapture(rtsp_url)`, chia 2 luồng:
- **Preview (10fps)** → `PUBLISH camera:stream:{id}` → client SUBSCRIBE qua `/streams/cameras/{id}` (MJPEG).
- **AI (2fps)** → `XADD recognition:queue` → worker xử lý.

Backpressure tự nhiên: queue đầy → ingestor drop frame, preview vẫn smooth.

### 10.3 BLACKLIST alert (SSE)

```mermaid
sequenceDiagram
    participant Worker
    participant Redis
    participant Backend
    participant Admin

    Admin->>Backend: GET /events/alerts (EventSource)
    Backend->>Redis: SUBSCRIBE alerts:blacklist
    Backend-->>Admin: SSE headers
    Note over Backend,Admin: heartbeat mỗi 15s

    Worker->>Redis: PUBLISH alerts:blacklist {plate, owner, image_url}
    Redis-->>Backend: message
    Backend-->>Admin: event: blacklist_match
    Admin->>Admin: toast + browser notification
```

---

## 11. Demo scenarios

> Giả định stack đã `up -d` xong và bạn có account admin.

### 11.1 Login

```bash
TOKEN=$(curl -sX POST http://localhost/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}' | jq -r .access_token)
```

PowerShell:
```powershell
$body = '{"username":"admin","password":"admin123"}'
$resp = Invoke-RestMethod -Method Post -Uri http://localhost/auth/login `
  -ContentType "application/json" -Body $body
$TOKEN = $resp.access_token
```

### 11.2 Upload ảnh & poll job

```bash
IMG=$(base64 -w 0 test.jpg)
JOB=$(curl -sX POST http://localhost/recognition/process \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"image_data\":\"$IMG\",\"camera_id\":1}" | jq -r .job_id)
sleep 1
curl -s http://localhost/recognition/jobs/$JOB -H "Authorization: Bearer $TOKEN" | jq
```

Response khi xong:
```json
{
  "job_id": "abc123...",
  "status": "done",
  "plates": [{
    "box": [120, 80, 280, 130],
    "text": "30A-12345",
    "conf_detect": 0.94,
    "owner": {
      "registered": true,
      "owner_name": "Nguyễn Văn An",
      "vehicle_type": "Ô tô con",
      "brand": "Toyota Camry",
      "color": "Trắng"
    },
    "watchlist": {"category": "BLACKLIST", "note": "Xe nợ phí gửi"},
    "alert": true
  }],
  "log_ids": [42],
  "process_time": 0.342
}
```

### 11.3 SSE BLACKLIST alert (admin)

```javascript
const es = new EventSource("/events/alerts");
es.addEventListener("blacklist_match", e => {
  console.log("ALERT:", JSON.parse(e.data));
});
```

### 11.4 MJPEG live preview

```html
<img src="http://localhost/streams/cameras/1" />
```

### 11.5 Bulk import

```bash
curl -X POST http://localhost/vehicles/bulk-import \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '[
    {"plate_number":"99A-111.11","owner_name":"Trần A","vehicle_type":"Ô tô"},
    {"plate_number":"99A-222.22","owner_name":"Lê B","vehicle_type":"Xe tải"}
  ]'
```

### 11.6 Vector similarity search

Tìm xe tương đồng với ảnh - hữu ích khi OCR sai nhưng vẫn nhìn rõ xe.

```bash
IMG=$(base64 -w 0 test.jpg)
curl -sX POST http://localhost/vehicles/similar \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"image_data\":\"$IMG\",\"detect\":true,\"top_k\":5}" | jq
```

Cách hoạt động: worker upsert vector 512d (ResNet18 pretrained ImageNet, fc=Identity, L2-norm) mỗi log → endpoint embed query rồi `qdrant.search()` Distance.COSINE → join `payload.plate_text` ngược về `vehicles` để trả owner.

---

## 12. Dữ liệu seed & test data

### 12.1 Bootstrap tài khoản admin

Sau `docker compose up` lần đầu, DB rỗng tài khoản. **User đăng ký đầu tiên auto-set role `ADMIN`** (first-admin bootstrap). Từ user thứ 2 trở đi `/auth/register` chỉ tạo role `USER`.

```bash
curl -X POST http://localhost/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}'
```

Endpoint không nhận field `role` → ngăn leo quyền sau khi đã có admin.

### 12.2 Vehicles (15 xe seed)

Trong `storage/db/init_db.sql`:
- `30A-12345` Toyota Camry trắng - Nguyễn Văn An
- `30G-999.88` Mercedes C200 đen - Hoàng Văn Khánh
- `92B-111.22` Ford Ranger cam - Đỗ Quốc Hùng
- … (xem file SQL)

### 12.3 Watchlist seed

| Plate | Category | Note |
|---|---|---|
| `30A-12345` | BLACKLIST | Xe nợ phí gửi tháng 11/2025 |
| `43A-234.56` | BLACKLIST | Báo cáo va chạm chưa giải quyết |
| `92B-111.22` | BLACKLIST | Xe bị báo mất tích 2026-01-15 |
| `30G-999.88` | WHITELIST | Xe VIP - Ban Giám đốc |
| `77C-555.66` | WHITELIST | Xe nội bộ phòng IT |

### 12.4 Test BLACKLIST alert end-to-end

1. Login admin → mở SSE listener (`GET /events/alerts`).
2. Gửi ảnh xe có biển `30A-12345` qua `/recognition/process`.
3. Đợi worker xử lý (~1-2s).
4. SSE listener nhận event `blacklist_match` với thông tin chủ xe + note.

---

## 13. Troubleshooting

### 13.1 Docker daemon not running
```
unable to connect to docker API at npipe:////./pipe/...
```
→ Khởi động Docker Desktop, đợi “Engine running”.

### 13.2 Port 80 bị chiếm
```yaml
nginx:
  ports:
    - "8080:80"
```
→ Truy cập <http://localhost:8080>.

### 13.3 Backend healthcheck fail
```bash
docker compose logs backend
```
- `ModuleNotFoundError: No module named 'app'` → kiểm tra `PYTHONPATH=/app` trong Dockerfile.
- `psycopg2 connection refused` → DB chưa healthy, đợi thêm.

### 13.4 Worker exit ngay sau start
- `cannot import name 'LPRPipeline'` → AI_Engine folder thiếu/sai cấu trúc.
- `FileNotFoundError: best_detector.pt` → quên `dvc pull` trước `docker build`.
- `redis.exceptions.ConnectionError` → Redis chưa ready.

### 13.5 `dvc pull` lỗi
- `ERROR: failed to pull data ... S3 NoSuchBucket` → MinIO chưa chạy hoặc `minio-setup` chưa tạo bucket `dvc-store`. Chạy `docker compose up -d minio minio-setup` trước.
- `403 Forbidden` → sai credential. Chạy lại `dvc remote modify --local minio access_key_id ...`.

### 13.6 MJPEG endpoint không trả frame
- Kiểm tra `docker compose logs stream-ingestor`.
- Camera phải có `rtsp_url` hợp lệ + status `ACTIVE`.
- RTSP yêu cầu auth: `rtsp://user:pass@host:port/path`.

### 13.7 SSE alert không nhận được
- `Content-Type` phải là `text/event-stream`.
- nginx config phải `proxy_buffering off` cho `/events/` (đã setup sẵn).
- EventSource không gửi custom header → token phải qua cookie/query.

### 13.8 Qdrant collection rỗng
Worker upsert mỗi log SUCCESS vào collection `plate_embeddings`. Nếu rỗng:
- Chưa có job SUCCESS nào → gửi vài ảnh qua `/recognition/process`.
- `GET /health/ai` trả mode `detect_only` hoặc `dead` → OCR/detect bị tắt → không có log SUCCESS.
- Check trực tiếp: `curl http://localhost:6333/collections/plate_embeddings`.

---

## 14. Phát triển

### 14.1 Folder structure

```
UET_AIT3004-2_OwnercheckAI/
├── AI_Engine/                  YOLO detect + PaddleOCR + ResNet18 embedder
│   ├── pipeline.py / pipeline_real.py   LPRPipeline E2E
│   ├── embedder.py                      ResNet18 → 512d
│   ├── schemas.py
│   ├── preprocess/{First,Last}          quality + crop + deskew + enhance
│   ├── modelLPdetector/
│   │   ├── src/                         trainYOLO.py · evalYOLO.py · modelYOLO.py · inferenceYOLO.py
│   │   ├── datasets/dataYOLO.yaml
│   │   └── models/best_detector.pt(.dvc)
│   ├── modelOCR/
│   │   ├── src/                         trainOCR.py · evalOCR.py · modelOCR.py · inferenceOCR.py
│   │   ├── configs/rec_config.yml
│   │   └── models/pretrained/rec_model/inference/*.dvc
│   └── requirements.txt
├── backend/
│   ├── Dockerfile (multi-stage, non-root)
│   ├── requirements.txt
│   ├── migrations/manual/*.sql
│   └── app/
│       ├── main.py · config.py · database.py · qdrant.py · queue.py · dependencies.py
│       ├── models/ · schemas/ · routers/
│       ├── worker/                      AI consumer
│       └── stream_ingestor/             RTSP reader
├── frontend/                   React + Vite SPA (Ant Design)
│   ├── Dockerfile · nginx.conf
│   └── src/{pages,components,api,context,hooks,layouts,routes}
├── storage/
│   ├── db/init_db.sql                  Schema + seed
│   ├── minio/setup_buckets.sh          Bucket bootstrap (plates, video-uploads, dvc-store, ...)
│   ├── mediamtx/mediamtx.yml           RTSP simulator config
│   ├── nginx/nginx.conf
│   └── test_videos/                    Mp4 mẫu
├── params.yaml                 ★ Hyperparams trung tâm
├── dvc.yaml                    ★ Pipeline stages (train + eval)
├── MODELS.md                   ★ Model registry + version history
├── metrics/                    ★ DVC-tracked metrics (detector.json, ocr.json)
├── .dvc/                       DVC metadata
├── *.dvc, **/*.dvc             DVC pointer files
├── docker-compose.yml
├── .env.example
└── README.md (file này)
```

### 14.2 Git workflow

- Branch chính: `main` (protected, chỉ merge qua PR).
- Feature: `feature/<short>`. Fix: `fix/<short>`.
- Commit theo Conventional Commits:
  ```
  feat(backend): add user CRUD
  fix(worker): handle empty plate text
  chore(model): bump detector to v1.1
  docs(readme): update DVC section
  ```
- Scope phổ biến: `backend`, `worker`, `stream`, `db`, `model`, `data`, `deps`, `docker`, `readme`.

### 14.3 Workflow đổi model

1. Sửa `params.yaml`.
2. `dvc repro` (DVC tự rerun stage bị ảnh hưởng).
3. `dvc metrics diff` để xem có cải thiện không.
4. Nếu OK → cập nhật `MODELS.md` (bump version row), `dvc push`, commit.

### 14.4 Thêm endpoint mới

1. Schema → `backend/app/schemas/<resource>.py`.
2. Endpoint → `backend/app/routers/<resource>.py`.
3. Dependency mới → `backend/app/dependencies.py`.
4. Mount router → `backend/app/main.py`.
5. Test qua `/docs`.
6. Cập nhật bảng [section 9.1](#91-tóm-tắt-endpoint).

### 14.5 Migration DB

Hiện không dùng Alembic. Thay đổi schema:
- **Dev**: `docker compose down -v && up --build` để recreate.
- **Prod**: viết SQL thủ công, áp dụng qua `psql`, lưu vào `backend/migrations/manual/000X_...sql`.

---

## 15. Đối chiếu rubric

| Tiêu chí | Max | Bằng chứng trong repo |
|---|---|---|
| **Chức năng** | 4 | E2E RTSP → detect → OCR → owner lookup → BLACKLIST alert (xem [section 10](#10-luồng-xử-lý-chi-tiết)) |
| **Đảm bảo yêu cầu** | 3 | Frontend user + admin ([frontend/](frontend/)), backend FastAPI, AI worker, **3 storage**: Postgres + MinIO + Qdrant, queue Redis Stream, load balancer nginx - đủ 7/7 component bắt buộc |
| **Tài liệu** | 2 | README này + [MODELS.md](MODELS.md) + Swagger `/docs` + sequence diagrams Mermaid |
| **Giao diện** | 1 | React SPA Ant Design - Login, Dashboard, LiveView, History, Lookup, CRUD admin |
| **Điểm cộng** | 1 | Xem 15.1 |

### 15.1 Điểm cộng đã thực hiện

- [x] **Cache đa lớp** - Redis `maxmemory 512mb / allkeys-lru` ([docker-compose.yml:178](docker-compose.yml#L178)) + React Query ở frontend + DB index trigram.
- [x] **Vector DB tích hợp** - ResNet18 → Qdrant upsert mỗi log + endpoint `/vehicles/similar`.
- [x] **Model & data pipeline versioning** - DVC + MinIO remote + `params.yaml` + `dvc.yaml` 4 stages + `MODELS.md` registry + `metrics/*.json` (xem [section 6](#6-quản-lý-phiên-bản-model--dữ-liệu)).
- [ ] CI/CD GitHub Actions.
- [ ] Kubernetes + Helm.
- [ ] Monitoring Prometheus + Grafana.
- [ ] Backup PG Back Web / Velero.
- [ ] Deploy Internet + SSL (Let's Encrypt).

---

## 16. Thành viên nhóm


| MSSV | Họ tên | Vai trò | GitHub |
|---|---|---|---|
| `24022276` | `Lê Mạnh Cường` | Backend / DevOps | `cuong897` |
| `24022376` | `Trần Tuấn Kiệt` | AI Engine + Model versioning | `Tuankiet261006` |
| `24022294` | `Nguyễn Minh Đức` | Frontend | `DucNguyen22-HP` |

### 16.1 Phân công

| Hạng mục | Thành viên |
|---|---|
| Backend API + auth + DB schema | `Lê Mạnh Cường` |
| Worker + stream ingestor + queue/SSE/MJPEG | `Lê Mạnh Cường` |
| Docker Compose + nginx + deployment | `Lê Mạnh Cường` |
| AI_Engine (YOLO detect + PaddleOCR + embedding) | `Trần Tuấn Kiệt` |
| DVC pipeline + params + MODELS.md | `Trần Tuấn Kiệt` |
| Frontend user (live + history) | `Nguyễn Minh Đức` |
| Frontend admin (CRUD + dashboard + alert) | `Nguyễn Minh Đức` |
| README + tài liệu | `Nguyễn Minh Đức` |

---

## Liên hệ

Issue trên GitHub repo, hoặc liên hệ trực tiếp thành viên nhóm.

## License

Sử dụng cho mục đích học tập theo quy định môn AIT3004-2 (UET).
