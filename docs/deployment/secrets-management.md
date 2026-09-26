# Secrets Management — Experimently

**Version:** 1.0
**Date:** March 2026
**Audience:** DevOps, Security Engineers
**Classification:** Internal — Handle as Confidential

---

## Overview

All production secrets are stored in AWS Secrets Manager. The application never reads secrets from files or baked environment variables. Secrets are injected at container runtime by ECS using the `secrets` key in the task definition.

**Core principles:**
- No secrets in source code, `.env` files, or container images
- All secrets under the `/prod/experimentation/` prefix in Secrets Manager
- ECS task role has `secretsmanager:GetSecretValue` permission scoped to that prefix
- Secret values are never logged, printed to stdout, or included in error messages
- Rotation is scheduled and documented below

---

## Required Secrets (Create Before First Deploy)

Create all of the following before running the first production deployment. These commands must be run by an IAM identity with `secretsmanager:CreateSecret` permission.

The secrets a human creates are:

| Secret | Profile |
|--------|---------|
| `/<env>/experimentation/jwt-secret` | both |
| `/<env>/experimentation/first-superuser-password` | both |
| `/<env>/experimentation/audit-hmac-key` | `full` only |

Nothing else: the database credentials and the Redis connection come from their
stacks (below).

### Database credentials: nothing to create

