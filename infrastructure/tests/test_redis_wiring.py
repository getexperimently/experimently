"""The API task reaches this environment's Redis, over TLS (#147).

Before this, the backend task definition injected ``REDIS_URL`` from a
hand-made ``/<env>/experimentation/redis-url`` secret -- a variable nothing in
the application reads. Every Redis client is built from ``REDIS_HOST`` and
``REDIS_PORT``, which the task did not set, so the tasks connected to
``localhost``, found nothing, and "degraded gracefully": the rate limiter fell
back to per-task memory and the caches were skipped, with nothing reporting it.

And even with the right host they would have failed: the replication group has
in-transit encryption on, so it refuses a plaintext client. ``REDIS_SSL`` is
what makes every client speak TLS (``backend/tests/unit/core/test_redis_tls.py``
proves each one honours it); this file proves the task sets it.

Everything is asserted on a real ``app.synth()``: the value each variable
resolves to is followed through the cross-stack export back to the attribute of
the replication group it names, so a variable pointing at the reader endpoint,
or at the port where the host belongs, fails here rather than at 3 a.m.
"""

from __future__ import annotations

import pytest

from .test_dashboard_service import _synth

ENVIRONMENTS = ("dev", "staging")


def _stack(assembly, marker: str):
    (stack,) = [s for s in assembly.stacks if marker in s.stack_name]
    return stack


def _backend_container(fargate_template: dict) -> dict:
    (task_def,) = [
        r
        for r in fargate_template["Resources"].values()
        if r["Type"] == "AWS::ECS::TaskDefinition"
        and r["Properties"].get("Family", "").startswith("experimentation-backend-")
    ]
    (container,) = [
        c
        for c in task_def["Properties"]["ContainerDefinitions"]
        if c["Name"] == "backend"
    ]
    return container


def _replication_group(redis_template: dict) -> tuple[str, dict]:
    ((lid, group),) = [
        (lid, r)
        for lid, r in redis_template["Resources"].items()
        if r["Type"] == "AWS::ElastiCache::ReplicationGroup"
    ]
    return lid, group


def _exported(redis_stack, redis_template: dict, export_name) -> object:
    """The value the Redis stack exports under ``export_name``."""
    for output in redis_template.get("Outputs", {}).values():
        name = output.get("Export", {}).get("Name")
        if name == export_name:
            return output["Value"]
    raise AssertionError(
        f"{redis_stack.stack_name} exports nothing named {export_name!r}; "
        f"exports: {[o.get('Export', {}).get('Name') for o in redis_template.get('Outputs', {}).values()]}"
    )


def _resolve(value, redis_stack, redis_template: dict):
    """Follow an ``Fn::ImportValue`` back to what the Redis stack exported."""
    assert isinstance(value, dict) and "Fn::ImportValue" in value, (
        f"expected a value imported from {redis_stack.stack_name}, got {value!r}"
    )
    return _exported(redis_stack, redis_template, value["Fn::ImportValue"])


@pytest.fixture(scope="module", params=ENVIRONMENTS)
def wiring(request):
    assembly = _synth(request.param)
    fargate = _stack(assembly, "-fargate-")
    redis = _stack(assembly, "-redis-")
    container = _backend_container(fargate.template)
    return {
        "env": request.param,
        "fargate": fargate,
        "redis": redis,
        "environment": {
            e["Name"]: e["Value"] for e in container.get("Environment", [])
        },
        "secrets": {s["Name"]: s["ValueFrom"] for s in container.get("Secrets", [])},
    }


@pytest.mark.unit
@pytest.mark.regression
def test_the_task_gets_the_replication_groups_primary_endpoint(wiring):
    env, redis = wiring["environment"], wiring["redis"]
    group_id, _ = _replication_group(redis.template)
    for name, attribute in (
        ("REDIS_HOST", "PrimaryEndPoint.Address"),
        ("REDIS_PORT", "PrimaryEndPoint.Port"),
    ):
        assert name in env, (
            f"the {wiring['env']} API task sets no {name}; the application then "
            "connects to localhost and silently runs without Redis (#147)"
        )
        assert _resolve(env[name], redis, redis.template) == {
            "Fn::GetAtt": [group_id, attribute]
        }, f"{name} is not the replication group's {attribute}"


@pytest.mark.unit
@pytest.mark.regression
def test_the_task_speaks_tls_to_a_replication_group_that_requires_it(wiring):
    _, group = _replication_group(wiring["redis"].template)
    assert group["Properties"]["TransitEncryptionEnabled"] is True
    assert wiring["environment"].get("REDIS_SSL") == "true", (
        f"the {wiring['env']} replication group has in-transit encryption on and "
        "refuses plaintext, but the API task does not set REDIS_SSL=true "
        f"(environment: {sorted(wiring['environment'])})"
    )


@pytest.mark.unit
@pytest.mark.regression
def test_there_is_no_redis_url_and_no_redis_secret(wiring):
    """REDIS_URL was read by nothing; its secret was one more thing to hand-make."""
    names = set(wiring["environment"]) | set(wiring["secrets"])
    assert "REDIS_URL" not in names
    assert "redis-url" not in str(wiring["fargate"].template), (
        "the fargate stack still names the redis-url secret (task definition "
        "or IAM policy); ECS refuses to start a task whose secret does not exist"
    )
