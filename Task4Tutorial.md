# Task 4 Tutorial — Metadata, Lineage, Retention

## Mục tiêu

Task 4 mô tả và kiểm tra metadata, truy vết và chính sách lưu giữ cho artifact thật từ Task 1–3. Dữ liệu là synthetic teaching data. Task 4 không phát hành approved release và không xóa file. Publish lineage là công việc riêng ở T5.

Run hiện tại: Task 1 `task1-20261012-01`, Task 3 `task3-20261012-01`, OpenLineage UUID `f4ea06e1-5465-4728-8491-cf92235271bb`. Mốc AS_OF cố định: `2026-02-09T00:00:00Z`.

## Đầu vào và đầu ra

Task 1 staging hai nguồn `observations_a.csv` và `observations_b.jsonl` trên S3, tạo envelope và stage report. Task 3 đọc envelope, registry `sensors.csv`, contract và curation decisions. QA reference chỉ được dùng để đánh giá sau curation, không để tính nhiệt độ.

Run tạo ba artifact:

- `outputs/curate/task3-20261012-01/candidate/curated.parquet`: 9.610 dòng.
- `outputs/curate/task3-20261012-01/quarantine.csv`: 395 dòng.
- `outputs/curate/task3-20261012-01/duplicates.csv`: 200 dòng.

Tổng bằng 10.205 quan sát raw. Size và SHA-256 thật của từng file nằm trong `evidence/task4/runs/task3-20261012-01/run-record.json`. Candidate chưa được review/phê duyệt thành release.

## Tạo run và OpenLineage

Sau `source env.sh`, kiểm tra pod `curate` đang Ready và `/work/envelopes.jsonl`, `/work/staged/sensors.csv`, `/work/stage-report.json` còn tồn tại. `/work` là EmptyDir; nếu pod được tạo lại, phải chuẩn bị lại Task 1. Mỗi run dùng ID mới, không chạy đè run cũ:

```bash
source .venv-task2/bin/activate
python src/run_task4_curate.py task3-YYYYMMDD-XX
```

Wrapper phát `START` khi bắt đầu thật, `COMPLETE` sau khi Task 3 và C01–C05 đạt; lỗi thực thi phát `FAIL`, ngắt phát `ABORT`. Cặp thành công dùng chung một UUID. Event được kiểm tra bằng schema chính thức lưu tại `schemas/openlineage-2-0-2.schema.json`, RunEvent là `#/$defs/RunEvent`. Không tạo event thủ công sau khi run kết thúc. File hiện tại: `evidence/task4/runs/task3-20261012-01/lineage.jsonl`; bản gốc `evidence/task4/lineage.jsonl` được đồng bộ từ file đó. Publish ở T5 cần UUID và cặp event riêng.

## Catalog, quality và run-record

`catalog.json` gồm `raw`, `quarantine`, `curated_candidate`; duplicate ledger là supporting artifact. Metadata có owner/steward, classification, allowed use, location, schema/cột, AS_OF, row count, manifest/contract/code hashes, quality link, retention và provenance. Code-bundle SHA-256 tính từ các dòng SHA-256 của sáu file mã thực thi, sắp theo tên file.

Quality-after của run: `evidence/task4/runs/task3-20261012-01/quality_after.json` (8 chỉ số, 9.610 curated rows, 100 QA rows). Cohort và giới hạn của từng chỉ số phải đọc trong báo cáo; không suy ra tất cả bản ghi đều đúng hoặc đúng hạn.

Run-record ghi UUID, thời gian thật, AS_OF, input/code/contract hashes, phiên bản Python/DuckDB/image, reviewer và output hashes. Reviewer hiện `PENDING_FINAL_REVIEW`; chưa có approval. Kiểm tra catalog:

```bash
python src/validate_catalog.py
```

`CATALOG: PASS` là đạt. Cảnh báo S3 nghĩa là validator dựa vào stage report và file local, chưa tự tính hash trực tiếp từ object S3.

## Evidence truy vấn và truy vết

`evidence/task4/runs/task3-20261012-01/catalog-queries.json` lưu M01/M02: tìm candidate có `temperature_c` đo bằng Celsius và quality link; tìm raw/quarantine restricted có retention và hold/dependency policy; candidate schema không có email.

`evidence/task4/runs/task3-20261012-01/row-traces.json` lưu:

- L02: curated `R001001` → `observations_b.jsonl` dòng 5101, đối chiếu source SHA-256, bản thắng/thua trong duplicate ledger, chuyển đổi nhiệt độ và registry site.
- L03: quarantine `R000001` → dòng nguồn, source SHA-256, lý do chính và toàn bộ lý do (`REQUIRED`).

File chỉ lưu trường cần truy vết, không lưu operator email. M03 cần thành viên khác đọc catalog, README và draft manifest rồi trả lời năm câu hỏi; việc này hoàn tất khi có draft manifest ở T5, không tự tạo câu trả lời giả.

## Retention

`evidence/task4/retention-plan.json` và bản theo run lưu 4 dry-run: scratch hết hạn → `ELIGIBLE`; quarantine hết hạn dưới hold → `KEEP / HOLD`; raw hết hạn còn approved-release dependency giả định → `KEEP / ACTIVE_DEPENDENCY`; object chưa hết hạn → `KEEP / NOT_EXPIRED`.

Raw giữ 30 ngày từ retrieval, quarantine 7 ngày từ run completion, approved release 90 ngày từ publication. Audit/manifests giữ ít nhất hết vòng đời release. Hold/dependency chặn xóa. Bốn ca chỉ là mô phỏng; `delete_executed=false`.

## README và kiểm tra cuối

`evidence/task4/README.md` tóm tắt nguồn synthetic, khóa truy vết, timestamp/units, curation, quality, giới hạn sử dụng, phiên bản phần mềm và cách tái lập (345 từ).

```bash
python -m json.tool catalog.json >/dev/null
python -m json.tool evidence/task4/run-record.json >/dev/null
python -m json.tool evidence/task4/retention-plan.json >/dev/null
python src/validate_catalog.py
cmp evidence/task4/lineage.jsonl evidence/task4/runs/task3-20261012-01/lineage.jsonl
cmp evidence/task4/run-record.json evidence/task4/runs/task3-20261012-01/run-record.json
wc -w evidence/task4/README.md
git status --short
```

Chỉ commit file Task 4 và evidence cần nộp. Không commit raw data, `outputs/`, `.venv-task2/`, file backup hoặc thay đổi Task 1–3 không liên quan.