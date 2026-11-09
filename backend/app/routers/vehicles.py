"""
Router: /vehicles
  GET    /vehicles              — danh sách vehicles (tìm theo biển số)
  POST   /vehicles              — thêm vehicle mới     [ADMIN]
  POST   /vehicles/similar      — tìm xe tương đồng qua Qdrant vector search
  GET    /vehicles/{plate}      — chi tiết vehicle
  PATCH  /vehicles/{plate}      — cập nhật vehicle      [ADMIN]
  DELETE /vehicles/{plate}      — xoá vehicle           [ADMIN]
"""

import base64
import logging
import os
import threading
from typing import List, Optional

import cv2
import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.vehicle import Vehicle
from app.qdrant import search_similar as qdrant_search
from app.schemas.vehicle import (
    VehicleCreate,
    VehicleUpdate,
    VehicleResponse,
    BulkImportResponse,
    BulkImportSkipped,
    SimilarSearchRequest,
    SimilarSearchResponse,
    SimilarDetection,
    SimilarMatch,
    SimilarOwnerInfo,
)
from app.dependencies import get_current_user, require_admin
from app.models.user import User
from app.utils.plate import normalize_plate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/vehicles", tags=["Vehicles"])


def _find_vehicle(db: Session, plate_input: str) -> Optional[Vehicle]:
    """Lookup vehicle theo cả 2 form: normalized (cho biển dân sự đã chuẩn hoá)
    và raw upper-stripped (cho biển ngoại giao / quân sự / legacy data chưa qua
    normalize). Trả về match đầu tiên.

    Lý do: normalize_plate() được thiết kế cho format dân sự 'XX[A-Z]-XXX.XX',
    nó phá format của biển 'NN-XX NNN.NN' (ngoại giao). Hậu quả là khi admin
    bấm DELETE qua UI, normalize biến 'NN-XX NNN.NN' thành 'NNXX-NNN.NN' →
    không match row đã lưu raw.
    """
    raw = (plate_input or "").strip().upper()
    normalized = normalize_plate(plate_input)
    candidates = {raw, normalized} - {""}
    if not candidates:
        return None
    return (
        db.query(Vehicle)
        .filter(Vehicle.plate_number.in_(candidates))
        .first()
    )


# ── Lazy singletons cho similarity search ──────────────────────────────────
# Detector: YOLO chỉ (không kéo PaddleOCR — backend chỉ cần crop, không OCR).
# Embedder: ResNet18 dùng chung với worker (AI_Engine.embedder).
_det_lock = threading.Lock()
_detector = None


def _get_detector():
    global _detector
    if _detector is not None:
        return _detector
    with _det_lock:
        if _detector is not None:
            return _detector
        from AI_Engine.modelLPdetector.src.modelYOLO import YOLODetector
        path = os.getenv(
            "AI_DETECTOR_PATH",
            "/app/AI_Engine/modelLPdetector/models/best_detector.pt",
        )
        conf = float(os.getenv("AI_DET_CONF", "0.5"))
        _detector = YOLODetector(model_path=path, conf_threshold=conf)
        logger.info("Vehicles router: YOLODetector loaded from %s", path)
        return _detector


@router.get("", response_model=List[VehicleResponse], summary="Danh sách vehicles")
def list_vehicles(
    plate_number: Optional[str] = Query(None, description="Tìm kiếm biển số (LIKE)"),
    owner_name: Optional[str] = Query(None, description="Tìm theo tên chủ xe (LIKE)"),
    vehicle_type: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    q = db.query(Vehicle)
    if plate_number:
        q = q.filter(Vehicle.plate_number.ilike(f"%{plate_number}%"))
    if owner_name:
        q = q.filter(Vehicle.owner_name.ilike(f"%{owner_name}%"))
    if vehicle_type:
        q = q.filter(Vehicle.vehicle_type == vehicle_type)
    return q.offset(offset).limit(limit).all()


@router.post(
    "",
    response_model=VehicleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Thêm vehicle mới [ADMIN]",
)
def create_vehicle(
    body: VehicleCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    # Chuẩn hoá để khớp format worker dùng — lookup BLACKLIST / enrichment sẽ match
    plate = normalize_plate(body.plate_number)
    if not plate:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="plate_number rỗng sau khi chuẩn hoá.",
        )
    if db.query(Vehicle).filter(Vehicle.plate_number == plate).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Biển số '{plate}' đã tồn tại trong hệ thống.",
        )
    vehicle = Vehicle(**{**body.model_dump(), "plate_number": plate})
    db.add(vehicle)
    db.commit()
    db.refresh(vehicle)
    return vehicle


