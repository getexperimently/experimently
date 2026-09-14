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

### Slack

Add to your `.env` or environment:

```bash
SLACK_ENABLED=true
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_DEFAULT_CHANNEL=#platform-alerts
```

**Required Slack App Permissions**: `chat:write`, `chat:write.public`

### Email via SendGrid

```bash
EMAIL_ENABLED=true
SENDGRID_API_KEY=SG.your-api-key
EMAIL_FROM_ADDRESS=platform@yourcompany.com
EMAIL_FROM_NAME=Experimently
NOTIFICATION_ADMIN_EMAILS=eng-team@yourcompany.com,oncall@yourcompany.com
```

### Email via SMTP (fallback)

If `SENDGRID_API_KEY` is empty, the service falls back to SMTP:

```bash
EMAIL_ENABLED=true
SMTP_HOST=smtp.yourcompany.com
SMTP_PORT=587
SMTP_USERNAME=platform-alerts@yourcompany.com
SMTP_PASSWORD=your-smtp-password
EMAIL_FROM_ADDRESS=platform-alerts@yourcompany.com
```

---

## Notification Preferences API

Each user can configure which event types they want to receive and on which channels.

### GET /api/v1/notifications/preferences

Get the current user's notification preferences. Creates defaults if none exist.

```bash
curl -X GET "http://localhost:8000/api/v1/notifications/preferences" \
  -H "Authorization: Bearer $TOKEN"
```

**Response**

```json
{
  "user_id": "user-uuid",
  "slack_enabled": true,
  "email_enabled": true,
  "notify_on_safety_rollback": true,
  "notify_on_experiment_lifecycle": true,
  "notify_on_rollout_advance": false,
  "slack_channel": null,
  "email_address": null
}
```

`slack_channel: null` and `email_address: null` use the platform defaults (`SLACK_DEFAULT_CHANNEL` and the user's registered email).

---

### PUT /api/v1/notifications/preferences

Update the current user's notification preferences.

```bash
curl -X PUT "http://localhost:8000/api/v1/notifications/preferences" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "slack_enabled": true,
    "email_enabled": false,
    "notify_on_rollout_advance": true,
    "slack_channel": "#my-team-alerts"
  }'
```

---

### GET /api/v1/notifications/admin/preferences

List all users' notification preferences. Requires ADMIN role.

---

### GET /api/v1/notifications/delivery-log

View notification delivery history with filtering. Requires ADMIN role.

**Query Parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `page` | int | Page number (default: 1) |
| `limit` | int | Results per page (default: 20, max: 100) |
| `event_type` | string | Filter by event type |
| `status` | string | Filter by delivery status: `success`, `failed` |

```bash
curl -X GET "http://localhost:8000/api/v1/notifications/delivery-log?status=failed" \
  -H "Authorization: Bearer $TOKEN"
```

**Response**

```json
{
  "items": [
    {
      "id": "log-uuid",
      "event_type": "safety_rollback",
      "channel": "slack",
      "status": "failed",
      "error": "channel_not_found",
      "created_at": "2026-03-02T14:32:00Z"
    }
  ],
  "total": 3,
  "page": 1,
  "limit": 20
}
```

---

### POST /api/v1/notifications/test

Send a test notification to verify channel connectivity. Requires DEVELOPER or ADMIN role.

```bash
curl -X POST "http://localhost:8000/api/v1/notifications/test" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"channel": "slack"}'
```

```json
{"success": true, "message": "Test notification sent to #platform-alerts"}
```

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
