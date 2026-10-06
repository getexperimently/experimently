#!/usr/bin/env bash
# Point the application at an Aurora cluster restored from point-in-time
# recovery. The restored cluster and its writer take the stack's identifiers
# and the original cluster and its instances move aside under new names, so
# every reference the stacks, the task definitions and deploy.yml hold (all by
# identifier, and the writer endpoint is the identifier plus a suffix) keeps
# working unchanged. Nothing is ever deleted.
#
# The procedure, and who approves each phase, is
# docs/deployment/disaster-recovery.md#restore-from-pitr-preferred. The phases,
# in order:
#
#   restore_repoint.sh read      <env>                record the original, the stacks and the API;
#                                                     prints the evidence directory; changes nothing
#   restore_repoint.sh restore   <evidence> <time>    restore beside the original to <time> (UTC,
#                                                     2026-10-06T12:00:00Z), add the writer, compare
#                                                     both with the original, mark the restored database
#   restore_repoint.sh cutover   <evidence>           DOWNTIME: API to 0, swap the names, check the
#                                                     endpoint and the marker, API back
#   restore_repoint.sh readers   <evidence>           after a cutover: add the readers the original had
#   restore_repoint.sh rollback  <evidence>           DOWNTIME: swap back; the restored cluster is left
#                                                     as <env>-db-abandoned-<time>
#   restore_repoint.sh keep      <evidence>           snapshot and deletion protection on the one
#                                                     cluster left out of the stack's names
#   restore_repoint.sh start-api <evidence>           put the API's recorded count and scaling back
#
# The only typed inputs are the environment and the restore time: every
# identifier, group, class and count is read from the stacks, the original
# cluster or the API service. cutover and rollback also ask for the stack's
# cluster identifier, typed at a terminal, so a pasted block cannot run them.
#
# Needs the AWS CLI with credentials for the environment's account, jq, and a
# checkout of the release the environment serves: the probe runs
# scripts/run_migration_task.sh and scripts/restore_probe.py from it. Evidence
# (state.env, log.txt, probe.log, parity.diff, the JSON read) goes in a new
# directory under the current one; it names the account's resources, so keep
# it out of the repository.
#
# Exit status: 0 done; 1 refused; 2 usage; anything else is the status of a
# command that failed (the AWS CLI's is 254). A cutover or rollback that stops
# part-way, for either reason, prints where every cluster is.
set -euo pipefail

POLL="${REPOINT_POLL_SECONDS:-15}"
WAIT_RESTORE_MIN="${REPOINT_WAIT_RESTORE_MIN:-180}"
WAIT_RENAME_MIN="${REPOINT_WAIT_RENAME_MIN:-30}"
WAIT_INSTANCE_MIN="${REPOINT_WAIT_INSTANCE_MIN:-60}"
WAIT_PROBE_MIN="${REPOINT_WAIT_PROBE_MIN:-30}"
WAIT_TASKS_MIN="${REPOINT_WAIT_TASKS_MIN:-10}"

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
EVID=""
SWAP_PHASE=""

usage() {
  printf 'usage: %s read <env> | restore <evidence> <UTC time> | cutover <evidence> | readers <evidence>\n       | rollback <evidence> | keep <evidence> | start-api <evidence>\n(the comment at the top of the script says what each does)\n' "$0" >&2
  exit 2
}
stamp() { date -u +%Y-%m-%dT%H:%M:%SZ; }
note() {
  if [ -n "$EVID" ]; then
    printf '%s %s\n' "$(stamp)" "$*" | tee -a "$EVID/log.txt" >&2
  else
    printf '%s %s\n' "$(stamp)" "$*" >&2
  fi
}
die() {
  printf 'REFUSED: %s\n' "$*" >&2
  if [ -n "$EVID" ] && [ -d "$EVID" ]; then
    printf '%s REFUSED: %s\n' "$(stamp)" "$*" >> "$EVID/log.txt"
  fi
  exit 1
}
# Refuse a value that was not read: empty, or the CLI's text for nothing.
need() {
  local v
  for v in "$@"; do
    case "${!v}" in "" | None | null) die "could not read $v (got '${!v}')" ;; esac
  done
}
save() {
  local v
  for v in "$@"; do printf '%s=%q\n' "$v" "${!v}" >> "$EVID/state.env"; done
}

