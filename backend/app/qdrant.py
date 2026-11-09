"""
Qdrant client singleton — vector store cho plate embeddings 512d.

Collection: plate_embeddings
  - id      : log_id từ PostgreSQL (int)
  - vector  : list[float] 512 chiều từ AI Engine
  - payload : plate_text, camera_id, timestamp

Dùng cho similarity search: tìm biển số tương đồng khi OCR confidence thấp.
"""

import logging
from typing import Optional

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct

from app.config import settings

logger = logging.getLogger(__name__)

COLLECTION = "plate_embeddings"
VECTOR_SIZE = 512

_client: Optional[QdrantClient] = None


def get_qdrant() -> QdrantClient:
    global _client
    if _client is None:
        _client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)
        logger.info("Qdrant client connected to %s:%s", settings.QDRANT_HOST, settings.QDRANT_PORT)
    return _client


def init_qdrant() -> None:
    """Tạo collection nếu chưa tồn tại — gọi một lần lúc startup."""
    client = get_qdrant()
    existing = {c.name for c in client.get_collections().collections}
    if COLLECTION not in existing:
        client.create_collection(
            collection_name=COLLECTION,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )
        logger.info("Qdrant: collection '%s' created.", COLLECTION)
    else:
        logger.info("Qdrant: collection '%s' already exists.", COLLECTION)


def upsert_embedding(log_id: int, embedding: list, plate_text: str, camera_id: int, timestamp: str) -> None:
    """
    Lưu embedding của một biển số vào Qdrant.
    Dùng log_id từ PostgreSQL làm point id để có thể join ngược lại.
    """
    try:
        get_qdrant().upsert(
            collection_name=COLLECTION,
            points=[
                PointStruct(
                    id=log_id,
                    vector=embedding,
                    payload={
                        "plate_text": plate_text,
                        "camera_id": camera_id,
                        "timestamp": timestamp,
                    },
                )
            ],
        )
    except Exception as exc:
        # Không raise — mất embedding không được làm hỏng luồng lưu log chính
        logger.warning("Qdrant upsert failed for log_id=%s: %s", log_id, exc)


def search_similar(
    embedding: list,
    top_k: int = 5,
    score_threshold: Optional[float] = None,
) -> list:
    """
    Tìm các crop biển số tương đồng. Trả về:
        [{"log_id": int, "score": float, "plate_text": str,
          "camera_id": int, "timestamp": str}, ...]

    score_threshold=None → trả về top_k mà không lọc (hữu ích khi demo trên
    DB nhỏ; tăng dần threshold khi DB lớn để tránh false positive).
    """
    kwargs = dict(
        collection_name=COLLECTION,
        query_vector=embedding,
        limit=top_k,
    )
    if score_threshold is not None:
        kwargs["score_threshold"] = score_threshold

    results = get_qdrant().search(**kwargs)
    return [
        {
            "log_id": r.id,
            "score": float(r.score),
            **(r.payload or {}),
        }
        for r in results
    ]