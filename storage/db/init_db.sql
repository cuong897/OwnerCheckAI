CREATE EXTENSION IF NOT EXISTS pg_trgm;  

-- 1. USERS — Quản lý tài khoản
-- Tên cột + role enum phải khớp với SQLAlchemy model (backend/app/models/user.py)
CREATE TABLE users (
    id              SERIAL PRIMARY KEY,
    username        VARCHAR(50)  UNIQUE NOT NULL,
    hashed_password VARCHAR(255) NOT NULL,           -- khớp với User.hashed_password
    full_name       VARCHAR(100),
    role            VARCHAR(20)  NOT NULL DEFAULT 'USER',
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
    last_login_at   TIMESTAMPTZ,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_role CHECK (role IN ('ADMIN', 'USER'))
);

-- 2. REFRESH TOKENS — Quản lý JWT sessions
--   - Cho phép logout (revoke token cụ thể)
--   - Cho phép "Đăng xuất tất cả thiết bị"
--   - Phát hiện token bị đánh cắp (rotation)
CREATE TABLE refresh_tokens (
    id           BIGSERIAL PRIMARY KEY,
    user_id      INT          NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash   VARCHAR(64)  UNIQUE NOT NULL,  -- SHA-256 của token thô
    device_info  VARCHAR(255),                  -- User-Agent / tên thiết bị
    ip_address   INET,
    expires_at   TIMESTAMPTZ  NOT NULL,
    revoked_at   TIMESTAMPTZ,                   -- NULL = còn hiệu lực
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_refresh_tokens_user_id ON refresh_tokens(user_id);
CREATE INDEX idx_refresh_tokens_expires ON refresh_tokens(expires_at)
    WHERE revoked_at IS NULL;   

-- 3. CAMERAS — Quản lý camera
CREATE TABLE cameras (
    id           SERIAL PRIMARY KEY,
    camera_name  VARCHAR(100) NOT NULL,
    location     VARCHAR(255),
    rtsp_url     VARCHAR(500),           -- URL stream RTSP (mã hóa nếu cần)
    status       VARCHAR(20)  NOT NULL DEFAULT 'ACTIVE',
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_camera_status CHECK (status IN ('ACTIVE', 'INACTIVE'))
);

-- 4. VEHICLES — Danh sách phương tiện & chủ xe
CREATE TABLE vehicles (
    plate_number VARCHAR(20)  PRIMARY KEY,
    owner_name   VARCHAR(100) NOT NULL,
    owner_cccd   VARCHAR(20),
    vehicle_type VARCHAR(50),
    brand        VARCHAR(50),
    color        VARCHAR(20),
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Index tìm kiếm chủ xe theo tên
CREATE INDEX idx_vehicles_owner_name ON vehicles(owner_name);

-- 5. WATCHLISTS — Danh sách đen/trắng
CREATE TABLE watchlists (
    id           SERIAL PRIMARY KEY,
    plate_number VARCHAR(20)  NOT NULL,
    category     VARCHAR(20)  NOT NULL,
    owner_name   VARCHAR(100),
    note         TEXT,
    created_by   INT          REFERENCES users(id) ON DELETE SET NULL,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT fk_watchlist_plate
        FOREIGN KEY (plate_number) REFERENCES vehicles(plate_number)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT chk_watchlist_category CHECK (category IN ('BLACKLIST', 'WHITELIST'))
);

-- Index tra cứu nhanh khi nhận diện biển số
CREATE UNIQUE INDEX idx_watchlists_plate ON watchlists(plate_number);
-- Partial index: chỉ BLACKLIST (hay query nhất)
CREATE INDEX idx_watchlists_blacklist ON watchlists(plate_number)
    WHERE category = 'BLACKLIST';

-- 6. RECOGNITION LOGS — Log nhận diện chính

CREATE TABLE recognition_logs (
    id                   BIGSERIAL    PRIMARY KEY, 
    camera_id            INT          REFERENCES cameras(id) ON DELETE SET NULL,
    plate_text           VARCHAR(20),
    ocr_confidence       FLOAT,
    image_url            VARCHAR(500),
    status               VARCHAR(20)  NOT NULL DEFAULT 'PENDING',
    retry_count          INT          NOT NULL DEFAULT 0,
    -- Xác nhận thủ công
    is_manual_verified   BOOLEAN      NOT NULL DEFAULT FALSE,
    verified_plate_text  VARCHAR(20),
    verified_by          INT          REFERENCES users(id) ON DELETE SET NULL,
    verified_at          TIMESTAMPTZ,
    -- Metadata
    timestamp            TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    processing_ms        INT,
    CONSTRAINT chk_log_status
        CHECK (status IN ('PENDING', 'SUCCESS', 'FAILED', 'RETRY'))
);

-- Indexes cho các query phổ biến
CREATE INDEX idx_recognition_timestamp
    ON recognition_logs(timestamp DESC);            

CREATE INDEX idx_recognition_camera_time
    ON recognition_logs(camera_id, timestamp DESC); 

CREATE INDEX idx_recognition_plate_text
    ON recognition_logs(plate_text);              

-- Partial index: chỉ các record chưa xác minh (PENDING) — ít record hơn
CREATE INDEX idx_recognition_unverified
    ON recognition_logs(timestamp DESC)
    WHERE is_manual_verified = FALSE AND status = 'SUCCESS';

-- Tìm kiếm biển số gần đúng (ví dụ: '51A123' vs '51A-123')
CREATE INDEX idx_recognition_plate_trgm
    ON recognition_logs USING gin(plate_text gin_trgm_ops);

-- 7. SYSTEM LOGS — Audit trail
CREATE TABLE system_logs (
    id           BIGSERIAL    PRIMARY KEY,
    user_id      INT          REFERENCES users(id) ON DELETE SET NULL,
    action       VARCHAR(100) NOT NULL,
    target_table VARCHAR(50),
    target_id    VARCHAR(50),
    detail       JSONB,                    -- JSONB thay TEXT: có thể query vào detail
    ip_address   INET,                     -- Lưu IP để audit
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_system_logs_user_id   ON system_logs(user_id);
CREATE INDEX idx_system_logs_action    ON system_logs(action);
CREATE INDEX idx_system_logs_created   ON system_logs(created_at DESC);
-- Index vào JSONB detail nếu hay query
CREATE INDEX idx_system_logs_detail    ON system_logs USING gin(detail);

-- 8. SEED DATA — Không seed admin sẵn nữa.
-- Sau khi `docker compose up`, đăng ký admin qua endpoint /auth/register.
-- User đầu tiên hệ thống được tự động cấp role ADMIN (first-admin bootstrap),
-- các lần register sau luôn là USER — muốn tạo admin tiếp phải qua POST /users.
--   curl -X POST http://localhost/auth/register \
--     -H "Content-Type: application/json" \
--     -d '{"username":"admin","password":"admin123"}'
-- (Backend tự hash bcrypt khi register.)

-- ============================================================
-- 9. SEED DEMO: Vehicles + Watchlists để giảng viên test ngay
-- ============================================================
-- Nếu deploy thật, xóa block dưới hoặc đặt sau biến môi trường SEED_DEMO=1.

INSERT INTO vehicles (plate_number, owner_name, owner_cccd, vehicle_type, brand, color) VALUES
    ('30A-12345', 'Nguyễn Văn An',    '001094012345', 'Ô tô con',   'Toyota Camry',     'Trắng'),
    ('30E-67890', 'Trần Thị Bình',    '001097067890', 'Ô tô con',   'Honda Civic',      'Đen'),
    ('29H-456.78','Lê Hoàng Cường',   '001088045678', 'SUV',        'Mazda CX-5',       'Bạc'),
    ('51F-789.01','Phạm Minh Đức',    '079089078901', 'Ô tô con',   'Hyundai Accent',   'Đỏ'),
    ('43A-234.56','Vũ Thị Hà',        '048090023456', 'Xe tải',     'Hyundai HD120',    'Xanh'),
    ('92B-111.22','Đỗ Quốc Hùng',     '049085011122', 'Ô tô con',   'Ford Ranger',      'Cam'),
    ('77C-555.66','Bùi Thanh Hương',  '060092055566', 'SUV',        'Kia Sorento',      'Trắng'),
    ('30G-999.88','Hoàng Văn Khánh',  '001083099988', 'Ô tô con',   'Mercedes C200',    'Đen'),
    ('14A-321.45','Mai Thị Lan',      '022091032145', 'Ô tô con',   'VinFast Lux A',    'Trắng ngọc trai'),
    ('72H-654.32','Phan Đức Minh',    '074087065432', 'Xe tải',     'Isuzu N-Series',   'Vàng'),
    ('60B-876.54','Nguyễn Thị Ngọc',  '075090087654', 'Ô tô con',   'Toyota Vios',      'Bạc'),
    ('15C-432.10','Lý Quốc Phong',    '031088043210', 'SUV',        'Honda CR-V',       'Đen'),
    ('38D-765.43','Trịnh Văn Quân',   '042086076543', 'Ô tô con',   'Mazda 3',          'Xanh dương'),
    ('86E-109.87','Đặng Thị Sương',   '083091010987', 'Ô tô con',   'Toyota Innova',    'Ghi'),
    ('99F-543.21','Hồ Minh Tâm',      '027089054321', 'Xe bán tải', 'Mitsubishi Triton','Trắng');

-- Watchlist demo:
--   3 BLACKLIST (cảnh báo) + 2 WHITELIST (cho phép tự do)
INSERT INTO watchlists (plate_number, category, owner_name, note) VALUES
    ('30A-12345', 'BLACKLIST', 'Nguyễn Văn An',   'Xe nợ phí gửi tháng 11/2025'),
    ('43A-234.56','BLACKLIST', 'Vũ Thị Hà',       'Báo cáo va chạm chưa giải quyết'),
    ('92B-111.22','BLACKLIST', 'Đỗ Quốc Hùng',    'Xe bị báo mất tích từ 2026-01-15'),
    ('30G-999.88','WHITELIST', 'Hoàng Văn Khánh', 'Xe VIP — Ban Giám đốc, không kiểm tra'),
    ('77C-555.66','WHITELIST', 'Bùi Thanh Hương', 'Xe nội bộ phòng IT');