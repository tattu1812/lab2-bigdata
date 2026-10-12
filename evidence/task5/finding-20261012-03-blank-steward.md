# Finding 20261012-03 – gate chấp nhận `steward` chỉ có khoảng trắng

- **Phát hiện bởi:** kiểm tra chéo của Hải Anh (vai D) trên ca P05 của Trung (vai E), ngày 2026-10-12.
- **Evidence:** `individual/D-hai-anh/p05-check-before-fix.json` (trước khi sửa) và
  `individual/D-hai-anh/p05-check.json` (sau khi sửa).

## Hiện tượng

| Ca | Gate cũ (`1d773e98…`) | Gate mới (`31c136a2…`) |
|---|---|---|
| CTRL – không sửa | PASS 9/9 | PASS 9/9 |
| P05 – xóa `steward` | REJECT 8/9, METADATA | REJECT 8/9, METADATA |
| P05b – `steward = "   "` | **PASS 9/9** | REJECT 8/9, METADATA |

G07 dùng `FILLED = lambda v: v not in (None, "", [], {})`. Chuỗi chỉ có khoảng trắng không
bằng `""` nên được coi là có giá trị. Contract quy định "thiếu = null, rỗng hoặc chỉ khoảng
trắng", và đề yêu cầu owner/steward không rỗng. Vì vậy gate cũ fail-open với ca này.

## Xử lý

1. `FILLED` trong `src/gate.py` giờ coi chuỗi rỗng sau `strip()` là thiếu.
2. Chạy lại bộ P01–P08 với gate mới (`gatetest-20261012-04`): kết quả giống hệt
   `gatetest-20261012-03`, chỉ khác `gate_sha256`.
3. Chạy lại kiểm tra chéo của Hải Anh: 3/3 ca đúng kỳ vọng.

## Ảnh hưởng tới release hiện hành

Không có. Catalog trong `release-20261012-02` có `steward = "Hải Anh"` cho cả 3 dataset, nên
gate mới vẫn PASS 9/9 (ca P01 và CTRL chạy trên đúng metadata đó). Release không cần thu hồi.
`gate-report.json` trong release ghi `gate_sha256` của gate cũ. Đó là đúng sự thật tại thời
điểm công bố, nên không sửa.
