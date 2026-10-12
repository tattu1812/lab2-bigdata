# Checklist nộp bài – Lab 2

Bản nộp được tạo bằng `./src/build_submission.sh <submission_id> task3-20261012-01`.
Các đường dẫn dưới đây là đường dẫn **bên trong** `lab2-submission.zip`.

| # | Hạng mục | Người phụ trách | Đường dẫn trong ZIP | Trạng thái |
|---|---|---|---|---|
| 1 | Code (SQL + helper) | Cả nhóm | `code/*.py`, `code/*.sql`, `code/*.sh`, `code/manifests/*.yaml` | [x] |
| 2 | `contract.json` | Tú | `contracts/contract.json`, `contracts/curation_decisions.json` | [x] |
| 3 | Hash của trusted manifest | Tú | `task1/trusted_manifest.sha256` (chỉ hash, không nộp bản gốc) | [x] |
| 4 | `input_inventory.json` | Tú | `task1/input_inventory.json` | [x] |
| 5 | `integrity-test.json`, `access-test.json` | Tú | `evidence/task1/integrity-test.json`, `evidence/task1/access-test.json` (+ I02/I03, run Task 1) | [x] |
| 6 | `quality_before.json`, `quality_after.json`, biểu đồ | Trung Nguyễn | `evidence/task2/quality_before.json`, `quality_after.json`, `quality_before_after.png`, `task2_crosscheck_after.json` | [x] |
| 7 | Manifest artifact của candidate, kết quả C01–C05 | Khánh | `evidence/task3/runs/task3-20261012-01/run-manifest.json`, `artifact-hashes.json`, `curate-checks.json` (+ run tái lập `task3-20261012-02`) | [x] |
| 8 | `catalog.json`, `README.md`, `lineage.jsonl`, `run-record.json`, `retention-plan.json` | Hải Anh | `catalog.json`, `evidence/task4/README.md`, `evidence/task4/lineage.jsonl`, `run-record.json`, `retention-plan.json` | [x] |
| 9 | `gate-tests.json`, `consumer-check.json`, `release_manifest.json` | Trung | `evidence/task5/gate-tests.json`, `consumer-check.json`, `release_manifest.json` (+ `review.json`, `qa-crosscheck.json`, `lineage-publish.jsonl`, `runs/`) | [x] |
| 10 | `contributions.csv` | Cả nhóm | `contributions.csv` | [ ] mỗi thành viên đổi `confirmed_by_member` thành `yes` sau khi đọc dòng của mình; Tú bổ sung cột `cross_checks_done` |
| 11 | Sổ quarantine/duplicates | Khánh | **Chỉ** trong `lab2-restricted.zip` (`restricted/quarantine.csv`, `restricted/duplicates.csv`). Không có trong bản chính, không có trong release cho analyst, không có trên GitHub | [x] |

Ngoài checklist, ZIP còn có: `README.md`, `SUBMISSION.md`, `evidence/evidence_index.csv`,
`docs/Task1..5Tutorial.md`, `individual/*.md`, `FILES.sha256` (SHA-256 của từng file trong ZIP).

## Kiểm tra trước khi nộp

- Không có credential, `.env`, kubeconfig hoặc file trong `data/` trong ZIP. Script tự
  từ chối gom nếu có.
- Không có email thô. Email duy nhất trong repo là `@example.com` trong fixture kiểm thử
  (domain dành riêng theo RFC 2606).
- Đối chiếu `SHA256SUMS` với hai file ZIP sau khi tải lên.
