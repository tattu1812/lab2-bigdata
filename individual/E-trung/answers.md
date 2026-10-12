# Trung – Vai E / Release (Task 5)


## 1. Thay đổi kỹ thuật

**`src/gate.py`** gồm 9 hàm G01–G09. Mỗi hàm tự đọc candidate, input tải lại từ S3, metadata
và lineage, rồi trả `{check, category, status, observed, reasons}`. Mọi exception được đổi
thành `BLOCKED`. Gate không đọc trường `status`/`passed` nào do task trước ghi ra.

- Test: `src/gate_tests.py` chạy 8 ca P01–P08 trên bản sao của bundle
  (`evidence/task5/gate-tests.json`). P01 PASS 9/9, 7 ca còn lại REJECT đúng category,
  publish các ca đó bị `REFUSED` với `s3_writes = 0`, và bundle gốc không đổi.
- Sửa sau kiểm tra chéo của Hải Anh: `steward` chỉ có khoảng trắng trước đây lọt qua G07.
  `FILLED` đã được sửa và P01–P08 chạy lại (`gatetest-20261012-04`), kết quả không đổi.
  Xem `evidence/task5/finding-20261012-03-blank-steward.md`.

## 2. Kiểm tra chéo: độ khớp và độ phủ QA của Trung Nguyễn (vai B)

**Dự đoán.** Độ phủ 100/100. Độ khớp 95/100 như `quality_after.json`, 5 ID lệch do sai số
có hệ thống chứ không phải lỗi làm tròn.

**Chạy** (truy vấn riêng `src/crosscheck_qa.py`, không dùng `quality_after.sql`):

```bash
./src/run_task5.sh crosscheck task3-20261012-01 qacheck-20261012-02
```

**Diễn giải** (`evidence/task5/qa-crosscheck.json`, PASS):

- So sánh bằng `DECIMAL(9,2)` thay vì `DOUBLE`; đếm phủ bằng INNER JOIN; tìm ID thiếu bằng
  anti-join.
- Kết quả: phủ 100/100, khớp 95/100, khớp `quality_after.json`.
- 5 ID lệch là `R000810`–`R000814`, mỗi ID lệch đúng 8,00 °C (27,00 so với 19,00 …).
- Không cặp nào nằm đúng biên 0,05 °C (`pairs_exactly_at_tolerance = 0`), nên kết quả không
  phụ thuộc cách so số thực.

## 3. Quyết định thiết kế đã giải thích

`release_manifest.json` được ghi **sau cùng**, sau khi mọi object đã upload và verify hash.
Manifest chỉ tham chiếu `runId` của lần publish; event COMPLETE mới chứa hash của manifest.
Cách này tránh phụ thuộc vòng (xem câu 3 và câu 5 bên dưới).

## 4. Câu hỏi cá nhân

**1. Vì sao gate phải tự tính lại từ dữ liệu thay vì đọc `"passed": true`?**

Một trường `passed: true` chỉ là lời khẳng định của bước trước, không phải bằng
chứng. Nó có thể đã cũ (được tính cho một candidate khác), bị sửa tay, hoặc do một
script có lỗi sinh ra. Gate là điểm kiểm soát cuối, nên nó phải kiểm *chính object
sắp công bố*. Ca P02 cho thấy rõ điều này: `curate-checks.json` của Task 3 vẫn ghi
C05 PASS, nhưng bản sao candidate đã có `temperature_c = 100.00`. Chỉ khi gate tự đếm
lại (`value_validity 9609/9610`) thì lỗi mới lộ ra. Gate cũng tự tải lại input từ S3
và tự tính lại khóa vật lý từ file nguồn, không dùng `envelopes.jsonl` của Task 1.

**2. Ca P08: xóa ID bị lệch làm độ khớp tăng, vì sao vẫn REJECT?**