# --- status: "absent" ONLY on the service's not-found error ------------------
# Any other error (an expired session, throttling) stops the script: it must
# never read as "the cluster is gone".
cluster_status() {
  local out
  if out=$(aws rds describe-db-clusters --db-cluster-identifier "$1" \
             --query 'DBClusters[0].Status' --output text 2> "$EVID/aws.err"); then
    printf '%s\n' "$out"
  elif grep -q 'DBClusterNotFoundFault' "$EVID/aws.err"; then
    printf 'absent\n'
  else
    printf 'describe-db-clusters %s failed: %s\n' "$1" "$(cat "$EVID/aws.err")" >&2
    return 1
  fi
}
instance_status() {
  local out
  if out=$(aws rds describe-db-instances --db-instance-identifier "$1" \
             --query 'DBInstances[0].DBInstanceStatus' --output text 2> "$EVID/aws.err"); then
    printf '%s\n' "$out"
  elif grep -q 'DBInstanceNotFound' "$EVID/aws.err"; then
    printf 'absent\n'
  else
    printf 'describe-db-instances %s failed: %s\n' "$1" "$(cat "$EVID/aws.err")" >&2
    return 1
  fi
}
wait_for() {  # <cluster|instance> <id> <status or absent> <minutes>
  local what=$1 id=$2 want=$3 minutes=$4 end s
  end=$(( $(date +%s) + minutes * 60 ))
  while :; do
    s=$("${what}_status" "$id")
    note "$what $id: $s (want $want)"
    if [ "$s" = "$want" ]; then return 0; fi
    if [ "$(date +%s)" -ge "$end" ]; then
      die "$what $id is still '$s' after $minutes min (wanted $want)"
    fi
    sleep "$POLL"
  done
}
members_of() {  # <cluster>: its instances, writer first, space-separated
  local json
  json=$(aws rds describe-db-clusters --db-cluster-identifier "$1" --output json)
  jq -r '.DBClusters[0].DBClusterMembers
         | sort_by(if .IsClusterWriter then 0 else 1 end)
         | map(.DBInstanceIdentifier) | join(" ")' <<<"$json"
}
cluster_arn() {
  aws rds describe-db-clusters --db-cluster-identifier "$1" \
    --query 'DBClusters[0].DBClusterArn' --output text
}

# --- the probe: is the hostname the tasks use the marked database? -----------
probe() {  # <host> <mode>: one task of the migration revision recorded by read
  local code net ov
  code=$(cat "$ROOT/scripts/restore_probe.py")
  net=$(jq -cn --arg s "$TASK_SUBNETS" --arg g "$TASK_SG" \
    '{awsvpcConfiguration: {subnets: ($s | split(",")), securityGroups: [$g], assignPublicIp: "DISABLED"}}')
  ov=$(jq -cn --arg code "$code" --arg host "$1" --arg id "$TS" --arg mode "$2" \
    '{containerOverrides: [{name: "backend", command: ["python", "-c", $code],
      environment: [{name: "POSTGRES_SERVER", value: $host}, {name: "RESTORE_ID", value: $id},
                    {name: "PROBE_MODE", value: $mode}]}]}')
  printf '\n%s probe %s %s\n' "$(stamp)" "$2" "$1" >> "$EVID/probe.log"
  MIGRATION_TIMEOUT_SECONDS=600 bash "$ROOT/scripts/run_migration_task.sh" \
    "$ECS" "$MIGRATE_TD" "$net" "$ov" "$MIGRATE_LOGS" >> "$EVID/probe.log" 2>&1
}
probe_until() {  # <host> <mode>: two passes in a row, within the deadline
  local end passes=0
  end=$(( $(date +%s) + WAIT_PROBE_MIN * 60 ))
  while :; do
    if probe "$1" "$2"; then
      passes=$((passes + 1)); note "probe $2 $1: pass $passes"
    else
      passes=0; note "probe $2 $1: not yet (probe.log has its output)"
    fi
    if [ "$passes" -ge 2 ]; then return 0; fi
    if [ "$(date +%s)" -ge "$end" ]; then
      die "the probe ($2) against $1 did not pass twice in a row within $WAIT_PROBE_MIN min"
    fi
    sleep "$POLL"
  done
}

