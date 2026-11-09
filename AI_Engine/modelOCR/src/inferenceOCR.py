import os
os.environ["FLAGS_use_mkldnn"] = "0"
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

import sys
import cv2
try:    from .modelOCR import PaddleOCRReader # Chạy khi dùng -m (Module mode)
except ImportError: from modelOCR import PaddleOCRReader  # Chạy khi run file trực tiếp

MODEL_PATH = "C:/Users/ADMIN/Documents/GitHub/UET_AIT3004-2_OwnercheckAI/AI_Engine/modelOCR/models/pretrained/rec_model/inference"  
DICT_PATH  = "C:/Users/ADMIN/Documents/GitHub/UET_AIT3004-2_OwnercheckAI/AI_Engine/modelOCR/models/latin_dict.txt"


def main():
    # 1. Khởi tạo reader
    reader = PaddleOCRReader(
        model_path=MODEL_PATH,
        dict_path=DICT_PATH,
        score_threshold=0.7,
        use_gpu=True,
    )

    # 2. Đọc ảnh crop biển số
    image = cv2.imread("test_plate.jpg")

    # Kiểm tra ảnh đọc được không trước khi predict
    # Nếu file không tồn tại, cv2.imread trả về None và PaddleOCR sẽ crash
    if image is None:
        print("[ERROR] Không đọc được ảnh 'test_plate.jpg'. Kiểm tra lại đường dẫn.")
        sys.exit(1)

    # 3. Dự đoán
    result = reader.predict(image)

    if not result["text"]:
        print(f"[INFO] Không đọc được ký tự nào (score: {result['score']:.2f}).")
    else:
        print(f"Biển số: {result['text']} | score: {result['score']:.2f}")

        # Hiển thị kết quả lên ảnh để kiểm tra trực quan
        label = f"{result['text']} ({result['score']:.2f})"
        cv2.putText(
            image, label,
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0, (0, 255, 0), 2,
        )

    cv2.namedWindow("OCR Result", cv2.WINDOW_NORMAL)
    cv2.imshow("OCR Result", image) 
    cv2.waitKey(0)
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()