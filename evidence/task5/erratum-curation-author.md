# Erratum 20261012-02 – `curation_author` ghi sai trong review

- **Phát hiện:** 2026-10-12, khi kiểm tra chéo cuối trước lúc nộp (Trung, vai E).
- **Ảnh hưởng:** chỉ ảnh hưởng metadata review. Candidate (`3c9762d7…`), gate (PASS 9/9),
  hash các object và kết quả consumer đều không đổi.

## Chuyện gì đã xảy ra

`review.json` của `release-20261012-01` và `release-20261012-02` ghi
`"curation_author": "Tú"`. Lịch sử git cho thấy tác giả chính của curation (Task 3:
`src/curate.sql`, `src/run_curate.py`, `src/test_curate.py`, fixture biên,
`evidence/task3/contract-review.md`) là **Khánh** (tài khoản `KenteaKe11`, nhánh
`task3-khanh`). Tú (tài khoản `tattu1812`, nhánh `task1-tu`) phụ trách Task 1.
Phân vai ban đầu trong `contributions.csv` bị đảo, và template review trong
`run_task5.sh` và `publish.py` lấy theo phân vai đó.

## Điều kiện review độc lập vẫn được đáp ứng

Người review là **Hải Anh** (vai D). Hải Anh không phải Khánh và cũng không phải Tú,
nên yêu cầu "reviewer khác tác giả chính của curation" vẫn đúng với phân vai thật.

## Xử lý

1. Không sửa `review.json` đã công bố. File này là một object trong
   `research-release/lab2/releases/release-20261012-02/` và có SHA-256 trong
   `release_manifest.json`. Sửa nó sẽ làm consumer check báo lệch hash.
2. Sửa giá trị mặc định cho các lần publish sau: `CURATION_AUTHOR` trong
   `src/publish.py` và template `review-request` trong `src/run_task5.sh` giờ là `Khánh`.
3. Sửa phân vai trong `contributions.csv` và `README.md`.
4. Đã kiểm tra lại release hiện hành từ Pod `consumer` (principal `analyst`) sau khi
   cluster khởi động lại: hash 4/4 khớp, 9610 dòng, raw 403, các release P02–P08
   không có manifest. Kết quả: `CONSUMER CHECK: PASS`.

`release-20261012-02` vẫn là release hiện hành.
