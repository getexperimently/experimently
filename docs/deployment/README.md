# Deployment Documentation

Operational documentation for deploying and operating Experimently on AWS.
There are two environments, **`staging`** and **`prod`**, and one path for
both: the same stacks (`ENVIRONMENT=<env> cdk deploy`) and the same three
workflows, each dispatched with `environment: staging` or `environment: prod`.
Below, `<env>` is one of those two words, spelled exactly so -- the CDK, the
GitHub environments and the secret paths all use it.

---

## Document Index

| Document | Audience | Description |
|----------|----------|-------------|
| [Deployment Guide](deployment-guide.md) | DevOps / Engineers | The ordered first-deploy checklist, then every deploy after it |
| [IAM Permissions](iam-permissions.md) | Account administrators | The three identities, and the workflow role's generated policy |
| [Rollback Runbook](rollback-runbook.md) | On-call Engineers | How to roll back a deployment |
| [Disaster Recovery](disaster-recovery.md) | SRE / DevOps | DR scenarios, runbooks, and recovery procedures |
| [Secrets Management](secrets-management.md) | DevOps / Security | How secrets are stored, injected, and rotated |

---

## Before the first deploy

Every workflow refuses -- a red run, not a skipped one -- an environment that is
not configured. Per GitHub environment (**Settings → Environments →
`<env>`**), in this order:

1. **Protection first**: a required reviewer, and deployment branches limited
   to `main`. Do this before adding anything else: dispatching a workflow for
   an environment that does not exist creates it, unprotected.
