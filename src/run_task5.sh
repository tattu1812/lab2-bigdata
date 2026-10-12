#!/usr/bin/env bash
# Task 5 - gate, đột biến, công bố release và kiểm tra phía analyst.
# Dùng:  source env.sh
#   ./src/run_task5.sh setup
#   ./src/run_task5.sh gate-tests     <curate_run_id> <test_id>  <release_base>
#   ./src/run_task5.sh crosscheck     <curate_run_id> <check_id>
#   ./src/run_task5.sh review-request <curate_run_id> <release_id>
#   ./src/run_task5.sh publish        <curate_run_id> <release_id>   (cần evidence/task5/review.json)
#   ./src/run_task5.sh consume        <release_id> <rejected_release_ids_csv>
set -euo pipefail

cd "$(dirname "$0")/.."

: "${NS:?Run 'source env.sh' first to set NS}"

PUB="publisher"
CON="consumer"
OPERATOR="${OPERATOR:-Trung}"
PY="env PYTHONPATH=/work/python-packages:/work/task5 python3"
EV="evidence/task5"

valid_id() {
  [[ "$1" =~ ^[a-zA-Z0-9_-]+$ ]] || { echo "Invalid id: $1" >&2; exit 1; }
}

new_dir() {
  if [[ -e "$1" ]]; then
    echo "Directory already exists: $1" >&2
    exit 1
  fi
  mkdir -p "$1"
}

install_duckdb() {
  kubectl exec -n "$NS" "$1" -- env PYTHONPATH=/work/python-packages python3 -c "import duckdb" 2>/dev/null || \
    kubectl exec -n "$NS" "$1" -- python3 -m pip install -q --no-cache-dir \
      --target /work/python-packages duckdb==1.4.1
}

copy_scripts() {
  kubectl exec -n "$NS" "$PUB" -- mkdir -p /work/task5
  for f in gate.py gate_tests.py publish.py crosscheck_qa.py stage_inputs.py; do
    kubectl cp "src/$f" "$NS/$PUB:/work/task5/$f"
  done
}

# Dựng bundle mới trong Pod publisher: metadata + artifact từ repo, input tải lại từ S3.
make_bundle() {
  local run="$1" bundle="/work/bundles/$2"
  [[ -f "outputs/curate/$run/candidate/curated.parquet" ]] || {
    echo "Missing outputs/curate/$run (run ./src/run_task3.sh first)" >&2; exit 1; }
  if kubectl exec -n "$NS" "$PUB" -- test -e "$bundle"; then
    echo "Bundle already exists: $bundle" >&2; exit 1
  fi
  kubectl exec -n "$NS" "$PUB" -- mkdir -p \
    "$bundle/outputs/curate/$run/candidate" "$bundle/evidence/task4" "$bundle/contracts" \
    "$bundle/data" "$bundle/src" "$bundle/schemas"
  for f in candidate/curated.parquet quarantine.csv duplicates.csv run-manifest.json artifact-hashes.json; do
    kubectl cp "outputs/curate/$run/$f" "$NS/$PUB:$bundle/outputs/curate/$run/$f"
  done
  for f in catalog.json schemas/catalog.schema.json evidence/task4/lineage.jsonl \
           evidence/task4/run-record.json contracts/contract.json contracts/curation_decisions.json \
           data/trusted_manifest.json src/curate.sql src/run_curate.py; do
    kubectl cp "$f" "$NS/$PUB:$bundle/$f"
  done
  kubectl exec -n "$NS" "$PUB" -- $PY /work/task5/stage_inputs.py s3 "$bundle/data/trusted_manifest.json" \
    --output-dir "$bundle/staged" --report "$bundle/stage-report.json"
}

cmd="${1:?Usage: see header of $0}"
shift

