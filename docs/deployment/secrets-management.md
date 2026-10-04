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
to per-task memory (and retries Redis every 30 s) and the caches are skipped, and `/health/ready` still
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

Deploy checks the secrets by the references ECS will use, before it builds
anything ("Every secret the task definitions reference exists"). It reads
every `valueFrom` in the API's, the migration's and the dashboard's task
definitions, refuses any that is not a complete ARN in the environment's
account and region (a partial ARN, one that stops at the name, is refused
before any Secrets Manager call), requires the API and migration task
definitions to reference `jwt-secret` and `first-superuser-password`, plus
`audit-hmac-key` for the `full` profile, and then runs `describe-secret` on
each complete ARN. Its log names each secret by name only, never by ARN.
`cognito-config` may also be listed; nothing in the deployment reads it. The
database credentials are not under this prefix: they are the database stack's
`experimentation-database-<env>-aurora-credentials`. Nor is Redis: see
[Redis: nothing to create](#redis-nothing-to-create).

### Give the CDK each secret's complete ARN

The task definitions name each secret by its **complete ARN**, which ends in a
six-character suffix Secrets Manager adds when the secret is created
(`.../secret:/<env>/experimentation/jwt-secret-<suffix>`). The suffix cannot be
worked out from the name, so `cdk synth`, `cdk diff`, `cdk deploy` and
`cdk destroy` take the three ARNs from the environment, in **every**
environment (`dev` and `demo` too):

| Variable | Secret | Needed |
|----------|--------|--------|
| `JWT_SECRET_ARN` | `/<env>/experimentation/jwt-secret` | always |
| `FIRST_SUPERUSER_PASSWORD_SECRET_ARN` | `/<env>/experimentation/first-superuser-password` | always |
| `AUDIT_HMAC_KEY_SECRET_ARN` | `/<env>/experimentation/audit-hmac-key` | `profile: full` only |

Read them (read-only) and export them in the shell that runs the CDK, with
the region the stacks deploy to. The third is for `profile: full` only:

```bash
ENV=staging
export JWT_SECRET_ARN=$(aws secretsmanager describe-secret \
  --secret-id "/$ENV/experimentation/jwt-secret" --query ARN --output text)
export FIRST_SUPERUSER_PASSWORD_SECRET_ARN=$(aws secretsmanager describe-secret \
  --secret-id "/$ENV/experimentation/first-superuser-password" --query ARN --output text)
export AUDIT_HMAC_KEY_SECRET_ARN=$(aws secretsmanager describe-secret \
  --secret-id "/$ENV/experimentation/audit-hmac-key" --query ARN --output text)
```

Synth refuses a value that is missing, that stops at the name (a *partial*
ARN, which ECS cannot resolve), that is for a different environment
(`/prod/...` in staging), that is in a region or account other than the
stack's, or that names another of the three secrets.
The refusal names the variable and prints the command above; it never prints
the value, because an ARN carries the account ID. For the same reason, keep
these values out of issues, pull requests and chat.

**Recreating a secret changes its ARN.** Deleting and re-creating
`/<env>/experimentation/jwt-secret` gives it a new suffix: update the input and
run `cdk deploy` again, or the next task start fails with
`ResourceNotFoundException`. Changing a secret's *value*
(`put-secret-value`, or rotation) keeps its ARN and needs nothing here.
---

## How Secrets Are Injected at Runtime

The ECS task definition references secrets by their complete ARN. At container start, ECS fetches the current secret value from Secrets Manager and sets it as an environment variable. The container process reads the environment variable normally — it never calls Secrets Manager directly.

A shortened version of the API task definition in
`infrastructure/cdk/stacks/fargate_service_stack.py` (the migration task in
`migration_task_stack.py` imports the same secrets the same way). The ARNs are
the synth inputs [above](#give-the-cdk-each-secrets-complete-arn), which
`app.py` checks and passes in as `secret_arns`:

```python
# Each secret by its COMPLETE ARN. A secret imported by name renders a partial
# ARN into valueFrom, and Secrets Manager does not resolve it, so no task
# would start.
jwt_secret = secretsmanager.Secret.from_secret_complete_arn(
    stack, "JwtSecret", secret_arns["JWT_SECRET_ARN"]
)
superuser_secret = secretsmanager.Secret.from_secret_complete_arn(
    stack, "SuperuserPasswordSecret", secret_arns["FIRST_SUPERUSER_PASSWORD_SECRET_ARN"]
)

# The execution role may read exactly these secrets, by the same ARNs.
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
        "SECRET_KEY": ecs.Secret.from_secrets_manager(jwt_secret),
        "FIRST_SUPERUSER_PASSWORD": ecs.Secret.from_secrets_manager(superuser_secret),
        # profile: full adds AUDIT_HMAC_KEY from AUDIT_HMAC_KEY_SECRET_ARN.
    },
)
```

The application reads these as standard environment variables:

```python
# backend/app/core/config.py
import os

POSTGRES_PASSWORD = os.environ["POSTGRES_PASSWORD"]  # from the Aurora-generated secret
SECRET_KEY = os.environ["SECRET_KEY"]            # from /prod/experimentation/jwt-secret
REDIS_HOST = os.environ["REDIS_HOST"]            # the Redis stack's primary endpoint
```

---

## Secret Rotation Schedule

| Secret | Rotation Frequency | Method | Requires Restart |
|--------|-------------------|--------|-----------------|
| `experimentation-database-prod-aurora-credentials` | 180 days | Secrets Manager Lambda rotation (single-user) | Yes: ECS injects it when a task starts |
| `/prod/experimentation/jwt-secret` | 90 days | Manual rotation (see below) | Yes ([restart the API](#restart-the-api-on-its-current-release)) |
| `/prod/experimentation/cognito-config` | On Cognito pool change | Manual update | Yes |
| GitHub Actions deployment secrets | 365 days | Manual (GitHub Settings) | N/A |

### Configure Automatic DB Password Rotation

Enable automatic rotation (runs every 180 days via Lambda):

```bash
aws secretsmanager rotate-secret \
  --secret-id experimentation-database-prod-aurora-credentials \
  --rotation-lambda-arn arn:aws:lambda:us-west-2:ACCOUNT:function:SecretsManagerRDSPostgreSQLRotationSingleUser \
  --rotation-rules AutomaticallyAfterDays=180
```

Verify rotation is enabled:

```bash
aws secretsmanager describe-secret \
  --secret-id experimentation-database-prod-aurora-credentials \
  --query '{RotationEnabled:RotationEnabled,RotationLambdaARN:RotationLambdaARN,LastRotatedDate:LastRotatedDate}'
```

The rotation Lambda changes the master password on the cluster and in the secret together. Running tasks keep the value ECS read for them when they started, so restart the API after a rotation: [Restart the API on its current release](#restart-the-api-on-its-current-release). Not `aws ecs update-service --force-new-deployment`: the API's service is controlled by CodeDeploy, which that call is not for (below).

---

## Emergency Secret Rotation

Use these procedures when a secret is known or suspected to be compromised.

Each one ends by restarting the API, which CodeDeploy refuses for about an hour after any deploy
([A deployment is still active](#a-deployment-is-still-active)). Check that first, with the
Rollback Runbook's [Step 1](rollback-runbook.md#restart-the-api-on-the-revision-it-is-serving),
before you change the secret: from the change on, any task that starts uses the new value while
the rest keep the old one.

### Rotate JWT Secret Immediately

Rotating the JWT secret invalidates every token the API signed itself: local sign-in tokens and
the tokens it issues after an SSO sign-in. Tokens issued by Cognito are not signed with it and
are not affected. It does **not** take effect at once. Tasks that started before the change keep
accepting tokens signed with the old secret until the restart's traffic shift has completed;
[How long the old value keeps working](#how-long-the-old-value-keeps-working) says how long that
is. After the shift, users of those tokens must sign in again.

Step 1: Generate a new JWT secret:

```bash
NEW_JWT_SECRET=$(openssl rand -base64 48)
```

Step 2: Update the secret value in Secrets Manager:

```bash
aws secretsmanager put-secret-value \
  --secret-id /prod/experimentation/jwt-secret \
  --secret-string "$NEW_JWT_SECRET"
```

Step 3: Restart the API so new tasks read the new value:
[Restart the API on its current release](#restart-the-api-on-its-current-release). The rotation
is done when that procedure confirms the new revision is serving, not when the secret is
updated.

### Rotate Database Password Immediately

Step 1: Generate a new password. `token_urlsafe` uses only letters, digits, `-` and `_`, none of which Aurora refuses in a master password:

```bash
NEW_DB_PASSWORD=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
```

Step 2: Set it on the cluster FIRST:

```bash
aws rds modify-db-cluster \
  --db-cluster-identifier <the cluster in experimentation-database-prod> \
  --master-user-password "$NEW_DB_PASSWORD" \
  --apply-immediately
```

Step 3: Put the same password in the database stack's secret (the tasks read its `username` and `password` fields):

```bash
aws secretsmanager put-secret-value \
  --secret-id experimentation-database-prod-aurora-credentials \
  --secret-string "$(python3 -c 'import json, sys; print(json.dumps({"username": "postgres", "password": sys.argv[1]}))' "$NEW_DB_PASSWORD")"
```

Step 4: Restart the API so the tasks reconnect with the new credentials:
[Restart the API on its current release](#restart-the-api-on-its-current-release). Until its
traffic shift completes, the running tasks keep the old password: connections they already hold
keep working, and any new connection they open is refused.

### Rotate Compromised API Key (Application-Level)

For application-level API keys managed by the platform itself:

Step 1: Revoke the compromised key. Only its SHA-256 hash is stored, so hash the leaked key first:

```bash
KEY_HASH=$(printf '%s' "$LEAKED_KEY" | shasum -a 256 | cut -d' ' -f1)
```

Then, connected to Aurora, deactivate that row (every request with the key then gets 401):

```sql
UPDATE experimentation.api_keys SET is_active = false WHERE key = '<KEY_HASH>' RETURNING id, name, user_id;
```

Step 2: Issue a new key to the legitimate owner via the API:

```bash
curl -X POST \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "Replacement key for owner X"}' \
  https://api.experimentation.example.com/api/v1/api-keys
```

Step 3: Notify the owner of the new key through a secure channel (not Slack or email).

Step 4: Audit all requests made with the compromised key in CloudWatch:

```bash
aws logs filter-log-events \
  --log-group-name /experimentation-platform/api \
  --filter-pattern '"api_key_prefix":"eptk_XXXXX"' \
  --start-time $(date -u -d '7 days ago' +%s000)
```

The key's owner, or an ADMIN, can instead delete it through the API with `DELETE /api/v1/api-keys/{id}`, or from **Admin → API Keys** in the dashboard. Neither the plaintext nor its `eptk_xxxx` prefix is stored, so identify the key by its name, or get its `id` from the `RETURNING` clause above. `KEY_HASH` is the hex SHA-256 of the key, which is what the platform stores (`hash_api_key` in `backend/app/core/security.py`).

If the key may have been exposed through a vulnerability in Experimently itself, report it privately as [SECURITY.md](https://github.com/getexperimently/experimently/blob/main/SECURITY.md) describes; see [Responding to an incident on your deployment](../security/incident-response.md).

---

## Restart the API on its current release

ECS reads each secret into a task when the task starts. A changed value reaches the API only
through new tasks, and the API's service is controlled by CodeDeploy, so new tasks come from a
CodeDeploy deployment. Not `aws ecs update-service --force-new-deployment`, the usual way to
restart an ECS service: on a CodeDeploy-controlled service, UpdateService may change only the
desired count, the deployment configuration, the health check grace period, task placement and
tag settings, and a forced new deployment is not among them.

### With the Deploy workflow

The preferred way: run **Deploy** again with the release that is already serving.

1. Find that release. The API's revision names its image by digest; the repository gives the
   tag (`vX.Y.Z-<profile>`) for it:

    ```{.bash skip reason="aws: reads the real service, task definition and repository"}
    CURRENT=$(aws ecs describe-services \
      --cluster "experimentation-$ENV" \
      --services "experimentation-backend-$ENV" \
      --query "services[0].taskSets[?status=='PRIMARY'].taskDefinition" \
      --output text)
    IMAGE=$(aws ecs describe-task-definition --task-definition "$CURRENT" \
      --query "taskDefinition.containerDefinitions[?name=='backend'].image | [0]" \
      --output text)
    aws ecr describe-images --repository-name experimentation-platform/backend \
      --image-ids imageDigest="${IMAGE#*@}" \
      --query "imageDetails[0].imageTags" --output text
    ```

2. **Actions → Deploy → Run workflow** from `main`, with `environment`, `version` the tag's
   `vX.Y.Z` part and `profile` its profile part.
3. The environment's required reviewer approves the run, as for any deploy. Nothing in AWS has
   changed before that.

With a release already deployed, the run (the [deployment guide](deployment-guide.md#3-every-deploy)
has every step):

- refuses, before changing anything, while an earlier CodeDeploy deployment is still active or
  an API alarm is firing;
- reuses the image already in the repository (`already exists (...): reusing it`) instead of
  building one;
- takes a database snapshot and runs the migration task, which has nothing new to apply;
- registers a new API revision naming the same image and creates a CodeDeploy deployment with
  the deployment group's canary;
- approves the traffic shift itself once every new task is healthy: 10% of traffic moves to the
  new tasks, then the rest fifteen minutes later;
- succeeds only when the new revision is the PRIMARY task set and the `/api/*` rule forwards to
  its target group, then sends a smoke request and rolls the dashboard onto a new revision of
  its own unchanged image.

### By hand

When the workflow is not available:
[Restart the API on the revision it is serving](rollback-runbook.md#restart-the-api-on-the-revision-it-is-serving)
in the Rollback Runbook. It registers a copy of the serving revision, creates the deployment
all at once, approves the shift and confirms the new revision is serving, with no canary.

### A deployment is still active

CodeDeploy accepts one deployment per deployment group at a time, and every deploy's deployment
stays active for about an hour after its traffic shift while the group keeps the old task set.
Inside that hour Deploy refuses with `A deployment is still active`, naming the deployment and
roughly how long it has left, and a deployment created by hand is refused too. Wait for it to
end and restart then. Stopping it does not help: it moves traffic back to the task set kept from
before that deploy, whose tasks still hold the old value. The Rollback Runbook's
[Step 1](rollback-runbook.md#restart-the-api-on-the-revision-it-is-serving) gives the one faster
path and what it costs.

### How long the old value keeps working

Tasks keep the value they started with. Until the traffic shift completes, some or all requests
still reach tasks that started before the change:

- **With Deploy**: from the change until the end of the canary, which is the approval of the
  run, the snapshot and the migration, starting the new tasks, and fifteen minutes with 90% of
  traffic still on the old ones: at least the canary's fifteen minutes, plus however long the
  approval and the steps before it take.
- **By hand**: until the all-at-once shift, a few minutes after `continue-deployment`.
- **During that time**, a task that starts in the serving set (a scale-out, or a replacement for
  a task that stopped) reads the new value. For the JWT secret, a token one task signed can be
  refused by another until the shift.
- **For an hour after the shift** the old tasks get no traffic but are kept. An alarm, or a stop
  with auto-rollback, in that hour moves traffic back to them, and with it the old value.

---

## IAM Permissions for Secret Access

The ECS task execution role must be able to read the secrets at container startup. The CDK stacks grant
`secretsmanager:GetSecretValue` on exactly the complete ARNs the task definition names (the synth
inputs above) and nothing wider. A hand-made role outside the CDK needs at least this:

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

Search for potential hardcoded secrets in Python files:

```bash
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

Create staging secrets (same structure, different values). The database credentials are generated by experimentation-database-staging:

```bash
aws secretsmanager create-secret \
  --name /staging/experimentation/jwt-secret \
  --secret-string "$(openssl rand -base64 32)"
```

Never copy production secrets to staging. Never use staging secrets in production.
