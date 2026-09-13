"""`infrastructure/cdk/app.py` — which stacks each profile builds.

The three module stacks (the real-time counters table, the analytics data lake
and the Glue ETL jobs) were gated on ``ENABLE_MODULE_STACKS``, a variable
nothing in the repository ever set.  ``cdk deploy --all`` from a full checkout
therefore built none of them, while the API went on reporting ``counters`` and
``etl`` installed, the bandit scheduler retried DynamoDB every tick, and the
core monitoring stack kept an alarm on a Kinesis stream nothing had created.

The gate is now the presence of ``modules/infrastructure/cdk/stacks`` — the
same rule ``backend/app/modules_loader.py`` applies to the application — with
``EXPERIMENTLY_PROFILE`` as the explicit override.

``app.py`` is run the way ``cdk synth`` runs it, with ``App.synth`` stubbed out
so the assertions are about which stacks the app *contains*.  (The app-wide
``app.synth()`` currently raises ``DependencyCycle`` between
``experimentation-compute-dev`` and ``experimentation-fargate-dev`` — the ALB
in the Fargate stack adds a rule to the ECS security group in the compute
stack, which already depends on it.  That is a pre-existing defect in the
core stacks, untouched here and not what these tests are about.)
"""

from __future__ import annotations

import os
import runpy
import shutil
import sys
from contextlib import contextmanager
from pathlib import Path

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Template

REPO_ROOT = Path(__file__).resolve().parents[2]
CDK_DIR = REPO_ROOT / "infrastructure" / "cdk"
MODULE_STACKS = {
    "experimentation-dynamodb-counters-dev",
    "experimentation-analytics-dev",
    "experimentation-glue-etl-dev",
}
CORE_STACKS = {
    "experimentation-vpc-dev",
    "experimentation-database-dev",
    "experimentation-fargate-dev",
    "experimentation-monitoring-dev",
}


@contextmanager
def _app_environment(cdk_dir: Path, **overrides: str):
    saved_env = dict(os.environ)
    saved_path = list(sys.path)
    saved_modules = {k: v for k, v in sys.modules.items() if k.split(".")[0] == "stacks"}
    os.environ.update(
        CDK_DEFAULT_ACCOUNT="123456789012",
        CDK_DEFAULT_REGION="us-west-2",
        ENVIRONMENT="dev",
    )
    os.environ.pop("EXPERIMENTLY_PROFILE", None)
    os.environ.update(overrides)
    sys.path.insert(0, str(cdk_dir))
    for name in list(sys.modules):
        if name.split(".")[0] == "stacks":
            del sys.modules[name]
    try:
        yield
    finally:
        sys.path[:] = saved_path
        os.environ.clear()
        os.environ.update(saved_env)
        for name in list(sys.modules):
            if name.split(".")[0] == "stacks":
                del sys.modules[name]
        sys.modules.update(saved_modules)


def build(cdk_dir: Path, **env: str) -> tuple[set[str], str]:
    """Run ``app.py`` without synthesising; return ``(stack ids, stdout)``."""
    synth = cdk.App.synth
    cdk.App.synth = lambda self, **kwargs: None  # type: ignore[method-assign]
    try:
        with _app_environment(cdk_dir, **env):
            namespace = runpy.run_path(str(cdk_dir / "app.py"), run_name="__main__")
    finally:
        cdk.App.synth = synth  # type: ignore[method-assign]
    app = namespace["app"]
    profile = "full" if namespace["ENABLE_MODULE_STACKS"] else "core"
    return {
        child.node.id for child in app.node.children if isinstance(child, cdk.Stack)
    }, profile


@pytest.fixture(scope="module")
def core_cdk_dir(tmp_path_factory) -> Path:
    """A copy of the CDK app with no ``modules/`` beside it — a core checkout."""
    root = tmp_path_factory.mktemp("core-checkout")
    shutil.copytree(CDK_DIR, root / "infrastructure" / "cdk")
    return root / "infrastructure" / "cdk"


