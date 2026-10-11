CREATE OR REPLACE MACRO ratio(n, d) AS
    CASE
        WHEN d = 0 THEN NULL
        ELSE CAST(n AS DOUBLE) / CAST(d AS DOUBLE)
    END;

CREATE OR REPLACE TEMP VIEW curated_after AS
SELECT *
FROM read_parquet('/work/curated.parquet');

CREATE OR REPLACE TEMP VIEW sensor_registry_after AS
SELECT DISTINCT upper(trim(sensor_id)) AS sensor_id
FROM read_csv_auto(
    '/work/staged/sensors.csv',
    header = true
);

CREATE OR REPLACE TEMP VIEW curated_with_sensor AS
SELECT
    c.*,
    CASE
        WHEN s.sensor_id IS NOT NULL THEN 1
        ELSE 0
    END AS sensor_known
FROM curated_after c
LEFT JOIN sensor_registry_after s
    ON upper(trim(c.sensor_id)) = s.sensor_id;

CREATE OR REPLACE TEMP VIEW qa_reference_after AS
SELECT
    trim(record_id) AS record_id,
    CAST(reference_c AS DOUBLE) AS reference_c
FROM read_csv_auto(
    '/work/staged/qa_reference.csv',
    header = true
);

CREATE OR REPLACE TEMP VIEW qa_join_after AS
SELECT
    q.record_id,
    q.reference_c,
    CAST(c.temperature_c AS DOUBLE) AS temperature_c,
    CASE
        WHEN c.record_id IS NULL THEN NULL
        ELSE abs(CAST(c.temperature_c AS DOUBLE) - q.reference_c)
    END AS abs_diff
FROM qa_reference_after q
LEFT JOIN curated_after c
    ON q.record_id = c.record_id;

CREATE OR REPLACE TEMP TABLE quality_after_counts AS
SELECT
    (SELECT count(*) FROM curated_after) AS curated_total,

    (
        SELECT count(*)
        FROM curated_after
        WHERE record_id IS NOT NULL
          AND sensor_id IS NOT NULL
          AND site IS NOT NULL
          AND event_time_utc IS NOT NULL
          AND ingest_time_utc IS NOT NULL
          AND temperature_c IS NOT NULL
          AND is_late IS NOT NULL
          AND source_object IS NOT NULL
          AND source_row IS NOT NULL
          AND source_sha256 IS NOT NULL
    ) AS completeness_n,

    (
        SELECT count(DISTINCT record_id)
        FROM curated_after
    ) AS uniqueness_n,

    (
        SELECT count(*)
        FROM curated_after
        WHERE temperature_c BETWEEN -30 AND 60
    ) AS value_validity_n,

    (
        SELECT sum(sensor_known)
        FROM curated_with_sensor
    ) AS referential_integrity_n,

    (
        SELECT count(*)
        FROM curated_after
        WHERE event_time_utc <= ingest_time_utc
          AND ingest_time_utc <= TIMESTAMP '2026-02-09 00:00:00'
    ) AS temporal_consistency_n,

    (
        SELECT count(*)
        FROM curated_after
        WHERE extract(epoch FROM (ingest_time_utc - event_time_utc)) <= 900
    ) AS timeliness_n,

    (
        SELECT count(*)
        FROM qa_reference_after
    ) AS qa_total,

    (
        SELECT count(temperature_c)
        FROM qa_join_after
    ) AS qa_coverage_n,

    (
        SELECT count(*)
        FROM qa_join_after
        WHERE temperature_c IS NOT NULL
          AND abs_diff <= 0.05
    ) AS qa_agreement_n;

CREATE OR REPLACE TEMP TABLE quality_after_metrics AS

