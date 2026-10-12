# Task 4 Tutorial – Metadata, Lineage and Retention

## 0. Mục tiêu

Task 4 không tạo lại dữ liệu. Nhiệm vụ là biến các artifact từ Task 1–3
thành tài sản dữ liệu có thể phát hiện, kiểm tra, truy vết và quản lý vòng
đời.

Các deliverable:

- `catalog.json`
- `schemas/catalog.schema.json`
- `src/validate_catalog.py`
- `evidence/task4/lineage.jsonl`
- `evidence/task4/run-record.json`
- `evidence/task4/retention-plan.json`
- `evidence/task4/README.md`
- `Task4Tutorial.md`

Run curation thật đang dùng:

```bash
RUN=task3-20261012-01
BASE="outputs/curate/$RUN"
```

## 1. Artifact nhận từ các task trước

Task 1 cung cấp raw input, staging và envelope. Task 2A cung cấp quality
trước curation. Task 3 áp dụng quy tắc curation. Task 2B kiểm tra quality
sau curation.

Artifact Task 3:

```text
outputs/curate/task3-20261012-01/candidate/curated.parquet
outputs/curate/task3-20261012-01/quarantine.csv
outputs/curate/task3-20261012-01/duplicates.csv
```

Metadata đã xác nhận:

| Artifact | Rows | Size | SHA-256 |
|---|---:|---:|---|
| `curated.parquet` | 9610 | 209500 bytes | `3c9762d7fc0667bc6ca850806e57a71b10e7552acd625251bd8229054046f58d` |
| `quarantine.csv` | 395 | 47225 bytes | `2b7a219a160a71f1cbe7dbcd7c13c9f2f757b5ef75a1382849bb40e88ed3b61b` |
| `duplicates.csv` | 200 | 39817 bytes | `c0c31ea812966ceb25af853c1700e865f9f0202cdb4f49c6cda32e5b1df5256c` |

Raw telemetry gồm 10205 records:

- `observations_a.csv`: 5000 records, 421028 bytes.
- `observations_b.jsonl`: 5205 records, 1037439 bytes.

## 2. Chuẩn bị môi trường

```bash
cd ~/lab2-bigdata
source env.sh
mkdir -p schemas evidence/task4
```

Để kiểm tra Parquet, dùng môi trường có DuckDB:

```bash
source .venv-task2/bin/activate
python -m pip install duckdb
python -c 'import duckdb; print(duckdb.__version__)'
```

Không dán JSON trực tiếp tại dấu nhắc `$`. JSON phải được dán trong
`nano` hoặc trình soạn thảo rồi lưu thành file.

## 3. Tạo `catalog.json`

`catalog.json` là danh mục metadata, không phải bản sao của dữ liệu. Nó cho
biết dataset nằm ở đâu, có bao nhiêu dòng, schema gì, hash nào, owner và
steward là ai, được tạo từ run nào và áp dụng retention policy nào.

Catalog có ba dataset chính:

1. `raw`: raw telemetry với alias `observations_a.csv` và
   `observations_b.jsonl`.
2. `quarantine`: record bị loại khỏi curated.
3. `curated_candidate`: dữ liệu sau curation.

`duplicates.csv` là side artifact được tham chiếu từ `curated_candidate`.
`qa_reference.csv` và `sensors.csv` là input hỗ trợ, không cộng vào số
dòng raw telemetry.

Tạo hoặc viết lại catalog:

```bash
nano catalog.json
```

Mỗi dataset cần các field:

```text
dataset_id, name, version, description, format, location,
row_count, size_bytes, sha256, columns, owner, steward,
source_run_id, quality_report, retention_policy, source_aliases,
source_inputs, dependencies
```

Raw có union columns của hai source:

```text
record_id, sensor_id, event_time, ingest_time, reading, unit,
operator_email, id, sensor, timestamp, arrived_at, temperature,
temperature_unit, operator
```

Raw có tổng kích thước `1458467` bytes, tổng `10205` records. Hash tổng
hợp của hai source được tạo bằng:

```bash
sha256sum \
  data/Lab2-datasets/input/observations_a.csv \
  data/Lab2-datasets/input/observations_b.jsonl \
  | sha256sum
```

Hash hiện tại:

```text
1f73d6aed112f63782481be3297afb9a334850dc28621cfe7a355cbdaf93cbac
```

Kiểm tra syntax:

```bash
python3 -m json.tool catalog.json
```

## 4. Tạo OpenLineage START/COMPLETE

`lineage.jsonl` ghi pipeline bắt đầu và hoàn thành. Hai event phải dùng
cùng một UUID; nếu dùng hai UUID khác nhau thì không chứng minh được chúng
thuộc cùng một run.

```bash
OPENLINEAGE_RUN_ID=$(python3 -c 'import uuid; print(uuid.uuid4())')
EVENT_TIME=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
echo "$OPENLINEAGE_RUN_ID"
echo "$EVENT_TIME"
```

Tạo file:

```bash
nano evidence/task4/lineage.jsonl
```

