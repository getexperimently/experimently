"""`scripts/restore_repoint.sh`: the decided restore path, against a fake `aws` (T143).

The script points the application at an Aurora cluster restored from
point-in-time recovery by renaming: the restored cluster and its writer take
the stack's identifiers, the original and its instances move aside, and the
API is at 0 tasks across the renames. Its specification is the principal
engineer's restore spec (the "full rename-swap") with the engineering
manager's sign-off conditions. This file drives every phase against
`fixtures/restore_repoint/fake_aws.py`, a stateful fake that models AWS the way
the specification does, so it proves the script's control flow and refusals
and nothing about RDS itself (the staging rehearsal does that):

* forward, back and `keep` on a one-instance cluster (staging's shape), under
  every distinct bash on this machine (macOS's /bin/bash is 3.2);
* the same with two instances (prod's shape), with `readers` between, which
  no rehearsal reaches;
* each refusal, planted and watched: the specification's T0-T6, the probe
  that cannot tell the clusters apart, the migration revision that names a
  tag, the confirmation that did not come from a terminal, an error that is
  not "not found", and the others its contract lists;
* what it must never do: delete anything, rename without
  `--apply-immediately`, rename while an API or migration task is not yet
  STOPPED (ECS marks a draining task desired STOPPED at once), run a probe
  on a revision other than the one `read` recorded, or run anything but the
  probe file's text;
* every flag it passes is one the AWS CLI has (botocore's service model);
* no workflow runs it and the deploy role gains nothing from it.

No AWS call is made: the fake is first on PATH and the credential chain is
blank.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.regression]

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT = REPO_ROOT / "scripts" / "restore_repoint.sh"
PROBE = REPO_ROOT / "scripts" / "restore_probe.py"
FAKE = Path(__file__).resolve().parent / "fixtures" / "restore_repoint" / "fake_aws.py"

REGION = "us-west-2"
ACCOUNT = "111111111111"
SUFFIX = "cabc123example"
DIGEST = "sha256:" + "d" * 64
SAFETY_NET_SECONDS = 120

#: Every distinct bash here: on macOS the Homebrew one and /bin/bash 3.2, on
#: CI's Linux the one bash.
BASHES = sorted(
    {
        os.path.realpath(b)
        for b in (shutil.which("bash"), "/bin/bash")
        if b and os.path.exists(b)
    }
)


def _bash_id(path: str) -> str:
    out = subprocess.run(
        [path, "-c", "printf %s ${BASH_VERSINFO[0]}.${BASH_VERSINFO[1]}"],
        capture_output=True,
        text=True,
        check=True,
    )
    return f"bash{out.stdout}"


@dataclass(frozen=True)
class Shape:
    env: str
    cluster: str
    instances: tuple[str, ...]
    instance_class: str
    desired: int

    @property
    def endpoint(self) -> str:
        return f"{self.cluster}.cluster-{SUFFIX}.{REGION}.rds.amazonaws.com"

    @property
    def migrate_family(self) -> str:
        return f"experimentation-migrate-{self.env}"


STAGING = Shape(
    env="staging",
    cluster="experimentation-database-staging-auroracluster-1a2b3c4d",
    instances=("experimentation-database-staging-auroraclusterinst-5e6f7a8b",),
    instance_class="db.t3.medium",
    desired=2,
)
PROD = Shape(
    env="prod",
    cluster="experimentation-database-prod-auroracluster-9c8d7e6f",
    instances=(
        "experimentation-database-prod-auroraclusterinst-1111aaaa",
        "experimentation-database-prod-auroraclusterinst-2222bbbb",
    ),
    instance_class="db.r5.large",
    desired=3,
)


def initial_state(shape: Shape, **faults) -> dict:
    """One environment as the CDK app deploys it (synth: one cluster parameter
    group, one instance parameter group, one subnet group, one VPC group in
    the database stack; staging one instance, prod two)."""
    db = f"experimentation-database-{shape.env}"
    cluster_pg = f"{db}-clusterparametergroup-aaa"
    instance_pg = f"{db}-instanceparametergroup-bbb"
    subnet = f"{db}-dbsubnetgroup-ccc"
    api = f"experimentation-backend-{shape.env}"
    ecs = f"experimentation-{shape.env}"
    return {
        "account_suffix": SUFFIX,
        "uid": 1,
        "n": 0,
        "clusters": {
            shape.cluster: {
                "uid": 1,
                "Status": "available",
                "suffix": SUFFIX,
                "marker": None,
                "tags": [{"Key": "Environment", "Value": shape.env}],
                "Engine": "aurora-postgresql",
                "EngineVersion": "15.17",
                "DBSubnetGroup": subnet,
                "DBClusterParameterGroup": cluster_pg,
                "KmsKeyId": f"arn:aws:kms:{REGION}:{ACCOUNT}:key/k",
                "StorageEncrypted": True,
                "Port": 5432,
                "MasterUsername": "postgres",
                "DatabaseName": "experimentation",
                "BackupRetentionPeriod": 35,
                "CopyTagsToSnapshot": True,
                "DeletionProtection": False,
                "IAMDatabaseAuthenticationEnabled": False,
                "sgs": ["sg-0db"],
                "password": "secret-value",
            }
        },
        "instances": {
            name: {
                "cluster": shape.cluster,
                "writer": n == 0,
                "class": shape.instance_class,
                "pg": instance_pg,
                "public": False,
                "tier": 1,
                "Status": "available",
                "tags": [
                    {"Key": "Environment", "Value": shape.env},
                    {"Key": "aws:cloudformation:stack-name", "Value": db},
                ],
            }
            for n, name in enumerate(shape.instances)
        },
        "secret_password": "secret-value",
        "stack": {
            "cluster": shape.cluster,
            "instances": list(shape.instances),
            "cluster_pg": cluster_pg,
            "instance_pg": instance_pg,
            "subnet_group": subnet,
            "sg": "sg-0db",
        },
        "outputs": {
            db: {"ClusterIdentifier": shape.cluster},
            f"experimentation-fargate-{shape.env}": {
                "TaskSubnets": "subnet-a,subnet-b",
                "TaskSecurityGroup": "sg-0tasks",
            },
        },
        "task_definitions": {
            api: {
                "newest": 12,
                "revisions": {
                    "12": {"image": f"repo/backend@{DIGEST}", "host": shape.endpoint}
                },
            },
            shape.migrate_family: {
                "newest": 7,
                "revisions": {
                    "7": {"image": f"repo/backend@{DIGEST}", "host": shape.endpoint}
                },
            },
        },
        "cluster_name": ecs,
        "service": {"family": api, "desired": shape.desired},
        "tasks": {
            f"arn:aws:ecs:{REGION}:{ACCOUNT}:task/{ecs}/old{k}": {
                "family": api,
                "desired": "RUNNING",
                "last": "RUNNING",
            }
            for k in range(shape.desired)
        },
        "scaling": {
            "ServiceNamespace": "ecs",
            "ResourceId": f"service/{ecs}/{api}",
            "ScalableDimension": "ecs:service:DesiredCount",
            "MinCapacity": shape.desired,
            "MaxCapacity": 10,
            "SuspendedState": {
                "DynamicScalingInSuspended": False,
                "DynamicScalingOutSuspended": False,
                "ScheduledScalingSuspended": False,
            },
        },
        "deployments": [],
        "snapshots": {},
        "probes": [],
        "dns_holder": {shape.endpoint: 1},
        "dns_stale": {},
        "faults": faults,
    }


@dataclass
class Result:
    code: int
    out: str
    err: str


class World:
    """One fake account, and the script run against it."""

    def __init__(self, tmp: Path, shape: Shape, **faults) -> None:
        self.tmp, self.shape = Path(tmp).resolve(), shape
        self.state_path = self.tmp / "state.json"
        self.state_path.write_text(json.dumps(initial_state(shape, **faults)))
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        shim = bin_dir / "aws"
        shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE}" "$@"\n')
        shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
        self.waits = {
            "REPOINT_POLL_SECONDS": "0",
            "REPOINT_WAIT_RESTORE_MIN": "1",
            "REPOINT_WAIT_RENAME_MIN": "1",
            "REPOINT_WAIT_INSTANCE_MIN": "1",
            "REPOINT_WAIT_PROBE_MIN": "1",
            "REPOINT_WAIT_TASKS_MIN": "0",
        }
        env = {k: v for k, v in os.environ.items() if not k.startswith("AWS_")}
        env.update(
            PATH=f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            FAKE_STATE=str(self.state_path),
            AWS_ACCESS_KEY_ID="",
            AWS_SECRET_ACCESS_KEY="",
            AWS_PROFILE="nonexistent",
            AWS_CONFIG_FILE="/dev/null",
            AWS_SHARED_CREDENTIALS_FILE="/dev/null",
            AWS_EC2_METADATA_DISABLED="true",
        )
        self.env = env
        self.evid = ""

    # --- running ---------------------------------------------------------------
    def run(
        self,
        *args: str,
        confirm: str | None = None,
        piped: str | None = None,
        bash: str = "bash",
        script: Path = SCRIPT,
        **waits: str,
    ) -> Result:
        env = {**self.env, **self.waits, **waits}
        command = [bash, str(script), *args]
        options = {
            "cwd": self.tmp,
            "env": env,
            "capture_output": True,
            "text": True,
            "timeout": SAFETY_NET_SECONDS,
        }
        if confirm is not None:
            # A terminal: the script reads the identifier typed at it.
            master, slave = os.openpty()
            os.write(master, (confirm + "\n").encode())
            try:
                done = subprocess.run(command, stdin=slave, **options)
            finally:
                os.close(slave)
                os.close(master)
        elif piped is not None:
            done = subprocess.run(command, input=piped, **options)
        else:
            done = subprocess.run(command, stdin=subprocess.DEVNULL, **options)
        return Result(done.returncode, done.stdout, done.stderr)

    def read(self, bash: str = "bash") -> str:
        result = self.run("read", self.shape.env, bash=bash)
        assert result.code == 0, result.err
        (evid,) = result.out.splitlines()
        assert Path(evid).is_dir() and Path(evid).parent == self.tmp
        self.evid = evid
        return evid

    def restore(self, bash: str = "bash") -> Result:
        return self.run("restore", self.evid, "2026-10-06T12:00:00Z", bash=bash)

    def cutover(self, bash: str = "bash", **kw) -> Result:
        kw.setdefault("confirm", self.shape.cluster)
        return self.run("cutover", self.evid, bash=bash, **kw)

    def rollback(self, bash: str = "bash", **kw) -> Result:
        kw.setdefault("confirm", self.shape.cluster)
        return self.run("rollback", self.evid, bash=bash, **kw)

    # --- reading the fake --------------------------------------------------------
    @property
    def state(self) -> dict:
        return json.loads(self.state_path.read_text())

    def mutate(self, change) -> None:
        state = self.state
        change(state)
        self.state_path.write_text(json.dumps(state))

    @property
    def calls(self) -> list[list[str]]:
        log = self.tmp / "calls.log"
        if not log.exists():
            return []
        return [json.loads(line) for line in log.read_text().splitlines()]

    def changes(self) -> list[list[str]]:
        """Every call that changes something in the account."""
        reads = ("describe-", "list-", "get-")
        return [c for c in self.calls if not c[1].startswith(reads)]

    def log(self) -> str:
        return (Path(self.evid) / "log.txt").read_text()

    def recorded(self, name: str) -> str:
        for line in (Path(self.evid) / "state.env").read_text().splitlines():
            key, _, value = line.partition("=")
            if key == name:
                return value
        raise KeyError(name)

    def names(self) -> dict:
        """{cluster: [its instances, writer first]}."""
        state = self.state
        return {
            cid: sorted(
                (i for i, x in state["instances"].items() if x["cluster"] == cid),
                key=lambda i: (not state["instances"][i]["writer"], i),
            )
            for cid in state["clusters"]
        }

    def holder_uid(self) -> int:
        """Which cluster (by its identity, not its name) holds the stack's identifier."""
        return self.state["clusters"][self.shape.cluster]["uid"]

    def api(self) -> tuple[int, int, bool]:
        state = self.state
        scaling = state["scaling"]
        return (
            state["service"]["desired"],
            scaling["MinCapacity"],
            any(scaling["SuspendedState"].values()),
        )


