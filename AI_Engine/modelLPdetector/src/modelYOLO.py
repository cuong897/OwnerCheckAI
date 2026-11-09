from ultralytics import YOLO


class YOLODetector:
    def __init__(self, model_path=None, conf_threshold=0.5):
        """
        Khởi tạo detector.

        """
        self.model = None
        self.conf_threshold = conf_threshold
        if model_path:
            self.load_model(model_path)

    def load_model(self, model_path):
        """
        Tải trọng số YOLOv8 từ file .pt.
        """
        try:
            self.model = YOLO(model_path)
            print(f"[INFO] Load model LP Detector thành công: {model_path}")
        except Exception as e:
            print(f"[ERROR] Không thể load model: {e}")
            raise  # [SỬA] Re-raise để caller biết load thất bại, không âm thầm bỏ qua

    def predict(self, frame, conf=None):
        """
        Nhận ảnh đầu vào và trả về danh sách các biển số phát hiện được.

        """
        if self.model is None:
            raise RuntimeError("[ERROR] Model chưa được load! Hãy gọi load_model() trước.")

        # [SỬA] Dùng conf_threshold từ instance nếu không truyền override
        conf_val = conf if conf is not None else self.conf_threshold

        results = self.model.predict(source=frame, conf=conf_val, verbose=False)

        detections = []
        for r in results:
            if r.boxes is None:   # Không phát hiện được gì, bỏ qua
                continue
            for box in r.boxes:
                xyxy = box.xyxy[0].cpu().numpy()
                score = float(box.conf[0].cpu().item())
                cls = int(box.cls[0].cpu().item())

                x1, y1, x2, y2 = int(xyxy[0]), int(xyxy[1]), int(xyxy[2]), int(xyxy[3])

                detections.append({
                    "bbox": (x1, y1, x2, y2),
                    "conf": score,
                    "class": cls
                })
        return detections