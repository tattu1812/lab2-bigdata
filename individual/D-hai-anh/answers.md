# Hải Anh – Vai D / Metadata & Lineage (Task 4)

> Bản nháp được soạn với hỗ trợ AI, dựa trên evidence của nhóm. Hải Anh phải tự đọc lại,
> chạy lại lệnh ở mục 2 và viết lại bằng lời của mình trước khi trình bày.
> Đã kiểm chứng: [ ]

## 1. Thay đổi kỹ thuật tự viết

**`catalog.json` + `schemas/catalog.schema.json` + `src/validate_catalog.py`.** Validator
không chỉ parse JSON. Nó đối chiếu từng dataset với file thật: file tồn tại, `size_bytes`,
SHA-256, `row_count` (Parquet đọc bằng DuckDB) và danh sách cột.

- Test dương: `CATALOG: PASS`, chạy lại ngày 12/10 trong Pod `curate`.
- Test âm: xóa `steward` của `curated_candidate` trong một bản sao thì validator báo
  `CATALOG: FAIL – curated_candidate: thiếu field steward`, exit 1
  (`individual/D-hai-anh/validator-no-steward.txt`).

Lineage curate (`evidence/task4/lineage.jsonl`) có START và COMPLETE dùng chung runId
`20d91699…`, trùng `openlineage_run_id` trong `run-record.json`.

Truy vết L02/L03 (`src/trace_record.py` → `evidence/task4/trace-L02-L03.json`) được viết
trong lúc gom bài, có AI hỗ trợ. Hải Anh cần đọc và chạy lại để nhận phần này.

## 2. Kiểm tra chéo: ca gate thiếu metadata (P05) của Trung (vai E)

**Dự đoán.** Bản sao không sửa: PASS 9/9. Xóa `steward`: REJECT, chỉ G07/METADATA FAIL
(8/9). Thêm một biến thể: `steward = "   "` cũng phải bị REJECT, vì khoảng trắng là thiếu.

**Chạy** (Pod `publisher`, sao chép bundle gốc rồi chạy `src/gate.py` của Trung):

```bash
python3 p05_check.py --base /work/bundles/gatetest-20261012-04 --gate /work/task5/gate.py \
  --run-id task3-20261012-01 --work /work/xcheck-D --out p05-check.json
```

**Diễn giải.**

| Ca | Gate trước khi sửa | Gate sau khi sửa |
|---|---|---|
| CTRL | PASS 9/9 ✔ | PASS 9/9 ✔ |
| P05 – xóa steward | REJECT 8/9, METADATA ✔ | REJECT 8/9, METADATA ✔ |
| P05b – steward chỉ khoảng trắng | **PASS 9/9 ✘** | REJECT 8/9, METADATA ✔ |

Ca P05 của Trung đúng như kỳ vọng. Biến thể P05b thì lộ ra một lỗ hổng fail-open: G07 coi
`"   "` là có giá trị. Trung đã sửa `FILLED` trong `gate.py` và chạy lại P01–P08
(`gatetest-20261012-04`, kết quả không đổi). Release hiện hành không bị ảnh hưởng, vì
steward thật là "Hải Anh". Chi tiết ở `evidence/task5/finding-20261012-03-blank-steward.md`.
Bundle gốc không bị sửa (`base_bundle_unchanged: true`).

## 3. Quyết định thiết kế đã giải thích

`duplicates.csv` không phải dataset riêng mà là artifact phụ của `curated_candidate`. Nó
không phải dữ liệu cho người dùng, nhưng cần để đối soát (200 bản `SUPERSEDED`, mỗi bản ghi
kèm khóa winner). Raw dùng một hash tổng hợp của hai file nguồn (`1f73d6ae…`), còn hash
từng file nằm trong trusted manifest.

## 4. Câu hỏi cá nhân

**1. JSON parse được có phải catalog đúng không? Validator ngữ nghĩa kiểm thêm gì?**
Không. `json.tool` chỉ chứng minh cú pháp, còn JSON Schema chỉ chứng minh cấu trúc: đủ
trường, đúng kiểu, hash 64 hex. Catalog vẫn có thể "hợp lệ" mà nói sai về dữ liệu. Validator
ngữ nghĩa kiểm thêm:

