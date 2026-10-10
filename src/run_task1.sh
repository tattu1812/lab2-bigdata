#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

: "${NS:?Run 'source env.sh' first to set NS}"

POD="curate"

RUN_ID="${1:?Usage: ./src/run_task1.sh <run_id>}"

if [[ ! "$RUN_ID" =~ ^[a-zA-Z0-9_-]+$ ]]; then
  echo "Invalid run_id: use letters, numbers, hyphens or underscores" >&2
  exit 1
fi

EVIDENCE_DIR="evidence/task1/runs/$RUN_ID"

if [[ -e "$EVIDENCE_DIR" ]]; then
  echo "Evidence directory already exists: $EVIDENCE_DIR" >&2
  exit 1
fi

echo "RUN_ID: $RUN_ID"

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
mkdir -p "$EVIDENCE_DIR"

kubectl cp "$NS/$POD:/work/stage-report.json" \
  "$EVIDENCE_DIR/stage-report.json"

kubectl cp "$NS/$POD:/work/envelope-check.json" \
  "$EVIDENCE_DIR/envelope-check.json"

echo "=== VERIFY RESULTS ==="
RUN_ID="$RUN_ID" python3 - <<'PY'
import json
import os
from pathlib import Path

for name in ("stage-report.json", "envelope-check.json"):
    path = Path("evidence/task1/runs") / os.environ["RUN_ID"] / name
    report = json.loads(path.read_text(encoding="utf-8"))
    if report.get("status") != "PASS":
        raise SystemExit(f"FAIL: {name}")
    print(f"PASS: {name}")
PY

echo "TASK 1 STAGING + ENVELOPE: PASS"
