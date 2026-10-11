# Task 2 – Data Quality Tutorial hoàn chỉnh (Task 2A + Task 2B)

## 1. Mục tiêu

Task 2 có nhiệm vụ đo **chất lượng dữ liệu (Data Quality)** bằng các số liệu có thể tính lại được từ SQL, với mỗi metric đều có:

- `rule_id`: mã quy tắc.
- `dataset_version`: phiên bản dataset.
- `cohort`: quần thể dùng để đánh giá.
- `numerator`: tử số.
- `denominator`: mẫu số.
- `value`: tỷ lệ `numerator / denominator`.
- `threshold`: ngưỡng chấp nhận.
- `severity`: mức độ lỗi.
- `status`: `PASS`, `FAIL` hoặc `NOT_EVALUATED`.

Task 2 gồm hai phần:

```text
Task 2A – Before Curation
Đo chất lượng trước khi Task 3 loại/quarantine dữ liệu lỗi.

Task 2B – After Curation
Đo lại chất lượng sau khi Task 3 tạo curated.parquet,
đánh giá QA reference, vẽ biểu đồ trước/sau
và tự cross-check lại conservation + uniqueness.
```

Trạng thái hiện tại:

```text
TASK 2A – COMPLETED
TASK 2B – COMPLETED
```

---

# 2. Luồng tổng thể

```text
Task 1
  |
  +-- /work/envelopes.jsonl
  +-- /work/staged/sensors.csv
  +-- /work/staged/qa_reference.csv
  |
  v
Task 2A
  |
  +-- canonical/typed data
  +-- prekey classification
  +-- key_eligible = 10160
  +-- duplicates = 200
  +-- winners W = 9960
  +-- quality_before.json
  +-- diagnostics + tests
  |
  v
Task 3
  |
  +-- curated.parquet = 9610
  +-- quarantine.csv = 395
  +-- duplicates.csv = 200
  |
  v
Task 2B
  |
  +-- quality_after.json
  +-- QA coverage = 100/100
  +-- QA agreement = 95/100
  +-- before/after chart
  +-- independent C01 cross-check
  +-- record_id uniqueness cross-check
```

---

# 3. Các file chính của Task 2

| File | Chức năng |
|---|---|
| `src/quality.sql` | SQL chính cho Task 2A: chuẩn hóa, prekey, deduplication, winners, before-quality metrics và diagnostics |
| `src/generate_quality_before.py` | Chạy `quality.sql` và sinh `quality_before.json` |
| `src/quality_after.sql` | SQL cho Task 2B: tính quality metrics trên `curated.parquet` và QA reference |
| `src/generate_quality_after.py` | Chạy `quality_after.sql` và sinh `quality_after.json` |
| `src/generate_quality_chart.py` | Sinh biểu đồ before/after trực tiếp từ hai JSON |
| `evidence/task2/quality_before.json` | Báo cáo chất lượng trước curation |
| `evidence/task2/quality_after.json` | Báo cáo chất lượng sau curation |
| `evidence/task2/error_diagnostics.txt` | Thống kê lỗi + sample `source_object/source_row` |
| `evidence/task2/quality_tests.json` | Evidence cho các test Task 2A |
| `evidence/task2/quality_before_after.png` | Biểu đồ trước/sau |
| `evidence/task2/task2_crosscheck_after.json` | Evidence cross-check độc lập C01 + uniqueness |

Không commit raw input hoặc dữ liệu staging tạm trong `/work`.

---

# 4. Điều kiện trước khi chạy lại

Vào repo và load biến môi trường:

```bash
cd ~/lab2-bigdata
source env.sh
```

Kiểm tra Pod:

```bash
kubectl get pod curate -n "$NS"
```

Pod `curate` phải ở trạng thái:

```text
1/1 Running
```

Kiểm tra các input cần thiết:

```bash
kubectl exec -n "$NS" curate -- \
  ls -lh \
    /work/envelopes.jsonl \
    /work/staged/sensors.csv \
    /work/staged/qa_reference.csv
```

Lưu ý:

```text
/work
```

được mount bằng `emptyDir`, nên nếu Pod bị recreate thì dữ liệu trong `/work` có thể mất.

Nếu `envelopes.jsonl` hoặc staging bị mất, phải chạy lại bước recovery/staging của Task 1 trước.

