import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

MANIFEST = ROOT / "data/trusted_manifest.json"
INPUT = ROOT / "data/Lab2-datasets/input/observations_a.csv"
OUTPUT = ROOT / "evidence/task1/mutation-test.json"

manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

obj = next(
    item for item in manifest["objects"]
    if item["key"] == "observations_a.csv"
)

original = INPUT.read_bytes()

if not original:
    raise RuntimeError("Input file is empty")

original_sha256 = hashlib.sha256(original).hexdigest()

if original_sha256 != obj["sha256"]:
    raise RuntimeError("Original input failed integrity check")

# Thay đổi đúng 1 byte trong bản sao ở bộ nhớ.
mutated = bytearray(original)
mutated[0] ^= 1

mutated_sha256 = hashlib.sha256(mutated).hexdigest()

# Sử dụng cùng quy tắc kiểm tra integrity của I01.
integrity_valid = (
    len(mutated) == obj["bytes"]
    and mutated_sha256 == obj["sha256"]
)

rejected = not integrity_valid

report = {
    "test_id": "I03",
    "mutation": "Flip one byte in copied observations_a.csv",
    "expected_sha256": obj["sha256"],
    "actual_sha256": mutated_sha256,
    "rejected": rejected,
    "reason": "INPUT_INTEGRITY" if rejected else None,
    "status": "PASS" if rejected else "FAIL"
}

OUTPUT.parent.mkdir(parents=True, exist_ok=True)
OUTPUT.write_text(
    json.dumps(report, indent=2) + "\n",
    encoding="utf-8"
)

print("Original SHA256:", original_sha256)
print("Mutated SHA256:", mutated_sha256)
print("Mutation rejected:", rejected)
print("I03:", report["status"])

sys.exit(0 if rejected else 1)
