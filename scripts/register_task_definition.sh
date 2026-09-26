#!/usr/bin/env bash
# Register a new revision of an ECS task definition family whose named
# container (`backend` unless a third argument says otherwise) runs one image,
# named by DIGEST; print the new revision's ARN.
#
#   scripts/register_task_definition.sh <family> <registry/repo@sha256:...> [<container>]
#
# Used by deploy.yml (the API and the migration task) and db-migrate.yml (the
# migration task), all with two arguments, so `backend`. The dashboard's
# family names its container `dashboard` (infrastructure/cdk/stacks/
# dashboard_service.py) and passes it as the third argument. Two producers
# register into these families and the split is deliberate:
#
#   CloudFormation owns the shape  -- environment, secrets, cpu/memory, roles,
#                                     log configuration (`cdk deploy`)
#   the workflows own the image    -- and nothing else
#
# So the base is the family's newest ACTIVE revision, whoever wrote it, with
# only that one container's image replaced. A revision with no container of
# that name, or more than one, is refused rather than guessed at: passing
# `backend` for the dashboard's family finds none, and says what it has.
#
# Only a digest is accepted (#138, QA 1c/2). A version tag lives in one ECR
# repository shared by every environment and profile, and ECS resolves a tag
# each time it starts a task: a later build pushed to the same tag would be
# what the next scale-out, or the migration, actually ran. A digest cannot
# move.
#
# Messages go to stderr; stdout is the ARN and nothing else.
# Exit status: 0 registered; 1 refused or failed; 2 usage.
set -euo pipefail

if [ "$#" -lt 2 ] || [ "$#" -gt 3 ] || [ -z "$1" ] || [ -z "$2" ]; then
  echo "usage: $0 <task definition family> <registry/repo@sha256:digest> [<container name>]" >&2
  exit 2
fi
FAMILY="$1"
IMAGE="$2"
CONTAINER="${3-backend}"
# The name is interpolated into a jq filter and a JMESPath query below; allow
# only what ECS allows in a container name, so neither can be rewritten.
if ! [[ "$CONTAINER" =~ ^[A-Za-z0-9_-]+$ ]]; then
  echo "usage: $0: container name '$CONTAINER' is not [A-Za-z0-9_-]+" >&2
  exit 2
fi

if ! [[ "$IMAGE" =~ ^[^@[:space:]]+@sha256:[0-9a-f]{64}$ ]]; then
  echo "::error::Refusing to register $FAMILY with '$IMAGE': not an image digest (repo@sha256:...). A tag can be moved by another build after the revision is registered." >&2
  exit 1
fi

if ! TD="$(aws ecs describe-task-definition --task-definition "$FAMILY" \
             --query taskDefinition --output json)"; then
  echo "::error::No task definition family $FAMILY in this account and region. Deploy the stacks first: docs/self-hosting/cdk.md" >&2
  exit 1
fi

COUNT="$(jq --arg name "$CONTAINER" '[.containerDefinitions[] | select(.name == $name)] | length' <<<"$TD")"
if [ "$COUNT" != "1" ]; then
  echo "::error::$FAMILY's newest revision has $COUNT containers named '$CONTAINER' (it has: $(jq -r '[.containerDefinitions[].name] | join(", ")' <<<"$TD")); expected exactly one." >&2
  exit 1
fi

# Everything `describe` returns that `register` refuses or ignores.
NEW="$(jq -c --arg image "$IMAGE" --arg name "$CONTAINER" '
  (.containerDefinitions[] | select(.name == $name) | .image) = $image
  | del(.taskDefinitionArn, .revision, .status, .requiresAttributes,
        .compatibilities, .registeredAt, .registeredBy, .deregisteredAt)
' <<<"$TD")"

ARN="$(aws ecs register-task-definition --cli-input-json "$NEW" \
         --query taskDefinition.taskDefinitionArn --output text)"

# Read it back: the revision that will run is the one ECS stored, not the JSON
# this script meant to send.
REGISTERED="$(aws ecs describe-task-definition --task-definition "$ARN" \
                --query "taskDefinition.containerDefinitions[?name=='$CONTAINER'].image | [0]" \
                --output text)"
if [ "$REGISTERED" != "$IMAGE" ]; then
  echo "::error::$ARN was registered with '$REGISTERED', not $IMAGE." >&2
  exit 1
fi

echo "registered $ARN with $IMAGE" >&2
echo "$ARN"