---

# 5. Cấu trúc input từ Task 1

Envelope có các trường chính:

```text
source_object
source_row
parse_status
payload
```

## 5.1 Nguồn CSV – `observations_a.csv`

```text
record_id
sensor_id
event_time
ingest_time
reading
unit
operator_email
```

## 5.2 Nguồn JSONL – `observations_b.jsonl`

```text
id
sensor
timestamp
arrived_at
temperature
temperature_unit
operator
```

## 5.3 Mapping – ánh xạ về schema chung

| CSV | JSONL | Canonical |
|---|---|---|
| `record_id` | `id` | `record_id` |
| `sensor_id` | `sensor` | `sensor_id` |
| `event_time` | `timestamp` | `event_raw/event_ts` |
| `ingest_time` | `arrived_at` | `ingest_raw/ingest_ts` |
| `reading` | `temperature` | `reading_raw` |
| `unit` | `temperature_unit` | `unit` |
| `operator_email` | `operator` | restricted, không release |

Không đưa raw `operator_email`, `operator` hay raw payload vào evidence public/release.

---

# 6. Raw population – quần thể dữ liệu gốc

Tổng input đã xác nhận:

```text
OK          = 10200
PARSE_ERROR =     5
--------------------
TOTAL       = 10205
```

Có thể kiểm tra lại:

```bash
kubectl exec -i -n "$NS" curate -- python3 - <<'PY'
import json
from collections import Counter

c = Counter()

with open("/work/envelopes.jsonl") as f:
    for line in f:
        r = json.loads(line)
        c[r.get("parse_status")] += 1

print(c)
print("Total:", sum(c.values()))
PY
```

---

# 7. Prekey classification – phân loại trước khi dedup

Các nhóm:

```text
PARSE
KEY
INGEST_PARSE
ELIGIBLE
```

Ý nghĩa:

- `PARSE`: payload không parse được.
- `KEY`: `record_id` thiếu hoặc không đúng pattern.
- `INGEST_PARSE`: `ingest_time` không parse được.
- `ELIGIBLE`: đủ điều kiện tham gia deduplication.

Kết quả:

```text
ELIGIBLE       = 10160
KEY            =    20
INGEST_PARSE   =    20
PARSE          =     5
----------------------
TOTAL          = 10205
```

Tổng prekey rejected:

```text
20 + 20 + 5 = 45
```

---

# 8. `key_eligible`, deduplication và winners

Chỉ những dòng:

```text
prekey_status = 'ELIGIBLE'
```

mới tham gia deduplication.

Quy tắc chọn winner:

```sql
ROW_NUMBER() OVER (
    PARTITION BY record_id
    ORDER BY
        ingest_ts DESC,
        source_object ASC,
        source_row ASC
)
```

Kết quả:

```text
key_eligible_rows = 10160
winner_rows       =  9960
duplicate_rows    =   200
```

Winner kiểm tra:

```text
winner_rows              = 9960
distinct_record_ids      = 9960
duplicate_ids_in_winners = 0
```

Do đó:

```text
W = 9960
```

Quan trọng:

- Winner được chọn **trước row-validity filtering**.
- Nếu winner mới nhất bị lỗi, Task 3 phải quarantine winner đó.
- Không được fallback về duplicate cũ hơn chỉ vì duplicate cũ hợp lệ.

---

# 9. Population/denominator đúng cho Task 2A

Không phải mọi metric trước curation đều dùng cùng một denominator.

| Metric | Cohort/denominator đúng |
|---|---|
| Completeness | `W = 9960` |
| Uniqueness | `KEY_ELIGIBLE = 10160` |
| Value validity | `W = 9960` |
| Referential integrity | `W = 9960` |
| Temporal consistency | `W = 9960` |
| Timeliness | chỉ các dòng `W` có temporal sequence hợp lệ = `9890` |

Hai điểm dễ nhầm:

### Uniqueness

Uniqueness trước curation phải phản ánh duplicate còn tồn tại **trước khử trùng**, nên:

```text
numerator   = 9960 distinct business IDs/winners
denominator = 10160 key-eligible physical records
```

Không dùng `9960/9960`.

### Timeliness

Timeliness chỉ được đánh giá trên các dòng có:

