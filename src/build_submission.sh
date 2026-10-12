#!/usr/bin/env bash
# Task 5 - gom file nộp cuối cùng.
# Dùng: ./src/build_submission.sh <submission_id> <curate_run_id>
# Tạo submission/<id>/lab2-submission.zip (bản chính),
#      submission/<id>/lab2-restricted.zip (chỉ sổ quarantine/duplicates) và SHA256SUMS.
set -euo pipefail

cd "$(dirname "$0")/.."

SUB_ID="${1:?Usage: ./src/build_submission.sh <submission_id> <curate_run_id>}"
RUN="${2:?Usage: ./src/build_submission.sh <submission_id> <curate_run_id>}"
[[ "$SUB_ID" =~ ^[a-zA-Z0-9_-]+$ && "$RUN" =~ ^[a-zA-Z0-9_-]+$ ]] || { echo "Invalid id" >&2; exit 1; }
OUT="submission/$SUB_ID"
[[ -e "$OUT" ]] && { echo "Directory already exists: $OUT" >&2; exit 1; }

SUB_ID="$SUB_ID" RUN="$RUN" OUT="$OUT" python3 - <<'PY'
import hashlib, json, os, re, sys, zipfile
from pathlib import Path

run, out = os.environ["RUN"], Path(os.environ["OUT"])

def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

# (đường dẫn trong ZIP, nguồn trong repo) theo checklist nộp bài
main = []
def add(src, dest=None):
    main.append((dest or src, src))

for p in sorted(Path("src").glob("*")):
    if p.suffix in (".py", ".sql", ".sh"):
        add(str(p), f"code/{p.name}")
for p in sorted(Path("manifests").glob("*.yaml")):
    add(str(p), f"code/manifests/{p.name}")
# Tú – Task 1
add("contracts/contract.json"); add("contracts/curation_decisions.json")
add("outputs/input_inventory.json", "task1/input_inventory.json")
for p in sorted(Path("evidence/task1").glob("*.json")) + sorted(Path("evidence/task1").glob("*.txt")):
    add(str(p))
for p in sorted(Path("evidence/task1/runs").rglob("*.json")):
    add(str(p))
# Trung Nguyễn – Task 2
for p in sorted(Path("evidence/task2").glob("*")):
    add(str(p))
# Khánh – Task 3 (manifest artifact + C01–C05)
for f in ("curate-checks.json", "artifact-hashes.json", "run-manifest.json"):
    add(f"evidence/task3/runs/{run}/{f}")
for p in sorted(Path("evidence/task3/runs").rglob("*.json")):   # các run tái lập khác
    if p.parent.name != run:
        add(str(p))
add("evidence/task3/contract-review.md")
# Hải Anh – Task 4
add("catalog.json"); add("schemas/catalog.schema.json")
for f in ("README.md", "lineage.jsonl", "run-record.json", "retention-plan.json", "trace-L02-L03.json"):
    add(f"evidence/task4/{f}")
# Trung – Task 5
for f in ("gate-tests.json", "consumer-check.json", "release_manifest.json",
          "lineage-publish.jsonl", "qa-crosscheck.json", "review.json"):
    add(f"evidence/task5/{f}")
for p in sorted(Path("evidence/task5").glob("*.md")):            # incident / erratum
    add(str(p))
for p in sorted(Path("evidence/task5/runs").rglob("*")):
    if p.is_file():
        add(str(p))
# Chung
add("README.md"); add("SUBMISSION.md")
add("contributions.csv"); add("evidence/evidence_index.csv")
for p in sorted(Path("individual").rglob("*")):                # phần cá nhân + kiểm tra chéo
    if p.is_file() and p.suffix in (".md", ".py", ".json", ".txt"):
        add(str(p))
for t in ("Task1Tutorial.md", "Task2Tutorial.md", "Task3Tutorial.md", "Task4Tutorial.md", "Task5Tutorial.md"):
    add(t, f"docs/{t}")

restricted = [(f"restricted/{f}", f"outputs/curate/{run}/{f}") for f in ("quarantine.csv", "duplicates.csv")]

missing = [src for _, src in main + restricted if not Path(src).is_file()]
if missing:
    print("THIẾU FILE:", *missing, sep="\n  ")
    sys.exit(1)

# Không nộp email thô và không nộp dữ liệu raw/credential
email = re.compile(rb"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
reserved = re.compile(rb"(^|\.)example\.(com|org|net|edu)$")   # RFC 2606, dùng làm marker trong test
leaks = [src for _, src in main
         if any(not reserved.search(m.group(1)) for m in email.finditer(Path(src).read_bytes()))]
banned = [src for _, src in main if re.search(r"envelopes\.jsonl|\.env$|kubeconfig|/data/", src)]
if leaks or banned:
    print("TỪ CHỐI GOM: có email thô hoặc file bị cấm:", *(leaks + banned), sep="\n  ")
    sys.exit(1)

# Trusted manifest không nộp nguyên bản (data/ bị ignore), chỉ nộp hash
trusted_hash = f"{sha('data/trusted_manifest.json')}  trusted_manifest.json\n"

out.mkdir(parents=True)
with zipfile.ZipFile(out / "lab2-submission.zip", "w", zipfile.ZIP_DEFLATED) as z:
    for dest, src in main:
        z.write(src, dest)
    z.writestr("task1/trusted_manifest.sha256", trusted_hash)
    z.writestr("FILES.sha256", "".join(f"{sha(src)}  {dest}\n" for dest, src in main))
with zipfile.ZipFile(out / "lab2-restricted.zip", "w", zipfile.ZIP_DEFLATED) as z:
    for dest, src in restricted:
        z.write(src, dest)
    z.writestr("restricted/README.txt",
               "Bản nộp hạn chế: sổ quarantine/duplicates của run " + run +
               ". Không đưa vào release cho analyst.\n")
(out / "SHA256SUMS").write_text(
    "".join(f"{sha(out / n)}  {n}\n" for n in ("lab2-submission.zip", "lab2-restricted.zip")))
print(f"lab2-submission.zip: {len(main) + 2} files")
print(f"lab2-restricted.zip: {len(restricted) + 1} files")
print((out / "SHA256SUMS").read_text(), end="")
PY