File phải có đúng hai dòng JSON theo thứ tự `START`, `COMPLETE`. Mỗi event
cần có `eventType`, `eventTime`, `run.runId`, `job`, `producer`, `schemaURL`,
`inputs` và `outputs`. Schema URL dùng OpenLineage 2-0-2 là:

```text
https://openlineage.io/spec/2-0-2/OpenLineage.json#/definitions/RunEvent
```

Kiểm tra:

```bash
wc -l evidence/task4/lineage.jsonl
python3 -c 'import json; p="evidence/task4/lineage.jsonl"; x=[json.loads(l) for l in open(p) if l.strip()]; assert len(x)==2; assert [e["eventType"] for e in x]==["START","COMPLETE"]; assert x[0]["run"]["runId"]==x[1]["run"]["runId"]; print("lineage: OK")'
```

`wc -l` phải là 2. Dòng trống cũng làm số dòng tăng nên không để dòng
trống trong JSONL.

## 5. Tạo `run-record.json`

`run-record.json` là hồ sơ audit của run, liên kết UUID, code, contract,
input manifest, output và reviewer.

Lấy hash code, contract và input:

```bash
sha256sum \
  src/curate.sql \
  src/run_curate.py \
  contracts/contract.json \
  contracts/curation_decisions.json \
  data/trusted_manifest.json
```

Tạo file:

```bash
nano evidence/task4/run-record.json
```

`openlineage_run_id` phải bằng `run.runId` trong `lineage.jsonl`. Output
phải ghi đúng số dòng và SHA-256 thật của ba artifact Task 3.

```bash
python3 -m json.tool evidence/task4/run-record.json >/dev/null \
  && echo "run-record.json: OK"

grep -o '"runId":"[^"]*"' evidence/task4/lineage.jsonl
grep '"openlineage_run_id"' evidence/task4/run-record.json
```

Không được còn placeholder:

```bash
grep -nE '<[^>]+>' \
  evidence/task4/lineage.jsonl \
  evidence/task4/run-record.json
```

## 6. Tạo `retention-plan.json`

Retention plan ghi quyết định lưu giữ/xóa ở chế độ dry-run. Nó không xóa
file thật. Bốn case bắt buộc:

```text
ELIGIBLE
KEEP/HOLD
KEEP/ACTIVE_DEPENDENCY
KEEP/NOT_EXPIRED
```

Tạo file:

```bash
nano evidence/task4/retention-plan.json
```

Mỗi case cần có `dataset_id`, `decision`, `dependency_status`,
`hold_status`, `reason` và `action`. File phải có:

```json
"dry_run": true,
"delete_executed": false
```

Kiểm tra:

```bash
python3 -m json.tool evidence/task4/retention-plan.json
grep -E '"decision"|"dry_run"|"delete_executed"' \
  evidence/task4/retention-plan.json
```

## 7. Tạo schema và semantic validator

JSON Schema kiểm tra cấu trúc, kiểu dữ liệu và hash pattern. Semantic
validator kiểm tra metadata có khớp file thật hay không.

Tạo schema:

```bash
nano schemas/catalog.schema.json
```

Schema phải yêu cầu `catalog_version`, `run_id`, `datasets`, `artifacts`,
ít nhất ba dataset và các field metadata của từng dataset. Hash phải khớp
pattern:

```text
^[0-9a-f]{64}$
```

Tạo validator:

```bash
nano src/validate_catalog.py
```

Validator cần kiểm tra field bắt buộc, file tồn tại, size, SHA-256, row
count và columns. Với Parquet, validator dùng DuckDB.

Chạy:

```bash
source .venv-task2/bin/activate
python src/validate_catalog.py
```

Kết quả đạt:

```text
CATALOG: PASS
WARNING: raw: location S3 chưa kiểm tra trực tiếp
```

Cảnh báo S3 không phải lỗi. Validator kiểm tra artifact local; raw được
ghi nhận bằng S3 location và metadata/hash lấy từ input thật.

## 8. README Task 4

`README.md` là bản tóm tắt 250–400 từ. `Task4Tutorial.md` là hướng dẫn chi
tiết, không thay thế README nếu rubric yêu cầu README riêng.

README cần tóm tắt mục tiêu metadata, curated/quarantine/duplicates,
catalog, OpenLineage, run-record, retention và quality-after evidence.

```bash
wc -w evidence/task4/README.md
```

## 9. Kiểm tra cuối cùng

```bash
python3 -m json.tool catalog.json >/dev/null
python3 -m json.tool evidence/task4/run-record.json >/dev/null
python3 -m json.tool evidence/task4/retention-plan.json >/dev/null
python3 src/validate_catalog.py

ls -lh \
  catalog.json \
  schemas/catalog.schema.json \
  src/validate_catalog.py \
  evidence/task4/lineage.jsonl \
  evidence/task4/run-record.json \
  evidence/task4/retention-plan.json \
  evidence/task4/README.md \
  Task4Tutorial.md
```

Sau Task 4, catalog cho biết dữ liệu nằm ở đâu và có hash nào; lineage cho
biết dữ liệu đi qua pipeline nào; run record cho biết code và contract nào
đã tạo output; validator chứng minh metadata khớp file thật; retention plan
mô tả cách xử lý vòng đời mà chưa xóa file.
