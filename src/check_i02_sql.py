import json
from pathlib import Path
import duckdb

input_file = "/work/envelopes.jsonl"
output_file = "/work/i02-sql-check.json"

con = duckdb.connect()

con.execute("""
    CREATE VIEW raw_envelopes AS
    SELECT
        source_object,
        source_row,
        parse_status
    FROM read_json(
        '/work/envelopes.jsonl',
        format = 'newline_delimited',
        columns = {
            'source_object': 'VARCHAR',
            'source_row': 'BIGINT',
            'parse_status': 'VARCHAR'
        }
    )
""")

source_counts = con.execute("""
    SELECT source_object, COUNT(*) AS row_count
    FROM raw_envelopes
    GROUP BY 1
    ORDER BY 1
""").fetchall()

total = con.execute("""
    SELECT COUNT(*) FROM raw_envelopes
""").fetchone()[0]

duplicates = con.execute("""
    SELECT COUNT(*)
    FROM (
        SELECT source_object, source_row
        FROM raw_envelopes
        GROUP BY source_object, source_row
        HAVING COUNT(*) > 1
    )
""").fetchone()[0]

parse_errors = con.execute("""
    SELECT COUNT(*)
    FROM raw_envelopes
    WHERE parse_status = 'PARSE_ERROR'
""").fetchone()[0]

counts = dict(source_counts)

passed = (
    total == 10205
    and counts.get("observations_a.csv") == 5000
    and counts.get("observations_b.jsonl") == 5205
    and duplicates == 0
    and parse_errors == 5
)

report = {
    "test_id": "I02_SQL",
    "engine": "DuckDB",
    "duckdb_version": duckdb.__version__,
    "input_file": input_file,
    "total_envelopes": total,
    "source_counts": counts,
    "duplicate_physical_keys": duplicates,
    "jsonl_parse_errors": parse_errors,
    "status": "PASS" if passed else "FAIL"
}

Path(output_file).write_text(
    json.dumps(report, indent=2) + "\n",
    encoding="utf-8"
)

print(json.dumps(report, indent=2))

if not passed:
    raise SystemExit(1)
