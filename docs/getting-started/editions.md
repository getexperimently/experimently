# Editions

Experimently ships in two editions from one codebase. The dashboard tells you
which one you are looking at: the pill beside the wordmark reads `CE` or `EE`,
and `GET /api/v1/edition` answers the same question for scripts.

## Community Edition

Community Edition is the whole product for a team running its own
experimentation platform. It is what you get with no licence key configured,
and it is not time-limited, seat-limited or feature-flagged down over time.

It includes experiments and feature flags end to end — targeting rules with
20+ operators, gradual rollouts, safety monitoring with automatic rollback,
scheduling — and the full statistics: frequentist and Bayesian analysis,
sequential testing with early stopping, CUPED variance reduction, multi-armed
bandits, mutual exclusion groups and global holdouts, dimensional breakdowns,
interaction detection, and live results over WebSocket. The four built-in roles
(Admin, Developer, Analyst, Viewer), audit logging, API keys, alerting and
every SDK are Community too.

## Enterprise Edition

Enterprise adds the things an organisation needs once more than one team shares
an instance, or once a compliance regime applies:

| Feature | Licence name | What it adds |
| --- | --- | --- |
| Team workspaces | `workspaces` | Multiple tenants on one instance: members, invites and workspace-scoped API keys |
| Custom roles | `rbac` | Roles beyond the built-in four, and permissions granted directly to a user |
| SSO / SAML / OIDC | `sso` | Enterprise identity providers with just-in-time provisioning and role mapping |
| HIPAA | `hipaa` | PHI encryption, six-year PHI audit retention, BAA records |
| Compliance reporting | `compliance` | SOC 2 / ISO 27001 reports, signed audit exports |
| Warehouse-native analytics | `warehouse` | Query Snowflake, BigQuery, Redshift, Databricks, ClickHouse or MySQL in place |
| Third-party integrations | `integrations` | Jira, Salesforce and GitHub |
| Real-time counters | `counters` | DynamoDB-backed live assignment and conversion counters |
| ETL | `etl` | Glue crawlers, Athena partitions and scheduled jobs |
| Split URL testing | `split_url` | Server-side URL splitting at the edge |

Nothing in the Community feature set moves to Enterprise. The split is along
"one team running the product" versus "an organisation administering it".

## Licences

An Enterprise licence is a signed, offline token. Nothing phones home: no
socket is opened, no hostname resolved, and no usage is reported. The instance
verifies the signature itself and reads the expiry from the token.

Set it as `EXPERIMENTLY_LICENSE_KEY`. `GET /api/v1/edition` then reports the
edition, the feature names the licence covers, and its status. The endpoint is
deliberately thin — it never returns the customer name, the plan, the seat
count or any part of the key itself.

### Licence states

| Status | Meaning | What works |
| --- | --- | --- |
| `none` | No licence key configured | Community Edition |
| `active` | In date | Everything the licence names |
| `grace` | Past expiry, inside the grace window (14 days by default) | Everything the licence names |
| `expired` | Past the grace window | Enterprise reads for a further 30 days; Enterprise writes are refused. The dashboard hides Enterprise pages |
| `invalid` | Malformed, signed by an unknown or revoked key, revoked individually, or not yet valid | Nothing; the instance behaves as Community |

Two things hold in every state, including `invalid`:

- **No data is deleted or hidden.** A lapsed licence refuses Enterprise writes,
  then Enterprise reads. Every row stays in the database and comes back when a
  valid licence is installed.
- **Community features are untouched.** Experiments, flags, assignment,
  tracking and results carry on exactly as before.

Every observed change of licence state is written to the audit trail as a
`license.*` event, so an expiry is visible in the log rather than only in the
banner.

## Which edition am I running?

```bash
curl -s http://localhost:8000/api/v1/edition
```

```json
{"edition": "ce", "features": [], "status": "none", "expires_at": null, "version": "1.0.0"}
```

In the dashboard, the pill next to the wordmark says `CE` or `EE`, and in the
`grace`, `expired` and `invalid` states a banner across the top says what is
happening and what is not affected.
