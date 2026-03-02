# Secrets Management — Experimentation Platform

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

### Database Password

```bash
# Generate a secure 32-character password
DB_PASSWORD=$(openssl rand -base64 32)

aws secretsmanager create-secret \
  --name /prod/experimentation/db-password \
  --description "Aurora PostgreSQL password for the experimentation application user" \
  --secret-string "$DB_PASSWORD" \
  --tags '[{"Key":"Environment","Value":"production"},{"Key":"Service","Value":"experimentation-platform"}]'

# Verify it was created
aws secretsmanager describe-secret --secret-id /prod/experimentation/db-password \
  --query '{Name:Name,ARN:ARN,CreatedDate:CreatedDate}'
```

Note: After creating the secret, you must also set this password on the Aurora database user:

```sql
-- Connect to Aurora as the master user and run:
ALTER USER experimentation_app WITH PASSWORD 'the-same-password-you-stored-in-secrets-manager';
```

### JWT Signing Secret

The JWT secret must be at least 32 characters. Using 48 characters provides adequate security margin.

```bash
JWT_SECRET=$(openssl rand -base64 48)

aws secretsmanager create-secret \
  --name /prod/experimentation/jwt-secret \
  --description "JWT token signing secret for the experimentation platform API" \
  --secret-string "$JWT_SECRET" \
  --tags '[{"Key":"Environment","Value":"production"},{"Key":"Service","Value":"experimentation-platform"}]'
```

### Redis Connection URL

Replace `REDIS_AUTH_TOKEN` with the actual ElastiCache auth token and the hostname with your ElastiCache primary endpoint:

```bash
# Get the ElastiCache primary endpoint
aws elasticache describe-replication-groups \
  --replication-group-id experimentation-redis-prod \
  --query 'ReplicationGroups[0].NodeGroups[0].PrimaryEndpoint.Address'

# Get the ElastiCache auth token (if configured during cluster creation)
# Or generate one:
REDIS_TOKEN=$(openssl rand -base64 24)

aws secretsmanager create-secret \
  --name /prod/experimentation/redis-url \
  --description "Redis connection URL for ElastiCache (includes auth token)" \
  --secret-string "redis://:${REDIS_TOKEN}@experimentation-redis-prod.XXXXX.cache.amazonaws.com:6379/0" \
  --tags '[{"Key":"Environment","Value":"production"},{"Key":"Service","Value":"experimentation-platform"}]'
```

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
  --tags '[{"Key":"Environment","Value":"production"},{"Key":"Service","Value":"experimentation-platform"}]'
```

### Verify All Secrets Exist

```bash
aws secretsmanager list-secrets \
  --filters Key=name,Values=/prod/experimentation/ \
  --query 'SecretList[*].{Name:Name,ARN:ARN,LastChanged:LastChangedDate}' \
  --output table
```

Expected output: 4 secrets — `db-password`, `jwt-secret`, `redis-url`, `cognito-config`.

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
    },
    secrets={
        "DB_PASSWORD": ecs.Secret.from_secrets_manager(
            secretsmanager.Secret.from_secret_name_v2(
                stack, "DbPassword", "/prod/experimentation/db-password"
            )
        ),
        "JWT_SECRET": ecs.Secret.from_secrets_manager(
            secretsmanager.Secret.from_secret_name_v2(
                stack, "JwtSecret", "/prod/experimentation/jwt-secret"
            )
        ),
        "REDIS_URL": ecs.Secret.from_secrets_manager(
            secretsmanager.Secret.from_secret_name_v2(
                stack, "RedisUrl", "/prod/experimentation/redis-url"
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

DB_PASSWORD = os.environ["DB_PASSWORD"]          # from /prod/experimentation/db-password
JWT_SECRET = os.environ["JWT_SECRET"]            # from /prod/experimentation/jwt-secret
REDIS_URL = os.environ.get("REDIS_URL", "")      # from /prod/experimentation/redis-url
```

---

## Secret Rotation Schedule

| Secret | Rotation Frequency | Method | Requires Restart |
|--------|-------------------|--------|-----------------|
| `/prod/experimentation/db-password` | 180 days | Secrets Manager Lambda rotation (dual-user strategy) | No (connection pool reconnects) |
| `/prod/experimentation/jwt-secret` | 90 days | Manual rotation (see below) | Yes (force ECS restart) |
| `/prod/experimentation/redis-url` (auth token) | 365 days | Manual (ElastiCache token rotation) | Yes |
| `/prod/experimentation/cognito-config` | On Cognito pool change | Manual update | Yes |
| GitHub Actions deployment secrets | 365 days | Manual (GitHub Settings) | N/A |

### Configure Automatic DB Password Rotation

```bash
# Enable automatic rotation (runs every 180 days via Lambda)
aws secretsmanager rotate-secret \
  --secret-id /prod/experimentation/db-password \
  --rotation-lambda-arn arn:aws:lambda:us-west-2:ACCOUNT:function:SecretsManagerRDSPostgreSQLRotationSingleUser \
  --rotation-rules AutomaticallyAfterDays=180

# Verify rotation is enabled
aws secretsmanager describe-secret \
  --secret-id /prod/experimentation/db-password \
  --query '{RotationEnabled:RotationEnabled,RotationLambdaARN:RotationLambdaARN,LastRotatedDate:LastRotatedDate}'
```

The Secrets Manager rotation Lambda uses the dual-user strategy: it creates a new password for the `experimentation_app_new` user, verifies connectivity, then updates the primary user — ensuring zero-downtime rotation.

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

```bash
# Step 1: Generate new password
NEW_DB_PASSWORD=$(openssl rand -base64 32)

# Step 2: Update the database user password in Aurora FIRST
# (Do this before updating Secrets Manager to avoid a gap)
# Connect to Aurora as master user and run:
# ALTER USER experimentation_app WITH PASSWORD 'new-password';

# Step 3: Update Secrets Manager with the new password
aws secretsmanager put-secret-value \
  --secret-id /prod/experimentation/db-password \
  --secret-string "$NEW_DB_PASSWORD"

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

See `docs/security/incident-response-plan.md` Runbook 2 for the full compromised API key response procedure.

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
# Create staging secrets (same structure, different values)
aws secretsmanager create-secret \
  --name /staging/experimentation/db-password \
  --secret-string "$(openssl rand -base64 24)"

aws secretsmanager create-secret \
  --name /staging/experimentation/jwt-secret \
  --secret-string "$(openssl rand -base64 32)"
```

Never copy production secrets to staging. Never use staging secrets in production.
