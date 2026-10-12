# Task 5 – Release Gate, Publish và Consumer

## 0. Mục tiêu

Chỉ công bố candidate khi gate tự tính lại đủ 9 kiểm tra G01–G09 **và** có một
người review độc lập (không phải tác giả curation). Phải chứng minh được ba điều:
gate từ chối đúng 7 ca đột biến, bản release khớp hash 100%, và analyst đọc được
release nhưng không đọc được raw.

## 1. Tệp của Task 5

| Tệp | Vai trò |
|---|---|
| `src/gate.py` | 9 hàm G01–G09, mỗi hàm tự đọc candidate/input/metadata/lineage và trả `{check, category, status, observed, reasons}`. Mọi exception → `BLOCKED`. |
| `src/gate_tests.py` | Tạo 8 ca P01–P08 trên bản sao, chạy gate, thử publish các ca bị REJECT. |
| `src/publish.py` | Gate → review → chống ghi đè → lineage START → upload + verify → manifest cuối cùng → lineage COMPLETE. |
| `src/consumer_check.py` | Phía analyst: kiểm hash, đếm dòng, GET raw (phải 403), ca bị REJECT không có manifest. |
| `src/crosscheck_qa.py` | Truy vấn riêng, tính lại độ phủ và độ khớp QA, so với `quality_after.json`. |
| `src/run_task5.sh` | Điều phối các bước trên qua `kubectl`. |
| `manifests/publisher.yaml`, `manifests/consumer.yaml` | Pod `publisher` (s3-owner) và `consumer` (s3-analyst). |

Evidence nằm trong `evidence/task5/`; mỗi lần chạy có thư mục riêng `evidence/task5/runs/<id>/`.

## 2. Pod

```bash
source env.sh
./src/run_task5.sh setup
```

Namespace có quota `limits.cpu=4`, `limits.memory=4Gi` và đã dùng hết 3,5 CPU/3,5Gi,
nên hai Pod này được đặt limit `250m/256Mi` mỗi Pod thay vì `500m/512Mi`. Như vậy
không phải xóa Pod nào của nhóm. 256Mi đủ cho DuckDB xử lý 9.610 dòng.

Quyền S3 (đọc từ `s3-config`, không in credential):

| Principal | Quyền |
|---|---|
| `owner` (publisher) | Admin, Read, Write, List mọi bucket |
| `analyst` (consumer) | Read, List chỉ trên `research-release` |

## 3. Gate G01–G09

Gate không đọc bất kỳ trường `status`/`passed` nào do task trước ghi ra. Mỗi lần
chạy, `run_task5.sh` dựng một bundle mới trong Pod publisher: artifact và metadata
lấy từ repo, còn 4 input **tải lại từ S3** và kiểm với trusted manifest.

| Check | Category | Tự tính lại |
|---|---|---|
| G01 | INPUT_INTEGRITY | bytes + SHA-256 của bản sao input so với trusted manifest; `source_sha256` trong candidate; hash input trong run-record và run-manifest |
| G02 | SCHEMA | 10 cột, đúng thứ tự và kiểu theo `released_columns`; không có `operator_email`/`raw_payload` |
| G03 | REQUIRED | Không có NULL ở mọi cột released |
| G04 | VALUE | Nhiệt độ trong [-30, 60], `record_id` đúng mẫu, sensor/site khớp registry, `event ≤ ingest ≤ as_of`, `is_late` nhất quán, timeliness ≥ 0.95 |
| G05 | UNIQUENESS | `record_id` và khóa vật lý `(source_object, source_row)` duy nhất |
| G06 | RECONCILIATION | Khóa vật lý tính lại từ chính file nguồn = curated ⊔ quarantine ⊔ duplicates; số đếm và hash khớp run-manifest |
| G07 | METADATA | Catalog đủ field (có `steward`), size/hash/rows/columns khớp file thật; run-record khớp hash code/contract/output |
| G08 | LINEAGE | START/COMPLETE cùng `runId` = run-record; COMPLETE có đủ 3 output, đúng `rowCount` |
| G09 | COVERAGE | QA coverage = 100/100 và agreement ≥ 0.95, so sánh bằng `Decimal` với dung sai 0.05 °C |

Quyết định: `PASS` khi đủ 9/9; có `BLOCKED` → `BLOCKED`; còn lại → `REJECT`.
Exit code 0/1/2.

## 4. Kiểm thử đột biến P01–P08

```bash
./src/run_task5.sh gate-tests task3-20261012-01 gatetest-20261012-02 release-20261012
```

