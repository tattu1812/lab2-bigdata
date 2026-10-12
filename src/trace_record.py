#!/usr/bin/env python3
"""Task 4 – truy vết cấp dòng L02 (dòng curated) và L03 (dòng quarantine).

Đi ngược từ artifact đã lưu về envelope và object nguồn: object, SHA-256 nguồn (so với
trusted manifest), số thứ tự dòng, mọi phiên bản cùng record_id, phiên bản được chọn và
quy tắc biến đổi/lý do. Không xuất operator_email hay raw_line.

Chạy trong Pod curate (cần DuckDB để đọc Parquet):
  python3 trace_record.py --envelopes /work/envelopes.jsonl --manifest trusted_manifest.json \
    --sensors staged/sensors.csv --contract contract.json --artifacts <outputs/curate/RUN> \
    --accepted R001001 --quarantined R001051 --out trace-L02-L03.json
"""

import argparse
import csv
import datetime as dt
import hashlib
import json
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

JSON_TO_CANON = {"id": "record_id", "sensor": "sensor_id", "timestamp": "event_time",
                 "arrived_at": "ingest_time", "temperature": "reading", "temperature_unit": "unit"}
RESTRICTED = {"operator_email", "operator", "raw_line", "raw_payload"}
REQUIRED = ("record_id", "sensor_id", "event_time", "ingest_time", "reading", "unit")


def canon(payload):
    out = {}
    for k, v in (payload or {}).items():
        k = JSON_TO_CANON.get(k, k)
        if k not in RESTRICTED:
            out[k] = v
    return out


def norm(v):
    v = (v or "").strip().upper()
    return v or None


def ts(v, fmt):
    try:
        return dt.datetime.strptime((v or "").strip(), fmt)
    except ValueError:
        return None