modules_present = pytest.mark.skipif(
    not (REPO_ROOT / "modules" / "infrastructure" / "cdk" / "stacks").is_dir(),
    reason="core checkout: no modules/infrastructure/cdk/stacks",
)


class TestProfileSelection:
    @pytest.mark.regression
    @modules_present
    def test_a_full_checkout_builds_the_module_stacks(self):
        """`cdk deploy --all` on a full checkout must include all three.

        They were gated on ENABLE_MODULE_STACKS, which nothing set, so every
        deployment silently left out the counters table, the Kinesis/OpenSearch
        data lake and the Glue ETL jobs.
        """
        stacks, profile = build(CDK_DIR)
        assert profile == "full"
        assert MODULE_STACKS <= stacks, sorted(stacks)

    def test_a_core_checkout_builds_none_of_them(self, core_cdk_dir):
        stacks, profile = build(core_cdk_dir)
        assert profile == "core"
        assert not MODULE_STACKS & stacks, sorted(stacks)
        assert CORE_STACKS <= stacks, sorted(stacks)

    @modules_present
    def test_the_profile_variable_overrides_a_full_checkout(self):
        stacks, profile = build(CDK_DIR, EXPERIMENTLY_PROFILE="core")
        assert profile == "core"
        assert not MODULE_STACKS & stacks, sorted(stacks)
        assert CORE_STACKS <= stacks, sorted(stacks)

    def test_asking_for_full_on_a_core_checkout_fails_loudly(self, core_cdk_dir):
        """Not a silent drop to the core set."""
        with pytest.raises(SystemExit) as excinfo:
            build(core_cdk_dir, EXPERIMENTLY_PROFILE="full")
        assert "core checkout" in str(excinfo.value)

    def test_an_unknown_profile_is_rejected(self, core_cdk_dir):
        with pytest.raises(SystemExit) as excinfo:
            build(core_cdk_dir, EXPERIMENTLY_PROFILE="enterprise")
        assert "EXPERIMENTLY_PROFILE must be" in str(excinfo.value)


class TestMonitoringFollowsTheProfile:
    """The Kinesis alarm may only exist where the Kinesis stream does."""

    @staticmethod
    def _template(events_stream_name: str | None) -> dict:
        sys.path.insert(0, str(CDK_DIR))
        try:
            from stacks.monitoring_stack import MonitoringStack
            from stacks.vpc_stack import VpcStack
        finally:
            sys.path.remove(str(CDK_DIR))
        app = cdk.App()
        vpc_stack = VpcStack(app, "TestVpc")
        stack = MonitoringStack(
            app,
            "TestMonitoring",
            vpc=vpc_stack.vpc,
            events_stream_name=events_stream_name,
        )
        return Template.from_stack(stack).to_json()

    @staticmethod
    def _kinesis_alarms(template: dict) -> list[dict]:
        return [
            resource
            for resource in template["Resources"].values()
            if resource["Type"] == "AWS::CloudWatch::Alarm"
            and resource["Properties"].get("Namespace") == "AWS/Kinesis"
        ]

    @pytest.mark.regression
    def test_the_core_profile_has_no_alarm_on_a_stream_it_never_creates(self):
        """A core deployment has no Kinesis stream; the alarm watched one anyway.

        `experimentation-events` is a name nothing ever created -- the
        analytics stack calls its stream `exp-events-<id>` -- so the alarm sat
        in INSUFFICIENT_DATA and the dashboard graphed an empty widget.
        """
        template = self._template(None)
        assert [
            resource
            for resource in template["Resources"].values()
            if resource["Type"] == "AWS::CloudWatch::Alarm"
        ], "the monitoring stack lost all of its alarms"
        assert not self._kinesis_alarms(template)
        assert "experimentation-events" not in str(template)

    def test_the_full_profile_keeps_it_on_the_real_stream(self):
        template = self._template("exp-events-abcd1234")
        alarms = self._kinesis_alarms(template)
        assert len(alarms) == 1, sorted(template["Resources"])
        assert alarms[0]["Properties"]["Dimensions"] == [
            {"Name": "StreamName", "Value": "exp-events-abcd1234"}
        ]
        assert "experimentation-events" not in str(template)
