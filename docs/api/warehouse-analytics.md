# Warehouse Analytics

!!! warning "Removed in the full profile; being rebuilt"
    The `/api/v1/warehouse` endpoints -- stored warehouse connections, sync,
    and the ClickHouse, MySQL and Databricks connectors -- have been removed
    and now answer 404. Warehouse analysis is being rebuilt
    ([#312](https://github.com/getexperimently/experimently/issues/312)) and
    will ship as new beta endpoints. Core deployments never served these
    routes and are unchanged.

## If you ran the full profile

Stored warehouse connections are no longer read by anything. Delete every
row in the `warehouse_connections` table, including inactive ones, and rotate
every credential that was ever saved there:

```sql
-- Replace experimentation with your POSTGRES_SCHEMA.
DELETE FROM experimentation.warehouse_connections;
```

Credentials sent to the connector endpoints as query parameters may be in
your access logs: rotate those too.

The ClickHouse, MySQL and Databricks drivers are no longer installed in the
full image, and the `DATABRICKS_*`, `CLICKHOUSE_*` and `MYSQL_*` settings are
no longer read.

See [Modules and profiles](../getting-started/modules.md) for what each
profile includes.
