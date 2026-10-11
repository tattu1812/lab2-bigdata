# Lab 2 – Big Data (Task 3: Curation)

Task 3 tuyển chọn dữ liệu từ envelope của Task 1 thành `curated.parquet`, `quarantine.csv`,
`duplicates.csv` mà không làm mất bằng chứng: mỗi physical record `(source_object, source_row)`
xuất hiện **đúng một lần** trong ba tệp này.

## Tệp của Task 3

| Đường dẫn | Vai trò |
|---|---|
| `src/curate.sql` | Pipeline tất định: prekey → dedup → validate winner → join site |
| `src/run_curate.py` | Thay tham số từ `contracts/*.json`, chạy SQL, xuất artifact + hash vào thư mục theo `run_id` |
| `src/test_curate.py` | Kiểm thử C01–C05, ghi `curate-checks.json` |
| `src/build_edge_fixtures.py` | Dựng fixture 4 ca biên (kết quả mong đợi khai báo thủ công) |
| `src/run_task3.sh` | Chạy toàn bộ trên Pod `curate`, kéo artifact/evidence về repo |
| `tests/fixtures/edge/` | `envelopes.jsonl`, `sensors.csv`, `stage-report.json`, `expected.json` |
| `evidence/task3/contract-review.md` | Biên bản review/ký duyệt `contract.json` |

Quy tắc: mọi ngưỡng/đơn vị/khoảng/precedence đọc từ `contracts/contract.json` và
`contracts/curation_decisions.json`; không dùng `qa_reference.csv`; winner lỗi → quarantine,
không fallback; `operator_email`/`raw_payload` không được đọc và không xuất ra.

## Chạy trên Pod (dữ liệu thật)

Điều kiện: Pod `curate` Ready; `/work/envelopes.jsonl`, `/work/staged/sensors.csv`,
`/work/stage-report.json` tồn tại (Task 1); DuckDB tại `/work/python-packages`.

```bash
cd ~/lab2-bigdata
source env.sh
./src/run_task3.sh task3-20261011-01
```

Kỳ vọng:

```text
CONSERVATION: PASS
C01: PASS
C02: PASS
C03: PASS
C04: PASS
C05: PASS
TASK 3 CURATE + C01-C05: PASS
```

Số đếm kỳ vọng nếu dữ liệu khớp baseline Task 2 (`evidence/task2/quality_before.json`):

```text
raw_total        = 10205
prekey_rejected  =    45   (PARSE 5 + KEY 20 + INGEST_PARSE 20)
key_eligible     = 10160
duplicates       =   200
winners (W)      =  9960
quarantine WINNER=   350   (REQUIRED 110, NUMERIC 60, UNIT 40, RANGE 40,
                            TIME_PARSE 40, TIME_ORDER 30, REFERENCE 30)
curated          =  9610
quarantine total =   395
9610 + 395 + 200 = 10205
```

`C01.details.task2_baseline.match = true` xác nhận khớp. Nếu `false`, so `population_summary`
của Task 2 với `counts` trong `run-manifest.json` (nguyên nhân thường gặp: Task 2 dùng `TRY_CAST`
cho timestamp, Task 3 parse đúng `timestamp_format` của contract).

## Chạy cục bộ trên fixture (không cần Pod)

```bash
pip install duckdb
python3 src/build_edge_fixtures.py          # sinh lại fixture (đã có sẵn trong repo)
FX=tests/fixtures/edge
python3 src/run_curate.py --run-id edge-local \
  --contract contracts/contract.json --decisions contracts/curation_decisions.json \
  --sql src/curate.sql --envelopes $FX/envelopes.jsonl --sensors $FX/sensors.csv \
  --stage-report $FX/stage-report.json --out-root /tmp/curate
```

Kỳ vọng:

```text
raw_total=37  prekey_rejected=5  winners=28  duplicates=4  curated=15  quarantine_total=18
CONSERVATION: PASS
```

## Artifact của mỗi run

```text
outputs/curate/<run_id>/
├── candidate/curated.parquet   10 cột theo released_columns, temperature_c DECIMAL(8,2)
├── quarantine.csv              record_id, source_object, source_row, source_sha256,
│                               stage (PREKEY|WINNER), primary_reason, reasons (A|B|…)
├── duplicates.csv              khóa bản bị thay + khóa winner, reason = SUPERSEDED
├── artifact-hashes.json        sha256 + bytes từng tệp
└── run-manifest.json           hash contract/SQL/input, số đếm, phiên bản DuckDB
```

`run_id` đã tồn tại thì dừng, không ghi đè. `outputs/` nằm trong `.gitignore`; commit phần
`evidence/task3/runs/<run_id>/` (chỉ hash và số đếm, không có dữ liệu raw).

## Kiểm thử