@pytest.fixture
def staging(tmp_path) -> World:
    return World(tmp_path, STAGING)


def renames(calls) -> list[list[str]]:
    return [
        c
        for c in calls
        if c[1] in ("modify-db-cluster", "modify-db-instance")
        and any(a.startswith("--new-db-") for a in c)
    ]


def refused(result: Result, *fragments: str) -> None:
    assert result.code == 1, (result.code, result.err)
    assert "REFUSED:" in result.err, result.err
    for fragment in fragments:
        assert fragment in result.err, (fragment, result.err)


def assert_never_deleted_or_deferred(world: World) -> None:
    for call in world.calls:
        assert not call[1].startswith("delete-"), call
    for call in renames(world.calls):
        assert "--apply-immediately" in call, call
    assert not world.state.get("renamed_while_running"), world.state[
        "renamed_while_running"
    ]


# --- the paths that work ----------------------------------------------------------


@pytest.mark.parametrize("bash", BASHES, ids=[_bash_id(b) for b in BASHES])
def test_staging_forward_back_and_keep(tmp_path, bash):
    world = World(tmp_path, STAGING)
    shape = world.shape
    (writer,) = shape.instances
    world.read(bash=bash)
    ts = world.recorded("TS")
    tmp, failed, abandoned = (
        f"staging-db-restore-{ts}",
        f"staging-db-failed-{ts}",
        f"staging-db-abandoned-{ts}",
    )
    assert world.changes() == [], "read changed something"

    result = world.restore(bash=bash)
    assert result.code == 0, result.err
    assert world.names() == {shape.cluster: [writer], tmp: [f"{tmp}-1"]}
    assert world.state["clusters"][tmp]["marker"] == f"experimently-restore {ts}"
    assert (Path(world.evid) / "parity.diff").read_text() == ""
    assert world.api() == (2, 2, False), "restore touched the API"

    result = world.cutover(bash=bash)
    assert result.code == 0, result.err
    # The restored cluster (uid 2) and its writer hold the stack's names; the
    # original and its instance are aside, kept.
    assert world.holder_uid() == 2
    assert world.names() == {shape.cluster: [writer], failed: [f"{failed}-1"]}
    assert world.state["clusters"][failed]["uid"] == 1
    endpoint = world.state["clusters"][shape.cluster]
    assert endpoint["marker"] == f"experimently-restore {ts}"
    assert world.api() == (2, 2, False)
    assert world.state["clusters"][shape.cluster]["tags"] == []
    assert {"Key": "experimently:left-identifier", "Value": shape.cluster} in (
        world.state["clusters"][failed]["tags"]
    )
    assert "endpoint unchanged: " + shape.endpoint in world.log()
    assert (Path(world.evid) / "cutover.ok").exists()

    result = world.rollback(bash=bash)
    assert result.code == 0, result.err
    assert world.holder_uid() == 1
    assert world.names() == {shape.cluster: [writer], abandoned: [f"{abandoned}-1"]}
    assert world.state["clusters"][shape.cluster]["marker"] is None
    assert world.state["clusters"][shape.cluster]["tags"] == [
        {"Key": "Environment", "Value": "staging"}
    ]
    assert world.api() == (2, 2, False)

    result = world.run("keep", world.evid, bash=bash)
    assert result.code == 0, result.err
    assert world.state["clusters"][abandoned]["DeletionProtection"] is True
    assert world.state["snapshots"] == {f"{abandoned}-kept": {"cluster_uid": 2}}
    assert_never_deleted_or_deferred(world)


