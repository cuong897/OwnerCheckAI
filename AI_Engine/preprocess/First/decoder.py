import cv2
import numpy as np
import base64
import threading
import time
from typing import Union, Optional, Tuple, Generator

class ImageDecoder:
    """
    Class xử lý giải mã các ảnh tĩnh (Base64, Binary bytes, File path).
    Hoạt động hoàn toàn trên RAM để tối ưu tốc độ I/O.
    """
    
    @staticmethod
    def from_base64(base64_str: str) -> Optional[np.ndarray]:
        try:
            # Bỏ phần header "data:image/jpeg;base64," nếu có
            if "," in base64_str:
                base64_str = base64_str.split(",")[1]
            
            img_bytes = base64.b64decode(base64_str)
            return ImageDecoder.from_bytes(img_bytes)
        except Exception as e:
            print(f"[Error] Failed to decode Base64: {e}")
            return None

    @staticmethod
    def from_bytes(img_bytes: bytes) -> Optional[np.ndarray]:
        try:
            np_arr = np.frombuffer(img_bytes, np.uint8)
            img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            return img
        except Exception as e:
            print(f"[Error] Failed to decode Bytes: {e}")
            return None
            
    @staticmethod
    def from_file(file_path: str) -> Optional[np.ndarray]:
        try:
            img = cv2.imread(file_path)
            if img is None:
                raise ValueError(f"File not found or corrupted: {file_path}")
            return img
        except Exception as e:
            print(f"[Error] Failed to read file: {e}")
            return None


class StreamDecoder:
    """
    Class xử lý các luồng video động (RTSP, Video Upload).
    Sử dụng Multi-threading cho luồng trực tiếp (RTSP) để tránh Buffer Lag.
    """
    
    def __init__(self, source: Union[str, int], is_live_stream: bool = True):
        self.source = source
        self.is_live_stream = is_live_stream
        self.cap = cv2.VideoCapture(self.source)
        
        if not self.cap.isOpened():
            raise ValueError(f"[Error] Cannot open video source: {self.source}")
            
        # Biến cho Multi-threading (chỉ dùng cho RTSP/Camera thực tế)
        self.latest_frame = None
        self.lock = threading.Lock()
        self.running = False
        self.thread = None

    def start_background_reader(self):
        """Khởi động luồng chạy ngầm liên tục cập nhật frame mới nhất từ Camera"""
        if not self.is_live_stream:
            return # Không cần chạy ngầm cho file video
            
        self.running = True
        self.thread = threading.Thread(target=self._update_frame, daemon=True)
        self.thread.start()
        print(f"[Info] Started background reader for {self.source}")

    def _update_frame(self):
        """Hàm chạy ngầm liên tục lấy frame mới nhất, giải quyết bài toán Buffer Lag"""
        while self.running:
            ret, frame = self.cap.read()
            if not ret:
                # Nếu mất kết nối tạm thời, có thể thêm logic reconnect ở đây
                print(f"[Warning] Frame drop or stream ended on {self.source}")
                time.sleep(0.1)
                continue
            
            with self.lock:
                self.latest_frame = frame

    def read_latest_frame(self) -> Optional[np.ndarray]:
        """Lấy frame mới nhất từ stream (Dùng cho luồng RTSP)"""
        if not self.is_live_stream:
            raise RuntimeError("Use get_video_frames() generator for video files instead.")
            
        with self.lock:
            if self.latest_frame is not None:
                return self.latest_frame.copy() # Copy để tránh thay đổi khi đang inference
        return None

    def get_video_frames(self, skip_frames: int = 5) -> Generator[Tuple[int, np.ndarray], None, None]:
        """
        Generator xử lý file video upload.
        Áp dụng thuật toán Frame Skipping để giảm tải AI.
        VD: skip_frames=5 nghĩa là cứ 5 frame thì AI xử lý 1 frame.
        """
        if self.is_live_stream:
            raise RuntimeError("Use read_latest_frame() for live streams.")
            
        frame_count = 0
        while self.cap.isOpened():
            ret, frame = self.cap.read()
            if not ret:
                break
                
            frame_count += 1
            if frame_count % skip_frames == 0:
                yield frame_count, frame

    def stop(self):
        """Giải phóng tài nguyên (Memory leak prevention)"""
        self.running = False
        if self.thread is not None:
            self.thread.join(timeout=2.0)
        self.cap.release()
        print(f"[Info] Stopped and released resources for {self.source}")