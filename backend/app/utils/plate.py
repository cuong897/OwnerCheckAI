"""Chuẩn hoá biển số Việt Nam.

Dùng chung cho:
  - Worker (sau khi OCR ra raw text)
  - Watchlist / Vehicle routers (khi admin nhập tay)

Vì worker normalize biển trước khi lưu RecognitionLog, các nguồn dữ liệu khác
cũng phải dùng cùng helper này — nếu không sẽ có mismatch khi worker tra cứu
vehicles / watchlists theo plate_number.
"""
import re
from typing import Optional

# Vietnamese plate pattern. Cho phép có / không dấu cách, dấu chấm phân cách:
#   30A-12345 / 30A 12345 / 51F-123.45 / 50-AF 119.99
_PLATE_RE = re.compile(r"\d{2}[-\s]?[A-Z]{1,2}[-\s]?\d{3,5}\.?\d{0,2}")
# Pattern chuẩn hoá: 2 số đầu + 1-2 chữ + 4-5 số
_PLATE_RAW_RE = re.compile(r"^(\d{2})([A-Z]{1,2})(\d{4,5})$")

PLATE_MAX_LEN = 20  # khớp VARCHAR(20) ở DB


def normalize_plate(raw: Optional[str]) -> str:
    """Chuẩn hoá biển VN về format `XX[A-Z]{1,2}-XXX.XX` (5 số) hoặc `XX[A-Z]{1,2}-XXXX` (4 số).

    - Tự strip whitespace, upper-case.
    - Nếu raw chứa text khác (ví dụ OCR đọc trúng overlay), trích phần khớp pattern
      dài nhất rồi chuẩn hoá.
    - Trả về tối đa 20 ký tự (khớp VARCHAR DB).
    - Empty / None → "".

    Examples:
      "30A61329"        → "30A-613.29"
      "30A6132"         → "30A-6132"
      "30A-61329"       → "30A-613.29"
      "30A-613.29"      → "30A-613.29"
      "miLPR 30A-613.29 Mi AI" → "30A-613.29"
      "ABC"             → "ABC"  (không khớp pattern, giữ nguyên upper)
    """
    if not raw:
        return ""
    s = raw.strip().upper()

    # Bước 1: trích phần khớp pattern nếu OCR đọc thêm text rác
    matches = _PLATE_RE.findall(s)
    candidate = max(matches, key=len) if matches else s

    # Bước 2: chuẩn hoá format
    digits_letters = re.sub(r"[^A-Z0-9]", "", candidate)
    m = _PLATE_RAW_RE.match(digits_letters)
    if not m:
        return candidate[:PLATE_MAX_LEN]

    prefix, letters, numbers = m.groups()
    if len(numbers) == 5:
        return f"{prefix}{letters}-{numbers[:3]}.{numbers[3:]}"[:PLATE_MAX_LEN]
    return f"{prefix}{letters}-{numbers}"[:PLATE_MAX_LEN]