Mỗi ca copy bundle gốc sang `/work/gate-tests/<test_id>/<case>/` rồi mới sửa.
Raw trên S3 không bao giờ bị ghi. Digest của bundle gốc được đo trước và sau khi
chạy để chứng minh nó không đổi (`base_bundle_unchanged: true`).

Kết quả lần chạy `gatetest-20261012-02`:

| Ca | Thay đổi | Gate | Category bị bắt | Publish |
|---|---|---|---|---|
| P01 | Không sửa | PASS 9/9 | – | – |
| P02 | `R000381.temperature_c = 100.00` | REJECT 6/9 | **VALUE** (9609/9610) | REFUSED |
| P03 | `R000381.temperature_c = NULL` | REJECT 5/9 | **REQUIRED**, **VALUE** | REFUSED |
| P04 | Thêm dòng trùng `R000381` | REJECT 5/9 | **UNIQUENESS**, **RECONCILIATION** (10206 ≠ 10205) | REFUSED |
| P05 | Xóa `steward` của `curated_candidate` | REJECT 8/9 | **METADATA** | REFUSED |
| P06 | Đổi 1 byte bản sao `observations_a.csv` | REJECT 8/9 | **INPUT_INTEGRITY** | REFUSED |
| P07 | Xóa output `duplicates.csv` khỏi COMPLETE | REJECT 8/9 | **LINEAGE** | REFUSED |
| P08 | Xóa `R000810` (QA lệch) khỏi candidate | REJECT 5/9 | **COVERAGE** (99/100) | REFUSED |

Các ca sửa parquet cũng làm G06/G07/G08 FAIL, vì hash và số dòng không còn khớp
run-manifest/catalog/lineage. Điều này là đúng; test chỉ yêu cầu category mục tiêu
nằm trong danh sách FAIL. Mỗi ca có `gate-report.json` riêng trong
`evidence/task5/runs/gatetest-20261012-02/`.

Ca bị REJECT được đưa qua `publish.py` với `release_id = release-20261012-<case>`.
Publish dừng ở bước gate, `s3_writes = 0`.

## 5. Kiểm tra chéo QA

```bash
./src/run_task5.sh crosscheck task3-20261012-01 qacheck-20261012-01
```

Truy vấn so sánh bằng `DECIMAL(9,2)` thay vì `DOUBLE`, đếm phủ bằng INNER JOIN và
liệt kê id thiếu bằng anti-join. Kết quả: coverage 100/100, agreement 95/100, khớp
`quality_after.json`. 5 bản ghi lệch là `R000810`–`R000814`, mỗi bản lệch 8,00 °C.
Không có cặp nào nằm đúng biên 0,05, nên DOUBLE và DECIMAL cho cùng kết quả.

## 6. Review độc lập

```bash
./src/run_task5.sh review-request task3-20261012-01 release-20261012-02
```

Lệnh này chạy gate trên một bundle mới và ghi `review-request.json`, gồm run ID,
hash candidate và mẫu review. Người review (không phải Khánh, tác giả curation) điền
`evidence/task5/review.json`:

```json
{
  "reviewer": "<tên>",
  "curation_author": "Khánh",
  "decision": "APPROVE",
  "reason": "<lý do>",
  "run_id": "task3-20261012-01",
  "candidate_sha256": "3c9762d7fc0667bc6ca850806e57a71b10e7552acd625251bd8229054046f58d",
  "reviewed_at": "YYYY-MM-DDTHH:MM:SSZ"
}
```

`publish.py` từ chối nếu `decision` khác `APPROVE`, nếu reviewer trùng tác giả
curation, hoặc nếu `run_id`/`candidate_sha256` khác candidate thực sự được gate.

`review.json` của `release-20261012-01/-02` đã công bố ghi `curation_author: "Tú"`,
nhưng phân vai đúng là Khánh. Reviewer là Hải Anh nên điều kiện độc lập vẫn đúng.
Chi tiết ở `evidence/task5/erratum-curation-author.md`.

## 7. Công bố

```bash
./src/run_task5.sh publish task3-20261012-01 release-20261012-02
```

Giao thức trong `publish.py`:

1. Chạy lại gate trên chính bundle sắp công bố → phải PASS 9/9.
2. Kiểm review.
3. `list_objects_v2` trên `lab2/releases/<release_id>/` phải trống, nên không ghi đè release cũ.
4. Ghi lineage publish **START** (`runId` mới).
5. Upload `curated.parquet`, `catalog.json`, `gate-report.json`, `review.json`. Sau mỗi
   object, tải lại và so SHA-256.