Xóa `R000810` làm agreement tăng từ 95/100 lên 95/99 = 96%, nhưng coverage giảm
xuống 99/100. Đây chính là cách "làm đẹp" số liệu bằng cách chọn mẫu: bỏ bằng
chứng bất lợi thay vì sửa nguyên nhân. `qa_reference.csv` chỉ là nguồn kiểm chứng,
không được dùng để chọn hay loại observation. Vì vậy hai metric phải đạt *cùng lúc*.
Coverage = 1.0 đảm bảo mẫu số của agreement không bị thu nhỏ có chọn lọc. Ngoài ra,
việc xóa dòng còn phá bảo toàn (10204 ≠ 10205), nên G06 cũng bắt được.

**3. Vì sao `release_manifest.json` phải ghi cuối cùng? Có phải giao dịch nguyên tử không?**

Manifest là tín hiệu "release đã hoàn chỉnh". Consumer chỉ tin những object được
liệt kê trong manifest, với hash đã ghi. Nếu publish hỏng giữa chừng (mất mạng,
hash sai sau upload), prefix có thể còn vài object nhưng *không có manifest*, nên
consumer coi release đó chưa tồn tại. Nếu ghi manifest trước thì consumer có thể
đọc một manifest trỏ tới object chưa có hoặc chưa được verify.

Đây **không** phải giao dịch nguyên tử. S3 không có transaction trên nhiều object,
nên sau sự cố vẫn có thể còn object "mồ côi". Giao thức chỉ đảm bảo *atomic
visibility* với điều kiện consumer tuân thủ quy ước "không có manifest thì không
đọc". Còn lại phải dọn dẹp thủ công. `LastModified` cũng chỉ có độ phân giải giây,
nên thứ tự ghi được chứng minh bằng code và `publish-result.json`, không chỉ bằng
timestamp.

**4. Vì sao người review phải khác tác giả chính của curation?**

Tác giả dễ có điểm mù với chính quyết định của mình, ví dụ quy tắc dedup hay cách
xử lý winner không hợp lệ, và có động lực muốn công bố. Tách vai (four-eyes) giúp
ít nhất một người không có lợi ích trực tiếp kiểm lại bằng chứng. `publish.py` buộc
điều này bằng code: nó từ chối khi `reviewer` trùng `curation_author` và khi review
không gắn đúng `run_id` + hash candidate. Nhờ đó một lời APPROVE không thể bị dùng
lại cho candidate khác.

**5. Tránh phụ thuộc vòng khi manifest cần tham chiếu lineage của chính lần publish?**

`runId` của lần publish được sinh (UUID) *trước* khi phát START. Manifest chỉ chứa
`runId` và thời điểm START, là những thứ đã biết trước khi ghi manifest. Event
COMPLETE được phát *sau* manifest và chứa SHA-256 của manifest. Chiều tham chiếu đi
một hướng: COMPLETE → manifest → runId. Manifest không bao giờ chứa hash của
COMPLETE, nên không có vòng.

**6. Nếu lỡ công bố một candidate không hợp lệ thì nhóm xử lý thế nào?**

1. Dừng: thông báo cho analyst/consumer ngay, ghi incident note với thời điểm, release_id, hash và phạm vi ảnh hưởng.
2. Không ghi đè release cũ. Đánh dấu nó là thu hồi/bị thay thế, và nếu cần thì chặn đọc. Giữ lại bằng chứng để audit.
3. Tìm nguyên nhân gốc, rồi thêm kiểm tra để lỗi đó bị gate hoặc publish chặn lần sau.
4. Sửa dữ liệu hoặc metadata, chạy lại gate, review lại, rồi công bố một `release_id` mới.
5. Liên hệ những người đã tải bản lỗi để họ thay bằng bản mới.

Nhóm đã gặp một phiên bản nhẹ của tình huống này: `release-20261012-01` có
`reviewed_at` ghi sai (muộn hơn lúc publish). Nhóm đã xử lý đúng quy trình trên:
không ghi đè, thêm kiểm tra `reviewed_at` vào `publish.py`, công bố `-02`, và ghi
`evidence/task5/incident-20261012-01.md`.