SELECT
    'completeness' AS rule_id,
    'research-telemetry-v1' AS dataset_version,
    'CURATED' AS cohort,
    completeness_n AS numerator,
    curated_total AS denominator,
    ratio(completeness_n, curated_total) AS value,
    1.0 AS threshold,
    'ERROR' AS severity,
    CASE
        WHEN curated_total = 0 THEN 'NOT_EVALUATED'
        WHEN ratio(completeness_n, curated_total) >= 1.0 THEN 'PASS'
        ELSE 'FAIL'
    END AS status
FROM quality_after_counts

UNION ALL

SELECT
    'referential_integrity',
    'research-telemetry-v1',
    'CURATED',
    referential_integrity_n,
    curated_total,
    ratio(referential_integrity_n, curated_total),
    1.0,
    'ERROR',
    CASE
        WHEN curated_total = 0 THEN 'NOT_EVALUATED'
        WHEN ratio(referential_integrity_n, curated_total) >= 1.0 THEN 'PASS'
        ELSE 'FAIL'
    END
FROM quality_after_counts

UNION ALL

SELECT
    'temporal_consistency',
    'research-telemetry-v1',
    'CURATED',
    temporal_consistency_n,
    curated_total,
    ratio(temporal_consistency_n, curated_total),
    1.0,
    'ERROR',
    CASE
        WHEN curated_total = 0 THEN 'NOT_EVALUATED'
        WHEN ratio(temporal_consistency_n, curated_total) >= 1.0 THEN 'PASS'
        ELSE 'FAIL'
    END
FROM quality_after_counts

UNION ALL

SELECT
    'timeliness',
    'research-telemetry-v1',
    'CURATED_TEMPORAL_VALID',
    timeliness_n,
    temporal_consistency_n,
    ratio(timeliness_n, temporal_consistency_n),
    0.95,
    'WARN',
    CASE
        WHEN temporal_consistency_n = 0 THEN 'NOT_EVALUATED'
        WHEN ratio(
            timeliness_n,
            temporal_consistency_n
        ) >= 0.95 THEN 'PASS'
        ELSE 'FAIL'
    END
FROM quality_after_counts

UNION ALL

SELECT
    'uniqueness',
    'research-telemetry-v1',
    'CURATED',
    uniqueness_n,
    curated_total,
    ratio(uniqueness_n, curated_total),
    1.0,
    'ERROR',
    CASE
        WHEN curated_total = 0 THEN 'NOT_EVALUATED'
        WHEN ratio(uniqueness_n, curated_total) >= 1.0 THEN 'PASS'
        ELSE 'FAIL'
    END
FROM quality_after_counts

UNION ALL

SELECT
    'value_validity',
    'research-telemetry-v1',
    'CURATED',
    value_validity_n,
    curated_total,
    ratio(value_validity_n, curated_total),
    1.0,
    'ERROR',
    CASE
        WHEN curated_total = 0 THEN 'NOT_EVALUATED'
        WHEN ratio(value_validity_n, curated_total) >= 1.0 THEN 'PASS'
        ELSE 'FAIL'
    END
FROM quality_after_counts

UNION ALL

SELECT
    'qa_coverage',
    'research-telemetry-v1',
    'QA_REFERENCE',
    qa_coverage_n,
    qa_total,
    ratio(qa_coverage_n, qa_total),
    1.0,
    'ERROR',
    CASE
        WHEN qa_total = 0 THEN 'NOT_EVALUATED'
        WHEN ratio(qa_coverage_n, qa_total) >= 1.0 THEN 'PASS'
        ELSE 'FAIL'
    END
FROM quality_after_counts

UNION ALL

SELECT
    'qa_agreement',
    'research-telemetry-v1',
    'QA_COVERED',
    qa_agreement_n,
    qa_coverage_n,
    ratio(qa_agreement_n, qa_coverage_n),
    0.95,
    'ERROR',
    CASE
        WHEN qa_coverage_n = 0 THEN 'NOT_EVALUATED'
        WHEN ratio(
            qa_agreement_n,
            qa_coverage_n
        ) >= 0.95 THEN 'PASS'
        ELSE 'FAIL'
    END
FROM quality_after_counts;
