# Task 4 – Metadata, Lineage và Retention

## Mục tiêu

Task 4 ghi lại metadata cho các artifact do pipeline Lab 2 tạo ra, để biết mỗi dataset nằm ở đâu, được tạo từ run nào, bằng code và contract nào, chất lượng ra sao và được lưu giữ bao lâu. Run được mô tả là `task3-20261012-01`, dùng input từ run staging `task1-20261012-01`.

## Dataset và artifact

| Dataset | Rows | SHA-256 (rút gọn) |
|---|---:|---|
| `raw` (S3 `research-raw/lab2/inputs/batch-01/`) | 10205 | `1f73d6ae…` |
| `curated_candidate` – `candidate/curated.parquet` | 9610 | `3c9762d7…` |
| `quarantine` – `quarantine.csv` | 395 | `2b7a219a…` |
| `duplicates.csv` (side artifact của curated) | 200 | `c0c31ea8…` |

Bảo toàn: 9610 + 395 + 200 = 10205. Cross-check độc lập của Task 2B xác nhận không có record bị mất, record thừa hay overlap giữa ba output.

## Các file evidence

- `catalog.json`: danh mục 3 dataset và 1 artifact, gồm location, row count, size, SHA-256, columns, owner/steward, source run, quality report, retention policy và dependencies. Cấu trúc được kiểm tra bằng `schemas/catalog.schema.json`.
- `evidence/task4/lineage.jsonl`: hai event OpenLineage `START` và `COMPLETE` dùng chung một `runId`, input là S3 raw và output là ba artifact Task 3.
- `evidence/task4/run-record.json`: hồ sơ audit của run, liên kết `openlineage_run_id` với SHA-256 của `curate.sql`, `run_curate.py`, contract, curation decisions, trusted manifest và ba output.
- `evidence/task4/retention-plan.json`: kế hoạch retention ở chế độ dry-run (`dry_run: true`, `delete_executed: false`) với bốn case `ELIGIBLE`, `KEEP/HOLD`, `KEEP/ACTIVE_DEPENDENCY` và `KEEP/NOT_EXPIRED`.
- `evidence/task2/quality_after.json`: quality sau curation. Sáu metric trên 9610 bản ghi curated đều PASS (timeliness 9410/9610), QA coverage 100/100, QA agreement 95/100.

## Cách kiểm tra

```bash
python3 src/validate_catalog.py
```

Validator đối chiếu catalog với file thật: tồn tại, size, SHA-256, row count và columns. Với Parquet, validator dùng DuckDB. Kết quả mong đợi là `CATALOG: PASS`, kèm cảnh báo rằng location S3 của `raw` không được kiểm tra trực tiếp.

## Giới hạn

- `outputs/` không được commit, nên muốn chạy validator thì phải có output của run `task3-20261012-01` trên máy (chạy `./src/run_task3.sh`).
- Hash của code và contract được tính trên file có xuống dòng LF như trong git. Checkout trên Windows với CRLF sẽ cho hash khác.
- Retention plan chỉ ghi quyết định, không xóa dữ liệu thật.
