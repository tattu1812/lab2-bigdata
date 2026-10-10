import json
import hashlib
from pathlib import Path

root = Path.home() / "lab2-bigdata"
manifest = json.loads(
    (root / "data/trusted_manifest.json").read_text()
)

objects = []

for obj in manifest["objects"]:
    path = root / "data/s3-snapshot" / obj["key"]
    content = path.read_bytes()

    actual_sha = hashlib.sha256(content).hexdigest()
    actual_size = len(content)

    if actual_sha != obj["sha256"] or actual_size != obj["bytes"]:
        raise RuntimeError(f'INPUT_INTEGRITY: {obj["key"]}')

    objects.append({
        "bucket": "research-raw",
        "key": f'lab2/inputs/batch-01/{obj["key"]}',
        "records": obj["records"],
        "bytes": actual_size,
        "sha256": actual_sha,
        "integrity": "PASS"
    })

inventory = {
    "fixture_version": manifest["fixture_version"],
    "as_of": manifest["as_of"],
    "source": "s3-snapshot",
    "trusted_manifest": "data/trusted_manifest.json",
    "objects": objects,
    "status": "PASS"
}

output = root / "outputs/input_inventory.json"
output.write_text(json.dumps(inventory, indent=2))

print("Inventory:", inventory["status"])
print("Verified objects:", len(objects))
print("Saved:", output)
