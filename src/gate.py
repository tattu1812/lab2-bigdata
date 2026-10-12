#!/usr/bin/env python3
"""Task 5 - release gate G01-G09.

Gate không tin bất kỳ trường "passed"/"status" nào do task trước ghi ra: mỗi
hàm tự đọc candidate, input đã stage, metadata và lineage rồi tính lại.

Bố cục <root> giống repo (catalog/run-record dùng đường dẫn tương đối repo):
  <root>/outputs/curate/<run_id>/{candidate/curated.parquet, quarantine.csv,
                                   duplicates.csv, run-manifest.json}
  <root>/catalog.json, <root>/schemas/catalog.schema.json
  <root>/evidence/task4/{lineage.jsonl, run-record.json}
  <root>/contracts/{contract.json, curation_decisions.json}
  <root>/data/trusted_manifest.json
  <root>/src/{curate.sql, run_curate.py}
  <root>/staged/{observations_a.csv, observations_b.jsonl, qa_reference.csv, sensors.csv}

Mỗi kiểm tra trả {check, category, status, observed, reasons}.
status: PASS | FAIL | BLOCKED (mọi exception đều là BLOCKED, không bao giờ PASS).
Quyết định: PASS khi đủ 9/9 PASS; có BLOCKED -> BLOCKED; còn lại -> REJECT.

Dùng: python3 gate.py --root <root> --run-id <curate_run_id> --out <report.json>
Exit: 0 PASS, 1 REJECT, 2 BLOCKED.
"""

import argparse
import csv
import datetime
import hashlib
import json
import math
import re
import sys
import traceback
from decimal import Decimal
from pathlib import Path

import duckdb

CHECKS = []


def check(check_id, category):
    def wrap(fn):
        CHECKS.append((check_id, category, fn))
        return fn
    return wrap


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def q(path) -> str:
    return str(path).replace("'", "''")


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


class Ctx:
    def __init__(self, root: Path, run_id: str):
        self.root = root
        self.run_id = run_id
        self.run_dir = root / "outputs/curate" / run_id
        self.parquet = self.run_dir / "candidate/curated.parquet"
        self.staged = root / "staged"
        self.contract = load_json(root / "contracts/contract.json")

    def con(self):
        con = duckdb.connect()
        con.execute(f"CREATE VIEW c AS SELECT * FROM read_parquet('{q(self.parquet)}')")
        return con


# ---------------------------------------------------------------------------
@check("G01", "INPUT_INTEGRITY")
def g01(ctx):
    """Bản sao input khớp trusted manifest; candidate và run-record trỏ đúng input đó."""
    reasons, observed = [], {"objects": {}}
    trusted_path = ctx.root / "data/trusted_manifest.json"
    trusted = load_json(trusted_path)
    trusted_sha = {o["key"]: o["sha256"] for o in trusted["objects"]}

    for obj in trusted["objects"]:
        p = ctx.staged / obj["key"]
        if not p.exists():
            reasons.append(f"thiếu bản sao input {obj['key']}")
            continue
        size, sha = p.stat().st_size, sha256_file(p)
        observed["objects"][obj["key"]] = {"bytes": size, "sha256": sha}
        if size != obj["bytes"]:
            reasons.append(f"{obj['key']}: bytes {size} != trusted {obj['bytes']}")
        if sha != obj["sha256"]:
            reasons.append(f"{obj['key']}: sha256 khác trusted manifest")

    rr = load_json(ctx.root / "evidence/task4/run-record.json")
    manifest_sha = sha256_file(trusted_path)
    if rr["input"]["sha256"] != manifest_sha:
        reasons.append("run-record.input.sha256 khác hash trusted_manifest.json")

    run_manifest = load_json(ctx.run_dir / "run-manifest.json")
    for key, sha in run_manifest["inputs"]["source_objects"].items():
        if trusted_sha.get(key) != sha:
            reasons.append(f"run-manifest khai báo hash {key} khác trusted manifest")

    con = ctx.con()
    pairs = con.execute(
        "SELECT source_object, source_sha256, count(*) FROM c GROUP BY 1, 2 ORDER BY 1, 2"
    ).fetchall()
    con.close()
    observed["candidate_source_hashes"] = [list(p) for p in pairs]
    for obj, sha, n in pairs:
        if trusted_sha.get(obj) != sha:
            reasons.append(f"{n} dòng candidate có source_sha256 của {obj} không khớp trusted manifest")
    return reasons, observed