def test_prod_two_instances_cutover_readers_rollback_keep(tmp_path):
    """Prod has a writer and a reader. The cutover moves both of the
    original's instances aside and brings only the restored writer in;
    `readers` adds the reader under the original reader's name, as a copy of
    it; rollback moves both back."""
    world = World(tmp_path, PROD)
    shape = world.shape
    writer, reader = shape.instances
    world.read()
    ts = world.recorded("TS")
    failed, abandoned = f"prod-db-failed-{ts}", f"prod-db-abandoned-{ts}"
    assert world.restore().code == 0

    result = world.cutover()
    assert result.code == 0, result.err
    assert world.names() == {
        shape.cluster: [writer],
        failed: [f"{failed}-1", f"{failed}-2"],
    }
    assert world.state["instances"][f"{failed}-1"]["writer"] is True
    assert world.api() == (3, 3, False)

    result = world.run("readers", world.evid)
    assert result.code == 0, result.err
    assert world.names()[shape.cluster] == [writer, reader]
    added = world.state["instances"][reader]
    assert added["writer"] is False
    assert (added["class"], added["pg"], added["tier"], added["public"]) == (
        "db.r5.large",
        "experimentation-database-prod-instanceparametergroup-bbb",
        1,
        False,
    )
    assert added["tags"] == [{"Key": "Environment", "Value": "prod"}]
    # Twice is refused: the reader exists.
    refused(world.run("readers", world.evid), f"{reader} exists")

    result = world.rollback()
    assert result.code == 0, result.err
    assert world.holder_uid() == 1
    assert world.names() == {
        shape.cluster: [writer, reader],
        abandoned: [f"{abandoned}-1", f"{abandoned}-2"],
    }
    assert world.api() == (3, 3, False)
    assert world.run("keep", world.evid).code == 0
    assert world.state["clusters"][abandoned]["DeletionProtection"] is True
    assert_never_deleted_or_deferred(world)


def test_the_restore_passes_every_setting_it_read(staging):
    """The restore and the writer get the original's settings, read, never
    typed: without the groups the cluster lands in the engine's default
    parameter group and the default VPC group (the tasks cannot reach it)."""
    staging.read()
    assert staging.restore().code == 0
    (restore,) = [
        c for c in staging.calls if c[1] == "restore-db-cluster-to-point-in-time"
    ]
    assert restore[restore.index("--db-subnet-group-name") + 1] == (
        "experimentation-database-staging-dbsubnetgroup-ccc"
    )
    assert restore[restore.index("--vpc-security-group-ids") + 1] == "sg-0db"
    assert restore[restore.index("--db-cluster-parameter-group-name") + 1] == (
        "experimentation-database-staging-clusterparametergroup-aaa"
    )
    assert restore[restore.index("--restore-to-time") + 1] == "2026-10-06T12:00:00Z"
    assert "--copy-tags-to-snapshot" in restore
    (create,) = [c for c in staging.calls if c[1] == "create-db-instance"]
    assert create[create.index("--db-instance-class") + 1] == "db.t3.medium"
    assert create[create.index("--db-parameter-group-name") + 1] == (
        "experimentation-database-staging-instanceparametergroup-bbb"
    )
    assert create[create.index("--promotion-tier") + 1] == "1"
    assert "--no-publicly-accessible" in create
    assert json.loads(create[create.index("--tags") + 1]) == [
        {"Key": "Environment", "Value": "staging"}
    ]


