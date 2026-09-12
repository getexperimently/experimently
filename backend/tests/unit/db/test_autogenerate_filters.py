"""The Community migration chain must not absorb Enterprise-owned constraints."""

from __future__ import annotations

import pytest

from backend.app.db.autogenerate_filters import (
    ENTERPRISE_MANAGED_CONSTRAINTS,
    include_object,
)


@pytest.mark.regression
@pytest.mark.parametrize("name", sorted(ENTERPRISE_MANAGED_CONSTRAINTS))
@pytest.mark.parametrize("reflected", [True, False])
def test_the_enterprise_foreign_keys_are_excluded_both_ways(name, reflected):
    """Whether the constraint is in the metadata and not the database (a
    migrated Enterprise database) or the other way round, autogenerate must
    neither add nor drop it: it belongs to the Enterprise branch."""
    assert (
        include_object(object(), name, "foreign_key_constraint", reflected, None)
        is False
    )


def test_everything_else_is_compared():
    assert (
        include_object(object(), "experiments_pkey", "primary_key", False, None) is True
    )
    assert include_object(object(), "ix_x", "index", True, None) is True
    assert include_object(object(), "experiments", "table", False, None) is True
    assert include_object(
        object(), "some_other_fkey", "foreign_key_constraint", False, None
    )


@pytest.mark.enterprise
def test_the_names_match_what_the_enterprise_model_attaches():
    """The filter is keyed by name, so the two lists must agree."""
    from backend.app.models import workspace

    source = open(workspace.__file__, encoding="utf-8").read()
    for name in ENTERPRISE_MANAGED_CONSTRAINTS:
        assert name in source, f"{name} is not attached by models/workspace.py"
