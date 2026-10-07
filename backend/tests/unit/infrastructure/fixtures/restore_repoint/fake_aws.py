"""A stateful fake `aws` for scripts/restore_repoint.sh (test_restore_repoint.py).

It holds one environment's database stack, Fargate stack, API service and
migration task family in a JSON file (FAKE_STATE), answers the calls the script
makes, and changes the state the way the restore path's specification models
AWS: a rename moves a cluster or an instance to its new identifier (status
`renaming` once, then `available`) and the old identifier answers
DBClusterNotFoundFault / DBInstanceNotFound; a cluster's writer endpoint is its
identifier plus a suffix that is the same for every cluster in the account; a
probe task reads the marker of whichever cluster its hostname resolves to.

That model is the specification's, not AWS's: these tests prove the script's
control flow and its refusals, never what RDS does. `faults` in the state
plants one defect each:

    suffix_per_cluster   the endpoint suffix is per cluster (the endpoint text
                         does not survive a rename)
    ignore_parameter_group  the restore lands in the engine's default group
    stuck_task           one API task never stops
    password_rotated     the restored cluster refuses the secret's password
    rename_deferred      a rename is accepted and not applied
    dns_lag              a renamed-onto hostname resolves to its previous
                         holder for this many more probe runs
    marker_everywhere    every database reads as marked
    describe_error       {"id": ..., "code": ..., "kind": "cluster"|"instance"}:
                         describing that cluster (the default) or instance
                         fails with that error code, as an expired session does
    refuse_rename_of     renaming the cluster with this identifier fails
                         (InvalidDBClusterStateFault)
    stop_lag             scaling the API to 0 marks its tasks desired STOPPED
                         at once, and each stays last RUNNING for this many
                         more describe-tasks answers (ECS drains them)
    writer_pending_reboot   a created instance's parameter group is
                         `pending-reboot`, not `in-sync`
    ghost_after_rename   "cluster" or "instance": a rename of that kind leaves
                         the old identifier answering `available` (renames are
                         then immediate, with no `renaming` answer first)
    strict_tag_removal   removing a tag key the cluster does not carry fails
                         (the pessimistic reading of RDS, which is unmeasured)
    api_does_not_start   scaling the API up starts no task
    no_endpoint          describing this cluster gives no Endpoint
    restore_error_after_create  the point-in-time restore makes the cluster,
                         then the call fails as the CLI does when the
                         connection closes before the answer (exit 255)

`"scaling": null` in the state is an API service with no scalable target.

Every rename made while an API or migration task is not yet STOPPED is
recorded in `renamed_while_running`.

Every call is appended to `calls.log` (one JSON list of arguments per line);
anything it does not know, and any delete, exits 99.
"""

import json
import os
import sys

STATE = os.environ["FAKE_STATE"]
CALLS = os.path.join(os.path.dirname(STATE), "calls.log")
ARGS = sys.argv[1:]
with open(CALLS, "a") as log:
    log.write(json.dumps(ARGS) + "\n")
with open(STATE) as handle:
    st = json.load(handle)
SVC, OP, REST = ARGS[0], ARGS[1], ARGS[2:]
FAULTS = st.get("faults", {})
REGION = "us-west-2"
ACCOUNT = "111111111111"


def save():
    with open(STATE, "w") as handle:
        json.dump(st, handle, indent=1)


def opt(name, default=None):
    """A flag's value, True for a flag given no value, or `default`."""
    if name not in REST:
        return default
    i = REST.index(name)
    if i + 1 < len(REST) and not REST[i + 1].startswith("--"):
        return REST[i + 1]
    return True


def opts(name):
    """Every value given to a flag that takes a list."""
    out = []
    for value in REST[REST.index(name) + 1 :]:
        if value.startswith("--"):
            break
        out.append(value)
    return out


def emit(obj):
    query, output = opt("--query"), opt("--output", "json")
    if query:
        import jmespath

        obj = jmespath.search(query, obj)
    if output == "text":
        values = obj if isinstance(obj, list) else [obj]
        print("\t".join("None" if v is None else str(v) for v in values))
    else:
        print(json.dumps(obj, indent=4))
    save()
    sys.exit(0)