def test_no_task_runs_while_a_cluster_is_renamed(staging):
    """The API is at 0, and every earlier task STOPPED, before the first
    rename; it comes back only after the probe passed twice."""
    staging.read()
    staging.restore()
    assert staging.cutover().code == 0
    calls = staging.calls
    first_rename = calls.index(renames(calls)[0])
    stop = calls.index(
        next(c for c in calls if c[1] == "update-service" and c[-1] == "0")
    )
    start = calls.index(
        next(c for c in calls if c[1] == "update-service" and c[-1] == "2")
    )
    assert stop < first_rename < start
    log = staging.log()
    assert log.index("no API or migration task is running") < log.index("renaming")
    assert log.index("pass 2") < log.index("API running")


def test_a_stale_hostname_does_not_count_as_a_pass(tmp_path):
    """Pooled connections and DNS caches keep reaching the old cluster for a
    while: a probe that reads the original's (unmarked) database through the
    stack's hostname is not a pass, and two passes in a row are needed."""
    world = World(tmp_path, STAGING, dns_lag=1)
    world.read()
    world.restore()
    assert world.cutover().code == 0
    probes = world.state["probes"][2:]  # the restore's two came first
    assert [p["exit"] for p in probes] == [3, 0, 0]
    assert probes[0]["target"].startswith("staging-db-failed-")


def test_the_probe_runs_the_revision_read_recorded(staging):
    """After read, a cdk deploy registers a newer revision naming the
    `bootstrap` tag: every probe still runs the digest-pinned revision read
    recorded, from the API tasks' subnets and group, never in public."""
    staging.read()
    family = STAGING.migrate_family

    def cdk_deploy(state):
        td = state["task_definitions"][family]
        td["revisions"]["8"] = {
            "image": "repo/backend:bootstrap",
            "host": STAGING.endpoint,
        }
        td["newest"] = 8

    staging.mutate(cdk_deploy)
    assert staging.restore().code == 0
    assert staging.cutover().code == 0
    probes = staging.state["probes"]
    assert len(probes) == 4
    recorded = f"arn:aws:ecs:{REGION}:{ACCOUNT}:task-definition/{family}:7"
    for probe in probes:
        assert probe["task_definition"] == recorded
        assert probe["network"] == {
            "awsvpcConfiguration": {
                "subnets": ["subnet-a", "subnet-b"],
                "securityGroups": ["sg-0tasks"],
                "assignPublicIp": "DISABLED",
            }
        }
        # The probe file's text, exactly: an empty or unread file would be
        # `python -c ""`, which exits 0, and every probe would pass.
        assert probe["command"] == ["python", "-c", PROBE.read_text().rstrip("\n")]
        assert "PROBE verdict" in probe["command"][2]
        assert set(probe["env"]) == {"POSTGRES_SERVER", "RESTORE_ID", "PROBE_MODE"}
        # ECS refuses overrides over 8 KiB.
        assert probe["overrides_bytes"] < 8192, probe["overrides_bytes"]


# --- refusals: read -------------------------------------------------------------


def _refused_at_read(world: World, *fragments: str) -> None:
    result = world.run("read", world.shape.env)
    refused(result, *fragments)
    assert result.out == ""
    assert world.changes() == []


def test_t0_the_stack_names_another_instance(tmp_path):
    world = World(tmp_path, STAGING)
    world.mutate(lambda s: s["stack"].update(instances=["some-other-instance"]))
    _refused_at_read(world, "the stack's instances")


def test_the_original_must_be_available(tmp_path):
    """DR Scenario 4's trigger is status `failed`: no decided path renames it."""
    world = World(tmp_path, STAGING)
    world.mutate(lambda s: s["clusters"][STAGING.cluster].update(Status="failed"))
    _refused_at_read(world, "is 'failed', not available")


def test_the_tasks_must_take_the_host_from_the_cluster_endpoint(tmp_path):
    world = World(tmp_path, STAGING)
    family = "experimentation-backend-staging"
    world.mutate(
        lambda s: s["task_definitions"][family]["revisions"]["12"].update(
            host="proxy.example.com"
        )
    )
    _refused_at_read(world, f"{family}'s newest revision reads POSTGRES_SERVER")


def test_the_probe_revision_must_be_pinned_by_digest(tmp_path):
    """EM condition 4(a): after a cdk deploy the family's newest revision is
    CloudFormation's, which names the `bootstrap` tag."""
    world = World(tmp_path, STAGING)
    family = STAGING.migrate_family
    world.mutate(
        lambda s: s["task_definitions"][family]["revisions"]["7"].update(
            image="repo/backend:bootstrap"
        )
    )
    _refused_at_read(
        world, "not an image pinned by digest", "register_task_definition.sh"
    )


def test_read_refuses_an_api_that_is_already_stopped(tmp_path):
    """read records what cutover puts back; recording 0 would bring the API
    back at 0 and report success."""
    world = World(tmp_path, STAGING)
    world.mutate(lambda s: s["service"].update(desired=0))
    _refused_at_read(world, "the API runs 0 tasks")


@pytest.mark.parametrize("env", ["Staging", "staging;", "", "1prod"])
def test_read_refuses_an_environment_name_that_is_not_one(staging, env):
    result = staging.run("read", env)
    refused(result, "is not lower-case letters and digits")
    assert staging.calls == []


# --- refusals: restore ----------------------------------------------------------


def test_t2_a_restore_in_another_parameter_group_is_refused(tmp_path):
    world = World(tmp_path, STAGING, ignore_parameter_group=True)
    world.read()
    refused(world.restore(), "differs from the original (parity.diff)")
    diff = (Path(world.evid) / "parity.diff").read_text()
    assert "default.aurora-postgresql15" in diff
    refused(world.cutover(), "the restore phase did not finish")
    assert renames(world.calls) == []


def test_t4_a_secret_that_does_not_open_the_restored_cluster(tmp_path):
    world = World(tmp_path, STAGING, password_rotated=True)
    world.read()
    refused(world.restore(), "could not mark", "password authentication failed")
    refused(world.cutover(), "the restore phase did not finish")
    assert renames(world.calls) == []


def test_a_probe_that_cannot_tell_the_clusters_apart(tmp_path):
    world = World(tmp_path, STAGING, marker_everywhere=True)
    world.read()
    refused(world.restore(), "reads the original as marked")
    assert not (Path(world.evid) / "restore.ok").exists()


@pytest.mark.parametrize(
    "when", ["2026-10-06 12:00:00", "2026-10-06T12:00:00", "2026-10-06T12:00:00+02:00"]
)
def test_a_restore_time_that_is_not_utc(staging, when):
    staging.read()
    refused(staging.run("restore", staging.evid, when), "is not UTC")
    assert staging.changes() == []


