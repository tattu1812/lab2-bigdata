CREATE OR REPLACE TEMP VIEW canonical_raw AS
SELECT
    source_object,
    source_row,
    parse_status,

    CASE
        WHEN source_object = 'observations_a.csv'
            THEN trim(upper(CAST(payload.record_id AS VARCHAR)))
        WHEN source_object = 'observations_b.jsonl'
            THEN trim(upper(CAST(payload.id AS VARCHAR)))
    END AS record_id,

    CASE
        WHEN source_object = 'observations_a.csv'
            THEN trim(upper(CAST(payload.sensor_id AS VARCHAR)))
        WHEN source_object = 'observations_b.jsonl'
            THEN trim(upper(CAST(payload.sensor AS VARCHAR)))
    END AS sensor_id,
    
        CASE
        WHEN source_object = 'observations_a.csv'
            THEN CAST(payload.event_time AS VARCHAR)
        WHEN source_object = 'observations_b.jsonl'
            THEN CAST(payload.timestamp AS VARCHAR)
    END AS event_raw,

    CASE
        WHEN source_object = 'observations_a.csv'
            THEN CAST(payload.ingest_time AS VARCHAR)
        WHEN source_object = 'observations_b.jsonl'
            THEN CAST(payload.arrived_at AS VARCHAR)
    END AS ingest_raw,

    CASE
        WHEN source_object = 'observations_a.csv'
            THEN TRY_CAST(payload.event_time AS TIMESTAMP)
        WHEN source_object = 'observations_b.jsonl'
            THEN TRY_CAST(payload.timestamp AS TIMESTAMP)
    END AS event_ts,

    CASE
        WHEN source_object = 'observations_a.csv'
            THEN TRY_CAST(payload.ingest_time AS TIMESTAMP)
        WHEN source_object = 'observations_b.jsonl'
            THEN TRY_CAST(payload.arrived_at AS TIMESTAMP)
    END AS ingest_ts,

    CASE
        WHEN source_object = 'observations_a.csv'
            THEN CAST(payload.reading AS VARCHAR)
        WHEN source_object = 'observations_b.jsonl'
            THEN CAST(payload.temperature AS VARCHAR)
    END AS reading_raw,

    CASE
        WHEN source_object = 'observations_a.csv'
            THEN trim(upper(CAST(payload.unit AS VARCHAR)))
        WHEN source_object = 'observations_b.jsonl'
            THEN trim(upper(CAST(payload.temperature_unit AS VARCHAR)))
    END AS unit

FROM read_json_auto(
    '/work/envelopes.jsonl',
    format='newline_delimited'
);


CREATE OR REPLACE TEMP VIEW prekey_classified AS
SELECT *,
    CASE
        WHEN parse_status <> 'OK'
            THEN 'PARSE'

        WHEN record_id IS NULL
          OR record_id = ''
          OR NOT regexp_matches(record_id, '^R[0-9]{6}$')
            THEN 'KEY'

        WHEN ingest_ts IS NULL
            THEN 'INGEST_PARSE'

        ELSE 'ELIGIBLE'
    END AS prekey_status
FROM canonical_raw;


CREATE OR REPLACE TEMP VIEW key_eligible AS
SELECT *
FROM prekey_classified
WHERE prekey_status = 'ELIGIBLE';


CREATE OR REPLACE TEMP VIEW ranked AS
SELECT *,
    row_number() OVER (
        PARTITION BY record_id
        ORDER BY
            ingest_ts DESC,
            source_object ASC,
            source_row ASC
    ) AS rn
FROM key_eligible;


CREATE OR REPLACE TEMP VIEW winners AS
SELECT *
FROM ranked
WHERE rn = 1;


SELECT
    (SELECT count(*) FROM canonical_raw) AS raw_rows,
    (SELECT count(*) FROM key_eligible) AS key_eligible_rows,
    (SELECT count(*) FROM ranked WHERE rn > 1) AS duplicate_rows,
    (SELECT count(*) FROM winners) AS winner_rows,
    (SELECT count(DISTINCT record_id) FROM winners) AS distinct_winner_ids;

