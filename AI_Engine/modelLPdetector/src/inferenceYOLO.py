import sys
import cv2
try:
    from .modelYOLO import YOLODetector # Chạy khi dùng -m (Module mode)
except ImportError:
    from modelYOLO import YOLODetector  # Chạy khi run file trực tiếp

# Đường dẫn model nhất quán với MODEL_RUN_NAME trong trainYOLO.py
MODEL_PATH = "AI_Engine/modelLPdetector/runs/train/lp_detector_v1/weights/best.pt"


def main():
    # 1. Khởi tạo detector
    detector = YOLODetector(MODEL_PATH, conf_threshold=0.5)

    # 2. Đọc ảnh
    image = cv2.imread("test.jpg")

    # [SỬA] Kiểm tra ảnh đọc được không trước khi predict.
    # Nếu file không tồn tại, cv2.imread trả về None và YOLO sẽ crash.
    if image is None:
        print("[ERROR] Không đọc được ảnh 'test.jpg'. Kiểm tra lại đường dẫn.")
        sys.exit(1)

    # 3. Dự đoán
    results = detector.predict(image)

    if not results:
        print("[INFO] Không phát hiện biển số nào.")
    else:
        for res in results:
            x1, y1, x2, y2 = res["bbox"]   # tuple int thuần Python — an toàn với cv2
            print(
                f"Tìm thấy biển số tại: ({x1}, {y1}, {x2}, {y2}) "
                f"| conf: {res['conf']:.2f} | class: {res['class']}"
            )
            cv2.rectangle(image, (x1, y1), (x2, y2), (0, 255, 0), 2)

    cv2.imshow("LP Detection", image)
    cv2.waitKey(0)
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()