def test_restore_again_after_a_cutover_is_refused(staging):
    staging.read()
    staging.restore()
    assert staging.cutover().code == 0
    before = len(staging.changes())
    refused(staging.restore(), "was cut over already")
    assert len(staging.changes()) == before


# --- refusals: cutover and rollback ------------------------------------------------


def _nothing_renamed_api_untouched(world: World) -> None:
    assert renames(world.calls) == []
    assert world.api() == (2, 2, False)
    assert not any(c[1] == "update-service" for c in world.calls)


def test_t6_a_deployment_in_flight(tmp_path):
    world = World(tmp_path, STAGING)
    world.read()
    world.restore()
    world.mutate(lambda s: s.update(deployments=["d-ABC123"]))
    refused(world.cutover(), "CodeDeploy deployment", "Nothing was changed")
    _nothing_renamed_api_untouched(world)


def test_cutover_reads_its_confirmation_from_a_terminal(staging):
    """EM condition 4(b): a pipe or a here-document cannot confirm, even with
    the right identifier in it; a block pasted into a terminal hands its next
    line to the prompt, which does not match."""
    staging.read()
    staging.restore()
    refused(
        staging.cutover(confirm=None, piped=STAGING.cluster + "\n"), "from a terminal"
    )
    _nothing_renamed_api_untouched(staging)
    pasted = f'scripts/restore_repoint.sh keep "{staging.evid}"'
    refused(staging.cutover(confirm=pasted), "was not the cluster identifier")
    _nothing_renamed_api_untouched(staging)
    refused(staging.cutover(confirm=""), "was not the cluster identifier")
    _nothing_renamed_api_untouched(staging)
    assert staging.cutover().code == 0


def test_rollback_reads_its_confirmation_from_a_terminal(staging):
    staging.read()
    staging.restore()
    assert staging.cutover().code == 0
    before = len(renames(staging.calls))
    refused(
        staging.rollback(confirm=None, piped=STAGING.cluster + "\n"), "from a terminal"
    )
    refused(staging.rollback(confirm=STAGING.cluster.upper()), "was not the cluster")
    assert len(renames(staging.calls)) == before
    assert staging.holder_uid() == 2


def test_t3_a_task_that_does_not_stop(tmp_path):
    """Refused before any rename, with the API at 0; start-api puts it back."""
    world = World(tmp_path, STAGING, stuck_task=True)
    world.read()
    world.restore()
    result = world.cutover()
    refused(result, "tasks still running", "no cluster was renamed")
    assert "stopped part-way" in result.err
    assert f"{STAGING.cluster}: available" in result.err
    assert renames(world.calls) == []
    assert world.api() == (0, 0, True)
    result = world.run("start-api", world.evid)
    assert result.code == 0, result.err
    assert world.api() == (2, 2, False)
    assert world.holder_uid() == 1


def test_t5_a_rename_that_is_not_applied(tmp_path):
    world = World(tmp_path, STAGING, rename_deferred=True)
    world.read()
    world.restore()
    result = world.cutover(REPOINT_WAIT_RENAME_MIN="0")
    refused(result, f"staging-db-failed-{world.recorded('TS')} is still 'absent'")
    assert world.holder_uid() == 1
    assert world.api() == (0, 0, True)


def test_t1_an_endpoint_that_does_not_follow_the_identifier(tmp_path):
    """The load-bearing premise only AWS can show. The cutover refuses with the
    API still at 0 and names the rollback, which puts the original back."""
    world = World(tmp_path, STAGING, suffix_per_cluster=True)
    world.read()
    assert world.restore().code == 0
    result = world.cutover()
    refused(result, "the endpoint did not follow the identifier", "rollback")
    assert world.api() == (0, 0, True)
    assert world.state["probes"][2:] == [], "a probe ran on a moved endpoint"
    result = world.rollback()
    assert result.code == 0, result.err
    assert world.holder_uid() == 1
    assert world.names()[STAGING.cluster] == list(STAGING.instances)
    assert world.api() == (2, 2, False)


def test_an_error_that_is_not_not_found_stops_the_script(tmp_path):
    """Only DBClusterNotFoundFault means absent. An expired session must not
    read as "the name is free"."""
    world = World(tmp_path, STAGING)
    world.read()
    world.restore()
    failed = f"staging-db-failed-{world.recorded('TS')}"
    world.mutate(
        lambda s: s["faults"].update(
            describe_error={"id": failed, "code": "ExpiredTokenException"}
        )
    )
    result = world.cutover()
    assert result.code != 0
    assert "ExpiredTokenException" in result.err
    _nothing_renamed_api_untouched(world)


def test_a_cutover_that_stopped_part_way_is_rolled_back(tmp_path):
    """The original moved out, then the restored cluster could not be moved in,
    so no cluster holds the stack's identifier. A second cutover is refused,
    keep is refused (two clusters are out of the stack's names), and rollback
    puts the original back on its own, leaving the restored cluster where it
    was; keep then keeps that one."""
    world = World(tmp_path, STAGING)
    world.read()
    world.restore()
    ts = world.recorded("TS")
    tmp, failed = f"staging-db-restore-{ts}", f"staging-db-failed-{ts}"
    world.mutate(lambda s: s["faults"].update(refuse_rename_of=tmp))
    result = world.cutover()
    assert result.code not in (0, 1, 2), result.code  # the CLI's own status
    assert "InvalidDBClusterStateFault" in result.err
    assert "stopped part-way" in result.err
    assert f"{STAGING.cluster}: absent" in result.err
    assert world.names() == {failed: [f"{failed}-1"], tmp: [f"{tmp}-1"]}
    assert world.api() == (0, 0, True)

    world.mutate(lambda s: s["faults"].pop("refuse_rename_of"))
    refused(world.cutover(), f"{failed} already exists")
    refused(world.run("keep", world.evid), "are out of the stack's names")
    result = world.rollback()
    assert result.code == 0, result.err
    assert world.holder_uid() == 1
    assert world.names() == {
        STAGING.cluster: list(STAGING.instances),
        tmp: [f"{tmp}-1"],
    }
    assert world.state["clusters"][STAGING.cluster]["tags"] == [
        {"Key": "Environment", "Value": "staging"}
    ]
    assert world.api() == (2, 2, False)
    assert world.run("keep", world.evid).code == 0
    assert world.state["clusters"][tmp]["DeletionProtection"] is True
    assert_never_deleted_or_deferred(world)