-- =========================================================
-- QUALITY BEFORE METRICS
-- Cohort W = winners before row-validity filtering
-- =========================================================

CREATE OR REPLACE MACRO ratio(n, d) AS
    CASE
        WHEN d = 0 THEN NULL
        ELSE CAST(n AS DOUBLE) / CAST(d AS DOUBLE)
    END;


CREATE OR REPLACE TEMP VIEW sensor_registry AS
SELECT DISTINCT trim(upper(sensor_id)) AS sensor_id
FROM read_csv_auto(
    '/work/staged/sensors.csv',
    header=true
);


CREATE OR REPLACE TEMP VIEW quality_before_counts AS
WITH value_check AS (
    SELECT
        *,
        TRY_CAST(reading_raw AS DOUBLE) AS reading_num,

        CASE
            WHEN unit = 'C'
                THEN TRY_CAST(reading_raw AS DOUBLE)
            WHEN unit = 'F'
                THEN (TRY_CAST(reading_raw AS DOUBLE) - 32.0) * 5.0 / 9.0
            ELSE NULL
        END AS temperature_c

    FROM winners
)

SELECT
    count(*) AS denominator,

    count(*) FILTER (
        WHERE record_id IS NOT NULL
          AND record_id <> ''
          AND sensor_id IS NOT NULL
          AND sensor_id <> ''
          AND event_raw IS NOT NULL
          AND trim(event_raw) <> ''
          AND ingest_raw IS NOT NULL
          AND trim(ingest_raw) <> ''
          AND reading_raw IS NOT NULL
          AND trim(reading_raw) <> ''
          AND unit IS NOT NULL
          AND unit <> ''
    ) AS completeness_numerator,

    count(DISTINCT record_id)
        AS uniqueness_numerator,

    count(*) FILTER (
        WHERE reading_num IS NOT NULL
          AND isfinite(reading_num)
          AND unit IN ('C', 'F')
          AND temperature_c BETWEEN -30 AND 60
    ) AS value_validity_numerator,

    count(*) FILTER (
        WHERE sensor_id IN (
            SELECT sensor_id FROM sensor_registry
        )
    ) AS referential_integrity_numerator,

    count(*) FILTER (
        WHERE event_ts IS NOT NULL
          AND ingest_ts IS NOT NULL
          AND event_ts <= ingest_ts
          AND ingest_ts <= TIMESTAMP '2026-02-09 00:00:00'
    ) AS temporal_consistency_numerator,

    count(*) FILTER (
        WHERE event_ts IS NOT NULL
          AND ingest_ts IS NOT NULL
          AND event_ts <= ingest_ts
          AND ingest_ts <= TIMESTAMP '2026-02-09 00:00:00'
          AND date_diff('second', event_ts, ingest_ts) <= 900
    ) AS timeliness_numerator

FROM value_check;


CREATE OR REPLACE TEMP VIEW quality_before_metrics AS

SELECT
    'completeness' AS rule_id,
    'research-telemetry-v1' AS dataset_version,
    'W' AS cohort,
    completeness_numerator AS numerator,
    denominator,
    ratio(completeness_numerator, denominator) AS value,
    1.0 AS threshold,
    'ERROR' AS severity,
    CASE
        WHEN denominator = 0 THEN 'NOT_EVALUATED'
        WHEN ratio(completeness_numerator, denominator) >= 1.0 THEN 'PASS'
        ELSE 'FAIL'
    END AS status
FROM quality_before_counts

UNION ALL

SELECT
    'uniqueness',
    'research-telemetry-v1',
    'W',
    uniqueness_numerator,
    denominator,
    ratio(uniqueness_numerator, denominator),
    1.0,
    'ERROR',
    CASE
        WHEN denominator = 0 THEN 'NOT_EVALUATED'
        WHEN ratio(uniqueness_numerator, denominator) >= 1.0 THEN 'PASS'
        ELSE 'FAIL'
    END
