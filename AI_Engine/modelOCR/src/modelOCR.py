from paddleocr import PaddleOCR


class PaddleOCRReader:
    def __init__(self, model_path=None, dict_path=None, score_threshold=0.7, use_gpu=True):
        """
        Khởi tạo reader.

        Args:
            model_path (str): Đường dẫn tới thư mục chứa inference model
                              (inference.pdmodel + inference.pdiparams).
                              Nếu None thì chưa load.
            dict_path (str):  Đường dẫn tới file latin_dict.txt.
            score_threshold (float): Ngưỡng tin cậy mặc định — chỉ giữ kết quả
                                     có score > ngưỡng này. Có thể override khi gọi predict().
            use_gpu (bool):   True nếu có GPU, False để dùng CPU.
        """
        self.model           = None
        self.score_threshold = score_threshold
        self.dict_path       = dict_path
        self.use_gpu         = use_gpu
        if model_path:
            self.load_model(model_path)

    def load_model(self, model_path):
        """
        Tải rec_model PaddleOCR từ thư mục chứa file inference.

        Lưu ý: model_path phải trỏ tới thư mục chứa inference model
        (export từ best_accuracy.pdparams bằng tools/export_model.py),
        KHÔNG phải thư mục chứa best_accuracy.pdparams trực tiếp.
        """
        try:
            self.model = PaddleOCR(
                rec_model_dir=model_path,
                # rec_char_dict_path=self.dict_path,
                use_angle_cls=False,    # Biển số không bị xoay dọc
                det=False,              # YOLO đã lo detection, chỉ cần recognition
                lang="en",
                use_gpu=self.use_gpu,
                show_log=False,         # Tắt log thừa của PaddleOCR
                enable_mkldnn=False,
            )
            print(f"[INFO] Load model OCR thành công: {model_path}")
        except Exception as e:
            print(f"[ERROR] Không thể load model OCR: {e}")
            raise  # Re-raise để caller biết load thất bại, không âm thầm bỏ qua

    def predict(self, image, score=None):
        """
        Nhận ảnh crop biển số và trả về chuỗi ký tự đọc được.

        Args:
            image: Ảnh crop biển số từ OpenCV (numpy array BGR), không được là None.
            score (float | None): Override ngưỡng tin cậy cho lần predict này.
                                  Nếu None thì dùng self.score_threshold.

        Returns:
            dict:
                - "text"  : str,   chuỗi ký tự biển số (vd: "29A-123.45").
                            Trả về "" nếu không đọc được hoặc score thấp.
                - "score" : float, độ tin cậy (0.0 → 1.0).
        """
        if self.model is None:
            raise RuntimeError("[ERROR] Model chưa được load! Hãy gọi load_model() trước.")

        if image is None:
            raise ValueError("[ERROR] image không được là None.")

        # Dùng score_threshold từ instance nếu không truyền override
        score_val = score if score is not None else self.score_threshold

        # PaddleOCR trả về dạng: [[["29A-123.45", 0.98]]]
        # Với det=False, shape luôn là list of [text, confidence]
        raw = self.model.ocr(image, det=False, cls=False)

        # Trường hợp model không đọc được gì
        if not raw or not raw[0]:
            return {"text": "", "score": 0.0}

        text, confidence = raw[0][0]
        confidence = float(confidence)

        # Lọc kết quả dưới ngưỡng tin cậy
        if confidence < score_val:
            return {"text": "", "score": confidence}

        return {
            "text" : text.strip().upper(),  # Chuẩn hoá: bỏ khoảng trắng, viết hoa
            "score": confidence,
        }