There is no `db-password` secret any more (#78). The database stack generates
Aurora's master credentials into its own secret,
`experimentation-database-<env>-aurora-credentials` (JSON with `username` and
`password` fields; the ARN is the stack's `SecretArn` output), and creates the
cluster with them. Both backend task definitions read `POSTGRES_USER` and
`POSTGRES_PASSWORD` from that secret's two fields, and `POSTGRES_SERVER` from
the stack's writer endpoint, so the credentials the tasks present are by
construction the ones the cluster has. A hand-made copy could only ever
disagree with it.

The generated password may contain any printable character except
`" @ / \`. The application percent-encodes `POSTGRES_USER` and
`POSTGRES_PASSWORD` when it builds the connection URL, so no escaping is needed
there.

**A `DATABASE_URI` supplied directly is used exactly as given, so it must
already be percent-encoded.** If you set `DATABASE_URI` (or
`SQLALCHEMY_DATABASE_URI`) yourself instead of the `POSTGRES_*` variables,
encode the user and password first -- a `#`, `?`, `%`, `:`, `/`, `@` or space
left raw either breaks the URL or silently sends a different password:

```bash
python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$PASSWORD"
```

(`quote`, not `quote_plus`: the driver decodes `+` literally, so a space
encoded as `+` would come back as `+`.)

### JWT Signing Secret

The JWT secret must be at least 32 characters. Using 48 characters provides adequate security margin.

```bash
JWT_SECRET=$(openssl rand -base64 48)

aws secretsmanager create-secret \
  --name /prod/experimentation/jwt-secret \
  --description "JWT token signing secret for the experimentation platform API" \
  --secret-string "$JWT_SECRET" \
  --tags '[{"Key":"Environment","Value":"production"},{"Key":"Service","Value":"experimently"}]'
```

### Redis: nothing to create

There is no Redis secret any more (#147). The old one held a connection URL,
injected as a variable nothing in the application reads; every Redis client is
built from `REDIS_HOST` and `REDIS_PORT`, which the task did not set, so the
tasks talked to `localhost` and ran without Redis.

The API task definition now takes its Redis connection from the Redis stack
(`experimentation-redis-<env>`), as plain environment, not secrets:

| Variable | Value |
|----------|-------|
| `REDIS_HOST` | the replication group's **primary** endpoint address |
| `REDIS_PORT` | the primary endpoint's port |
| `REDIS_SSL` | `true` |

The replication group has in-transit encryption on, so it refuses a plaintext
connection; `REDIS_SSL=true` makes every Redis client the application builds
connect over TLS (`ssl=True`). It defaults to `false`, for the plaintext
`redis:7` used locally and in CI. The replication group has no AUTH token, so
there is no password to store: `REDIS_PASSWORD` stays unset.

Redis is optional to the application: without it the rate limiter falls back
to per-task memory and the caches are skipped, and `/health/ready` still
answers 200 unless `REDIS_REQUIRED=true`. So a Redis the tasks cannot reach (a
TLS failure, say) does **not** fail a deployment by itself. Two things exist to
catch it, and the first staging deploy uses one of them:

- set `REDIS_REQUIRED=true` in staging, so readiness -- the ALB health check --
  fails without Redis; or
- read `checks.redis.status` from the `/health/ready` body, which is
  `healthy` or `unhealthy` in every environment (production shows the status
  only, not the error).

This change sets neither: the deployed task keeps the default,
`REDIS_REQUIRED=false`.

### Cognito Configuration

Replace the placeholder values with your actual Cognito user pool ID and app client ID:

```bash
aws secretsmanager create-secret \
  --name /prod/experimentation/cognito-config \
  --description "AWS Cognito user pool configuration for the experimentation platform" \
  --secret-string '{
    "user_pool_id": "us-west-2_XXXXXXXXX",
    "client_id": "XXXXXXXXXXXXXXXXXXXXXXXXXX",
    "region": "us-west-2"
  }' \
  --tags '[{"Key":"Environment","Value":"production"},{"Key":"Service","Value":"experimently"}]'
```

### First Superuser Password

The bootstrap creates the first administrator with this password. It has no
usable default: `FIRST_SUPERUSER_PASSWORD` falls back to `admin`, which the
production settings reject outright — without this secret the container exits
before uvicorn binds, on **either** profile.

```bash
SUPERUSER_PASSWORD=$(python3 -c "import secrets; print(secrets.token_urlsafe(24))")

aws secretsmanager create-secret \
  --name /prod/experimentation/first-superuser-password \
  --description "Password for the first administrator account (FIRST_SUPERUSER_PASSWORD)" \
  --secret-string "$SUPERUSER_PASSWORD" \
  --tags '[{"Key":"Environment","Value":"production"},{"Key":"Service","Value":"experimently"}]'
```

### Compliance Audit HMAC Key (`profile: full` only)

Signs the SOC 2 / ISO 27001 compliance audit log (HMAC-SHA256). Only module
code reads it, and `modules.register(hooks)` builds those settings as its first
step: a **full** deployment without this secret fails the registration, so the
API refuses to start and every `alembic` command fails with it. A `core`
deployment never reads it and does not need the secret at all.

```bash
AUDIT_HMAC_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")

aws secretsmanager create-secret \
  --name /prod/experimentation/audit-hmac-key \
  --description "HMAC-SHA256 key signing the compliance audit log (AUDIT_HMAC_KEY)" \
  --secret-string "$AUDIT_HMAC_KEY" \
  --tags '[{"Key":"Environment","Value":"production"},{"Key":"Service","Value":"experimently"}]'
```

Rotating it does not invalidate old rows, but signatures made with the previous
key no longer verify — re-verify or re-sign before rotating.

### Verify All Secrets Exist

```bash
aws secretsmanager list-secrets \
  --filters Key=name,Values=/prod/experimentation/ \
  --query 'SecretList[*].{Name:Name,ARN:ARN,LastChanged:LastChangedDate}' \
  --output table
```

`Deploy to Production` checks for `jwt-secret` and
`first-superuser-password`, plus `audit-hmac-key` for the `full` profile,
before it builds anything ("Required secrets exist for this profile").
`cognito-config` may also be listed; nothing in the deployment reads it. The
database credentials are not under this prefix: they are the database stack's
`experimentation-database-<env>-aurora-credentials`. Nor is Redis: see
[Redis: nothing to create](#redis-nothing-to-create).
---

## How Secrets Are Injected at Runtime

The ECS task definition references secrets by ARN. At container start, ECS fetches the current secret value from Secrets Manager and injects it as an environment variable. The container process reads the environment variable normally — it never calls Secrets Manager directly.

Example CDK task definition configuration (from `infrastructure/cdk/stacks/compute_stack.py`):

```python
# The ECS task role must have:
#   secretsmanager:GetSecretValue on arn:aws:secretsmanager:*:*:secret:/prod/experimentation/*
task_definition.add_container(
    "ExperimentationBackend",
    image=ecs.ContainerImage.from_ecr_repository(repo, tag=image_tag),
    environment={
        "APP_ENV": "production",
        "LOG_LEVEL": "INFO",
        "PYTHONUNBUFFERED": "1",
        "POSTGRES_DB": "experimentation",
        "POSTGRES_SCHEMA": "experimentation",
        # Not secrets: the Redis stack's primary endpoint, spoken to over TLS.
        "REDIS_HOST": redis_stack.primary_host,
        "REDIS_PORT": redis_stack.primary_port,
        "REDIS_SSL": "true",
    },
    secrets={
        # The secret the database stack generated Aurora's credentials into.
        "POSTGRES_USER": ecs.Secret.from_secrets_manager(
            db_credentials, field="username"
        ),
        "POSTGRES_PASSWORD": ecs.Secret.from_secrets_manager(
            db_credentials, field="password"
        ),
        "JWT_SECRET": ecs.Secret.from_secrets_manager(
            secretsmanager.Secret.from_secret_name_v2(
                stack, "JwtSecret", "/prod/experimentation/jwt-secret"
            )
        ),
        "COGNITO_CONFIG": ecs.Secret.from_secrets_manager(
            secretsmanager.Secret.from_secret_name_v2(
                stack, "CognitoConfig", "/prod/experimentation/cognito-config"
            )
        ),
    },
)
```

The application reads these as standard environment variables:

```python
# backend/app/core/config.py
import os

POSTGRES_PASSWORD = os.environ["POSTGRES_PASSWORD"]  # from the Aurora-generated secret
JWT_SECRET = os.environ["JWT_SECRET"]            # from /prod/experimentation/jwt-secret
REDIS_HOST = os.environ["REDIS_HOST"]            # the Redis stack's primary endpoint
```

---

## Secret Rotation Schedule

| Secret | Rotation Frequency | Method | Requires Restart |
|--------|-------------------|--------|-----------------|
| `experimentation-database-prod-aurora-credentials` | 180 days | Secrets Manager Lambda rotation (single-user) | Yes: ECS injects it when a task starts |
| `/prod/experimentation/jwt-secret` | 90 days | Manual rotation (see below) | Yes (force ECS restart) |
| `/prod/experimentation/cognito-config` | On Cognito pool change | Manual update | Yes |
| GitHub Actions deployment secrets | 365 days | Manual (GitHub Settings) | N/A |

### Configure Automatic DB Password Rotation

```bash
# Enable automatic rotation (runs every 180 days via Lambda)
aws secretsmanager rotate-secret \
  --secret-id experimentation-database-prod-aurora-credentials \
  --rotation-lambda-arn arn:aws:lambda:us-west-2:ACCOUNT:function:SecretsManagerRDSPostgreSQLRotationSingleUser \
  --rotation-rules AutomaticallyAfterDays=180

# Verify rotation is enabled
aws secretsmanager describe-secret \
  --secret-id experimentation-database-prod-aurora-credentials \
  --query '{RotationEnabled:RotationEnabled,RotationLambdaARN:RotationLambdaARN,LastRotatedDate:LastRotatedDate}'
```

The rotation Lambda changes the master password on the cluster and in the secret together. Running tasks keep the value ECS injected when they started, so force a new deployment after a rotation.

---

## Emergency Secret Rotation

Use these procedures when a secret is known or suspected to be compromised.

### Rotate JWT Secret Immediately

Rotating the JWT secret invalidates all active sessions immediately. All users will be logged out and must re-authenticate.

```bash
# Step 1: Generate a new JWT secret
NEW_JWT_SECRET=$(openssl rand -base64 48)

# Step 2: Update the secret value in Secrets Manager
aws secretsmanager put-secret-value \
  --secret-id /prod/experimentation/jwt-secret \
  --secret-string "$NEW_JWT_SECRET"

# Step 3: Force ECS service to restart and pick up the new secret
# (New tasks fetch the new secret value at startup)
aws ecs update-service \
  --cluster experimentation-prod \
  --service experimentation-backend-prod \
  --force-new-deployment

# Step 4: Wait for stabilization
aws ecs wait services-stable \
  --cluster experimentation-prod \
  --services experimentation-backend-prod

echo "JWT secret rotated. All existing sessions are now invalid."
```

### Rotate Database Password Immediately

# Step 1: Generate new password. token_urlsafe uses only letters, digits, `-`
# and `_`, none of which Aurora refuses in a master password.
# master password, so use a URL-safe alphabet.
NEW_DB_PASSWORD=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")

# Step 2: Set it on the cluster FIRST
aws rds modify-db-cluster \
  --db-cluster-identifier <the cluster in experimentation-database-prod> \
  --master-user-password "$NEW_DB_PASSWORD" \
  --apply-immediately

# Step 3: Put the same password in the database stack's secret (the tasks read
# its `username` and `password` fields)
aws secretsmanager put-secret-value \
  --secret-id experimentation-database-prod-aurora-credentials \
  --secret-string "$(python3 -c 'import json, sys; print(json.dumps({"username": "postgres", "password": sys.argv[1]}))' "$NEW_DB_PASSWORD")"

# Step 4: Force ECS restart to reconnect with new credentials
aws ecs update-service \
  --cluster experimentation-prod \
  --service experimentation-backend-prod \
  --force-new-deployment

aws ecs wait services-stable \
  --cluster experimentation-prod \
  --services experimentation-backend-prod
```

### Rotate Compromised API Key (Application-Level)

For application-level API keys managed by the platform itself:

```bash
# Step 1: Revoke the compromised key immediately via direct DB update
# (Do not wait for the API — the key may be actively abused)
# Connect to Aurora and run:
# UPDATE experimentation.api_keys SET is_active = false WHERE key = 'eptk_XXXXXXXXXXXX';

# Step 2: Issue a new key to the legitimate owner via the API
curl -X POST \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "Replacement key for owner X", "scopes": ["tracking:write"]}' \
  https://api.experimentation.example.com/api/v1/api-keys

# Step 3: Notify the owner of the new key via secure channel (not Slack or email)

# Step 4: Audit all requests made with the compromised key in CloudWatch
aws logs filter-log-events \
  --log-group-name /experimentation-platform/api \
  --filter-pattern '"api_key_prefix":"eptk_XXXXX"' \
  --start-time $(date -u -d '7 days ago' +%s000)
```

If the key may have been exposed through a vulnerability in Experimently itself, report it privately as [SECURITY.md](https://github.com/getexperimently/experimently/blob/main/SECURITY.md) describes; see [Responding to an incident on your deployment](../security/incident-response.md).

---

## IAM Permissions for Secret Access

The ECS task execution role must have the following policy attached to read secrets at container startup:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowSecretsAccess",
      "Effect": "Allow",
      "Action": [
        "secretsmanager:GetSecretValue",
        "secretsmanager:DescribeSecret"
      ],
      "Resource": "arn:aws:secretsmanager:us-west-2:ACCOUNT_ID:secret:/prod/experimentation/*"
    },
    {
      "Sid": "AllowKMSDecrypt",
      "Effect": "Allow",
      "Action": [
        "kms:Decrypt",
        "kms:GenerateDataKey"
      ],
      "Resource": "arn:aws:kms:us-west-2:ACCOUNT_ID:key/EXPERIMENTATION-KMS-KEY-ID"
    }
  ]
}
```

Verify the task execution role has this policy:

```bash
aws iam list-attached-role-policies \
  --role-name ExperimentationECSTaskExecutionRole \
  --query 'AttachedPolicies[*].PolicyName'
```

---

## Secrets Audit

Quarterly, verify:

1. No secrets in application code:

```bash
# Search for potential hardcoded secrets in Python files
grep -r "password\s*=\s*['\"]" backend/ --include="*.py" | grep -v "test\|mock\|fixture\|example"
grep -r "secret\s*=\s*['\"]" backend/ --include="*.py" | grep -v "test\|mock\|fixture\|example"
```

2. All secrets in Secrets Manager have been accessed recently (unused secrets may indicate a configuration error):

```bash
aws secretsmanager list-secrets \
  --filters Key=name,Values=/prod/experimentation/ \
  --query 'SecretList[*].{Name:Name,LastAccessed:LastAccessedDate,LastChanged:LastChangedDate}'
```

3. Rotation schedule is being met — no secret exceeds its rotation window:

```bash
aws secretsmanager describe-secret \
  --secret-id /prod/experimentation/jwt-secret \
  --query '{LastRotated:LastRotatedDate,RotationEnabled:RotationEnabled}'
```

---

## Staging Secrets

Staging uses separate secrets under `/staging/experimentation/` with the same structure. Staging secrets use weaker but non-production values and are safe to rotate independently.

```bash
# Create staging secrets (same structure, different values). The database
# credentials are generated by experimentation-database-staging.
aws secretsmanager create-secret \
  --name /staging/experimentation/jwt-secret \
  --secret-string "$(openssl rand -base64 32)"
```

Never copy production secrets to staging. Never use staging secrets in production.
