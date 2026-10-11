#!/usr/bin/env python3
"""Task 3 - chạy curate.sql và xuất artifact vào thư mục theo run_id.

Đầu ra (không ghi đè; run_id đã tồn tại thì dừng):
  <out-root>/<run_id>/candidate/curated.parquet
  <out-root>/<run_id>/quarantine.csv
  <out-root>/<run_id>/duplicates.csv
  <out-root>/<run_id>/artifact-hashes.json   (sha256 từng tệp)
  <out-root>/<run_id>/run-manifest.json      (lineage đầu vào + số đếm)

Mọi tham số nghiệp vụ nằm trong contract.json / curation_decisions.json;
runner chỉ kiểm tra tính nhất quán và thay placeholder trong curate.sql.
"""

import argparse
import csv
import hashlib
import json
import re
import sys
import tempfile
from pathlib import Path

import duckdb

RUN_ID_RE = re.compile(r"^[a-zA-Z0-9_-]+$")
OUTPUT_TYPE_RE = re.compile(r"^DECIMAL\(\d+,\s*\d+\)$")
KNOWN_SOURCES = {"observations_a.csv", "observations_b.jsonl"}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def quote(path) -> str:
    """Escape một đường dẫn để nhúng vào literal SQL '...'."""
    return str(path).replace("'", "''")


def ts_format_to_strptime(fmt: str) -> str:
    """'YYYY-MM-DDTHH:MM:SSZ' -> '%Y-%m-%dT%H:%M:%SZ' (MM đầu = tháng, MM sau HH = phút)."""
    out = fmt
    for token, code in (("YYYY", "%Y"), ("DD", "%d"), ("HH", "%H"), ("SS", "%S")):
        out = out.replace(token, code, 1)
    out = out.replace("MM", "%m", 1)   # tháng (xuất hiện trước)
    out = out.replace("MM", "%M", 1)   # phút (sau HH)
    if re.search(r"YYYY|DD|HH|SS|MM", out):
        raise SystemExit(f"timestamp_format không hỗ trợ: {fmt}")
    return out


def load_params(contract_path: Path, decisions_path: Path):
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    decisions = json.loads(decisions_path.read_text(encoding="utf-8"))

    output_type = contract["temperature_validation"]["output_type"].replace(" ", "")
    if not OUTPUT_TYPE_RE.match(output_type):
        raise SystemExit(f"output_type không hợp lệ: {output_type}")

    rounding = decisions["temperature_rounding"]
    if rounding["mode"] != "ROUND_HALF_UP":
        raise SystemExit(f"Chỉ hỗ trợ ROUND_HALF_UP, nhận: {rounding['mode']}")
    scale = int(output_type.split(",")[1].rstrip(")"))
    if scale != rounding["decimal_places"]:
        raise SystemExit(
            f"output_type scale ({scale}) != decimal_places ({rounding['decimal_places']})"
        )

    if contract["deduplication"]["order"] != [
        "ingest_time DESC", "source_object ASC", "source_row ASC"
    ]:
        raise SystemExit("deduplication.order trong contract khác thứ tự mà curate.sql cài đặt")

    return contract, output_type, ts_format_to_strptime(contract["timestamp_format"])