2. **Variables**: `AWS_ACCOUNT_ID` (that environment's account, 12 digits) and
   `PUBLIC_BASE_URL` (the origin the stacks were deployed with, e.g.
   `https://app.example.com` -- the smoke test calls it).
3. **Secret**: `AWS_ROLE_ARN`, that environment's OIDC role
   ([IAM Permissions](iam-permissions.md)).

`SLACK_BOT_TOKEN` (repository secret, optional) posts to `#deployments`.

The AWS side -- IAM, certificate, ECR, secrets, stacks -- is the ordered
checklist in [the deployment guide](deployment-guide.md#1-before-the-first-deploy).

---

## Quick Reference

### Deploy

1. A release tag: release-please cuts them (`vX.Y.Z`). **Release Gate** runs on
   every push to `main`, so the tagged commit has a result; for a tag cut
   before that, run it on the tag: `gh workflow run release-gate.yml --ref vX.Y.Z`.
2. **Actions → Deploy → Run workflow**, from `main`: pick `environment`, type
   the tag as `version`, pick the `profile` (below).
3. Approve the run when the environment asks. There is one approval per
   deploy, and nothing in AWS has changed before it.
4. Read the run summary: it names what was built and deployed, and hands you
   the rollback line.

**How the traffic moves.** The deploy creates a CodeDeploy blue/green
deployment. When CodeDeploy reports it `Ready`, the deploy checks that every
target in the new task set's target group is healthy, as many as the task set
wants, and then approves the shift. The deployment group's canary sends 10%
of traffic to the new revision, waits five minutes, then sends the rest. The
run succeeds when the new revision is the API's PRIMARY task set **and** the
HTTPS listener's `/api/*` rule forwards to that task set's target group. The
summary then prints the live group and the `-c api_live_target_group=<blue|green>`
value the next `cdk deploy` of the Fargate stack needs.

> **The canary is timed only.** No alarm watches it, so nothing rolls back
> automatically on application errors. A release that answers `/health` and
> fails everywhere else still reaches 100% after five minutes. The response is
> **Rollback**, within the hour CodeDeploy keeps the previous task set. Alarm
> based rollback is tracked in #148 and is a prerequisite for the first
> production deploy, unless the founder waives it.

**One deploy per environment per hour.** After the shift, CodeDeploy keeps
the previous task set for an hour, and the deployment stays active that whole
time. CodeDeploy accepts no second deployment meanwhile, so a deploy
dispatched within the hour is refused before it changes anything. The
refusal names the deployment and roughly how long it has left. The deploy never
stops that deployment: stopping one whose traffic has shifted rolls back a
release that succeeded. Rollback does stop it, deliberately.

**One at a time per environment.** Deploy and Database Migration share a
concurrency group per environment and are never cancelled mid-run. GitHub keeps
at most one run *waiting* in a group: a newer dispatch that queues behind a
running deploy **replaces** an older one that was still waiting, which is then
cancelled without running. Rollback has its own group, so it never waits behind
a deploy.

Full procedure: [deployment-guide.md](deployment-guide.md)

#### Which profile?

`Deploy` asks for a `profile`, and the answer is a decision about what the
environment *is*, not a build detail:

| profile | image | compliance audit log |
|---------|-------|----------------------|
| `full` (default) | `backend/Dockerfile --target full`: `backend/` plus `modules/backend/` and the module-only dependencies | HMAC-SHA256 signed by the compliance module (`AuditSigningService`) |
| `core` | `--target core`: `backend/` only, no `modules/` directory at all | **unsigned** — `hooks.audit_signer` stays `NullAuditSigner`, every event is written with `hmac_signature = NULL`, and `verify()` reports those rows as intact |

Nothing at runtime flags the difference: `/health/ready` answers 200 either way
(it reports `profile`, it does not judge it) and `abort_if_modules_broken()`
only fires for a *broken* modules package, never for an absent one. So `core`
also requires ticking **`accept_unsigned_audit_log`**; the workflow refuses the
run otherwise, in its preflight, before anything assumes an AWS role.

The profile must also be the one the stacks were deployed with: a `full` image
needs `AUDIT_HMAC_KEY`, which only a full checkout's stacks inject. The deploy
reads both task-definition families and refuses a mismatch in either direction
before it builds anything.

`full` needs one secret `core` does not: **`/<env>/experimentation/audit-hmac-key`**
(→ `AUDIT_HMAC_KEY`). `modules.register(hooks)` builds the modules' settings as
its very first step and their validator rejects the shipped dev default in
staging and production, so a full image without it never registers the modules
— `abort_if_modules_broken()` refuses to start the API and
`require_modules_or_absent()` fails every `alembic` command, including the
migration task. The deploy's **"Required secrets exist for this profile"**
step checks for it (and for the two every profile needs) before it builds
anything. Create it with [secrets-management.md](secrets-management.md).

---

### Emergency Rollback

**Method 1 — GitHub Actions (preferred):** **Actions → Rollback**, from `main`:
`environment`, the `task_definition_arn` the deploy's run summary printed
(`experimentation-backend-<env>:<n>`), and a reason.

**Method 2 — AWS CLI:**

> The service has a **CODE_DEPLOY** deployment controller
> (`fargate_service_stack.py`), and ECS rejects a task-definition change
> through `UpdateService` on such a service — *"Unable to update task
> definition on services with a CODE_DEPLOY deployment controller"*. Rolling
> back means creating a CodeDeploy deployment that names the older revision —
> **and approving it**, because the deployment group parks for 30 minutes
> waiting for `ContinueDeployment` and then stops, which auto-rollback turns
> back into the revision you were rolling away from.
>
> That is three calls with an AppSpec in between, which is not something to
> assemble by hand during an incident. **Use Method 1.** If the workflow itself
> is unavailable, [rollback-runbook.md](rollback-runbook.md) Method 2 has the
> full sequence.

How to find the previous task definition, **with its image** — the revision
list alone is not enough, because CloudFormation also registers into this
family with a `bootstrap` image that may not exist in ECR (#82). A revision a
deploy registered names its image by digest (`…/backend@sha256:…`):

```bash
ENV=prod   # or staging
for arn in $(aws ecs list-task-definitions \
               --family-prefix "experimentation-backend-$ENV" \
               --sort DESC --max-results 5 \
               --query 'taskDefinitionArns' --output text); do
  printf '%s  %s\n' "$arn" "$(aws ecs describe-task-definition \
    --task-definition "$arn" \
    --query 'taskDefinition.containerDefinitions[?name==`backend`].image' \
    --output text)"
done
```

Full rollback procedure: [rollback-runbook.md](rollback-runbook.md)

---

### Database Migration

A deploy runs its own migration. **Actions → Database Migration** is for the
rest -- chiefly undoing one:

1. From `main`: `environment` (`staging` or `prod`), `direction` (`upgrade` or
   `downgrade`), `target` (`heads` to upgrade; a revision id or `-1` to
   downgrade -- never the singular `head`, which a full image refuses because it
   has two).
2. It runs with the image the API is **serving** (the PRIMARY task set), and
   refuses when nothing is serving yet. It snapshots the database first.
3. The task's log is printed in the run; it is also CloudWatch log group
   `/ecs/experimentation-migrate-<env>`.

---

### Health Checks

```bash
# Through the public origin (PUBLIC_BASE_URL). /health is readiness: it runs
# the database check, and it is what the load balancer probes.
curl -s https://app.example.com/health
# {"status": "...", "profile": "full", "version": "X.Y.Z", "environment": "...",
#  "checks": {"database": {"status": "..."}, ...}}

# The smoke test the deploy runs: a real route, unauthenticated.
curl -s https://app.example.com/api/v1/experiments/
# 401 {"detail":"Not authenticated"}

ENV=prod   # or staging
aws ecs describe-services \
  --cluster "experimentation-$ENV" \
  --services "experimentation-backend-$ENV" \
  --query "services[0].{Running:runningCount,Desired:desiredCount,Serving:taskSets[?status=='PRIMARY'].taskDefinition|[0]}"
```

---

## Names

Everything the workflows and the runbooks address, per environment. Where the
CDK generates a name, the stack publishes it as an output and the workflows
read it from there. `infrastructure/tests/test_workflow_names_exist.py` checks
every row with a resource type against a synth of `staging` and `prod`.

| What | Name | Resource type |
|------|------|---------------|
| ECS cluster | `experimentation-<env>` | `AWS::ECS::Cluster` |
| API service | `experimentation-backend-<env>` | `AWS::ECS::Service` |
| API task definition family | `experimentation-backend-<env>` | `AWS::ECS::TaskDefinition` |
| Migration task definition family | `experimentation-migrate-<env>` | `AWS::ECS::TaskDefinition` |
| Dashboard service | `experimentation-dashboard-<env>` | `AWS::ECS::Service` |
| API log group | `/ecs/experimentation-backend-<env>` | `AWS::Logs::LogGroup` |
| Migration log group | `/ecs/experimentation-migrate-<env>` | `AWS::Logs::LogGroup` |
| Dashboard log group | `/ecs/experimentation-dashboard-<env>` | `AWS::Logs::LogGroup` |
| CodeDeploy application | `experimentation-platform-<env>` | `AWS::CodeDeploy::Application` |
| CodeDeploy deployment group | `experimentation-<env>` | `AWS::CodeDeploy::DeploymentGroup` |
| Redis replication group | `experimentation-redis-<env>-redis` | `AWS::ElastiCache::ReplicationGroup` |
| Aurora credentials (generated) | `experimentation-database-<env>-aurora-credentials` | `AWS::SecretsManager::Secret` |
| Fargate stack | `experimentation-fargate-<env>` | stack |
| Database stack | `experimentation-database-<env>` | stack |
| Migrations stack | `experimentation-migrations-<env>` | stack |
| Aurora cluster identifier | generated: output `ClusterIdentifier` of `experimentation-database-<env>` | — |
| Task subnets and security group | outputs `TaskSubnets`, `TaskSecurityGroup` of `experimentation-fargate-<env>` | — |
| Secrets you create | `/<env>/experimentation/<name>` (Secrets Manager) | — |
| Parameters the stacks write | `/experimentation/<env>/...` (SSM -- the other order, #67) | — |
| API image | `experimentation-platform/backend:<tag>-<profile>`, run by digest; `:bootstrap` for `cdk deploy` | — |
| Dashboard image | `experimentation-platform/web:bootstrap` | — |
| GitHub environment | `staging`, `prod` | — |

There is no `:latest` and no bare `:<tag>`: each release is pushed once per
profile as `:<tag>-<profile>` (reused, not rebuilt, when the same release is
deployed again into the same account), and every task definition the workflows
register names the image **by digest**, so a later push to a tag cannot change
what a running environment starts. Staging and prod are meant to be separate
AWS accounts, each with its own ECR, so prod builds the release itself from the
tag: it runs the same release (tag, commit and profile; the deploy refuses an
image whose labels name another commit or profile), not the same digest
staging ran.

---

## Required AWS Secrets Manager Secrets

These secrets must exist before the Fargate and migrations stacks are deployed.
See [secrets-management.md](secrets-management.md) for creation commands.

| Secret Path | Injected as | Description |
|-------------|-------------|-------------|
| `/<env>/experimentation/jwt-secret` | `SECRET_KEY` | JWT signing secret (minimum 32 characters) |
| `/<env>/experimentation/first-superuser-password` | `FIRST_SUPERUSER_PASSWORD` | Password for the first administrator; the default `admin` is refused in staging and production |
| `/<env>/experimentation/audit-hmac-key` | `AUDIT_HMAC_KEY` | **`profile: full` only** — signs the compliance audit log; the modules refuse to register without it |

The database credentials are not in this table: `POSTGRES_USER` and
`POSTGRES_PASSWORD` come from the secret the database stack generates for
Aurora (`experimentation-database-<env>-aurora-credentials`), and
`POSTGRES_SERVER` from its writer endpoint. Nothing to create.

Every row is injected by the ECS task definitions
(`infrastructure/cdk/stacks/fargate_service_stack.py` and
`migration_task_stack.py`) and is one the application refuses to start without:
the image ships no `.env` file, so the task definition is the only source.
`Deploy` refuses the run if one is missing, before it builds anything.

Redis is not in this table: the API task takes `REDIS_HOST` and `REDIS_PORT`
from the Redis stack's primary endpoint and sets `REDIS_SSL=true`, because the
replication group refuses plaintext. Nothing to create; see
[Redis: nothing to create](secrets-management.md#redis-nothing-to-create),
which also says how the staging rehearsal proves the tasks really reach it
(`REDIS_REQUIRED=true`, or `checks.redis.status` in `/health/ready`).

---

## Infrastructure Stack Deployment Order

CDK stacks must be deployed in this order. Each stack depends on outputs from the previous.

These are stack **ids** — what `cdk deploy` takes, and what `cdk list` prints.

1. `experimentation-auth-<env>` — Cognito user pool, client and groups
2. `experimentation-vpc-<env>` — VPC, subnets, NAT gateways
3. `experimentation-dynamodb-<env>` — the five DynamoDB tables
4. `experimentation-database-<env>` — Aurora PostgreSQL cluster
5. `experimentation-redis-<env>` — ElastiCache Redis replication group
6. `experimentation-compute-<env>` — ECS cluster, task security group, database-access Lambda
7. `experimentation-monitoring-<env>` — CloudWatch dashboards, alarms, log groups
8. `experimentation-fargate-<env>` — Fargate services, ALB, CodeDeploy blue/green
9. `experimentation-migrations-<env>` — ECS task definition for Alembic (plural)

With `modules/` present, three more: `experimentation-dynamodb-counters-<env>`,
`experimentation-analytics-<env>` and `experimentation-glue-etl-<env>`.

Standing an environment up for the first time (CDK handles ordering):
```bash
cd infrastructure/cdk
ENVIRONMENT=staging cdk deploy --all --require-approval never
```

On an environment that is already running, deploy the Fargate stack on its own
with the pins the [deployment guide](deployment-guide.md) gives, never `--all`.

---

## Useful AWS CLI Commands

```bash
ENV=prod   # or staging

# Watch what is serving during a deployment: the PRIMARY task set moves,
# services[0].taskDefinition does not (it is frozen at CreateService).
watch -n 5 "aws ecs describe-services \
  --cluster experimentation-$ENV \
  --services experimentation-backend-$ENV \
  --query 'services[0].{Running:runningCount,Desired:desiredCount,Serving:taskSets[?status==\`PRIMARY\`].taskDefinition|[0]}'"

# Recent API errors
aws logs filter-log-events \
  --log-group-name "/ecs/experimentation-backend-$ENV" \
  --filter-pattern '"level":"ERROR"' \
  --start-time $(( ($(date +%s) - 900) * 1000 ))

# Aurora cluster status (its identifier is generated: read it from the stack)
CLUSTER=$(aws cloudformation describe-stacks --stack-name "experimentation-database-$ENV" \
  --query "Stacks[0].Outputs[?OutputKey=='ClusterIdentifier'].OutputValue" --output text)
aws rds describe-db-clusters --db-cluster-identifier "$CLUSTER" \
  --query 'DBClusters[0].{Status:Status,Endpoint:Endpoint,LatestRestorableTime:LatestRestorableTime}'
```

---

## Recovery Time Objectives

| Scenario | RTO | RPO | See |
|----------|-----|-----|-----|
| Single ECS task crash | ~60 seconds | 0 | DR Plan — Scenario 1 |
| All ECS tasks down | ~5 minutes | 0 | DR Plan — Scenario 2 |
| Application rollback | < 5 minutes | 0 | Rollback Runbook |
| Aurora primary failure | ~2 minutes | 0 | DR Plan — Scenario 3 |
| Aurora cluster restore from snapshot | ~30 minutes | 5 minutes | DR Plan — Scenario 4 |
| Full region failover | ~60 minutes | 5 minutes | DR Plan — Scenario 6 |
