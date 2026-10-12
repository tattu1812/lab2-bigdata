#!/usr/bin/env python3
"""Task 5 - kiểm tra chéo độ phủ (/100) và độ khớp (<= 0.05 °C) của Task 2B.

Truy vấn viết riêng, khác quality_after.sql ở hai điểm cố ý:
  - so sánh bằng DECIMAL(9,2) thay vì DOUBLE (tránh sai số nhị phân sát 0.05);
  - dùng INNER JOIN để đếm phủ, rồi anti-join để liệt kê id QA bị thiếu.

Dùng: python3 crosscheck_qa.py --candidate <curated.parquet> --qa <qa_reference.csv>
                               --quality-after <quality_after.json> --tolerance 0.05 --out <json>
"""

import argparse
import json
import sys
from pathlib import Path

import duckdb


def q(p):
    return str(p).replace("'", "''")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--qa", required=True)
    ap.add_argument("--quality-after", required=True)
    ap.add_argument("--tolerance", default="0.05")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    con = duckdb.connect()
    con.execute(f"""
        CREATE VIEW qa AS
        SELECT trim(record_id) AS record_id, CAST(trim(reference_c) AS DECIMAL(9,2)) AS ref
        FROM read_csv('{q(args.qa)}', header=true, all_varchar=true);
        CREATE VIEW cand AS
        SELECT record_id, CAST(temperature_c AS DECIMAL(9,2)) AS temp
        FROM read_parquet('{q(args.candidate)}');
    """)
    tol = args.tolerance
    total, covered, agreed, max_diff = con.execute(f"""
        SELECT
          (SELECT count(*) FROM qa),
          count(*) FILTER (WHERE cand.temp IS NOT NULL),
          count(*) FILTER (WHERE abs(cand.temp - qa.ref) <= CAST('{tol}' AS DECIMAL(9,2))),
          max(abs(cand.temp - qa.ref))
        FROM qa JOIN cand USING (record_id)
    """).fetchone()
    missing = [r[0] for r in con.execute(
        "SELECT record_id FROM qa ANTI JOIN cand USING (record_id) ORDER BY 1").fetchall()]
    disagree = [
        {"record_id": r[0], "temperature_c": str(r[1]), "reference_c": str(r[2]), "abs_diff": str(r[3])}
        for r in con.execute(f"""
            SELECT record_id, cand.temp, qa.ref, abs(cand.temp - qa.ref)
            FROM qa JOIN cand USING (record_id)
            WHERE abs(cand.temp - qa.ref) > CAST('{tol}' AS DECIMAL(9,2)) ORDER BY 1
        """).fetchall()
    ]
    boundary = con.execute(f"""
        SELECT count(*) FROM qa JOIN cand USING (record_id)
        WHERE abs(cand.temp - qa.ref) = CAST('{tol}' AS DECIMAL(9,2))
    """).fetchone()[0]
    con.close()

    after = {m["rule_id"]: m for m in json.loads(Path(args.quality_after).read_text(encoding="utf-8"))["metrics"]}
    mine = {
        "qa_coverage": {"numerator": covered, "denominator": total},
        "qa_agreement": {"numerator": agreed, "denominator": covered},
    }
    comparison = {}
    for rule, m in mine.items():
        theirs = after[rule]
        same = (m["numerator"], m["denominator"]) == (theirs["numerator"], theirs["denominator"])
        comparison[rule] = {"crosscheck": f"{m['numerator']}/{m['denominator']}",
                            "quality_after": f"{theirs['numerator']}/{theirs['denominator']}",
                            "match": same}
    report = {
        "check_id": "QA_CROSSCHECK",
        "tolerance_c": tol,
        "qa_total": total, "qa_covered": covered, "qa_agreed": agreed,
        "max_abs_diff": str(max_diff),
        "pairs_exactly_at_tolerance": boundary,
        "missing_qa_ids": missing,
        "disagreeing": disagree,
        "comparison_with_quality_after": comparison,
        "status": "PASS" if all(c["match"] for c in comparison.values()) else "FAIL",
    }
    Path(args.out).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for rule, c in comparison.items():
        print(f"{rule:<13} crosscheck={c['crosscheck']} quality_after={c['quality_after']} match={c['match']}")
    print(f"QA CROSSCHECK: {report['status']}")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