# --- the API -------------------------------------------------------------------
refuse_deploy_in_flight() {
  local n
  n=$(aws deploy list-deployments --application-name "$CODEDEPLOY_APP" \
        --deployment-group-name "$CODEDEPLOY_GROUP" \
        --include-only-statuses Created Queued InProgress Baking Ready --output json |
      jq '.deployments | length')
  [ "$n" = 0 ] ||
    die "a CodeDeploy deployment of $CODEDEPLOY_GROUP is Created, Queued, InProgress, Baking or Ready: let it finish or stop it first. Nothing was changed"
}
stop_api() {
  local before running t end
  # shellcheck disable=SC1091
  . "$EVID/api.env"
  before=$(aws ecs list-tasks --cluster "$ECS" --family "$SVC" --output json | jq -r '.taskArns | join(" ")')
  trap swap_stopped EXIT
  aws application-autoscaling register-scalable-target --service-namespace ecs \
    --scalable-dimension ecs:service:DesiredCount --resource-id "$RID" --min-capacity 0 \
    --suspended-state DynamicScalingInSuspended=true,DynamicScalingOutSuspended=true,ScheduledScalingSuspended=true \
    > /dev/null
  aws ecs update-service --cluster "$ECS" --service "$SVC" --desired-count 0 > /dev/null
  note "API scaled to 0 (recorded: $API_DESIRED tasks, floor $API_MIN): DOWNTIME STARTS"
  end=$(( $(date +%s) + WAIT_TASKS_MIN * 60 ))
  while :; do
    running=$(( $(aws ecs list-tasks --cluster "$ECS" --family "$SVC" --desired-status RUNNING --output json | jq '.taskArns | length') \
              + $(aws ecs list-tasks --cluster "$ECS" --family "$MIGRATE_FAMILY" --desired-status RUNNING --output json | jq '.taskArns | length') ))
    t=0
    if [ -n "$before" ]; then
      # shellcheck disable=SC2086
      t=$(aws ecs describe-tasks --cluster "$ECS" --tasks $before --output json |
            jq '[.tasks[] | select(.lastStatus != "STOPPED")] | length')
    fi
    note "tasks: $running API or migration tasks desired RUNNING; $t of the API's earlier tasks not yet STOPPED"
    if [ "$running" = 0 ] && [ "$t" = 0 ]; then
      note "no API or migration task is running"
      return 0
    fi
    if [ "$(date +%s)" -ge "$end" ]; then
      die "tasks still running $WAIT_TASKS_MIN min after the API was scaled to 0 ($running desired RUNNING, $t not STOPPED); no cluster was renamed"
    fi
    sleep "$POLL"
  done
}
start_api() {
  local end n
  # shellcheck disable=SC1091
  . "$EVID/api.env"
  aws ecs update-service --cluster "$ECS" --service "$SVC" --desired-count "$API_DESIRED" > /dev/null
  aws application-autoscaling register-scalable-target --service-namespace ecs \
    --scalable-dimension ecs:service:DesiredCount --resource-id "$RID" \
    --min-capacity "$API_MIN" --max-capacity "$API_MAX" --suspended-state "$API_SUSPENDED" > /dev/null
  end=$(( $(date +%s) + WAIT_TASKS_MIN * 60 ))
  while :; do
    n=$(aws ecs describe-services --cluster "$ECS" --services "$SVC" \
          --query 'services[0].runningCount' --output text)
    note "API running $n of $API_DESIRED"
    if [ "$n" -ge "$API_DESIRED" ]; then
      note "API back at $API_DESIRED tasks, floor $API_MIN, scaling as recorded: check /health and the target group"
      return 0
    fi
    if [ "$(date +%s)" -ge "$end" ]; then
      die "the API has $n of $API_DESIRED tasks $WAIT_TASKS_MIN min after it was started"
    fi
    sleep "$POLL"
  done
}

# --- renames: always --apply-immediately (without it RDS waits for the -------
# maintenance window and reports success)
rename_cluster() {  # <from> <to>
  aws rds modify-db-cluster --db-cluster-identifier "$1" --new-db-cluster-identifier "$2" \
    --apply-immediately > /dev/null
  wait_for cluster "$2" available "$WAIT_RENAME_MIN"
  wait_for cluster "$1" absent "$WAIT_RENAME_MIN"
}
rename_instance() {  # <from> <to>
  aws rds modify-db-instance --db-instance-identifier "$1" --new-db-instance-identifier "$2" \
    --apply-immediately > /dev/null
  wait_for instance "$2" available "$WAIT_RENAME_MIN"
  wait_for instance "$1" absent "$WAIT_RENAME_MIN"
}

