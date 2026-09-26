#!/usr/bin/env bash
# Roll an ECS-controller (rolling update) service out to one registered
# task-definition revision, and decide whether it took.
#
#   scripts/ecs_rolling_rollout.sh [--no-update] [--expect-primary <ARN>]
#       [--interval <seconds>] [--deadline <seconds>]
#       <cluster> <service> <task definition ARN>
#
# Written for the dashboard service (#69), which the CDK creates with the ECS
# rolling controller and the deployment circuit breaker with rollback
# (infrastructure/cdk/stacks/dashboard_service.py). The API is a CODE_DEPLOY
# service and is refused here: its rollout is CodeDeploy's.
#
# Why not `aws ecs wait services-stable`: its success condition is "one
# deployment, and the service's runningCount == desiredCount". After the
# circuit breaker rolls a failed rollout back, the old revision is the one
# deployment and every task is running, so the waiter reports success on a
# rollout that did not happen. It has no task-definition term. This script
# never uses it.
#
# The success rule, exactly (C4 plan-v2; EM v1 condition 3, PE v1 C3):
#
#   * the deployment this run started is anchored by its id, the one
#     `update-service` returned. No verdict of any kind is reached until a
#     `describe-services` has listed that id once: ECS is eventually
#     consistent, and a first poll can still show the state before the update.
#   * once it has been seen:
#       - a PRIMARY whose taskDefinition is not ours is an immediate failure.
#         If it is the revision serving before this run, that is the circuit
#         breaker's rollback; otherwise something else changed the service.
#         It does not wait for that rollback to COMPLETE.
#       - our id no longer listed is a failure.
#   * success is: exactly one deployment, it is ours, it is PRIMARY on our
#     taskDefinition, its rolloutState is COMPLETED, and the PRIMARY
#     DEPLOYMENT's own runningCount == desiredCount >= 1 -- not the
#     service's, which counts old and new tasks together.
#   * otherwise it polls every --interval seconds until --deadline seconds
#     after the update, then fails, saying ECS is still working on it. It does
#     not stop or undo anything.
#
# Before any mutation it refuses, without calling `update-service`, when:
#   * the service is not ACTIVE, or is not deployed by the ECS controller;
#   * its desiredCount is below 1 (0 == 0 would be a success with nothing
#     running);
#   * --expect-primary is given and the service's PRIMARY deployment is not
#     that revision (C4's race guard R11: the dashboard changed since the
#     calling run read it). The API-serving half of that guard (R10) is not
#     here: it is B3b's serving predicate, called by C4's workflow wiring
#     before this script.
#
# --no-update changes nothing: it follows the PRIMARY deployment already on
# the given revision, under the same rule, for a caller (rollback) whose target
# is already serving. If the PRIMARY is on another revision it fails at once.
#
# The outcome is one line on stdout; a failure is a GitHub `::error` line
# preceded by the service's last events and one stopped task's reason. Progress
# lines go to stderr. Exit status: 0 the rollout took; 1 it did not, or it was
# refused; 2 usage.
set -euo pipefail

usage() {
  echo "usage: $0 [--no-update] [--expect-primary <task definition ARN>] [--interval <seconds>] [--deadline <seconds>] <cluster> <service> <task definition ARN>" >&2
  exit 2
}

NO_UPDATE=0
EXPECT_PRIMARY=""
EXPECT_GIVEN=0
INTERVAL=15
DEADLINE=1200
while [ "$#" -gt 0 ]; do
  case "$1" in
    --no-update) NO_UPDATE=1; shift ;;
    --expect-primary) [ "$#" -ge 2 ] || usage; EXPECT_PRIMARY="$2"; EXPECT_GIVEN=1; shift 2 ;;
    --interval) [ "$#" -ge 2 ] || usage; INTERVAL="$2"; shift 2 ;;
    --deadline) [ "$#" -ge 2 ] || usage; DEADLINE="$2"; shift 2 ;;
    --) shift; break ;;
    -*) usage ;;
    *) break ;;
  esac
