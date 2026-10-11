#!/usr/bin/env python3
"""Task 3 - kiểm chứng phép biến đổi C01-C05 trên một run đã có.

  C01  bảo toàn tập hợp: raw = curated + quarantine + duplicates, khóa vật lý
       rời nhau và phủ đủ envelope (đếm độc lập bằng Python)
  C02  tất định: chạy lại với envelope đảo thứ tự -> artifact giống hệt
  C03  schema Parquet: đúng 10 cột/kiểu theo contract, không trường nhạy cảm
  C04  4 ca biên (fixture nhỏ) khớp expected.json
  C05  tính lại chất lượng "sau" từ curated.parquet theo release_thresholds

Kết quả: <evidence-dir>/curate-checks.json   (exit 0 nếu tất cả PASS)
"""

import argparse
import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def q(p) -> str:
    return str(p).replace("'", "''")


def read_csv_rows(p: Path):
    with p.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def parquet_digest(path: Path) -> str:
    """Hash nội dung logic của parquet (độc lập metadata tệp)."""
    con = duckdb.connect()
    rows = con.execute(
        f"SELECT * FROM read_parquet('{q(path)}') ORDER BY record_id"
    ).fetchall()
    con.close()
    return hashlib.sha256(repr(rows).encode("utf-8")).hexdigest()


def run_curate(args, run_id, out_root, *, envelopes, sensors, stage_report, reverse=False):
    cmd = [
        sys.executable, str(HERE / "run_curate.py"),
        "--run-id", run_id, "--out-root", str(out_root),
        "--contract", args.contract, "--decisions", args.decisions, "--sql", args.sql,
        "--envelopes", str(envelopes), "--sensors", str(sensors),
        "--stage-report", str(stage_report),
    ]
    if reverse:
        cmd.append("--reverse-input")
    res = subprocess.run(cmd, capture_output=True, text=True)
    return res.returncode, res.stdout[-2000:], res.stderr[-2000:]


# --------------------------------------------------------------------------
def c01(args, run_dir):
    keys_raw = []
    with Path(args.envelopes).open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                e = json.loads(line)
                keys_raw.append((e["source_object"], int(e["source_row"])))

    con = duckdb.connect()
    cur = con.execute(
        f"SELECT source_object, source_row FROM read_parquet('{q(run_dir / 'candidate/curated.parquet')}')"
    ).fetchall()
    con.close()
    qua = [(r["source_object"], int(r["source_row"])) for r in read_csv_rows(run_dir / "quarantine.csv")]
    dup = [(r["source_object"], int(r["source_row"])) for r in read_csv_rows(run_dir / "duplicates.csv")]

    union = cur + qua + dup
    overlap = len(union) - len(set(union))
    missing = set(keys_raw) - set(union)
    extra = set(union) - set(keys_raw)
    details = {
        "raw_total": len(keys_raw), "raw_unique_keys": len(set(keys_raw)),
        "curated": len(cur), "quarantine": len(qua), "duplicates": len(dup),
        "sum": len(union), "overlap": overlap,
        "missing_from_outputs": len(missing), "unknown_in_outputs": len(extra),
    }
    ok = (len(keys_raw) == len(set(keys_raw)) == len(union)
          and overlap == 0 and not missing and not extra)

    # Đối chiếu baseline Task 2 (chỉ báo cáo; không làm FAIL)
    baseline = None
    bp = Path(args.baseline) if args.baseline else None
    if bp and bp.exists():
        pop = json.loads(bp.read_text(encoding="utf-8"))["population_summary"]
        manifest = json.loads((run_dir / "run-manifest.json").read_text(encoding="utf-8"))["counts"]
        w_check = len(cur) + sum(
            1 for r in read_csv_rows(run_dir / "quarantine.csv") if r["stage"] == "WINNER"
        )
        baseline = {
            "task2_raw_total": pop["raw_total"], "run_raw_total": manifest["raw_total"],
            "task2_prekey_rejected": pop["parse_failures"] + pop["key_excluded"] + pop["ingest_parse_failures"],
            "run_prekey_rejected": manifest["prekey_rejected"],
            "task2_duplicates": pop["duplicates"], "run_duplicates": manifest["duplicates"],
            "task2_W": pop["winners_W"], "run_W": w_check,
        }
        baseline["match"] = (
            baseline["task2_raw_total"] == baseline["run_raw_total"]
            and baseline["task2_prekey_rejected"] == baseline["run_prekey_rejected"]
            and baseline["task2_duplicates"] == baseline["run_duplicates"]
            and baseline["task2_W"] == baseline["run_W"]
        )
        details["task2_baseline"] = baseline
    return ok, details