# cutover and rollback: the operator types the stack's cluster identifier at a
# terminal. A pipe or a here-document is refused, and a pasted block hands its
# next line to the prompt, which does not match.
confirm() {  # <phase>
  local typed=""
  [ -t 0 ] ||
    die "$1 reads its confirmation from a terminal: run it on its own line, not from a pipe or a here-document. Nothing was changed"
  printf '%s takes the API down and renames clusters. Type the cluster identifier %s to go on: ' \
    "$1" "$CLUSTER" >&2
  IFS= read -r typed || true
  [ "$typed" = "$CLUSTER" ] ||
    die "the confirmation was not the cluster identifier. Nothing was changed"
  note "$1 confirmed at the terminal"
}

swap_stopped() {
  local rc=$? id s
  [ "$rc" -ne 0 ] || return 0
  {
    printf '\n%s stopped part-way. The API was scaled to 0 for it and has not been put back.\n' "$SWAP_PHASE"
    printf 'Where the clusters are now:\n'
    for id in "$CLUSTER" "$TMP" "$FAILED" "$ABANDONED"; do
      s=$(cluster_status "$id" 2> /dev/null) || s="(could not be read)"
      printf '  %s: %s\n' "$id" "$s"
    done
    printf 'Next: docs/deployment/disaster-recovery.md#if-the-script-stops-part-way, with %s/log.txt.\n' "$EVID"
  } | tee -a "$EVID/log.txt" >&2
}

# swap <name the cluster now holding the stack's identifier leaves under>
#      <cluster that takes the identifier> <probe mode afterwards> <phase>
swap() {
  local out=$1 in=$2 mode=$3 phase=$4 holder s list j m endpoint arn
  local -a live incoming
  live=()
  s=$(cluster_status "$in")
  [ "$s" = available ] || die "$in is '$s', not available: there is nothing to $phase to. Nothing was changed"
  s=$(cluster_status "$out")
  [ "$s" = absent ] ||
    die "$out already exists ('$s'): an earlier $phase moved a cluster there. Nothing was changed; read log.txt"
  holder=$(cluster_status "$CLUSTER")
  case "$holder" in
    available)
      list=$(members_of "$CLUSTER")
      read -r -a live <<<"$list" ;;
    absent)
      # Only after a cutover that stopped between moving the original out and
      # moving the restored cluster in: the original is put back on its own.
      [ "$phase" = rollback ] || die "no cluster holds the stack's identifier $CLUSTER. Nothing was changed"
      ;;
    *) die "$CLUSTER is '$holder', not available. Nothing was changed" ;;
  esac
  list=$(members_of "$in")
  read -r -a incoming <<<"$list"
  [ "${#incoming[@]}" -ge 1 ] || die "$in has no instance. Nothing was changed"
  [ "${#incoming[@]}" -le "${#MEMBERS[@]}" ] ||
    die "$in has ${#incoming[@]} instances, more than the stack's ${#MEMBERS[@]}. Nothing was changed"
  refuse_deploy_in_flight
  confirm "$phase"

  SWAP_PHASE=$phase
  stop_api
  if [ "$holder" = available ]; then
    arn=$(cluster_arn "$CLUSTER")
    aws rds add-tags-to-resource --resource-name "$arn" \
      --tags "Key=experimently:left-identifier,Value=$CLUSTER" "Key=experimently:restore,Value=$TS" \
      > /dev/null
    rename_cluster "$CLUSTER" "$out"
    j=0
    for m in ${live[@]+"${live[@]}"}; do
      j=$((j + 1))
      rename_instance "$m" "$out-$j"
    done
  else
    note "no cluster holds $CLUSTER: $in goes back onto it, and nothing leaves"
  fi
  rename_cluster "$in" "$CLUSTER"
  endpoint=$(aws rds describe-db-clusters --db-cluster-identifier "$CLUSTER" \
               --query 'DBClusters[0].Endpoint' --output text)
  if [ "$endpoint" != "$ENDPOINT" ]; then
    if [ "$phase" = cutover ]; then
      die "the endpoint did not follow the identifier: '$endpoint' is not '$ENDPOINT'. The API is still at 0. Run: $0 rollback $EVID"
    fi
    die "the endpoint did not follow the identifier: '$endpoint' is not '$ENDPOINT'. The API is still at 0, and there is no scripted way on from here"
  fi
  note "endpoint unchanged: $endpoint"
  # The cluster on the stack's identifier carries none of this procedure's tags.
  arn=$(cluster_arn "$CLUSTER")
  aws rds remove-tags-from-resource --resource-name "$arn" \
    --tag-keys experimently:left-identifier experimently:restore > /dev/null
  j=0
  for m in "${incoming[@]}"; do
    if [ "$m" != "${MEMBERS[$j]}" ]; then rename_instance "$m" "${MEMBERS[$j]}"; fi
    j=$((j + 1))
  done
  probe_until "$ENDPOINT" "$mode"
  start_api
  trap - EXIT
  : > "$EVID/$phase.ok"
  note "DOWNTIME ENDS: $phase done; $CLUSTER is the cluster that was $in"
}