```text
event_time <= ingest_time <= AS_OF
```

Do đó denominator là số dòng temporal-valid:

```text
9890
```

không phải toàn bộ W.

---

# 10. Kết quả Task 2A – Before Curation

Kết quả cuối cùng sau khi sửa đúng denominator:

| Metric | Numerator / Denominator | Value | Status |
|---|---:|---:|---|
| Completeness | `9850 / 9960` | 98.90% | FAIL |
| Uniqueness | `9960 / 10160` | 98.03% | FAIL |
| Value validity | `9710 / 9960` | 97.49% | FAIL |
| Referential integrity | `9930 / 9960` | 99.70% | FAIL |
| Temporal consistency | `9890 / 9960` | 99.30% | FAIL |
| Timeliness | `9690 / 9890` | 97.98% | PASS |

Threshold:

```text
Completeness            100%
Uniqueness              100%
Value validity          100%
Referential integrity   100%
Temporal consistency    100%
Timeliness               95%
```

`AS_OF` dùng trong bài:

```text
2026-02-09T00:00:00Z
```

Không thay threshold sau khi nhìn thấy kết quả.

---

# 11. Ý nghĩa 6 quality metrics trước/sau

## 11.1 Completeness – độ đầy đủ

Kiểm tra các field bắt buộc có dữ liệu:

```text
record_id
sensor_id
event_time
ingest_time
reading
unit
```

`NULL` phải được tính là lỗi, không được loại khỏi denominator.

---

## 11.2 Uniqueness – tính duy nhất

Kiểm tra business key:

```text
record_id
```

Before:

```text
9960 / 10160 = 98.03%
```

After:

```text
9610 / 9610 = 100%
```

---

## 11.3 Value validity – hợp lệ giá trị

Temperature phải:

- parse numeric được;
- finite;
- unit hợp lệ;
- quy đổi về Celsius;
- nằm trong `[-30, 60] °C`.

---

## 11.4 Referential integrity – toàn vẹn tham chiếu

`sensor_id` sau chuẩn hóa phải tồn tại trong:

```text
/work/staged/sensors.csv
```

---

## 11.5 Temporal consistency – nhất quán thời gian

Điều kiện:

```text
event_time <= ingest_time <= AS_OF
```

---

## 11.6 Timeliness – tính kịp thời

Chỉ tính trên các dòng đã temporal-valid.

Điều kiện PASS cho từng dòng:

```text
lag_seconds <= 900
```

Threshold toàn metric:

```text
>= 95%
```

---

# 12. Error diagnostics – chẩn đoán lỗi Task 2A

Primary reason precedence:

```text
REQUIRED
NUMERIC
UNIT
RANGE
TIME_PARSE
TIME_ORDER
REFERENCE
```

Số lượng:

```text
REQUIRED    = 110
NUMERIC     =  60
UNIT        =  40
RANGE       =  40
TIME_PARSE  =  40
TIME_ORDER  =  30
REFERENCE   =  30
```

Evidence:

```text
evidence/task2/error_diagnostics.txt
```

Mỗi nhóm lỗi lưu:

```text
reason
count
sample_source
sample_row
```

Không ghi email thô.

---

# 13. Các kiểm thử Task 2A

## 13.1 Zero denominator – mẫu số bằng 0

Nếu:

```text
denominator = 0
```

thì phải trả:

```text
value  = null
status = NOT_EVALUATED
```

Kết quả test: PASS.

---

## 13.2 Reproducibility – tái lập

Sinh `quality_before.json` nhiều lần với cùng input phải cho cùng kết quả logic/JSON.

Kết quả test: PASS.

---

## 13.3 NULL mutation – đột biến NULL

Tạo một bản sao W và đặt một `sensor_id = NULL`.

Kết quả đã kiểm tra:

```text
baseline denominator = 9960
test denominator     = 9960

baseline numerator   = 9850
test numerator       = 9849

numerator change     = -1
```

Điều này chứng minh NULL không bị biến mất khỏi denominator.

Evidence:

```text
evidence/task2/quality_tests.json
```

---

# 14. Chạy lại Task 2A

Copy SQL:

```bash
kubectl cp \
  src/quality.sql \
  "$NS/curate:/work/quality.sql"
```

Copy generator:

```bash
kubectl cp \
  src/generate_quality_before.py \
  "$NS/curate:/work/generate_quality_before.py"
```

Chạy:

```bash
kubectl exec -n "$NS" curate -- \
env PYTHONPATH=/work/python-packages \
python3 /work/generate_quality_before.py
```

Kỳ vọng:

```text
Generated: /work/quality_before.json
Metrics: 6
W: 9960
```

Copy về repo:

```bash
kubectl cp \
  "$NS/curate:/work/quality_before.json" \
  evidence/task2/quality_before.json
```

Kiểm tra:

```bash
python3 -m json.tool \
  evidence/task2/quality_before.json
```

Kiểm tra nhanh uniqueness và timeliness:

```bash
python3 - <<'PY'
import json

x = json.load(open("evidence/task2/quality_before.json"))

for m in x["metrics"]:
    if m["rule_id"] in ["uniqueness", "timeliness"]:
        print(
            m["rule_id"],
            f'{m["numerator"]}/{m["denominator"]}',
            m["cohort"],
            m["value"],
            m["status"]
        )
PY
```

Kết quả đúng:

```text
timeliness 9690/9890 W_TEMPORAL_VALID ... PASS
uniqueness 9960/10160 KEY_ELIGIBLE ... FAIL
```

---

# 15. Kết quả bàn giao từ Task 3

Task 3 đã hoàn thành curation.

Run đã dùng trong lần kiểm tra hiện tại:

```text
task3-local-20261011-1324
```

Kết quả:

```text
raw_total          = 10205
prekey_rejected    =    45
key_eligible       = 10160
duplicates         =   200
winners            =  9960
quarantine_winner  =   350
curated            =  9610
quarantine_total   =   395
```

Bảo toàn:

```text
9610 curated
+395 quarantine
+200 duplicates
-----------------
10205 raw records
```

Task 3 outputs:

```text
outputs/curate/<run_id>/candidate/curated.parquet
outputs/curate/<run_id>/quarantine.csv
outputs/curate/<run_id>/duplicates.csv
```

Current example:

```text
outputs/curate/task3-local-20261011-1324/candidate/curated.parquet
```

---

# 16. Task 2B – After Curation

Task 2B dùng:

```text
/work/curated.parquet
/work/staged/sensors.csv
/work/staged/qa_reference.csv
```

Mục tiêu:

1. Tính lại quality metrics sau curation.
2. Đánh giá QA coverage – độ phủ tham chiếu.
3. Đánh giá QA agreement – độ khớp tham chiếu.
4. Vẽ biểu đồ before/after.
5. Tự cross-check C01 conservation.
6. Tự kiểm tra uniqueness của `record_id` trên curated.

---

# 17. Đưa `curated.parquet` vào Pod

Nếu file chưa có trong Pod:

```bash
RUN=task3-local-20261011-1324

kubectl cp \
  "outputs/curate/$RUN/candidate/curated.parquet" \
  "$NS/curate:/work/curated.parquet"
```

Kiểm tra:

```bash
kubectl exec -n "$NS" curate -- \
  ls -lh /work/curated.parquet
```

Schema curated hiện tại:

```text
record_id         VARCHAR
sensor_id         VARCHAR
site              VARCHAR
event_time_utc    TIMESTAMP
ingest_time_utc   TIMESTAMP
temperature_c     DECIMAL(8,2)
is_late           BOOLEAN
source_object     VARCHAR
source_row        BIGINT
source_sha256     VARCHAR
```

Số dòng:

```text
9610
```

Restricted fields như `operator_email` và `raw_payload` không xuất hiện.

---

# 18. Chạy `quality_after.sql`

Copy SQL:

```bash
kubectl cp \
  src/quality_after.sql \
  "$NS/curate:/work/quality_after.sql"
```

Copy generator:

```bash
kubectl cp \
  src/generate_quality_after.py \
  "$NS/curate:/work/generate_quality_after.py"
```

Chạy:

```bash
kubectl exec -n "$NS" curate -- \
env PYTHONPATH=/work/python-packages \
python3 /work/generate_quality_after.py
```

Kỳ vọng:

```text
Generated: /work/quality_after.json
Metrics: 8
Curated: 9610
QA: 100
```

Copy về repo:

