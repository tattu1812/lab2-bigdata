#!/usr/bin/env python3
"""Dựng fixture nhỏ cho 4 ca biên của Task 3 (C04).

Kết quả mong đợi (expected.json) được khai báo THỦ CÔNG tại đây, không lấy từ
curate.sql, để test độc lập với phần cài đặt.

  EC1  winner mới nhất không hợp lệ -> quarantine, KHÔNG fallback bản cũ;
       bản prekey-lỗi không tham gia dedup (bản cũ hợp lệ thành winner)
  EC2  hòa ingest_time -> source_object ASC rồi source_row ASC
  EC3  biên đơn vị/khoảng nhiệt độ, làm tròn HALF_UP, chuẩn hóa trim/upper
  EC4  ngưỡng late 900s, as_of, TIME_PARSE/TIME_ORDER, đa lý do, prekey precedence

Chạy:  python3 src/build_edge_fixtures.py [--out tests/fixtures/edge]
"""

import argparse
import hashlib
import json
from pathlib import Path

A, B = "observations_a.csv", "observations_b.jsonl"
EV = "2026-02-01T10:00:00Z"
ING = "2026-02-01T10:05:00Z"
LEAK = "leak@example.com"  # phải KHÔNG xuất hiện ở bất kỳ artifact nào

rows = []        # danh sách hàng theo thứ tự khai báo
counters = {A: 0, B: 0}
labels = {}      # label -> (source_object, source_row)


def add(label, src, rid, sensor="S01", ev=EV, ing=ING, reading="20.0", unit="C",
        expect=None, parse_error=False, numeric=False):
    counters[src] += 1
    key = (src, counters[src])
    labels[label] = key
    rows.append(dict(label=label, src=src, row=key[1], rid=rid, sensor=sensor, ev=ev,
                     ing=ing, reading=reading, unit=unit, expect=expect or {},
                     parse_error=parse_error, numeric=numeric))


def cur(temp, site="LAB-A", late=False):
    return {"kind": "curated", "temperature_c": temp, "site": site, "is_late": late}


def quar(stage, primary, reasons):
    return {"kind": "quarantine", "stage": stage, "primary": primary, "reasons": reasons}


def dup(winner_label):
    return {"kind": "duplicate", "winner": winner_label}


# ---- EC1: không fallback + prekey không tham gia dedup -------------------
add("r1_old", A, "R000001", ing="2026-02-01T10:05:00Z", reading="20.0", expect=dup("r1_new"))
add("r1_new", B, "R000001", ing="2026-02-01T10:10:00Z", reading="20.5", unit="K",
    expect=quar("WINNER", "UNIT", "UNIT"))
add("r2_old", A, "R000002", ing="2026-02-01T10:05:00Z", reading="abc", expect=dup("r2_new"))
add("r2_new", B, "R000002", ing="2026-02-01T10:10:00Z", reading="19.5",
    expect=cur("19.50"))
add("r25_good", A, "R000025", ing="2026-02-01T10:05:00Z", reading="18", expect=cur("18.00"))
add("r25_bad", B, "R000025", ing="garbage", reading="99",
    expect=quar("PREKEY", "INGEST_PARSE", "INGEST_PARSE"))

# ---- EC2: tie-break ------------------------------------------------------
add("r3_a", A, "R000003", reading="21.0", expect=cur("21.00"))
add("r3_b", B, "R000003", reading="22.0", expect=dup("r3_a"))       # a.csv < b.jsonl
add("r4_a1", A, "R000004", reading="21.0", expect=cur("21.00"))
add("r4_a2", A, "R000004", reading="22.0", expect=dup("r4_a1"))     # row nhỏ hơn thắng

# ---- EC3: đơn vị / khoảng / làm tròn / chuẩn hóa -------------------------
add("r5", A, "R000005", reading="140", unit="F", expect=cur("60.00"))      # biên trên
add("r6", A, "R000006", reading="-22", unit="F", expect=cur("-30.00"))     # biên dưới
add("r7", A, "R000007", reading="60.004", expect=quar("WINNER", "RANGE", "RANGE"))
add("r8", A, "R000008", reading="-30.001", expect=quar("WINNER", "RANGE", "RANGE"))
add("r9", A, "R000009", reading="140.01", unit="F", expect=quar("WINNER", "RANGE", "RANGE"))
add("r10", A, "R000010", reading="32.009", unit="F", expect=cur("0.01"))   # hòa +0.005
add("r11", A, "R000011", reading="31.991", unit="F", expect=cur("-0.01"))  # hòa -0.005
add("r12", A, "R000012", reading="21.125", expect=cur("21.13"))
add("r13", B, "R000013", reading=2.675, numeric=True, expect=cur("2.68"))  # JSON số
add("r14", A, " r000014 ", sensor=" s01 ", reading=" 68 ", unit=" f ", expect=cur("20.00"))
add("r15", A, "R000015", reading="NaN", expect=quar("WINNER", "NUMERIC", "NUMERIC"))
add("r16", A, "R000016", reading="inf", expect=quar("WINNER", "NUMERIC", "NUMERIC"))
add("r26", A, "R000026", sensor="S02", reading="25", expect=cur("25.00", site="LAB-B"))