inst() { jq -r ".DBInstances[0]$2" "$EVID/original-instance-$1.json"; }
create_instance() {  # <new id> <cluster> <number of the original instance it copies>
  aws rds create-db-instance --db-instance-identifier "$1" --db-cluster-identifier "$2" \
    --engine "$ENGINE" --db-instance-class "$(inst "$3" .DBInstanceClass)" \
    --db-parameter-group-name "$(inst "$3" '.DBParameterGroups[0].DBParameterGroupName')" \
    --promotion-tier "$(inst "$3" .PromotionTier)" --no-publicly-accessible \
    --tags "$(jq -c '[.DBInstances[0].TagList // [] | .[] | select(.Key | startswith("aws:") | not)]' \
               "$EVID/original-instance-$3.json")" \
    > /dev/null
  note "creating instance $1 in $2 (a copy of the original's instance $3)"
  wait_for instance "$1" available "$WAIT_INSTANCE_MIN"
}

# --- phases ------------------------------------------------------------------
phase_read() {
  local env=$1 c_json host fam re json n m
  re='^[a-z][a-z0-9]*$'
  [[ "$env" =~ $re ]] || die "the environment '$env' is not lower-case letters and digits"
  ENV=$env
  TS=$(date -u +%Y%m%d%H%M%S)
  EVID="$PWD/restore-$ENV-$TS"
  mkdir "$EVID"
  : > "$EVID/state.env"
  : > "$EVID/log.txt"
  stack_output() {
    aws cloudformation describe-stacks --stack-name "$1" \
      --query "Stacks[0].Outputs[?OutputKey=='$2'].OutputValue | [0]" --output text
  }
  CLUSTER=$(stack_output "experimentation-database-$ENV" ClusterIdentifier)
  TASK_SUBNETS=$(stack_output "experimentation-fargate-$ENV" TaskSubnets)
  TASK_SG=$(stack_output "experimentation-fargate-$ENV" TaskSecurityGroup)
  need CLUSTER TASK_SUBNETS TASK_SG

  aws rds describe-db-clusters --db-cluster-identifier "$CLUSTER" --output json > "$EVID/original-cluster.json"
  c_json="$EVID/original-cluster.json"
  c() { jq -r ".DBClusters[0]$1" "$c_json"; }
  [ "$(c .Status)" = available ] ||
    die "the original cluster is '$(c .Status)', not available: renaming it is not a decided path (docs/deployment/disaster-recovery.md#scenario-4-full-aurora-database-cluster-failure)"
  ENDPOINT=$(c .Endpoint)
  ENGINE=$(c .Engine)
  SUBNET_GROUP=$(c .DBSubnetGroup)
  CLUSTER_PG=$(c .DBClusterParameterGroup)
  SG_LIST=$(c '.VpcSecurityGroups | map(.VpcSecurityGroupId) | sort | join(" ")')
  MEMBER_LIST=$(c '.DBClusterMembers | sort_by(if .IsClusterWriter then 0 else 1 end) | map(.DBInstanceIdentifier) | join(" ")')
  need ENDPOINT ENGINE SUBNET_GROUP CLUSTER_PG SG_LIST MEMBER_LIST
  read -r -a MEMBERS <<<"$MEMBER_LIST"
  n=0
  for m in "${MEMBERS[@]}"; do
    n=$((n + 1))
    aws rds describe-db-instances --db-instance-identifier "$m" --output json > "$EVID/original-instance-$n.json"
  done

  # The original must be exactly what the database stack names: the cluster,
  # its groups, and its instances. RDS stores identifiers in lower case.
  aws cloudformation describe-stack-resources --stack-name "experimentation-database-$ENV" \
    --output json > "$EVID/stack-resources.json"
  phys() {
    jq -r --arg t "$1" '[.StackResources[] | select(.ResourceType == $t) | .PhysicalResourceId
                         | ascii_downcase] | sort | join(" ")' "$EVID/stack-resources.json"
  }
  [ "$(phys AWS::RDS::DBCluster)" = "$(tr '[:upper:]' '[:lower:]' <<<"$CLUSTER")" ] ||
    die "the stack output names $CLUSTER, but the stack's cluster is '$(phys AWS::RDS::DBCluster)'"
  [ "$(phys AWS::RDS::DBClusterParameterGroup)" = "$CLUSTER_PG" ] ||
    die "the original uses the cluster parameter group $CLUSTER_PG, the stack's is '$(phys AWS::RDS::DBClusterParameterGroup)'"
  [ "$(phys AWS::RDS::DBSubnetGroup)" = "$SUBNET_GROUP" ] ||
    die "the original's subnet group $SUBNET_GROUP is not the stack's '$(phys AWS::RDS::DBSubnetGroup)'"
  [ "$(phys AWS::EC2::SecurityGroup)" = "$SG_LIST" ] ||
    die "the original's VPC groups ($SG_LIST) are not the stack's ('$(phys AWS::EC2::SecurityGroup)')"
  [ "$(phys AWS::RDS::DBInstance)" = "$(tr ' ' '\n' <<<"$MEMBER_LIST" | sort | paste -sd' ' -)" ] ||
    die "the stack's instances ('$(phys AWS::RDS::DBInstance)') are not the cluster's members ($MEMBER_LIST)"
  n=0
  for m in "${MEMBERS[@]}"; do
    n=$((n + 1))
    [ "$(inst "$n" '.DBParameterGroups[0].DBParameterGroupName')" = "$(phys AWS::RDS::DBParameterGroup)" ] ||
      die "instance $m does not use the stack's instance parameter group '$(phys AWS::RDS::DBParameterGroup)'"
  done

  ECS="experimentation-$ENV"
  SVC="experimentation-backend-$ENV"
  RID="service/$ECS/$SVC"
  MIGRATE_FAMILY="experimentation-migrate-$ENV"
  MIGRATE_LOGS="/ecs/experimentation-migrate-$ENV"
  CODEDEPLOY_APP="experimentation-platform-$ENV"
  CODEDEPLOY_GROUP="experimentation-$ENV"
  # Both task families must take the database host from the cluster endpoint:
  # that is what makes a rename the whole repoint.
  for fam in "$SVC" "$MIGRATE_FAMILY"; do
    aws ecs describe-task-definition --task-definition "$fam" --output json > "$EVID/task-definition-$fam.json"
    host=$(jq -r '[.taskDefinition.containerDefinitions[] | select(.name == "backend")
                   | .environment // [] | .[] | select(.name == "POSTGRES_SERVER") | .value]
                  | if length == 1 then .[0] else "" end' "$EVID/task-definition-$fam.json")
    [ "$host" = "$ENDPOINT" ] ||
      die "$fam's newest revision reads POSTGRES_SERVER='$host', not the cluster endpoint $ENDPOINT"
  done
  # The probe runs this revision, recorded now, and only if its image is
  # pinned by digest: after a cdk deploy the family's newest revision is
  # CloudFormation's, which names a tag.
  json="$EVID/task-definition-$MIGRATE_FAMILY.json"
  MIGRATE_TD=$(jq -r '.taskDefinition.taskDefinitionArn' "$json")
  MIGRATE_IMAGE=$(jq -r '[.taskDefinition.containerDefinitions[] | select(.name == "backend") | .image]
                         | if length == 1 then .[0] else "" end' "$json")
  re='@sha256:[0-9a-f]{64}$'
  [[ "$MIGRATE_IMAGE" =~ $re ]] ||
    die "the newest revision of $MIGRATE_FAMILY (${MIGRATE_TD##*/}) runs '${MIGRATE_IMAGE##*/}', not an image pinned by digest. Register a revision naming the image the API serves (scripts/register_task_definition.sh $MIGRATE_FAMILY <repository@sha256:...>), then run read again"

  # What cutover and rollback put back: the API's count and scaling now.
  aws ecs describe-services --cluster "$ECS" --services "$SVC" --output json > "$EVID/service-before.json"
  aws application-autoscaling describe-scalable-targets --service-namespace ecs \
    --resource-ids "$RID" --scalable-dimension ecs:service:DesiredCount \
    --output json > "$EVID/scaling-before.json"
  [ "$(jq '.ScalableTargets | length' "$EVID/scaling-before.json")" = 1 ] ||
    die "the API service $RID has no scalable target"
  API_DESIRED=$(jq -r '.services[0].desiredCount' "$EVID/service-before.json")
  API_MIN=$(jq -r '.ScalableTargets[0].MinCapacity' "$EVID/scaling-before.json")
  API_MAX=$(jq -r '.ScalableTargets[0].MaxCapacity' "$EVID/scaling-before.json")
  API_SUSPENDED=$(jq -r '.ScalableTargets[0].SuspendedState // {} |
    "DynamicScalingInSuspended=\(.DynamicScalingInSuspended // false),DynamicScalingOutSuspended=\(.DynamicScalingOutSuspended // false),ScheduledScalingSuspended=\(.ScheduledScalingSuspended // false)"' \
    "$EVID/scaling-before.json")
  re='^[1-9][0-9]*$'
  [[ "$API_DESIRED" =~ $re ]] && [[ "$API_MIN" =~ $re ]] ||
    die "the API runs $API_DESIRED tasks with a floor of $API_MIN: read records what cutover puts back, so run it while the API serves (before Scenario 8's Step 1)"
  {
    printf 'API_DESIRED=%q\n' "$API_DESIRED"
    printf 'API_MIN=%q\n' "$API_MIN"
    printf 'API_MAX=%q\n' "$API_MAX"
    printf 'API_SUSPENDED=%q\n' "$API_SUSPENDED"
  } > "$EVID/api.env"

  TMP="$ENV-db-restore-$TS"
  FAILED="$ENV-db-failed-$TS"
  ABANDONED="$ENV-db-abandoned-$TS"
  save ENV TS CLUSTER ENDPOINT ENGINE SUBNET_GROUP CLUSTER_PG SG_LIST MEMBER_LIST \
       TASK_SUBNETS TASK_SG ECS SVC RID MIGRATE_FAMILY MIGRATE_TD MIGRATE_LOGS \
       CODEDEPLOY_APP CODEDEPLOY_GROUP TMP FAILED ABANDONED
  note "recorded $CLUSTER ($ENDPOINT), instances $MEMBER_LIST; probe revision ${MIGRATE_TD##*/}; API $API_DESIRED tasks, floor $API_MIN; restorable $(c .EarliestRestorableTime) to $(c .LatestRestorableTime)"
  printf '%s\n' "$EVID"
}

phase_restore() {
  local s re parity iparity id
  RESTORE_TIME=$1
  re='^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$'
  [[ "$RESTORE_TIME" =~ $re ]] ||
    die "the restore time '$RESTORE_TIME' is not UTC in the form 2026-10-06T12:00:00Z"
  for id in "$FAILED" "$ABANDONED"; do
    s=$(cluster_status "$id")
    [ "$s" = absent ] || die "$id exists ('$s'): this evidence directory was cut over already"
  done
  # Resumable: a restored cluster from an earlier run of this phase is checked,
  # not restored again.
  s=$(cluster_status "$TMP")
  if [ "$s" = absent ]; then
    aws rds restore-db-cluster-to-point-in-time --source-db-cluster-identifier "$CLUSTER" \
      --db-cluster-identifier "$TMP" --restore-to-time "$RESTORE_TIME" \
      --db-subnet-group-name "$SUBNET_GROUP" --vpc-security-group-ids "${SG_IDS[@]}" \
      --db-cluster-parameter-group-name "$CLUSTER_PG" --copy-tags-to-snapshot \
      --output json > "$EVID/restore.json"
    save RESTORE_TIME
    note "restore of $CLUSTER to $RESTORE_TIME started as $TMP"
  else
    note "$TMP exists ('$s'): checking it, not restoring again"
  fi
  wait_for cluster "$TMP" available "$WAIT_RESTORE_MIN"
  aws rds describe-db-clusters --db-cluster-identifier "$TMP" --output json > "$EVID/restored-cluster.json"
  parity='.DBClusters[0] | {DBClusterParameterGroup, DBSubnetGroup,
    VpcSecurityGroups: (.VpcSecurityGroups | map(.VpcSecurityGroupId) | sort), KmsKeyId,
    StorageEncrypted, Engine, EngineVersion, Port, MasterUsername, DatabaseName,
    BackupRetentionPeriod, CopyTagsToSnapshot, DeletionProtection, IAMDatabaseAuthenticationEnabled}'
  diff <(jq -S "$parity" "$EVID/original-cluster.json") <(jq -S "$parity" "$EVID/restored-cluster.json") \
    > "$EVID/parity.diff" ||
    die "the restored cluster differs from the original (parity.diff): change $TMP to match, then run restore again. No cutover until then"
  note "cluster parity: identical on every compared field"
  s=$(instance_status "$TMP-1")
  if [ "$s" = absent ]; then create_instance "$TMP-1" "$TMP" 1; fi
  wait_for instance "$TMP-1" available "$WAIT_INSTANCE_MIN"
  aws rds describe-db-instances --db-instance-identifier "$TMP-1" --output json > "$EVID/restored-instance-1.json"
  iparity='.DBInstances[0] | {DBInstanceClass, Engine, PubliclyAccessible,
    DBParameterGroups: (.DBParameterGroups | map({DBParameterGroupName, ParameterApplyStatus})),
    DBSubnetGroup: .DBSubnetGroup.DBSubnetGroupName}'
  diff <(jq -S "$iparity" "$EVID/original-instance-1.json") <(jq -S "$iparity" "$EVID/restored-instance-1.json") \
    >> "$EVID/parity.diff" ||
    die "the restored writer differs from the original's (parity.diff). No cutover until it matches"
  TMP_ENDPOINT=$(jq -r '.DBClusters[0].Endpoint' "$EVID/restored-cluster.json")
  need TMP_ENDPOINT
  save TMP_ENDPOINT
  probe "$TMP_ENDPOINT" mark ||
    die "the probe could not mark $TMP. 'password authentication failed' in probe.log means the stack's secret does not open the restored cluster (the password was changed after the restore time)"
  probe "$ENDPOINT" expect-unmarked ||
    die "the probe reads the original as marked, or could not read it (probe.log): it cannot tell the two apart"
  : > "$EVID/restore.ok"
  note "restored $TMP is marked and opens with the stack's secret; the original is unmarked. Check the data on $TMP_ENDPOINT, then: $0 cutover $EVID"
}