def to_celsius(reading, unit):
    value = Decimal(reading.strip())
    if unit == "F":
        value = (value - 32) * 5 / 9
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def main():
    ap = argparse.ArgumentParser()
    for a in ("--envelopes", "--manifest", "--sensors", "--contract", "--artifacts",
              "--accepted", "--quarantined", "--out"):
        ap.add_argument(a, required=True)
    args = ap.parse_args()

    import duckdb

    contract = json.loads(Path(args.contract).read_text(encoding="utf-8"))
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    late_s = contract.get("late_threshold_seconds", 900)
    trusted = {o["key"]: o["sha256"] for o in json.loads(Path(args.manifest).read_text())["objects"]}
    sites = {norm(r["sensor_id"]): r["site"] for r in csv.DictReader(open(args.sensors, encoding="utf-8"))}
    art = Path(args.artifacts)

    quarantine = {(r["source_object"], int(r["source_row"])): r
                  for r in csv.DictReader(open(art / "quarantine.csv", encoding="utf-8"))}
    duplicates = {(r["source_object"], int(r["source_row"])): r
                  for r in csv.DictReader(open(art / "duplicates.csv", encoding="utf-8"))}
    con = duckdb.connect()
    cur_cols = [c[0] for c in con.execute(
        f"DESCRIBE SELECT * FROM read_parquet('{art / 'candidate/curated.parquet'}')").fetchall()]
    curated = {}
    for row in con.execute(f"SELECT * FROM read_parquet('{art / 'candidate/curated.parquet'}')").fetchall():
        r = dict(zip(cur_cols, row))
        curated[(r["source_object"], r["source_row"])] = r

    versions = {}
    for line in open(args.envelopes, encoding="utf-8"):
        env = json.loads(line)
        p = canon(env.get("payload"))
        rid = norm(p.get("record_id"))
        if rid in (args.accepted, args.quarantined):
            versions.setdefault(rid, []).append((env, p))

    def status(key):
        if key in curated:
            return {"output": "curated"}
        if key in quarantine:
            q = quarantine[key]
            return {"output": "quarantine", "stage": q["stage"], "primary_reason": q["primary_reason"],
                    "reasons": q["reasons"].split("|")}
        if key in duplicates:
            d = duplicates[key]
            return {"output": "duplicates", "reason": d["reason"],
                    "winner": [d["winner_source_object"], int(d["winner_source_row"])]}
        return {"output": "MISSING"}

    def trace(rid):
        rows = []
        for env, p in versions.get(rid, []):
            key = (env["source_object"], env["source_row"])
            rows.append({
                "source_object": key[0], "source_row": key[1],
                "source_sha256_trusted": trusted[key[0]],
                "parse_status": env["parse_status"],
                "fields": {k: p.get(k) for k in REQUIRED},
                "ingest_ts": p.get("ingest_time"),
                "status": status(key),
            })
        # Thứ tự khử trùng của contract: ingest_time DESC, source_object ASC, source_row ASC
        def order(r):
            t = ts(r["ingest_ts"], fmt)
            return (t is None, -t.timestamp() if t else 0, r["source_object"], r["source_row"])
        ranked = sorted(rows, key=order)
        for i, r in enumerate(ranked, 1):
            r["rank"] = i
            del r["ingest_ts"]
        return ranked

    checks = {}

    # L02 – dòng curated
    l02 = trace(args.accepted)
    winner = l02[0]
    key = (winner["source_object"], winner["source_row"])
    row = curated.get(key)
    f = winner["fields"]
    ev, ing = ts(f["event_time"], fmt), ts(f["ingest_time"], fmt)
    expected = {
        "temperature_c": str(to_celsius(f["reading"], norm(f["unit"]))),
        "sensor_id": norm(f["sensor_id"]),
        "site": sites.get(norm(f["sensor_id"])),
        "event_time_utc": ev.isoformat(), "ingest_time_utc": ing.isoformat(),
        "is_late": (ing - ev).total_seconds() > late_s,
        "source_sha256": trusted[key[0]],
    }
    observed = None if row is None else {
        "temperature_c": str(row["temperature_c"]), "sensor_id": row["sensor_id"], "site": row["site"],
        "event_time_utc": row["event_time_utc"].isoformat(), "ingest_time_utc": row["ingest_time_utc"].isoformat(),
        "is_late": row["is_late"], "source_sha256": row["source_sha256"],
    }
    checks["L02"] = {
        "record_id": args.accepted,
        "versions": l02,
        "selected_version": [key[0], key[1]],
        "rules": [
            "dedup: ingest_time DESC, source_object ASC, source_row ASC → rank 1 là winner",
            "chuẩn hóa: trim + upper cho record_id, sensor_id, unit",
            f"đơn vị: C giữ nguyên, F → (F − 32) × 5/9; làm tròn HALF_UP 2 chữ số, DECIMAL(8,2)",
            f"is_late = ingest − event > {late_s} s; site lấy từ sensors.csv",
        ],
        "curated_row_expected": expected,
        "curated_row_observed": observed,
        "others_superseded": all(r["status"]["output"] == "duplicates" and
                                 r["status"]["winner"] == [key[0], key[1]] for r in l02[1:]),
    }
    checks["L02"]["status"] = "PASS" if (observed == expected and winner["status"]["output"] == "curated"
                                         and checks["L02"]["others_superseded"]) else "FAIL"

    # L03 – dòng quarantine
    l03 = trace(args.quarantined)
    qwin = l03[0]
    missing = [k for k in REQUIRED if norm(qwin["fields"].get(k)) is None]
    checks["L03"] = {
        "record_id": args.quarantined,
        "versions": l03,
        "selected_version": [qwin["source_object"], qwin["source_row"]],
        "recomputed": {"missing_required_fields": missing},
        "rules": [
            "winner được chọn TRƯỚC khi validate; winner lỗi → quarantine (stage WINNER)",
            "không fallback: các bản cũ hơn vẫn là SUPERSEDED trong duplicates.csv",
            "primary_reason theo thứ tự REQUIRED, NUMERIC, UNIT, RANGE, TIME_PARSE, TIME_ORDER, REFERENCE",
        ],
    }
    st = qwin["status"]
    ok = (st["output"] == "quarantine" and st.get("stage") == "WINNER"
          and (st["primary_reason"] != "REQUIRED" or missing)
          and all(r["status"]["output"] == "duplicates" for r in l03[1:]))
    checks["L03"]["status"] = "PASS" if ok else "FAIL"

    report = {"artifacts": str(art), "trusted_manifest_sha256":
              hashlib.sha256(Path(args.manifest).read_bytes()).hexdigest(), **checks,
              "status": "PASS" if all(c["status"] == "PASS" for c in checks.values()) else "FAIL"}
    Path(args.out).write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n",
                              encoding="utf-8")
    for k, c in checks.items():
        print(f"{k} {c['record_id']}: {c['status']}  selected={c['selected_version']}")
    print("TRACE:", report["status"])
    raise SystemExit(0 if report["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
