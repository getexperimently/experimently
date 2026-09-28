WITH exposures AS (
  SELECT CAST("USER_ID" AS VARCHAR) AS unit_id,
    SUBSTR(CAST("VARIANT" AS VARCHAR), 1, 64) AS variant,
    CAST("EXPOSED_AT" AS TIMESTAMP_TZ) AS exposed_at
  FROM "ANALYTICS"."PUBLIC"."EXPOSURES"
  WHERE "EXPERIMENT_KEY" = 'checkout-v2'
    AND CAST("EXPOSED_AT" AS TIMESTAMP_TZ) >= '2026-09-01 00:00:00 +00:00'::TIMESTAMP_TZ
    AND CAST("EXPOSED_AT" AS TIMESTAMP_TZ) < '2026-09-27 12:30:00 +00:00'::TIMESTAMP_TZ
    AND "PLATFORM" IN ('web', 'ios')
),
units AS (
  SELECT unit_id, MIN(variant) AS variant, MIN(exposed_at) AS first_exposed_at,
    COUNT(DISTINCT variant) AS n_variants
  FROM exposures
  WHERE unit_id IS NOT NULL AND variant IS NOT NULL
  GROUP BY unit_id
),
events AS (
  SELECT CAST("USER_ID" AS VARCHAR) AS unit_id, CAST("EVENT_AT" AS TIMESTAMP_TZ) AS event_at, CAST("AMOUNT" AS DOUBLE) AS metric_value
  FROM "ANALYTICS"."PUBLIC"."ORDERS"
  WHERE CAST("EVENT_AT" AS TIMESTAMP_TZ) >= '2026-09-01 00:00:00 +00:00'::TIMESTAMP_TZ
    AND CAST("EVENT_AT" AS TIMESTAMP_TZ) < '2026-09-27 12:30:00 +00:00'::TIMESTAMP_TZ
    AND "STATUS" = 'paid'
    AND "IS_TEST" <> TRUE
    AND "AMOUNT" IS NOT NULL
),
per_unit AS (
  SELECT u.unit_id, u.variant, COUNT(e.event_at) AS n_events,
    COALESCE(SUM(e.metric_value), 0) AS y_raw
  FROM units AS u
  LEFT JOIN events AS e
    ON e.unit_id = u.unit_id
    AND e.event_at >= u.first_exposed_at
    AND e.event_at < LEAST(DATEADD(HOUR, 168, u.first_exposed_at), '2026-09-27 12:30:00 +00:00'::TIMESTAMP_TZ)
  WHERE u.n_variants = 1
  GROUP BY u.unit_id, u.variant
),
y AS (
  SELECT variant, CASE WHEN n_events > 0 THEN 1 ELSE 0 END AS converted,
    LEAST(CAST(y_raw AS DOUBLE), CAST(500.0 AS DOUBLE)) AS y
  FROM per_unit
),
k AS (
  SELECT AVG(y) AS k FROM y
),
diag AS (
  SELECT (SELECT COUNT(*) FROM events) AS metric_rows_in_window,
    (SELECT COUNT(*) FROM events AS e INNER JOIN units AS u ON e.unit_id = u.unit_id) AS metric_rows_matched,
    (SELECT COUNT(*) FROM events WHERE metric_value IS NULL) AS null_value_rows,
    TO_CHAR(CURRENT_TIMESTAMP(), 'TZH:TZM') AS session_offset
)
SELECT y.variant AS variant,
  COUNT(*) AS n,
  SUM(y.converted) AS n_converted,
  CAST(CAST(MIN(k.k) AS DECFLOAT) AS VARCHAR) AS k,
  CAST(CAST(SUM(y.y - k.k) AS DECFLOAT) AS VARCHAR) AS sum_d,
  CAST(CAST(SUM((y.y - k.k) * (y.y - k.k)) AS DECFLOAT) AS VARCHAR) AS sum_d2,
  MIN(diag.metric_rows_in_window) AS metric_rows_in_window,
  MIN(diag.metric_rows_matched) AS metric_rows_matched,
  MIN(diag.null_value_rows) AS null_value_rows,
  MIN(diag.session_offset) AS session_offset
FROM y CROSS JOIN k CROSS JOIN diag
GROUP BY y.variant
ORDER BY n DESC, variant
LIMIT 51
