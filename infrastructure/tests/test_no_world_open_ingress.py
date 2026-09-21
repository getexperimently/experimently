"""Nothing is reachable from the whole internet except the load balancer.

Two rules in this app were open to ``0.0.0.0/0`` and neither needed to be:

* the bastion security group on port 22 (#175), which the Aurora cluster
  trusts and which is advertised in SSM and a ``CfnOutput`` as the thing to
  attach a bastion to.  Its only control was a code comment reading
  "IMPORTANT: Replace with your specific IP range in production!", so a plain
  ``cdk deploy`` opened SSH to the internet.  ``cdk synth`` warned about it on
  every run (CloudFormation-Validate W2508) and the warning was scrolled past,
  which is the argument for asserting it instead;
* the ECS task port 8000, which let anything routable inside the VPC reach the
  tasks directly, bypassing the load balancer.  It could not be removed before
  #174, because it was the only reason the ALB could reach the tasks at all.

What remains is the load balancer's own 80 and 443, which is what a public ALB
is for.  Anything else that becomes world-open has to be argued for here.
"""

from __future__ import annotations

import runpy

import pytest

from .test_app_profiles import CDK_DIR, _app_environment

#: (port, why) for the rules a public deployment must have.  A range is given
#: as its own entry rather than a span, so widening one is a visible edit.
ALLOWED_WORLD_OPEN_PORTS = {
    80: "the ALB's HTTP listener, which redirects to HTTPS",
    443: "the ALB's HTTPS listener",
}


def _world_open_rules(assembly) -> list[tuple[str, str, int | str, str]]:
    """Every ingress rule in the app whose peer is the whole internet.

    Both spellings are collected: a standalone
    ``AWS::EC2::SecurityGroupIngress`` and the inline ``SecurityGroupIngress``
    list on ``AWS::EC2::SecurityGroup``.  Missing either would make this pass
    for the wrong reason -- the bastion rule was the inline kind.
    """
    found = []
    for stack in assembly.stacks:
        for logical_id, resource in stack.template.get("Resources", {}).items():
            if resource["Type"] == "AWS::EC2::SecurityGroupIngress":
                rules = [resource.get("Properties", {})]
            elif resource["Type"] == "AWS::EC2::SecurityGroup":
                rules = resource.get("Properties", {}).get("SecurityGroupIngress") or []
            else:
                continue
            for rule in rules:
                if not isinstance(rule, dict):
                    continue
                if rule.get("CidrIp") == "0.0.0.0/0" or rule.get("CidrIpv6") == "::/0":
                    found.append(
                        (
                            stack.stack_name,
                            logical_id,
                            rule.get("FromPort", "all"),
                            str(rule.get("Description", "")),
                        )
                    )
    return found


@pytest.fixture(scope="module")
def assembly():
    with _app_environment(CDK_DIR):
        namespace = runpy.run_path(str(CDK_DIR / "app.py"), run_name="__main__")
    return namespace["app"].synth()


@pytest.mark.regression
def test_the_scan_finds_the_rules_that_should_be_there(assembly):
    """Guard against the assertion below passing on an empty list.

    Every way this scan can break -- a renamed resource type, a CDK version
    that stops emitting inline rules, a synth that produced nothing -- shows up
    as zero findings, and zero findings is exactly what "no world-open rules"
    looks like. So the ports that SHOULD be open are asserted present.
    """
    ports = {port for _, _, port, _ in _world_open_rules(assembly)}
    assert ports == set(ALLOWED_WORLD_OPEN_PORTS), (
        f"expected the ALB's {sorted(ALLOWED_WORLD_OPEN_PORTS)} and nothing else, "
        f"got {sorted(ports)}"
    )


@pytest.mark.regression
def test_nothing_else_is_open_to_the_internet(assembly):
    unexpected = [
        (stack, logical_id, port, desc)
        for stack, logical_id, port, desc in _world_open_rules(assembly)
        if port not in ALLOWED_WORLD_OPEN_PORTS
    ]
    assert not unexpected, (
        "these accept traffic from 0.0.0.0/0 and are not the load balancer:\n"
        + "\n".join(f"  {s}/{lid}  port {p}  {d}" for s, lid, p, d in unexpected)
    )


@pytest.mark.regression
def test_the_bastion_group_exists_but_lets_nobody_in(assembly):
    """No `bastion_ssh_cidr` context means no SSH rule at all.

    The group itself stays -- `enhanced_database_stack.py` grants it access to
    Aurora, so removing it would change the database's trust relationships.
    What goes is the way in.
    """
    vpc = next(s for s in assembly.stacks if s.stack_name.endswith("-vpc-dev"))
    bastion = [
        (lid, res)
        for lid, res in vpc.template["Resources"].items()
        if res["Type"] == "AWS::EC2::SecurityGroup"
        and "bastion" in str(res.get("Properties", {}).get("GroupDescription", "")).lower()
    ]
    assert len(bastion) == 1, f"expected one bastion security group, found {bastion}"

    _, group = bastion[0]
    ingress = group.get("Properties", {}).get("SecurityGroupIngress") or []
    assert not ingress, (
        "the bastion group has an ingress rule without anyone asking for one; "
        f"deploy with -c bastion_ssh_cidr=<your cidr> to add it. Got: {ingress}"
    )
