# Task 3 – Review & ký duyệt `contracts/contract.json`

## Phiên bản được duyệt

| Tệp | SHA-256 |
|---|---|
| `contracts/contract.json` | `a655a0ca42f9f847c77fca1060d88c76e7aed21e36994aa3d71fd54c26ce5d6d` |
| `contracts/curation_decisions.json` | `68899639b17752f0067e51c0ae6e1e278f8bb4c634c19cc9f889243b1f78fc5d` |

Kiểm lại: `sha256sum contracts/contract.json contracts/curation_decisions.json`

Lưu ý: dòng `task1-20261010-02` trong `evidence/evidence_index.csv` ghi hash cũ
`af08336397eaf39f3fbf9dee23f5c257b50d0d6b4398b7dd8ffa47c6b1117a26`.
File hiện tại đã thay đổi so với hash đó (working tree đang `modified`); mọi run Task 3
ghi lại hash thực dùng trong `run-manifest.json` (`inputs.contract_sha256`).

**Đính chính (Trung, kiểm tra chéo cuối 2026-10-12):** hai hash trong bảng trên được
tính trên bản checkout Windows (xuống dòng CRLF). Nội dung không đổi; bản LF trong git
có hash như sau, và trùng `run-manifest.json` của `task3-20261012-01`/`-02` cũng như
`evidence/task4/run-record.json`:

| Tệp (LF) | SHA-256 |
|---|---|
| `contracts/contract.json` | `af08336397eaf39f3fbf9dee23f5c257b50d0d6b4398b7dd8ffa47c6b1117a26` |
| `contracts/curation_decisions.json` | `086a763f210dfdeaa5fd8537eb359149eff2c3f008c5536e897da9bed792ae1d` |

Kiểm lại: `sed 's/$/\r/' contracts/contract.json | sha256sum` cho ra `a655a0ca…`. Vậy
contract **không** thay đổi so với hash `af083363…` trong evidence index.

## Checklist review

| # | Nội dung contract | Cách `curate.sql` / runner áp dụng | Kết quả |
|---|---|---|---|
| 1 | `schema_version`, `as_of` = `2026-02-09T00:00:00Z` | `params.as_of_ts` (đọc từ contract) | OK |
| 2 | `timestamp_format` = `YYYY-MM-DDTHH:MM:SSZ` | Runner đổi sang mã strptime; parse nghiêm ngặt bằng `try_strptime` | OK |
| 3 | `normalization`: `record_id`, `sensor_id`, `unit` – trim + uppercase; rỗng = missing | `NULLIF(trim(upper(x)),'')` trong `canonical` | OK |
| 4 | `record_id_pattern` `^R[0-9]{6}$` | `regexp_matches(record_id, params.record_id_pattern)` | OK |
| 5 | `prekey_reason_precedence`: PARSE, KEY, INGEST_PARSE | Chạy trước dedup; mọi lý do áp dụng được ghi, sắp theo precedence | OK |
| 6 | `deduplication.order`: ingest_time DESC, source_object ASC, source_row ASC | `ROW_NUMBER() OVER (PARTITION BY record_id ORDER BY …)`; runner từ chối nếu contract đổi thứ tự | OK |
| 7 | `invalid_winner_policy` = `quarantine_no_fallback` | Winner chọn trước validate; winner lỗi → quarantine, bản cũ vẫn là `SUPERSEDED` | OK |
| 8 | `row_reason_precedence`: REQUIRED, NUMERIC, UNIT, RANGE, TIME_PARSE, TIME_ORDER, REFERENCE | `winner_checked.row_reasons`; `primary_reason` theo `primary_reason_precedence` | OK |
| 9 | `supported_units` C, F; `fahrenheit_to_celsius` `(F-32)*5/9` | Số học số nguyên cố định (`temp_num/temp_den`) | OK |
| 10 | `temperature_range_c` [-30, 60] (bao gồm biên); `finite_required`; `validate_before_rounding` | Kiểm khoảng trên giá trị chính xác trước khi làm tròn (60.004 °C bị RANGE) | OK |
| 11 | `temperature_rounding` 2 chữ số, `ROUND_HALF_UP` (curation_decisions) | Hòa làm tròn ra xa 0 (`0.005→0.01`, `-0.005→-0.01`); runner kiểm mode và scale = `output_type` | OK |
| 12 | `output_type` `DECIMAL(8,2)` | Thay vào `CAST(... AS {{OUTPUT_TYPE}})`; C03 kiểm kiểu Parquet | OK |
| 13 | `time_order`: event ≤ ingest ≤ as_of | `f_time_order` (ingest = as_of vẫn hợp lệ) | OK |
| 14 | `late_threshold_seconds` 900, `late_records_policy` retain | `is_late = lag > 900`; bản trễ vẫn vào curated | OK |
| 15 | `privacy.restricted_fields`: operator_email, raw_payload; `operator_email_required` false | `curate.sql` không đọc các trường này; C03/C04 kiểm không xuất hiện | OK |
| 16 | `released_columns` (10 cột, thứ tự cố định) | `curated` xuất đúng thứ tự; C03 so với contract | OK |
| 17 | `release_thresholds` | C05 tính lại và so ngưỡng; `qa_*` để Task 2B | OK |
| 18 | Không dùng `qa_reference.csv` để tạo/bù giá trị | Không có tham chiếu tới tệp này trong Task 3 | OK |

## Quyết định diễn giải (ghi nhận để Task 2B/4/5 dùng cùng)

1. Timestamp parse theo đúng `timestamp_format` của contract; chuỗi lệch định dạng → `INGEST_PARSE`
   (ingest) hoặc `TIME_PARSE` (event). `quality.sql` của Task 2 dùng `TRY_CAST`, rộng hơn; C01 so
   với baseline Task 2 (`--baseline`) và báo `task2_baseline.match`.
2. `site` lấy từ cột `site` của `sensors.csv`; sensor không có trong registry hoặc `site` rỗng → `REFERENCE`.
3. Bản ghi prekey-lỗi không tham gia dedup, nên bản hợp lệ cũ hơn cùng `record_id` có thể là winner
   (khác với winner lỗi sau dedup: không fallback).
4. `quarantine.csv` không chứa payload hay email; chỉ khóa vật lý, `source_sha256`, stage, lý do.

## Ký duyệt

- Phạm vi: Task 3 – Curation (Vai C)
- Kết luận: contract đủ rõ để cài đặt tất định; không thay đổi ngưỡng.
- Người review: ______________________   Ngày: ____ / ____ / ________