6. Ghi `release_manifest.json` **sau cùng**, tải lại và so byte.
7. Ghi lineage **COMPLETE** kèm SHA-256 của từng object và của manifest.

`quarantine.csv`/`duplicates.csv` không vào release. Chúng chỉ nằm trong bản nộp hạn chế.

## 8. Phía analyst

```bash
./src/run_task5.sh consume release-20261012-02 \
  release-20261012-P02,release-20261012-P03,release-20261012-P04,release-20261012-P05,release-20261012-P06,release-20261012-P07,release-20261012-P08
```

Pod `consumer` (s3-analyst) tải manifest và từng object rồi kiểm hash. Nó kiểm
manifest có `LastModified` muộn nhất, đếm dòng parquet bằng DuckDB, GET
`research-raw/.../sensors.csv` (phải 403), và kiểm 7 release bị REJECT không có
manifest cũng như không có object nào. Kết quả nằm ở `evidence/task5/consumer-check.json`.

Kết quả với `release-20261012-02` (principal `analyst`):

| Kiểm tra | Kết quả |
|---|---|
| Hash từng object so với manifest | 4/4 khớp |
| Manifest ghi sau cùng | PASS (cùng giây với object cuối, xem lưu ý) |
| Số dòng `curated.parquet` | 9610 = manifest, 9610 `record_id` khác nhau |
| Sổ quarantine/duplicates trong release | Không có |
| GET `research-raw/.../sensors.csv` | `AccessDenied`, HTTP 403 |
| 7 release P02–P08 | Không có manifest (HEAD 404), 0 object |

**Lưu ý:** `LastModified` của S3 chỉ chính xác đến từng giây. Manifest trùng giây
với object cuối, nên check này chỉ chứng minh được manifest "không sớm hơn". Bằng
chứng về thứ tự ghi là `publish-result.json` cùng code: manifest chỉ được ghi sau
khi mọi object đã upload và verify.

Cũng đã thử ghi đè: publish lại `release-20261012-01` bị `REFUSED`
(`prefix ... đã có 5 object`, `s3_writes: 0`).

**Incident:** `release-20261012-01` mang `reviewed_at` ghi sai (muộn hơn lúc publish),
nên đã bị thay bằng `-02`. Chi tiết ở `evidence/task5/incident-20261012-01.md`.

## 9. Chạy tái lập cuối (sau khi cluster khởi động lại)

Ngày 2026-10-12, sau khi Docker/k3d khởi động lại, Pod `curate`, `publisher` và
`consumer` được tạo lại, nên `/work` (emptyDir) trống. Toàn bộ pipeline được chạy
lại từ S3 với run ID mới:

| Bước | Run ID | Kết quả | So với lần trước |
|---|---|---|---|
| Task 1 staging + envelope | `task1-20261012-02` | PASS | `stage-report`, `envelope-check` giống `task1-20261012-01` |
| I01–I04, I02 SQL, contract | – | PASS | `integrity-test`, `access-test`, `i02-sql-check` giống evidence đã commit |
| Task 2A quality before | – | 6 metric, W = 9960 | Giống `evidence/task2/quality_before.json` |
| Task 3 curate + C01–C05 | `task3-20261012-02` | PASS | 3 artifact **trùng SHA-256** với `task3-20261012-01` |
| Task 2B quality after | – | 8 metric, 9610 dòng, QA 100 | Giống `evidence/task2/quality_after.json` |
| Task 4 `validate_catalog.py` (trong Pod, có DuckDB) | – | `CATALOG: PASS` | – |
| Gate tests P01–P08 | `gatetest-20261012-03` | PASS (7 ca REJECT) | Giống `gatetest-20261012-02`, chỉ khác `executed_at`/`test_id` |
| QA crosscheck | `qacheck-20261012-02` | PASS (100/100, 95/100) | Giống `qacheck-20261012-01` |
| Consumer check `release-20261012-02` | – | PASS | Giống `consumer-check.json`, chỉ khác `executed_at` |

Vì artifact trùng hash, release hiện hành vẫn là `release-20261012-02` (không công bố
lại). Thư mục `evidence/task5/runs/` chứa evidence của các run mới.

## 10. Gom bài nộp

```bash
./src/build_submission.sh <submission_id> task3-20261012-01
```

Lệnh tạo `submission/<id>/lab2-submission.zip` (bản chính) và
`submission/<id>/lab2-restricted.zip` (chỉ chứa sổ quarantine/duplicates), kèm
`SHA256SUMS`.
