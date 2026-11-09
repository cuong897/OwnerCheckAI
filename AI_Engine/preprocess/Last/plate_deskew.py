import cv2
import numpy as np
from typing import Optional, List

class PlateDeskewer:
    """
    Chuyên trách việc nắn thẳng biển số bị nghiêng (Perspective Transform).
    Giúp đưa biển số về dạng hình chữ nhật phẳng để OCR đọc chính xác nhất.
    """

    def __init__(self, target_width: int = 470, target_height: int = 110):
        # Kích thước chuẩn cho biển số dài Việt Nam (tỷ lệ ~4.27)
        self.target_width = target_width
        self.target_height = target_height

    def _order_points(self, pts: np.ndarray) -> np.ndarray:
        """
        Sắp xếp 4 tọa độ theo thứ tự: Trên-Trái, Trên-Phải, Dưới-Phải, Dưới-Trái.
        """
        rect = np.zeros((4, 2), dtype="float32")

        # Trên-Trái có tổng (x + y) nhỏ nhất, Dưới-Phải có tổng lớn nhất
        s = pts.sum(axis=1)
        rect[0] = pts[np.argmin(s)]
        rect[2] = pts[np.argmax(s)]

        # Trên-Phải có hiệu (y - x) nhỏ nhất (hoặc x-y lớn nhất), 
        # Dưới-Trái có hiệu lớn nhất
        diff = np.diff(pts, axis=1)
        rect[1] = pts[np.argmin(diff)]
        rect[3] = pts[np.argmax(diff)]

        return rect

    def find_plate_contour(self, image: np.ndarray) -> Optional[np.ndarray]:
        """
        Tìm 4 góc của biển số dựa trên đường viền lớn nhất.
        """
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        # Sử dụng Canny hoặc Threshold để tìm cạnh
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edged = cv2.Canny(blurred, 50, 200)

        # Tìm các đường viền
        contours, _ = cv2.findContours(edged.copy(), cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        contours = sorted(contours, key=cv2.contourArea, reverse=True)[:5]

        for c in contours:
            # Xấp xỉ đường viền thành đa giác
            peri = cv2.arcLength(c, True)
            approx = cv2.approxPolyDP(c, 0.02 * peri, True)

            # Nếu đa giác có 4 điểm, giả định đó là biển số
            if len(approx) == 4:
                return approx.reshape(4, 2)
        
        return None

    def deskew(self, image: np.ndarray) -> np.ndarray:
        """
        Thực hiện nắn thẳng ảnh.
        """
        if image is None: return None
        
        pts = self.find_plate_contour(image)
        
        # Nếu không tìm thấy 4 góc rõ ràng, trả về ảnh gốc (đã qua enhancer)
        if pts is None:
            return cv2.resize(image, (self.target_width, self.target_height))

        # 1. Sắp xếp các điểm tìm được
        rect = self._order_points(pts)
        (tl, tr, br, bl) = rect

        # 2. Định nghĩa các điểm đích (hình chữ nhật phẳng chuẩn)
        dst = np.array([
            [0, 0],
            [self.target_width - 1, 0],
            [self.target_width - 1, self.target_height - 1],
            [0, self.target_height - 1]
        ], dtype="float32")

        # 3. Tính toán ma trận biến đổi và thực hiện Warp
        M = cv2.getPerspectiveTransform(rect, dst)
        warped = cv2.warpPerspective(image, M, (self.target_width, self.target_height))

        return warped