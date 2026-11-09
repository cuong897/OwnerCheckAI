MINIO_URL="http://minio:9000"
ALIAS="local"
MAX_RETRIES=30
RETRY_INTERVAL=2


log() { echo "[setup_buckets] $1"; }


log "⏳ Waiting for MinIO to be ready..."
attempt=0
until mc alias set "$ALIAS" "$MINIO_URL" "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" 2>/dev/null; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge "$MAX_RETRIES" ]; then
        log "❌ MinIO did not become ready after $MAX_RETRIES attempts. Exiting."
        exit 1
    fi
    log "   Attempt $attempt/$MAX_RETRIES — retrying in ${RETRY_INTERVAL}s..."
    sleep "$RETRY_INTERVAL"
done
log "✅ MinIO is ready."

create_bucket() {
    BUCKET="$1"
    if mc ls "$ALIAS/$BUCKET" >/dev/null 2>&1; then
        log "   Bucket '$BUCKET' already exists, skipping."
    else
        mc mb "$ALIAS/$BUCKET"
        log "   ✅ Bucket '$BUCKET' created."
    fi
}

log "📦 Creating buckets..."
create_bucket "evidence-images"   # Ảnh toàn cảnh bằng chứng nhận diện
create_bucket "plate-crops"       # Ảnh crop biển số
create_bucket "video-uploads"     # Video upload từ người dùng
create_bucket "dvc-store"         # DVC remote storage cho model weights & artifacts


mc anonymous set download "$ALIAS/evidence-images"
log "   ✅ evidence-images: public-read policy set."

# plate-crops: private (chỉ backend truy cập qua presigned URL)
mc anonymous set none "$ALIAS/plate-crops"
log "   ✅ plate-crops: private policy set."

# video-uploads: private
mc anonymous set none "$ALIAS/video-uploads"
log "   ✅ video-uploads: private policy set."

# dvc-store: private (model weights — chỉ DVC client/CI mới push/pull qua access key)
mc anonymous set none "$ALIAS/dvc-store"
log "   ✅ dvc-store: private policy set."

# --- Lifecycle: tự xóa object cũ hơn 90 ngày ---
# Giúp kiểm soát dung lượng storage tự động
log "🗓️  Setting lifecycle policies..."

cat > /tmp/lifecycle.json << 'EOF'
{
    "Rules": [
        {
            "ID": "expire-old-evidence",
            "Status": "Enabled",
            "Filter": {"Prefix": ""},
            "Expiration": {"Days": 90}
        }
    ]
}
EOF

mc ilm import "$ALIAS/evidence-images" < /tmp/lifecycle.json
mc ilm import "$ALIAS/plate-crops"     < /tmp/lifecycle.json
log "   ✅ Lifecycle policy (90 days) applied."

# Bucket "plates" (settings.MINIO_BUCKET trong app) — misses/ là frame gốc
# khi AI không detect được biển, lưu để user verify thủ công. Phình nhanh
# (~1.6 GB/h/cam) nên auto-expire sau 7 ngày. Plate crops ở prefix khác
# (plates/<PLATE>/...) không bị động.
if mc ls "$ALIAS/plates" >/dev/null 2>&1; then
    mc ilm rule add --expire-days 7  --prefix "misses/" "$ALIAS/plates" 2>/dev/null || true
    mc ilm rule add --expire-days 30 --prefix "plates/" "$ALIAS/plates" 2>/dev/null || true
    log "   ✅ plates/misses/: 7-day  expiry rule applied."
    log "   ✅ plates/plates/: 30-day expiry rule applied."
fi

# --- Tạo service account cho backend (KHÔNG dùng root credentials) ---
# Service account có quyền tối thiểu: chỉ read/write vào các bucket cụ thể
log "👤 Creating backend service account..."

# Kiểm tra xem service account đã tồn tại chưa
if mc admin user svcacct info "$ALIAS" "$MINIO_SERVICE_USER" >/dev/null 2>&1; then
    log "   Service account '$MINIO_SERVICE_USER' already exists, skipping."
else
    # Policy: chỉ cho phép r/w vào 3 buckets của hệ thống
    cat > /tmp/backend_policy.json << EOF
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "s3:GetObject",
                "s3:PutObject",
                "s3:DeleteObject",
                "s3:GetObjectAttributes"
            ],
            "Resource": [
                "arn:aws:s3:::evidence-images/*",
                "arn:aws:s3:::plate-crops/*",
                "arn:aws:s3:::video-uploads/*"
            ]
        },
        {
            "Effect": "Allow",
            "Action": ["s3:ListBucket"],
            "Resource": [
                "arn:aws:s3:::evidence-images",
                "arn:aws:s3:::plate-crops",
                "arn:aws:s3:::video-uploads"
            ]
        }
    ]
}
EOF

    mc admin user add "$ALIAS" "$MINIO_SERVICE_USER" "$MINIO_SERVICE_PASSWORD"
    mc admin policy create "$ALIAS" lpr-backend-policy /tmp/backend_policy.json
    mc admin policy attach "$ALIAS" lpr-backend-policy --user "$MINIO_SERVICE_USER"
    log "   ✅ Service account '$MINIO_SERVICE_USER' created with minimal permissions."
fi

log ""
log "🎉 MinIO setup completed successfully!"
log "   Buckets  : evidence-images, plate-crops, video-uploads"
log "   Service  : $MINIO_SERVICE_USER (use in backend, NOT root credentials)"
log "   Lifecycle: Objects auto-expire after 90 days"