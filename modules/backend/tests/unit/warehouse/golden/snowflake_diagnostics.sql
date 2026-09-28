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
  SELECT unit_id, COUNT(DISTINCT variant) AS n_variants
  FROM exposures
  WHERE unit_id IS NOT NULL AND variant IS NOT NULL
  GROUP BY unit_id
)
SELECT (SELECT COUNT(*) FROM exposures) AS exposure_rows,
  (SELECT COUNT(*) FROM exposures WHERE unit_id IS NULL OR variant IS NULL) AS null_key_rows,
  (SELECT COUNT(*) FROM units) AS units,
  (SELECT COUNT(*) FROM units WHERE n_variants > 1) AS multi_variant_units,
  (SELECT COUNT(DISTINCT variant) FROM exposures WHERE unit_id IS NOT NULL AND variant IS NOT NULL) AS variant_values,
  TO_CHAR(CURRENT_TIMESTAMP(), 'TZH:TZM') AS session_offset