```bash
kubectl cp \
  "$NS/curate:/work/quality_after.json" \
  evidence/task2/quality_after.json
```

---

# 19. Kết quả Task 2B – After Curation

Kết quả cuối:

| Metric | Numerator / Denominator | Value | Status |
|---|---:|---:|---|
| Completeness | `9610 / 9610` | 100% | PASS |
| Uniqueness | `9610 / 9610` | 100% | PASS |
| Value validity | `9610 / 9610` | 100% | PASS |
| Referential integrity | `9610 / 9610` | 100% | PASS |
| Temporal consistency | `9610 / 9610` | 100% | PASS |
| Timeliness | `9410 / 9610` | 97.92% | PASS |
| QA coverage | `100 / 100` | 100% | PASS |
| QA agreement | `95 / 100` | 95% | PASS |

Population chính:

```text
curated_total = 9610
qa_total      = 100
qa_covered    = 100
qa_agreed     = 95
```

---

# 20. Denominator đúng cho Task 2B

| Metric | Cohort/denominator |
|---|---|
| Completeness | curated |
| Uniqueness | curated |
| Value validity | curated |
| Referential integrity | curated |
| Temporal consistency | curated |
| Timeliness | curated temporal-valid |
| QA coverage | toàn bộ 100 QA reference IDs |
| QA agreement | chỉ các QA IDs tìm thấy trong curated |

Trong dataset hiện tại:

```text
qa_total      = 100
qa_covered    = 100
```

nên:

```text
qa_agreement denominator = qa_covered = 100
```

Nếu sau này coverage < 100 thì QA agreement **không được chia cho toàn bộ 100**; phải chia cho số QA IDs thực sự được tìm thấy.

---

# 21. QA Coverage – độ phủ tham chiếu

Logic:

```text
qa_reference
LEFT JOIN curated
USING (record_id)
```

Coverage:

```text
số QA record_id tìm thấy trong curated
--------------------------------------
tổng số QA reference record_id
```

Kết quả:

```text
100 / 100 = 100%
```

PASS.

QA reference chỉ dùng để **evaluation – đánh giá**, không được dùng để lựa chọn, sửa hoặc làm sạch dữ liệu.

---

# 22. QA Agreement – độ khớp tham chiếu

Một QA record được coi là agreement nếu:

```text
abs(temperature_c - reference_c) <= 0.05
```

Denominator:

```text
số QA IDs đã covered
```

Kết quả:

```text
95 / 100 = 95%
```

Threshold:

```text
>= 95%
```

PASS.

---

# 23. So sánh Before và After

Tóm tắt:

| Metric | Before | After | Nhận xét |
|---|---:|---:|---|
| Completeness | 98.90% FAIL | 100% PASS | Dòng thiếu required field đã bị quarantine |
| Uniqueness | 98.03% FAIL | 100% PASS | 200 duplicate đã được tách |
| Value validity | 97.49% FAIL | 100% PASS | Winner lỗi value đã bị quarantine |
| Referential integrity | 99.70% FAIL | 100% PASS | Sensor không hợp lệ đã bị quarantine |
| Temporal consistency | 99.30% FAIL | 100% PASS | Dòng temporal-invalid đã bị quarantine |
| Timeliness | 97.98% PASS | 97.92% PASS | Late data vẫn được giữ/report theo policy |

Điểm quan trọng:

**Quality tăng sau curation không có nghĩa dữ liệu gốc tự nhiên tốt hơn.**

Nó có nghĩa candidate curated chỉ giữ các record đáp ứng các rule phát hành, trong khi lỗi được chuyển sang quarantine/duplicates và vẫn được contabilize/bảo toàn.

---

# 24. Sinh biểu đồ Before/After

Script:

```text
src/generate_quality_chart.py
```

Chạy trong môi trường có `matplotlib`:

```bash
source .venv-task2/bin/activate
python src/generate_quality_chart.py
```

Output:

```text
evidence/task2/quality_before_after.png
```

Biểu đồ phải:

- đọc trực tiếp từ JSON metric;
- có nhãn Before/After;
- hiển thị `n/d`;
- thể hiện từng metric riêng;
- không tạo một **aggregate quality score – điểm chất lượng gộp**.

Nhãn trục hiện dùng:

```text
Metric value (%)
```