done
[ "$#" -eq 3 ] || usage
CLUSTER="$1"
SERVICE="$2"
TASK_DEFINITION="$3"
[ -n "$CLUSTER" ] && [ -n "$SERVICE" ] || usage
[[ "$INTERVAL" =~ ^[0-9]+$ ]] && [[ "$DEADLINE" =~ ^[0-9]+$ ]] || usage

ARN_RE='^arn:aws[a-z-]*:ecs:[a-z0-9-]+:[0-9]{12}:task-definition/[A-Za-z0-9_-]+:[0-9]+$'
if ! [[ "$TASK_DEFINITION" =~ $ARN_RE ]]; then
  echo "::error::Refusing to roll $SERVICE out to '$TASK_DEFINITION': not a registered revision ARN. A family resolves to whatever registered last. Nothing was changed."
  exit 1
fi
# Given but empty is a caller whose "serving before" value went missing: that
# must not quietly switch the guard off.
if [ "$EXPECT_GIVEN" = 1 ] && ! [[ "$EXPECT_PRIMARY" =~ $ARN_RE ]]; then
  echo "::error::Refusing to roll $SERVICE out: --expect-primary '$EXPECT_PRIMARY' is not a registered revision ARN. Nothing was changed."
  exit 1
fi

describe() {
  aws ecs describe-services --cluster "$CLUSTER" --services "$SERVICE" --output json
}

SVC=""
# The last 10 service events and one stopped task's reason, best effort: a
# failure to read them must not change the verdict.
diagnose() {
  echo "--- $SERVICE: last service events ---"
  jq -r '[.events[]?][:10][] | "\(.createdAt // "")  \(.message // "")"' <<<"$SVC" || true
  local task
  task="$(aws ecs list-tasks --cluster "$CLUSTER" --service-name "$SERVICE" \
            --desired-status STOPPED --query 'taskArns[0]' --output text 2>/dev/null)" || task=""
  if [ -n "$task" ] && [ "$task" != "None" ]; then
    echo "--- one stopped task ---"
    aws ecs describe-tasks --cluster "$CLUSTER" --tasks "$task" \
      --query 'tasks[0].[taskDefinitionArn, stoppedReason]' --output text 2>/dev/null \
      || echo "(its reason could not be read)"
  fi
  echo "---"
}

image_of() {
  aws ecs describe-task-definition --task-definition "$1" \
    --query 'taskDefinition.containerDefinitions[0].image' --output text 2>/dev/null || echo "image unknown"
}

# --- before any mutation ------------------------------------------------------

if ! OUT="$(describe)"; then
  echo "::error::Could not describe ECS service $SERVICE in $CLUSTER. Nothing was changed."
  exit 1
fi
SVC="$(jq -c '.services[0] // empty' <<<"$OUT")"
if [ -z "$SVC" ] || [ "$(jq -r '.status // ""' <<<"$SVC")" != "ACTIVE" ]; then
  echo "::error::No ACTIVE ECS service $SERVICE in $CLUSTER. Nothing was changed."
  exit 1
fi
CONTROLLER="$(jq -r '.deploymentController.type // "ECS"' <<<"$SVC")"
if [ "$CONTROLLER" != "ECS" ]; then
  echo "::error::$SERVICE is deployed by $CONTROLLER, not the ECS rolling controller; this script does not roll it out. Nothing was changed."
  exit 1
fi
WANTED="$(jq -r '.desiredCount // 0' <<<"$SVC")"
if ! [ "$WANTED" -ge 1 ] 2>/dev/null; then
  echo "::error::$SERVICE wants $WANTED tasks. A rollout to no tasks would look complete with nothing running, so this run does not start one. Nothing was changed."
  exit 1
fi
BEFORE="$(jq -r '[.deployments[]? | select(.status == "PRIMARY") | .taskDefinition]
                 | if length == 1 then .[0] else "" end' <<<"$SVC")"