def test_rollback_with_nothing_to_roll_back(staging):
    staging.read()
    staging.restore()
    refused(staging.rollback(), "is 'absent', not available")
    _nothing_renamed_api_untouched(staging)


def test_readers_before_a_cutover(tmp_path):
    world = World(tmp_path, PROD)
    world.read()
    world.restore()
    refused(world.run("readers", world.evid), "after a finished cutover")
    reader = PROD.instances[1]
    assert not any(c[1] == "create-db-instance" and reader in c for c in world.calls)


def test_usage(staging):
    for args in ([], ["cutover"], ["read"], ["restore", "x"], ["bogus", "x"]):
        assert staging.run(*args).code == 2, args
    refused(staging.run("cutover", str(staging.tmp)), "is not an evidence directory")


# --- review round 1 (#1017): fail-open paths ----------------------------------------


def test_a_restore_refused_on_parity_leaves_no_restore_ok(staging):
    """A restore that finished once, then is run again and refused, must not
    leave the earlier run's `restore.ok`: a cutover would put the cluster
    live as it is now, out of parity."""
    staging.read()
    assert staging.restore().code == 0
    ok = Path(staging.evid) / "restore.ok"
    assert ok.exists()
    tmp = f"staging-db-restore-{staging.recorded('TS')}"
    staging.mutate(
        lambda s: s["clusters"][tmp].update(
            DBClusterParameterGroup="default.aurora-postgresql15"
        )
    )
    refused(staging.restore(), "differs from the original (parity.diff)")
    assert not ok.exists(), "a refused restore left restore.ok behind"
    refused(staging.cutover(), "the restore phase did not finish")
    assert renames(staging.calls) == []


def test_any_refused_restore_rerun_invalidates_restore_ok(staging):
    """`restore.ok` goes first, before any refusal: a re-run refused for its
    input (here a time that is not UTC) leaves no `restore.ok` either."""
    staging.read()
    assert staging.restore().code == 0
    refused(staging.run("restore", staging.evid, "2026-10-06T12:00:00"), "is not UTC")
    assert not (Path(staging.evid) / "restore.ok").exists()
    refused(staging.cutover(), "the restore phase did not finish")


def test_a_restore_again_at_another_time_is_refused(staging):
    """The restored cluster exists: a second `restore` with a different time
    would silently check the first restore and let it be cut over."""
    staging.read()
    assert staging.restore().code == 0
    restores = len(
        [c for c in staging.calls if c[1] == "restore-db-cluster-to-point-in-time"]
    )
    result = staging.run("restore", staging.evid, "2026-10-06T11:30:00Z")
    refused(result, "was restored to '2026-10-06T12:00:00Z', not 2026-10-06T11:30:00Z")
    assert "run read again" in result.err
    assert not (Path(staging.evid) / "restore.ok").exists()
    # The same time carries on with the cluster it made.
    assert staging.restore().code == 0
    assert (Path(staging.evid) / "restore.ok").exists()
    assert restores == len(
        [c for c in staging.calls if c[1] == "restore-db-cluster-to-point-in-time"]
    )


@pytest.mark.parametrize("probe", ["missing", "empty"])
def test_a_missing_or_empty_probe_is_refused(staging, probe):
    """The probe is `python -c "$(cat scripts/restore_probe.py)"`: with the file
    missing or empty that is `python -c ""`, which exits 0, so every probe
    would pass. The script refuses before it does anything."""
    copy = staging.tmp / "checkout" / "scripts"
    copy.mkdir(parents=True)
    for name in ("restore_repoint.sh", "run_migration_task.sh"):
        shutil.copy2(REPO_ROOT / "scripts" / name, copy / name)
    if probe == "empty":
        (copy / "restore_probe.py").write_text("")
    result = staging.run("read", "staging", script=copy / "restore_repoint.sh")
    refused(result, "restore_probe.py is missing or empty")
    assert staging.calls == []


def test_the_api_tasks_are_stopped_before_any_rename(tmp_path):
    """ECS marks a draining task desired STOPPED at once while it still holds
    pooled connections: the wait is for every earlier task to be STOPPED,
    not only for none to be desired RUNNING."""
    world = World(tmp_path, STAGING, stop_lag=2)
    world.read()
    world.restore()
    result = world.cutover(REPOINT_WAIT_TASKS_MIN="1")
    assert result.code == 0, result.err
    log = world.log()
    assert "2 of the API's earlier tasks not yet STOPPED" in log
    assert log.index("not yet STOPPED") < log.index(
        "no API or migration task is running"
    )
    assert_never_deleted_or_deferred(world)


def test_a_running_migration_task_refuses_the_cutover(staging):
    """A migration task (a deploy's, or db-migrate.yml's) is writing to the
    original: no rename while it runs."""
    staging.read()
    staging.restore()
    task = f"arn:aws:ecs:{REGION}:{ACCOUNT}:task/experimentation-staging/migration"
    staging.mutate(
        lambda s: s["tasks"].update(
            {
                task: {
                    "family": STAGING.migrate_family,
                    "desired": "RUNNING",
                    "last": "RUNNING",
                }
            }
        )
    )
    result = staging.cutover()
    refused(result, "tasks still running", "(1 desired RUNNING, 0 not STOPPED)")
    assert renames(staging.calls) == []
    assert staging.holder_uid() == 1


def test_a_restored_writer_that_differs_is_refused(tmp_path):
    """The writer's parity: here its parameter group is not applied yet."""
    world = World(tmp_path, STAGING, writer_pending_reboot=True)
    world.read()
    refused(world.restore(), "the restored writer differs from the original's")
    assert "pending-reboot" in (Path(world.evid) / "parity.diff").read_text()
    assert not (Path(world.evid) / "restore.ok").exists()
    refused(world.cutover(), "the restore phase did not finish")


READ_REFUSALS = {
    "cluster_pg": ("other-clusterparametergroup", "the cluster parameter group"),
    "subnet_group": ("other-dbsubnetgroup", "subnet group"),
    "sg": ("sg-0other", "VPC groups"),
    "instance_pg": (
        "other-instanceparametergroup",
        "the stack's instance parameter group",
    ),
    "cluster": ("other-cluster", "the stack output names"),
}


@pytest.mark.parametrize("resource", sorted(READ_REFUSALS))
def test_the_original_must_use_the_stacks_resources(tmp_path, resource):
    """`read` refuses an original whose groups, or whose cluster, are not the
    database stack's: the restore copies them, and a swap would carry the
    difference into the stack's names."""
    world = World(tmp_path, STAGING)
    value, message = READ_REFUSALS[resource]
    world.mutate(lambda s: s["stack"].update({resource: value}))
    _refused_at_read(world, message)