# ---- EC4: thời gian / late / đa lý do / prekey precedence ----------------
add("r17", A, "R000017", ev="2026-02-01T10:00:00Z", ing="2026-02-01T10:15:00Z",
    expect=cur("20.00", late=False))                                       # đúng 900s
add("r18", A, "R000018", ev="2026-02-01T10:00:00Z", ing="2026-02-01T10:15:01Z",
    expect=cur("20.00", late=True))                                        # 901s, vẫn giữ
add("r19", A, "R000019", ev="2026-02-08T23:00:00Z", ing="2026-02-09T00:00:00Z",
    expect=cur("20.00", late=True))                                        # ingest == as_of
add("r20", A, "R000020", ev=EV, ing="2026-02-09T00:00:01Z",
    expect=quar("WINNER", "TIME_ORDER", "TIME_ORDER"))
add("r21", A, "R000021", ev="2026-02-01T10:10:00Z", ing="2026-02-01T10:05:00Z",
    expect=quar("WINNER", "TIME_ORDER", "TIME_ORDER"))
add("r22", A, "R000022", ev="not-a-time", expect=quar("WINNER", "TIME_PARSE", "TIME_PARSE"))
add("r23", A, "R000023", sensor="S99", unit="K",
    expect=quar("WINNER", "UNIT", "UNIT|REFERENCE"))
add("r24", A, "R000024", sensor="", expect=quar("WINNER", "REQUIRED", "REQUIRED"))
add("r27", A, "R000027", ev="", reading="", expect=quar("WINNER", "REQUIRED", "REQUIRED"))
add("r28", A, "R000028", sensor="S98", reading="99",
    expect=quar("WINNER", "RANGE", "RANGE|REFERENCE"))
add("p_parse", B, "", parse_error=True, expect=quar("PREKEY", "PARSE", "PARSE"))
add("p_key1", A, "X123", expect=quar("PREKEY", "KEY", "KEY"))
add("p_key2", A, "", expect=quar("PREKEY", "KEY", "KEY"))
add("p_both", A, "bad", ing="bad", expect=quar("PREKEY", "KEY", "KEY|INGEST_PARSE"))


def envelope(r):
    if r["src"] == A:
        payload = {
            "record_id": r["rid"], "sensor_id": r["sensor"], "event_time": r["ev"],
            "ingest_time": r["ing"], "reading": str(r["reading"]), "unit": r["unit"],
            "operator_email": LEAK,
        }
        return {"source_object": A, "source_row": r["row"], "parse_status": "OK",
                "payload": payload}
    if r["parse_error"]:
        return {"source_object": B, "source_row": r["row"], "parse_status": "PARSE_ERROR",
                "payload": None, "raw_line": '{"id": "R9' + LEAK}
    payload = {
        "id": r["rid"], "sensor": r["sensor"], "timestamp": r["ev"],
        "arrived_at": r["ing"],
        "temperature": r["reading"] if r["numeric"] else str(r["reading"]),
        "temperature_unit": r["unit"], "operator": LEAK,
    }
    return {"source_object": B, "source_row": r["row"], "parse_status": "OK",
            "payload": payload, "raw_line": json.dumps(payload)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="tests/fixtures/edge")
    out = Path(ap.parse_args().out)
    out.mkdir(parents=True, exist_ok=True)

    with (out / "envelopes.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(envelope(r), ensure_ascii=False) + "\n")

    (out / "sensors.csv").write_text("sensor_id,site\nS01,LAB-A\nS02,LAB-B\n", encoding="utf-8")

    sha = {k: hashlib.sha256(f"fixture:{k}".encode()).hexdigest() for k in (A, B)}
    stage = {
        "fixture_version": "edge-cases-v1", "as_of": "2026-02-09T00:00:00Z", "status": "PASS",
        "objects": [{"key": k, "actual_sha256": v, "status": "PASS"} for k, v in sha.items()],
    }
    (out / "stage-report.json").write_text(json.dumps(stage, indent=2) + "\n", encoding="utf-8")

    expected = {"fixture": "edge-cases-v1", "raw_total": len(rows),
                "curated": {}, "quarantine": {}, "duplicates": {}, "leak_marker": LEAK}
    for r in rows:
        key = f"{r['src']}#{r['row']}"
        e = r["expect"]
        if e["kind"] == "curated":
            expected["curated"][key] = {
                "record_id": r["rid"].strip().upper(), "site": e["site"],
                "temperature_c": e["temperature_c"], "is_late": e["is_late"],
            }
        elif e["kind"] == "quarantine":
            expected["quarantine"][key] = {
                "stage": e["stage"], "primary_reason": e["primary"], "reasons": e["reasons"],
            }
        else:
            wsrc, wrow = labels[e["winner"]]
            expected["duplicates"][key] = {
                "record_id": r["rid"].strip().upper(), "reason": "SUPERSEDED",
                "winner": f"{wsrc}#{wrow}",
            }
    (out / "expected.json").write_text(
        json.dumps(expected, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"fixtures: {len(rows)} envelopes -> {out}")
    print({k: len(expected[k]) for k in ("curated", "quarantine", "duplicates")})


if __name__ == "__main__":
    main()
