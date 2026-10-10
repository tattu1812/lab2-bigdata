import hashlib
import json
from pathlib import Path

root = Path.home() / "lab2-bigdata"
input_dir = root / "data/Lab2-datasets/input"
manifest_path = root / "data/trusted_manifest.json"
output_path = root / "outputs/integrity-test.json"

manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

results = []

for obj in manifest["objects"]:
    path = input_dir / obj["key"]

    if not path.is_file():
        results.append({
            "key": obj["key"],
            "status": "FAIL",
            "reason": "INPUT_INTEGRITY",
            "detail": "Missing input file"
        })
        continue

    content = path.read_bytes()
    actual_bytes = len(content)
    actual_sha256 = hashlib.sha256(content).hexdigest()

    passed = (
        actual_bytes == obj["bytes"]
        and actual_sha256 == obj["sha256"]
    )

    results.append({
        "key": obj["key"],
        "expected_bytes": obj["bytes"],
        "actual_bytes": actual_bytes,
        "expected_sha256": obj["sha256"],
        "actual_sha256": actual_sha256,
        "status": "PASS" if passed else "FAIL",
        "reason": None if passed else "INPUT_INTEGRITY"
    })

report = {
    "test_id": "I01",
    "fixture_version": manifest["fixture_version"],
    "as_of": manifest["as_of"],
    "status": "PASS" if all(
        r["status"] == "PASS" for r in results
    ) and len(results) == 4 else "FAIL",
    "objects": results
}

output_path.parent.mkdir(parents=True, exist_ok=True)
output_path.write_text(
    json.dumps(report, indent=2),
    encoding="utf-8"
)

for r in results:
    print(f'{r["key"]}: {r["status"]}')

print("I01:", report["status"])
print("Saved:", output_path)
