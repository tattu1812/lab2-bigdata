#!/usr/bin/env python3
"""Kiểm tra chéo của Trung Nguyễn (vai B) trên C01 (bảo toàn) và tính duy nhất của Khánh (vai C).

Truy vấn riêng, không dùng test_curate.py: lấy tập khóa vật lý (source_object, source_row)
từ envelope của Task 1 rồi so với hợp của 3 output bằng anti-join hai chiều, đếm chồng lấn
từng cặp, đếm trùng trong từng output và record_id trùng trong curated.

Chạy trong Pod curate (cần DuckDB):
  python3 c01_crosscheck.py --envelopes /work/envelopes.jsonl --artifacts <outputs/curate/RUN> --out c01-crosscheck.json
"""

import argparse
import json
from pathlib import Path

SQL = """
CREATE TEMP TABLE raw AS
  SELECT source_object, source_row FROM read_json('{env}', format='newline_delimited',
         columns={{source_object: 'VARCHAR', source_row: 'BIGINT'}});
CREATE TEMP TABLE cur AS SELECT * FROM read_parquet('{art}/candidate/curated.parquet');
CREATE TEMP TABLE q   AS SELECT * FROM read_csv('{art}/quarantine.csv', header=true, all_varchar=true);
CREATE TEMP TABLE d   AS SELECT * FROM read_csv('{art}/duplicates.csv', header=true, all_varchar=true);
CREATE TEMP TABLE outs AS
  SELECT source_object, source_row, 'curated' AS k FROM cur
  UNION ALL SELECT source_object, CAST(source_row AS BIGINT), 'quarantine' FROM q
  UNION ALL SELECT source_object, CAST(source_row AS BIGINT), 'duplicates' FROM d;
"""

QUERIES = {
    "raw_total": "SELECT count(*) FROM raw",
    "raw_distinct_physical_keys": "SELECT count(DISTINCT (source_object, source_row)) FROM raw",
    "curated_total": "SELECT count(*) FROM cur",
    "quarantine_total": "SELECT count(*) FROM q",
    "duplicates_total": "SELECT count(*) FROM d",
    "missing_from_outputs": "SELECT count(*) FROM raw ANTI JOIN outs USING (source_object, source_row)",
    "extra_in_outputs": "SELECT count(*) FROM (SELECT DISTINCT source_object, source_row FROM outs) o "
                        "ANTI JOIN raw USING (source_object, source_row)",
    "keys_in_more_than_one_place": "SELECT count(*) FROM (SELECT source_object, source_row FROM outs "
                                   "GROUP BY ALL HAVING count(*) > 1)",
    "curated_vs_quarantine": "SELECT count(*) FROM (SELECT source_object, source_row FROM outs WHERE k='curated' "
                             "INTERSECT SELECT source_object, source_row FROM outs WHERE k='quarantine')",
    "curated_vs_duplicates": "SELECT count(*) FROM (SELECT source_object, source_row FROM outs WHERE k='curated' "
                             "INTERSECT SELECT source_object, source_row FROM outs WHERE k='duplicates')",
    "quarantine_vs_duplicates": "SELECT count(*) FROM (SELECT source_object, source_row FROM outs WHERE k='quarantine' "
                                "INTERSECT SELECT source_object, source_row FROM outs WHERE k='duplicates')",
    "curated_distinct_record_ids": "SELECT count(DISTINCT record_id) FROM cur",
    "curated_null_record_ids": "SELECT count(*) FROM cur WHERE record_id IS NULL",
}

EXPECT = {"raw_total": 10205, "raw_distinct_physical_keys": 10205, "missing_from_outputs": 0,
          "extra_in_outputs": 0, "keys_in_more_than_one_place": 0, "curated_vs_quarantine": 0,
          "curated_vs_duplicates": 0, "quarantine_vs_duplicates": 0, "curated_null_record_ids": 0}


def main():
    ap = argparse.ArgumentParser()
    for a in ("--envelopes", "--artifacts", "--out"):
        ap.add_argument(a, required=True)
    args = ap.parse_args()
    import duckdb
    con = duckdb.connect()
    con.execute(SQL.format(env=args.envelopes, art=args.artifacts))
    obs = {k: con.execute(v).fetchone()[0] for k, v in QUERIES.items()}
    checks = {k: ("PASS" if obs[k] == v else "FAIL") for k, v in EXPECT.items()}
    checks["conservation_sum"] = ("PASS" if obs["curated_total"] + obs["quarantine_total"] + obs["duplicates_total"]
                                  == obs["raw_total"] else "FAIL")
    checks["curated_record_id_unique"] = "PASS" if obs["curated_distinct_record_ids"] == obs["curated_total"] else "FAIL"
    out = {"cross_check": "B (Trung Nguyễn) → C (Khánh): tính lại C01 + duy nhất record_id bằng truy vấn riêng",
           "artifacts": args.artifacts, "duckdb": duckdb.__version__,
           "prediction": "10205 = 9610 + 395 + 200; mất 0, thừa 0, chồng lấn 0; 9610 record_id khác nhau.",
           "observed": obs, "checks": checks,
           "status": "PASS" if all(v == "PASS" for v in checks.values()) else "FAIL"}
    Path(args.out).write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for k, v in obs.items():
        print(f"{k:32} {v}")
    print("C01 CROSSCHECK:", out["status"])
    raise SystemExit(0 if out["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
