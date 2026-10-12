# Khánh – Vai C / Curation (Task 3)

> Bản nháp được soạn với hỗ trợ AI, dựa trên evidence của nhóm. Khánh phải tự đọc lại,
> chạy lại lệnh ở mục 2 và viết lại bằng lời của mình trước khi trình bày.
> Đã kiểm chứng: [ ]

## 1. Thay đổi kỹ thuật tự viết

**`src/curate.sql` + `src/run_curate.py` + `src/test_curate.py`.** Pipeline chạy theo bốn
bước: prekey → khử trùng bằng `ROW_NUMBER()` → validate winner → join registry.
`run_curate.py` thay tham số từ `contracts/*.json` vào SQL và từ chối nếu contract đổi thứ
tự khử trùng.

- Test C01–C05 PASS (`evidence/task3/runs/task3-20261012-0{1,2}/curate-checks.json`).
- C04 chạy 4 ca biên trên fixture 37 dòng (`tests/fixtures/edge/`): 15 curated,
  18 quarantine, 4 duplicates.
- Ngày 12/10 chạy lại trên Pod mới (`task3-20261012-02`): 3 artifact trùng SHA-256 với `-01`.

## 2. Kiểm tra chéo: ca từ chối object bị sửa (I03) của Tú (vai A)

**Dự đoán.** Sửa byte ở vị trí khác byte đầu và ở object khác `observations_a.csv` thì
`check_integrity.py` của Tú vẫn phải đánh object đó `FAIL / INPUT_INTEGRITY`, ba object còn
lại PASS, và `data/` không bị đổi.

**Chạy.**

```bash
python3 individual/C-khanh/i03_recheck.py     # ở thư mục gốc repo
```

Script sao chép input vào thư mục tạm rồi chạy chính `src/check_integrity.py` với `HOME`
trỏ vào bản sao. Có 3 ca:

| Ca | Object | Thay đổi | Kết quả |
|---|---|---|---|
| M1 | `observations_b.jsonl` | lật 1 bit ở byte giữa (offset 518.719), giữ nguyên kích thước | FAIL / INPUT_INTEGRITY |
| M2 | `sensors.csv` | thay byte cuối (offset 255) | FAIL / INPUT_INTEGRITY |
| M3 | `qa_reference.csv` | nối thêm 1 byte | FAIL / INPUT_INTEGRITY |

**Diễn giải** (`individual/C-khanh/i03-recheck.json`, PASS):

- Mỗi ca chỉ đúng object bị sửa FAIL, I01 tổng thể FAIL, và `data/` không đổi hash.
- M1 và M2 giữ nguyên kích thước, nên chính hash là thứ bắt được lỗi; một kiểm tra chỉ so
  kích thước sẽ để lọt.
- M3 bị bắt ở cả kích thước (1.423 → 1.424) lẫn hash.

## 3. Quyết định thiết kế đã giải thích

Winner được chọn **trước** khi validate và không fallback. Ví dụ `R001051` (truy vết L03,
`evidence/task4/trace-L02-L03.json`):

- Bản mới `observations_b.jsonl:5151` (ingest 08:48:30) thiếu `reading`, nên vào
  quarantine với lý do `REQUIRED`.
- Bản cũ `observations_a.csv:1051` (ingest 08:46:30, `reading = 23.10`) vẫn hợp lệ nhưng
  nằm trong `duplicates.csv` là `SUPERSEDED`, winner ghi là `observations_b.jsonl:5151`.
- `R001051` không có trong curated.

## 4. Câu hỏi cá nhân

**1. Vì sao dùng `ROW_NUMBER()` với thứ tự đầy đủ thay vì `DISTINCT` hoặc dòng đầu theo
thứ tự file?**
`DISTINCT` chỉ gộp dòng giống hệt nhau. Hai phiên bản của cùng `record_id` khác
`ingest_time`/`reading` thì vẫn còn cả hai, và không nói được bản nào thắng. "Dòng đầu theo
thứ tự file" phụ thuộc thứ tự đọc: đổi thứ tự file hay chạy song song sẽ cho winner khác.
`ROW_NUMBER() OVER (PARTITION BY record_id ORDER BY ingest_ts DESC, source_object,
source_row)` là thứ tự toàn phần, vì khóa vật lý là duy nhất nên không bao giờ hòa. Do đó
winner tất định. C02 chạy với envelope đảo ngược thứ tự và cho cùng `quarantine.csv`,
`duplicates.csv` và cùng digest nội dung curated `a9d993df…`. Mọi bản không thắng (200) đều
có trong sổ trùng kèm khóa winner.