EXPECTED_TYPES = {
    "record_id": "VARCHAR", "sensor_id": "VARCHAR", "site": "VARCHAR",
    "event_time_utc": "TIMESTAMP", "ingest_time_utc": "TIMESTAMP",
    "is_late": "BOOLEAN", "source_object": "VARCHAR",
    "source_row": "BIGINT", "source_sha256": "VARCHAR",
}


@check("G02", "SCHEMA")
def g02(ctx):
    """Cột, thứ tự, kiểu đúng contract; không có trường bị hạn chế."""
    reasons = []
    contract = ctx.contract
    con = ctx.con()
    schema = con.execute("SELECT column_name, column_type FROM (DESCRIBE SELECT * FROM c)").fetchall()
    con.close()
    cols, types = [c for c, _ in schema], dict(schema)
    expected = dict(EXPECTED_TYPES)
    expected["temperature_c"] = contract["temperature_validation"]["output_type"].replace(" ", "")
    if cols != contract["released_columns"]:
        reasons.append(f"cột/thứ tự khác released_columns: {cols}")
    for col, typ in expected.items():
        if types.get(col) != typ:
            reasons.append(f"{col}: kiểu {types.get(col)} != {typ}")
    leaked = [c for c in cols if c in contract["privacy"]["restricted_fields"]]
    if leaked:
        reasons.append(f"candidate chứa trường bị hạn chế: {leaked}")
    return reasons, {"columns": schema}


@check("G03", "REQUIRED")
def g03(ctx):
    """Mọi cột released đều không NULL (completeness = 1.0)."""
    cols = ctx.contract["released_columns"]
    con = ctx.con()
    n = con.execute("SELECT count(*) FROM c").fetchone()[0]
    per_col = {
        col: con.execute(f'SELECT count(*) FROM c WHERE "{col}" IS NULL').fetchone()[0]
        for col in cols
    }
    complete = con.execute(
        "SELECT count(*) FROM c WHERE " + " AND ".join(f'"{col}" IS NOT NULL' for col in cols)
    ).fetchone()[0]
    con.close()
    reasons = []
    if n == 0:
        reasons.append("candidate rỗng")
    for col, k in per_col.items():
        if k:
            reasons.append(f"{k} dòng NULL ở {col}")
    threshold = ctx.contract["release_thresholds"]["required_completeness"]
    if n and complete / n < threshold:
        reasons.append(f"completeness {complete}/{n} < {threshold}")
    return reasons, {"rows": n, "complete_rows": complete, "null_by_column": per_col}


