import json
import duckdb
from pathlib import Path

SQL_PATH = "/work/quality.sql"
OUTPUT_PATH = "/work/quality_before.json"

con = duckdb.connect()
con.execute(Path(SQL_PATH).read_text())

population = con.execute("""
SELECT
    (SELECT count(*) FROM canonical_raw) AS raw_total,
    (SELECT count(*) FROM prekey_classified WHERE prekey_status = 'PARSE') AS parse_failures,
    (SELECT count(*) FROM prekey_classified WHERE prekey_status = 'KEY') AS key_excluded,
    (SELECT count(*) FROM prekey_classified WHERE prekey_status = 'INGEST_PARSE') AS ingest_parse_failures,
    (SELECT count(*) FROM key_eligible) AS key_eligible,
    (SELECT count(*) FROM ranked WHERE rn > 1) AS duplicates,
    (SELECT count(*) FROM winners) AS winners
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
FROM quality_before_metrics
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
    "phase": "before_curation",
    "population_summary": {
        "raw_total": population[0],
        "parse_failures": population[1],
        "key_excluded": population[2],
        "ingest_parse_failures": population[3],
        "key_eligible": population[4],
        "duplicates": population[5],
        "winners_W": population[6]
    },
    "metrics": metrics
}

Path(OUTPUT_PATH).write_text(
    json.dumps(report, indent=2, default=float) + "\n",
    encoding="utf-8"
)

print("Generated:", OUTPUT_PATH)
print("Metrics:", len(metrics))
print("W:", population[6])
