# Lab 2 – Big Data: Research Telemetry Pipeline (nhóm `bd-g01`)

Pipeline đưa dữ liệu nhiệt độ từ hai nguồn (`observations_a.csv`, `observations_b.jsonl`)
trên S3 thành một bản release có kiểm soát cho analyst. Pipeline gồm 5 bước: ingestion
có kiểm tra toàn vẹn, đo chất lượng, curation tất định, ghi metadata/lineage, rồi
gate và công bố.

**Kết quả cuối:** `release-20261012-02` được công bố trên `research-release/lab2/releases/`.
Release gồm 9.610 dòng, gate PASS 9/9 và có review độc lập. Analyst đọc được release
nhưng không đọc được raw (HTTP 403).

## Thành viên và phân vai

| Thành viên | Vai | Phần chính |
|---|---|---|
| Tú | A – Ingestion & Contract (Task 1) | `contracts/`, staging S3, envelope, I01–I04 |
| Trung Nguyễn | B – Data Quality (Task 2) | `quality*.sql`, quality before/after, biểu đồ, kiểm tra chéo C01 |
| Khánh | C – Curation (Task 3) | `curate.sql`, C01–C05, fixture biên, review contract |
| Hải Anh | D – Metadata & Lineage (Task 4) | `catalog.json`, lineage, run-record, retention; review release |
| Trung | E – Release (Task 5) | gate G01–G09, đột biến P01–P08, publish, consumer, gom bài |

Chi tiết đóng góp, kiểm tra chéo và quyết định thiết kế của từng người nằm trong
[`contributions.csv`](contributions.csv).

## Kết quả chính

**Bảo toàn dữ liệu:** 10.205 bản ghi raw = 9.610 curated + 395 quarantine + 200 duplicates.
Mỗi khóa vật lý `(source_object, source_row)` xuất hiện đúng một lần.

**Chất lượng trước/sau curation** (`evidence/task2/`):

| Metric | Trước | Sau | Ngưỡng |
|---|---|---|---|
| completeness | 9850/9960 (FAIL) | 9610/9610 (PASS) | 1.00 |
| uniqueness | 9960/10160 (FAIL) | 9610/9610 (PASS) | 1.00 |
| value_validity | 9710/9960 (FAIL) | 9610/9610 (PASS) | 1.00 |
| referential_integrity | 9930/9960 (FAIL) | 9610/9610 (PASS) | 1.00 |
| temporal_consistency | 9890/9960 (FAIL) | 9610/9610 (PASS) | 1.00 |
| timeliness | 9690/9890 (PASS) | 9410/9610 (PASS) | 0.95 |
| qa_coverage | – | 100/100 (PASS) | 1.00 |
| qa_agreement | – | 95/100 (PASS) | 0.95 |

**Kiểm thử:**

| Nhóm | Kết quả | Evidence |
|---|---|---|
| I01–I04 (integrity, envelope, mutation, S3 access) | PASS | `evidence/task1/` |
| C01–C05 (bảo toàn, tất định, schema, ca biên, metric) | PASS | `evidence/task3/runs/<run>/curate-checks.json` |
| Catalog / lineage / run-record | `CATALOG: PASS` | `catalog.json`, `evidence/task4/` |
| Gate G01–G09 trên candidate thật | PASS 9/9 | `evidence/task5/runs/*/P01-gate-report.json` |
| Đột biến P02–P08 | 7/7 bị REJECT, publish bị từ chối, `s3_writes = 0` | `evidence/task5/gate-tests.json` |
| Kiểm tra chéo QA (DECIMAL) | 100/100, 95/100, khớp `quality_after.json` | `evidence/task5/qa-crosscheck.json` |
| Consumer (analyst) | hash 4/4, 9610 dòng, raw 403, release REJECT không có manifest | `evidence/task5/consumer-check.json` |

## Tái lập (chạy lại toàn bộ ngày 2026-10-12)

Sau khi cluster khởi động lại, cả 3 Pod được tạo mới và toàn bộ pipeline chạy lại từ S3
với run ID mới. Mọi evidence khớp với lần trước. `curated.parquet`, `quarantine.csv` và
`duplicates.csv` của `task3-20261012-02` **trùng SHA-256** với `task3-20261012-01`.
Bảng đối chiếu từng bước nằm trong [`Task5Tutorial.md`](Task5Tutorial.md) mục 9.

## Cấu trúc repo

