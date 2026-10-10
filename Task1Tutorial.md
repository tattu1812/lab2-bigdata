# Task 1 – Ingestion & Contract

## 1. Mục tiêu

Task 1 chuẩn bị dữ liệu đầu vào cho Task 3 – Curation.

Các công việc chính:

- Đọc dữ liệu từ S3 bucket `research-raw`.
- Xác minh kích thước và SHA-256 của 4 input objects.
- Tạo envelope cho từng observation.
- Giữ lại các dòng JSONL không parse được.
- Kiểm tra data contract theo JSON Schema.
- Thực hiện các kiểm thử I01–I04.
- Lưu evidence phục vụ đánh giá và bàn giao.

## 2. Chuẩn bị môi trường

Chạy trong WSL:

```bash
cd ~/lab2-bigdata
source env.sh

kubectl config current-context
echo "$NS"
kubectl get pods -n "$NS"
```

Môi trường thực hành đã kiểm thử:

- Kubernetes context: `k3d-bigdata`
- Namespace: `bd-g01`
- Pod: `curate`
- S3 endpoint trong cluster: `http://objects:8333`
- S3 bucket nguồn: `research-raw`
- S3 prefix: `lab2/inputs/batch-01`

Yêu cầu trước khi chạy:

- Kubernetes cluster và SeaweedFS đã hoạt động.
- Namespace và Secret `s3-ingestor` đã được cấu hình.
- File `data/trusted_manifest.json` đã có.
- Bộ dữ liệu gốc có tại `data/Lab2-datasets/input/`.
- JSON Schema có tại `data/Lab2-datasets/schemas/observation_contract_schema.json`.
- Python trên WSL có thư viện `jsonschema` để kiểm tra contract.

### 2.1. Tạo Pod nếu chưa tồn tại

```bash
kubectl apply -f manifests/curate.yaml
kubectl wait --for=condition=Ready pod/curate \
  -n "$NS" --timeout=120s
```

Pod sử dụng image được cố định bằng SHA-256 digest, credentials từ Secret `s3-ingestor` và thư mục làm việc `/work`.

**Lưu ý:** `/work` dùng `emptyDir`, nên dữ liệu trong đó sẽ mất nếu Pod bị xóa và tạo lại.

## 3. Chạy S3 Staging và Envelope

Chạy:

```bash
source env.sh
./src/run_task1.sh
```

Script thực hiện:

1. Kiểm tra Pod `curate` đã Ready.
2. Sao chép trusted manifest và các script Python vào Pod.
3. Tải 4 objects từ S3.
4. Kiểm tra kích thước và SHA-256.
5. Tạo envelopes từ dữ liệu trong `/work/staged`.
6. Lưu stage report và envelope report về WSL.

Kết quả mong đợi:

```text
observations_a.csv: PASS
observations_b.jsonl: PASS
qa_reference.csv: PASS
sensors.csv: PASS
STAGING: PASS
PASS: stage-report.json
PASS: envelope-check.json
TASK 1 STAGING + ENVELOPE: PASS
```

### 3.1. Kiểm tra I02 – Envelope

```bash
cat evidence/task1/envelope-check.json
```

Kết quả mong đợi:

- `status`: `PASS`
- `actual_envelopes`: `10205`
- `unique_physical_ids`: `10205`
- `observations_a.csv`: `5000`
- `observations_b.jsonl`: `5205`
- `jsonl_parse_errors`: `5`

Envelope chứa các trường như `source_object`, `source_row`, `parse_status` và `payload`.

Dòng JSONL không hợp lệ được giữ lại với `parse_status = PARSE_ERROR` và `raw_line`.

File `/work/envelopes.jsonl` là dữ liệu trung gian có thể chứa dữ liệu raw; không commit file này lên GitHub.

## 4. Kiểm thử I01–I04

### I01 – Input Integrity

Chạy trên WSL:

```bash
python3 src/check_integrity.py
```

Script đọc dữ liệu từ:

```text
data/Lab2-datasets/input/
```

Đối chiếu kích thước và SHA-256 với:

```text
data/trusted_manifest.json
```

Báo cáo được ghi tại:

```text
outputs/integrity-test.json
```

Để lưu evidence:

```bash
cp outputs/integrity-test.json \
  evidence/task1/integrity-test.json
```

Kết quả mong đợi: `I01: PASS`.

### I02 – Envelope

I02 được thực hiện trong:

```bash
./src/run_task1.sh
```

Báo cáo:

```text
evidence/task1/envelope-check.json
```

Kết quả mong đợi: `PASS`, 10.205 envelopes và 5 JSONL parse errors.

### I03 – Mutation Test

Chạy trên WSL:

```bash
python3 src/test_mutation.py
```

Script tạo bản sao của `observations_a.csv` trong bộ nhớ, thay đổi một byte và kiểm tra SHA-256.