| ID | Nội dung | Kỳ vọng |
|---|---|---|
| C01 | raw = curated + quarantine + duplicates; khóa vật lý rời nhau, phủ đủ envelope | PASS |
| C02 | Chạy lại với envelope đảo thứ tự: `quarantine.csv`, `duplicates.csv` trùng sha256; `curated.parquet` trùng nội dung | PASS |
| C03 | Parquet đúng 10 cột/kiểu/thứ tự theo contract, không NULL, không trường nhạy cảm | PASS |
| C04 | 4 ca biên khớp `expected.json`; không rò `operator_email` | PASS |
| C05 | Tính lại 6 metric "sau" từ `curated.parquet` so `release_thresholds` | PASS |

Ca biên (C04):

| Ca | Nội dung |
|---|---|
| EC1 | Winner mới nhất lỗi (`UNIT`) → quarantine, không fallback bản cũ; bản prekey-lỗi không tham gia dedup |
| EC2 | Hòa `ingest_time`: `source_object` ASC rồi `source_row` ASC |
| EC3 | Biên 60/-30 °C, 140/-22 °F, 60.004 → `RANGE`, làm tròn HALF_UP (0.005→0.01, -0.005→-0.01), `NaN`/`inf` → `NUMERIC`, chuẩn hóa trim/upper |
| EC4 | Late đúng 900 s (không late) vs 901 s (late, vẫn giữ); `ingest == as_of` hợp lệ, `as_of + 1 s` → `TIME_ORDER`; đa lý do; `PARSE`/`KEY`/`KEY\|INGEST_PARSE` |

C05 chỉ tính `required_completeness`, `business_key_uniqueness`, `value_validity`,
`sensor_consistency`, `chronology`, `timeliness`; `qa_coverage`/`qa_agreement` thuộc Task 2B.
`C05` sẽ `FAIL` nếu `timeliness` của curated < 0.95 (đúng ngưỡng contract; không chỉnh ngưỡng).

Kết quả chạy: `evidence/task3/runs/<run_id>/curate-checks.json`.

## Lệnh dùng hàng ngày

```bash
# Chuẩn bị phiên làm việc
cd ~/lab2-bigdata && source env.sh

# Kiểm tra Pod và input còn đủ (Pod bị tạo lại thì /work mất → chạy lại Task 1)
kubectl get pod curate -n "$NS"
kubectl exec -n "$NS" curate -- ls -lh /work/envelopes.jsonl /work/staged/sensors.csv /work/stage-report.json

# Kiểm tra contract trước khi chạy
python3 src/validate_contract.py
sha256sum contracts/contract.json contracts/curation_decisions.json

# Chạy mới (mỗi lần phải dùng run_id mới)
./src/run_task3.sh task3-$(date +%Y%m%d)-01

# Xem kết quả run gần nhất
RUN=task3-20261011-01
python3 -m json.tool evidence/task3/runs/$RUN/curate-checks.json | head -40
python3 -m json.tool outputs/curate/$RUN/run-manifest.json
cat outputs/curate/$RUN/artifact-hashes.json

# Xác minh hash artifact sau khi copy/di chuyển
sha256sum outputs/curate/$RUN/candidate/curated.parquet \
          outputs/curate/$RUN/quarantine.csv outputs/curate/$RUN/duplicates.csv

# Liệt kê các run đã có
ls outputs/curate evidence/task3/runs

# Xem nhanh quarantine / duplicates (không chứa dữ liệu nhạy cảm)
head -5 outputs/curate/$RUN/quarantine.csv
head -5 outputs/curate/$RUN/duplicates.csv
cut -d, -f6 outputs/curate/$RUN/quarantine.csv | sort | uniq -c | sort -rn   # theo primary_reason

# Sau khi sửa curate.sql: chạy lại fixture cục bộ và so với expected.json
FX=tests/fixtures/edge; OUT=/tmp/curate-dev; rm -rf $OUT
python3 src/run_curate.py --run-id dev --out-root $OUT \
  --contract contracts/contract.json --decisions contracts/curation_decisions.json \
  --sql src/curate.sql --envelopes $FX/envelopes.jsonl --sensors $FX/sensors.csv \
  --stage-report $FX/stage-report.json
python3 src/test_curate.py --run-id dev --out-root $OUT --evidence-dir $OUT/ev \
  --contract contracts/contract.json --decisions contracts/curation_decisions.json \
  --sql src/curate.sql --envelopes $FX/envelopes.jsonl --sensors $FX/sensors.csv \
  --stage-report $FX/stage-report.json --fixtures $FX
# Trên fixture: C01–C04 = PASS; C05 = FAIL (timeliness 86,7% < 95% do fixture cố ý có bản ghi trễ)

# Dựng lại fixture khi đổi ca biên
python3 src/build_edge_fixtures.py

# Commit evidence (không commit outputs/ hay dữ liệu raw)
git status --short
git add src/curate.sql src/run_curate.py src/test_curate.py src/build_edge_fixtures.py src/run_task3.sh \
        tests/ evidence/task3/ README.md
git commit -m "feat(task3): curation pipeline, C01-C05 evidence"
```

## Bàn giao

- Task 2B: `outputs/curate/<run_id>/candidate/curated.parquet` → `quality_after.json`.
- Task 4: `run-manifest.json` + `artifact-hashes.json` cho catalog/lineage.
- Task 5: ba artifact và hash cho release gate.