case "$cmd" in
  setup)
    kubectl apply -f manifests/publisher.yaml
    kubectl apply -f manifests/consumer.yaml
    kubectl wait --for=condition=Ready "pod/$PUB" "pod/$CON" -n "$NS" --timeout=180s
    install_duckdb "$PUB"
    install_duckdb "$CON"
    for p in "$PUB" "$CON"; do
      echo "$p: $(kubectl exec -n "$NS" "$p" -- sh -c 'echo $PRINCIPAL') duckdb=$(kubectl exec -n "$NS" "$p" -- \
        env PYTHONPATH=/work/python-packages python3 -c 'import duckdb; print(duckdb.__version__)')"
    done
    ;;

  gate-tests)
    RUN="${1:?curate_run_id}"; TEST_ID="${2:?test_id}"; BASE="${3:?release_base}"
    valid_id "$RUN"; valid_id "$TEST_ID"; valid_id "$BASE"
    OUT="$EV/runs/$TEST_ID"; new_dir "$OUT"
    copy_scripts
    make_bundle "$RUN" "$TEST_ID"
    set +e
    kubectl exec -n "$NS" "$PUB" -- $PY /work/task5/gate_tests.py \
      --root "/work/bundles/$TEST_ID" --run-id "$RUN" --work-dir "/work/gate-tests/$TEST_ID" \
      --release-base "$BASE" --operator "$OPERATOR" --test-id "$TEST_ID" \
      --out "/work/gate-tests/$TEST_ID/gate-tests.json"
    RC=$?
    set -e
    kubectl cp "$NS/$PUB:/work/gate-tests/$TEST_ID/gate-tests.json" "$OUT/gate-tests.json"
    for c in P01 P02 P03 P04 P05 P06 P07 P08; do
      kubectl cp "$NS/$PUB:/work/gate-tests/$TEST_ID/$c/gate-report.json" "$OUT/$c-gate-report.json"
    done
    cp "$OUT/gate-tests.json" "$EV/gate-tests.json"
    exit "$RC"
    ;;

  crosscheck)
    RUN="${1:?curate_run_id}"; ID="${2:?check_id}"
    valid_id "$RUN"; valid_id "$ID"
    OUT="$EV/runs/$ID"; new_dir "$OUT"
    copy_scripts
    make_bundle "$RUN" "$ID"
    kubectl cp evidence/task2/quality_after.json "$NS/$PUB:/work/bundles/$ID/quality_after.json"
    B="/work/bundles/$ID"
    set +e
    kubectl exec -n "$NS" "$PUB" -- $PY /work/task5/crosscheck_qa.py \
      --candidate "$B/outputs/curate/$RUN/candidate/curated.parquet" --qa "$B/staged/qa_reference.csv" \
      --quality-after "$B/quality_after.json" \
      --tolerance "$(python3 -c 'import json; print(json.load(open("contracts/contract.json"))["qa_tolerance_c"])')" \
      --out "$B/qa-crosscheck.json"
    RC=$?
    set -e
    kubectl cp "$NS/$PUB:$B/qa-crosscheck.json" "$OUT/qa-crosscheck.json"
    cp "$OUT/qa-crosscheck.json" "$EV/qa-crosscheck.json"
    exit "$RC"
    ;;

  review-request)
    RUN="${1:?curate_run_id}"; REL="${2:?release_id}"
    valid_id "$RUN"; valid_id "$REL"
    ID="$REL-prereview"; OUT="$EV/runs/$ID"; new_dir "$OUT"
    copy_scripts
    make_bundle "$RUN" "$ID"
    set +e
    kubectl exec -n "$NS" "$PUB" -- $PY /work/task5/gate.py \
      --root "/work/bundles/$ID" --run-id "$RUN" --out "/work/bundles/$ID/gate-report.json"
    RC=$?
    set -e
    kubectl cp "$NS/$PUB:/work/bundles/$ID/gate-report.json" "$OUT/gate-report.json"
    RUN="$RUN" REL="$REL" OUT="$OUT" python3 - <<'PY'
import json, os
from pathlib import Path
out = Path(os.environ["OUT"])
gate = json.loads((out / "gate-report.json").read_text(encoding="utf-8"))
request = {
    "release_id": os.environ["REL"],
    "run_id": os.environ["RUN"],
    "candidate_sha256": gate["candidate_sha256"],
    "gate_decision": gate["decision"],
    "gate_passed": gate["passed"],
    "gate_report": str(out / "gate-report.json"),
    "review_template": {
        "reviewer": "<tên người review, KHÔNG phải tác giả curation>",
        "curation_author": "Khánh",
        "decision": "<APPROVE | REJECT>",
        "reason": "<lý do>",
        "run_id": os.environ["RUN"],
        "candidate_sha256": gate["candidate_sha256"],
        "reviewed_at": "<YYYY-MM-DDTHH:MM:SSZ>",
    },
}
(out / "review-request.json").write_text(json.dumps(request, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(json.dumps(request, indent=2, ensure_ascii=False))
PY
    exit "$RC"
    ;;

  publish)
    RUN="${1:?curate_run_id}"; REL="${2:?release_id}"
    valid_id "$RUN"; valid_id "$REL"
    [[ -f "$EV/review.json" ]] || { echo "Missing $EV/review.json (run review-request first)" >&2; exit 1; }
    OUT="$EV/runs/$REL"; new_dir "$OUT"; rmdir "$OUT"   # kubectl cp tạo lại thư mục này
    copy_scripts
    make_bundle "$RUN" "$REL"
    kubectl cp "$EV/review.json" "$NS/$PUB:/work/bundles/$REL/review.json"
    set +e
    kubectl exec -n "$NS" "$PUB" -- $PY /work/task5/publish.py \
      --root "/work/bundles/$REL" --run-id "$RUN" --release-id "$REL" \
      --review "/work/bundles/$REL/review.json" --evidence-dir "/work/publish/$REL" --operator "$OPERATOR"
    RC=$?
    set -e
    kubectl cp "$NS/$PUB:/work/publish/$REL" "$OUT"
    if [[ "$RC" -eq 0 ]]; then
      cp "$OUT/release_manifest.json" "$EV/release_manifest.json"
      cp "$OUT/lineage-publish.jsonl" "$EV/lineage-publish.jsonl"
    fi
    exit "$RC"
    ;;

  consume)
    REL="${1:?release_id}"; REJECTED="${2:?rejected_release_ids_csv}"
    valid_id "$REL"
    ID="$REL-consumer"; OUT="$EV/runs/$ID"; new_dir "$OUT"
    kubectl exec -n "$NS" "$CON" -- mkdir -p /work/task5
    kubectl cp src/consumer_check.py "$NS/$CON:/work/task5/consumer_check.py"
    set +e
    kubectl exec -n "$NS" "$CON" -- env PYTHONPATH=/work/python-packages python3 /work/task5/consumer_check.py \
      --release-id "$REL" --rejected "$REJECTED" --operator "$OPERATOR" --out "/work/task5/$ID.json"
    RC=$?
    set -e
    kubectl cp "$NS/$CON:/work/task5/$ID.json" "$OUT/consumer-check.json"
    cp "$OUT/consumer-check.json" "$EV/consumer-check.json"
    exit "$RC"
    ;;

  *)
    echo "Unknown command: $cmd" >&2
    exit 1
    ;;
esac