if [ -z "$BEFORE" ]; then
  echo "::error::$SERVICE does not have exactly one PRIMARY deployment; this run cannot tell what is serving. Nothing was changed."
  exit 1
fi
echo "$SERVICE: serving before this run: $BEFORE" >&2

if [ "$EXPECT_GIVEN" = 1 ] && [ "$BEFORE" != "$EXPECT_PRIMARY" ]; then
  echo "::error title=$SERVICE changed during this run::$SERVICE's PRIMARY deployment is ${BEFORE##*/}, not ${EXPECT_PRIMARY##*/}, which this run read earlier. A Rollback run, another Deploy or a cdk deploy changed it while this run worked; this run did not change it back, and did not roll ${TASK_DEFINITION##*/} out. Nothing was changed."
  exit 1
fi

# --- the mutation, and the anchor ---------------------------------------------

if [ "$NO_UPDATE" = 1 ]; then
  ID="$(jq -r --arg td "$TASK_DEFINITION" \
          '[.deployments[]? | select(.status == "PRIMARY" and .taskDefinition == $td) | .id] | .[0] // ""' <<<"$SVC")"
  if [ -z "$ID" ]; then
    echo "::error title=$SERVICE is not on ${TASK_DEFINITION##*/}::$SERVICE is serving ${BEFORE##*/}, not ${TASK_DEFINITION##*/}. --no-update only follows a revision that is already PRIMARY. Nothing was changed."
    exit 1
  fi
  SEEN=1
  echo "$SERVICE: --no-update: following PRIMARY deployment $ID of ${TASK_DEFINITION##*/}; nothing will be changed" >&2
else
  ERR="$(mktemp)"
  trap 'rm -f "$ERR"' EXIT
  if ! UPDATED="$(aws ecs update-service --cluster "$CLUSTER" --service "$SERVICE" \
                    --task-definition "$TASK_DEFINITION" --output json 2>"$ERR")"; then
    cat "$ERR"
    if grep -q "AccessDenied" "$ERR"; then
      echo "::error title=Workflow role cannot update $SERVICE::ecs:UpdateService was denied. The role's policy predates this rollout; apply the generated policy in docs/deployment/iam-permissions.md. $SERVICE is still on ${BEFORE##*/}."
    else
      echo "::error title=$SERVICE was not updated::ECS refused update-service for ${TASK_DEFINITION##*/} (above). $SERVICE was serving ${BEFORE##*/} before the call."
    fi
    exit 1
  fi
  ID="$(jq -r --arg td "$TASK_DEFINITION" \
          '[.service.deployments[]? | select(.status == "PRIMARY" and .taskDefinition == $td) | .id] | .[0] // ""' <<<"$UPDATED")"
  if [ -z "$ID" ]; then
    echo "::error title=$SERVICE rollout cannot be followed::update-service returned no PRIMARY deployment of ${TASK_DEFINITION##*/}, so this run cannot tell its own rollout from any other and does not claim one. ECS may still be rolling it out: check $SERVICE's deployments."
    exit 1
  fi
  SEEN=0
  echo "$SERVICE: update-service started deployment $ID of ${TASK_DEFINITION##*/}" >&2
fi

# --- the wait -------------------------------------------------------------------