@check("G04", "VALUE")
def g04(ctx):
    """Giá trị hợp lệ: nhiệt độ trong khoảng, record_id đúng mẫu, sensor/site khớp
    registry, thứ tự thời gian, is_late nhất quán, timeliness đạt ngưỡng."""
    c = ctx.contract
    th = c["release_thresholds"]
    rng = c["temperature_range_c"]
    con = ctx.con()
    con.execute(
        f"CREATE VIEW reg AS SELECT upper(trim(sensor_id)) AS sensor_id, trim(site) AS site "
        f"FROM read_csv('{q(ctx.staged / 'sensors.csv')}', header=true, all_varchar=true)"
    )
    as_of = datetime.datetime.strptime(c["as_of"], "%Y-%m-%dT%H:%M:%SZ")
    late = c["late_threshold_seconds"]
    n = con.execute("SELECT count(*) FROM c").fetchone()[0]

    temps = [r[0] for r in con.execute("SELECT CAST(temperature_c AS DOUBLE) FROM c").fetchall()]
    valid_temp = sum(1 for t in temps if t is not None and math.isfinite(t) and rng["min"] <= t <= rng["max"])
    pattern = re.compile(c["record_id_pattern"])
    ids = [r[0] for r in con.execute("SELECT record_id FROM c").fetchall()]
    valid_id = sum(1 for i in ids if i is not None and pattern.fullmatch(i))
    sensor_ok = con.execute(
        "SELECT count(*) FROM c JOIN reg r ON r.sensor_id = c.sensor_id AND r.site = c.site"
    ).fetchone()[0]
    chrono_ok = con.execute(
        "SELECT count(*) FROM c WHERE event_time_utc <= ingest_time_utc AND ingest_time_utc <= ?",
        [as_of],
    ).fetchone()[0]
    timely = con.execute(
        "SELECT count(*) FROM c WHERE event_time_utc <= ingest_time_utc AND ingest_time_utc <= ? "
        "AND epoch(ingest_time_utc) - epoch(event_time_utc) <= ?",
        [as_of, late],
    ).fetchone()[0]
    late_bad = con.execute(
        "SELECT count(*) FROM c WHERE is_late IS DISTINCT FROM "
        "((epoch(ingest_time_utc) - epoch(event_time_utc)) > ?)",
        [late],
    ).fetchone()[0]
    con.close()

    observed = {
        "rows": n,
        "value_validity": [valid_temp, n],
        "record_id_pattern": [valid_id, n],
        "sensor_consistency": [sensor_ok, n],
        "chronology": [chrono_ok, n],
        "timeliness": [timely, chrono_ok],
        "is_late_inconsistent": late_bad,
    }
    reasons = []
    if n == 0:
        return ["candidate rỗng"], observed
    for name, (num, den), key in (
        ("value_validity", (valid_temp, n), "value_validity"),
        ("sensor_consistency", (sensor_ok, n), "sensor_consistency"),
        ("chronology", (chrono_ok, n), "chronology"),
    ):
        if num / den < th[key]:
            reasons.append(f"{name} {num}/{den} < {th[key]}")
    if valid_id != n:
        reasons.append(f"record_id sai mẫu: {n - valid_id} dòng")
    if chrono_ok == 0 or timely / chrono_ok < th["timeliness"]:
        reasons.append(f"timeliness {timely}/{chrono_ok} < {th['timeliness']}")
    if late_bad:
        reasons.append(f"is_late không nhất quán ở {late_bad} dòng")
    return reasons, observed


@check("G05", "UNIQUENESS")
def g05(ctx):
    """Business key record_id và physical key (source_object, source_row) là duy nhất."""
    con = ctx.con()
    n, ids, phys = con.execute(
        "SELECT count(*), count(DISTINCT record_id), count(DISTINCT (source_object, source_row)) FROM c"
    ).fetchone()
    dup_ids = [r[0] for r in con.execute(
        "SELECT record_id FROM c GROUP BY 1 HAVING count(*) > 1 ORDER BY 1 LIMIT 5"
    ).fetchall()]
    con.close()
    reasons = []
    if ids != n:
        reasons.append(f"record_id trùng: {n - ids} dòng thừa (ví dụ {dup_ids})")
    if phys != n:
        reasons.append(f"khóa vật lý trùng: {n - phys} dòng thừa")
    return reasons, {"rows": n, "distinct_record_id": ids, "distinct_physical_key": phys}


def raw_physical_keys(staged: Path):
    """Tính lại khóa vật lý từ chính bản sao nguồn (không dùng envelopes của Task 1)."""
    keys = []
    with (staged / "observations_a.csv").open("r", encoding="utf-8-sig", newline="") as f:
        for i, _ in enumerate(csv.DictReader(f), start=1):
            keys.append(("observations_a.csv", i))
    with (staged / "observations_b.jsonl").open("r", encoding="utf-8-sig") as f:
        for i, _ in enumerate(f, start=1):
            keys.append(("observations_b.jsonl", i))
    return keys


