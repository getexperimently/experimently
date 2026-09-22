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
