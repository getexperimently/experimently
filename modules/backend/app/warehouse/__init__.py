"""The shared outbound layer the warehouse connectors are built on.

* :mod:`.errors` -- the fixed set of error codes and the one exception type
  every warehouse failure is reported as.
* :mod:`.deadlines` -- the fixed per-call and total time limits, enforced on a
  monotonic clock inside the thread that does the work.
* :mod:`.egress` -- the HTTP client: only the warehouses' published endpoints,
  only public addresses, no redirects, no environment proxies.
* :mod:`.aws` -- the same destination rule for boto3 clients.
* :mod:`.executor` -- the bounded pool warehouse calls run on, off the request
  thread pool, with an admission step that refuses instead of waiting.

* :mod:`.connectors` -- which connectors a deployment may use (none until
  each has passed a check against a real account).
* :mod:`.bigquery` -- the BigQuery connector, built on the modules above.
* :mod:`.snowflake` -- the Snowflake connector, built on the same modules.

Nothing here is routed; the routes build on it.
"""
