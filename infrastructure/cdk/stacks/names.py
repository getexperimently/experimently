"""Identifiers more than one tree has to agree on.

The ECR repository is the case that motivated this. The deployment guide told
operators to create `experimentation-backend` and `experimentation-migrations`
before the first deployment, and **nothing** used either name -- every
producer and consumer says `experimentation-platform/backend`. Following the
documentation exactly produced a first deploy that died at `docker push` with
"name unknown" (#211). The name was written down in five documents and two
stacks with nothing tying any of them together.

A name belongs here when more than one tree has to spell it the same way.
`infrastructure/tests/test_ecr_repository_agrees.py` asserts that the CDK, the
deploy workflow and every deployment document still agree about this one, so a
rename that misses a caller fails a test rather than a deployment.

Not here yet, and deliberately: the ECS cluster name
(`experimentation-{env}`), which `deploy-prod.yml` and `rollback.yml` also
spell out. It was made explicit in #80 and nothing asserts the agreement; it
is the obvious next entry, and moving it is a change to those workflows rather
than a comment.
"""

from __future__ import annotations

#: The one container repository this project pushes to and runs from. The API
#: service and the migration task deliberately share it -- migrations run the
#: same image with a different command, so a second repository would be a
#: second thing to keep in step for no gain.
#:
#: Nothing in the CDK *creates* it. That was tried and reverted: a registry is
#: account-scoped while these stacks are per-environment, so a fixed name in a
#: per-environment stack means only one environment per account can deploy
#: (`demo/setup-aws.sh` runs `ENVIRONMENT=demo cdk deploy --all`), and
#: `RemovalPolicy.RETAIN` plus an explicit name makes `cdk deploy` fail
#: outright wherever the repository already exists -- including for the
#: operator who hit #211 and created it by hand to unblock themselves.
#: Creating it belongs in a once-per-account stack, not here.
BACKEND_ECR_REPOSITORY = "experimentation-platform/backend"

#: The dashboard's repository (#69): `frontend/Dockerfile`'s static nginx
#: image. Imported by name for the same reasons as the backend's, and created
#: by hand once per account, with a `bootstrap` image pushed to it, before the
#: first `cdk deploy` that includes the dashboard service
#: (docs/deployment/deployment-guide.md section 1.3).
DASHBOARD_ECR_REPOSITORY = "experimentation-platform/web"

#: The CDK context key naming the API target group that is LIVE -- the one
#: CodeDeploy's most recent deployment left serving traffic -- and its
#: default. The HTTPS listener's API path rules forward to it.
#:
#: CloudFormation cannot know which of blue and green that is: CodeDeploy
#: swaps them on every deployment, outside CloudFormation. After an odd number
#: of deployments green is live and blue is empty, and a `cdk deploy` that
#: wrote the rules against blue would send every API request to an empty
#: target group. `scripts/check_live_target_group.py` reads the live one from
#: the running environment (read-only) and refuses a mismatch with this value.
#: The script carries its own copy of both; a unit test asserts they agree.
API_LIVE_TARGET_GROUP_CONTEXT = "api_live_target_group"
API_LIVE_TARGET_GROUP_DEFAULT = "blue"