def check_registry(sensors_path: Path):
    with sensors_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        cols = reader.fieldnames or []
        if "sensor_id" not in cols or "site" not in cols:
            raise SystemExit(f"sensors.csv cần cột sensor_id, site; hiện có: {cols}")
        seen = set()
        for row in reader:
            sid = (row["sensor_id"] or "").strip().upper()
            if not sid:
                continue
            if sid in seen:
                raise SystemExit(f"sensors.csv trùng sensor_id sau chuẩn hóa: {sid}")
            seen.add(sid)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--contract", default="/work/contract.json")
    ap.add_argument("--decisions", default="/work/curation_decisions.json")
    ap.add_argument("--sql", default="/work/curate.sql")
    ap.add_argument("--envelopes", default="/work/envelopes.jsonl")
    ap.add_argument("--sensors", default="/work/staged/sensors.csv")
    ap.add_argument("--stage-report", default="/work/stage-report.json")
    ap.add_argument("--out-root", default="/work/curate")
    ap.add_argument(
        "--reverse-input", action="store_true",
        help="Đảo thứ tự dòng envelope (kiểm tra tính tất định C02)",
    )
    args = ap.parse_args()

    if not RUN_ID_RE.match(args.run_id):
        raise SystemExit("run_id chỉ gồm chữ, số, '-' hoặc '_'")

    run_dir = Path(args.out_root) / args.run_id
    if run_dir.exists():
        raise SystemExit(f"Thư mục run đã tồn tại: {run_dir}")

    contract_p, decisions_p = Path(args.contract), Path(args.decisions)
    envelopes_p, sensors_p = Path(args.envelopes), Path(args.sensors)
    stage_p, sql_p = Path(args.stage_report), Path(args.sql)

    contract, output_type, strp = load_params(contract_p, decisions_p)
    check_registry(sensors_p)

    # Kiểm tra source_object lạ + có sha256 trong stage-report
    stage = json.loads(stage_p.read_text(encoding="utf-8"))
    sha_by_obj = {
        o["key"]: o["actual_sha256"].lower()
        for o in stage["objects"] if o.get("status") == "PASS"
    }
    objs_in_env = set()
    with envelopes_p.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                objs_in_env.add(json.loads(line)["source_object"])
    unknown = objs_in_env - KNOWN_SOURCES
    if unknown:
        raise SystemExit(f"source_object chưa có mapping: {sorted(unknown)}")
    missing_sha = objs_in_env - set(sha_by_obj)
    if missing_sha:
        raise SystemExit(f"Thiếu sha256 PASS trong stage-report cho: {sorted(missing_sha)}")

    if "{{" in re.sub(r"\{\{[A-Z_]+\}\}", "", sql_p.read_text(encoding="utf-8")):
        raise SystemExit("curate.sql có cú pháp {{ không phải placeholder")
    run_dir.mkdir(parents=True)
    (run_dir / "candidate").mkdir()

    tmp = None
    try:
        env_for_sql = envelopes_p
        if args.reverse_input:
            tmp = tempfile.NamedTemporaryFile(
                "w", suffix=".jsonl", delete=False, encoding="utf-8"
            )
            lines = envelopes_p.read_text(encoding="utf-8").splitlines()
            tmp.write("\n".join(reversed(lines)) + "\n")
            tmp.close()
            env_for_sql = Path(tmp.name)

        sql = sql_p.read_text(encoding="utf-8")
        for key, val in {
            "{{CONTRACT_PATH}}": quote(contract_p),
            "{{DECISIONS_PATH}}": quote(decisions_p),
            "{{ENVELOPES_PATH}}": quote(env_for_sql),
            "{{SENSORS_PATH}}": quote(sensors_p),
            "{{STAGE_REPORT_PATH}}": quote(stage_p),
            "{{TS_FORMAT}}": strp,
            "{{OUTPUT_TYPE}}": output_type,
        }.items():
            sql = sql.replace(key, val)
        if "{{" in sql:
            raise SystemExit("curate.sql còn placeholder chưa thay")

        con = duckdb.connect()
        con.execute("SET threads = 1")  # xuất file tất định
        con.execute(sql)

        curated_p = run_dir / "candidate" / "curated.parquet"
        quarantine_p = run_dir / "quarantine.csv"
        duplicates_p = run_dir / "duplicates.csv"

        con.execute(
            f"COPY (SELECT * FROM curated ORDER BY record_id) "
            f"TO '{quote(curated_p)}' (FORMAT parquet)"
        )
        con.execute(
            f"COPY (SELECT record_id, source_object, source_row, source_sha256, "
            f"stage, primary_reason, reasons FROM quarantine "
            f"ORDER BY source_object, source_row) "
            f"TO '{quote(quarantine_p)}' (FORMAT csv, HEADER)"
        )
        con.execute(
            f"COPY (SELECT record_id, source_object, source_row, source_sha256, reason, "
            f"winner_source_object, winner_source_row, winner_source_sha256 FROM duplicates "
            f"ORDER BY source_object, source_row) "
            f"TO '{quote(duplicates_p)}' (FORMAT csv, HEADER)"
        )

        cols = [d[0] for d in con.execute("SELECT * FROM curation_summary").description]
        summary = dict(zip(cols, con.execute("SELECT * FROM curation_summary").fetchone()))
        by_reason = dict(con.execute(
            "SELECT primary_reason, count(*) FROM quarantine GROUP BY 1 ORDER BY 1"
        ).fetchall())
        late = con.execute(
            "SELECT count(*) FILTER (WHERE is_late) FROM curated"
        ).fetchone()[0]
        duckdb_version = duckdb.__version__
        con.close()
    finally:
        if tmp is not None:
            Path(tmp.name).unlink(missing_ok=True)

    hashes = {}
    for p in (curated_p, quarantine_p, duplicates_p):
        hashes[str(p.relative_to(run_dir))] = {
            "sha256": sha256_file(p),
            "bytes": p.stat().st_size,
        }
    (run_dir / "artifact-hashes.json").write_text(
        json.dumps(hashes, indent=2) + "\n", encoding="utf-8"
    )

    manifest = {
        "run_id": args.run_id,
        "schema_version": contract["schema_version"],
        "as_of": contract["as_of"],
        "duckdb_version": duckdb_version,
        "reverse_input": args.reverse_input,
        "inputs": {
            "contract_sha256": sha256_file(contract_p),
            "curation_decisions_sha256": sha256_file(decisions_p),
            "curate_sql_sha256": sha256_file(sql_p),
            "envelopes_sha256": sha256_file(envelopes_p),
            "sensors_sha256": sha256_file(sensors_p),
            "source_objects": sha_by_obj,
        },
        "counts": summary,
        "quarantine_by_primary_reason": by_reason,
        "curated_late_rows": late,
        "artifacts": hashes,
    }
    (run_dir / "run-manifest.json").write_text(
        json.dumps(manifest, indent=2, default=str) + "\n", encoding="utf-8"
    )

    print(json.dumps({"run_id": args.run_id, "counts": summary,
                      "quarantine_by_primary_reason": by_reason}, indent=2, default=str))
    conserved = (
        summary["curated"] + summary["quarantine_total"] + summary["duplicates"]
        == summary["raw_total"]
    )
    print("CONSERVATION:", "PASS" if conserved else "FAIL")
    return 0 if conserved else 1


if __name__ == "__main__":
    sys.exit(main())
