"""Every environment's Aurora cluster can actually be created.

Two things made the database stack undeployable in every environment, prod
included:

* **The engine version.** The cluster and both parameter groups asked for
  Aurora PostgreSQL 15.3, which is deprecated and no longer orderable, so
  ``CreateDBCluster`` could not succeed. They now share one module constant,
  ``AURORA_POSTGRES_VERSION`` (15.17).
* **The memory parameters.** ``shared_buffers`` and ``effective_cache_size`` are
  in 8 kB pages and were written as kB, so ``shared_buffers`` asked for more
  than the instance's whole memory (16 GiB on a 4 GiB staging instance). Both
  are now left at Aurora's instance-scaled defaults.

Asserted on a real ``app.synth()`` of each environment, the way ``cdk synth``
builds it.
"""

from __future__ import annotations

import pytest

from .test_dashboard_service import _synth

ENVIRONMENTS = ("dev", "staging", "prod", "demo")
EXPECTED_ENGINE_VERSION = "15.17"
EXPECTED_FAMILY = "aurora-postgresql15"
# Left to Aurora's defaults on purpose: both are 8 kB units, and the values
# this stack used to set were computed as kB.
FORBIDDEN_INSTANCE_PARAMETERS = ("shared_buffers", "effective_cache_size")


@pytest.fixture(scope="module", params=ENVIRONMENTS)
def database(request) -> tuple[str, dict]:
    assembly = _synth(request.param)
    (stack,) = [
        s
        for s in assembly.stacks
        if s.stack_name == f"experimentation-database-{request.param}"
    ]
    return request.param, stack.template["Resources"]


def _of_type(resources: dict, rtype: str) -> list[dict]:
    return [r["Properties"] for r in resources.values() if r["Type"] == rtype]


@pytest.mark.regression
def test_the_cluster_uses_an_orderable_engine_version(database):
    env, resources = database
    clusters = _of_type(resources, "AWS::RDS::DBCluster")
    assert len(clusters) == 1, f"{env}: {len(clusters)} Aurora clusters"
    (cluster,) = clusters
    assert cluster["Engine"] == "aurora-postgresql", f"{env}: {cluster['Engine']!r}"
    assert cluster["EngineVersion"] == EXPECTED_ENGINE_VERSION, (
        f"{env}: the Aurora cluster asks for engine version "
        f"{cluster['EngineVersion']!r}, not {EXPECTED_ENGINE_VERSION!r}"
    )


@pytest.mark.regression
def test_both_parameter_groups_match_the_engine_family(database):
    env, resources = database
    groups = _of_type(resources, "AWS::RDS::DBClusterParameterGroup") + _of_type(
        resources, "AWS::RDS::DBParameterGroup"
    )
    assert len(groups) == 2, f"{env}: {len(groups)} parameter groups, expected 2"
    for group in groups:
        assert group["Family"] == EXPECTED_FAMILY, (
            f"{env}: parameter group {group.get('Description')!r} is family "
            f"{group['Family']!r}, not {EXPECTED_FAMILY!r}"
        )


@pytest.mark.regression
def test_the_instance_parameter_group_leaves_memory_to_aurora(database):
    env, resources = database
    (instance_group,) = _of_type(resources, "AWS::RDS::DBParameterGroup")
    parameters = instance_group.get("Parameters", {})
    present = [p for p in FORBIDDEN_INSTANCE_PARAMETERS if p in parameters]
    assert not present, (
        f"{env}: the instance parameter group sets {present}; these are 8 kB "
        "units and are left at Aurora's instance-scaled defaults"
    )
    # The rest of the group is still there, so an empty group cannot pass.
    assert parameters.get("work_mem"), f"{env}: work_mem is missing: {parameters}"
