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
per_variant AS (
  SELECT variant, COUNT(DISTINCT unit_id) AS units
  FROM exposures
  WHERE variant IS NOT NULL
  GROUP BY variant
  ORDER BY units DESC, variant
  LIMIT 51
),
totals AS (
  SELECT COUNT(*) AS total_rows,
    COUNT(CASE WHEN unit_id IS NULL THEN 1 END) AS null_unit_rows,
    COUNT(CASE WHEN variant IS NULL THEN 1 END) AS null_variant_rows,
    MIN(DATE_PART(EPOCH_SECOND, exposed_at)) AS earliest,
    MAX(DATE_PART(EPOCH_SECOND, exposed_at)) AS latest,
    MIN(TO_CHAR(CURRENT_TIMESTAMP(), 'TZH:TZM')) AS session_offset
  FROM exposures
)
SELECT t.total_rows AS total_rows, t.null_unit_rows AS null_unit_rows,
  t.null_variant_rows AS null_variant_rows, t.earliest AS earliest,
  t.latest AS latest, v.variant AS variant, v.units AS units,
  t.session_offset AS session_offset
FROM totals AS t
LEFT JOIN per_variant AS v ON 1 = 1
ORDER BY v.units DESC, v.variant
LIMIT 51
