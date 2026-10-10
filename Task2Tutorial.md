# Task 2 – Data Quality Tutorial & Handover for Task 3

## 1. Mục tiêu

Task 2 đánh giá **chất lượng dữ liệu trước curation** (before-curation) dựa trên dữ liệu envelope do Task 1 tạo ra.

Task 2 hiện đã hoàn thành phần **Task 2A – Before Curation**:

- Chuẩn hóa schema giữa CSV và JSONL.
- Phân loại lỗi prekey.
- Xác định `key_eligible`.
- Deduplication (khử trùng lặp).
- Chọn `winner` và tạo tập `W`.
- Tính 6 quality metrics (chỉ số chất lượng).
- Phân tích các loại lỗi chính.
- Sinh `quality_before.json` tự động từ SQL.
- Chạy các kiểm thử denominator = 0, reproducibility và NULL mutation.

Phần **Task 2B – After Curation** chưa thực hiện vì cần chờ Task 3 tạo `curated.parquet`.

---

## 2. Các file chính của Task 2

| File | Chức năng |
|---|---|
| `src/quality.sql` | SQL chính: chuẩn hóa dữ liệu, prekey classification, deduplication, winners, quality metrics và error diagnostics |
| `src/generate_quality_before.py` | Chạy `quality.sql` và sinh `quality_before.json` tự động |
| `evidence/task2/quality_before.json` | Báo cáo chất lượng trước curation |
| `evidence/task2/error_diagnostics.txt` | Thống kê lỗi chính và sample `source_object/source_row` |
| `evidence/task2/quality_tests.json` | Evidence cho các kiểm thử Task 2 |

Task 2 sử dụng trực tiếp dữ liệu từ Task 1:

```text
/work/envelopes.jsonl
/work/staged/sensors.csv
```

Không commit `/work/envelopes.jsonl` hoặc raw data lên Git.

---

## 3. Điều kiện trước khi chạy lại Task 2

```bash
cd ~/lab2-bigdata
source env.sh
kubectl get pod curate -n "$NS"
```

Pod `curate` phải ở trạng thái `Running/Ready`.

Kiểm tra input:

```bash
kubectl exec -n "$NS" curate -- \
  ls -lh /work/envelopes.jsonl /work/staged/sensors.csv
```

Kết quả hiện tại:

```text
/work/envelopes.jsonl        ~4.1 MiB
/work/staged/sensors.csv     256 bytes
```

Nếu `/work/envelopes.jsonl` bị mất, cần chạy lại Task 1 vì `/work` sử dụng `emptyDir`.

---

## 4. Cấu trúc dữ liệu đầu vào

Envelope có các trường:

```text
source_object
source_row
parse_status
payload
```

### CSV – `observations_a.csv`

```text
record_id
sensor_id
event_time
ingest_time
reading
unit
operator_email
```

### JSONL – `observations_b.jsonl`

```text
id
sensor
timestamp
arrived_at
temperature
temperature_unit
operator
```

### Mapping (ánh xạ)

| CSV | JSONL | Canonical |
|---|---|---|
| `record_id` | `id` | `record_id` |
| `sensor_id` | `sensor` | `sensor_id` |
| `event_time` | `timestamp` | `event_raw/event_ts` |
| `ingest_time` | `arrived_at` | `ingest_raw/ingest_ts` |
| `reading` | `temperature` | `reading_raw` |
| `unit` | `temperature_unit` | `unit` |
| `operator_email` | `operator` | restricted, không dùng trong release |

Không hiển thị hoặc ghi raw `operator_email` vào evidence.

---

## 5. Kiểm tra số lượng raw records

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

Kết quả hiện tại:

```text
OK          = 10200
PARSE_ERROR = 5
Total       = 10205
```

---

## 6. Prekey classification

Prekey classification (phân loại trước khi khử trùng lặp):

```text
PARSE
KEY
INGEST_PARSE
ELIGIBLE
```

Ý nghĩa:

- `PARSE`: raw JSON không parse được.
- `KEY`: `record_id` thiếu hoặc không khớp `^R[0-9]{6}$`.
- `INGEST_PARSE`: `ingest_time` không parse được.
- `ELIGIBLE`: đủ điều kiện tham gia deduplication.

Kết quả:

```text
ELIGIBLE       = 10160
KEY            =    20
INGEST_PARSE   =    20
PARSE          =     5
TOTAL          = 10205
```

---

## 7. `key_eligible`, deduplication và winners

Chỉ record có:

```text
prekey_status = 'ELIGIBLE'
```

mới được tham gia deduplication.

Quy tắc chọn winner:

```text
PARTITION BY record_id

ORDER BY
    ingest_ts DESC,
    source_object ASC,
    source_row ASC
```

Kết quả:

```text
key_eligible_rows = 10160
winner_rows       = 9960
duplicate_rows    = 200
```

