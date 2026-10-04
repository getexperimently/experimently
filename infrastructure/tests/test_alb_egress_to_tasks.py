"""The load balancer keeps its egress to the API tasks for both live colours (#801).

The ALB's group has no allow-all outbound rule, so it reaches a target only
through an explicit egress rule. Before #801 the tcp 8000 rule to the API
tasks was written only implicitly, by ``attach_to_application_target_group``
through the blue target group's listener -- so it existed only while
``api_live_target_group`` was blue. A green synth dropped it, and the staging
``cdk diff`` with ``-c api_live_target_group=green`` planned to destroy it:
every ``/api/v1`` and ``/health`` request through the load balancer would then
fail while the dashboard at ``/`` kept working.

``fargate_service_stack.py`` now asks for the rule explicitly against the same
imported peer, so CDK gives it the logical id the deployed stacks already
carry, and on blue skips it as a duplicate of the implicit one.

Every case is a real ``app.synth()``, over every environment the stack is
built for, both profiles and both colours (16 synths):

* **G1** -- the egress to the ECS group is exactly one rule, under the
  deployed logical id, with exactly the deployed properties. A rule under any
  other id would be created beside (or in place of) the deployed one.
* **G2** -- the ALB group's egress is exactly the two rules (8000 to the ECS
  group, 8080 to the dashboard group): no inline egress, no duplicate.
* **G3** -- flipping the live colour changes no ingress or egress rule.
* **G4** -- blue and green differ only in the two ``ApiPaths`` listener rules
  and ``BackendService``'s DependsOn, so a new colour-dependent resource fails
  here with a diff instead of slipping through.
"""

from __future__ import annotations

import json

import pytest

from .test_codedeploy_alarms import _synth

#: Every environment app.py builds a fargate stack for. demo is included on
#: purpose (EM condition 1 of the #801 review): it synthesises the same stack.
ENVIRONMENTS = ("dev", "staging", "prod", "demo")
PROFILES = ("core", "full")
LIVE = ("blue", "green")

CASES = [(e, p, live) for e in ENVIRONMENTS for p in PROFILES for live in LIVE]
# The whole matrix, core-green included: a partial matrix is how the gap this
# file closes went unnoticed.
assert len(CASES) == 16, CASES

#: The logical id of the ALB -> ECS tcp 8000 egress rule, per environment. Both
#: profiles share it. These are literals, not recomputed, because a different
#: id is a remove-and-add on a deployed stack.
DEPLOYED_ID = {
    # Synth-derived, not checked against a deployment: main's blue synth at
    # 2fe9da1e.
    "dev": "BackendALBSecurityGrouptoexperimentationfargatedevImportedEcsSecurityGroupF383F1978000BC8B6378",
    # Checked against the deployed stack: the founder's staging `cdk diff`
    # (green pin) of 2026-10-03 named this id on its `[-]` line (diff line
    # 187), recorded in launch-readiness/alb-egress-801/
    # founder-staging-evidence-2026-10-03.md in the founder's private planning
    # repository. It also equals main's blue synth at 2fe9da1e.
    "staging": "BackendALBSecurityGrouptoexperimentationfargatestagingImportedEcsSecurityGroupC89BEFCF8000AEE5A56F",
    # Synth-derived, not checked against a deployment: main's blue synth at
    # 2fe9da1e.
    "prod": "BackendALBSecurityGrouptoexperimentationfargateprodImportedEcsSecurityGroup16B1F950800051E3B09E",
    # Synth-derived, not checked against a deployment: main's blue synth at
    # 2fe9da1e.
    "demo": "BackendALBSecurityGrouptoexperimentationfargatedemoImportedEcsSecurityGroup956FF10980001F21F999",
}

#: (IpProtocol, FromPort, ToPort, Description) of the deployed rule. The
#: description is the implicit rule's: CDK skips the explicit call by id, not
#: by content, so any other text would make the rule differ between colours.
DEPLOYED_PROPERTIES = ("tcp", 8000, 8000, "Load balancer to target")

#: The resources that may differ between blue and green (G4), by prefix.
COLOUR_DEPENDENT = (
    "BackendALBHttpsListenerApiPaths10Rule",
    "BackendALBHttpsListenerApiPaths11Rule",
    "BackendService",
)

EGRESS = "AWS::EC2::SecurityGroupEgress"
INGRESS = "AWS::EC2::SecurityGroupIngress"


@pytest.fixture(scope="module")
def templates():
    return {case: _synth(*case).template for case in CASES}


def _ids(case):
    return "-".join(case)


def _alb_group(resources: dict) -> str:
    (lid,) = [
        lid
        for lid, r in resources.items()
        if r["Type"] == "AWS::EC2::SecurityGroup"
        and lid.startswith("BackendALBSecurityGroup")
    ]
    return lid


def _ecs_group_ref(resources: dict, environment: str) -> dict:
    """The ECS group as this stack references it: AlbToTasksIngress's GroupId."""
    (ingress,) = [
        r
        for lid, r in resources.items()
        if r["Type"] == INGRESS and lid.startswith("AlbToTasksIngress")
    ]
    ref = ingress["Properties"]["GroupId"]
    assert ref["Fn::ImportValue"].startswith(
        f"experimentation-compute-{environment}:"
    ), ref
    return ref


