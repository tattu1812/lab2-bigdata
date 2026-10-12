#!/usr/bin/env python3
"""Kiểm tra chéo của Tú (vai A) trên truy vết L02 của Hải Anh (vai D).

Không dùng envelope hay DuckDB: đọc thẳng file nguồn trong data/Lab2-datasets/input,
tự tính SHA-256, tự tìm dòng theo quy ước source_row của Task 1 (CSV: thứ tự bản ghi
không tính header; JSONL: số dòng), rồi so với evidence/task4/trace-L02-L03.json.

Dùng (từ thư mục gốc repo):  python3 individual/A-tu/l02_rerun.py
"""

import csv
import datetime as dt
import hashlib
import io
import json
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INPUT = ROOT / "data/Lab2-datasets/input"
TRACE = ROOT / "evidence/task4/trace-L02-L03.json"
OUT = Path(__file__).with_name("l02-rerun.json")
FMT = "%Y-%m-%dT%H:%M:%SZ"

PREDICTION = ("R001001 có 2 phiên bản; bản observations_b.jsonl dòng 5101 tiếp nhận muộn hơn "
              "nên thắng, temperature_c = 19.10 °C, is_late = false, site = zone-1; "
              "bản observations_a.csv dòng 1001 là SUPERSEDED.")


def raw_row(obj, row):
    data = (INPUT / obj).read_bytes()
    text = data.decode("utf-8")
    if obj.endswith(".jsonl"):
        r = json.loads(text.splitlines()[row - 1])
        return data, {"record_id": r["id"], "sensor_id": r["sensor"], "event_time": r["timestamp"],
                      "ingest_time": r["arrived_at"], "reading": r["temperature"], "unit": r["temperature_unit"]}
    rows = list(csv.DictReader(io.StringIO(text)))
    r = rows[row - 1]
    return data, {k: r[k] for k in ("record_id", "sensor_id", "event_time", "ingest_time", "reading", "unit")}


def main():
    trusted = {o["key"]: o for o in json.loads((ROOT / "data/trusted_manifest.json").read_text())["objects"]}
    sensors = {r["sensor_id"].strip().upper(): r["site"]
               for r in csv.DictReader(open(INPUT / "sensors.csv", encoding="utf-8"))}
    l02 = json.loads(TRACE.read_text(encoding="utf-8"))["L02"]
    checks = []

    def check(name, expected, observed):
        checks.append({"check": name, "expected": expected, "observed": observed,
                       "status": "PASS" if expected == observed else "FAIL"})

    for v in l02["versions"]:
        data, fields = raw_row(v["source_object"], v["source_row"])
        sha = hashlib.sha256(data).hexdigest()
        tag = f'{v["source_object"]}:{v["source_row"]}'
        check(f"{tag} sha256 = trusted manifest", trusted[v["source_object"]]["sha256"], sha)
        check(f"{tag} sha256 = trace", v["source_sha256_trusted"], sha)
        check(f"{tag} fields = trace", v["fields"], fields)

    # Tính lại winner và dòng curated từ byte nguồn
    def key(v):
        _, f = raw_row(v["source_object"], v["source_row"])
        return (-dt.datetime.strptime(f["ingest_time"], FMT).timestamp(), v["source_object"], v["source_row"])
    winner = sorted(l02["versions"], key=key)[0]
    check("winner (ingest DESC, object ASC, row ASC)", l02["selected_version"],
          [winner["source_object"], winner["source_row"]])
    _, f = raw_row(winner["source_object"], winner["source_row"])
    value = Decimal(f["reading"].strip())
    if f["unit"].strip().upper() == "F":
        value = (value - 32) * 5 / 9
    ev, ing = (dt.datetime.strptime(f[k], FMT) for k in ("event_time", "ingest_time"))
    obs = l02["curated_row_observed"]
    check("temperature_c", str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)), obs["temperature_c"])
    check("is_late", (ing - ev).total_seconds() > 900, obs["is_late"])
    check("site", sensors[f["sensor_id"].strip().upper()], obs["site"])
    check("source_sha256 trong curated", trusted[winner["source_object"]]["sha256"], obs["source_sha256"])

    report = {"cross_check": "A (Tú) → D (Hải Anh): chạy lại L02 độc lập từ byte nguồn",
              "record_id": l02["record_id"], "prediction": PREDICTION, "checks": checks,
              "status": "PASS" if all(c["status"] == "PASS" for c in checks) else "FAIL"}
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for c in checks:
        print(f'{c["status"]}  {c["check"]}')
    print("L02 RERUN:", report["status"])
    raise SystemExit(0 if report["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
