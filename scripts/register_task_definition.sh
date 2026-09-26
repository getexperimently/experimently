#!/usr/bin/env bash
# Register a new revision of an ECS task definition family whose `backend`
# container runs one image, named by DIGEST; print the new revision's ARN.
#
#   scripts/register_task_definition.sh <family> <registry/repo@sha256:...>
#
# Used by deploy.yml (the API and the migration task) and db-migrate.yml (the
# migration task). Two producers register into these families and the split is
# deliberate:
#
#   CloudFormation owns the shape  -- environment, secrets, cpu/memory, roles,
#                                     log configuration (`cdk deploy`)
#   the workflows own the image    -- and nothing else
#
# So the base is the family's newest ACTIVE revision, whoever wrote it, with
# only the `backend` container's image replaced.
#
# Only a digest is accepted (#138, QA 1c/2). A version tag lives in one ECR
# repository shared by every environment and profile, and ECS resolves a tag
# each time it starts a task: a later build pushed to the same tag would be
# what the next scale-out, or the migration, actually ran. A digest cannot
# move.
#
# Messages go to stderr; stdout is the ARN and nothing else.
set -euo pipefail

if [ "$#" -ne 2 ] || [ -z "$1" ] || [ -z "$2" ]; then
  echo "usage: $0 <task definition family> <registry/repo@sha256:digest>" >&2
  exit 2
fi
FAMILY="$1"
IMAGE="$2"

if ! [[ "$IMAGE" =~ ^[^@[:space:]]+@sha256:[0-9a-f]{64}$ ]]; then
  echo "::error::Refusing to register $FAMILY with '$IMAGE': not an image digest (repo@sha256:...). A tag can be moved by another build after the revision is registered." >&2
  exit 1
fi

if ! TD="$(aws ecs describe-task-definition --task-definition "$FAMILY" \
             --query taskDefinition --output json)"; then
  echo "::error::No task definition family $FAMILY in this account and region. Deploy the stacks first: docs/self-hosting/cdk.md" >&2
  exit 1
fi

COUNT="$(jq '[.containerDefinitions[] | select(.name == "backend")] | length' <<<"$TD")"
if [ "$COUNT" != "1" ]; then
  echo "::error::$FAMILY's newest revision has $COUNT containers named 'backend' (it has: $(jq -r '[.containerDefinitions[].name] | join(", ")' <<<"$TD")); expected exactly one." >&2
  exit 1
fi

# Everything `describe` returns that `register` refuses or ignores.
NEW="$(jq -c --arg image "$IMAGE" '
  (.containerDefinitions[] | select(.name == "backend") | .image) = $image
  | del(.taskDefinitionArn, .revision, .status, .requiresAttributes,
        .compatibilities, .registeredAt, .registeredBy, .deregisteredAt)
' <<<"$TD")"

ARN="$(aws ecs register-task-definition --cli-input-json "$NEW" \
         --query taskDefinition.taskDefinitionArn --output text)"

# Read it back: the revision that will run is the one ECS stored, not the JSON
# this script meant to send.
REGISTERED="$(aws ecs describe-task-definition --task-definition "$ARN" \
                --query "taskDefinition.containerDefinitions[?name=='backend'].image | [0]" \
                --output text)"
if [ "$REGISTERED" != "$IMAGE" ]; then
  echo "::error::$ARN was registered with '$REGISTERED', not $IMAGE." >&2
  exit 1
fi

echo "registered $ARN with $IMAGE" >&2
echo "$ARN"
