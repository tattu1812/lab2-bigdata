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
./src/run_task1.sh task1-YYYYMMDD-01
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
./src/run_task1.sh task1-YYYYMMDD-01
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
4. Chạy lại `./src/run_task1.sh task1-YYYYMMDD-01`.

Kết quả:

```text
PASS: stage-report.json
PASS: envelope-check.json
TASK 1 STAGING + ENVELOPE: PASS
```

Kết luận: Pipeline S3 staging và envelope chạy thành công sau khi tạo lại Pod. Việc tái lập toàn bộ các kiểm thử I01–I04 và cài đặt DuckDB chưa nằm trong phạm vi kiểm thử này.

### Quy ước đường dẫn evidence

Các file trực tiếp trong `evidence/task1/` là evidence đã lưu từ những lần kiểm thử trước hoặc các kiểm thử bổ sung.

Mỗi lần chạy mới bằng `src/run_task1.sh <run_id>` sẽ lưu `stage-report.json` và `envelope-check.json` vào `evidence/task1/runs/<run_id>/`. Khi đánh giá kết quả mới, hãy sử dụng báo cáo trong thư mục run tương ứng, không mặc định dùng các file evidence cũ ở thư mục cha.

## 10. Kiểm tra SeaweedFS, S3 Secret và input objects

Thực hiện trước khi chạy pipeline trên cluster thực hành.

```

### 10.1. Kiểm tra cluster và Pod

```bash
source env.sh

kubectl config current-context
echo "$NS"

kubectl get nodes
kubectl get pod curate -n "$NS"
kubectl get svc -n "$NS"
Xác nhận đang dùng đúng cluster và namespace của nhóm. Pod curate phải ở trạng thái Running và Ready.

10.2. Kiểm tra Pod và dịch vụ

kubectl get pod curate -n "$NS"
kubectl get svc -n "$NS"
kubectl describe pod curate -n "$NS"

Nếu Pod chưa tồn tại, tham khảo manifests/curate.yaml và hướng dẫn triển khai hiện có của nhóm để tạo lại Pod. Không tự tạo một cấu hình mới nếu chưa đối chiếu manifest.

10.3. Kiểm tra Secret S3

Liệt kê tên Secret trong namespace:

kubectl get secrets -n "$NS"

Đối chiếu cấu hình Secret với manifests/curate.yaml. Không in giá trị access key hoặc secret key ra terminal log, tài liệu hoặc Git.

Nếu Pod sử dụng Secret thông qua biến môi trường, kiểm tra tham chiếu mà không đọc giá trị credential:

kubectl get pod curate -n "$NS" \
  -o jsonpath='{range .spec.containers[*]}{"Container: "}{.name}{"\n"}{range .env[*]}{.name}{" -> "}{.valueFrom.secretKeyRef.name}{"/"}{.valueFrom.secretKeyRef.key}{"\n"}{end}{end}'

Lưu ý: Lệnh này chỉ hiển thị các tham chiếu Secret được khai báo trực tiếp trong env; nó không hiển thị đầy đủ mọi hình thức cấu hình môi trường.

10.4. Kiểm tra manifest và input objects

Kiểm tra manifest:

python3 -m json.tool data/trusted_manifest.json

Bốn object cần được xác minh trong bucket research-raw:

lab2/inputs/batch-01/observations_a.csv

lab2/inputs/batch-01/observations_b.jsonl

lab2/inputs/batch-01/qa_reference.csv

lab2/inputs/batch-01/sensors.csv

Đối chiếu object key, kích thước và SHA-256 với data/trusted_manifest.json.

Khả năng đọc thực tế được xác minh trong bước staging ở mục 11. Nếu staging thất bại, kiểm tra endpoint S3, Secret, quyền đọc, bucket và object key trước khi chạy lại.

Không tự ghi đè hoặc sửa dữ liệu nguồn để làm cho kiểm thử PASS.

## 11. Chạy staging và tạo raw envelopes

11.1. Tạo run ID

Mỗi lần chạy phải sử dụng một run_id mới, chưa tồn tại.

Ví dụ:

./src/run_task1.sh task1-20261010-03

Thay ngày và số thứ tự bằng giá trị phù hợp với lần chạy thực tế. Không sử dụng nguyên chuỗi YYYYMMDD làm ngày chạy.

11.2. Những việc script tự động thực hiện

src/run_task1.sh:

Kiểm tra biến NS.

Chờ Pod curate ở trạng thái Ready.

Sao chép manifest và các script cần thiết vào Pod.

Chạy staging dữ liệu từ S3.

Kiểm tra kích thước và SHA-256 của bốn input objects.

Tạo raw envelopes từ CSV và JSONL.

Lưu stage-report.json và envelope-check.json vào evidence/task1/runs/<run_id>/.

Kiểm tra trạng thái hai báo cáo và kết thúc bằng thông báo PASS hoặc lỗi.

Script không tự tạo cluster, Secret hoặc Pod; không tự cài DuckDB; không tự chạy toàn bộ I01, I03 và I04.

11.3. Kết quả kỳ vọng

Staging: PASS.

Tổng envelopes: 10.205.

observations_a.csv: 5.000 envelopes.

observations_b.jsonl: 5.205 envelopes.

JSONL parse errors: 5.

Physical keys trùng lặp: 0.

Kiểm tra báo cáo trong evidence/task1/runs/<run_id>/ của lần chạy vừa thực hiện. Nếu bất kỳ điều kiện nào không đạt, không xác nhận Task 1 hoàn thành cho lần chạy đó.

## 12. Chạy kiểm thử I01–I04

12.1. I01 – Kiểm tra integrity

Chạy:

python3 src/check_integrity.py

Kiểm tra evidence/task1/integrity-test.json. Kết quả mong đợi là PASS cho cả bốn input objects.