Kiểm tra winner:

```text
winner_rows              = 9960
distinct_record_ids      = 9960
duplicate_ids_in_winners = 0
```

Do đó:

```text
W = 9960
```

`W` là population (quần thể) dùng làm denominator cho quality-before metrics.

Quan trọng: winner được chọn **trước row-validity filtering**. Nếu winner sau đó không hợp lệ thì Task 3 phải quarantine winner đó và **không fallback** về duplicate cũ hơn.

---

## 8. Chạy `quality.sql`

Copy SQL vào Pod:

```bash
kubectl cp src/quality.sql \
  "$NS/curate:/work/quality.sql"
```

Chạy:

```bash
kubectl exec -i -n "$NS" curate -- \
env PYTHONPATH=/work/python-packages python3 - <<'PY'
import duckdb

con = duckdb.connect()
con.execute(open("/work/quality.sql").read())

rows = con.execute("""
    SELECT
        rule_id,
        numerator,
        denominator,
        round(value * 100, 2) AS percent,
        status
    FROM quality_before_metrics
""").fetchall()

for row in rows:
    print(row)
PY
```

Kết quả hiện tại:

```text
completeness           9850 / 9960   98.90%   FAIL
uniqueness             9960 / 9960  100.00%   PASS
value_validity         9710 / 9960   97.49%   FAIL
referential_integrity  9930 / 9960   99.70%   FAIL
temporal_consistency   9890 / 9960   99.30%   FAIL
timeliness             9690 / 9960   97.29%   PASS
```

---

## 9. Ý nghĩa và threshold của 6 metrics

| Metric | Ý nghĩa | Threshold | Kết quả |
|---|---|---:|---:|
| Completeness (độ đầy đủ) | Các field bắt buộc không thiếu | 100% | 98.90% – FAIL |
| Uniqueness (tính duy nhất) | `record_id` của winner không trùng | 100% | 100% – PASS |
| Value Validity (tính hợp lệ giá trị) | reading numeric, finite, unit C/F, nhiệt độ trong `[-30,60]` | 100% | 97.49% – FAIL |
| Referential Integrity (toàn vẹn tham chiếu) | `sensor_id` tồn tại trong `sensors.csv` | 100% | 99.70% – FAIL |
| Temporal Consistency (nhất quán thời gian) | `event_time <= ingest_time <= AS_OF` | 100% | 99.30% – FAIL |
| Timeliness (tính kịp thời) | lag `<= 900` giây | 95% | 97.29% – PASS |

`AS_OF`:

```text
2026-02-09T00:00:00Z
```

Không thay đổi threshold để làm test PASS.

---

## 10. Error diagnostics

Primary reason precedence (thứ tự ưu tiên lý do lỗi):

```text
REQUIRED
NUMERIC
UNIT
RANGE
TIME_PARSE
TIME_ORDER
REFERENCE
```

Kết quả:

```text
REQUIRED    = 110
NUMERIC     = 60
UNIT        = 40
RANGE       = 40
TIME_PARSE  = 40
TIME_ORDER  = 30
REFERENCE   = 30
```

Evidence:

```text
evidence/task2/error_diagnostics.txt
```

Mỗi loại lỗi lưu:

```text
reason
count
sample_source
sample_row
```

Không lưu raw payload hoặc `operator_email`.

---

## 11. Sinh `quality_before.json`

Copy generator:

```bash
kubectl cp src/generate_quality_before.py \
  "$NS/curate:/work/generate_quality_before.py"
```

Chạy:

```bash
kubectl exec -n "$NS" curate -- \
env PYTHONPATH=/work/python-packages \
python3 /work/generate_quality_before.py
```

Kết quả mong đợi:

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

Population hiện tại:

```text
raw_total              = 10205
parse_failures         = 5
key_excluded           = 20
ingest_parse_failures  = 20
key_eligible           = 10160
duplicates             = 200
winners_W              = 9960
```

---

## 12. Các kiểm thử Task 2 đã chạy

### 12.1. Zero denominator test

Nếu:

```text
denominator = 0
```

thì kết quả:

```text
value  = NULL
status = NOT_EVALUATED
```

Kết quả thực tế:

```text
numerator   = 0
denominator = 0
value       = None
status      = NOT_EVALUATED
```

PASS.

### 12.2. Reproducibility test

Reproducibility (khả năng tái lập) được kiểm tra bằng cách sinh `quality_before.json` hai lần rồi so SHA-256.

Hash:

```text
f697c03c68c1681fa4d444d9de5ad2cedf99ec5accd8aecd4e98d89eb4f860fd
```

Hai lần giống nhau.

PASS.

### 12.3. NULL sensor mutation test

Tạo bản sao tạm của `W`, đặt một `sensor_id = NULL`.

Kết quả:

```text
changed_record       = R000101

baseline denominator = 9960
baseline numerator   = 9850

test denominator     = 9960
test numerator       = 9849

numerator change     = -1
```

PASS.

Evidence:

```text
evidence/task2/quality_tests.json
```

---

## 13. File bàn giao cho Task 3

Người làm Task 3 nên đọc:

```text
contracts/contract.json
contracts/curation_decisions.json

src/quality.sql
src/generate_quality_before.py

evidence/task2/quality_before.json
evidence/task2/error_diagnostics.txt
evidence/task2/quality_tests.json
```

Task 3 cũng cần input:

```text
/work/envelopes.jsonl
/work/staged/sensors.csv
```

---

## 14. Các quy tắc Task 3 cần giữ giống Task 2

### Mapping hai nguồn

```text
record_id       <-> id
sensor_id       <-> sensor
event_time      <-> timestamp
ingest_time     <-> arrived_at
reading         <-> temperature
unit            <-> temperature_unit
operator_email  <-> operator
```

### Prekey validation trước deduplication

```text
PARSE
KEY
INGEST_PARSE
```

Record lỗi prekey không tham gia deduplication.

### Winner selection

```text
ROW_NUMBER() OVER (
    PARTITION BY record_id
    ORDER BY
        ingest_time DESC,
        source_object ASC,
        source_row ASC
)
```

### Không fallback

Nếu winner không đạt row validation:

```text
winner -> quarantine
```

Không chọn duplicate cũ hơn thay thế.

### Restricted fields

```text
operator_email
raw_payload
```

không được đưa vào released output.

---

## 15. Conservation baseline để Task 3 đối chiếu

Task 2 đã xác nhận:

```text
raw total          = 10205
prekey rejected    = 45
key eligible       = 10160
duplicates         = 200
winners W          = 9960
```

Bảo toàn:

```text
9960 winners
+ 200 duplicates
+ 45 prekey rejected
= 10205 raw records
```

Task 3 cần đảm bảo mọi physical record cuối cùng được giải thích thông qua:

```text
curated
quarantine
duplicates
```

Không được mất record im lặng.

---

## 16. Task 3 cần bàn giao lại gì cho Task 2

Sau khi curation hoàn thành, Task 2 cần tối thiểu:

```text
curated.parquet
```

và các output/evidence liên quan để kiểm tra conservation.

Sau đó Task 2 tiếp tục:

```text
quality_after.json
QA coverage
QA agreement
before/after chart
C01 conservation cross-check
record_id uniqueness cross-check
```

Task 2 dùng `qa_reference.csv` cho QA evaluation, không dùng QA reference để sửa hoặc chọn dữ liệu.

---

## 17. Trạng thái hiện tại

```text
TASK 2A – BEFORE CURATION

[PASS] Input inspection
[PASS] Cross-source field mapping
[PASS] Prekey classification
[PASS] key_eligible
[PASS] Deduplication
[PASS] Winners / W
[PASS] 6 before-quality metrics
[PASS] Error diagnostics
[PASS] quality_before.json generation
[PASS] Zero-denominator test
[PASS] Reproducibility test
[PASS] NULL mutation test

W = 9960
```

```text
TASK 2B – AFTER CURATION

[WAITING] curated.parquet from Task 3
[TODO] quality_after.json
[TODO] QA coverage
[TODO] QA agreement
[TODO] before/after chart
[TODO] conservation cross-check
[TODO] uniqueness cross-check
```

---

## 18. Kiểm tra nhanh trước khi Task 3 bắt đầu

```bash
cd ~/lab2-bigdata
source env.sh

kubectl get pod curate -n "$NS"

kubectl exec -n "$NS" curate -- \
  ls -lh /work/envelopes.jsonl \
         /work/staged/sensors.csv

python3 -m json.tool \
  evidence/task2/quality_before.json >/dev/null

python3 -m json.tool \
  evidence/task2/quality_tests.json >/dev/null

git status --short
```

Nếu Pod `curate` bị recreate và `/work/envelopes.jsonl` mất, phải tái tạo Task 1 staging/envelope trước khi chạy lại Task 2 hoặc Task 3.

---

## 19. Luồng bàn giao

```text
Task 1
  |
  +-- /work/envelopes.jsonl
  +-- /work/staged/sensors.csv
  |
  v
Task 2A
  |
  +-- canonical_raw
  +-- prekey_classified
  +-- key_eligible = 10160
  +-- duplicates = 200
  +-- W = 9960
  +-- quality_before.json
  +-- diagnostics + tests
  |
  v
Task 3
  |
  +-- curation
  +-- quarantine
  +-- curated.parquet
  |
  v
Task 2B
  |
  +-- quality_after.json
  +-- QA coverage/agreement
  +-- before/after chart
  +-- cross-check
```
