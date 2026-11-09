import cv2
import numpy as np
from typing import Tuple, Dict

class ImageQuality:
    """
    Class đánh giá chất lượng ảnh trước khi đưa vào Model AI.
    Tối ưu hóa bằng cách resize ảnh nhỏ lại trước khi tính toán để giảm tải CPU.
    """
    
    def __init__(self, blur_threshold: float = 100.0, 
                 dark_threshold: float = 40.0, 
                 bright_threshold: float = 230.0):
        """
        Khởi tạo các ngưỡng đánh giá. 
        Lưu ý: Các ngưỡng này cần được tinh chỉnh (fine-tune) theo từng loại Camera thực tế.
        """
        self.blur_threshold = blur_threshold
        self.dark_threshold = dark_threshold
        self.bright_threshold = bright_threshold
        # Kích thước dùng để tính toán IQA (nhỏ gọn để chạy nhanh)
        self.eval_size = (300, 300) 

    def _get_eval_image(self, image: np.ndarray) -> np.ndarray:
        """Chuyển ảnh về Grayscale và thu nhỏ để tăng tốc độ tính toán"""
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        return cv2.resize(gray, self.eval_size)

    def check_blur(self, eval_image: np.ndarray) -> Tuple[bool, float]:
        """
        Kiểm tra độ mờ bằng Laplacian Variance.
        Return: (is_blurry, variance_score)
        """
        variance = float(cv2.Laplacian(eval_image, cv2.CV_64F).var())
        is_blurry = variance < self.blur_threshold
        return is_blurry, variance

    def check_exposure(self, eval_image: np.ndarray) -> Tuple[str, float]:
        """
        Kiểm tra độ sáng của ảnh.
        Return: (exposure_status, mean_intensity)
        - exposure_status: 'dark', 'bright', hoặc 'normal'
        """
        mean_intensity = float(np.mean(eval_image))
        
        if mean_intensity < self.dark_threshold:
            return 'dark', mean_intensity
        elif mean_intensity > self.bright_threshold:
            return 'bright', mean_intensity
        else:
            return 'normal', mean_intensity

    def assess(self, image: np.ndarray) -> Dict:
        """
        Đánh giá toàn diện bức ảnh.
        Return: Dictionary chứa trạng thái hợp lệ và các thông số chi tiết.
        """
        if image is None or image.size == 0:
            return {"is_valid": False, "reason": "Empty image"}

        # Tiền xử lý 1 lần cho cả 2 phép đo để tiết kiệm tài nguyên
        eval_image = self._get_eval_image(image)
        
        # 1. Kiểm tra mờ
        is_blurry, blur_score = self.check_blur(eval_image)
        if is_blurry:
            return {
                "is_valid": False, 
                "reason": "Too blurry", 
                "blur_score": blur_score
            }
            
        # 2. Kiểm tra sáng tối
        exposure_status, brightness_score = self.check_exposure(eval_image)
        if exposure_status != 'normal':
            return {
                "is_valid": False, 
                "reason": f"Exposure issue: {exposure_status}", 
                "brightness": brightness_score
            }
            
        # Nếu qua hết các bài test
        return {
            "is_valid": True,
            "reason": "Good quality",
            "blur_score": blur_score,
            "brightness": brightness_score
        }