**2. Bản mới nhất không hợp lệ, bản cũ hợp lệ: vì sao không lấy bản cũ?**
Bản mới nhất là thông tin mới nhất nguồn gửi: nó có thể là bản sửa, hoặc là tín hiệu cảm
biến hỏng. Lặng lẽ lấy bản cũ sẽ công bố một giá trị mà nguồn đã thay thế, và che mất lỗi.
Lựa chọn còn phụ thuộc vào việc bản nào lỗi, nên kết quả khó giải thích. Contract quy định
`invalid_winner_policy = quarantine_no_fallback`. Với `R001051`, `reading = 23.10` cũ trông
hợp lý nhưng không được dùng. Người phân tích thấy ID này trong quarantine (`REQUIRED`) và
có thể hỏi lại nguồn.

**3. Vì sao tổng bằng nhau chưa đủ chứng minh bảo toàn? Ví dụ.**
Giả sử pipeline làm mất `observations_a.csv:1` nhưng ghi `observations_a.csv:2` vào cả
curated lẫn quarantine. Tổng vẫn là 9.610 + 395 + 200 = 10.205 nhưng có 1 bản ghi mất và 1
bản ghi bị đếm hai lần. Vì vậy C01 so **tập** khóa vật lý: anti-join raw → outputs (mất 0),
outputs → raw (bịa 0), chồng lấn từng cặp output bằng 0, và mỗi output không trùng khóa.
Trung Nguyễn đã tính lại độc lập và ra cùng kết quả
(`individual/B-trung-nguyen/c01-crosscheck.json`).

**4. Vì sao validate trước khi làm tròn về `DECIMAL(8,2)`? Ví dụ.**
Khoảng [−30, 60] °C áp dụng cho giá trị đo thật. `60.004` °C nằm ngoài khoảng, nhưng làm
tròn trước thì thành `60.00` và lọt qua. Fixture C04 (EC3) có đúng các ca này:

| Đầu vào | Giá trị chính xác | Kết quả |
|---|---|---|
| `60.004` °C | 60,004 | quarantine `RANGE` |
| `-30.001` °C | −30,001 | quarantine `RANGE` |
| `140.01` °F | 60,0056 | quarantine `RANGE` (làm tròn trước sẽ thành 60,01, vẫn sai, nhưng 140,005 °F sẽ lọt) |
| `140` °F | 60 | giữ, `60.00` |
| `-22` °F | −30 | giữ, `-30.00` |
| `32.009` °F | 0,005 | giữ, `0.01` (HALF_UP) |

Chuyển đổi `(F − 32) × 5/9` được tính bằng số học số nguyên cố định. Khoảng được so trên
giá trị chính xác, sau đó mới làm tròn `HALF_UP`.

**5. Vì sao so replay bằng digest logic mà không so SHA-256 file Parquet?**
Byte Parquet phụ thuộc vào writer: row group, nén, metadata và phiên bản thư viện. Hai lần
ghi cùng dữ liệu logic có thể khác byte, nên so SHA-256 file dễ báo "khác" sai. Ngược lại,
byte giống nhau chỉ là may mắn của cùng writer, không phải bằng chứng logic. C02 so digest
của các dòng đã sắp xếp (`content_equal: true`), còn hai sổ CSV thì so SHA-256 vì CSV được
xuất có thứ tự cố định. Run `-01` và `-02` tình cờ cũng trùng byte Parquet, nhưng nhóm không
lấy đó làm bằng chứng. Hạn chế: C02 hiện chỉ đảo ngược thứ tự envelope, chưa xáo trộn ngẫu
nhiên như đề gợi ý.

**6. `TRY_CAST` trả NULL thì xử lý thế nào để không dòng nào lọt mà không phân loại?**
`TRY_CAST`/`try_strptime` chỉ tránh làm hỏng cả batch. NULL sinh ra phải được biến thành lý
do có tên:

- `reading` không ép được hoặc không hữu hạn (`isfinite`) → `NUMERIC`;
- `event_time` không parse được → `TIME_PARSE`;
- `ingest_time` không parse được → `INGEST_PARSE` ở bước prekey (trước khử trùng);
- trường bắt buộc rỗng hoặc chỉ khoảng trắng → `REQUIRED`.

Mọi điều kiện được bọc để giá trị không xác định không bao giờ ngầm PASS. Dòng curated là
dòng có danh sách lý do rỗng, không phải dòng "không bị lỗi nào bắt". C01 là lưới an toàn
cuối: một dòng không được phân loại sẽ thành "mất" trong anti-join.