def fail(code, operation, message):
    print(
        f"\nAn error occurred ({code}) when calling the {operation} operation: {message}",
        file=sys.stderr,
    )
    save()
    sys.exit(254)


def unexpected(why):
    print(f"fake aws: {why}: {' '.join(ARGS)}", file=sys.stderr)
    save()
    sys.exit(99)


def endpoint(cid):
    c = st["clusters"][cid]
    suffix = c["suffix"] if FAULTS.get("suffix_per_cluster") else st["account_suffix"]
    return f"{cid}.cluster-{suffix}.{REGION}.rds.amazonaws.com"


def by_uid(uid):
    return next((cid for cid, c in st["clusters"].items() if c["uid"] == uid), None)


def settle(record, busy):
    """The status to report: `busy` for the pending describes, then available."""
    if record.get("pending", 0) > 0:
        record["pending"] -= 1
        return busy
    if record["Status"] in ("renaming", "creating", "modifying"):
        record["Status"] = "available"
    return record["Status"]


def members(cid):
    out = [
        i
        for i, x in st["instances"].items()
        if x["cluster"] == cid and not x.get("ghost")
    ]
    return sorted(out, key=lambda i: (not st["instances"][i]["writer"], i))


def cluster_view(cid):
    c = st["clusters"][cid]
    status = settle(c, c["Status"])
    view = {
        k: c[k]
        for k in (
            "Engine",
            "EngineVersion",
            "DBSubnetGroup",
            "DBClusterParameterGroup",
            "KmsKeyId",
            "StorageEncrypted",
            "Port",
            "MasterUsername",
            "DatabaseName",
            "BackupRetentionPeriod",
            "CopyTagsToSnapshot",
            "DeletionProtection",
            "IAMDatabaseAuthenticationEnabled",
        )
    }
    view.update(
        DBClusterIdentifier=cid,
        Status=status,
        Endpoint=None if FAULTS.get("no_endpoint") == cid else endpoint(cid),
        DBClusterArn=f"arn:aws:rds:{REGION}:{ACCOUNT}:cluster:{cid}",
        VpcSecurityGroups=[
            {"VpcSecurityGroupId": g, "Status": "active"} for g in c["sgs"]
        ],
        DBClusterMembers=[
            {"DBInstanceIdentifier": m, "IsClusterWriter": st["instances"][m]["writer"]}
            for m in members(cid)
        ],
        EarliestRestorableTime="2026-09-01T00:00:00+00:00",
        LatestRestorableTime="2026-10-06T13:00:00+00:00",
    )
    return view


def instance_view(iid):
    x = st["instances"][iid]
    status = settle(x, x["Status"])
    return {
        "DBInstanceIdentifier": iid,
        "DBInstanceStatus": status,
        "DBInstanceClass": x["class"],
        "Engine": "aurora-postgresql",
        "PubliclyAccessible": x["public"],
        "PromotionTier": x["tier"],
        "DBClusterIdentifier": x["cluster"],
        "DBParameterGroups": [
            {
                "DBParameterGroupName": x["pg"],
                "ParameterApplyStatus": x.get("apply", "in-sync"),
            }
        ],
        "DBSubnetGroup": {
            "DBSubnetGroupName": st["clusters"][x["cluster"]]["DBSubnetGroup"]
        },
        "TagList": x["tags"],
    }


def tags_from(values):
    """`--tags` as JSON or as `Key=k,Value=v` shorthand, one per value."""
    if len(values) == 1 and values[0].startswith("["):
        return json.loads(values[0])
    return [dict(kv.split("=", 1) for kv in v.split(",")) for v in values]