không dùng `Quality score (%)` để tránh hiểu nhầm thành một điểm tổng hợp.

---

# 25. Cross-check độc lập C01 của Task 2B

Task 2 không được chỉ tin kết quả C01 của Task 3.

Task 2 phải tự viết truy vấn độc lập để xác nhận:

1. Conservation – bảo toàn.
2. Anti-join – không thiếu record.
3. Anti-join ngược – không có record thừa.
4. Không overlap giữa curated/quarantine/duplicates.
5. `record_id` trên curated là duy nhất.

Headers hiện tại:

```text
quarantine.csv
record_id,source_object,source_row,source_sha256,stage,primary_reason,reasons

duplicates.csv
record_id,source_object,source_row,source_sha256,reason,
winner_source_object,winner_source_row,winner_source_sha256
```

Số dòng:

```text
quarantine.csv = 396 lines = 395 records + header
duplicates.csv = 201 lines = 200 records + header
```

---

# 26. Chuẩn bị dữ liệu để cross-check

Copy artifact vào Pod:

```bash
RUN=task3-local-20261011-1324

kubectl cp \
  "outputs/curate/$RUN/quarantine.csv" \
  "$NS/curate:/work/task2_quarantine.csv"

kubectl cp \
  "outputs/curate/$RUN/duplicates.csv" \
  "$NS/curate:/work/task2_duplicates.csv"
```

Kiểm tra đủ 4 nguồn:

```bash
kubectl exec -n "$NS" curate -- \
  ls -lh \
    /work/envelopes.jsonl \
    /work/curated.parquet \
    /work/task2_quarantine.csv \
    /work/task2_duplicates.csv
```

---

# 27. Kết quả independent cross-check

Kết quả cuối:

```text
raw_total                          = 10205
raw_distinct_physical_keys         = 10205

curated_total                      = 9610
quarantine_total                   = 395
duplicates_total                   = 200

output_union_distinct_physical_keys = 10205

missing_from_outputs               = 0
extra_in_outputs                   = 0

curated_vs_quarantine              = 0
curated_vs_duplicates              = 0
quarantine_vs_duplicates           = 0

curated_distinct_record_ids        = 9610
curated_duplicate_record_ids       = 0

overall                            = PASS
```

Evidence:

```text
evidence/task2/task2_crosscheck_after.json
```

Giải thích:

```text
9610 + 395 + 200 = 10205
```

chỉ chứng minh arithmetic conservation – bảo toàn theo số lượng.

Các anti-join và overlap check mới chứng minh mạnh hơn rằng:

- không record vật lý nào bị mất;
- không record lạ nào xuất hiện;
- không một physical key nào nằm ở hai output classification khác nhau.

---

# 28. Physical key và business key

## Physical key – khóa vật lý

```text
(source_object, source_row)
```

Dùng để xác định **một dòng vật lý cụ thể** trong input.

Nó được dùng cho:

- conservation;
- anti-join;
- lineage;
- sample lỗi;
- kiểm tra overlap.

## Business key – khóa nghiệp vụ

```text
record_id
```

Dùng để xác định cùng một observation logic/nghiệp vụ và phục vụ:

- deduplication;
- winner selection;
- uniqueness của curated.

Hai loại khóa không thay thế cho nhau.

---

# 29. Kiểm tra nhanh toàn bộ kết quả cuối

Có thể chạy:

```bash
python3 - <<'PY'
import json

before = json.load(open("evidence/task2/quality_before.json"))
after = json.load(open("evidence/task2/quality_after.json"))
cross = json.load(open("evidence/task2/task2_crosscheck_after.json"))

B = {m["rule_id"]: m for m in before["metrics"]}
A = {m["rule_id"]: m for m in after["metrics"]}

checks = {
    "before_uniqueness":
        B["uniqueness"]["numerator"] == 9960
        and B["uniqueness"]["denominator"] == 10160
        and B["uniqueness"]["status"] == "FAIL",

    "before_timeliness":
        B["timeliness"]["numerator"] == 9690
        and B["timeliness"]["denominator"] == 9890
        and B["timeliness"]["status"] == "PASS",

    "after_curated":
        A["completeness"]["denominator"] == 9610,

    "after_uniqueness":
        A["uniqueness"]["numerator"] == 9610
        and A["uniqueness"]["denominator"] == 9610
        and A["uniqueness"]["status"] == "PASS",

    "qa_coverage":
        A["qa_coverage"]["numerator"] == 100
        and A["qa_coverage"]["denominator"] == 100,

    "qa_agreement":
        A["qa_agreement"]["numerator"] == 95
        and A["qa_agreement"]["denominator"] == 100
        and A["qa_agreement"]["cohort"] == "QA_COVERED",

    "crosscheck":
        cross["overall"] == "PASS",
}

for k, v in checks.items():
    print(f"{k:25s}", "PASS" if v else "FAIL")

print("\nOVERALL:", "PASS" if all(checks.values()) else "FAIL")
PY
```