@check("G06", "RECONCILIATION")
def g06(ctx):
    """raw = curated ⊔ quarantine ⊔ duplicates theo khóa vật lý; artifact khớp run-manifest."""
    raw = raw_physical_keys(ctx.staged)
    con = ctx.con()
    cur = [(o, int(r)) for o, r in con.execute("SELECT source_object, source_row FROM c").fetchall()]
    con.close()
    qua = [(r["source_object"], int(r["source_row"])) for r in read_csv(ctx.run_dir / "quarantine.csv")]
    dup = [(r["source_object"], int(r["source_row"])) for r in read_csv(ctx.run_dir / "duplicates.csv")]
    union = cur + qua + dup
    raw_set, union_set = set(raw), set(union)
    observed = {
        "raw": len(raw), "raw_distinct": len(raw_set),
        "curated": len(cur), "quarantine": len(qua), "duplicates": len(dup),
        "overlap_or_repeat": len(union) - len(union_set),
        "missing_from_outputs": len(raw_set - union_set),
        "extra_in_outputs": len(union_set - raw_set),
    }
    reasons = []
    if len(raw) != len(raw_set):
        reasons.append("khóa vật lý raw không duy nhất")
    if len(union) != len(raw):
        reasons.append(f"bảo toàn sai: {len(cur)}+{len(qua)}+{len(dup)}={len(union)} != raw {len(raw)}")
    if observed["overlap_or_repeat"]:
        reasons.append(f"{observed['overlap_or_repeat']} khóa vật lý xuất hiện nhiều lần trong output")
    if observed["missing_from_outputs"]:
        reasons.append(f"{observed['missing_from_outputs']} bản ghi raw bị mất")
    if observed["extra_in_outputs"]:
        reasons.append(f"{observed['extra_in_outputs']} bản ghi lạ trong output")

    manifest = load_json(ctx.run_dir / "run-manifest.json")
    counts = manifest["counts"]
    for name, actual in (("raw_total", len(raw)), ("curated", len(cur)),
                         ("quarantine_total", len(qua)), ("duplicates", len(dup))):
        if counts.get(name) != actual:
            reasons.append(f"run-manifest.counts.{name}={counts.get(name)} != thực tế {actual}")
    for rel, meta in manifest["artifacts"].items():
        if sha256_file(ctx.run_dir / rel) != meta["sha256"]:
            reasons.append(f"{rel} khác hash trong run-manifest")
    return reasons, observed


def FILLED(v):
    """Có giá trị thật. Chuỗi chỉ có khoảng trắng tính là thiếu (như normalization của contract)."""
    if isinstance(v, str):
        return bool(v.strip())
    return v not in (None, [], {})


