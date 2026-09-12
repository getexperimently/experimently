"""
Unit tests for load test profiles: breakpoint shape, CRUD users, and DB stress users.

These tests validate the structure and configuration of the load test scripts
without requiring a running server or Locust runtime. They import the classes
and verify weights, task counts, payload structures, and shape stage definitions.

Note: These tests require locust to be importable. On some Python 3.9 / macOS
environments, locust triggers an SSL recursion error during import. Tests are
skipped automatically in that case.
"""

import pytest

# Guard against locust import failures (Python 3.9 SSL recursion on macOS)
try:
    import locust
except (ImportError, RecursionError):
    pytest.skip(
        "locust not available or import error (Python 3.9 SSL recursion on macOS)",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# BreakpointShape tests
# ---------------------------------------------------------------------------


class TestBreakpointShape:
    """Tests for the BreakpointShape LoadTestShape class."""

    def test_shape_has_stages(self):
        """BreakpointShape must define ramp stages."""
        from backend.tests.performance.locustfiles.breakpoint_test import (
            BreakpointShape,
        )

        shape = BreakpointShape()
        assert hasattr(shape, "stages"), (
            "BreakpointShape must have a 'stages' attribute"
        )
        assert len(shape.stages) >= 5, (
            f"Expected at least 5 ramp stages, got {len(shape.stages)}"
        )

    def test_stages_have_increasing_user_counts(self):
        """Each successive stage should have equal or greater user count (ramp up)."""
        from backend.tests.performance.locustfiles.breakpoint_test import (
            BreakpointShape,
        )

        shape = BreakpointShape()
        user_counts = [s["users"] for s in shape.stages]
        for i in range(1, len(user_counts)):
            assert user_counts[i] >= user_counts[i - 1], (
                f"Stage {i} users ({user_counts[i]}) < stage {i - 1} users ({user_counts[i - 1]})"
            )

    def test_stages_have_increasing_durations(self):
        """Stage durations must be cumulative and increasing."""
        from backend.tests.performance.locustfiles.breakpoint_test import (
            BreakpointShape,
        )

        shape = BreakpointShape()
        durations = [s["duration"] for s in shape.stages]
        for i in range(1, len(durations)):
            assert durations[i] > durations[i - 1], (
                f"Stage {i} duration ({durations[i]}) must be > stage {i - 1} ({durations[i - 1]})"
            )

    def test_stages_have_positive_spawn_rate(self):
        """Each stage must have a positive spawn rate."""
        from backend.tests.performance.locustfiles.breakpoint_test import (
            BreakpointShape,
        )

        shape = BreakpointShape()
        for i, stage in enumerate(shape.stages):
            assert stage["spawn_rate"] > 0, (
                f"Stage {i} spawn_rate must be positive, got {stage['spawn_rate']}"
            )

    def test_tick_returns_tuple_at_start(self):
        """tick() at time 0 should return a (users, spawn_rate) tuple."""
        from backend.tests.performance.locustfiles.breakpoint_test import (
            BreakpointShape,
        )

        shape = BreakpointShape()
        # Mock get_run_time to return 0
        shape.get_run_time = lambda: 0.0
        result = shape.tick()
        assert result is not None, "tick() should return a tuple at t=0"
        assert len(result) == 2, (
            f"tick() should return a 2-tuple, got {len(result)}-tuple"
        )

    def test_tick_returns_none_after_last_stage(self):
        """tick() should return None after all stages complete."""
        from backend.tests.performance.locustfiles.breakpoint_test import (
            BreakpointShape,
        )

        shape = BreakpointShape()
        # Set run time well past the last stage duration
        last_duration = shape.stages[-1]["duration"]
        shape.get_run_time = lambda: last_duration + 100
        result = shape.tick()
        assert result is None, "tick() should return None after all stages are done"

    def test_final_stage_has_high_user_count(self):
        """The final stage should target a high user count (>=1000) for breakpoint detection."""
        from backend.tests.performance.locustfiles.breakpoint_test import (
            BreakpointShape,
        )

        shape = BreakpointShape()
        final_users = shape.stages[-1]["users"]
        assert final_users >= 1000, (
            f"Final stage should have >= 1000 users, got {final_users}"
        )


# ---------------------------------------------------------------------------
# BreakpointUser tests
# ---------------------------------------------------------------------------


class TestBreakpointUser:
    """Tests for the BreakpointUser HttpUser class."""

    def test_user_class_exists(self):
        """BreakpointUser must be importable."""
        from backend.tests.performance.locustfiles.breakpoint_test import BreakpointUser

        assert BreakpointUser is not None

    def test_user_has_tasks(self):
        """BreakpointUser should define at least 3 tasks (mixed traffic)."""
        from backend.tests.performance.locustfiles.breakpoint_test import BreakpointUser

        # Locust stores tasks as a 'tasks' attribute on the class
        assert hasattr(BreakpointUser, "tasks") and len(BreakpointUser.tasks) >= 3, (
            "BreakpointUser should have at least 3 tasks for mixed traffic"
        )


# ---------------------------------------------------------------------------
# CrudWriteUser / CrudReadUser tests
# ---------------------------------------------------------------------------


class TestCrudUsers:
    """Tests for the CRUD load test user classes."""

    def test_write_user_exists(self):
        """CrudWriteUser must be importable."""
        from backend.tests.performance.locustfiles.crud_load_test import CrudWriteUser

        assert CrudWriteUser is not None

    def test_read_user_exists(self):
        """CrudReadUser must be importable."""
        from backend.tests.performance.locustfiles.crud_load_test import CrudReadUser

        assert CrudReadUser is not None

    def test_write_user_has_higher_weight(self):
        """CrudWriteUser should have higher weight (write-heavy test)."""
        from backend.tests.performance.locustfiles.crud_load_test import (
            CrudReadUser,
            CrudWriteUser,
        )

        assert CrudWriteUser.weight > CrudReadUser.weight, (
            f"CrudWriteUser weight ({CrudWriteUser.weight}) should be > "
            f"CrudReadUser weight ({CrudReadUser.weight})"
        )

    def test_write_user_has_tasks(self):
        """CrudWriteUser should define tasks for create/update/delete operations."""
        from backend.tests.performance.locustfiles.crud_load_test import CrudWriteUser

        assert hasattr(CrudWriteUser, "tasks") and len(CrudWriteUser.tasks) >= 3, (
            "CrudWriteUser should have at least 3 tasks (create, update, delete)"
        )

    def test_read_user_has_tasks(self):
        """CrudReadUser should define tasks for list/get/search operations."""
        from backend.tests.performance.locustfiles.crud_load_test import CrudReadUser

        assert hasattr(CrudReadUser, "tasks") and len(CrudReadUser.tasks) >= 2, (
            "CrudReadUser should have at least 2 tasks (list, get)"
        )


# ---------------------------------------------------------------------------
# DbStressUser tests
# ---------------------------------------------------------------------------


class TestDbStressUser:
    """Tests for the database stress test user class."""

    def test_user_class_exists(self):
        """DbStressUser must be importable."""
        from backend.tests.performance.locustfiles.db_stress_test import DbStressUser

        assert DbStressUser is not None

    def test_user_has_mixed_tasks(self):
        """DbStressUser should have tasks for writes, reads, and complex queries."""
        from backend.tests.performance.locustfiles.db_stress_test import DbStressUser

        assert hasattr(DbStressUser, "tasks") and len(DbStressUser.tasks) >= 3, (
            "DbStressUser should have at least 3 tasks (writes, reads, complex queries)"
        )

    def test_user_has_large_data_pool(self):
        """DB stress test should use a large user pool to stress connection pooling."""
        from backend.tests.performance.locustfiles import db_stress_test

        assert hasattr(db_stress_test, "USER_POOL_SIZE"), (
            "db_stress_test must define USER_POOL_SIZE"
        )
        assert db_stress_test.USER_POOL_SIZE >= 50_000, (
            f"USER_POOL_SIZE should be >= 50,000, got {db_stress_test.USER_POOL_SIZE}"
        )


# ---------------------------------------------------------------------------
# Test data constants
# ---------------------------------------------------------------------------


class TestCrudTestData:
    """Tests for test data constants in CRUD load test."""

    def test_experiment_keys_defined(self):
        """CRUD test must define experiment keys for payloads."""
        from backend.tests.performance.locustfiles import crud_load_test

        assert hasattr(crud_load_test, "EXPERIMENT_KEYS"), (
            "crud_load_test must define EXPERIMENT_KEYS"
        )
        assert len(crud_load_test.EXPERIMENT_KEYS) >= 10, (
            "Should have at least 10 experiment keys"
        )

    def test_feature_flag_keys_defined(self):
        """CRUD test must define feature flag keys for payloads."""
        from backend.tests.performance.locustfiles import crud_load_test

        assert hasattr(crud_load_test, "FEATURE_FLAG_KEYS"), (
            "crud_load_test must define FEATURE_FLAG_KEYS"
        )
        assert len(crud_load_test.FEATURE_FLAG_KEYS) >= 10, (
            "Should have at least 10 feature flag keys"
        )