def _alb_egress(resources: dict) -> dict:
    alb = {"Fn::GetAtt": [_alb_group(resources), "GroupId"]}
    return {
        lid: r
        for lid, r in resources.items()
        if r["Type"] == EGRESS and r["Properties"].get("GroupId") == alb
    }


def _rules(resources: dict, rtype: str) -> dict:
    return {
        lid: json.dumps(r, sort_keys=True)
        for lid, r in resources.items()
        if r["Type"] == rtype
    }


@pytest.mark.regression
@pytest.mark.parametrize("case", CASES, ids=_ids)
def test_the_load_balancer_reaches_the_tasks_under_the_deployed_id(templates, case):
    """G1: exactly one egress rule to the ECS group, with the deployed id and
    the deployed properties, whichever colour is live."""
    environment = case[0]
    resources = templates[case]["Resources"]
    ecs = _ecs_group_ref(resources, environment)
    to_ecs = {
        lid: (
            r["Properties"].get("IpProtocol"),
            r["Properties"].get("FromPort"),
            r["Properties"].get("ToPort"),
            r["Properties"].get("Description"),
        )
        for lid, r in _alb_egress(resources).items()
        if r["Properties"].get("DestinationSecurityGroupId") == ecs
    }
    assert to_ecs == {DEPLOYED_ID[environment]: DEPLOYED_PROPERTIES}


@pytest.mark.regression
@pytest.mark.parametrize("case", CASES, ids=_ids)
def test_the_load_balancers_egress_is_exactly_the_two_targets(templates, case):
    """G2: the ALB group's egress is the API tasks on 8000 and the dashboard on
    8080, and nothing else -- no inline rule, no allow-all, no duplicate."""
    environment = case[0]
    resources = templates[case]["Resources"]
    alb = resources[_alb_group(resources)]
    assert "SecurityGroupEgress" not in alb["Properties"], alb["Properties"]

    ecs = _ecs_group_ref(resources, environment)
    (dashboard,) = [
        lid
        for lid, r in resources.items()
        if r["Type"] == "AWS::EC2::SecurityGroup"
        and lid.startswith("DashboardSecurityGroup")
    ]

    def target(props: dict):
        dest = props.get("DestinationSecurityGroupId")
        if dest == ecs:
            return "api-tasks"
        if dest == {"Fn::GetAtt": [dashboard, "GroupId"]}:
            return "dashboard"
        return json.dumps(dest if dest is not None else props.get("CidrIp"))

    rules = sorted(
        (
            r["Properties"].get("IpProtocol"),
            r["Properties"].get("FromPort"),
            r["Properties"].get("ToPort"),
            target(r["Properties"]),
        )
        for r in _alb_egress(resources).values()
    )
    assert len(rules) == len(set(rules)), f"duplicate egress rule: {rules}"
    assert rules == [
        ("tcp", 8000, 8000, "api-tasks"),
        ("tcp", 8080, 8080, "dashboard"),
    ]


@pytest.mark.regression
@pytest.mark.parametrize(
    "environment,profile",
    [(e, p) for e in ENVIRONMENTS for p in PROFILES],
    ids=lambda v: v,
)
@pytest.mark.parametrize("rtype", (EGRESS, INGRESS))
def test_flipping_the_live_colour_changes_no_ingress_or_egress_rule(
    templates, environment, profile, rtype
):
    """G3: the same rules, ids and properties, under blue and green."""
    blue = _rules(templates[(environment, profile, "blue")]["Resources"], rtype)
    green = _rules(templates[(environment, profile, "green")]["Resources"], rtype)
    assert sorted(blue) == sorted(green)
    for lid in blue:
        assert blue[lid] == green[lid], lid


@pytest.mark.parametrize(
    "environment,profile",
    [(e, p) for e in ENVIRONMENTS for p in PROFILES],
    ids=lambda v: v,
)
def test_blue_and_green_differ_only_in_the_api_routing(templates, environment, profile):
    """G4: the only colour-dependent resources are the two ApiPaths listener
    rules (which forward to the live group) and BackendService, whose DependsOn
    follows them."""
    blue = templates[(environment, profile, "blue")]["Resources"]
    green = templates[(environment, profile, "green")]["Resources"]
    only_blue = sorted(set(blue) - set(green))
    only_green = sorted(set(green) - set(blue))
    assert (only_blue, only_green) == ([], [])

    differing = sorted(lid for lid in blue if blue[lid] != green[lid])
    prefixes = [
        next((p for p in COLOUR_DEPENDENT if lid.startswith(p)), lid)
        for lid in differing
    ]
    assert prefixes == list(COLOUR_DEPENDENT), differing

    (service,) = [lid for lid in differing if lid.startswith("BackendService")]
    fields = {
        f
        for f in set(blue[service]) | set(green[service])
        if blue[service].get(f) != green[service].get(f)
    }
    assert fields == {"DependsOn"}, fields
