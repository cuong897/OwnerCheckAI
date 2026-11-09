import cv2
import numpy as np
from typing import Optional

class PlateEnhancer:
    """
    Chuyên trách việc nâng cao chất lượng ảnh vùng biển số (Enhancement).
    Giúp làm sạch nhiễu và cân bằng ánh sáng trước khi đưa vào OCR.
    """

    def __init__(self):
        # Khởi tạo CLAHE (Contrast Limited Adaptive Histogram Equalization)
        # clipLimit: Ngưỡng giới hạn độ tương phản (tránh nhiễu)
        # tileGridSize: Chia ảnh thành các ô nhỏ 8x8 để xử lý cục bộ
        self.clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))

    def remove_noise(self, image: np.ndarray) -> np.ndarray:
        """
        Khử nhiễu bằng Bilateral Filter.
        Giúp mịn vùng nền biển số nhưng giữ lại độ sắc nét của cạnh chữ số.
        """
        # d=9: Đường kính của mỗi vùng lân cận pixel
        # sigmaColor=75: Tỉ lệ lọc màu (càng lớn càng làm mịn nhiều màu)
        # sigmaSpace=75: Tỉ lệ lọc không gian (càng lớn càng ảnh hưởng đến pixel xa hơn)
        return cv2.bilateralFilter(image, 9, 75, 75)

    def adjust_lighting(self, image: np.ndarray) -> np.ndarray:
        """
        Cân bằng ánh sáng bằng CLAHE trên hệ màu LAB.
        Giúp xử lý biển số bị lóa đèn hoặc quá tối.
        """
        # Chuyển sang hệ màu LAB để tách riêng kênh độ sáng (L) ra khỏi màu sắc (AB)
        lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)

        # Áp dụng CLAHE lên kênh L (Lightness)
        cl = self.clahe.apply(l)

        # Gộp lại và chuyển về BGR
        limg = cv2.merge((cl, a, b))
        final_img = cv2.cvtColor(limg, cv2.COLOR_LAB2BGR)
        return final_img

    def sharpen_image(self, image: np.ndarray) -> np.ndarray:
        """
        Làm sắc nét ảnh bằng kỹ thuật Unsharp Masking.
        """
        gaussian_blur = cv2.GaussianBlur(image, (0, 0), 3)
        # addWeighted: Trộn ảnh gốc với ảnh làm mờ để tạo hiệu ứng sắc nét
        sharpened = cv2.addWeighted(image, 1.5, gaussian_blur, -0.5, 0)
        return sharpened

    def enhance(self, plate_img: np.ndarray) -> np.ndarray:
        """
        Pipeline xử lý toàn diện cho vùng biển số.
        """
        if plate_img is None:
            return None

        # 1. Cân bằng sáng trước (để các bước sau nhìn thấy chi tiết rõ hơn)
        enhanced = self.adjust_lighting(plate_img)

        # 2. Khử nhiễu
        enhanced = self.remove_noise(enhanced)

        # 3. Làm sắc nét các cạnh chữ
        enhanced = self.sharpen_image(enhanced)

        return enhanced