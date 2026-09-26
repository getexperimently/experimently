# IAM permissions for deploying

Three identities touch an AWS account that runs Experimently, and they need
different things. Keep them separate: the one that deploys releases every week
should not be able to rewrite the account.

| Identity | Who uses it | When | What it needs |
|---|---|---|---|
| **Bootstrap** | a human, once per account and region | `cdk bootstrap` | create the CDK toolkit stack (below) |
| **`cdk deploy`** | a human standing up or changing an environment | `ENVIRONMENT=<env> cdk deploy …` | `sts:AssumeRole` on the bootstrap's `cdk-*` roles, and a few one-off extras |
| **Workflow role** | GitHub Actions, through OIDC | Deploy, Rollback, Database Migration | exactly the generated list below |

Nothing in this repository creates any of them. They are set up by a person
with IAM rights in the account, before the first deploy
([deployment guide, section 1](deployment-guide.md#1-before-the-first-deploy)).

## 1. The bootstrap identity

`cdk bootstrap aws://<account>/<region>` creates the `CDKToolkit`
CloudFormation stack: an S3 bucket and an ECR repository for assets, SSM
parameter `/cdk-bootstrap/hnb659fds/version`, and the IAM roles
`cdk-hnb659fds-{deploy,cfn-exec,file-publishing,image-publishing,lookup}-role-<account>-<region>`.
So it needs to create CloudFormation stacks, IAM roles and policies, an S3
bucket, an ECR repository and an SSM parameter. In practice that is an
administrator, once. Nothing afterwards should use it.

## 2. The `cdk deploy` identity

With a modern bootstrap, `cdk deploy` does not use its caller's permissions to
create resources: it assumes the bootstrap roles, and CloudFormation acts as
`cdk-hnb659fds-cfn-exec-role-…`. The caller needs:

- `sts:AssumeRole` on `arn:aws:iam::<account>:role/cdk-hnb659fds-*`;
- for the one-off steps the deployment guide has them do by hand:
  `ecr:CreateRepository` and push rights on `experimentation-platform/backend`
  and `experimentation-platform/web`, `secretsmanager:CreateSecret` on
  `/<env>/experimentation/*`, and `acm:RequestCertificate` /
  `acm:DescribeCertificate` (plus `route53:ChangeResourceRecordSets` if DNS is
  in Route 53).

Check it before relying on it:

```bash
aws iam simulate-principal-policy \
  --policy-source-arn <the identity's ARN> \
  --action-names sts:AssumeRole \
  --resource-arns "arn:aws:iam::<account>:role/cdk-hnb659fds-deploy-role-<account>-<region>"
```

## 3. The workflow role (GitHub OIDC)

One role **per environment**, each trusted only by jobs bound to that GitHub
environment, and each holding the same permissions policy.

### Trust policy

[`infrastructure/cdk/github-actions-trust-policy.json`](https://github.com/getexperimently/experimently/blob/main/infrastructure/cdk/github-actions-trust-policy.json)
is the template. Replace `<AWS_ACCOUNT_ID>` and `<ENVIRONMENT>` (`staging` or
`prod`) and create one role from each copy. It pins the token's `sub` claim
exactly -- `StringEquals`, no wildcard:

```
repo:getexperimently@328439352/experimently@1367480368:environment:<ENVIRONMENT>
```

That is GitHub's **immutable subject**: the owner and repository by name *and*
numeric id, so a repository deleted and recreated under the same name (or a
transferred one) cannot assume the role. This repository uses it; the prefix
comes from

```bash
gh api repos/<owner>/<repo>/actions/oidc/customization/sub
# {"use_default":true,"use_immutable_subject":true,
#  "sub_claim_prefix":"repo:getexperimently@328439352/experimently@1367480368"}
```

and a fork or a copy of this repository has a different one: read yours with
the same call. The `:environment:<name>` suffix is what a job that declares
`environment:` receives, which is the only kind of job in these workflows that
assumes the role.

**Before writing the policy, decode a real token.** The prefix above was read
from the API, not from a token. The first staging rehearsal (Stream I) runs a
throwaway job bound to the `staging` environment that prints only the
*payload* of its OIDC token's `sub` claim, and the trust policy is written
from what it printed. A `sub` that does not match fails `AssumeRoleWithWebIdentity`
with "Not authorized", which is the safe direction.

The account also needs the GitHub OIDC provider
(`token.actions.githubusercontent.com`, audience `sts.amazonaws.com`), once.

### Permissions policy

[`infrastructure/cdk/github-actions-deploy-policy.json`](https://github.com/getexperimently/experimently/blob/main/infrastructure/cdk/github-actions-deploy-policy.json),
generated -- like the table below -- by `scripts/iam_actions.py` from every
`aws <service> <verb>` in `deploy.yml`, `rollback.yml`, `db-migrate.yml`, the
local actions under `.github/actions/`, and the scripts those run. A unit test
fails when a workflow gains a call the committed copies do not grant, so the
list cannot fall behind the workflows. `iam:PassRole` is granted only for
passing roles to ECS tasks.

Resources are `*`. Narrowing them to one environment's ARNs is worth doing;
it is not done here, because the names mix generated identifiers (the Aurora
cluster, the task roles) that are only known after `cdk deploy`.

Three of the actions are not visible in the workflow text and come from AWS's
documentation of what the call needs: `iam:PassRole` (registering and running
a task definition that names roles), and `codedeploy:GetDeploymentConfig` /
`codedeploy:RegisterApplicationRevision` (creating a deployment from an AppSpec).
Stream I confirms the whole list with `aws iam simulate-principal-policy`
before the first dispatch.

<!-- BEGIN GENERATED by scripts/iam_actions.py; do not edit by hand -->
| Action | Needed by |
|---|---|
| `cloudformation:DescribeStackResources` | `scripts/check_live_target_group.py: aws cloudformation describe-stack-resources` |
| `cloudformation:DescribeStacks` | `.github/actions/stack-outputs/action.yml: aws cloudformation describe-stacks` |
| `codedeploy:ContinueDeployment` | `.github/workflows/rollback.yml: aws deploy continue-deployment`<br>`scripts/shift_traffic.py: aws deploy continue-deployment` |
| `codedeploy:CreateDeployment` | `.github/workflows/deploy.yml: aws deploy create-deployment`<br>`.github/workflows/rollback.yml: aws deploy create-deployment` |
| `codedeploy:GetDeployment` | `.github/workflows/rollback.yml: aws deploy get-deployment`<br>`scripts/refuse_active_deployment.py: aws deploy get-deployment`<br>`scripts/shift_traffic.py: aws deploy get-deployment` |
| `codedeploy:GetDeploymentConfig` | `.github/workflows/deploy.yml: aws deploy create-deployment`<br>`.github/workflows/rollback.yml: aws deploy create-deployment` |
| `codedeploy:ListDeployments` | `.github/workflows/rollback.yml: aws deploy list-deployments`<br>`scripts/refuse_active_deployment.py: aws deploy list-deployments` |
| `codedeploy:RegisterApplicationRevision` | `.github/workflows/deploy.yml: aws deploy create-deployment`<br>`.github/workflows/rollback.yml: aws deploy create-deployment` |
| `codedeploy:StopDeployment` | `.github/workflows/rollback.yml: aws deploy stop-deployment` |
| `ecr:BatchCheckLayerAvailability` | `.github/workflows/deploy.yml: docker pull`<br>`.github/workflows/deploy.yml: docker push` |
| `ecr:BatchGetImage` | `.github/workflows/deploy.yml: docker pull` |
| `ecr:CompleteLayerUpload` | `.github/workflows/deploy.yml: docker push` |
| `ecr:DescribeImages` | `.github/workflows/deploy.yml: aws ecr describe-images` |
| `ecr:DescribeRepositories` | `.github/workflows/deploy.yml: aws ecr describe-repositories` |
| `ecr:GetAuthorizationToken` | `.github/workflows/deploy.yml: uses aws-actions/amazon-ecr-login` |
| `ecr:GetDownloadUrlForLayer` | `.github/workflows/deploy.yml: docker pull` |
| `ecr:InitiateLayerUpload` | `.github/workflows/deploy.yml: docker push` |
| `ecr:PutImage` | `.github/workflows/deploy.yml: docker push` |
| `ecr:UploadLayerPart` | `.github/workflows/deploy.yml: docker push` |
| `ecs:DescribeClusters` | `.github/workflows/deploy.yml: aws ecs describe-clusters` |
| `ecs:DescribeServices` | `.github/workflows/db-migrate.yml: aws ecs describe-services`<br>`.github/workflows/deploy.yml: aws ecs describe-services`<br>`.github/workflows/rollback.yml: aws ecs describe-services`<br>`scripts/check_live_target_group.py: aws ecs describe-services`<br>`scripts/shift_traffic.py: aws ecs describe-services` |
| `ecs:DescribeTaskDefinition` | `.github/workflows/db-migrate.yml: aws ecs describe-task-definition`<br>`.github/workflows/deploy.yml: aws ecs describe-task-definition`<br>`.github/workflows/rollback.yml: aws ecs describe-task-definition`<br>`scripts/register_task_definition.sh: aws ecs describe-task-definition` |
| `ecs:DescribeTasks` | `scripts/run_migration_task.sh: aws ecs describe-tasks` |
| `ecs:RegisterTaskDefinition` | `scripts/register_task_definition.sh: aws ecs register-task-definition` |
| `ecs:RunTask` | `scripts/run_migration_task.sh: aws ecs run-task` |
| `elasticloadbalancing:DescribeListeners` | `scripts/check_live_target_group.py: aws elbv2 describe-listeners` |
| `elasticloadbalancing:DescribeRules` | `scripts/check_live_target_group.py: aws elbv2 describe-rules` |
| `elasticloadbalancing:DescribeTargetHealth` | `scripts/shift_traffic.py: aws elbv2 describe-target-health` |
| `iam:PassRole` | `scripts/register_task_definition.sh: aws ecs register-task-definition`<br>`scripts/run_migration_task.sh: aws ecs run-task` |
| `logs:GetLogEvents` | `scripts/run_migration_task.sh: aws logs get-log-events` |
| `rds:CreateDBClusterSnapshot` | `.github/workflows/db-migrate.yml: aws rds create-db-cluster-snapshot`<br>`.github/workflows/deploy.yml: aws rds create-db-cluster-snapshot` |
| `rds:DescribeDBClusterSnapshots` | `.github/workflows/db-migrate.yml: aws rds wait db-cluster-snapshot-available`<br>`.github/workflows/deploy.yml: aws rds wait db-cluster-snapshot-available` |
| `secretsmanager:DescribeSecret` | `.github/workflows/deploy.yml: aws secretsmanager describe-secret` |
<!-- END GENERATED -->

### GitHub side

Per environment (`staging`, `prod`): Settings → Environments → *env*:

- **required reviewer**, and **deployment branches: `main` only** -- set these
  first, before any variable or secret (a dispatch that names an environment
  that does not exist creates it, unprotected);
- variables `AWS_ACCOUNT_ID` and `PUBLIC_BASE_URL`;
- secret `AWS_ROLE_ARN` -- that environment's role.

`SLACK_BOT_TOKEN` may be a repository secret; it is optional.