@router.post(
    "/bulk-import",
    response_model=BulkImportResponse,
    status_code=status.HTTP_200_OK,
    summary="Import nhiều vehicle cùng lúc [ADMIN]",
)
def bulk_import_vehicles(
    body: List[VehicleCreate],
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """
    Import nhiều vehicle trong 1 request. Duplicate sẽ bị skip (không lỗi toàn batch).

    Body: JSON array, ví dụ:
      [
        {"plate_number": "30A-12345", "owner_name": "...", "vehicle_type": "..."},
        ...
      ]

    Giới hạn 1000 entry/request để tránh timeout.
    """
    if len(body) == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Body rỗng.",
        )
    if len(body) > 1000:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Tối đa 1000 entry/request, nhận được {len(body)}.",
        )

    incoming_plates = [normalize_plate(e.plate_number) for e in body]
    existing = {
        row[0]
        for row in db.query(Vehicle.plate_number)
        .filter(Vehicle.plate_number.in_(incoming_plates))
        .all()
    }

    imported = 0
    skipped: List[BulkImportSkipped] = []
    seen_in_batch = set()

    for entry in body:
        plate = normalize_plate(entry.plate_number)
        if not plate:
            skipped.append(BulkImportSkipped(plate_number=entry.plate_number, reason="plate_number rỗng / không hợp lệ"))
            continue

        if plate in seen_in_batch:
            skipped.append(BulkImportSkipped(plate_number=plate, reason="trùng trong batch"))
            continue
        seen_in_batch.add(plate)

        if plate in existing:
            skipped.append(BulkImportSkipped(plate_number=plate, reason="đã tồn tại trong DB"))
            continue

        db.add(Vehicle(**{**entry.model_dump(), "plate_number": plate}))
        imported += 1

    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"DB error khi commit batch: {exc}",
        )

    return BulkImportResponse(imported=imported, skipped=skipped, total=len(body))


# ─────────────────────────────────────────────────────────────────────────────
# POST /vehicles/similar — vector search trên Qdrant
# ─────────────────────────────────────────────────────────────────────────────
# Luồng:
#   1. Decode base64 → ndarray (BGR).
#   2. Nếu detect=True: YOLO → list crops; nếu False: treat input như 1 crop.
#   3. Mỗi crop → embed (ResNet18 512d, L2-normalized) → qdrant.search().
#   4. Join hit.plate_text với bảng vehicles → enrich owner info.
#
# Lưu ý:
#   • Qdrant payload được worker đẩy lên gồm plate_text + camera_id + timestamp.
#     Vì payload đã có plate_text, owner lookup chỉ là 1 truy vấn SQL IN().
#   • Score là cosine similarity (1.0 = identical). Dữ liệu demo nhỏ nên
#     score_threshold mặc định = None (trả top_k). Production nên đặt ~0.85.