END=$(( $(date +%s) + DEADLINE ))
LAST=""
LISTED=false PRIMARIES=0 P_ID="-" P_TD="-" STATE="-" RUNNING=0 DESIRED=0 FAILED=0 COUNT=0
while :; do
  if OUT="$(describe)" && NEXT="$(jq -c '.services[0] // empty' <<<"$OUT")" && [ -n "$NEXT" ]; then
    SVC="$NEXT"
    IFS=$'\t' read -r LISTED PRIMARIES P_ID P_TD STATE RUNNING DESIRED FAILED COUNT < <(
      jq -r --arg id "$ID" '
        [.deployments[]?] as $d
        | [$d[] | select(.status == "PRIMARY")] as $p
        | [ any($d[]; .id == $id), ($p | length),
            ($p[0].id // "-"), ($p[0].taskDefinition // "-"), ($p[0].rolloutState // "-"),
            ($p[0].runningCount // 0), ($p[0].desiredCount // 0), ($p[0].failedTasks // 0),
            ($d | length) ]
        | @tsv' <<<"$SVC")

    [ "$LISTED" = "true" ] && SEEN=1
    if [ "$SEEN" = 1 ] && [ "$PRIMARIES" = 1 ]; then
      if [ "$P_TD" != "$TASK_DEFINITION" ]; then
        diagnose
        if [ "$P_TD" = "$BEFORE" ]; then
          echo "::error title=$SERVICE rolled back by ECS::$SERVICE did not start on ${TASK_DEFINITION##*/}, and ECS's circuit breaker put ${BEFORE##*/} ($(image_of "$BEFORE")) back. Nothing else was undone. The service events and a stopped task's reason are printed above."
        else
          echo "::error title=$SERVICE changed during this run::$SERVICE's PRIMARY deployment is ${P_TD##*/}, which is neither this run's revision (${TASK_DEFINITION##*/}) nor the one serving before it (${BEFORE##*/}), so it is not the circuit breaker's rollback. A Rollback run, another Deploy or a cdk deploy changed $SERVICE while this run waited; this run did not change it back."
        fi
        exit 1
      fi
      if [ "$LISTED" != "true" ]; then
        diagnose
        echo "::error title=$SERVICE changed during this run::This run's deployment $ID of ${TASK_DEFINITION##*/} is no longer listed; $SERVICE's PRIMARY is deployment $P_ID, which this run did not start. Another update-service replaced it; this run does not claim its outcome."
        exit 1
      fi
      if [ "$STATE" = "FAILED" ]; then
        diagnose
        echo "::error title=$SERVICE rollout failed::ECS marked the deployment of ${TASK_DEFINITION##*/} FAILED ($RUNNING/$DESIRED running, $FAILED failed tasks) and did not roll it back. The service events and a stopped task's reason are printed above."
        exit 1
      fi
      if [ "$COUNT" = 1 ] && [ "$P_ID" = "$ID" ] && [ "$STATE" = "COMPLETED" ] \
         && [ "$DESIRED" -ge 1 ] && [ "$RUNNING" = "$DESIRED" ]; then
        echo "$SERVICE: ${TASK_DEFINITION##*/} is PRIMARY, rollout COMPLETED, $RUNNING/$DESIRED tasks running"
        exit 0
      fi
    fi
    LINE="$SERVICE: PRIMARY ${P_TD##*/} $STATE, $RUNNING/$DESIRED running, $FAILED failed, $COUNT deployment(s)"
    [ "$SEEN" = 1 ] || LINE="$SERVICE: waiting for ECS to list deployment $ID"
    if [ "$LINE" != "$LAST" ]; then
      echo "$LINE" >&2
      LAST="$LINE"
    fi
  else
    echo "$SERVICE: could not read the service; retrying" >&2
  fi

  if [ "$(date +%s)" -ge "$END" ]; then
    diagnose
    if [ "$SEEN" = 1 ]; then
      echo "::error title=$SERVICE rollout did not finish::After ${DEADLINE}s $SERVICE's deployment of ${TASK_DEFINITION##*/} is $STATE ($RUNNING/$DESIRED running, $FAILED failed tasks, $COUNT deployment(s)). ECS is still working on it; this run stopped waiting and did not stop it."
    else
      echo "::error title=$SERVICE rollout did not finish::After ${DEADLINE}s ECS has not listed deployment $ID of ${TASK_DEFINITION##*/}. This run stopped waiting and did not stop anything."
    fi
    exit 1
  fi
  sleep "$INTERVAL"
done