Kết quả hiện tại:

```text
before_uniqueness         PASS
before_timeliness         PASS
after_curated             PASS
after_uniqueness          PASS
qa_coverage               PASS
qa_agreement              PASS
crosscheck                PASS

OVERALL: PASS
```

---

# 30. Trạng thái cuối Task 2

```text
TASK 2A – BEFORE CURATION

[PASS] Input inspection
[PASS] Cross-source field mapping
[PASS] Prekey classification
[PASS] key_eligible
[PASS] Deduplication
[PASS] Winner/W construction
[PASS] Correct denominator by cohort
[PASS] 6 before-quality metrics
[PASS] Error diagnostics
[PASS] quality_before.json
[PASS] Zero-denominator test
[PASS] Reproducibility test
[PASS] NULL mutation test

W = 9960
```

```text
TASK 2B – AFTER CURATION

[PASS] curated.parquet handoff from Task 3
[PASS] quality_after.json
[PASS] Completeness after
[PASS] Uniqueness after
[PASS] Value validity after
[PASS] Referential integrity after
[PASS] Temporal consistency after
[PASS] Timeliness after
[PASS] QA coverage = 100/100
[PASS] QA agreement = 95/100
[PASS] Before/after chart
[PASS] Independent conservation cross-check
[PASS] Anti-join missing = 0
[PASS] Anti-join extra = 0
[PASS] Output overlap = 0
[PASS] Curated record_id uniqueness
[PASS] Overall final self-check
```

---

# 31. Git – chỉ commit file thuộc Task 2

Các file Task 2B cần commit:

```text
src/quality.sql
src/quality_after.sql
src/generate_quality_after.py
src/generate_quality_chart.py

evidence/task2/quality_before.json
evidence/task2/quality_after.json
evidence/task2/quality_before_after.png
evidence/task2/task2_crosscheck_after.json
```

Không dùng:

```bash
git add .
```

nếu working tree còn các artifact local khác.

Các thư mục local không thuộc Task 2B:

```text
.venv-task2/
evidence/task1/runs/...
evidence/task3/runs/...
```

không cần commit trong Task 2B.

Commit Task 2B đã tạo:

```text
e3eaf02 Complete Task 2B quality after curation and cross-checks
```

---

# 32. Một số lỗi thường gặp

## 32.1 `python3: can't open file '/work/generate_quality_before.py'`

Nguyên nhân:

Pod đã recreate và file trong `/work` mất.

Khắc phục:

```bash
kubectl cp \
  src/generate_quality_before.py \
  "$NS/curate:/work/generate_quality_before.py"
```

Sau đó chạy lại generator.

---

## 32.2 `tar: Removing leading '/' from member names`

Ví dụ:

```text
tar: Removing leading `/' from member names
```

Đây là thông báo bình thường của `kubectl cp`, không phải lỗi.

---

## 32.3 DuckDB Out Of Memory

Pod có giới hạn RAM thấp.

`generate_quality_after.py` hiện cấu hình:

```python
con.execute("SET threads=1")
con.execute("SET preserve_insertion_order=false")
con.execute("SET memory_limit='256MB'")
con.execute("SET temp_directory='/work/duckdb_tmp'")
```

Và các intermediate counts quan trọng được materialize thành `TEMP TABLE` để giảm memory pressure.

---

## 32.4 `git diff` bị đứng ở màn hình có dấu `:`

Đó là pager `less`.

Thoát bằng:

```text
q
```

Hoặc xem diff không dùng pager:

```bash
git --no-pager diff --cached
```

---

## 32.5 Copy cả prompt terminal rồi Bash báo `command not found`

Không copy dòng dạng:

```text
(.venv-task2) nhannhan@Trung:~/lab2-bigdata$
```

Chỉ copy phần command.

---

# 33. Các câu cần hiểu để báo cáo giảng viên

## Vì sao population Before không phải toàn bộ 10,205 raw?

Vì raw còn chứa:

- parse error;
- invalid key;
- ingest timestamp không parse được;
- duplicate physical versions.

Metric row-level cần đánh giá trên cohort được định nghĩa rõ, không trộn những dòng chưa đủ điều kiện vào cùng denominator.

---

## Vì sao uniqueness Before dùng 10,160 thay vì W = 9,960?

Vì uniqueness phải đo mức trùng lặp **trước deduplication**.

Nếu dùng:

```text
9960 / 9960
```

thì duplicate đã bị loại trước khi đo và metric sẽ luôn 100%, làm mất ý nghĩa.

Đúng là:

```text
9960 / 10160 = 98.03%
```

---

## Vì sao timeliness chỉ dùng temporal-valid rows?

Nếu một dòng có timestamp parse lỗi hoặc:

```text
event_time > ingest_time
```

thì không thể diễn giải lag thời gian một cách hợp lệ.

Do đó timeliness phải có denominator là những dòng đã đạt temporal consistency.

---

## Vì sao quality After tốt hơn không đồng nghĩa raw data tốt hơn?

Vì Task 3 đã phân loại dữ liệu:

```text
good candidate -> curated
bad winner     -> quarantine
duplicate      -> duplicates
```

Candidate tốt hơn là do curation, không phải các lỗi ban đầu biến mất khỏi lịch sử.

---

## Vì sao QA agreement cao chưa đủ?

Ví dụ nếu chỉ tìm được:

```text
10 / 100 QA IDs
```

và cả 10 đều agreement:

```text
agreement = 100%
coverage  = 10%
```

thì không thể nói candidate đã được QA tốt trên toàn tập tham chiếu.

Vì vậy phải báo cáo **cả coverage và agreement**.

---

## Vì sao không gộp tất cả metric thành một quality score?

Các metric đo các loại rủi ro khác nhau.

Một average score có thể che giấu lỗi nghiêm trọng, ví dụ:

```text
Completeness = 100%
Uniqueness   = 100%
Temporal     = 100%
Reference    = 0%
```

Một điểm trung bình vẫn có thể trông cao dù reference validation hoàn toàn thất bại.

Do đó bài yêu cầu từng metric có `n/d`, threshold và status riêng.

---

# 34. Checklist trước khi bàn giao Task 2

```text
[ ] quality_before.json parse được
[ ] quality_after.json parse được
[ ] uniqueness before = 9960/10160
[ ] timeliness before = 9690/9890
[ ] curated_total = 9610
[ ] uniqueness after = 9610/9610
[ ] timeliness after = 9410/9610
[ ] QA coverage = 100/100
[ ] QA agreement = 95/100
[ ] chart được sinh trực tiếp từ JSON
[ ] chart có Before/After và n/d
[ ] không có aggregate quality score
[ ] crosscheck overall = PASS
[ ] missing_from_outputs = 0
[ ] extra_in_outputs = 0
[ ] overlap = 0
[ ] curated duplicate record_id = 0
[ ] không leak operator_email/raw_payload
[ ] không commit .venv-task2
[ ] không commit evidence Task 1/Task 3 ngoài phạm vi
```

---

# 35. Kết luận

Task 2 hiện đã hoàn thành cả hai giai đoạn:

```text
Task 2A – đo chất lượng trước curation
Task 2B – đo chất lượng sau curation + QA + cross-check
```

Các con số chính:

```text
RAW                           10205

KEY_ELIGIBLE                  10160
DUPLICATES                      200
W                              9960

CURATED                        9610
QUARANTINE                      395
DUPLICATES                      200

QA COVERAGE                  100/100
QA AGREEMENT                  95/100

MISSING FROM OUTPUTS                0
EXTRA IN OUTPUTS                   0
OUTPUT OVERLAP                     0
CURATED DUPLICATE record_id        0
```

Conservation cuối:

```text
9610 + 395 + 200 = 10205
```

Task 2B final self-check:

```text
OVERALL: PASS
```
