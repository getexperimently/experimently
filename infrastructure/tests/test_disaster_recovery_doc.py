"""docs/deployment/disaster-recovery.md states what the CDK app actually creates (#168).

The page used to promise S3 cross-region replication of "frontend" assets
(no stack puts the dashboard in S3), replicated secrets, a 35-day Aurora
retention, log export to S3 and alarms that do not exist. Operators follow
that page mid-incident, so each figure it now gives is checked here against a
real ``app.synth()`` of prod, and the page must still say it. A change to the
stacks that moves one of them fails here until the page is updated with it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from .test_dashboard_service import _synth

REPO_ROOT = Path(__file__).resolve().parents[2]
PAGE = REPO_ROOT / "docs" / "deployment" / "disaster-recovery.md"

pytestmark = pytest.mark.regression


@pytest.fixture(scope="module")
def templates() -> dict:
    """{stack name: template} for the prod app, as `cdk synth` builds it."""
    assembly = _synth("prod")
    return {s.stack_name: s.template for s in assembly.stacks}


@pytest.fixture(scope="module")
def prod(templates) -> dict:
    """{stack name: resources} for the prod app."""
    return {name: t.get("Resources", {}) for name, t in templates.items()}


@pytest.fixture(scope="module")
def page() -> str:
    """The page with its whitespace collapsed, so a re-wrap is not a failure."""
    return " ".join(PAGE.read_text(encoding="utf-8").split())


def _of_type(prod: dict, rtype: str) -> list[tuple[str, dict]]:
    return [
        (stack, r)
        for stack, resources in prod.items()
        for r in resources.values()
        if r["Type"] == rtype
    ]


def _props(r: dict) -> dict:
    return r.get("Properties", {})


def test_no_bucket_is_replicated_and_only_module_stacks_have_buckets(prod, page):
    buckets = _of_type(prod, "AWS::S3::Bucket")
    assert buckets, "the full-profile synth has no bucket: the check is vacuous"
    for stack, bucket in buckets:
        assert "ReplicationConfiguration" not in _props(bucket), stack
        # The core profile creates none: every bucket is in a module stack.
        assert "-analytics-" in stack or "-glue-etl-" in stack, stack
    assert "None has cross-region replication" in page
    assert "The core profile creates no bucket" in page
    assert "Cross-region replication" not in page
    assert "S3 assets (frontend" not in page


def test_nothing_serves_the_dashboard_from_s3_or_cloudfront(prod, page):
    assert not _of_type(prod, "AWS::CloudFront::Distribution")
    services = {
        _props(r)["ServiceName"]: _props(r)
        for _, r in _of_type(prod, "AWS::ECS::Service")
    }
    assert services["experimentation-dashboard-prod"]["DeploymentController"] == {
        "Type": "ECS"
    }
    assert services["experimentation-backend-prod"]["DeploymentController"] == {
        "Type": "CODE_DEPLOY"
    }
    assert "The CDK creates no S3 bucket or CloudFront distribution for it" in page


def test_no_secret_is_replicated_to_another_region(prod, page):
    secrets = _of_type(prod, "AWS::SecretsManager::Secret")
    assert secrets
    for stack, secret in secrets:
        assert "ReplicaRegions" not in _props(secret), stack
    assert "The CDK configures no replica regions" in page


def test_aurora_keeps_the_default_one_day_of_backups(prod, page):
    ((stack, cluster),) = _of_type(prod, "AWS::RDS::DBCluster")
    # Unset means CloudFormation's default, 1 day. Set it and this fails until
    # the page's "1 day" figures (backup table, Scenarios 4 and 8) follow.
    assert _props(cluster).get("BackupRetentionPeriod", 1) == 1, stack
    assert cluster.get("DeletionPolicy") == "Snapshot", stack
    assert not _of_type(prod, "AWS::RDS::GlobalCluster")
    assert "Aurora's default of **1 day** applies" in page
    assert "deleting the prod stack leaves a final snapshot" in page
    assert "35 days" not in page


def test_redis_snapshot_retention_and_failover(prod, page):
    ((stack, group),) = _of_type(prod, "AWS::ElastiCache::ReplicationGroup")
    props = _props(group)
    assert props["ReplicationGroupId"] == "experimentation-redis-prod-redis"
    assert props["SnapshotRetentionLimit"] == 7
    assert props["SnapshotWindow"] == "02:00-03:00"
    assert props["NumCacheClusters"] == 3 and props["AutomaticFailoverEnabled"]
    assert "prod 7 days, staging 3, dev 1" in page
    assert "There is no append-only file" in page
    assert "experimentation-redis-$ENV-redis" in page


def test_log_retention_and_no_export(prod, page):
    retention = {
        _props(r)["LogGroupName"]: _props(r).get("RetentionInDays")
        for _, r in _of_type(prod, "AWS::Logs::LogGroup")
        if isinstance(_props(r).get("LogGroupName"), str)
    }
    assert retention["/ecs/experimentation-backend-prod"] == 90
    assert retention["/ecs/experimentation-dashboard-prod"] == 90
    assert retention["/ecs/experimentation-migrate-prod"] == 30
    # #205: the monitoring stack's `/experimentation/<env>/application` group
    # was written to by nothing, and is gone with its ERROR filter; the API's
    # ERROR filter is on its tasks' own group now.
    assert "/experimentation/prod/application" not in retention, sorted(retention)
    assert not _of_type(prod, "AWS::Logs::SubscriptionFilter")
    assert "CloudWatch Logs only, with no export to S3" in page
    assert (
        "`/ecs/experimentation-backend-$ENV` and `/ecs/experimentation-dashboard-$ENV` "
        "are kept 90 days, and `/ecs/experimentation-migrate-$ENV` 30 days."
    ) in page
    assert "/application" not in page


def test_the_api_scaling_floor_is_its_task_count(prod, page):
    """Scenario 8 lowers the floor before scaling to 0, because it is there."""
    services = {
        _props(r)["ServiceName"]: _props(r)
        for _, r in _of_type(prod, "AWS::ECS::Service")
    }
    assert services["experimentation-backend-prod"]["DesiredCount"] == 3
    targets = [
        _props(r)
        for _, r in _of_type(prod, "AWS::ApplicationAutoScaling::ScalableTarget")
        if _props(r).get("ScalableDimension") == "ecs:service:DesiredCount"
    ]
    assert [t["MinCapacity"] for t in targets] == [3], targets
    assert "with a floor equal to its task count (3 in prod)" in page
    assert "--min-capacity 0" in page


def _alarms(prod: dict) -> dict:
    return {
        _props(r)["AlarmName"]: _props(r)
        for _, r in _of_type(prod, "AWS::CloudWatch::Alarm")
    }


def test_the_alarms_the_page_describes(templates, prod, page):
    alarms = _alarms(prod)
    composites = {
        _props(r)["AlarmName"]: _props(r)
        for _, r in _of_type(prod, "AWS::CloudWatch::CompositeAlarm")
    }
    # Scenario 2: the API's 5xx alarms count the TASKS' 5xx responses, so they
    # stay quiet with no task running...
    for colour in ("blue", "green"):
        alarm = alarms[f"experimentation-api-5xx-{colour}-prod"]
        names = {
            m["MetricStat"]["Metric"]["MetricName"]
            for m in alarm["Metrics"]
            if "MetricStat" in m
        }
        assert "HTTPCode_Target_5XX_Count" in names, names
        assert alarm["TreatMissingData"] == "notBreaching"
    assert "(`HTTPCode_Target_5XX_Count`)" in page
    # ...and the composite over the two healthy-task alarms is what emails
    # (#390). Scenario 1 names all three, and says the idle colour's alarm is
    # in ALARM by design.
    for colour in ("blue", "green"):
        healthy = alarms[f"experimentation-api-healthy-{colour}-prod"]
        assert healthy["MetricName"] == "HealthyHostCount"
        assert healthy["TreatMissingData"] == "breaching"
        assert "AlarmActions" not in healthy
        assert f"`experimentation-api-healthy-{colour}-$ENV`" in page
    assert "experimentation-api-no-healthy-task-prod" in composites, sorted(composites)
    assert "The composite `experimentation-api-no-healthy-task-$ENV` emails" in page
    assert (
        "the idle colour's healthy alarm is always in ALARM, by design; that is not "
        "an incident"
    ) in page
    assert 'the composite sends a true "no healthy task" email for it' in page
    assert "`experimentation-api-no-healthy-task-$ENV` emails `ALARM_EMAIL` once neither" in page
    assert "No alarm watches the number of running tasks" not in page
    assert "No alarm the CDK creates fires for this" not in page
    # Scenario 3: the Aurora alarm names the real cluster, through the
    # database stack's parameter, and only the writer.
    aurora = alarms["AuroraHighCPU-prod"]
    dimensions = {d["Name"]: d["Value"] for d in aurora["Dimensions"]}
    assert dimensions["Role"] == "WRITER"
    parameter = dimensions["DBClusterIdentifier"]["Ref"]
    name = templates["experimentation-monitoring-prod"]["Parameters"][parameter]["Default"]
    assert name == "/experimentation/prod/database/aurora-cluster-identifier"
    (cluster,) = [
        lid
        for lid, r in prod["experimentation-database-prod"].items()
        if r["Type"] == "AWS::RDS::DBCluster"
    ]
    assert [
        _props(r)["Value"]
        for r in prod["experimentation-database-prod"].values()
        if r["Type"] == "AWS::SSM::Parameter" and _props(r)["Name"] == name
    ] == [{"Ref": cluster}]
    assert "`/experimentation/$ENV/database/aurora-cluster-identifier`, `Role=WRITER`" in page
    assert "`AuroraCluster`" not in page
    # Scenario 4: a cluster restored beside the stack is not what it watches.
    assert (
        "A cluster restored beside the stack is not watched by `AuroraHighCPU-$ENV` either."
    ) in page
    assert (
        "The restored cluster is watched only once the database stack's parameter points "
        "at it and `experimentation-monitoring-$ENV` is redeployed."
    ) in page
    # Scenario 5: one Redis alarm per node, on the nodes' real ids.
    redis = {
        n: alarms[n]["Dimensions"] for n in alarms if n.startswith("RedisHighCPU-")
    }
    assert redis == {
        f"RedisHighCPU-00{i}-prod": [
            {"Name": "CacheClusterId", "Value": f"experimentation-redis-prod-redis-00{i}"}
        ]
        for i in (1, 2, 3)
    }, redis
    assert "`RedisHighCPU-001-$ENV` (and `-002-`, `-003-` in prod)" in page
    assert "`experimentation-redis-$ENV-redis-001`" in page
    assert "names the cache cluster `Redis`" not in page
    # Alarm names the old page gave, none of which exists.
    for gone in (
        "AllTasksDown",
        "RDS-FreeableMemory-Low",
        "RDS-DatabaseConnections-High",
        "Redis-CacheMisses-High",
        "Redis-Replication-Lag-High",
    ):
        assert not any(gone in name for name in alarms), gone
        assert gone not in page, gone
