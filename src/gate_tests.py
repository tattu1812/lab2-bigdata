#!/usr/bin/env python3
"""Task 5 - chạy 8 ca đột biến P01-P08 qua gate và ghi gate-tests.json.

Mỗi ca copy bundle gốc sang <work-dir>/<case>/ rồi mới sửa: bundle gốc và raw
trên S3 không bị đụng tới (hash bundle gốc được đo trước/sau để chứng minh).
Các ca phải REJECT còn được đưa qua publish.py với release_id <release-base>-<case>:
publish phải từ chối trước mọi lần ghi S3, nên các release đó không có manifest.

Dùng: python3 gate_tests.py --root <bundle> --run-id <curate_run> --work-dir <dir mới>
                            --release-base <id> --operator <tên> --out <gate-tests.json>
"""

import argparse
import datetime
import hashlib
import json
import shutil
import sys
from decimal import Decimal
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gate import q, read_csv, run_gate, sha256_file  # noqa: E402
from publish import publish  # noqa: E402


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def tree_digest(root: Path):
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(root)).encode())
            h.update(sha256_file(p).encode())
    return h.hexdigest()


def rewrite_parquet(path: Path, select_sql: str):
    tmp = path.with_suffix(".tmp.parquet")
    con = duckdb.connect()
    con.execute(f"CREATE VIEW c AS SELECT * FROM read_parquet('{q(path)}')")
    con.execute(f"COPY ({select_sql}) TO '{q(tmp)}' (FORMAT PARQUET)")
    con.close()
    tmp.replace(path)


def qa_ids(root: Path):
    return {r["record_id"].strip(): Decimal(r["reference_c"]) for r in read_csv(root / "staged/qa_reference.csv")}


def non_qa_record(root: Path, parquet: Path):
    ids = "', '".join(qa_ids(root))
    con = duckdb.connect()
    rid = con.execute(
        f"SELECT min(record_id) FROM read_parquet('{q(parquet)}') WHERE record_id NOT IN ('{ids}')"
    ).fetchone()[0]
    con.close()
    return rid


# Mỗi hàm sửa bản sao và trả mô tả thay đổi đã thực hiện.
def p01(root, parquet, run_id):
    return {"artifact": None, "change": "không sửa gì"}


def p02(root, parquet, run_id):
    rid = non_qa_record(root, parquet)
    rewrite_parquet(parquet, f"SELECT * REPLACE (CASE WHEN record_id = '{rid}' "
                             f"THEN CAST(100.00 AS DECIMAL(8,2)) ELSE temperature_c END AS temperature_c) FROM c")
    return {"artifact": "candidate/curated.parquet", "change": f"{rid}.temperature_c = 100.00"}


def p03(root, parquet, run_id):
    rid = non_qa_record(root, parquet)
    rewrite_parquet(parquet, f"SELECT * REPLACE (CASE WHEN record_id = '{rid}' "
                             f"THEN CAST(NULL AS DECIMAL(8,2)) ELSE temperature_c END AS temperature_c) FROM c")
    return {"artifact": "candidate/curated.parquet", "change": f"{rid}.temperature_c = NULL"}


def p04(root, parquet, run_id):
    rid = non_qa_record(root, parquet)
    rewrite_parquet(parquet, f"SELECT * FROM c UNION ALL SELECT * FROM c WHERE record_id = '{rid}'")
    return {"artifact": "candidate/curated.parquet", "change": f"thêm một dòng trùng record_id {rid}"}


def p05(root, parquet, run_id):
    path = root / "catalog.json"
    catalog = json.loads(path.read_text(encoding="utf-8"))
    ds = next(d for d in catalog["datasets"] if d["dataset_id"] == "curated_candidate")
    old = ds.pop("steward")
    path.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"artifact": "catalog.json", "change": f"xóa steward ('{old}') của curated_candidate"}


