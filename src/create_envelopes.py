import csv
import json
from pathlib import Path
from collections import Counter

ROOT = Path.home() / "lab2-bigdata"
INPUT = ROOT / "data/s3-snapshot"
OUTPUT = ROOT / "outputs"
OUTPUT.mkdir(exist_ok=True)

envelopes = []

# CSV: mỗi hàng dữ liệu sau header là một observation.
with (INPUT / "observations_a.csv").open(
    "r", encoding="utf-8-sig", newline=""
) as f:
    reader = csv.DictReader(f)

    for row_number, row in enumerate(reader, start=1):
        envelopes.append({
            "source_object": "observations_a.csv",
            "source_row": row_number,
            "parse_status": "OK",
            "payload": row
        })

# JSONL: giữ nguyên từng dòng vật lý, kể cả dòng lỗi.
with (INPUT / "observations_b.jsonl").open(
    "r", encoding="utf-8-sig"
) as f:
    for row_number, line in enumerate(f, start=1):
        try:
            payload = json.loads(line)
            status = "OK"
        except json.JSONDecodeError:
            payload = None
            status = "PARSE_ERROR"

        envelopes.append({
            "source_object": "observations_b.jsonl",
            "source_row": row_number,
            "parse_status": status,
            "payload": payload,
            "raw_line": line.rstrip("\r\n")
        })

# Kiểm tra định danh vật lý.
keys = [
    (e["source_object"], e["source_row"])
    for e in envelopes
]

counts = Counter(e["source_object"] for e in envelopes)
unique_count = len(set(keys))
parse_errors = sum(
    e["parse_status"] == "PARSE_ERROR"
    for e in envelopes
)

passed = (
    len(envelopes) == 10205
    and unique_count == 10205
    and counts["observations_a.csv"] == 5000
    and counts["observations_b.jsonl"] == 5205
)

# File này là artifact nội bộ, có thể chứa dữ liệu raw.
with (OUTPUT / "envelopes.jsonl").open(
    "w", encoding="utf-8"
) as f:
    for envelope in envelopes:
        f.write(json.dumps(envelope, ensure_ascii=False) + "\n")

report = {
    "test_id": "I02",
    "status": "PASS" if passed else "FAIL",
    "expected_envelopes": 10205,
    "actual_envelopes": len(envelopes),
    "unique_physical_ids": unique_count,
    "source_counts": dict(counts),
    "jsonl_parse_errors": parse_errors
}

(OUTPUT / "envelope-check.json").write_text(
    json.dumps(report, indent=2),
    encoding="utf-8"
)

print(json.dumps(report, indent=2))
