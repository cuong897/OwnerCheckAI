import cv2
import numpy as np
from typing import Tuple, Dict, Any

class ImageProcessor:
    """
    Class đảm nhiệm việc biến đổi hình học và định dạng Tensor cho mô hình AI.
    Tối ưu hóa cho YOLO (ONNX/TensorRT) và các mô hình Pytorch.
    """
    
    def __init__(self, target_size: Tuple[int, int] = (640, 640)):
        self.target_size = target_size
        self.pad_color = (114, 114, 114) # Màu xám chuẩn cho YOLO

    def letterbox(self, image: np.ndarray) -> Tuple[np.ndarray, float, Tuple[float, float]]:
        """
        Resize ảnh giữ nguyên tỉ lệ (Aspect Ratio) và thêm viền đệm (Padding).
        """
        shape = image.shape[:2]  # current shape [height, width]
        new_shape = self.target_size

        # 1. Tính toán tỷ lệ scale nhỏ nhất
        r = min(new_shape[0] / shape[0], new_shape[1] / shape[1])
        
        # 2. Tính toán kích thước mới (chưa có padding)
        new_unpad = int(round(shape[1] * r)), int(round(shape[0] * r))
        
        # 3. Tính toán lượng padding cần thiết
        dw, dh = new_shape[1] - new_unpad[0], new_shape[0] - new_unpad[1]  # wh padding
        
        # Chia đều padding ra 2 bên (trái/phải, trên/dưới)
        dw /= 2  
        dh /= 2

        # 4. Resize ảnh nếu cần
        if shape[::-1] != new_unpad:
            image = cv2.resize(image, new_unpad, interpolation=cv2.INTER_LINEAR)
            
        # 5. Thêm viền (Padding)
        top, bottom = int(round(dh - 0.1)), int(round(dh + 0.1))
        left, right = int(round(dw - 0.1)), int(round(dw + 0.1))
        
        padded_img = cv2.copyMakeBorder(
            image, top, bottom, left, right, 
            cv2.BORDER_CONSTANT, value=self.pad_color
        )

        return padded_img, r, (left, top)

    def prepare_for_model(self, padded_img: np.ndarray) -> np.ndarray:
        """
        Chuyển đổi ảnh Numpy sang định dạng Tensor CHW chuẩn bị đưa vào YOLO.
        
        """
        # 1. Chuyển từ BGR sang RGB (YOLO train trên hệ màu RGB)
        img_rgb = cv2.cvtColor(padded_img, cv2.COLOR_BGR2RGB)
        
        # 2. Chuyển đổi HWC (Height, Width, Channels) sang CHW
        # Ví dụ: (640, 640, 3) -> (3, 640, 640)
        img_chw = img_rgb.transpose((2, 0, 1))
        
        # 3. Ép kiểu về float32 để giữ hiệu năng khi tính toán ma trận
        img_chw = np.ascontiguousarray(img_chw, dtype=np.float32)
        
        # 4. Chuẩn hóa giá trị pixel (Normalization) từ [0, 255] về [0.0, 1.0]
        img_chw /= 255.0
        
        # 5. Thêm Batch dimension: (3, 640, 640) -> (1, 3, 640, 640) (BCHW)
        tensor = np.expand_dims(img_chw, axis=0)
        
        return tensor
        
    def scale_coords(self, coords: np.ndarray, ratio: float, pad: Tuple[float, float], img0_shape: Tuple[int, int]) -> np.ndarray:
        """
        Biến đổi ngược tọa độ Bounding Box từ ảnh 640x640 về ảnh gốc (VD: 1920x1080).
        (Hàm này sẽ được dùng sau khi YOLO trả ra kết quả).
        """
        # Trừ đi phần padding
        coords[:, [0, 2]] -= pad[0]  # x padding
        coords[:, [1, 3]] -= pad[1]  # y padding
        
        # Chia cho tỷ lệ scale
        coords[:, :4] /= ratio
        
        # Clip tọa độ để không bị tràn ra ngoài kích thước ảnh gốc
        coords[:, 0] = np.clip(coords[:, 0], 0, img0_shape[1])  # x1
        coords[:, 1] = np.clip(coords[:, 1], 0, img0_shape[0])  # y1
        coords[:, 2] = np.clip(coords[:, 2], 0, img0_shape[1])  # x2
        coords[:, 3] = np.clip(coords[:, 3], 0, img0_shape[0])  # y2
        
        return coords