- location trỏ tới file có thật;
- `size_bytes` và SHA-256 khớp file;
- `row_count` khớp số dòng đếm được (9.610 / 395 / 200);
- `columns` khớp schema thật của Parquet/CSV;
- owner/steward không rỗng.

Gate G07 kiểm lại đúng những điều này. P05b cho thấy chỗ khó nhất là định nghĩa "không
rỗng": `"   "` qua được kiểm tra tồn tại nhưng không có nghĩa.

**2. Vì sao `qa_reference.csv` là đầu vào kiểm định còn `sensors.csv` là đầu vào biến đổi?**
`sensors.csv` tham gia tạo giá trị output: cột `site` của curated lấy từ registry, và
sensor không có trong registry thì bị `REFERENCE`. `qa_reference.csv` chỉ dùng để đo độ
khớp/độ phủ sau curation. Nó không được phép sửa, điền hay chọn giá trị đo. Trong lineage,
`sensors.csv` là input của job `curate`, còn `qa_reference.csv` là input của job
`validate-and-publish` (gate G09). Hạn chế hiện tại: event curate ghi input ở mức prefix
`lab2/inputs/batch-01` nên chưa tách hai vai trò này thành dataset riêng.

**3. Khi nào ABORT, khi nào FAIL? Vì sao không COMPLETE cho publish bị từ chối?**
`ABORT` là dừng có chủ đích do chính sách: gate REJECT hoặc review không đạt. `FAIL` là lỗi
thực thi: exception khi upload, hash sau upload không khớp. `COMPLETE` nghĩa là run đã tạo
ra output của nó. Với publish, output là release đã duyệt. Phát COMPLETE cho lần bị từ chối
sẽ khiến lineage nói rằng có một release không tồn tại. Hiện `publish.py` phát `FAIL` khi
upload hoặc verify lỗi. Khi gate từ chối, nó dừng **trước** START nên không phát event nào
(`s3_writes = 0`). Đề yêu cầu phát ABORT trong trường hợp này, nên đây là điểm còn thiếu.

**4. Sự kiện OpenLineage cấp dataset có đủ để truy vết một dòng không?**
Không. Event chỉ nói job đọc prefix raw và ghi ba file. Nó không nói dòng `R001001` trong
curated đến từ dòng nào. Truy vết cấp dòng cần thêm:

- các cột provenance trong release: `source_object`, `source_row`, `source_sha256`;
- trusted manifest, để xác nhận hash nguồn;
- `duplicates.csv` và `quarantine.csv`, cho các phiên bản không được chọn và lý do.

L02 (`R001001` → `observations_b.jsonl:5101`, `3072ad0b…`, bản CSV 1001 bị thay thế) và L03
(`R001051` → quarantine `REQUIRED`) đều PASS, và Tú đã chạy lại L02 độc lập.

**5. Raw quá 30 ngày nhưng release đang hoạt động còn tham chiếu thì sao?**
`KEEP / ACTIVE_DEPENDENCY` (ca R03 trong `retention-plan.json`). Hết hạn chỉ là điều kiện
cần để xóa. `release-20261012-02` vẫn hoạt động và ghi `source_sha256` của raw. Xóa raw sẽ
làm mất khả năng tái lập và kiểm chứng release. Raw chỉ trở thành `ELIGIBLE` khi mọi release
phụ thuộc đã hết hạn hoặc bị thu hồi và không có legal hold. Kế hoạch chạy ở dry-run
(`delete_executed: false`).

**6. Vì sao không tính hạn lưu trữ từ mốc AS_OF?**
`AS_OF = 2026-02-09T00:00:00Z` là mốc đánh giá dữ liệu mô phỏng, dùng để xét
trình tự/độ muộn. Nó không phải thời điểm dữ liệu vào hệ thống. Tính hạn từ AS_OF thì raw
lấy về ngày 12/10/2026 đã "quá 30 ngày" ngay lúc lấy, và mọi thứ sẽ đủ điều kiện xóa sai.
Hạn phải tính từ sự kiện vận hành thật:

- raw: 30 ngày từ lúc lấy;
- quarantine: 7 ngày từ lúc run hoàn tất;
- release: 90 ngày từ lúc công bố.

Các mốc lấy từ `run-record.json`, lineage và `release_manifest.json`. Hạn chế:
`retention-plan.json` hiện ghi quyết định nhưng chưa ghi rõ `days`/`start_basis` cho từng ca.