def p06(root, parquet, run_id):
    path = root / "staged/observations_a.csv"
    before = sha256_file(path)
    data = bytearray(path.read_bytes())
    pos = next(i for i in range(len(data) // 2, len(data)) if chr(data[i]).isdigit())
    old = chr(data[pos])
    data[pos] = ord("7" if old != "7" else "3")
    path.write_bytes(bytes(data))
    return {"artifact": "staged/observations_a.csv (bản sao)",
            "change": f"byte offset {pos}: '{old}' -> '{chr(data[pos])}'",
            "sha256_before": before, "sha256_after": sha256_file(path)}


def p07(root, parquet, run_id):
    path = root / "evidence/task4/lineage.jsonl"
    events = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    complete = next(e for e in events if e["eventType"] == "COMPLETE")
    removed = complete["outputs"].pop()["name"]
    path.write_text("".join(json.dumps(e, ensure_ascii=False, separators=(",", ":")) + "\n" for e in events),
                    encoding="utf-8")
    return {"artifact": "evidence/task4/lineage.jsonl", "change": f"xóa output {removed} khỏi COMPLETE"}


def p08(root, parquet, run_id):
    ref = qa_ids(root)
    con = duckdb.connect()
    rows = con.execute(
        f"SELECT record_id, CAST(temperature_c AS VARCHAR) FROM read_parquet('{q(parquet)}') ORDER BY record_id"
    ).fetchall()
    con.close()
    rid = next(r for r, t in rows if r in ref and abs(Decimal(t) - ref[r]) > Decimal("0.05"))
    rewrite_parquet(parquet, f"SELECT * FROM c WHERE record_id <> '{rid}'")
    return {"artifact": "candidate/curated.parquet",
            "change": f"xóa {rid} (QA lệch) khỏi candidate -> độ khớp tăng nhưng độ phủ giảm"}


CASES = [
    ("P01", "Candidate nguyên vẹn", p01, "PASS", []),
    ("P02", "Một temperature_c = 100.00", p02, "REJECT", ["VALUE"]),
    ("P03", "Một temperature_c = NULL", p03, "REJECT", ["REQUIRED", "VALUE"]),
    ("P04", "Thêm một dòng trùng record_id", p04, "REJECT", ["UNIQUENESS", "RECONCILIATION"]),
    ("P05", "Xóa steward trong metadata", p05, "REJECT", ["METADATA"]),
    ("P06", "Sửa byte bản sao nguồn", p06, "REJECT", ["INPUT_INTEGRITY"]),
    ("P07", "Xóa một output lineage của curate", p07, "REJECT", ["LINEAGE"]),
    ("P08", "Xóa một ID QA bị lệch khỏi candidate", p08, "REJECT", ["COVERAGE"]),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--work-dir", required=True)
    ap.add_argument("--release-base", required=True)
    ap.add_argument("--operator", required=True)
    ap.add_argument("--test-id", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    base, work = Path(args.root), Path(args.work_dir)
    if work.exists():
        raise SystemExit(f"Thư mục đã tồn tại: {work}")
    work.mkdir(parents=True)
    base_digest_before = tree_digest(base)

    results = []
    for case_id, title, mutate, want, want_categories in CASES:
        case_root = work / case_id / "bundle"
        shutil.copytree(base, case_root)
        parquet = case_root / "outputs/curate" / args.run_id / "candidate/curated.parquet"
        started = now()
        mutation = mutate(case_root, parquet, args.run_id)
        gate = run_gate(case_root, args.run_id)
        (work / case_id / "gate-report.json").write_text(
            json.dumps(gate, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")

        failed = gate["failed_categories"]
        hit = [c for c in want_categories if c in failed]
        ok = gate["decision"] == want and (not want_categories or bool(hit))
        record = {
            "case_id": case_id,
            "title": title,
            "artifact_changed": mutation.pop("artifact"),
            "mutation": mutation,
            "expected": want if want == "PASS" else f"REJECT / {' hoặc '.join(want_categories)}",
            "observed_decision": gate["decision"],
            "observed_passed": gate["passed"],
            "observed_failed_categories": failed,
            "expected_category_hit": hit,
            "measured_errors": {r["category"]: r["reasons"] for r in gate["checks"] if r["status"] != "PASS"},
            "candidate_sha256": gate["candidate_sha256"],
            "result": "PASS" if ok else "FAIL",
            "operator": args.operator,
            "started_at": started,
            "finished_at": now(),
        }
        if want == "REJECT":
            rel = f"{args.release_base}-{case_id}"
            code = publish(case_root, args.run_id, rel, None, work / case_id / "publish", args.operator)
            pr = json.loads((work / case_id / "publish/publish-result.json").read_text(encoding="utf-8"))
            record["publish_attempt"] = {"release_id": rel, "status": pr["status"], "exit_code": code,
                                         "reason": pr.get("reason"), "s3_writes": pr["s3_writes"]}
            if pr["status"] != "REFUSED" or pr["s3_writes"] != 0:
                record["result"] = "FAIL"
        results.append(record)
        print(f"{case_id} {record['observed_decision']:<7} {record['observed_passed']} "
              f"failed={failed} -> {record['result']}")

    base_digest_after = tree_digest(base)
    report = {
        "test_id": args.test_id,
        "curate_run_id": args.run_id,
        "operator": args.operator,
        "executed_at": now(),
        "gate_sha256": sha256_file(Path(__file__).resolve().parent / "gate.py"),
        "base_bundle_unchanged": base_digest_before == base_digest_after,
        "base_bundle_digest": base_digest_before,
        "cases": results,
        "rejected_cases": sum(1 for r in results if r["observed_decision"] == "REJECT"),
        "status": "PASS" if all(r["result"] == "PASS" for r in results)
                  and base_digest_before == base_digest_after else "FAIL",
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"GATE TESTS: {report['status']} ({report['rejected_cases']} ca bị REJECT)")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