def c02(args, run_dir, check_root):
    rid = run_dir.name + "-rev"
    rc, out, err = run_curate(
        args, rid, check_root, envelopes=args.envelopes, sensors=args.sensors,
        stage_report=args.stage_report, reverse=True,
    )
    if rc != 0:
        return False, {"error": "rerun thất bại", "stdout": out, "stderr": err}
    rev = check_root / rid
    files = {}
    ok = True
    for name in ("quarantine.csv", "duplicates.csv"):
        a, b = sha256_file(run_dir / name), sha256_file(rev / name)
        files[name] = {"original": a, "reversed": b, "equal": a == b}
        ok &= a == b
    pa = run_dir / "candidate/curated.parquet"
    pb = rev / "candidate/curated.parquet"
    da, db = parquet_digest(pa), parquet_digest(pb)
    files["curated.parquet"] = {
        "content_original": da, "content_reversed": db, "content_equal": da == db,
        "file_sha256_equal": sha256_file(pa) == sha256_file(pb),
    }
    ok &= da == db
    return ok, {"files": files}


EXPECTED_TYPES = {
    "record_id": "VARCHAR", "sensor_id": "VARCHAR", "site": "VARCHAR",
    "event_time_utc": "TIMESTAMP", "ingest_time_utc": "TIMESTAMP",
    "is_late": "BOOLEAN", "source_object": "VARCHAR",
    "source_row": "BIGINT", "source_sha256": "VARCHAR",
}


def c03(args, run_dir, contract):
    path = run_dir / "candidate/curated.parquet"
    con = duckdb.connect()
    schema = con.execute(
        f"SELECT column_name, column_type FROM (DESCRIBE SELECT * FROM read_parquet('{q(path)}'))"
    ).fetchall()
    cols = [c for c, _ in schema]
    types = dict(schema)
    expected_cols = contract["released_columns"]
    expected_types = dict(EXPECTED_TYPES)
    expected_types["temperature_c"] = contract["temperature_validation"]["output_type"].replace(" ", "")
    restricted = contract["privacy"]["restricted_fields"]

    problems = []
    if cols != expected_cols:
        problems.append(f"cột/thứ tự khác contract: {cols}")
    for c, t in expected_types.items():
        if types.get(c) != t:
            problems.append(f"{c}: {types.get(c)} != {t}")
    if len(cols) != 10:
        problems.append(f"số cột = {len(cols)}")
    leaked = [c for c in cols if c in restricted]
    if leaked:
        problems.append(f"trường nhạy cảm trong parquet: {leaked}")
    for name in ("quarantine.csv", "duplicates.csv"):
        header = (run_dir / name).read_text(encoding="utf-8").splitlines()[0].split(",")
        bad = [h for h in header if h in restricted]
        if bad:
            problems.append(f"{name} chứa cột nhạy cảm: {bad}")
    nulls = con.execute(
        f"SELECT count(*) FROM read_parquet('{q(path)}') WHERE "
        + " OR ".join(f"{c} IS NULL" for c in expected_cols)
    ).fetchone()[0]
    if nulls:
        problems.append(f"{nulls} dòng có giá trị NULL")
    con.close()
    return not problems, {"columns": schema, "problems": problems}