I01 đối chiếu kích thước và SHA-256 với trusted manifest.

12.2. I02 – Kiểm tra envelope

Chạy pipeline theo mục 11, sau đó kiểm tra envelope-check.json.

Kết quả mong đợi:

10.205 envelopes.

10.205 unique physical IDs.

5.000 CSV records.

5.205 JSONL physical lines.

5 JSONL parse errors được giữ lại.

12.3. I03 – Kiểm tra mutation

Chạy:

python3 src/test_mutation.py

Kiểm tra evidence/task1/mutation-test.json. Kết quả mong đợi là PASS: thay đổi một byte trong bản sao phải làm thất bại kiểm tra integrity.

Script không chủ ý sửa file input gốc.

12.4. I04 – Kiểm tra quyền S3

Kiểm tra cấu hình credential và identity được yêu cầu trong đề bài trước khi chạy:

kubectl exec -n "$NS" curate -- \
  python3 /work/test_access.py

Lệnh trên chỉ phù hợp khi script đã được sao chép vào Pod và môi trường xác thực S3 đã được cấu hình đúng.

Kết quả đã ghi nhận trước đây cho identity ingestor:

GET từ research-raw: PASS.

PUT vào research-release: bị từ chối với AccessDenied, HTTP 403.

Báo cáo I04: PASS.

Cần xác nhận với nhóm rằng identity này đúng với yêu cầu chính thức của bài lab. Không coi kết quả của một identity là bằng chứng cho mọi identity khác.

## 13. Kiểm tra I02 SQL bằng DuckDB

Đây là kiểm tra bổ sung bằng SQL, không thay thế I02 envelope hoặc các kiểm thử I01, I03, I04.

13.1. Điều kiện tiên quyết

Cần có:

/work/envelopes.jsonl trong Pod curate.

src/check_i02_sql.py trong repository.

Python trong Pod.

DuckDB có thể import được trong Python.

13.2. Kiểm tra DuckDB

kubectl exec -n "$NS" curate -- \
  env PYTHONPATH=/work/python-packages \
  python3 -c "import duckdb; print(duckdb.__version__)"

Phiên bản đã kiểm thử là 1.4.1.

Nếu chưa cài DuckDB, cài vào thư mục riêng:

kubectl exec -n "$NS" curate -- \
  python3 -m pip install \
  --no-cache-dir \
  --target /work/python-packages \
  duckdb==1.4.1

Nếu Pod được tạo lại, thư mục cài đặt trong Pod có thể mất và cần được chuẩn bị lại.

13.3. Sao chép script và chạy SQL

kubectl cp src/check_i02_sql.py \
  "$NS/curate:/work/check_i02_sql.py"

kubectl exec -n "$NS" curate -- \
  env PYTHONPATH=/work/python-packages \
  python3 /work/check_i02_sql.py

Kết quả mong đợi:

DuckDB: 1.4.1.

Tổng envelopes: 10205.

CSV: 5000.

JSONL: 5205.

Duplicate physical keys: 0.

JSONL parse errors: 5.

Status: PASS.

13.4. Lưu và xác minh SQL evidence

mkdir -p evidence/task1

kubectl cp \
  "$NS/curate:/work/i02-sql-check.json" \
  evidence/task1/i02-sql-check.json

Xác minh:

python3 - <<'PY'
import json
from pathlib import Path

path = Path("evidence/task1/i02-sql-check.json")
report = json.loads(path.read_text(encoding="utf-8"))

assert report["status"] == "PASS"
assert report["total_envelopes"] == 10205
assert report["source_counts"]["observations_a.csv"] == 5000
assert report["source_counts"]["observations_b.jsonl"] == 5205
assert report["duplicate_physical_keys"] == 0
assert report["jsonl_parse_errors"] == 5

print("I02 SQL EVIDENCE: PASS")
PY

Sau khi xác minh, cập nhật evidence/evidence_index.csv theo định dạng hiện có, ghi đúng operator, reviewer nếu đã review, run ID, input version và đường dẫn evidence.

Nếu cần lưu nhiều lần chạy độc lập, sử dụng quy ước thư mục run ID mà nhóm thống nhất và cập nhật evidence index tương ứng.

## 14. Kiểm tra contract và evidence

14.1. Contract validation

python3 src/validate_contract.py

Kết quả mong đợi: CONTRACT VALIDATION: PASS.

14.2. Kiểm tra báo cáo JSON

python3 -m json.tool evidence/task1/integrity-test.json >/dev/null
python3 -m json.tool evidence/task1/envelope-check.json >/dev/null
python3 -m json.tool evidence/task1/mutation-test.json >/dev/null
python3 -m json.tool evidence/task1/access-test.json >/dev/null
python3 -m json.tool evidence/task1/stage-report.json >/dev/null
python3 -m json.tool evidence/task1/i02-sql-check.json >/dev/null

Các lệnh trên chỉ kiểm tra cú pháp JSON. Để xác nhận một kiểm thử PASS, phải kiểm tra trường status trong báo cáo tương ứng.

14.3. Kiểm tra Git

git diff --check
git status --short

Không commit dữ liệu raw, credential, file envelopes.jsonl hoặc evidence chứa dữ liệu nhạy cảm.


## 15. Bàn giao và giới hạn kiểm thử

- Các kết quả đã ghi nhận được thu thập trên cluster thực hành.
- Khi chạy trên cluster chính thức của nhóm, cần thực hiện lại các kiểm thử cần thiết và thu thập evidence mới.
- I04 cần được đối chiếu với identity được yêu cầu trong đề bài.
- Field mapping hiện ở trạng thái PARTIAL và cần reviewer xác nhận.
- Staging và envelope PASS không đồng nghĩa các task curation hoặc release đã hoàn thành.
