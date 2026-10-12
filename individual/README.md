# Phần cá nhân (30 điểm)

Mỗi thư mục có `answers.md` gồm ba phần cá nhân:

1. **Thay đổi kỹ thuật tự viết** và test của nó.
2. **Kiểm tra chéo độc lập** trên sản phẩm của bạn khác, theo bảng phân công: dự đoán →
   chạy → diễn giải. Script và kết quả JSON nằm cùng thư mục.
3. **Quyết định thiết kế** và 6 **câu hỏi cá nhân** của vai, có dẫn số liệu từ run.

| Vai | Người | Kiểm tra chéo cho | Script | Kết quả |
|---|---|---|---|---|
| A / Ingestion | Tú | Truy vết L02 của Hải Anh (D) | `A-tu/l02_rerun.py` | PASS 11/11 |
| B / Quality | Trung Nguyễn | C01 + duy nhất của Khánh (C) | `B-trung-nguyen/c01_crosscheck.py` | PASS |
| C / Curation | Khánh | I03 của Tú (A), sửa byte vị trí khác | `C-khanh/i03_recheck.py` | PASS 3/3 |
| D / Metadata | Hải Anh | Gate P05 của Trung (E) | `D-hai-anh/p05_check.py` | Phát hiện lỗi fail-open, đã sửa → PASS 3/3 |
| E / Release | Trung | Độ khớp/độ phủ QA của Trung Nguyễn (B) | `src/crosscheck_qa.py` | PASS (100/100, 95/100) |

Phân vai A/C theo người thực sự làm, xác định từ lịch sử git: Tú làm Task 1, Khánh làm Task 3.
Bản phân công ban đầu ghi ngược lại.

## Chạy lại

```bash
python3 individual/A-tu/l02_rerun.py          # máy local, cần data/ (input + trusted manifest)
python3 individual/C-khanh/i03_recheck.py     # máy local, cần data/
# B và D chạy trong Pod (cần DuckDB / bundle gate), xem docstring đầu mỗi script.
```

## Liêm chính

Bản nháp `answers.md` của A–D và mục 1–3 của E được soạn với hỗ trợ AI, dựa trên evidence
thật của nhóm. Các kiểm tra chéo do Trung chạy trong lúc gom bài. **Mỗi người phải tự chạy
lại kiểm tra chéo của mình, đọc và viết lại câu trả lời bằng lời của mình**, rồi đánh dấu
"Đã kiểm chứng" ở đầu file trước khi nộp. Đề yêu cầu sinh viên tự giải thích và tái hiện
được phần đóng góp.