FROM quality_before_counts

UNION ALL

SELECT
    'value_validity',
    'research-telemetry-v1',
    'W',
    value_validity_numerator,
    denominator,
    ratio(value_validity_numerator, denominator),
    1.0,
    'ERROR',
    CASE
        WHEN denominator = 0 THEN 'NOT_EVALUATED'
        WHEN ratio(value_validity_numerator, denominator) >= 1.0 THEN 'PASS'
        ELSE 'FAIL'
    END
FROM quality_before_counts

UNION ALL

SELECT
    'referential_integrity',
    'research-telemetry-v1',
    'W',
    referential_integrity_numerator,
    denominator,
    ratio(referential_integrity_numerator, denominator),
    1.0,
    'ERROR',
    CASE
        WHEN denominator = 0 THEN 'NOT_EVALUATED'
        WHEN ratio(referential_integrity_numerator, denominator) >= 1.0 THEN 'PASS'
        ELSE 'FAIL'
    END
FROM quality_before_counts

UNION ALL

SELECT
    'temporal_consistency',
    'research-telemetry-v1',
    'W',
    temporal_consistency_numerator,
    denominator,
    ratio(temporal_consistency_numerator, denominator),
    1.0,
    'ERROR',
    CASE
        WHEN denominator = 0 THEN 'NOT_EVALUATED'
        WHEN ratio(temporal_consistency_numerator, denominator) >= 1.0 THEN 'PASS'
        ELSE 'FAIL'
    END
FROM quality_before_counts

UNION ALL

SELECT
    'timeliness',
    'research-telemetry-v1',
    'W',
    timeliness_numerator,
    denominator,
    ratio(timeliness_numerator, denominator),
    0.95,
    'WARN',
    CASE
        WHEN denominator = 0 THEN 'NOT_EVALUATED'
        WHEN ratio(timeliness_numerator, denominator) >= 0.95 THEN 'PASS'
        ELSE 'FAIL'
    END
FROM quality_before_counts;

-- =========================================================
-- WINNER ERROR DIAGNOSTICS
-- =========================================================

CREATE OR REPLACE TEMP VIEW winner_diagnostics AS
WITH checked AS (
    SELECT
        w.*,

        TRY_CAST(reading_raw AS DOUBLE) AS reading_num,

        CASE
            WHEN unit = 'C'
                THEN TRY_CAST(reading_raw AS DOUBLE)
            WHEN unit = 'F'
                THEN (TRY_CAST(reading_raw AS DOUBLE) - 32.0) * 5.0 / 9.0
            ELSE NULL
        END AS temperature_c,

        sensor_id IN (
            SELECT sensor_id FROM sensor_registry
        ) AS sensor_known

    FROM winners w
)

SELECT
    *,

    CASE
        WHEN sensor_id IS NULL OR sensor_id = ''
          OR event_raw IS NULL OR trim(event_raw) = ''
          OR ingest_raw IS NULL OR trim(ingest_raw) = ''
          OR reading_raw IS NULL OR trim(reading_raw) = ''
          OR unit IS NULL OR unit = ''
            THEN 'REQUIRED'

        WHEN reading_num IS NULL
          OR NOT isfinite(reading_num)
            THEN 'NUMERIC'

        WHEN unit NOT IN ('C', 'F')
            THEN 'UNIT'

        WHEN temperature_c < -30
          OR temperature_c > 60
            THEN 'RANGE'

        WHEN event_ts IS NULL
          OR ingest_ts IS NULL
            THEN 'TIME_PARSE'

        WHEN event_ts > ingest_ts
          OR ingest_ts > TIMESTAMP '2026-02-09 00:00:00'
            THEN 'TIME_ORDER'

        WHEN NOT sensor_known
            THEN 'REFERENCE'

        ELSE 'VALID'
    END AS primary_reason

FROM checked;
