"""What each environment's Redis replication group costs and survives.

Staging runs one ``cache.t4g.small`` node. It used to run two
``cache.m6g.large`` nodes, about 40% of the staging stack's hourly cost, to
rehearse a failover nothing in the staging plan exercises. With one node there
is no replica, so automatic failover and Multi-AZ must both be off (ElastiCache
documents both as needing at least one replica).

Prod is pinned alongside it, unchanged at three ``cache.r6g.large`` nodes with
failover and Multi-AZ on, so shrinking staging cannot quietly shrink prod.

Asserted on a real ``app.synth()`` of each environment.
"""

from __future__ import annotations

import pytest

from .test_dashboard_service import _synth

EXPECTED = {
    "staging": {
        "CacheNodeType": "cache.t4g.small",
        "NumCacheClusters": 1,
        "AutomaticFailoverEnabled": False,
        "MultiAZEnabled": False,
    },
    "prod": {
        "CacheNodeType": "cache.r6g.large",
        "NumCacheClusters": 3,
        "AutomaticFailoverEnabled": True,
        "MultiAZEnabled": True,
    },
}


@pytest.fixture(scope="module", params=sorted(EXPECTED))
def replication_group(request) -> tuple[str, dict]:
    env = request.param
    assembly = _synth(env)
    (stack,) = [
        s for s in assembly.stacks if s.stack_name == f"experimentation-redis-{env}"
    ]
    groups = [
        r["Properties"]
        for r in stack.template["Resources"].values()
        if r["Type"] == "AWS::ElastiCache::ReplicationGroup"
    ]
    assert len(groups) == 1, f"{env}: {len(groups)} replication groups"
    return env, groups[0]


@pytest.mark.parametrize(
    "prop",
    ["CacheNodeType", "NumCacheClusters", "AutomaticFailoverEnabled", "MultiAZEnabled"],
)
def test_replication_group_sizing(replication_group, prop: str):
    env, group = replication_group
    expected = EXPECTED[env][prop]
    assert group.get(prop) == expected, (
        f"{env}: the Redis replication group has {prop}={group.get(prop)!r}, "
        f"expected {expected!r}"
    )


def test_encryption_is_unchanged(replication_group):
    """The smaller node keeps TLS, which every Redis client relies on (#147)."""
    env, group = replication_group
    assert group.get("TransitEncryptionEnabled") is True, env
    assert group.get("AtRestEncryptionEnabled") is True, env
