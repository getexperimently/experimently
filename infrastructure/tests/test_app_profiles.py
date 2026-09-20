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
so the assertions below are about which stacks the app *contains*.

That stub is also why a two-year-old defect shipped.  ``app.synth()`` raised
``DependencyCycle`` between ``experimentation-compute-dev`` and
``experimentation-fargate-dev`` from the day EP-019 added the Fargate stack,
and every test here passed throughout, because none of them ever called it: a
dependency cycle is an app-level, synth-time failure, invisible to
``Template.from_stack`` on one stack at a time.  ``TestTheAppActuallySynthesises``
at the bottom of this file is the test that would have caught it, and is the
regression test for the fix.
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
    saved_modules = {
        k: v for k, v in sys.modules.items() if k.split(".")[0] == "stacks"
    }
    os.environ.update(
        CDK_DEFAULT_ACCOUNT="123456789012",
        CDK_DEFAULT_REGION="us-west-2",
        ENVIRONMENT="dev",
        # Required at synth, not at deploy: both ALB listeners are HTTPS and
        # CDK validates that at the end of synthesis, so FargateServiceStack
        # refuses to build without one. Never resolved -- no AWS call is made
        # for an ACM ARN until a real deployment.
        CERTIFICATE_ARN=(
            "arn:aws:acm:us-west-2:123456789012:certificate/"
            "00000000-0000-0000-0000-000000000000"
        ),
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


class TestTheAppActuallySynthesises:
    """A real ``app.synth()``, which nothing in this repository did before.

    Everything else in this file stubs ``App.synth`` so it can assert on the
    app's *contents*.  That is a different question from "does this app
    synthesise", and the difference is not academic: cross-stack references,
    the stack dependency graph, export generation and the CDK validation
    plugins all run only inside ``synth()``.  ``cdk synth`` -- and therefore
    ``cdk deploy`` -- was impossible for either profile from 2026-03-01 until
    this test was written, and CI was green the whole time.
    """

    @pytest.mark.parametrize("profile", ["core", "full"])
    def test_synth_completes(self, profile: str, core_cdk_dir: Path):
        """`app.synth()` succeeds and yields a template for every stack.

        Asserted on the returned ``CloudAssembly``, not on files: the jsii Node
        process fixes its working directory and environment when it starts, so
        by the time this test runs neither ``CDK_OUTDIR`` nor an ``os.chdir``
        can move where a synth writes. The assembly object has everything worth
        checking and no such constraint.

        The dummy account, region and certificate come from
        ``_app_environment``. Nothing here calls ``from_lookup``, so no
        credentials and no context lookups are needed; the certificate is
        required at *synth* because both ALB listeners are HTTPS, and an ACM
        ARN is never resolved until a deployment.
        """
        cdk_dir = core_cdk_dir if profile == "core" else CDK_DIR

        with _app_environment(cdk_dir):
            # No `App.synth` stub -- calling it for real is the entire point.
            namespace = runpy.run_path(str(cdk_dir / "app.py"), run_name="__main__")

        assembly = namespace["app"].synth()
        produced = {stack.stack_name for stack in assembly.stacks}
        assert produced, f"{profile}: synth produced no stacks"

        # The stack set is pinned, not counted: a stack silently dropping out
        # of a deploy is the defect the ENABLE_MODULE_STACKS gate produced
        # before this file existed.
        expected = CORE_STACKS | {
            "experimentation-auth-dev",
            "experimentation-api-dev",
            "experimentation-compute-dev",
            "experimentation-redis-dev",
            "experimentation-dynamodb-dev",
            "experimentation-migrations-dev",
        }
        assert expected <= produced, f"{profile}: missing {sorted(expected - produced)}"

        if profile == "full":
            assert MODULE_STACKS <= produced, (
                f"full: missing module stacks {sorted(MODULE_STACKS - produced)}"
            )
        else:
            assert not (MODULE_STACKS & produced), (
                f"core: module stacks leaked in {sorted(MODULE_STACKS & produced)}"
            )

        # Every stack carries a real template -- synth having "succeeded" with
        # an empty one would mean nothing.
        for stack in assembly.stacks:
            assert stack.template.get("Resources"), (
                f"{profile}: {stack.stack_name} synthesised no resources"
            )

    @pytest.mark.regression
    def test_the_load_balancer_can_still_reach_the_tasks(self):
        """The ALB -> task ingress survives, and is written by the fargate stack.

        This is the half of the cycle fix that fails *silently*.  Importing the
        compute stack's security group with ``mutable=False`` is what breaks the
        cycle, and it also makes CDK decline -- with no warning and no
        annotation -- to write the rule that
        ``attach_to_application_target_group`` would otherwise have added.  The
        explicit ``CfnSecurityGroupIngress`` in ``fargate_service_stack.py``
        puts it back.

        Delete that construct and everything still synthesises, every other
        test here still passes, and the service still answers -- because
        ``compute_stack.py`` opens 0.0.0.0/0 on 8000 (see #175's neighbourhood).
        The day that rule is tightened, the load balancer goes dark.  So the
        rule is asserted here rather than left to be inferred from a green
        synth.
        """
        with _app_environment(CDK_DIR):
            namespace = runpy.run_path(str(CDK_DIR / "app.py"), run_name="__main__")
        assembly = namespace["app"].synth()

        fargate = next(
            s for s in assembly.stacks if s.stack_name == "experimentation-fargate-dev"
        )
        ingress = [
            props
            for res in fargate.template["Resources"].values()
            if res["Type"] == "AWS::EC2::SecurityGroupIngress"
            for props in [res.get("Properties", {})]
            if props.get("FromPort") == 8000 and props.get("ToPort") == 8000
        ]
        assert len(ingress) == 1, (
            "expected exactly one ALB->task ingress rule on port 8000 in "
            f"experimentation-fargate-dev, found {len(ingress)}"
        )

        rule = ingress[0]
        assert rule.get("IpProtocol") == "tcp", rule
        # Sourced from a security group, never a CIDR: a rule that widened to
        # 0.0.0.0/0 here would pass a "the rule exists" check and be wrong.
        assert "SourceSecurityGroupId" in rule, rule
        assert "CidrIp" not in rule, rule
        # And it targets the compute stack's group, which is why the rule has
        # to be written from this side at all.
        assert "GroupId" in rule, rule
