# Slack & Email Alerting

The alerting system sends notifications to Slack channels and email addresses when significant platform events occur: safety rollbacks, experiment lifecycle changes, rollout stage advances, and custom alerts.

Notification failure is always non-fatal — if a Slack message or email cannot be sent, the platform operation that triggered it continues normally and the failure is logged.

---

## Supported Channels

| Channel | Provider | Configuration |
|---------|----------|--------------|
| Slack | Slack Block Kit via `slack_sdk` | `SLACK_BOT_TOKEN`, `SLACK_DEFAULT_CHANNEL` |
| Email | SendGrid (preferred) or SMTP fallback | `SENDGRID_API_KEY` or SMTP settings |

---

## Event Types

| Event | Slack | Email | Description |
|-------|-------|-------|-------------|
| Safety rollback | ✅ | ✅ | Feature flag auto-rolled back due to error rate or latency threshold |
| Experiment lifecycle | ✅ | ✅ | Experiment started, paused, stopped, or completed |
| Rollout stage advance | ✅ | ❌ | Rollout schedule progressed to next stage |
| Generic alert | ✅ | ✅ | Custom alert from any platform service |

---

## Configuration

These are settings of the API process: put them in its environment (on the Quick Start
stack, the `api` service's `environment:` in `docker-compose.yml`), then restart it.
Both channels are off until you turn them on.

### Slack

```dotenv
SLACK_ENABLED=true
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_DEFAULT_CHANNEL="#platform-alerts"
```

**Required Slack App Permissions**: `chat:write`, `chat:write.public`

### Email via SendGrid

`NOTIFICATION_ADMIN_EMAILS` is a JSON array. A plain comma-separated list stops the API
from starting, with `error parsing value for field "NOTIFICATION_ADMIN_EMAILS"`.

```dotenv
EMAIL_ENABLED=true
SENDGRID_API_KEY=SG.your-api-key
EMAIL_FROM_ADDRESS=platform@yourcompany.com
EMAIL_FROM_NAME=Experimently
NOTIFICATION_ADMIN_EMAILS=["eng-team@yourcompany.com","oncall@yourcompany.com"]
```

### Email via SMTP (fallback)

If `SENDGRID_API_KEY` is empty, the service falls back to SMTP:

```dotenv
EMAIL_ENABLED=true
SMTP_HOST=smtp.yourcompany.com
SMTP_PORT=587
SMTP_USERNAME=platform-alerts@yourcompany.com
SMTP_PASSWORD=your-smtp-password
EMAIL_FROM_ADDRESS=platform-alerts@yourcompany.com
```

---

## Notification Preferences API

Each user chooses which events they are notified about, and can send their Slack alerts to
a channel of their own or their email to another address.

Run the commands on this page in one terminal, in order, against the stack from the
[Quick Start](../getting-started/quick-start.md). Each uses the shell variables set by the
ones before it. Log in first:

```{.bash exec}
TOKEN=$(curl -s -X POST localhost:8000/api/v1/auth/login \
  -H 'content-type: application/json' \
  -d '{"email":"admin@demo.com","password":"Demo1234!"}' | jq -r .access_token)

curl -s localhost:8000/api/v1/auth/me -H "Authorization: Bearer $TOKEN" | jq .role
```
<!-- expect: "ADMIN" -->

It prints `"ADMIN"`.

### GET /api/v1/notifications/preferences

Returns the current user's preferences, creating the defaults the first time:

```{.bash exec}
curl -s localhost:8000/api/v1/notifications/preferences \
  -H "Authorization: Bearer $TOKEN" | jq '{notify_experiment_started, notify_rollout_advanced, slack_channel}'
```
<!-- expect: "notify_experiment_started": true -->
<!-- expect: "notify_rollout_advanced": false -->
<!-- expect: "slack_channel": null -->

It prints the defaults: notified when an experiment starts, not when a rollout advances,
and no channel of your own. The full response:

```json
{
  "notify_experiment_started": true,
  "notify_experiment_completed": true,
  "notify_safety_rollback": true,
  "notify_rollout_advanced": false,
  "slack_channel": null,
  "email_override": null,
  "id": "e99a2406-2fb5-455d-8082-47024f676fee",
  "user_id": "2658dd18-4167-4803-9aff-a3ffb1f603ce",
  "created_at": "2026-09-26T22:51:27.531187",
  "updated_at": "2026-09-26T22:51:27.531187"
}
```

`slack_channel: null` and `email_override: null` use the platform defaults
(`SLACK_DEFAULT_CHANNEL` and the user's own email).

---

### PUT /api/v1/notifications/preferences

Changes the fields you send and leaves the others as they are. This turns on rollout
notifications and sends your Slack alerts to `#my-team-alerts`:

```{.bash exec}
curl -s -X PUT localhost:8000/api/v1/notifications/preferences \
  -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"notify_rollout_advanced": true, "slack_channel": "#my-team-alerts"}' \
  | jq '{notify_rollout_advanced, slack_channel}'
```
<!-- expect: "notify_rollout_advanced": true -->
<!-- expect: "slack_channel": "#my-team-alerts" -->

It prints the two changed values. The fields are `notify_experiment_started`,
`notify_experiment_completed`, `notify_safety_rollback`, `notify_rollout_advanced`,
`slack_channel` and `email_override`; any other field is ignored.

---

### GET /api/v1/notifications/admin/preferences

Lists every user's preferences. Requires the ADMIN role.

---

### GET /api/v1/notifications/delivery-log

Lists the notifications that were sent, most recent first. Requires the ADMIN role.

**Query Parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `page` | int | Page number (default: 1) |
| `limit` | int | Results per page (default: 20, max: 100) |
| `event_type` | string | Filter by event type |
| `status` | string | Filter by delivery status: `sent`, `failed`, `skipped` |

```{.bash exec}
curl -s "localhost:8000/api/v1/notifications/delivery-log?status=failed" \
  -H "Authorization: Bearer $TOKEN" | jq '{total, page, limit}'
```
<!-- expect: "total": 0 -->

On a new stack it prints `"total": 0`, since nothing has been sent. Each entry in `items`
looks like this:

```json
{
  "id": "0b8f3c9e-3c3a-4d5e-9c0e-1f2a3b4c5d6e",
  "event_type": "safety_rollback",
  "channel": "slack",
  "recipient": "#platform-alerts",
  "subject": null,
  "status": "failed",
  "error_message": "channel_not_found",
  "payload": null,
  "created_at": "2026-03-02T14:32:00Z"
}
```

---

### POST /api/v1/notifications/test

Sends a test notification, to check a channel's settings. Requires the DEVELOPER or
ADMIN role. `channel` is `slack`, `email` or `webhook`; `recipient` is optional (a Slack
channel or an email address) and `message` defaults to "Test notification from
Experimently":

```{.bash exec}
curl -s -X POST localhost:8000/api/v1/notifications/test \
  -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"channel": "slack"}' | jq .success
```
<!-- expect: false -->

On the Quick Start stack it prints `false`, because Slack is not configured there. With
`SLACK_ENABLED=true` and a valid bot token, it prints `true` and the message arrives in
`SLACK_DEFAULT_CHANNEL`. A test is not written to the delivery log.

---

## Permissions

| Action | Minimum Role |
|--------|-------------|
| View own preferences | Any authenticated user |
| Update own preferences | Any authenticated user |
| Send test notification | DEVELOPER |
| View all preferences / delivery log | ADMIN |

---

## Troubleshooting

**Slack messages not arriving**
1. Confirm `SLACK_ENABLED=true` in environment
2. Verify the bot token is valid: `GET https://slack.com/api/auth.test`
3. Ensure the bot is invited to the target channel (`/invite @your-bot`)
4. Check the delivery log for `channel_not_found` or `not_authed` errors

**Emails not arriving**
1. Confirm `EMAIL_ENABLED=true`
2. For SendGrid: check API key has `Mail Send` permission
3. For SMTP: verify host, port and credentials from the API container with `python -c "import smtplib; smtplib.SMTP('$SMTP_HOST', $SMTP_PORT).starttls()"`
4. Check spam folder — add `EMAIL_FROM_ADDRESS` domain to allowlist
5. Delivery log errors like `unauthorized` indicate a bad API key