@router.post(
    "/similar",
    response_model=SimilarSearchResponse,
    summary="Tìm xe tương đồng trong logs cũ (vector search Qdrant)",
)
def search_similar_vehicles(
    body: SimilarSearchRequest,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """
    Sinh embedding 512d cho crop biển số trong ảnh đầu vào, tìm top-K crop
    tương đồng nhất trong Qdrant (đã upsert từ các log nhận diện trước đây),
    rồi join với bảng `vehicles` để trả về owner info.

    Trường hợp dùng:
      • Crop biển mờ không OCR được → tìm xem hệ thống đã từng thấy crop tương
        tự chưa, lấy plate_text từ lần đó.
      • Tìm tất cả lần xe X đã đi qua các camera (audit trail).
    """
    from AI_Engine.embedder import embed_crop

    # 1. Decode base64
    try:
        img_bytes = base64.b64decode(body.image_data, validate=True)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="image_data không phải base64 hợp lệ.",
        )
    arr = np.frombuffer(img_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Không decode được ảnh (định dạng không hỗ trợ?).",
        )

    note: Optional[str] = None
    crops: list[tuple[Optional[list[int]], Optional[float], np.ndarray]] = []

    if body.detect:
        try:
            detections = _get_detector().predict(img)
        except Exception as exc:
            logger.exception("Detector failed: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Detector lỗi: {exc}",
            )
        for det in detections:
            bbox = det.get("bbox")
            if bbox is None:
                continue
            x1, y1, x2, y2 = [int(v) for v in bbox]
            h, w = img.shape[:2]
            x1, x2 = max(0, min(x1, x2)), min(w, max(x1, x2))
            y1, y2 = max(0, min(y1, y2)), min(h, max(y1, y2))
            if x2 - x1 < 2 or y2 - y1 < 2:
                continue
            crops.append(([x1, y1, x2, y2], float(det.get("conf", 0.0)),
                          img[y1:y2, x1:x2]))
        if not crops:
            note = "Detector không tìm thấy biển số trong ảnh — fallback embed ảnh đầu vào trực tiếp."
            crops.append((None, None, img))
    else:
        crops.append((None, None, img))

    # 2. Embed + search Qdrant
    detections_out: list[SimilarDetection] = []
    total = 0
    for box, conf, crop in crops:
        vec = embed_crop(crop)
        if vec is None:
            detections_out.append(SimilarDetection(box=box, conf_detect=conf, matches=[]))
            continue
        try:
            hits = qdrant_search(
                vec,
                top_k=body.top_k,
                score_threshold=body.score_threshold,
            )
        except Exception as exc:
            logger.exception("Qdrant search failed: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Qdrant search lỗi: {exc}",
            )

        # 3. Enrich owner info: 1 query IN() cho toàn bộ plate trong hits
        plates_in_hits = list({h["plate_text"] for h in hits if h.get("plate_text")})
        owner_map: dict[str, Vehicle] = {}
        if plates_in_hits:
            rows = db.query(Vehicle).filter(Vehicle.plate_number.in_(plates_in_hits)).all()
            owner_map = {v.plate_number: v for v in rows}

        matches: list[SimilarMatch] = []
        for h in hits:
            plate = h.get("plate_text")
            v = owner_map.get(plate) if plate else None
            owner = (
                SimilarOwnerInfo(
                    registered=True,
                    owner_name=v.owner_name,
                    vehicle_type=v.vehicle_type,
                    brand=v.brand,
                    color=v.color,
                )
                if v
                else SimilarOwnerInfo(registered=False)
            )
            matches.append(SimilarMatch(
                log_id=int(h["log_id"]),
                score=float(h["score"]),
                plate_text=plate,
                camera_id=h.get("camera_id"),
                timestamp=h.get("timestamp"),
                owner=owner,
            ))
        total += len(matches)
        detections_out.append(SimilarDetection(box=box, conf_detect=conf, matches=matches))

    return SimilarSearchResponse(
        detections=detections_out,
        total_matches=total,
        note=note,
    )


@router.get(
    "/{plate_number}",
    response_model=VehicleResponse,
    summary="Chi tiết vehicle",
)
def get_vehicle(
    plate_number: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    vehicle = _find_vehicle(db, plate_number)
    if not vehicle:
        raise HTTPException(status_code=404, detail=f"Biển số '{plate_number}' không tồn tại.")
    return vehicle


@router.patch(
    "/{plate_number}",
    response_model=VehicleResponse,
    summary="Cập nhật vehicle [ADMIN]",
)
def update_vehicle(
    plate_number: str,
    body: VehicleUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    vehicle = _find_vehicle(db, plate_number)
    if not vehicle:
        raise HTTPException(status_code=404, detail=f"Biển số '{plate_number}' không tồn tại.")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(vehicle, field, value)
    db.commit()
    db.refresh(vehicle)
    return vehicle


@router.delete(
    "/{plate_number}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Xoá vehicle [ADMIN]",
)
def delete_vehicle(
    plate_number: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    from app.models.watchlist import Watchlist

    vehicle = _find_vehicle(db, plate_number)
    if not vehicle:
        raise HTTPException(status_code=404, detail=f"Biển số '{plate_number}' không tồn tại.")

    # FK watchlists.plate_number → vehicles.plate_number ON DELETE RESTRICT ở DB
    # ⇒ phải clear watchlist entries trong cùng transaction trước khi xoá vehicle.
    # Cascade-in-code để admin chỉ cần 1 thao tác (UX), không phải vào page watchlist
    # xoá tay rồi quay lại. Recognition_logs.plate_text chỉ là VARCHAR không có FK
    # nên log lịch sử vẫn được giữ lại — chỉ owner enrichment lookup sẽ trả "chưa
    # đăng ký" sau khi xoá.
    db.query(Watchlist).filter(Watchlist.plate_number == vehicle.plate_number).delete(
        synchronize_session=False
    )
    db.delete(vehicle)
    db.commit()