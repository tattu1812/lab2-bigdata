import json
import duckdb
from pathlib import Path

SQL_PATH = "/work/quality_after.sql"
OUTPUT_PATH = "/work/quality_after.json"

con = duckdb.connect()

Path("/work/duckdb_tmp").mkdir(parents=True, exist_ok=True)

con.execute("SET threads=1")
con.execute("SET preserve_insertion_order=false")
con.execute("SET memory_limit='256MB'")
con.execute("SET temp_directory='/work/duckdb_tmp'")
con.execute(Path(SQL_PATH).read_text())

population = con.execute("""
SELECT
    curated_total,
    qa_total,
    qa_coverage_n,
    qa_agreement_n
FROM quality_after_counts
""").fetchone()

rows = con.execute("""
SELECT
    rule_id,
    dataset_version,
    cohort,
    numerator,
    denominator,
    value,
    threshold,
    severity,
    status
FROM quality_after_metrics
ORDER BY rule_id
""").fetchall()

metrics = []

for r in rows:
    metrics.append({
        "rule_id": r[0],
        "dataset_version": r[1],
        "cohort": r[2],
        "numerator": r[3],
        "denominator": r[4],
        "value": r[5],
        "threshold": r[6],
        "severity": r[7],
        "status": r[8]
    })

report = {
    "dataset_version": "research-telemetry-v1",
    "phase": "after_curation",
    "population_summary": {
        "curated_total": population[0],
        "qa_reference_total": population[1],
        "qa_covered": population[2],
        "qa_agreed": population[3]
    },
    "metrics": metrics
}

Path(OUTPUT_PATH).write_text(
    json.dumps(report, indent=2, default=float) + "\n",
    encoding="utf-8"
)

print("Generated:", OUTPUT_PATH)
print("Metrics:", len(metrics))
print("Curated:", population[0])
print("QA:", population[1])
