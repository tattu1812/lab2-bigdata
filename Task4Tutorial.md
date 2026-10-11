# Task 4 Tutorial – Metadata, Lineage and Retention

## 1. Mục tiêu

Task 4 biến các artifact của Task 1–3 thành dữ liệu có metadata,
lineage và chính sách lưu trữ rõ ràng.

Các artifact chính:

- `curated.parquet`: dữ liệu curated dùng cho downstream.
- `quarantine.csv`: các bản ghi bị loại.
- `duplicates.csv`: các bản ghi trùng bị loại.
- `quality_after.json`: kết quả kiểm thử sau curation.

## 2. Chuẩn bị run

```bash
cd ~/lab2-bigdata

RUN=task3-20261011-01
BASE="outputs/curate/$RUN"

ls -lh \
  "$BASE/candidate/curated.parquet" \
  "$BASE/quarantine.csv" \
  "$BASE/duplicates.csv"
