#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

: "${NS:?Run 'source env.sh' first to set NS}"

POD="curate"

echo "=== CHECK POD ==="
kubectl wait \
  --for=condition=Ready \
  "pod/$POD" \
  -n "$NS" \
  --timeout=120s

echo "=== COPY INPUTS AND SCRIPTS ==="
kubectl cp data/trusted_manifest.json \
  "$NS/$POD:/work/trusted_manifest.json"

kubectl cp src/stage_inputs.py \
  "$NS/$POD:/work/stage_inputs.py"

kubectl cp src/create_envelopes.py \
  "$NS/$POD:/work/create_envelopes.py"

echo "=== STAGE S3 INPUTS ==="
kubectl exec -n "$NS" "$POD" -- \
  python3 /work/stage_inputs.py \
  s3 /work/trusted_manifest.json

echo "=== GENERATE ENVELOPES ==="
kubectl exec -n "$NS" "$POD" -- \
  python3 /work/create_envelopes.py \
  --input-dir /work/staged \
  --output-dir /work

echo "=== SAVE EVIDENCE ==="
mkdir -p evidence/task1

kubectl cp "$NS/$POD:/work/stage-report.json" \
  evidence/task1/stage-report.json

kubectl cp "$NS/$POD:/work/envelope-check.json" \
  evidence/task1/envelope-check.json

echo "=== VERIFY RESULTS ==="
python3 - <<'PY'
import json
from pathlib import Path

for name in ("stage-report.json", "envelope-check.json"):
    path = Path("evidence/task1") / name
    report = json.loads(path.read_text(encoding="utf-8"))
    if report.get("status") != "PASS":
        raise SystemExit(f"FAIL: {name}")
    print(f"PASS: {name}")
PY

echo "TASK 1 STAGING + ENVELOPE: PASS"
