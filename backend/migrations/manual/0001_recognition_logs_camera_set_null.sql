-- Migration 0001: recognition_logs.camera_id → ON DELETE SET NULL + nullable
--
-- Lý do: trước đây FK CASCADE + NOT NULL khiến (1) xoá camera tải toàn bộ
-- logs vào memory rồi xoá hàng loạt, (2) job pending trong queue trỏ tới
-- camera vừa xoá throw ForeignKeyViolation → worker SIGTERM. Đổi sang
-- SET NULL: log giữ lại lịch sử, camera_id NULL nếu camera bị xoá.
--
-- Tương đương với thay đổi trong:
--   - backend/app/models/recognition_log.py   (camera_id nullable, SET NULL)
--   - backend/app/models/camera.py            (passive_deletes=True)
--   - backend/app/schemas/recognition.py      (camera_id Optional)
--
-- Idempotent: dùng IF EXISTS / DO blocks để re-run an toàn.
-- Áp dụng:
--   docker exec -i lpr_postgres psql -U admin -d lpr_db \
--     < backend/migrations/manual/0001_recognition_logs_camera_set_null.sql

BEGIN;

-- 1) Drop FK cũ (CASCADE)
ALTER TABLE recognition_logs
    DROP CONSTRAINT IF EXISTS recognition_logs_camera_id_fkey;

-- 2) Cho phép NULL
ALTER TABLE recognition_logs
    ALTER COLUMN camera_id DROP NOT NULL;

-- 3) Thêm FK mới (SET NULL). NOT VALID + VALIDATE để tránh full table lock
--    dài trên bảng lớn — current state đã pass FK CASCADE cũ nên validate
--    sẽ thành công.
ALTER TABLE recognition_logs
    ADD CONSTRAINT recognition_logs_camera_id_fkey
    FOREIGN KEY (camera_id) REFERENCES cameras(id) ON DELETE SET NULL
    NOT VALID;

ALTER TABLE recognition_logs
    VALIDATE CONSTRAINT recognition_logs_camera_id_fkey;

COMMIT;