```text
contracts/             contract.json, curation_decisions.json
src/                   SQL + helper Python/Bash của cả nhóm
manifests/             Pod curate, publisher, consumer
schemas/               catalog.schema.json
tests/fixtures/edge/   fixture ca biên cho C04 (email chỉ dùng example.com)
catalog.json           metadata catalog (Task 4)
evidence/task1..5/     evidence của từng task; mỗi lần chạy có thư mục runs/<run_id>/
evidence/evidence_index.csv   ai chạy lệnh nào, run ID nào, ra file nào
individual/            câu trả lời cá nhân
Task1..5Tutorial.md    hướng dẫn chạy lại chi tiết từng task
```

`data/` (input, trusted manifest) và `outputs/` (artifact curation, gồm sổ
quarantine/duplicates) bị `.gitignore` nên **không** có trên GitHub.

## Chạy lại

Yêu cầu: cluster `k3d-bigdata`, namespace `bd-g01`, Secret S3 sẵn có, input đã upload
lên `research-raw/lab2/inputs/batch-01/`, và `data/trusted_manifest.json` có trên máy.

```bash
source env.sh
kubectl apply -f manifests/curate.yaml
kubectl wait --for=condition=Ready pod/curate -n "$NS" --timeout=180s
kubectl exec -n "$NS" curate -- python3 -m pip install -q --no-cache-dir \
  --target /work/python-packages duckdb==1.4.1

./src/run_task1.sh  task1-<YYYYMMDD>-NN                # staging + envelope (Task 1)
python3 src/check_integrity.py && python3 src/test_mutation.py   # I01, I03
# I02 SQL, I04, Task 2A/2B: xem Task1Tutorial.md và Task2Tutorial.md
./src/run_task3.sh  task3-<YYYYMMDD>-NN                # curation + C01–C05 (Task 3)
python3 src/validate_catalog.py                        # Task 4, cần DuckDB

./src/run_task5.sh setup
./src/run_task5.sh gate-tests task3-20261012-01 gatetest-<id> release-20261012
./src/run_task5.sh crosscheck task3-20261012-01 qacheck-<id>
./src/run_task5.sh review-request task3-20261012-01 <release_id>
./src/run_task5.sh publish task3-20261012-01 <release_id>     # cần evidence/task5/review.json
./src/run_task5.sh consume <release_id> <rejected_release_ids_csv>
```

Mỗi run ID chỉ dùng một lần. Script sẽ dừng nếu thư mục evidence đã tồn tại, không
ghi đè.

## Bài nộp

```bash
./src/build_submission.sh <submission_id> task3-20261012-01
```

Lệnh tạo hai file ZIP trong `submission/<submission_id>/`:

- `lab2-submission.zip`: bản nộp chính. Nội dung đối chiếu với checklist nằm trong
  [`SUBMISSION.md`](SUBMISSION.md).
- `lab2-restricted.zip`: chỉ chứa sổ `quarantine.csv`/`duplicates.csv`. Bản này chỉ nộp
  vào kênh hạn chế của môn học, không bao giờ vào release cho analyst và không lên GitHub.

Script từ chối gom nếu phát hiện email thô (ngoài domain `example.*` dùng trong
fixture), `envelopes.jsonl`, `.env`, kubeconfig hoặc file trong `data/`.

## Sự cố và đính chính

- [`evidence/task5/incident-20261012-01.md`](evidence/task5/incident-20261012-01.md):
  `release-20261012-01` mang `reviewed_at` sai. Release này đã được thay bằng `-02`,
  không bị ghi đè.
- [`evidence/task5/erratum-curation-author.md`](evidence/task5/erratum-curation-author.md):
  `review.json` đã công bố ghi `curation_author` là Tú, trong khi tác giả curation là
  Khánh. Reviewer là Hải Anh nên điều kiện review độc lập vẫn đúng.
- [`evidence/task3/contract-review.md`](evidence/task3/contract-review.md): hash contract
  trong bảng duyệt được tính trên bản CRLF. Nội dung contract không đổi.

## Khai báo sử dụng AI

Nhóm dùng trợ lý AI (Claude Code) ở vai E cho các việc sau: chạy lại toàn bộ pipeline
để kiểm tra tái lập, đối chiếu evidence, soạn `README.md`/`SUBMISSION.md`, soạn erratum
và điền `contributions.csv` dựa trên evidence và lịch sử git. Mọi số liệu trong tài liệu
được lấy từ file evidence do script sinh ra, không do AI tự đặt. Mỗi thành viên phải tự
xác nhận dòng của mình trong `contributions.csv` (cột `confirmed_by_member`) và bổ sung
phần AI hỗ trợ trong task của mình nếu có.

Không có credential hay dữ liệu hạn chế nào được commit lên repo.