def test_a_restored_cluster_with_more_instances_than_the_stack(staging):
    staging.read()
    staging.restore()
    tmp = f"staging-db-restore-{staging.recorded('TS')}"
    staging.mutate(
        lambda s: s["instances"].update(
            {f"{tmp}-2": dict(s["instances"][f"{tmp}-1"], writer=False)}
        )
    )
    refused(staging.cutover(), f"{tmp} has 2 instances, more than the stack's 1")
    _nothing_renamed_api_untouched(staging)


def test_a_holder_that_is_not_available(staging):
    staging.read()
    staging.restore()
    staging.mutate(lambda s: s["clusters"][STAGING.cluster].update(Status="backing-up"))
    refused(staging.cutover(), f"{STAGING.cluster} is 'backing-up', not available")
    _nothing_renamed_api_untouched(staging)


@pytest.mark.parametrize("kind", ["cluster", "instance"])
def test_an_old_name_that_does_not_go(tmp_path, kind):
    """A rename is done only when the new name answers and the old one is
    gone: two clusters (or instances) answering is not a finished swap."""
    world = World(tmp_path, STAGING, ghost_after_rename=kind)
    world.read()
    world.restore()
    old = STAGING.cluster if kind == "cluster" else STAGING.instances[0]
    result = world.cutover(REPOINT_WAIT_RENAME_MIN="0")
    refused(result, f"{kind} {old} is still 'available' after 0 min (wanted absent)")
    assert "stopped part-way" in result.err


# --- review round 2 (#1017): the rest of the refusals, and the EM's rulings --------


def test_a_restore_with_no_recorded_time_is_refused(staging):
    """A restore call that errored after RDS made the cluster leaves the
    cluster and no recorded time: which time it holds is unknown, so a
    restore phase must not carry on with it."""
    staging.read()
    tmp = f"staging-db-restore-{staging.recorded('TS')}"

    def made_but_not_recorded(state):
        state["clusters"][tmp] = dict(
            state["clusters"][STAGING.cluster], uid=9, tags=[]
        )

    staging.mutate(made_but_not_recorded)
    refused(
        staging.restore(),
        f"{tmp} was restored to 'an unrecorded time'",
        "run read again",
    )
    assert not any(c[1] == "restore-db-cluster-to-point-in-time" for c in staging.calls)


def test_keep_then_rollback_leaves_deletion_protection_on(staging):
    """EM ruling R1: `keep` protects the original; a rollback after it brings
    the original back onto the stack's names still protected, which the
    database stack does not set. Pinned here, said on the page."""
    staging.read()
    staging.restore()
    assert staging.cutover().code == 0
    assert staging.run("keep", staging.evid).code == 0
    assert staging.rollback().code == 0
    assert staging.holder_uid() == 1
    assert staging.state["clusters"][STAGING.cluster]["DeletionProtection"] is True


def test_tag_removal_names_only_keys_the_cluster_carries(tmp_path):
    """EM ruling R2: on a cutover the cluster taking the identifier never
    carried this procedure's tags. If RDS refused to remove an absent key,
    every cutover would stop inside the downtime window after a good swap.
    With the fake refusing exactly that, cutover and rollback both finish."""
    world = World(tmp_path, STAGING, strict_tag_removal=True)
    world.read()
    world.restore()
    assert world.cutover().code == 0
    removals = [c for c in world.calls if c[1] == "remove-tags-from-resource"]
    assert removals == [], "the cutover asked to remove keys the cluster did not carry"
    assert world.rollback().code == 0
    (removal,) = [c for c in world.calls if c[1] == "remove-tags-from-resource"]
    assert removal[removal.index("--tag-keys") + 1 :] == [
        "experimently:left-identifier",
        "experimently:restore",
    ]
    assert world.state["clusters"][STAGING.cluster]["tags"] == [
        {"Key": "Environment", "Value": "staging"}
    ]


def test_a_stack_output_that_cannot_be_read(tmp_path):
    world = World(tmp_path, STAGING)
    world.mutate(
        lambda s: s["outputs"]["experimentation-fargate-staging"].pop("TaskSubnets")
    )
    _refused_at_read(world, "could not read TASK_SUBNETS (got 'None')")


def test_read_refuses_a_service_with_no_scalable_target(tmp_path):
    world = World(tmp_path, STAGING)
    world.mutate(lambda s: s.update(scaling=None))
    _refused_at_read(world, "has no scalable target")


def test_a_restored_cluster_with_no_endpoint(staging):
    staging.read()
    tmp = f"staging-db-restore-{staging.recorded('TS')}"
    staging.mutate(lambda s: s["faults"].update(no_endpoint=tmp))
    refused(staging.restore(), "could not read TMP_ENDPOINT")
    assert staging.state["probes"] == []


def test_an_instance_describe_error_is_not_absent(staging):
    """Only DBInstanceNotFound means absent: a throttled describe of the
    restored writer must not read as "no writer yet" and make a second one."""
    staging.read()
    tmp = f"staging-db-restore-{staging.recorded('TS')}"
    staging.mutate(
        lambda s: s["faults"].update(
            describe_error={"id": f"{tmp}-1", "code": "Throttling", "kind": "instance"}
        )
    )
    result = staging.restore()
    assert result.code != 0
    assert "Throttling" in result.err
    assert not any(c[1] == "create-db-instance" for c in staging.calls)


def test_a_cutover_with_no_cluster_on_the_identifier(staging):
    staging.read()
    staging.restore()
    staging.mutate(lambda s: s["clusters"].pop(STAGING.cluster))
    refused(
        staging.cutover(), f"no cluster holds the stack's identifier {STAGING.cluster}"
    )
    _nothing_renamed_api_untouched(staging)


def test_a_restored_cluster_with_no_instance(staging):
    staging.read()
    staging.restore()
    tmp = f"staging-db-restore-{staging.recorded('TS')}"
    staging.mutate(lambda s: s["instances"].pop(f"{tmp}-1"))
    refused(staging.cutover(), f"{tmp} has no instance")
    _nothing_renamed_api_untouched(staging)


