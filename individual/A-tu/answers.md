# Tú – Vai A / Ingestion (Task 1)


## 1. Thay đổi kỹ thuật tự viết

**`src/stage_inputs.py` + `src/check_integrity.py` (I01).** Script tải 4 object từ
`research-raw/lab2/inputs/batch-01/` vào file `.partial`, vừa stream vừa đếm byte và tính
SHA-256, rồi so với `data/trusted_manifest.json`. File chỉ được đổi tên thành tên thật khi
**cả** số byte và hash đều khớp. Nếu sai, file tạm bị xóa và object bị đánh `FAIL`.

- Test: `evidence/task1/integrity-test.json` (4/4 PASS) và
  `evidence/task1/runs/task1-20261012-02/stage-report.json`. Kết quả này lấy từ lần chạy
  lại trên Pod mới tạo ngày 12/10 và giống hệt lần `task1-20261012-01`.
- Ca phản ví dụ: I03 (`evidence/task1/mutation-test.json`). Lật 1 byte đầu của
  `observations_a.csv` thì hash thành `abf16694…`, kết quả `INPUT_INTEGRITY`.

## 2. Kiểm tra chéo: truy vết L02 của Hải Anh (vai D)

**Dự đoán.** `R001001` có 2 phiên bản. Bản `observations_b.jsonl` dòng 5101 có
`arrived_at` = 08:23:30, muộn hơn bản `observations_a.csv` dòng 1001 (08:21:30), nên thắng.
Curated phải có `temperature_c = 19.10`, `is_late = false`, `site = zone-1`. Bản CSV là
`SUPERSEDED`.

**Chạy.**

```bash
python3 individual/A-tu/l02_rerun.py      # chạy ở thư mục gốc repo, chỉ dùng thư viện chuẩn
```

Script **không** dùng envelope hay DuckDB như `src/trace_record.py` của Hải Anh. Nó đọc
thẳng byte của file nguồn, tự tính SHA-256 và tự tìm dòng theo quy ước `source_row`
(CSV: thứ tự bản ghi không tính header; JSONL: số dòng). Sau đó nó tự chọn winner theo
thứ tự của contract và tự tính lại nhiệt độ, `is_late`, `site`.

**Diễn giải.** 11/11 kiểm tra PASS (`individual/A-tu/l02-rerun.json`):

- Hash file nguồn khớp trusted manifest và khớp giá trị ghi trong trace.
- 6 trường của cả hai phiên bản khớp trace.
- Winner tự tính trùng `selected_version`.
- `19.10 / false / zone-1 / 3072ad0b…` trùng dòng curated.

Vậy từ một dòng curated có thể truy về đúng object, đúng hash nguồn, đúng số dòng và đúng
phiên bản được chọn.

## 3. Quyết định thiết kế đã giải thích

Envelope giữ cả dòng JSON hỏng thay vì bỏ qua. 5 dòng `observations_b.jsonl` 5201–5205
(`{"broken":`) có `parse_status = PARSE_ERROR` và `payload = null`, nên tổng envelope vẫn là
10.205. Task 3 xếp chúng vào quarantine với lý do `PARSE`.

## 4. Câu hỏi cá nhân

**1. Vì sao phải kiểm hash với `trusted_manifest.json` mà không dùng manifest trong ZIP?**
`source_manifest.json` đi cùng dữ liệu. Ai sửa được dữ liệu thì cũng sửa được manifest đó
cho khớp, nên so hai file cùng một người kiểm soát không chứng minh được gì. Danh tính
`ingestor` lại có quyền ghi bucket raw. Trusted manifest do giảng viên phát qua kênh chỉ-đọc,
nên nó là mốc độc lập với người ghi dữ liệu. I01 so 4/4 object với trusted manifest
(ví dụ `observations_a.csv`: 421.028 byte, `51574189…`).

**2. Vì sao không được dùng ETag thay cho SHA-256?**
ETag do server sinh ra và không bảo đảm là hash nội dung. Với upload multipart, ETag là
MD5 của các MD5 từng phần kèm số phần, nên thay đổi theo cách chia part. Một số store dùng
định dạng riêng. MD5 cũng không còn chống được va chạm có chủ đích. Trusted manifest ghi
SHA-256, nên chỉ có cách tự tính SHA-256 trên đúng byte tải về mới so sánh được.

**3. Khóa vật lý `(source_object, source_row)` khác `record_id` thế nào?**
Khóa vật lý định danh **một lần xuất hiện** trong file nguồn. Nó luôn duy nhất (10.205 khóa
cho 10.205 envelope) và tồn tại cả với dòng hỏng không có `record_id`. Khóa vật lý dùng cho
bảo toàn và truy vết: mỗi khóa phải rơi vào đúng một trong curated, quarantine hoặc
duplicates. `record_id` là định danh **nghiệp vụ** của một quan trắc, có thể lặp giữa hai
nguồn. Ví dụ `R001001` có ở cả `observations_a.csv:1001` và `observations_b.jsonl:5101`.
`record_id` dùng để khử trùng và phải duy nhất trong release (9.610 dòng, 9.610 ID).

**4. Dòng JSON hỏng: vì sao giữ với `parse_ok = false` thay vì bỏ qua?**
Bỏ qua tức là làm mất dữ liệu ngầm. Tổng sẽ còn 10.200, không khớp 10.205 trong manifest
và không ai biết 5 dòng đã đi đâu. Giữ dòng hỏng thì nó có khóa vật lý, có lý do `PARSE`
trong quarantine, và đối soát C01 vẫn đóng được: 10.205 = 9.610 + 395 + 200. Nó cũng giúp
nhóm báo lỗi lại cho nguồn dữ liệu.

**5. PUT bị timeout có được coi là I04 đạt không?**
Không. Timeout chỉ cho biết không nhận được câu trả lời, có thể do mạng, sai endpoint hoặc
Pod treo. Nó không chứng minh store đã kiểm tra quyền và từ chối. I04 phải thấy server trả
lời rõ ràng là cấm: `put_error = AccessDenied`, `put_http_status = 403`
(`evidence/task1/access-test.json`). Cũng cần một GET raw thành công trên cùng credential để
loại trừ trường hợp credential sai. Kiểm tra bị nền tảng chặn không bao giờ được ghi PASS.

**6. Cần sửa quy tắc trong `contract.json` sau phút 30 thì làm gì?**
Không sửa lén bản đã đóng băng. Phải tăng phiên bản contract, ghi lý do thay đổi, nhờ một
người khác review lại, tính hash mới và ghi vào `evidence_index.csv`. Sau đó chạy lại các
bước phụ thuộc (quality before, curation, metadata) với run ID mới. Mọi run đều ghi
`contract_sha256` trong run-manifest/run-record, nên luôn biết output nào dùng contract nào.
Hash đang dùng là `af083363…`. Hash `a655a0ca…` trong `contract-review.md` chỉ là cùng file
đó khi checkout với CRLF, nội dung không đổi.
