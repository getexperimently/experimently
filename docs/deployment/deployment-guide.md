# Deployment Guide — Experimently

**Audience:** whoever stands up an environment, and whoever deploys to it.
**Environments:** `staging` and `prod` -- one path for both. `<env>` below is
one of those two words, and `ENV=staging` (or `prod`) in a shell.
**Region:** `us-west-2`, the region the workflows act in
([cdk.md](../self-hosting/cdk.md#required-environment-variables)).

---

## Table of Contents

1. [Before the first deploy](#1-before-the-first-deploy) -- the ordered checklist
2. [The first deploys, and the rollback rehearsal](#2-the-first-deploys-and-the-rollback-rehearsal)
3. [Every deploy](#3-every-deploy)
4. [Pre-Deployment Checklist](#4-pre-deployment-checklist)
5. [Post-Deployment Verification](#5-post-deployment-verification)
6. [Deployment Architecture](#6-deployment-architecture)
7. [Troubleshooting](#7-troubleshooting)

---

## 1. Before the first deploy

Do these **in this order**, once per environment. Each step says who does it,
how to check it read-only, and where to stop. Several are irreversible or
billable, and each of those needs a person to say yes at the moment it happens.

### 1.0 Decisions (founder)

Which AWS account (one per environment), which region (one: `us-west-2` unless
you change all three workflows), which profile (`full` or `core`), the domain
(`app.<domain>`), a budget alarm and who owns the bill, and when a staging
environment is torn down. Nothing below should start without them.

### 1.1 IAM (account administrator)

Three identities, described with their exact permissions in
[IAM Permissions](iam-permissions.md): the **bootstrap** identity (once), the
**`cdk deploy`** identity, and one **workflow role** per environment.

- The workflow role's trust policy pins the OIDC subject exactly. **Decode a
  real token's `sub` first** (a throwaway job bound to the `staging`
  environment printing only the payload's `sub`), and write the trust policy
  from what it printed, not from memory.
- Check: `aws iam simulate-principal-policy` for each identity (the IAM page
  gives the command). **Stop here if** any action is denied.

### 1.2 Certificate and domain

An ACM certificate **in `us-west-2`** (the load balancer's region -- not
`us-east-1`, which is CloudFront's) covering `app.<domain>`, status `ISSUED`,
before any `cdk deploy`. `PUBLIC_BASE_URL=https://app.<domain>`.

```bash
aws acm describe-certificate --certificate-arn "$CERTIFICATE_ARN" \
  --region us-west-2 --query Certificate.Status
# "ISSUED" -- stop here if not
```

After the Fargate stack exists, point `app.<domain>` at the load balancer
(output `ALBDnsName` of `experimentation-fargate-<env>`). Nothing in the CDK
creates that DNS record.

### 1.3 ECR repositories and the bootstrap images

**Two** repositories, created once per account and region; nothing in the CDK
creates them (a registry is account-scoped, the stacks are per-environment):

```bash
aws ecr create-repository \
  --repository-name experimentation-platform/backend \
  --region us-west-2 \
  --image-scanning-configuration scanOnPush=true

aws ecr create-repository \
  --repository-name experimentation-platform/web \
  --region us-west-2 \
  --image-scanning-configuration scanOnPush=true
```

Then one image in each tagged `bootstrap`: CloudFormation cannot create an ECS
service without a task definition, and a task definition cannot name no image.
`bootstrap` is a tag the Deploy workflow never writes, so the revision
CloudFormation registers cannot drift to a later build. Build from the
repository root with the profile you will deploy:

```bash
ECR_REGISTRY=<account>.dkr.ecr.us-west-2.amazonaws.com
aws ecr get-login-password --region us-west-2 \
  | docker login --username AWS --password-stdin "$ECR_REGISTRY"
docker build --target <core|full> -f backend/Dockerfile \
  -t "$ECR_REGISTRY/experimentation-platform/backend:bootstrap" .
docker push "$ECR_REGISTRY/experimentation-platform/backend:bootstrap"
docker build -f frontend/Dockerfile --build-arg EXPERIMENTLY_PROFILE=<core|full> \
  -t "$ECR_REGISTRY/experimentation-platform/web:bootstrap" .
docker push "$ECR_REGISTRY/experimentation-platform/web:bootstrap"
```

Both repositories survive a teardown (they are not in any stack).

### 1.4 Secrets

`/<env>/experimentation/jwt-secret` and `/<env>/experimentation/first-superuser-password`,
plus `/<env>/experimentation/audit-hmac-key` on `full`
([Secrets Management](secrets-management.md)). They must exist before the
Fargate and migrations stacks: ECS will not start a task whose definition
names a missing secret. The database and Redis need nothing from you -- the
stacks wire them.

```bash
ENV=staging
for s in jwt-secret first-superuser-password audit-hmac-key; do
  aws secretsmanager describe-secret --secret-id "/$ENV/experimentation/$s" \
    --query Name --output text
done
```

### 1.5 GitHub (repository administrator)

For each environment, **protection first**, then configuration:

1. Settings → Environments → `<env>`: a **required reviewer** and
   **deployment branches: `main` only**. Check it before going on:
   `gh api repos/<owner>/<repo>/environments/<env> --jq '.protection_rules, .deployment_branch_policy'`.
   A workflow dispatched for an environment that does not exist creates it,
   unprotected -- which is why this comes before anything that names it.
2. Variables `AWS_ACCOUNT_ID` and `PUBLIC_BASE_URL`; secret `AWS_ROLE_ARN`.
   Setting them arms the workflows for that environment.

### 1.6 The stacks

```bash
cdk bootstrap aws://<account>/us-west-2          # once per account and region

cd infrastructure/cdk
export ENVIRONMENT=staging CDK_DEFAULT_REGION=us-west-2
export CERTIFICATE_ARN=... PUBLIC_BASE_URL=https://app.<domain>
cdk deploy --all --require-approval never
```

`cdk deploy --all` is for standing an environment up. On one that is already
running, deploy `experimentation-fargate-<env>` on its own, pinned to what is
live -- CodeDeploy swaps the API's blue and green target groups outside
CloudFormation, and a `cdk deploy` that names the empty one sends every API
request to it while every probe stays green:

```bash
python3 scripts/check_live_target_group.py --env "$ENVIRONMENT"   # from the repo root; read-only
RUNNING_TD=$(aws ecs describe-services --cluster "experimentation-$ENVIRONMENT" \
  --services "experimentation-backend-$ENVIRONMENT" \
  --query "services[0].taskSets[?status=='PRIMARY'].taskDefinition" --output text)
test -n "$RUNNING_TD" || { echo "no PRIMARY task set"; exit 1; }
aws ecs describe-task-definition --task-definition "$RUNNING_TD" \
  --query "taskDefinition.containerDefinitions[?name=='backend'].image" --output text
# pass the image's tag, or keep bootstrap, and the value the check printed:
cdk deploy "experimentation-fargate-$ENVIRONMENT" --require-approval never \
  -c backend_image_tag=<tag> -c api_live_target_group=<blue|green>
```

Check: `aws cloudformation list-stacks --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE --query "StackSummaries[?contains(StackName, 'experimentation-')].StackName"`.
**Stop here if** a stack rolled back: the first missing secret or image is the
usual cause (section 7).

---

## 2. The first deploys, and the rollback rehearsal

In **staging**, before prod is ever deployed (DECISIONS D6):

1. **Deploy tag A** (section 3). The first deploy's migration builds the
   schema from nothing (`backend.app.db.bootstrap`).
2. **Smoke through the public origin**: `curl -s https://app.<domain>/api/v1/experiments/`
   answers `401 {"detail":"Not authenticated"}`. `/health` is not enough: it
   is what the load balancer already probed.
3. **Deploy tag B.**
4. **Roll back to A** with the line tag B's run summary printed
   ([Rollback Runbook](rollback-runbook.md)).
5. Record, for the plan's open questions: whether CodeDeploy rewrites the API
   listener rules; when the PRIMARY task set flips relative to the canary; the
   deployment's status during the hour-long termination wait.
6. Tear down, and compare what is left with
   [what `cdk destroy` leaves behind](../self-hosting/cdk.md#what-cdk-destroy-leaves-behind-and-bills).

> **Until #143 lands, steps 1 and 3 stop before the traffic shift**, red, by
> design: see [section 3](#3-every-deploy). The rehearsal waits for it.

Prod: the same checklist, with a reviewer who did not dispatch the run. There
is no automatic rollback on application errors: the canary is timed, not
judged, and the response to a bad release is the Rollback workflow within the
hour the old task set is kept.

---

## 3. Every deploy

1. **A release tag.** release-please cuts them; the Release Gate runs on every
   push to `main`, so the tag's commit has a result. For a tag cut before that:
   `gh workflow run release-gate.yml --ref vX.Y.Z`, then wait for it.
2. **Actions → Deploy → Run workflow**, "Use workflow from" **`main`** (any other
   ref is refused: the workflow's own tooling comes from it), then
   `environment`, `version` (the tag), `profile`.
3. **Preflight**, with no AWS credentials: the dispatch ref, the profile
   acknowledgement, that `version` matches `vX.Y.Z[-pre]`, exists, and is on
   `main`, and that its commit passed the Release Gate (the latest completed
   run wins; a run still in progress refuses).
4. **Approve** when the environment asks. Nothing in AWS has changed yet.
5. The deploy job then, in order: refuses an unconfigured environment, the
   wrong AWS account, missing stacks, a profile the stacks were not deployed
   for, missing secrets or repository -- all before any change -- and then
   builds `:<tag>-<profile>` from the tag (or reuses it if an earlier deploy of
   the same release into this account already pushed it), checks the image's
   labels name the tag's commit,
   snapshots the database (`pre-deploy-<env>-<tag>-<time>`), registers and
   runs the migration by digest, registers the API revision by digest, and
   creates the CodeDeploy deployment.
6. **Until #143:** the run stops there, red: *"Stopped before the traffic
   shift (#143)"*. Nothing shifts; the previous revision keeps serving and
   CodeDeploy stops the unapproved deployment after its 30-minute wait. The
   migration **has** been applied, which is safe only when it is
   backward-compatible (below).
7. **After #143:** the traffic shift, then the smoke request
   (`GET ${PUBLIC_BASE_URL}/api/v1/experiments/` → `401 {"detail":"Not authenticated"}`).
   A failed smoke test does **not** roll back; the run summary gives the line:
   `Rollback: Actions → Rollback → environment=<env>, task_definition_arn=experimentation-backend-<env>:<n>`.

One deploy or manual migration per environment at a time. A newer dispatch
waiting behind a running deploy replaces an older one that was still waiting
(GitHub keeps one pending run per concurrency group).

### Backward-compatible migrations

A deploy migrates **before** it shifts traffic, so for a while -- and for as
long as a failed or stopped deploy leaves it so -- the previous release runs
against the new schema. Every migration must therefore be one the previous
release can run against: add columns and tables (nullable, or with defaults),
never drop or rename one the previous release reads in the same release. Drop
in a later release, once nothing running reads it.

---

## 4. Pre-Deployment Checklist

### Mandatory Checks

- [ ] The Release Gate passed on the tag's commit (the workflow refuses otherwise)
- [ ] Security scan passing — no new CRITICAL or HIGH CVEs
- [ ] No active P0 or P1 incidents (check `#incidents` and PagerDuty; the workflow does not)
- [ ] Team notified in `#deployments`: "Deploying vX.Y.Z to <env> at HH:MM UTC"
- [ ] For prod: the same tag deployed to staging and smoke-tested

### Database Migration Checks (if migration is included)

- [ ] Migration applied in staging — no errors, no data loss
- [ ] Migration is [backward-compatible](#backward-compatible-migrations)
- [ ] The downgrade tested in staging (Actions → Database Migration, `downgrade`, `-1`)

---

## 5. Post-Deployment Verification

```bash
ENV=staging   # or prod
BASE=https://app.<domain>

curl -s "$BASE/health"                      # readiness: checks.database.status
curl -s "$BASE/api/v1/experiments/"         # 401 {"detail":"Not authenticated"}

aws ecs describe-services --cluster "experimentation-$ENV" \
  --services "experimentation-backend-$ENV" \
  --query "services[0].{Running:runningCount,Desired:desiredCount,Serving:taskSets[?status=='PRIMARY'].taskDefinition|[0]}"
```

Expected: `Running == Desired`, and `Serving` the revision the run summary
named.

---

## 6. Deployment Architecture

```
Actions → Deploy (from main; environment = staging | prod)
  preflight   no credentials: ref, profile, tag on main, Release Gate
  deploy      one approval, then:
                refusals (account, stacks, profile, secrets, ECR)
                build :<tag>-<profile> from ./release (or reuse it)
                snapshot  →  migration (by digest)  →  API revision (by digest)
                CodeDeploy blue/green  →  [#143: shift]  →  smoke  →  summary
      |
      v
ECS cluster experimentation-<env>
  service experimentation-backend-<env>   image .../backend@sha256:...
  secrets  /<env>/experimentation/*  and the Aurora-generated credentials
  Aurora (identifier: stack output)  ·  Redis over TLS (REDIS_SSL=true)
```

---

## 7. Troubleshooting

### "Deployment stuck in Pending"

```bash
ENV=staging
aws ecs describe-tasks --cluster "experimentation-$ENV" \
  --tasks $(aws ecs list-tasks --cluster "experimentation-$ENV" --query 'taskArns[0]' --output text) \
  --query 'tasks[0].{Status:lastStatus,StopCode:stopCode,StopReason:stoppedReason}'
```

Common causes: a secret not found (check `/<env>/experimentation/`), an image
not found (check ECR), IAM permission denied (check the task role).

### "Migration task failed"

The run prints the task's last 100 log lines. The full log is CloudWatch log
group `/ecs/experimentation-migrate-<env>`, stream `migrate/backend/<task id>`.
A migration that failed half-way needs its downgrade before a re-deploy
([Rollback Runbook](rollback-runbook.md)).

### "Smoke test failing after deployment"

Nothing rolls back automatically. Decide, and use the rollback line in the run
summary. The API's log is `/ecs/experimentation-backend-<env>`.