Kết quả mong đợi:

```text
Mutation rejected: True
I03: PASS
```

Evidence:

```text
evidence/task1/mutation-test.json
```

Đây là kiểm thử logic integrity trên bản sao trong bộ nhớ, không thay đổi object trên S3.

### I04 – S3 Access Test

Script I04 phải chạy bên trong Pod có quyền `s3-ingestor`.

Chạy trong WSL:

```bash
source env.sh

kubectl cp src/test_access.py \
  "$NS/curate:/work/test_access.py"

kubectl exec -n "$NS" curate -- \
  python3 /work/test_access.py

kubectl cp \
  "$NS/curate:/work/access-test.json" \
  evidence/task1/access-test.json
```

Kết quả mong đợi:

- Ingestor đọc được object trong `research-raw`.
- Ingestor không ghi được vào `research-release`.
- PUT bị từ chối với `AccessDenied`, HTTP 403.
- Trạng thái I04: `PASS`.

## 5. Kiểm tra Data Contract

Contract chính:

```text
contracts/contract.json
```

JSON Schema:

```text
data/Lab2-datasets/schemas/observation_contract_schema.json
```

Chạy:

```bash
python3 src/validate_contract.py
```

Kết quả mong đợi:

```text
CONTRACT VALIDATION: PASS
Schema version: research-telemetry-v1
AS_OF: 2026-02-09T00:00:00Z
Required fields: 9
```

Các quy tắc triển khai bổ sung nằm trong:

```text
contracts/curation_decisions.json
```

File này làm rõ:

- Prekey validation trước deduplication.
- Bản ghi lỗi prekey không tham gia deduplication.
- Chọn winner trước row validation.
- Invalid winner bị quarantine, không fallback.
- Làm tròn nhiệt độ theo `ROUND_HALF_UP` sau các bước kiểm tra.

Các quyết định bổ sung cần được người phụ trách Task 3 xác nhận trước khi chốt contract cuối cùng.

## 6. Evidence và môi trường chạy

Các báo cáo Task 1 nằm tại:

```text
evidence/task1/
```

Bao gồm:

- `integrity-test.json`
- `envelope-check.json`
- `mutation-test.json`
- `access-test.json`
- `stage-report.json`
- `pip-freeze.txt`
- `python-version.txt`
- `duckdb-version.txt`
- `duckdb-install.txt`
- `image-digest.txt`

Chỉ commit báo cáo và thông tin môi trường được phép công bố.

Không commit dữ liệu raw, credentials hoặc các file chứa thông tin nhạy cảm.

Evidence index của nhóm:

```text
evidence/evidence_index.csv
```

Cần cập nhật thông tin operator, reviewer, command, run ID và input version theo quy trình đánh giá của nhóm.

## 7. Bàn giao cho Task 3 – Curation

Người phụ trách Task 3 cần đọc:

1. `contracts/contract.json`
2. `contracts/curation_decisions.json`
3. `data/trusted_manifest.json`
4. `evidence/task1/stage-report.json`
5. `evidence/task1/envelope-check.json`

Dữ liệu trung gian trong Pod:

```text
/work/staged/
/work/envelopes.jsonl
```

Task 3 cần thống nhất cách gắn `source_sha256` từ trusted manifest và cách ánh xạ `PARSE_ERROR` sang reason `PARSE` khi quarantine.

Các kết quả PASS trong tutorial được ghi nhận từ môi trường thực hành của Task 1. Khi chạy trên cluster chính thức, nhóm cần thực hiện lại kiểm thử và thu thập evidence mới.

## 8. Giới hạn của script tự động

`src/run_task1.sh` tự động hóa staging và envelope, nhưng không tự:

- Tạo cluster hoặc Secret S3.
- Tạo Pod `curate`.
- Cài đặt DuckDB.
- Chạy I01, I03, I04.
- Chốt hoặc phê duyệt contract.

Các bước này phải thực hiện riêng theo hướng dẫn ở trên.

## 9. Kiểm thử tái lập trên Pod mới

Đã thực hiện trên cluster thực hành `k3d-bigdata`, namespace `bd-g01`.

Quy trình:
1. Xóa Pod `curate` cũ.
2. Tạo lại Pod bằng `manifests/curate.yaml`.
3. Chờ Pod ở trạng thái Ready.
4. Chạy lại `./src/run_task1.sh`.

Kết quả:

```text
PASS: stage-report.json
PASS: envelope-check.json
TASK 1 STAGING + ENVELOPE: PASS
```

Kết luận: Pipeline S3 staging và envelope chạy thành công sau khi tạo lại Pod. Việc tái lập toàn bộ các kiểm thử I01–I04 và cài đặt DuckDB chưa nằm trong phạm vi kiểm thử này.