@check("G07", "METADATA")
def g07(ctx):
    """Catalog đủ field (owner/steward...), khớp file thật; run-record khớp code/contract/output."""
    reasons = []
    catalog = load_json(ctx.root / "catalog.json")
    schema = load_json(ctx.root / "schemas/catalog.schema.json")
    for field in schema["required"]:
        if not FILLED(catalog.get(field)):
            reasons.append(f"catalog thiếu {field}")
    if catalog.get("run_id") != ctx.run_id:
        reasons.append(f"catalog.run_id={catalog.get('run_id')} != {ctx.run_id}")

    # Cho phép rỗng: danh sách dependencies của raw là [] hợp lệ.
    may_be_empty = {"dependencies"}
    entries = catalog.get("datasets", []) + catalog.get("artifacts", [])
    for ds in catalog.get("datasets", []):
        for field in schema["$defs"]["dataset"]["required"]:
            if field not in ds or (field not in may_be_empty and not FILLED(ds[field])):
                reasons.append(f"{ds.get('dataset_id', '?')}: thiếu {field}")
    for item in entries:
        loc = item.get("location", "")
        name = item.get("dataset_id") or item.get("artifact_id")
        if loc.startswith("s3://"):
            continue
        p = ctx.root / loc
        if not p.exists():
            reasons.append(f"{name}: không thấy {loc}")
            continue
        if p.stat().st_size != item.get("size_bytes"):
            reasons.append(f"{name}: size_bytes khác file thật")
        if sha256_file(p) != item.get("sha256"):
            reasons.append(f"{name}: sha256 khác file thật")
        if p.suffix == ".parquet":
            con = duckdb.connect()
            rows = con.execute(f"SELECT count(*) FROM read_parquet('{q(p)}')").fetchone()[0]
            cols = [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet('{q(p)}')").fetchall()]
            con.close()
        else:
            data = read_csv(p)
            rows = len(data)
            with p.open("r", encoding="utf-8", newline="") as f:
                cols = next(csv.reader(f))
        if rows != item.get("row_count"):
            reasons.append(f"{name}: row_count {item.get('row_count')} != thực tế {rows}")
        if "columns" in item and cols != item["columns"]:
            reasons.append(f"{name}: columns khác file thật")

    rr = load_json(ctx.root / "evidence/task4/run-record.json")
    if rr.get("run_id") != ctx.run_id:
        reasons.append(f"run-record.run_id={rr.get('run_id')} != {ctx.run_id}")
    if not FILLED(rr.get("reviewer")):
        reasons.append("run-record thiếu reviewer")
    for ref in (rr["code"]["sql"], rr["code"]["runner"], rr["contract"], rr["curation_decisions"], *rr["outputs"]):
        p = ctx.root / ref["path"]
        if not p.exists() or sha256_file(p) != ref["sha256"]:
            reasons.append(f"run-record: hash {ref['path']} không khớp")
    observed = {
        "catalog_run_id": catalog.get("run_id"),
        "datasets": [d.get("dataset_id") for d in catalog.get("datasets", [])],
        "stewards": {d.get("dataset_id"): d.get("steward") for d in catalog.get("datasets", [])},
        "run_record_run_id": rr.get("run_id"),
    }
    return reasons, observed


@check("G08", "LINEAGE")
def g08(ctx):
    """OpenLineage curate: START/COMPLETE cùng runId = run-record; COMPLETE có đủ 3 output, đúng rowCount."""
    reasons = []
    lines = [l for l in (ctx.root / "evidence/task4/lineage.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    events = [json.loads(l) for l in lines]
    types = [e.get("eventType") for e in events]
    if types != ["START", "COMPLETE"]:
        reasons.append(f"cần đúng START, COMPLETE; nhận {types}")
    run_ids = {e.get("run", {}).get("runId") for e in events}
    rr = load_json(ctx.root / "evidence/task4/run-record.json")
    if len(run_ids) != 1:
        reasons.append(f"các event dùng runId khác nhau: {sorted(map(str, run_ids))}")
    elif rr.get("openlineage_run_id") not in run_ids:
        reasons.append("runId lineage khác run-record.openlineage_run_id")
    for e in events:
        if ctx.run_id not in e.get("job", {}).get("name", ""):
            reasons.append(f"{e.get('eventType')}: job.name không chứa {ctx.run_id}")
        if not any(i.get("namespace") == "s3://research-raw" for i in e.get("inputs", [])):
            reasons.append(f"{e.get('eventType')}: thiếu input s3://research-raw")
    if len(events) == 2 and events[0].get("eventTime", "") > events[1].get("eventTime", ""):
        reasons.append("START xảy ra sau COMPLETE")

    complete = next((e for e in events if e.get("eventType") == "COMPLETE"), {})
    outputs = {o.get("name"): o for o in complete.get("outputs", [])}
    expected = {
        f"outputs/curate/{ctx.run_id}/candidate/curated.parquet":
            duckdb.connect().execute(f"SELECT count(*) FROM read_parquet('{q(ctx.parquet)}')").fetchone()[0],
        f"outputs/curate/{ctx.run_id}/quarantine.csv": len(read_csv(ctx.run_dir / "quarantine.csv")),
        f"outputs/curate/{ctx.run_id}/duplicates.csv": len(read_csv(ctx.run_dir / "duplicates.csv")),
    }
    for name, rows in expected.items():
        if name not in outputs:
            reasons.append(f"COMPLETE thiếu output {name}")
        elif outputs[name].get("facets", {}).get("rowCount") != rows:
            reasons.append(f"{name}: rowCount {outputs[name].get('facets', {}).get('rowCount')} != thực tế {rows}")
    extra = set(outputs) - set(expected)
    if extra:
        reasons.append(f"COMPLETE có output lạ: {sorted(extra)}")
    return reasons, {"event_types": types, "run_ids": sorted(map(str, run_ids)),
                     "complete_outputs": sorted(outputs)}


@check("G09", "COVERAGE")
def g09(ctx):
    """QA: độ phủ = id QA có trong candidate / tổng QA; độ khớp |temp - ref| <= tolerance."""
    th = ctx.contract["release_thresholds"]
    tol = Decimal(str(ctx.contract["qa_tolerance_c"]))
    qa = {r["record_id"].strip(): Decimal(r["reference_c"].strip()) for r in read_csv(ctx.staged / "qa_reference.csv")}
    con = ctx.con()
    temps = {
        rid: Decimal(t) for rid, t in con.execute(
            "SELECT record_id, CAST(temperature_c AS VARCHAR) FROM c WHERE temperature_c IS NOT NULL"
        ).fetchall()
    }
    con.close()
    covered = [rid for rid in qa if rid in temps]
    agreed = [rid for rid in covered if abs(temps[rid] - qa[rid]) <= tol]
    total = len(qa)
    observed = {
        "qa_total": total, "qa_covered": len(covered), "qa_agreed": len(agreed),
        "coverage": len(covered) / total if total else None,
        "agreement": len(agreed) / len(covered) if covered else None,
        "missing_qa_ids": sorted(set(qa) - set(covered))[:10],
    }
    reasons = []
    if total == 0:
        reasons.append("qa_reference rỗng")
    elif len(covered) / total < th["qa_coverage"]:
        reasons.append(f"qa_coverage {len(covered)}/{total} < {th['qa_coverage']}")
    if covered and len(agreed) / len(covered) < th["qa_agreement"]:
        reasons.append(f"qa_agreement {len(agreed)}/{len(covered)} < {th['qa_agreement']}")
    return reasons, observed


# ---------------------------------------------------------------------------
def run_gate(root: Path, run_id: str):
    results = []
    try:
        ctx = Ctx(root, run_id)
    except Exception as exc:  # không đọc nổi contract -> mọi kiểm tra BLOCKED
        ctx, ctx_error = None, f"{type(exc).__name__}: {exc}"
    for check_id, category, fn in CHECKS:
        try:
            if ctx is None:
                raise RuntimeError(ctx_error)
            reasons, observed = fn(ctx)
            status = "FAIL" if reasons else "PASS"
        except Exception as exc:
            reasons = [f"{type(exc).__name__}: {exc}"]
            observed = {"traceback": traceback.format_exc(limit=3)}
            status = "BLOCKED"
        results.append({"check": check_id, "category": category, "status": status,
                        "observed": observed, "reasons": reasons})

    statuses = [r["status"] for r in results]
    if any(s == "BLOCKED" for s in statuses):
        decision = "BLOCKED"
    elif all(s == "PASS" for s in statuses):
        decision = "PASS"
    else:
        decision = "REJECT"
    parquet = root / "outputs/curate" / run_id / "candidate/curated.parquet"
    return {
        "gate_version": "1.0",
        "curate_run_id": run_id,
        "evaluated_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "gate_sha256": sha256_file(Path(__file__)),
        "candidate_sha256": sha256_file(parquet) if parquet.exists() else None,
        "decision": decision,
        "passed": f"{statuses.count('PASS')}/{len(statuses)}",
        "failed_categories": [r["category"] for r in results if r["status"] != "PASS"],
        "checks": results,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    report = run_gate(Path(args.root), args.run_id)
    out = Path(args.out)
    if out.exists():
        raise SystemExit(f"Không ghi đè report đã có: {out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    for r in report["checks"]:
        print(f"{r['check']} {r['category']:<16} {r['status']}" + (f"  {r['reasons'][0]}" if r["reasons"] else ""))
    print(f"GATE: {report['decision']} ({report['passed']})")
    return {"PASS": 0, "REJECT": 1}.get(report["decision"], 2)


if __name__ == "__main__":
    sys.exit(main())
