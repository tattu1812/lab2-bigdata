-- =========================================================
-- TASK 3 - CURATE (Vai C / Curation)
-- Chạy bởi src/run_curate.py. Các placeholder dạng double-brace do runner thay thế;
-- mọi ngưỡng/quy tắc đọc trực tiếp từ contracts/*.json (không hard-code).
--
-- Luồng:
--   canonical -> prekey (PARSE/KEY/INGEST_PARSE) -> key_eligible
--   -> ranked/winners/duplicates -> winner_checked (7 lý do)
--   -> curated | quarantine | duplicates
--
-- Đầu ra (TEMP VIEW): curated, quarantine, duplicates, curation_summary
-- =========================================================

-- ---------------------------------------------------------
-- 0. Tham số từ contract.json + curation_decisions.json
-- ---------------------------------------------------------
CREATE OR REPLACE TEMP TABLE params AS
SELECT
    strptime(c.as_of, '{{TS_FORMAT}}')            AS as_of_ts,
    c.late_threshold_seconds                      AS late_seconds,
    c.record_id_pattern                           AS record_id_pattern,
    c.supported_units                             AS supported_units,
    c.temperature_range_c.min                     AS range_min,
    c.temperature_range_c.max                     AS range_max,
    c.prekey_reason_precedence                    AS prekey_precedence,
    c.row_reason_precedence                       AS row_precedence,
    c.primary_reason_precedence                   AS primary_precedence,
    d.temperature_rounding.decimal_places         AS decimal_places,
    d.temperature_rounding.mode                   AS rounding_mode,
    CAST(power(10, d.temperature_rounding.decimal_places) AS HUGEINT) AS dp_factor
FROM read_json(
        '{{CONTRACT_PATH}}',
        columns = {
            'as_of': 'VARCHAR',
            'late_threshold_seconds': 'BIGINT',
            'record_id_pattern': 'VARCHAR',
            'supported_units': 'VARCHAR[]',
            'temperature_range_c': 'STRUCT(min DECIMAL(18,6), max DECIMAL(18,6))',
            'prekey_reason_precedence': 'VARCHAR[]',
            'row_reason_precedence': 'VARCHAR[]',
            'primary_reason_precedence': 'VARCHAR[]'
        }
     ) AS c,
     read_json(
        '{{DECISIONS_PATH}}',
        columns = {
            'temperature_rounding': 'STRUCT(decimal_places INTEGER, mode VARCHAR)'
        }
     ) AS d;


-- ---------------------------------------------------------
-- 1. Nguồn vật lý: sha256 từng source_object (từ stage-report của Task 1)
-- ---------------------------------------------------------
CREATE OR REPLACE TEMP VIEW source_files AS
SELECT o.key AS source_object, lower(o.actual_sha256) AS source_sha256
FROM (
    SELECT unnest(objects) AS o
    FROM read_json(
        '{{STAGE_REPORT_PATH}}',
        columns = {'objects': 'STRUCT(key VARCHAR, actual_sha256 VARCHAR, status VARCHAR)[]'}
    )
)
WHERE o.status = 'PASS';


-- ---------------------------------------------------------
-- 2. Registry sensors (chỉ dùng để join site + kiểm REFERENCE)
-- ---------------------------------------------------------
CREATE OR REPLACE TEMP VIEW sensor_registry AS
SELECT
    NULLIF(trim(upper(sensor_id)), '') AS sensor_id,
    NULLIF(trim(site), '')             AS site
FROM read_csv('{{SENSORS_PATH}}', header = true, all_varchar = true)
WHERE NULLIF(trim(sensor_id), '') IS NOT NULL;


-- ---------------------------------------------------------
-- 3. Canonical: gộp 2 nguồn về cùng schema (mapping như Task 2).
--    Mọi giá trị đọc dưới dạng chuỗi; rỗng/blank -> NULL.
-- ---------------------------------------------------------
CREATE OR REPLACE TEMP VIEW envelopes AS
SELECT source_object, source_row, parse_status, payload
FROM read_json(
    '{{ENVELOPES_PATH}}',
    format = 'newline_delimited',
    columns = {
        'source_object': 'VARCHAR',
        'source_row': 'BIGINT',
        'parse_status': 'VARCHAR',
        'payload': 'JSON'
    }
);

CREATE OR REPLACE TEMP VIEW canonical AS
WITH mapped AS (
    SELECT
        e.source_object,
        e.source_row,
        e.parse_status,
        f.source_sha256,
        CASE e.source_object
            WHEN 'observations_a.csv'   THEN json_extract_string(e.payload, '$.record_id')
            WHEN 'observations_b.jsonl' THEN json_extract_string(e.payload, '$.id')
        END AS record_id_raw,
        CASE e.source_object
            WHEN 'observations_a.csv'   THEN json_extract_string(e.payload, '$.sensor_id')
            WHEN 'observations_b.jsonl' THEN json_extract_string(e.payload, '$.sensor')
        END AS sensor_id_raw,
        CASE e.source_object
            WHEN 'observations_a.csv'   THEN json_extract_string(e.payload, '$.event_time')
            WHEN 'observations_b.jsonl' THEN json_extract_string(e.payload, '$.timestamp')
        END AS event_raw_,
        CASE e.source_object
            WHEN 'observations_a.csv'   THEN json_extract_string(e.payload, '$.ingest_time')
            WHEN 'observations_b.jsonl' THEN json_extract_string(e.payload, '$.arrived_at')
        END AS ingest_raw_,
        CASE e.source_object
            WHEN 'observations_a.csv'   THEN json_extract_string(e.payload, '$.reading')
            WHEN 'observations_b.jsonl' THEN json_extract_string(e.payload, '$.temperature')
        END AS reading_raw_,
        CASE e.source_object
            WHEN 'observations_a.csv'   THEN json_extract_string(e.payload, '$.unit')
            WHEN 'observations_b.jsonl' THEN json_extract_string(e.payload, '$.temperature_unit')
        END AS unit_raw
        -- operator_email / operator / raw_payload: CỐ Ý không đọc (restricted_fields)
    FROM envelopes e
    LEFT JOIN source_files f USING (source_object)
)
SELECT
    source_object,
    source_row,
    parse_status,
    source_sha256,
    NULLIF(trim(upper(record_id_raw)), '') AS record_id,
    NULLIF(trim(upper(sensor_id_raw)), '') AS sensor_id,
    NULLIF(trim(upper(unit_raw)), '')      AS unit,
    NULLIF(trim(event_raw_), '')           AS event_raw,
    NULLIF(trim(ingest_raw_), '')          AS ingest_raw,
    NULLIF(trim(reading_raw_), '')         AS reading_raw,
    try_strptime(NULLIF(trim(event_raw_), ''),  '{{TS_FORMAT}}') AS event_ts,
    try_strptime(NULLIF(trim(ingest_raw_), ''), '{{TS_FORMAT}}') AS ingest_ts
FROM mapped;


-- ---------------------------------------------------------
-- 4. BƯỚC 1 - Prekey: PARSE / KEY / INGEST_PARSE (trước dedup)
--    reasons = mọi lý do áp dụng, sắp theo prekey_reason_precedence
-- ---------------------------------------------------------
CREATE OR REPLACE TEMP VIEW prekey_flags AS
SELECT
    c.*,
    (c.parse_status <> 'OK') AS f_parse,
    (c.parse_status = 'OK'
        AND (c.record_id IS NULL
             OR NOT regexp_matches(c.record_id, p.record_id_pattern))) AS f_key,
    (c.parse_status = 'OK' AND c.ingest_ts IS NULL)                    AS f_ingest_parse
FROM canonical c, params p;

CREATE OR REPLACE TEMP VIEW prekey_classified AS
SELECT
    pf.*,
    list_filter(
        p.prekey_precedence,
        r -> (r = 'PARSE'        AND pf.f_parse)
          OR (r = 'KEY'          AND pf.f_key)
          OR (r = 'INGEST_PARSE' AND pf.f_ingest_parse)
    ) AS prekey_reasons
FROM prekey_flags pf, params p;

CREATE OR REPLACE TEMP VIEW prekey_rejected AS
SELECT * FROM prekey_classified WHERE len(prekey_reasons) > 0;

CREATE OR REPLACE TEMP VIEW key_eligible AS
SELECT * FROM prekey_classified WHERE len(prekey_reasons) = 0;


-- ---------------------------------------------------------
-- 5. BƯỚC 2 - Dedup tất định: ingest_ts DESC, source_object ASC, source_row ASC
-- ---------------------------------------------------------
CREATE OR REPLACE TEMP VIEW ranked AS
SELECT
    k.*,
    row_number() OVER (
        PARTITION BY k.record_id
        ORDER BY k.ingest_ts DESC, k.source_object ASC, k.source_row ASC
    ) AS rn
FROM key_eligible k;

CREATE OR REPLACE TEMP VIEW winners AS
SELECT * FROM ranked WHERE rn = 1;

CREATE OR REPLACE TEMP VIEW duplicates AS
SELECT
    r.record_id,
    r.source_object,
    r.source_row,
    r.source_sha256,
    'SUPERSEDED'            AS reason,
    w.source_object         AS winner_source_object,
    w.source_row            AS winner_source_row,
    w.source_sha256         AS winner_source_sha256
FROM ranked r
JOIN winners w ON w.record_id = r.record_id
WHERE r.rn > 1;


-- ---------------------------------------------------------
-- 6. BƯỚC 3 - Validate winner (không fallback sang bản cũ)
--    Số học nhiệt độ dùng số nguyên cố định (HUGEINT) để làm tròn
--    ROUND_HALF_UP chính xác; kiểm khoảng TRƯỚC khi làm tròn.
--      temp_c = temp_num / temp_den
--      C: num = x*1e8        den = 1e8
--      F: num = (x-32)*5*1e8 den = 9e8
-- ---------------------------------------------------------
CREATE OR REPLACE TEMP VIEW winner_numeric AS
SELECT
    w.*,
    TRY_CAST(w.reading_raw AS DOUBLE) AS reading_dbl,
    CAST(
        TRY_CAST(TRY_CAST(w.reading_raw AS DOUBLE) AS DECIMAL(24,8)) * 100000000
        AS HUGEINT
    ) AS reading_scaled
FROM winners w;

CREATE OR REPLACE TEMP VIEW winner_calc AS
SELECT
    n.*,
    CASE n.unit
        WHEN 'C' THEN n.reading_scaled
        WHEN 'F' THEN (n.reading_scaled - CAST(3200000000 AS HUGEINT)) * 5
    END AS temp_num,
    CASE n.unit
        WHEN 'C' THEN CAST(100000000 AS HUGEINT)
        WHEN 'F' THEN CAST(900000000 AS HUGEINT)
    END AS temp_den
FROM winner_numeric n;

CREATE OR REPLACE TEMP VIEW winner_flags AS
SELECT
    c.*,
    reg.site AS reg_site,
    -- REQUIRED
    (c.sensor_id IS NULL OR c.event_raw IS NULL OR c.ingest_raw IS NULL
        OR c.reading_raw IS NULL OR c.unit IS NULL)                          AS f_required,
    -- NUMERIC: có giá trị nhưng không parse được / không hữu hạn
    (c.reading_raw IS NOT NULL
        AND (c.reading_dbl IS NULL OR NOT isfinite(c.reading_dbl)))          AS f_numeric,
    -- UNIT
    (c.unit IS NOT NULL AND NOT list_contains(p.supported_units, c.unit))    AS f_unit,
    -- RANGE: chỉ xét khi số hợp lệ + đơn vị hợp lệ; tràn DECIMAL(24,8) => ngoài khoảng
    (c.reading_raw IS NOT NULL
        AND c.reading_dbl IS NOT NULL AND isfinite(c.reading_dbl)
        AND c.unit IS NOT NULL AND list_contains(p.supported_units, c.unit)
        AND (c.temp_num IS NULL
             OR c.temp_num * 1000000 < CAST(p.range_min * 1000000 AS HUGEINT) * c.temp_den
             OR c.temp_num * 1000000 > CAST(p.range_max * 1000000 AS HUGEINT) * c.temp_den
        ))                                                                   AS f_range,
    -- TIME_PARSE (ingest đã hợp lệ nhờ prekey)
    (c.event_raw IS NOT NULL AND c.event_ts IS NULL)                         AS f_time_parse,
    -- TIME_ORDER: event <= ingest <= as_of
    (c.event_ts IS NOT NULL AND c.ingest_ts IS NOT NULL
        AND (c.event_ts > c.ingest_ts OR c.ingest_ts > p.as_of_ts))          AS f_time_order,
    -- REFERENCE
    (c.sensor_id IS NOT NULL AND reg.sensor_id IS NULL)                      AS f_reference
FROM winner_calc c
CROSS JOIN params p
LEFT JOIN sensor_registry reg ON reg.sensor_id = c.sensor_id
                             AND reg.site IS NOT NULL;

CREATE OR REPLACE TEMP VIEW winner_checked AS
SELECT
    f.*,
    list_filter(
        p.row_precedence,
        r -> (r = 'REQUIRED'   AND f.f_required)
          OR (r = 'NUMERIC'    AND f.f_numeric)
          OR (r = 'UNIT'       AND f.f_unit)
          OR (r = 'RANGE'      AND f.f_range)
          OR (r = 'TIME_PARSE' AND f.f_time_parse)
          OR (r = 'TIME_ORDER' AND f.f_time_order)
          OR (r = 'REFERENCE'  AND f.f_reference)
    ) AS row_reasons
FROM winner_flags f, params p;


-- ---------------------------------------------------------
-- 7. BƯỚC 4 - Curated: join site, is_late, làm tròn HALF_UP sau validate
--    hundredths = sign(num) * floor((2*|num|*10^dp + den) / (2*den))
-- ---------------------------------------------------------
CREATE OR REPLACE TEMP VIEW curated AS
SELECT
    w.record_id                                         AS record_id,
    w.sensor_id                                         AS sensor_id,
    w.reg_site                                          AS site,
    w.event_ts                                          AS event_time_utc,
    w.ingest_ts                                         AS ingest_time_utc,
    CAST(
        CAST(
            sign(w.temp_num) * ((2 * abs(w.temp_num) * p.dp_factor + w.temp_den)
                                // (2 * w.temp_den))
            AS DOUBLE
        ) / p.dp_factor
        AS {{OUTPUT_TYPE}}
    )                                                   AS temperature_c,
    (epoch(w.ingest_ts) - epoch(w.event_ts)) > p.late_seconds AS is_late,
    w.source_object                                     AS source_object,
    w.source_row                                        AS source_row,
    w.source_sha256                                     AS source_sha256
FROM winner_checked w, params p
WHERE len(w.row_reasons) = 0;


-- ---------------------------------------------------------
-- 8. Quarantine: khóa vật lý + mọi lý do (theo precedence) + lý do chính
-- ---------------------------------------------------------
CREATE OR REPLACE TEMP VIEW quarantine AS
WITH q AS (
    SELECT record_id, source_object, source_row, source_sha256,
           'PREKEY' AS stage, prekey_reasons AS reasons
    FROM prekey_rejected
    UNION ALL
    SELECT record_id, source_object, source_row, source_sha256,
           'WINNER' AS stage, row_reasons AS reasons
    FROM winner_checked
    WHERE len(row_reasons) > 0
)
SELECT
    q.record_id,
    q.source_object,
    q.source_row,
    q.source_sha256,
    q.stage,
    list_filter(p.primary_precedence, r -> list_contains(q.reasons, r))[1] AS primary_reason,
    array_to_string(q.reasons, '|')                                         AS reasons
FROM q, params p;


-- ---------------------------------------------------------
-- 9. Tóm tắt (đối soát bảo toàn)
-- ---------------------------------------------------------
CREATE OR REPLACE TEMP VIEW curation_summary AS
SELECT
    (SELECT count(*) FROM canonical)       AS raw_total,
    (SELECT count(*) FROM prekey_rejected) AS prekey_rejected,
    (SELECT count(*) FROM key_eligible)    AS key_eligible,
    (SELECT count(*) FROM winners)         AS winners,
    (SELECT count(*) FROM duplicates)      AS duplicates,
    (SELECT count(*) FROM curated)         AS curated,
    (SELECT count(*) FROM quarantine)      AS quarantine_total,
    (SELECT count(*) FROM quarantine WHERE stage = 'WINNER') AS quarantine_winner;
