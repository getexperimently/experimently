# GDPR considerations for operators

**Audience:** teams that self-host Experimently and are subject to the GDPR or similar
regimes (UK GDPR, CCPA). **Status:** describes what the software does as of this
version, verified against the code. It is not legal advice, and Experimently is not
certified against any privacy standard. You, the operator, are the controller or
processor; the software gives you controls, it does not make you compliant.

Everything marked *you must* is an operator obligation the software does not automate.

---

## 1. What personal data the platform stores

| Data | Table / column | Why it exists |
|------|----------------|---------------|
| Dashboard account: email, username, first/last name, bcrypt password hash, role | `users` | Login and access control (`backend/app/models/user.py`) |
| Optional Cognito subject | `users.external_id` | Only when `AUTH_PROVIDER=cognito` |
| End-user identifier you send from your app (`user_id`) | `assignments.user_id`, `events.user_id` | Sticky bucketing and metric computation |
| Targeting context you send with an assignment (`context`) | `assignments.context` (JSONB) | Recorded with the assignment so results can be broken down by segment |
| Event payloads (`event_metadata`, `value`) | `events` | Metric computation |
| Client error reports | `error_logs` | SDK error reporting (`POST /api/v1/tracking/errors`) |
| Who changed what in the dashboard | `audit_logs`, `audit_events_v2` | Change history; `audit_events_v2` rows are HMAC-signed |
| PHI access log (HIPAA module) | `phi_audit_logs` | Only written when the HIPAA endpoints are used |
| API key name, scopes, last use | `api_keys` | Key management; the key itself is stored hashed |
| Request logs (IP, user agent, path) | wherever you ship container logs | Operational logging; not written to the database |

The `user_id` you pass to `/api/v1/tracking/assign` and `/track` is opaque to the
platform. **You must** decide whether it is personal data in your context (a hashed or
pseudonymous id is strongly recommended) and **you must not** put names, emails or other
direct identifiers in `context` or `event_metadata`. Nothing in the platform strips
them.

## 2. Lawful basis and roles

When you run Experimently for your own product, you are the controller for both dashboard
accounts and end-user assignment/event data. If you run it on behalf of others, you are a
processor and **you must** have a data-processing agreement with each controller. The
software has no built-in notion of a controller/processor split; multi-tenant
workspaces exist for isolation, not for legal separation.

## 3. Retention and deletion

What exists today:

- `EventService.purge_old_events(days_to_keep)` deletes events older than a cutoff.
  It is **not scheduled**; nothing calls it automatically.
- `DELETE /api/v1/users/{id}` deletes a dashboard account. It does not anonymise the
  account's audit log entries, which keep the actor's email.
- There is **no endpoint** that deletes or exports one end user's assignments and
  events by `user_id`.
- HIPAA audit logs carry a configured retention period (`HIPAA_AUDIT_LOG_RETENTION_YEARS`),
  but no purge job enforces it.

**You must** therefore implement retention yourself for now, for example a scheduled
`DELETE FROM experimentation.events WHERE created_at < now() - interval '1 year'` and the
equivalent for `assignments`, or a cron that calls `purge_old_events`. A per-`user_id`
erasure and export endpoint is on the roadmap (tracked in the launch plan, phase P5) and
is required before the platform can serve data-subject requests without database access.

## 4. Data-subject rights

| Right | What the software offers | What you must do |
|-------|--------------------------|------------------|
| Access / portability (Art. 15, 20) | No self-service export. `GET /api/v1/export/experiments` and `/export/reports/experiments/{id}` export experiments and aggregate results, not one person's data. | Run a query on `assignments` and `events` by `user_id` and hand over the rows. |
| Erasure (Art. 17) | None per end user. Dashboard accounts can be deleted. | Delete or null the `user_id` rows for that person in `assignments`, `events` and `error_logs`. |
| Objection / restriction (Art. 18, 21) | Feature flags and targeting rules let you exclude an identifier. | Maintain the exclusion list in your own system and pass it as context. |

## 5. Security controls that support a privacy programme

- Passwords are bcrypt-hashed; API keys are stored hashed and shown once at creation.
- Local JWTs expire after `LOCAL_AUTH_TOKEN_TTL_MINUTES` (default 12 hours); accounts lock
  for `LOCAL_AUTH_LOCKOUT_MINUTES` after `LOCAL_AUTH_MAX_FAILED_ATTEMPTS` failures.
- `DEV_AUTH_BYPASS` cannot be enabled in staging or production; settings validation refuses to boot.
- The HIPAA module encrypts designated PHI fields with Fernet (`backend/app/core/phi_encryption.py`).
- Audit events in `audit_events_v2` are HMAC-SHA256 signed so tampering is detectable.
- TLS, disk encryption, backups and log retention are properties of your deployment,
  not of the software. **You must** configure them.

## 6. Breach handling

The software does not detect or report breaches. [incident-response-plan.md](incident-response-plan.md) is a template you can adapt; **you must** own the 72-hour notification process.

## 7. Checklist for operators

- [ ] Decide whether `user_id` is personal data in your context; hash it client-side if in doubt.
- [ ] Document your lawful basis for assignment and event data.
- [ ] Schedule retention deletion for `events`, `assignments` and `error_logs`.
- [ ] Write the runbook for access and erasure requests (SQL by `user_id`) until the endpoints exist.
- [ ] Keep `SECRET_KEY`, `POSTGRES_PASSWORD` and the HIPAA encryption key out of the repository and rotate them.
- [ ] Ship container logs to a store with a retention limit; they contain IPs and user agents.
- [ ] If you operate for other controllers, sign a DPA and list your sub-processors.

Related: [Security overview](README.md), [HIPAA module](../api/compliance.md).