phase_readers() {
  local j m s
  [ -f "$EVID/cutover.ok" ] || die "readers runs after a finished cutover (no cutover.ok)"
  if [ "${#MEMBERS[@]}" -le 1 ]; then
    note "the original had no reader: nothing to add"
    return 0
  fi
  j=1
  while [ "$j" -lt "${#MEMBERS[@]}" ]; do
    m=${MEMBERS[$j]}
    s=$(instance_status "$m")
    [ "$s" = absent ] || die "$m exists ('$s')"
    create_instance "$m" "$CLUSTER" $((j + 1))
    j=$((j + 1))
  done
  note "readers added: ${MEMBERS[*]:1}"
}

phase_keep() {
  local left="" id s
  for id in "$FAILED" "$ABANDONED" "$TMP"; do
    s=$(cluster_status "$id")
    if [ "$s" != absent ]; then
      [ -z "$left" ] || die "both $left and $id are out of the stack's names: finish or undo the swap first"
      left=$id
    fi
  done
  [ -n "$left" ] || die "no cluster of this restore is out of the stack's names"
  aws rds create-db-cluster-snapshot --db-cluster-identifier "$left" \
    --db-cluster-snapshot-identifier "$left-kept" > /dev/null
  aws rds modify-db-cluster --db-cluster-identifier "$left" --deletion-protection \
    --apply-immediately > /dev/null
  note "$left: snapshot $left-kept requested, deletion protection on. Deleting it is a human decision, taken at the time"
}