def c04(args, check_root):
    fx = Path(args.fixtures)
    rid = "edge"
    rc, out, err = run_curate(
        args, rid, check_root, envelopes=fx / "envelopes.jsonl",
        sensors=fx / "sensors.csv", stage_report=fx / "stage-report.json",
    )
    if rc != 0:
        return False, {"error": "chạy fixture thất bại", "stdout": out, "stderr": err}
    run = check_root / rid
    exp = json.loads((fx / "expected.json").read_text(encoding="utf-8"))
    problems = []

    con = duckdb.connect()
    got_cur = {}
    for r in con.execute(
        f"SELECT record_id, site, CAST(temperature_c AS VARCHAR), is_late, source_object, source_row "
        f"FROM read_parquet('{q(run / 'candidate/curated.parquet')}')"
    ).fetchall():
        got_cur[f"{r[4]}#{r[5]}"] = {
            "record_id": r[0], "site": r[1], "temperature_c": r[2], "is_late": r[3],
        }
    con.close()
    got_q = {
        f"{r['source_object']}#{r['source_row']}": {
            "stage": r["stage"], "primary_reason": r["primary_reason"], "reasons": r["reasons"],
        } for r in read_csv_rows(run / "quarantine.csv")
    }
    got_d = {
        f"{r['source_object']}#{r['source_row']}": {
            "record_id": r["record_id"], "reason": r["reason"],
            "winner": f"{r['winner_source_object']}#{r['winner_source_row']}",
        } for r in read_csv_rows(run / "duplicates.csv")
    }

    for name, got in (("curated", got_cur), ("quarantine", got_q), ("duplicates", got_d)):
        want = exp[name]
        for k in sorted(set(want) | set(got)):
            if want.get(k) != got.get(k):
                problems.append({"set": name, "key": k, "expected": want.get(k), "got": got.get(k)})

    total = len(got_cur) + len(got_q) + len(got_d)
    if total != exp["raw_total"]:
        problems.append(f"tổng {total} != raw_total {exp['raw_total']}")

    leak = exp["leak_marker"]
    for p in (run / "quarantine.csv", run / "duplicates.csv", run / "candidate/curated.parquet"):
        if leak.encode() in p.read_bytes():
            problems.append(f"rò rỉ operator_email trong {p.name}")

    return not problems, {
        "cases": {
            "EC1_invalid_winner_no_fallback": ["R000001", "R000002", "R000025"],
            "EC2_tie_break": ["R000003", "R000004"],
            "EC3_unit_range_rounding": [f"R{n:06d}" for n in (5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 26)],
            "EC4_time_late_multireason_prekey": [f"R{n:06d}" for n in (17, 18, 19, 20, 21, 22, 23, 24, 27, 28)] + ["PARSE", "KEY", "KEY|INGEST_PARSE"],
        },
        "counts": {"curated": len(got_cur), "quarantine": len(got_q), "duplicates": len(got_d)},
        "problems": problems,
    }