def task_definition(ref):
    family = ref.split(":task-definition/")[-1].split(":")[0]
    td = st["task_definitions"].get(family)
    if td is None:
        fail(
            "ClientException",
            "DescribeTaskDefinition",
            "Unable to describe task definition.",
        )
    revision = (
        int(ref.rsplit(":", 1)[1]) if ":task-definition/" in ref else td["newest"]
    )
    rev = td["revisions"][str(revision)]
    return {
        "taskDefinitionArn": f"arn:aws:ecs:{REGION}:{ACCOUNT}:task-definition/{family}:{revision}",
        "family": family,
        "revision": revision,
        "containerDefinitions": [
            {
                "name": "backend",
                "image": rev["image"],
                "environment": [{"name": "POSTGRES_SERVER", "value": rev["host"]}],
            }
        ],
    }


def note_rename(what):
    """Record a rename made while an API or migration task is not STOPPED."""
    busy = [
        arn
        for arn, t in st["tasks"].items()
        if t["family"].startswith(
            ("experimentation-backend", "experimentation-migrate")
        )
        and t["last"] != "STOPPED"
    ]
    if busy:
        st.setdefault("renamed_while_running", []).append(
            {"rename": what, "tasks": busy}
        )


# --- cloudformation ------------------------------------------------------------
if SVC == "cloudformation" and OP == "describe-stacks":
    name = opt("--stack-name")
    outputs = st["outputs"].get(name)
    if outputs is None:
        fail(
            "ValidationError", "DescribeStacks", f"Stack with id {name} does not exist"
        )
    emit(
        {
            "Stacks": [
                {
                    "StackName": name,
                    "Outputs": [
                        {"OutputKey": k, "OutputValue": v} for k, v in outputs.items()
                    ],
                }
            ]
        }
    )

if SVC == "cloudformation" and OP == "describe-stack-resources":
    s = st["stack"]
    resources = [
        ("AWS::RDS::DBCluster", s["cluster"]),
        ("AWS::RDS::DBClusterParameterGroup", s["cluster_pg"]),
        ("AWS::RDS::DBParameterGroup", s["instance_pg"]),
        ("AWS::RDS::DBSubnetGroup", s["subnet_group"]),
        ("AWS::EC2::SecurityGroup", s["sg"]),
        ("AWS::KMS::Key", "k"),
    ] + [("AWS::RDS::DBInstance", i) for i in s["instances"]]
    emit(
        {
            "StackResources": [
                {
                    "ResourceType": t,
                    "PhysicalResourceId": p,
                    "LogicalResourceId": f"R{n}",
                }
                for n, (t, p) in enumerate(resources)
            ]
        }
    )

# --- rds -------------------------------------------------------------------------
if SVC == "rds" and OP == "describe-db-clusters":
    cid = opt("--db-cluster-identifier")
    error = FAULTS.get("describe_error")
    if error and error["id"] == cid and error.get("kind", "cluster") == "cluster":
        fail(error["code"], "DescribeDBClusters", "The session has expired")
    if cid not in st["clusters"]:
        fail(
            "DBClusterNotFoundFault",
            "DescribeDBClusters",
            f"DBCluster {cid} not found.",
        )
    emit({"DBClusters": [cluster_view(cid)]})

if SVC == "rds" and OP == "describe-db-instances":
    iid = opt("--db-instance-identifier")
    error = FAULTS.get("describe_error")
    if error and error["id"] == iid and error.get("kind") == "instance":
        fail(error["code"], "DescribeDBInstances", "Rate exceeded")
    if iid not in st["instances"]:
        fail(
            "DBInstanceNotFound", "DescribeDBInstances", f"DBInstance {iid} not found."
        )
    emit({"DBInstances": [instance_view(iid)]})

