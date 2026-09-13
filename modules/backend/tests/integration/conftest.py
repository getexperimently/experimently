"""Integration fixtures, shared with the core integration tree.

The role users, the factory fixtures and the per-role ``TestClient`` fixtures
are defined once, in ``backend/tests/integration/conftest.py``; the modules'
API tests use them unchanged.  ``make_client_for_user`` is a plain helper, not
a fixture, and is imported by the tests that need it.
"""

from backend.tests.integration.conftest import (  # fixture re-exports
    admin_client,
    admin_user,
    analyst_client,
    analyst_user,
    developer_client,
    developer_user,
    make_assignment,
    make_event,
    make_experiment,
    make_feature_flag,
    make_metric,
    make_variant,
    viewer_client,
    viewer_user,
)