def test_probes_that_never_pass_twice(tmp_path):
    """The hostname keeps reaching the original: the cutover stops with the
    API at 0 and does not start it (the page sends this to rollback)."""
    world = World(tmp_path, STAGING, dns_lag=100)
    world.read()
    world.restore()
    result = world.cutover(REPOINT_WAIT_PROBE_MIN="0")
    refused(result, "did not pass twice in a row within 0 min")
    assert "stopped part-way" in result.err
    assert world.api() == (0, 0, True)


def test_an_api_that_does_not_come_back(tmp_path):
    world = World(tmp_path, STAGING, api_does_not_start=True)
    world.read()
    world.restore()
    result = world.cutover()
    refused(result, "the API has 0 of 2 tasks 0 min after it was started")
    assert "stopped part-way" in result.err


def test_a_rollback_whose_endpoint_does_not_follow(staging):
    """The rollback's own endpoint check: there is no scripted way on."""
    staging.read()
    staging.restore()
    assert staging.cutover().code == 0
    failed = f"staging-db-failed-{staging.recorded('TS')}"

    def original_moves_endpoint(state):
        state["clusters"][failed]["suffix"] = "zzz"
        state["faults"]["suffix_per_cluster"] = True

    staging.mutate(original_moves_endpoint)
    result = staging.rollback()
    refused(result, "the endpoint did not follow", "no scripted way on from here")
    assert staging.api() == (0, 0, True)


def test_keep_with_no_cluster_out_of_the_stack(staging):
    staging.read()
    refused(staging.run("keep", staging.evid), "no cluster of this restore is out")
    assert staging.changes() == []


@pytest.mark.parametrize("missing", ["aws", "jq"])
def test_a_missing_tool_is_refused(staging, missing):
    """Without the CLI or jq on PATH the script stops before anything. The
    PATH here holds only `dirname` (and, for the jq case, a failing `aws`)."""
    bin_dir = staging.tmp / "bare-bin"
    bin_dir.mkdir()
    os.symlink(shutil.which("dirname"), bin_dir / "dirname")
    if missing == "jq":
        stub = bin_dir / "aws"
        stub.write_text("#!/bin/sh\nprintf 'NO-REAL-AWS\\n' >&2\nexit 97\n")
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    staging.env["PATH"] = str(bin_dir)
    result = staging.run("read", "staging", bash=shutil.which("bash"))
    refused(
        result,
        "the AWS CLI is not on PATH" if missing == "aws" else "jq is not on PATH",
    )
    assert staging.calls == []


# --- what the script passes ------------------------------------------------------


def _script_commands() -> list[tuple[str, str, list[str]]]:
    """Every `aws <service> <operation>` in the script, with the flags it passes."""
    text = SCRIPT.read_text().replace("\\\n", " ")
    found = []
    for service, operation, rest in re.findall(
        r"\baws ([a-z-]+) ([a-z0-9-]+)([^\n]*)", text
    ):
        rest = rest.split("$(")[0].split("|")[0]
        flags = re.findall(r"(?<![\w-])--([a-z0-9-]+)", rest)
        found.append((service, operation, flags))
    return found


def test_every_flag_is_one_the_cli_has():
    """`aws` refuses an unknown flag (exit 252) mid-incident. Checked offline
    against botocore's service models, which the CLI reads."""
    from botocore import xform_name
    from botocore.session import get_session

    session = get_session()
    models = {
        "rds": "rds",
        "ecs": "ecs",
        "cloudformation": "cloudformation",
        "deploy": "codedeploy",
        "application-autoscaling": "application-autoscaling",
    }
    commands = _script_commands()
    assert {(s, o) for s, o, _ in commands} >= {
        ("rds", "restore-db-cluster-to-point-in-time"),
        ("rds", "modify-db-cluster"),
        ("rds", "modify-db-instance"),
        ("rds", "create-db-instance"),
        ("ecs", "update-service"),
        ("deploy", "list-deployments"),
        ("application-autoscaling", "register-scalable-target"),
    }, commands
    for service, operation, flags in commands:
        model = session.get_service_model(models[service])
        operations = {xform_name(o).replace("_", "-"): o for o in model.operation_names}
        assert operation in operations, (service, operation)
        shape = model.operation_model(operations[operation]).input_shape
        members = {xform_name(m).replace("_", "-"): m for m in shape.members}
        for flag in flags:
            if flag in ("query", "output"):
                continue
            name = flag[3:] if flag.startswith("no-") and flag[3:] in members else flag
            assert name in members, (service, operation, flag)
    statuses = (
        session.get_service_model("codedeploy").shape_for("DeploymentStatus").enum
    )
    for status in ("Created", "Queued", "InProgress", "Baking", "Ready"):
        assert status in statuses


def test_every_rename_applies_immediately_and_nothing_deletes():
    """Statically too: a rename without --apply-immediately waits for the
    maintenance window and reports success; the procedure deletes nothing."""
    commands = _script_commands()
    for service, operation, flags in commands:
        assert not operation.startswith("delete-"), operation
        if (
            "new-db-cluster-identifier" in flags
            or "new-db-instance-identifier" in flags
        ):
            assert "apply-immediately" in flags, (operation, flags)


def test_the_scripts_parse_under_every_bash():
    # The runbooks run it as `scripts/restore_repoint.sh <phase>`.
    assert os.access(SCRIPT, os.X_OK), "scripts/restore_repoint.sh is not executable"
    for bash in BASHES:
        done = subprocess.run([bash, "-n", str(SCRIPT)], capture_output=True, text=True)
        assert done.returncode == 0, (bash, done.stderr)
    compile(PROBE.read_text(), str(PROBE), "exec")


# --- the deploy role gains nothing (EM condition 5) -------------------------------


def test_no_workflow_runs_it_and_the_deploy_role_gains_nothing():
    workflows = REPO_ROOT / ".github" / "workflows"
    for workflow in sorted(workflows.glob("*.yml")):
        assert "restore_repoint" not in workflow.read_text(), workflow.name
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        import iam_actions
    finally:
        sys.path.pop(0)
    assert SCRIPT not in iam_actions.sources()
    assert SCRIPT not in iam_actions.STAGED_SCRIPTS
    policy = json.loads(
        (
            REPO_ROOT / "infrastructure" / "cdk" / "github-actions-deploy-policy.json"
        ).read_text()
    )
    rds = set()
    for statement in policy["Statement"]:
        actions = statement["Action"]
        for action in [actions] if isinstance(actions, str) else actions:
            if action.startswith("rds:"):
                rds.add(action)
    assert rds == {
        "rds:CreateDBClusterSnapshot",
        "rds:DescribeDBClusterSnapshots",
        "rds:AddTagsToResource",
    }, rds