if SVC == "rds" and OP == "restore-db-cluster-to-point-in-time":
    source, new = opt("--source-db-cluster-identifier"), opt("--db-cluster-identifier")
    if new in st["clusters"]:
        fail("DBClusterAlreadyExistsFault", "RestoreDBClusterToPointInTime", new)
    c = json.loads(json.dumps(st["clusters"][source]))
    st["uid"] += 1
    group = opt("--db-cluster-parameter-group-name") or "default.aurora-postgresql15"
    c.update(
        uid=st["uid"],
        Status="creating",
        pending=1,
        suffix="r%04d" % st["uid"],
        marker=None,
        tags=[],
        DeletionProtection=False,
        DBSubnetGroup=opt("--db-subnet-group-name") or "default",
        sgs=opts("--vpc-security-group-ids")
        if "--vpc-security-group-ids" in REST
        else ["sg-default"],
        DBClusterParameterGroup="default.aurora-postgresql15"
        if FAULTS.get("ignore_parameter_group")
        else group,
        CopyTagsToSnapshot="--copy-tags-to-snapshot" in REST,
        password="rotated" if FAULTS.get("password_rotated") else c["password"],
    )
    st["clusters"][new] = c
    if FAULTS.get("restore_error_after_create"):
        print(
            "\nConnection was closed before we received a valid response from"
            f' endpoint URL: "https://rds.{REGION}.amazonaws.com/".',
            file=sys.stderr,
        )
        save()
        sys.exit(255)
    emit({"DBCluster": {"DBClusterIdentifier": new, "Status": "creating"}})

if SVC == "rds" and OP == "create-db-instance":
    iid, cid = opt("--db-instance-identifier"), opt("--db-cluster-identifier")
    if iid in st["instances"]:
        fail("DBInstanceAlreadyExists", "CreateDBInstance", iid)
    st["instances"][iid] = {
        "cluster": cid,
        "writer": not members(cid),
        "class": opt("--db-instance-class"),
        "pg": opt("--db-parameter-group-name") or "default.aurora-postgresql15",
        "apply": "pending-reboot" if FAULTS.get("writer_pending_reboot") else "in-sync",
        "public": "--no-publicly-accessible" not in REST,
        "tier": int(opt("--promotion-tier", 1)),
        "Status": "creating",
        "pending": 1,
        "tags": tags_from(opts("--tags")) if "--tags" in REST else [],
    }
    emit({"DBInstance": {"DBInstanceIdentifier": iid, "DBInstanceStatus": "creating"}})

if SVC == "rds" and OP == "modify-db-cluster":
    cid = opt("--db-cluster-identifier")
    if cid not in st["clusters"]:
        fail("DBClusterNotFoundFault", "ModifyDBCluster", f"DBCluster {cid} not found.")
    new = opt("--new-db-cluster-identifier")
    if new:
        if FAULTS.get("refuse_rename_of") == cid:
            fail(
                "InvalidDBClusterStateFault",
                "ModifyDBCluster",
                f"{cid} cannot be renamed now",
            )
        if new in st["clusters"]:
            fail("DBClusterAlreadyExistsFault", "ModifyDBCluster", new)
        if "--apply-immediately" not in REST or FAULTS.get("rename_deferred"):
            emit({"DBCluster": {"DBClusterIdentifier": cid}})  # waits for the window
        note_rename(f"cluster {cid} -> {new}")
        moved = st["clusters"].pop(cid)
        st["clusters"][new] = moved
        moved.update(Status="renaming", pending=1)
        if FAULTS.get("ghost_after_rename"):
            moved.update(Status="available", pending=0)
        if FAULTS.get("ghost_after_rename") == "cluster":
            st["clusters"][cid] = dict(moved, uid=-1, Status="available")
        for x in st["instances"].values():
            if x["cluster"] == cid:
                x["cluster"] = new
        lag = FAULTS.get("dns_lag", 0)
        holder = st["dns_holder"].get(endpoint(new))
        if lag and holder is not None:
            st["dns_stale"][endpoint(new)] = {"uid": holder, "left": lag}
        st["dns_holder"][endpoint(new)] = moved["uid"]
    if "--deletion-protection" in REST:
        st["clusters"][new or cid]["DeletionProtection"] = True
    if "--no-deletion-protection" in REST:
        st["clusters"][new or cid]["DeletionProtection"] = False
    emit({"DBCluster": {"DBClusterIdentifier": new or cid}})

