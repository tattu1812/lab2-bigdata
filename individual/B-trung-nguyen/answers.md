# Trung Nguyễn – Vai B / Quality (Task 2)


## 1. Thay đổi kỹ thuật tự viết

**`src/quality.sql` + `src/generate_quality_before.py`.** Mỗi metric được tính bằng
`count(*) FILTER (WHERE …)` trên một cohort rõ ràng. JSON ghi riêng tử số, mẫu số, cohort,
ngưỡng và trạng thái. Báo cáo còn tách `population_summary`: raw 10.205, parse lỗi 5,
loại vì khóa 20, ingest không parse được 20, key-eligible 10.160, trùng 200, W 9.960.

Test (`evidence/task2/quality_tests.json`):

- `ZERO_DENOMINATOR`: cohort rỗng cho `value = null`, `NOT_EVALUATED`.
- `NULL_SENSOR_COMPLETENESS`: đặt `sensor_id` của `R000101` thành NULL thì mẫu số giữ
  nguyên 9.960 còn tử số giảm từ 9.850 xuống 9.849.
- `REPRODUCIBILITY`: hai lần chạy cho cùng SHA-256 `f697c03c…`.

Ngày 12/10, `quality_before.json` và `quality_after.json` được chạy lại trên Pod mới và ra
giống hệt.

## 2. Kiểm tra chéo: C01 và tính duy nhất của Khánh (vai C)

**Dự đoán.** 10.205 = 9.610 + 395 + 200. Không mất, không thừa, không chồng lấn khóa vật
lý. 9.610 `record_id` khác nhau trong curated.

**Chạy** (trong Pod `curate`, truy vấn riêng, không dùng `test_curate.py`):

```bash
python3 c01_crosscheck.py --envelopes /work/envelopes.jsonl \
  --artifacts <outputs/curate/task3-20261012-01> --out c01-crosscheck.json
```

**Diễn giải** (`individual/B-trung-nguyen/c01-crosscheck.json`, PASS):

- Anti-join hai chiều cho thấy mất 0, thừa 0.
- 0 khóa nằm ở hơn một output; giao từng cặp output đều bằng 0.
- 9.610 `record_id` khác nhau và 0 NULL.

Tổng bằng nhau chưa đủ, vì một dòng mất cộng một dòng trùng vẫn cho tổng đúng. Anti-join
và đếm chồng lấn mới chứng minh được đó là một phân hoạch. Lần kiểm tra trước
(`evidence/task2/task2_crosscheck_after.json`) chạy trên run nháp; lần này chạy trên đúng
candidate đã công bố.

## 3. Quyết định thiết kế đã giải thích

Mỗi metric dùng mẫu số theo đúng cohort của nó, không dùng một mẫu số chung:

- uniqueness trước curation: 9.960/10.160 (key-eligible, trước khử trùng);
- timeliness: chỉ tính trên 9.890 dòng đúng trình tự;
- các metric còn lại: tính trên W = 9.960.

## 4. Câu hỏi cá nhân

**1. Vì sao population "trước" là W mà không phải 10.205 dòng raw?**
Trong 10.205 dòng có 45 dòng hỏng từ trước khi có khóa (5 PARSE, 20 KEY, 20 INGEST_PARSE)
và 200 bản bị thay thế. Các dòng đó không phải "quan trắc" để đo chất lượng giá trị: dòng
hỏng không có trường nào, còn bản bị thay thế không bao giờ được chọn. Tính trên raw sẽ đếm
một quan trắc nhiều lần và trộn lỗi cấu trúc với lỗi giá trị. W = 9.960 là tập winner tất
định, mỗi `record_id` một dòng, chính là tập curation sẽ phán xét. Các loại trừ vẫn được
báo cáo riêng trong `population_summary`, nên không bị giấu.

**2. Đếm tử số sao cho NULL tính là lỗi; vì sao lọc NULL ở mẫu số là sai?**

```sql
SELECT count(*) AS denominator,
       count(*) FILTER (WHERE COALESCE(sensor_id IS NOT NULL AND trim(sensor_id) <> '', false)) AS numerator
FROM winners;
```

Mẫu số là `count(*)` của cả cohort. Một predicate cho ra NULL thì không thỏa `FILTER`, nên
dòng đó bị tính là lỗi. Nếu viết `WHERE sensor_id IS NOT NULL` cho cả truy vấn, dòng NULL
biến mất khỏi mẫu số và tỷ lệ tăng giả tạo. Đây đúng là thứ test
`NULL_SENSOR_COMPLETENESS` bắt: mẫu số phải giữ nguyên 9.960.

**3. Độ đầy đủ tăng sau khi xóa dòng lỗi có nghĩa là dữ liệu tốt hơn không?**
Không hẳn. Completeness từ 9.850/9.960 (98,9%) lên 9.610/9.610 (100%) chỉ vì 350 winner
lỗi đã bị đưa vào quarantine (110 REQUIRED, 60 NUMERIC, 40 UNIT, 40 RANGE, 40 TIME_PARSE,
30 TIME_ORDER, 30 REFERENCE). Không giá trị thiếu nào được khôi phục. Phải báo cáo kèm:

- tỷ lệ giữ lại: 9.610/9.960 = 96,5%;
- tỷ lệ bị từ chối: 350/9.960 = 3,5%;
- 200 quan trắc muộn vẫn được giữ (timeliness 9.410/9.610).

Release "sạch hơn", nhưng ít quan trắc hơn và không đại diện cho các cảm biến hay khoảng
thời gian bị loại.

**4. Phân biệt độ hợp lệ, độ khớp tham chiếu, độ phủ tham chiếu.**
- **Hợp lệ** kiểm giá trị có thỏa luật: là số hữu hạn, đơn vị C/F, nằm trong [−30, 60] °C.
- **Khớp** so với mẫu tham chiếu: 95/100 ID lệch ≤ 0,05 °C.
- **Phủ** đo mẫu tham chiếu có mặt đủ trong candidate: 100/100.

`R000810`–`R000814` hợp lệ nhưng lệch 8,00 °C so với tham chiếu, tức là hợp lệ không có
nghĩa là đúng. Độ khớp cao cũng chỉ nói về 100 ID được lấy mẫu. 9.510 dòng còn lại không có
tham chiếu, nên không chứng minh mọi phép đo đều chính xác.

**5. Vì sao mẫu số của tính kịp thời chỉ gồm các dòng đúng trình tự?**
`lag = ingest − event` chỉ có nghĩa khi cả hai timestamp parse được và
`event ≤ ingest ≤ AS_OF`. Dòng sai trình tự (lag âm, hoặc ingest sau AS_OF) không thể xếp
vào "kịp thời" hay "muộn". Đưa chúng vào mẫu số sẽ trộn lỗi thời gian vào chỉ số độ trễ.
Vì vậy trước curation là 9.690/9.890; 70 dòng bị loại khỏi mẫu số đã được nêu riêng ở metric
nhất quán thời gian (9.890/9.960).

**6. Vì sao không gộp 7 chiều thành một "điểm chất lượng"?**
Các chiều khác đơn vị đo, khác cohort và khác mức nghiêm trọng. Một điểm gộp như "97%" có
thể che một chiều bắt buộc đang FAIL: trước curation, uniqueness chỉ 98,0% và 5/6 metric
FAIL. Nó cũng không cho biết phải sửa gì. Mỗi ngưỡng phát hành áp dụng cho từng chiều, nên
biểu đồ `quality_before_after.png` vẽ từng metric riêng với n/d và trục ghi
"Metric value (%)".
