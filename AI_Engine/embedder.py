"""
PlateEmbedder — sinh vector 512d cho crop biển số bằng ResNet18 pretrained
ImageNet (torchvision). Vector đã L2-normalize sẵn → đẩy thẳng vào Qdrant
với Distance.COSINE.

Vì sao chọn ResNet18:
  • 512d native (sau avgpool, fc=Identity) → khớp đúng VECTOR_SIZE=512 trong
    app/qdrant.py, không phải migrate collection.
  • Nhẹ (~45MB weight, ~11M params), inference CPU < 50ms / crop.
  • Pretrained ImageNet đủ tốt cho zero-shot similarity của crop biển số
    (hình dạng + tỉ lệ + texture nền). Không cần fine-tune cho demo.

Lazy singleton — model chỉ load lần đầu gọi (tiết kiệm RAM cho worker chưa
xử lý job nào).
"""

from __future__ import annotations

import logging
import threading
from typing import List, Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)

EMBED_DIM = 512

_lock = threading.Lock()
_model = None
_device = None
_preprocess = None


def _load():
    global _model, _device, _preprocess
    if _model is not None:
        return _model

    with _lock:
        if _model is not None:
            return _model

        import torch
        import torch.nn as nn
        from torchvision import models, transforms

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        try:
            weights = models.ResNet18_Weights.IMAGENET1K_V1
            model = models.resnet18(weights=weights)
        except Exception:
            model = models.resnet18(weights=None)
            logger.warning("ResNet18 pretrained weights unavailable — sử dụng init ngẫu nhiên.")
        model.fc = nn.Identity()
        model.eval().to(device)

        _model = model
        _device = device
        _preprocess = transforms.Compose([
            transforms.ToPILImage(),
            transforms.Resize((128, 256)),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406],
                                 std=[0.229, 0.224, 0.225]),
        ])
        logger.info("PlateEmbedder ready — ResNet18 (dim=%d) on %s", EMBED_DIM, device)
        return _model


def embed_crop(crop_bgr: np.ndarray) -> Optional[List[float]]:
    """
    crop_bgr: BGR ndarray (cv2 format). Trả về list[float] 512d đã L2-normalize,
    hoặc None nếu input không hợp lệ / embed lỗi.
    """
    if crop_bgr is None:
        return None
    if not isinstance(crop_bgr, np.ndarray) or crop_bgr.size == 0:
        return None
    if crop_bgr.ndim != 3 or crop_bgr.shape[2] != 3:
        return None

    try:
        import torch

        model = _load()
        rgb = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB)
        with torch.no_grad():
            x = _preprocess(rgb).unsqueeze(0).to(_device)
            feat = model(x).cpu().numpy()[0]
        norm = float(np.linalg.norm(feat))
        if norm == 0.0 or not np.isfinite(norm):
            return None
        feat = feat / norm
        return feat.astype(np.float32).tolist()
    except Exception as exc:
        logger.warning("embed_crop failed: %s", exc)
        return None


def embed_jpeg_bytes(jpeg_bytes: bytes) -> Optional[List[float]]:
    """Decode JPEG bytes → embed_crop()."""
    if not jpeg_bytes:
        return None
    try:
        arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        return embed_crop(img)
    except Exception as exc:
        logger.warning("embed_jpeg_bytes decode failed: %s", exc)
        return None