if SVC == "rds" and OP == "modify-db-instance":
    iid, new = opt("--db-instance-identifier"), opt("--new-db-instance-identifier")
    if iid not in st["instances"]:
        fail("DBInstanceNotFound", "ModifyDBInstance", f"DBInstance {iid} not found.")
    if new in st["instances"]:
        fail("DBInstanceAlreadyExists", "ModifyDBInstance", new)
    if "--apply-immediately" not in REST or FAULTS.get("rename_deferred"):
        emit({"DBInstance": {"DBInstanceIdentifier": iid}})
    note_rename(f"instance {iid} -> {new}")
    st["instances"][new] = st["instances"].pop(iid)
    st["instances"][new].update(Status="renaming", pending=1)
    if FAULTS.get("ghost_after_rename"):
        st["instances"][new].update(Status="available", pending=0)
    if FAULTS.get("ghost_after_rename") == "instance":
        st["instances"][iid] = dict(
            st["instances"][new], Status="available", ghost=True
        )
    emit({"DBInstance": {"DBInstanceIdentifier": new}})

if SVC == "rds" and OP in ("add-tags-to-resource", "remove-tags-from-resource"):
    cid = opt("--resource-name").rsplit(":", 1)[1]
    if cid not in st["clusters"]:
        fail("DBClusterNotFoundFault", "AddTagsToResource", cid)
    tags = st["clusters"][cid]["tags"]
    if OP == "add-tags-to-resource":
        for tag in tags_from(opts("--tags")):
            tags[:] = [t for t in tags if t["Key"] != tag["Key"]] + [tag]
    else:
        keys = set(opts("--tag-keys"))
        absent = keys - {t["Key"] for t in tags}
        if FAULTS.get("strict_tag_removal") and absent:
            fail(
                "InvalidParameterValue",
                "RemoveTagsFromResource",
                f"Tag keys {sorted(absent)} are not on the resource",
            )
        tags[:] = [t for t in tags if t["Key"] not in keys]
    emit({})

if SVC == "rds" and OP == "list-tags-for-resource":
    cid = opt("--resource-name").rsplit(":", 1)[1]
    if cid not in st["clusters"]:
        fail("DBClusterNotFoundFault", "ListTagsForResource", cid)
    emit({"TagList": st["clusters"][cid]["tags"]})

if SVC == "rds" and OP == "create-db-cluster-snapshot":
    cid, sid = opt("--db-cluster-identifier"), opt("--db-cluster-snapshot-identifier")
    if cid not in st["clusters"]:
        fail("DBClusterNotFoundFault", "CreateDBClusterSnapshot", cid)
    if sid in st["snapshots"]:
        fail("DBClusterSnapshotAlreadyExistsFault", "CreateDBClusterSnapshot", sid)
    st["snapshots"][sid] = {"cluster_uid": st["clusters"][cid]["uid"]}
    emit({"DBClusterSnapshot": {"DBClusterSnapshotIdentifier": sid}})

# --- ecs ---------------------------------------------------------------------------
if SVC == "ecs" and OP == "describe-task-definition":
    emit({"taskDefinition": task_definition(opt("--task-definition"))})

if SVC == "ecs" and OP == "list-tasks":
    family, desired = opt("--family"), opt("--desired-status", "RUNNING")
    emit(
        {
            "taskArns": [
                arn
                for arn, t in st["tasks"].items()
                if t["family"] == family and t["desired"] == desired
            ]
        }
    )

if SVC == "ecs" and OP == "describe-tasks":
    for arn in opts("--tasks"):
        task = st["tasks"][arn]
        if task.get("draining", 0) > 0:
            task["draining"] -= 1
        elif task.get("draining") == 0:
            task["last"] = "STOPPED"
    emit(
        {
            "tasks": [
                {
                    "taskArn": arn,
                    "lastStatus": st["tasks"][arn]["last"],
                    "stoppedReason": "Essential container in task exited",
                    "containers": [
                        {"name": "backend", "exitCode": st["tasks"][arn].get("exit")}
                    ],
                }
                for arn in opts("--tasks")
            ],
            "failures": [],
        }
    )

