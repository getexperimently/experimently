WITH events AS (
  SELECT CAST("user_id" AS VARCHAR) AS unit_id, "event_at" AS event_at, CAST("amount" AS DOUBLE) AS metric_value
  FROM "analytics"."orders"
  WHERE "event_at" >= TIMESTAMP '2026-09-01 00:00:00 UTC'
    AND "event_at" < TIMESTAMP '2026-09-27 12:30:00 UTC'
    AND "status" = 'paid'
    AND "is_test" <> TRUE
    AND "amount" IS NOT NULL
)
SELECT COUNT(*) AS total_rows,
  COUNT(CASE WHEN unit_id IS NULL THEN 1 END) AS null_unit_rows,
  COUNT(CASE WHEN metric_value IS NULL THEN 1 END) AS null_value_rows,
  MIN(CAST(floor(to_unixtime(event_at)) AS BIGINT)) AS earliest,
  MAX(CAST(floor(to_unixtime(event_at)) AS BIGINT)) AS latest
FROM events