def c05(args, run_dir, contract):
    """Tính lại metric 'sau' bằng truy vấn độc lập curate.sql, từ curated.parquet."""
    th = contract["release_thresholds"]
    rng = contract["temperature_range_c"]
    path = q(run_dir / "candidate/curated.parquet")
    con = duckdb.connect()
    con.execute(
        f"CREATE VIEW reg AS SELECT upper(trim(sensor_id)) AS sensor_id, trim(site) AS site "
        f"FROM read_csv('{q(args.sensors)}', header=true, all_varchar=true)"
    )
    con.execute(f"CREATE VIEW c AS SELECT * FROM read_parquet('{path}')")
    as_of = con.execute(
        "SELECT strptime(?, '%Y-%m-%dT%H:%M:%SZ')", [contract["as_of"]]
    ).fetchone()[0]
    n, = con.execute("SELECT count(*) FROM c").fetchone()

    def cnt(where):
        return con.execute(f"SELECT count(*) FROM c WHERE {where}").fetchone()[0]

    nums = {
        "required_completeness": cnt(" AND ".join(f"{col} IS NOT NULL" for col in contract["released_columns"])),
        "business_key_uniqueness": con.execute("SELECT count(DISTINCT record_id) FROM c").fetchone()[0],
        "value_validity": cnt(f"temperature_c BETWEEN {rng['min']} AND {rng['max']}"),
        "sensor_consistency": con.execute(
            "SELECT count(*) FROM c JOIN reg r ON r.sensor_id = c.sensor_id AND r.site = c.site"
        ).fetchone()[0],
        "chronology": con.execute(
            "SELECT count(*) FROM c WHERE event_time_utc <= ingest_time_utc AND ingest_time_utc <= ?",
            [as_of],
        ).fetchone()[0],
        "timeliness": con.execute(
            "SELECT count(*) FROM c WHERE epoch(ingest_time_utc) - epoch(event_time_utc) <= ?",
            [contract["late_threshold_seconds"]],
        ).fetchone()[0],
    }
    is_late_consistent = con.execute(
        "SELECT count(*) FROM c WHERE is_late <> "
        "((epoch(ingest_time_utc) - epoch(event_time_utc)) > ?)",
        [contract["late_threshold_seconds"]],
    ).fetchone()[0] == 0
    con.close()

    metrics, ok = [], is_late_consistent
    for rule, num in nums.items():
        value = None if n == 0 else num / n
        status = "NOT_EVALUATED" if n == 0 else ("PASS" if value >= th[rule] else "FAIL")
        ok &= status == "PASS"
        metrics.append({"rule_id": rule, "numerator": num, "denominator": n,
                        "value": value, "threshold": th[rule], "status": status})
    return ok, {"cohort": "curated", "is_late_consistent": is_late_consistent,
                "metrics": metrics,
                "note": "qa_coverage/qa_agreement thuộc Task 2B (qa_reference.csv), không tính ở đây"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True, help="run curate chính cần kiểm chứng")
    ap.add_argument("--out-root", default="/work/curate")
    ap.add_argument("--contract", default="/work/contract.json")
    ap.add_argument("--decisions", default="/work/curation_decisions.json")
    ap.add_argument("--sql", default="/work/curate.sql")
    ap.add_argument("--envelopes", default="/work/envelopes.jsonl")
    ap.add_argument("--sensors", default="/work/staged/sensors.csv")
    ap.add_argument("--stage-report", default="/work/stage-report.json")
    ap.add_argument("--fixtures", default="/work/tests/fixtures/edge")
    ap.add_argument("--baseline", default=None, help="evidence/task2/quality_before.json (tùy chọn)")
    ap.add_argument("--evidence-dir", default="/work/evidence/task3")
    args = ap.parse_args()

    run_dir = Path(args.out_root) / args.run_id
    check_root = Path(args.out_root) / f"{args.run_id}-checks"
    contract = json.loads(Path(args.contract).read_text(encoding="utf-8"))

    results = {}
    for cid, fn in (
        ("C01", lambda: c01(args, run_dir)),
        ("C02", lambda: c02(args, run_dir, check_root)),
        ("C03", lambda: c03(args, run_dir, contract)),
        ("C04", lambda: c04(args, check_root)),
        ("C05", lambda: c05(args, run_dir, contract)),
    ):
        ok, details = fn()
        results[cid] = {"status": "PASS" if ok else "FAIL", "details": details}
        print(f"{cid}: {results[cid]['status']}")

    overall = all(r["status"] == "PASS" for r in results.values())
    report = {"run_id": args.run_id, "status": "PASS" if overall else "FAIL", "checks": results}
    ev = Path(args.evidence_dir)
    ev.mkdir(parents=True, exist_ok=True)
    (ev / "curate-checks.json").write_text(
        json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8"
    )
    print("TASK 3 CHECKS:", report["status"])
    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(main())