load() {
  [ -f "$1/state.env" ] || die "'$1' is not an evidence directory (no state.env): give the directory read printed"
  EVID=$(cd "$1" && pwd)
  # shellcheck disable=SC1091
  . "$EVID/state.env"
  read -r -a MEMBERS <<<"$MEMBER_LIST"
  read -r -a SG_IDS <<<"$SG_LIST"
}

command -v aws > /dev/null || die "the AWS CLI is not on PATH"
command -v jq > /dev/null || die "jq is not on PATH"
cmd=${1:-}
case "$cmd" in
  read)
    [ "$#" -eq 2 ] || usage
    phase_read "$2" ;;
  restore)
    [ "$#" -eq 3 ] || usage
    load "$2"
    phase_restore "$3" ;;
  cutover | rollback | readers | keep | start-api)
    [ "$#" -eq 2 ] || usage
    load "$2"
    case "$cmd" in
      cutover)
        [ -f "$EVID/restore.ok" ] || die "the restore phase did not finish (no restore.ok): no cutover"
        swap "$FAILED" "$TMP" expect-marked cutover ;;
      rollback)
        swap "$ABANDONED" "$FAILED" expect-unmarked rollback ;;
      readers) phase_readers ;;
      keep) phase_keep ;;
      start-api)
        start_api
        note "API put back at the recorded count and scaling; no rename was undone" ;;
    esac ;;
  *) usage ;;
esac