if SVC == "ecs" and OP == "update-service":
    count = int(opt("--desired-count"))
    st["service"]["desired"] = count
    api = [a for a, t in st["tasks"].items() if t["family"] == st["service"]["family"]]
    if count == 0:
        for k, arn in enumerate(api):
            if FAULTS.get("stuck_task") and k == 0:
                continue
            if FAULTS.get("stop_lag"):
                st["tasks"][arn].update(desired="STOPPED", draining=FAULTS["stop_lag"])
            else:
                st["tasks"][arn].update(desired="STOPPED", last="STOPPED")
    elif not FAULTS.get("api_does_not_start"):
        for k in range(count):
            st["n"] += 1
            st["tasks"][f"arn:aws:ecs:{REGION}:{ACCOUNT}:task/started{st['n']}"] = {
                "family": st["service"]["family"],
                "desired": "RUNNING",
                "last": "RUNNING",
            }
    emit({"service": {"desiredCount": count}})

if SVC == "ecs" and OP == "describe-services":
    running = sum(
        1
        for t in st["tasks"].values()
        if t["family"] == st["service"]["family"] and t["last"] == "RUNNING"
    )
    emit(
        {
            "services": [
                {
                    "serviceName": st["service"]["family"],
                    "desiredCount": st["service"]["desired"],
                    "runningCount": running,
                }
            ],
            "failures": [],
        }
    )

if SVC == "ecs" and OP == "run-task":
    raw = opt("--overrides")
    override = json.loads(raw)["containerOverrides"][0]
    env = {e["name"]: e["value"] for e in override["environment"]}
    host, mode, rid = env["POSTGRES_SERVER"], env["PROBE_MODE"], env["RESTORE_ID"]
    stale = st["dns_stale"].get(host)
    if stale and stale["left"] > 0:
        stale["left"] -= 1
        target = by_uid(stale["uid"])
    else:
        target = next((c for c in st["clusters"] if endpoint(c) == host), None)
    marker = "experimently-restore " + rid
    if target is None:
        code = 1  # the name does not resolve
    elif st["clusters"][target]["password"] != st["secret_password"]:
        code = 1  # password authentication failed
    else:
        if mode == "mark":
            st["clusters"][target]["marker"] = marker
        found = (
            marker
            if FAULTS.get("marker_everywhere")
            else st["clusters"][target]["marker"]
        )
        holds = found != marker if mode == "expect-unmarked" else found == marker
        code = 0 if holds else 3
    st["n"] += 1
    arn = f"arn:aws:ecs:{REGION}:{ACCOUNT}:task/{st['cluster_name']}/probe{st['n']}"
    st["tasks"][arn] = {
        "family": opt("--task-definition").split("/")[-1].split(":")[0],
        "desired": "STOPPED",
        "last": "STOPPED",
        "exit": code,
        "log": f"PROBE {mode} target={target} exit={code}",
    }
    st["probes"].append(
        {
            "task_definition": opt("--task-definition"),
            "network": json.loads(opt("--network-configuration")),
            "overrides_bytes": len(raw.encode()),
            "command": override["command"],
            "env": env,
            "target": target,
            "exit": code,
        }
    )
    emit({"tasks": [{"taskArn": arn, "lastStatus": "PROVISIONING"}], "failures": []})

# --- application-autoscaling, codedeploy, logs ---------------------------------
if SVC == "application-autoscaling" and OP == "describe-scalable-targets":
    emit({"ScalableTargets": [st["scaling"]] if st["scaling"] else []})

if SVC == "application-autoscaling" and OP == "register-scalable-target":
    st["scaling"]["MinCapacity"] = int(opt("--min-capacity"))
    if opt("--max-capacity"):
        st["scaling"]["MaxCapacity"] = int(opt("--max-capacity"))
    if opt("--suspended-state"):
        pairs = dict(kv.split("=") for kv in opt("--suspended-state").split(","))
        st["scaling"]["SuspendedState"] = {k: v == "true" for k, v in pairs.items()}
    emit({})

if SVC == "deploy" and OP == "list-deployments":
    emit({"deployments": st["deployments"]})

if SVC == "logs" and OP == "get-log-events":
    task = opt("--log-stream-name").rsplit("/", 1)[1]
    found = next((t for a, t in st["tasks"].items() if a.endswith("/" + task)), {})
    emit({"events": [{"message": found.get("log", "")}]})

unexpected("unhandled call")
