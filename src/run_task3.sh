#!/usr/bin/env bash
# Task 3 - chạy curate trên Pod `curate`, kiểm thử C01-C05, kéo artifact + evidence về repo.
# Dùng:  source env.sh && ./src/run_task3.sh <run_id>
set -euo pipefail

cd "$(dirname "$0")/.."

: "${NS:?Run 'source env.sh' first to set NS}"

POD="curate"
RUN_ID="${1:?Usage: ./src/run_task3.sh <run_id>}"

if [[ ! "$RUN_ID" =~ ^[a-zA-Z0-9_-]+$ ]]; then
  echo "Invalid run_id: use letters, numbers, hyphens or underscores" >&2
  exit 1
fi

OUT_DIR="outputs/curate/$RUN_ID"
EVIDENCE_DIR="evidence/task3/runs/$RUN_ID"

for d in "$OUT_DIR" "$EVIDENCE_DIR"; do
  if [[ -e "$d" ]]; then
    echo "Directory already exists: $d" >&2
    exit 1
  fi
done

PY="env PYTHONPATH=/work/python-packages python3"

echo "RUN_ID: $RUN_ID"

echo "=== CHECK POD + INPUTS ==="
kubectl wait --for=condition=Ready "pod/$POD" -n "$NS" --timeout=120s
kubectl exec -n "$NS" "$POD" -- \
  ls /work/envelopes.jsonl /work/staged/sensors.csv /work/stage-report.json

echo "=== VALIDATE CONTRACT (local) ==="
python3 src/validate_contract.py

echo "=== COPY CONTRACT, SQL, SCRIPTS, FIXTURES ==="
kubectl cp contracts/contract.json           "$NS/$POD:/work/contract.json"
kubectl cp contracts/curation_decisions.json "$NS/$POD:/work/curation_decisions.json"
kubectl cp src/curate.sql                    "$NS/$POD:/work/curate.sql"
kubectl cp src/run_curate.py                 "$NS/$POD:/work/run_curate.py"
kubectl cp src/test_curate.py                "$NS/$POD:/work/test_curate.py"
kubectl exec -n "$NS" "$POD" -- mkdir -p /work/tests/fixtures/edge
for f in envelopes.jsonl sensors.csv stage-report.json expected.json; do
  kubectl cp "tests/fixtures/edge/$f" "$NS/$POD:/work/tests/fixtures/edge/$f"
done
if [[ -f evidence/task2/quality_before.json ]]; then
  kubectl cp evidence/task2/quality_before.json "$NS/$POD:/work/quality_before.json"
  BASELINE="--baseline /work/quality_before.json"
else
  BASELINE=""
fi

echo "=== CURATE ==="
kubectl exec -n "$NS" "$POD" -- $PY /work/run_curate.py --run-id "$RUN_ID"

echo "=== TESTS C01-C05 ==="
set +e
kubectl exec -n "$NS" "$POD" -- $PY /work/test_curate.py \
  --run-id "$RUN_ID" --evidence-dir "/work/evidence/task3/$RUN_ID" $BASELINE
TEST_RC=$?
set -e

echo "=== COPY ARTIFACTS + EVIDENCE ==="
mkdir -p outputs/curate "$EVIDENCE_DIR"
kubectl cp "$NS/$POD:/work/curate/$RUN_ID" "$OUT_DIR"
kubectl cp "$NS/$POD:/work/evidence/task3/$RUN_ID/curate-checks.json" \
  "$EVIDENCE_DIR/curate-checks.json"
# Evidence chỉ chứa hash/số đếm, không chứa dữ liệu raw
cp "$OUT_DIR/artifact-hashes.json" "$EVIDENCE_DIR/artifact-hashes.json"
cp "$OUT_DIR/run-manifest.json"    "$EVIDENCE_DIR/run-manifest.json"

echo "=== ARTIFACT HASHES ==="
cat "$OUT_DIR/artifact-hashes.json"

if [[ "$TEST_RC" -ne 0 ]]; then
  echo "TASK 3: FAIL (xem $EVIDENCE_DIR/curate-checks.json)" >&2
  exit 1
fi
echo "TASK 3 CURATE + C01-C05: PASS"
