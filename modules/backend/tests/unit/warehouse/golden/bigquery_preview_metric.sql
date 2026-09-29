WITH events AS (
  SELECT CAST(`user_id` AS STRING) AS unit_id, `event_at` AS event_at, CAST(`amount` AS FLOAT64) AS metric_value
  FROM `acme-prod`.`analytics`.`orders`
  WHERE `event_at` >= TIMESTAMP '2026-09-01 00:00:00+00:00'
    AND `event_at` < TIMESTAMP '2026-09-27 12:30:00+00:00'
    AND `status` = 'paid'
    AND `is_test` <> TRUE
    AND `amount` IS NOT NULL
)
SELECT COUNT(*) AS total_rows,
  COUNT(CASE WHEN unit_id IS NULL THEN 1 END) AS null_unit_rows,
  COUNT(CASE WHEN metric_value IS NULL THEN 1 END) AS null_value_rows,
  MIN(UNIX_SECONDS(event_at)) AS earliest,
  MAX(UNIX_SECONDS(event_at)) AS latest
FROM events
