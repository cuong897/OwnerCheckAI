import cv2
import numpy as np
from typing import List, Tuple, Union, Optional

class PlateCropper:
    """
    Chuyên trách việc trích xuất vùng biển số từ ảnh gốc dựa trên kết quả của YOLO.
    """
    
    def __init__(self, padding_ratio: float = 0.05):
        """
        Args:
            padding_ratio: Tỷ lệ phần trăm mở rộng vùng cắt (mặc định 5%).
        """
        self.padding_ratio = padding_ratio

    def crop(self, image: np.ndarray, bbox: Union[List[float], np.ndarray]) -> Optional[np.ndarray]:
        """
        Thực hiện cắt ảnh với padding và kiểm tra biên.
        
        Args:
            image: Ảnh gốc (BGR).
            bbox: List/Array tọa độ [x1, y1, x2, y2].
            
        Returns:
            cropped_plate: Ảnh vùng biển số đã được cắt, hoặc None nếu lỗi.
        """
        if image is None or len(bbox) != 4:
            return None

        h_img, w_img = image.shape[:2]
        x1, y1, x2, y2 = bbox

        # 1. Tính toán độ rộng và cao của box
        box_w = x2 - x1
        box_h = y2 - y1

        # 2. Tính toán lượng padding cần thêm (Dựa trên tỷ lệ)
        pad_w = box_w * self.padding_ratio
        pad_h = box_h * self.padding_ratio

        # 3. Mở rộng tọa độ với padding
        x1_pad = int(x1 - pad_w)
        y1_pad = int(y1 - pad_h)
        x2_pad = int(x2 + pad_w)
        y2_pad = int(y2 + pad_h)

        # 4. Boundary Check (Quan trọng: Không để tọa độ vượt quá khung ảnh gốc)
        x1_final = max(0, x1_pad)
        y1_final = max(0, y1_pad)
        x2_final = min(w_img, x2_pad)
        y2_final = min(h_img, y2_pad)

        # 5. Thực hiện cắt
        cropped_plate = image[y1_final:y2_final, x1_final:x2_final]

        # Kiểm tra xem vùng cắt có hợp lệ không (tránh ảnh rỗng)
        if cropped_plate.size == 0:
            return None

        return cropped_plate

    def get_multiple_crops(self, image: np.ndarray, bboxes: List[List[float]]) -> List[np.ndarray]:
        """Hỗ trợ trường hợp 1 ảnh có nhiều biển số xe"""
        crops = []
        for box in bboxes:
            plate = self.crop(image, box)
            if plate is not None:
                crops.append(plate)
        return crops