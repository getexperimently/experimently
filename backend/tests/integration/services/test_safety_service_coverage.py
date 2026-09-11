"""
Integration tests for SafetyService (backend/app/services/safety_service.py).

These tests exercise SafetyService against a real Postgres database (via the
`db_session` / `make_feature_flag` fixtures defined in
backend/tests/integration/conftest.py). See also
backend/tests/unit/services/test_safety_service.py (mock-based unit tests)
and backend/tests/integration/api/test_safety_api.py (HTTP-layer tests,
which already document two of the bugs below and work around them).

IMPORTANT - product bugs documented (not fixed) by these tests
----------------------------------------------------------------
While writing these tests we discovered that most of SafetyService's async
"public" surface, and several of its sync helpers, are currently broken:

1. Method-name shadowing. `get_safety_settings` and
   `get_feature_flag_safety_config` are each defined *twice* on
   `SafetyService`: once as `@staticmethod` (taking `db` as the first
   positional arg) near the top of the class, and again later in the class
   body as an `async def` *instance* method (taking only `self`/
   `self, feature_flag_id`). Because Python class bodies execute top to
   bottom and each `def` rebinds the same name in the class namespace, the
   later async definition completely replaces the earlier static one.
   `SafetyService.get_safety_settings` and
   `SafetyService.get_feature_flag_safety_config` are therefore ALWAYS the
   async instance versions - the static implementations are unreachable
   dead code (there is no way to invoke them through the class or an
   instance). See `TestMethodNameShadowing`.

2. `get_safety_settings` (the async instance version that wins per bug #1)
   and `async_get_safety_settings` both build a default row via
   `SafetySettings(enabled=True, auto_rollback_enabled=False,
   default_metrics=[])` when none exists yet. Neither `enabled` nor
   `auto_rollback_enabled` are real columns on the `SafetySettings` model
   (the actual column is `enable_automatic_rollbacks`), so this always
   raises `TypeError` whenever no settings row exists.

3. `SafetySettingsResponse`/`FeatureFlagSafetyConfigResponse` use the
   Pydantic v1 `class Config: orm_mode = True` idiom. Under the installed
   Pydantic v2 (2.10.x), `.from_orm()` unconditionally raises
   `PydanticUserError` ("You must set the config attribute
   `from_attributes=True`") no matter what is passed in. Every code path
   that reaches `.from_orm()` -
   `get_safety_settings`/`async_get_safety_settings` (existing-row
   branch), `create_or_update_safety_settings`,
   `get_feature_flag_safety_config`/`async_get_feature_flag_safety_config`
   (existing-config branch), and
   `create_or_update_feature_flag_safety_config` - is completely
   non-functional. Combined with bug #2, every read/write of safety
   settings or per-flag safety config through the async API always raises,
   and so does `check_feature_flag_safety` (which delegates to
   `async_get_feature_flag_safety_config` internally) for any existing
   flag.

4. Side effect on failure: `create_or_update_safety_settings` and
   `create_or_update_feature_flag_safety_config` both call
   `self.db.commit()` *before* the doomed `.from_orm()` call. The
   underlying DB write (create or update) actually succeeds and is
   persisted even though the method always raises `PydanticUserError` to
   the caller - callers have no way to know their write actually went
   through.

5. `create_feature_flag_safety_config` (static) reads `data.feature_flag_id`,
   but the `FeatureFlagSafetyConfigCreate` schema it is typed to accept has
   no `feature_flag_id` field at all (it does not inherit from
   `FeatureFlagSafetyConfigBase`, which is the schema class that does have
   it). Calling it with a genuine `FeatureFlagSafetyConfigCreate` instance
   always raises `AttributeError` immediately.

6. `create_rollback_record` (static) does
   `SafetyRollbackRecord(**data.model_dump())` where `data` is a
   `SafetyRollbackRecordCreate`. That schema has no `safety_config_id`
   field, but the model column is a non-nullable FK with no default, so
   this always raises `sqlalchemy.exc.IntegrityError` on commit.

7. `should_rollback` reads `safety_config.monitoring_enabled` /
   `safety_config.auto_rollback_enabled`, but `FeatureFlagSafetyConfig` has
   neither column (only `enabled`). As soon as a feature flag is ACTIVE
   with `rollout_percentage > 0`, this raises `AttributeError` - and unlike
   the later `check_feature_flag_safety` call (which *is* wrapped in
   try/except), this line sits outside that try block, so the exception
   propagates straight out of `should_rollback` to its caller.

8. `execute_rollback` constructs `SafetyRollbackRecord(trigger_value=...,
   threshold_value=..., rollout_percentage_before=..., description=...,
   metrics_data=...)`, none of which are real columns on the model (the
   real columns are `trigger_reason`, `previous_percentage`,
   `target_percentage`, `success`). This always raises `TypeError`, caught
   by the method's own try/except, which returns a "failure"
   `RollbackResponse`. Two further issues compound this:
     8a. The `RollbackResponse(...)` construction (both in the failure
         branch and in the otherwise-unreachable success branch) passes
         `current_percentage=...`, but the schema's field is actually named
         `new_percentage`. Pydantic v2 silently drops unknown kwargs, so
         `new_percentage` is always `None` in the returned response instead
         of the intended `-1` (failure) or `0`/target (success).
     8b. Whether the feature flag's `rollout_percentage` is left unchanged
         in the DB after a failed rollback depends on an unrelated
         implementation detail: `execute_rollback` calls
         `self.get_or_create_safety_config(db, feature_flag_id)` *between*
         setting `feature_flag.rollout_percentage = 0` and the (failing)
         `SafetyRollbackRecord` construction. If no safety config exists
         yet for the flag, `get_or_create_safety_config` performs its own
         internal `db.commit()`, which prematurely and silently commits the
         `rollout_percentage = 0` change - so the flag's traffic really is
         cut to 0% even though the method reports `success=False`. If a
         safety config already existed for the flag, no such interim commit
         happens, and the later `db.rollback()` correctly reverts the
         change. `execute_rollback`'s failure mode is therefore
         inconsistent: sometimes a true no-op, sometimes a silent data
         mutation while reporting failure. See
         `TestExecuteRollback.test_*_without_existing_config` vs.
         `test_*_with_existing_config`.

9. `get_latency_metrics` computes `latencies` via
   `getattr(metric, 'latency', 0)`, but `RawMetric` has no `latency`
   attribute at all (only `value`), so every metric always contributes `0`.
   `avg_latency`/`max_latency`/`min_latency`/`p95_latency` are therefore
   always `0` whenever there is any data, and the `if not latencies:`
   branch (distinct from the earlier `total_metrics == 0` branch) is
   unreachable dead code, since the list is never actually empty once any
   `RawMetric` rows match the query.

Given the above, tests below assert on the *actual* current (broken)
behaviour using `pytest.raises`/explicit assertions, so that a future fix
to the model/schema mismatch is caught by a red test here rather than
silently regressing elsewhere. Methods that are NOT affected by any of the
bugs above (most of the plain static CRUD helpers, `get_error_metrics`,
`rollback_feature_flag`/`async_rollback_feature_flag`,
`get_or_create_safety_config`, `update_feature_flag_safety_config`) are
tested with genuine happy-path/edge-case assertions.
"""
import uuid
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from pydantic import PydanticUserError
from sqlalchemy.exc import IntegrityError

from backend.app.models.feature_flag import FeatureFlag, FeatureFlagStatus
from backend.app.models.metrics.metric import RawMetric, ErrorLog
from backend.app.models.safety import (
    SafetySettings,
    FeatureFlagSafetyConfig,
    SafetyRollbackRecord,
    RollbackTriggerType,
)
from backend.app.schemas.safety import (
    SafetySettingsCreate,
    SafetySettingsUpdate,
    FeatureFlagSafetyConfigCreate,
    FeatureFlagSafetyConfigUpdate,
    SafetyRollbackRecordCreate,
    MetricThreshold,
)
from backend.app.services.safety_service import SafetyService

pytestmark = [pytest.mark.integration, pytest.mark.requires_db]


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _wipe_safety_settings(db_session):
    """Delete all SafetySettings rows (there should only ever be 0 or 1)."""
    db_session.query(SafetySettings).delete()
    db_session.commit()


@pytest.fixture
def safety_settings_guard(db_session):
    """Snapshot the global SafetySettings singleton row (if any) before the
    test runs, and restore that exact state afterwards - regardless of
    whether the test deletes rows, creates rows, or mutates rows. The
    safety_settings table is a process-wide singleton that is *not*
    truncated between tests, so tests that need a known starting state
    (e.g. "no settings row exists yet") must use this fixture rather than
    assuming a clean table.
    """
    original = db_session.query(SafetySettings).first()
    snapshot = None
    if original is not None:
        snapshot = {
            "enable_automatic_rollbacks": original.enable_automatic_rollbacks,
            "default_metrics": original.default_metrics,
        }
    yield
    db_session.rollback()  # in case the test left an aborted transaction
    rows = db_session.query(SafetySettings).all()
    if snapshot is None:
        for row in rows:
            db_session.delete(row)
        db_session.commit()
    else:
        if not rows:
            db_session.add(SafetySettings(**snapshot))
        else:
            first, *extra = rows
            first.enable_automatic_rollbacks = snapshot["enable_automatic_rollbacks"]
            first.default_metrics = snapshot["default_metrics"]
            db_session.add(first)
            for row in extra:
                db_session.delete(row)
        db_session.commit()


# ---------------------------------------------------------------------------
# Static: SafetySettings CRUD (unaffected by the bugs above)
# ---------------------------------------------------------------------------


class TestSafetySettingsStatic:
    def test_get_returns_none_when_table_empty(self, db_session, safety_settings_guard):
        """NOTE: SafetyService.get_safety_settings(db) cannot be exercised as
        a static method here - see TestMethodNameShadowing / bug #1. The
        static implementation is unreachable dead code, so this test simply
        confirms the table-empty precondition via a direct query and covers
        the equivalent behaviour through create_safety_settings below."""
        _wipe_safety_settings(db_session)
        assert db_session.query(SafetySettings).first() is None

    def test_create_succeeds_when_none_exists(self, db_session, safety_settings_guard):
        _wipe_safety_settings(db_session)
        data = SafetySettingsCreate(
            enable_automatic_rollbacks=True,
            default_metrics={
                "error_rate": MetricThreshold(warning_threshold=0.05, critical_threshold=0.1)
            },
        )
        created = SafetyService.create_safety_settings(db_session, data)

        assert created.id is not None
        assert created.enable_automatic_rollbacks is True
        assert created.default_metrics["error_rate"]["critical_threshold"] == 0.1

        # Confirm the new row is really in the DB (see note above re: why we
        # cannot use the shadowed static get_safety_settings here).
        fetched = db_session.query(SafetySettings).first()
        assert fetched.id == created.id

    def test_create_raises_value_error_when_already_exists(
        self, db_session, safety_settings_guard
    ):
        _wipe_safety_settings(db_session)
        db_session.add(SafetySettings(enable_automatic_rollbacks=False, default_metrics=None))
        db_session.commit()

        with pytest.raises(ValueError, match="already exist"):
            SafetyService.create_safety_settings(
                db_session, SafetySettingsCreate(enable_automatic_rollbacks=True)
            )

    def test_update_modifies_existing_row(self, db_session, safety_settings_guard):
        _wipe_safety_settings(db_session)
        db_session.add(
            SafetySettings(
                enable_automatic_rollbacks=False,
                default_metrics={"latency": {"warning_threshold": 100}},
            )
        )
        db_session.commit()

        updated = SafetyService.update_safety_settings(
            db_session, SafetySettingsUpdate(enable_automatic_rollbacks=True)
        )

        assert updated.enable_automatic_rollbacks is True
        # default_metrics was not part of the update payload (exclude_unset),
        # so it must be untouched.
        assert updated.default_metrics == {"latency": {"warning_threshold": 100}}

    def test_update_returns_none_when_table_empty(self, db_session, safety_settings_guard):
        _wipe_safety_settings(db_session)
        result = SafetyService.update_safety_settings(
            db_session, SafetySettingsUpdate(enable_automatic_rollbacks=True)
        )
        assert result is None


# ---------------------------------------------------------------------------
# Static: FeatureFlagSafetyConfig CRUD
# ---------------------------------------------------------------------------


class TestFeatureFlagSafetyConfigStatic:
    def test_create_raises_attribute_error_bug(self, db_session, make_feature_flag):
        """Documents bug #5: FeatureFlagSafetyConfigCreate has no
        feature_flag_id field, but create_feature_flag_safety_config reads
        data.feature_flag_id unconditionally."""
        data = FeatureFlagSafetyConfigCreate(enabled=True, metrics={}, rollback_percentage=0)
        with pytest.raises(AttributeError, match="feature_flag_id"):
            SafetyService.create_feature_flag_safety_config(db_session, data)

    def test_update_modifies_existing_config(self, db_session, make_feature_flag):
        flag = make_feature_flag()
        config = SafetyService.get_or_create_safety_config(db_session, flag.id)
        assert config.enabled is True
        assert config.rollback_percentage == 0

        updated = SafetyService.update_feature_flag_safety_config(
            db_session,
            flag.id,
            FeatureFlagSafetyConfigUpdate(enabled=False, rollback_percentage=42),
        )

        assert updated.enabled is False
        assert updated.rollback_percentage == 42
        # metrics was not part of the update payload; unchanged.
        assert updated.metrics == {}

    def test_update_returns_none_when_no_config_exists(self, db_session, make_feature_flag):
        flag = make_feature_flag()
        result = SafetyService.update_feature_flag_safety_config(
            db_session, flag.id, FeatureFlagSafetyConfigUpdate(enabled=False)
        )
        assert result is None

    def test_get_or_create_creates_new_config_with_defaults(self, db_session, make_feature_flag):
        flag = make_feature_flag()
        assert (
            db_session.query(FeatureFlagSafetyConfig)
            .filter(FeatureFlagSafetyConfig.feature_flag_id == flag.id)
            .first()
            is None
        )

        config = SafetyService.get_or_create_safety_config(db_session, flag.id)

        assert config.id is not None
        assert config.feature_flag_id == flag.id
        assert config.enabled is True
        assert config.metrics == {}
        assert config.rollback_percentage == 0

    def test_get_or_create_returns_existing_config_without_duplicating(
        self, db_session, make_feature_flag
    ):
        flag = make_feature_flag()
        first = SafetyService.get_or_create_safety_config(db_session, flag.id)
        second = SafetyService.get_or_create_safety_config(db_session, flag.id)

        assert first.id == second.id
        count = (
            db_session.query(FeatureFlagSafetyConfig)
            .filter(FeatureFlagSafetyConfig.feature_flag_id == flag.id)
            .count()
        )
        assert count == 1

    def test_get_or_create_raises_for_missing_flag(self, db_session):
        with pytest.raises(ValueError, match="does not exist"):
            SafetyService.get_or_create_safety_config(db_session, uuid.uuid4())


class TestCreateRollbackRecordStatic:
    def test_raises_integrity_error_due_to_missing_safety_config_id(
        self, db_session, make_feature_flag
    ):
        """Documents bug #6: SafetyRollbackRecordCreate has no
        safety_config_id field, but the model column is non-nullable with
        no default."""
        flag = make_feature_flag()
        data = SafetyRollbackRecordCreate(
            feature_flag_id=flag.id,
            trigger_type="manual",
            trigger_reason="test rollback",
            previous_percentage=50,
            target_percentage=0,
        )

        with pytest.raises(IntegrityError):
            SafetyService.create_rollback_record(db_session, data)

        # The session is left in an aborted transaction state after an
        # IntegrityError; roll back so it stays usable for later
        # assertions/fixture teardown.
        db_session.rollback()
        assert (
            db_session.query(SafetyRollbackRecord)
            .filter(SafetyRollbackRecord.feature_flag_id == flag.id)
            .count()
            == 0
        )


# ---------------------------------------------------------------------------
# Instance (sync): get_error_metrics / get_latency_metrics
# ---------------------------------------------------------------------------


class TestGetErrorMetrics:
    def test_raises_for_missing_flag(self, db_session):
        service = SafetyService(db_session)
        with pytest.raises(ValueError, match="does not exist"):
            service.get_error_metrics(db_session, uuid.uuid4())

    def test_returns_zero_metrics_when_no_data(self, db_session, make_feature_flag):
        flag = make_feature_flag()
        service = SafetyService(db_session)

        result = service.get_error_metrics(db_session, flag.id)

        assert result["error_count"] == 0
        assert result["total_evaluations"] == 0
        assert result["error_rate"] == 0
        assert result["error_types"] == {}
        assert result["timeframe_minutes"] == 15

    def test_computes_rate_and_error_type_breakdown(self, db_session, make_feature_flag):
        flag = make_feature_flag()
        # 3 errors: 2 "rate_limit", 1 "timeout".
        for _ in range(2):
            db_session.add(
                ErrorLog(feature_flag_id=flag.id, error_type="rate_limit", message="boom")
            )
        db_session.add(ErrorLog(feature_flag_id=flag.id, error_type="timeout", message="slow"))
        # 10 total evaluations.
        for _ in range(10):
            db_session.add(RawMetric(feature_flag_id=flag.id, metric_type="evaluation"))
        db_session.commit()

        service = SafetyService(db_session)
        result = service.get_error_metrics(db_session, flag.id)

        assert result["error_count"] == 3
        assert result["total_evaluations"] == 10
        assert result["error_rate"] == pytest.approx(0.3)
        assert result["error_types"] == {"rate_limit": 2, "timeout": 1}

    def test_excludes_data_outside_timeframe_window(self, db_session, make_feature_flag):
        flag = make_feature_flag()
        old_time = datetime.utcnow() - timedelta(hours=2)
        db_session.add(
            ErrorLog(
                feature_flag_id=flag.id,
                error_type="old_error",
                message="stale",
                created_at=old_time,
            )
        )
        db_session.add(
            RawMetric(feature_flag_id=flag.id, metric_type="evaluation", created_at=old_time)
        )
        db_session.commit()

        service = SafetyService(db_session)
        result = service.get_error_metrics(db_session, flag.id, timeframe_minutes=15)

        assert result["error_count"] == 0
        assert result["total_evaluations"] == 0
        assert result["error_types"] == {}


class TestGetLatencyMetrics:
    def test_raises_for_missing_flag(self, db_session):
        service = SafetyService(db_session)
        with pytest.raises(ValueError, match="does not exist"):
            service.get_latency_metrics(db_session, uuid.uuid4())

    def test_returns_zero_structure_when_no_data(self, db_session, make_feature_flag):
        flag = make_feature_flag()
        service = SafetyService(db_session)

        result = service.get_latency_metrics(db_session, flag.id)

        assert result["avg_latency"] == 0
        assert result["max_latency"] == 0
        assert result["min_latency"] == 0
        assert result["p95_latency"] == 0
        assert result["total_requests"] == 0

    def test_with_data_latency_is_always_zero_bug(self, db_session, make_feature_flag):
        """Documents bug #9: RawMetric has no `latency` attribute, so
        get_latency_metrics always reports 0 even though total_requests
        correctly reflects the number of matching rows."""
        flag = make_feature_flag()
        for _ in range(5):
            db_session.add(
                RawMetric(feature_flag_id=flag.id, metric_type="evaluation", value=123.4)
            )
        db_session.commit()

        service = SafetyService(db_session)
        result = service.get_latency_metrics(db_session, flag.id)

        assert result["total_requests"] == 5
        assert result["avg_latency"] == 0
        assert result["max_latency"] == 0
        assert result["min_latency"] == 0
        assert result["p95_latency"] == 0


class TestGetMetricValue:
    def test_returns_value_within_documented_simulated_range(self, db_session, make_feature_flag):
        flag = make_feature_flag()
        service = SafetyService(db_session)
        value = service._get_metric_value(flag.id, "error_rate")
        assert 0.1 <= value <= 5.0


# ---------------------------------------------------------------------------
# Bug #1: method-name shadowing
# ---------------------------------------------------------------------------


class TestMethodNameShadowing:
    def test_get_safety_settings_class_attribute_is_the_async_version(self):
        import inspect

        assert inspect.iscoroutinefunction(SafetyService.get_safety_settings)

    def test_get_feature_flag_safety_config_class_attribute_is_the_async_version(self):
        import inspect

        assert inspect.iscoroutinefunction(SafetyService.get_feature_flag_safety_config)

    def test_unshadowed_static_methods_remain_plain_functions(self):
        """Sanity check / contrast: static methods with unique names are NOT
        affected by the shadowing bug."""
        import inspect

        assert not inspect.iscoroutinefunction(SafetyService.create_safety_settings)
        assert not inspect.iscoroutinefunction(SafetyService.update_safety_settings)
        assert not inspect.iscoroutinefunction(SafetyService.get_or_create_safety_config)


# ---------------------------------------------------------------------------
# Bugs #2, #3, #4: async safety settings methods
# ---------------------------------------------------------------------------


class TestAsyncSafetySettingsBugs:
    @pytest.mark.asyncio
    async def test_async_get_safety_settings_no_row_raises_type_error(
        self, db_session, safety_settings_guard
    ):
        _wipe_safety_settings(db_session)
        service = SafetyService(db_session)
        with pytest.raises(TypeError, match="enabled"):
            await service.async_get_safety_settings()

    @pytest.mark.asyncio
    async def test_get_safety_settings_instance_call_shares_the_same_bug(
        self, db_session, safety_settings_guard
    ):
        """service.get_safety_settings() resolves to the async instance
        method per TestMethodNameShadowing, and shares async_get_safety_
        settings' identical broken default-creation logic."""
        _wipe_safety_settings(db_session)
        service = SafetyService(db_session)
        with pytest.raises(TypeError, match="enabled"):
            await service.get_safety_settings()

    @pytest.mark.asyncio
    async def test_get_safety_settings_instance_call_existing_row_raises_pydantic_user_error(
        self, db_session, safety_settings_guard
    ):
        """Existing-row branch of the shadowed instance get_safety_settings
        (distinct source lines from async_get_safety_settings, despite the
        identical body) - covered separately for its own coverage credit."""
        _wipe_safety_settings(db_session)
        db_session.add(
            SafetySettings(enable_automatic_rollbacks=False, default_metrics=None)
        )
        db_session.commit()

        service = SafetyService(db_session)
        with pytest.raises(PydanticUserError, match="from_attributes"):
            await service.get_safety_settings()

    @pytest.mark.asyncio
    async def test_async_get_safety_settings_existing_row_raises_pydantic_user_error(
        self, db_session, safety_settings_guard
    ):
        _wipe_safety_settings(db_session)
        db_session.add(
            SafetySettings(enable_automatic_rollbacks=True, default_metrics=None)
        )
        db_session.commit()

        service = SafetyService(db_session)
        with pytest.raises(PydanticUserError, match="from_attributes"):
            await service.async_get_safety_settings()

    @pytest.mark.asyncio
    async def test_create_or_update_safety_settings_creates_row_but_still_raises(
        self, db_session, safety_settings_guard
    ):
        _wipe_safety_settings(db_session)
        service = SafetyService(db_session)
        data = SafetySettingsCreate(
            enable_automatic_rollbacks=True,
            default_metrics={
                "error_rate": MetricThreshold(warning_threshold=0.1, critical_threshold=0.2)
            },
        )

        with pytest.raises(PydanticUserError):
            await service.create_or_update_safety_settings(data)

        # Bug #4: the write is persisted despite the exception.
        persisted = db_session.query(SafetySettings).first()
        assert persisted is not None
        assert persisted.enable_automatic_rollbacks is True

    @pytest.mark.asyncio
    async def test_create_or_update_safety_settings_updates_existing_row_but_still_raises(
        self, db_session, safety_settings_guard
    ):
        _wipe_safety_settings(db_session)
        db_session.add(
            SafetySettings(enable_automatic_rollbacks=False, default_metrics=None)
        )
        db_session.commit()

        service = SafetyService(db_session)
        data = SafetySettingsCreate(enable_automatic_rollbacks=True, default_metrics=None)

        with pytest.raises(PydanticUserError):
            await service.create_or_update_safety_settings(data)

        persisted = db_session.query(SafetySettings).first()
        assert persisted.enable_automatic_rollbacks is True


# ---------------------------------------------------------------------------
# Bugs #2, #3, #4: async feature flag safety config methods
# ---------------------------------------------------------------------------


class TestAsyncFeatureFlagSafetyConfigBugs:
    @pytest.mark.asyncio
    async def test_get_config_missing_flag_raises_404(self, db_session):
        service = SafetyService(db_session)
        with pytest.raises(HTTPException) as exc_info:
            await service.async_get_feature_flag_safety_config(uuid.uuid4())
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_config_existing_config_raises_pydantic_user_error(
        self, db_session, make_feature_flag
    ):
        flag = make_feature_flag()
        db_session.add(
            FeatureFlagSafetyConfig(
                feature_flag_id=flag.id, enabled=True, metrics={}, rollback_percentage=0
            )
        )
        db_session.commit()

        service = SafetyService(db_session)
        with pytest.raises(PydanticUserError, match="from_attributes"):
            await service.async_get_feature_flag_safety_config(flag.id)

    @pytest.mark.asyncio
    async def test_get_config_missing_config_falls_through_to_settings_bug(
        self, db_session, make_feature_flag, safety_settings_guard
    ):
        """When no config row exists, the method tries to build a default
        response from global settings via async_get_safety_settings(),
        inheriting bug #2 when no settings row exists either."""
        flag = make_feature_flag()
        _wipe_safety_settings(db_session)

        service = SafetyService(db_session)
        with pytest.raises(TypeError, match="enabled"):
            await service.async_get_feature_flag_safety_config(flag.id)

    @pytest.mark.asyncio
    async def test_get_feature_flag_safety_config_instance_alias_same_bug(
        self, db_session, make_feature_flag
    ):
        """service.get_feature_flag_safety_config(...) resolves to the async
        instance method per TestMethodNameShadowing."""
        flag = make_feature_flag()
        db_session.add(
            FeatureFlagSafetyConfig(
                feature_flag_id=flag.id, enabled=True, metrics={}, rollback_percentage=0
            )
        )
        db_session.commit()

        service = SafetyService(db_session)
        with pytest.raises(PydanticUserError):
            await service.get_feature_flag_safety_config(flag.id)

    @pytest.mark.asyncio
    async def test_get_feature_flag_safety_config_instance_missing_config_falls_through(
        self, db_session, make_feature_flag, safety_settings_guard
    ):
        """Missing-config branch of the shadowed instance
        get_feature_flag_safety_config (distinct source lines from
        async_get_feature_flag_safety_config, despite the identical body) -
        covered separately for its own coverage credit."""
        flag = make_feature_flag()
        _wipe_safety_settings(db_session)

        service = SafetyService(db_session)
        with pytest.raises(TypeError, match="enabled"):
            await service.get_feature_flag_safety_config(flag.id)

    @pytest.mark.asyncio
    async def test_create_or_update_config_missing_flag_raises_404(self, db_session):
        service = SafetyService(db_session)
        data = FeatureFlagSafetyConfigCreate(enabled=True, metrics={}, rollback_percentage=10)
        with pytest.raises(HTTPException) as exc_info:
            await service.create_or_update_feature_flag_safety_config(uuid.uuid4(), data)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_create_or_update_config_creates_row_but_still_raises(
        self, db_session, make_feature_flag
    ):
        flag = make_feature_flag()
        service = SafetyService(db_session)
        data = FeatureFlagSafetyConfigCreate(
            enabled=True,
            metrics={"latency": MetricThreshold(warning_threshold=100)},
            rollback_percentage=5,
        )

        with pytest.raises(PydanticUserError):
            await service.create_or_update_feature_flag_safety_config(flag.id, data)

        # Bug #4: the write is persisted despite the exception.
        persisted = (
            db_session.query(FeatureFlagSafetyConfig)
            .filter(FeatureFlagSafetyConfig.feature_flag_id == flag.id)
            .first()
        )
        assert persisted is not None
        assert persisted.rollback_percentage == 5

    @pytest.mark.asyncio
    async def test_create_or_update_config_updates_existing_row_but_still_raises(
        self, db_session, make_feature_flag
    ):
        flag = make_feature_flag()
        config = FeatureFlagSafetyConfig(
            feature_flag_id=flag.id, enabled=True, metrics={}, rollback_percentage=0
        )
        db_session.add(config)
        db_session.commit()

        service = SafetyService(db_session)
        data = FeatureFlagSafetyConfigCreate(enabled=False, metrics={}, rollback_percentage=99)

        with pytest.raises(PydanticUserError):
            await service.create_or_update_feature_flag_safety_config(flag.id, data)

        db_session.refresh(config)
        assert config.rollback_percentage == 99
        assert config.enabled is False


# ---------------------------------------------------------------------------
# check_feature_flag_safety
# ---------------------------------------------------------------------------


class TestCheckFeatureFlagSafety:
    @pytest.mark.asyncio
    async def test_missing_flag_raises_404(self, db_session):
        service = SafetyService(db_session)
        with pytest.raises(HTTPException) as exc_info:
            await service.check_feature_flag_safety(uuid.uuid4())
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_existing_flag_inherits_config_bug(self, db_session, make_feature_flag):
        """check_feature_flag_safety always delegates to
        async_get_feature_flag_safety_config internally, so it inherits
        bug #3 as soon as a config row exists for the flag."""
        flag = make_feature_flag()
        db_session.add(
            FeatureFlagSafetyConfig(
                feature_flag_id=flag.id, enabled=True, metrics={}, rollback_percentage=0
            )
        )
        db_session.commit()

        service = SafetyService(db_session)
        with pytest.raises(PydanticUserError):
            await service.check_feature_flag_safety(flag.id)


# ---------------------------------------------------------------------------
# rollback_feature_flag / async_rollback_feature_flag (NOT affected by the
# from_orm bug - these construct RollbackResponse directly).
# ---------------------------------------------------------------------------


class TestRollbackFeatureFlagAsync:
    @pytest.mark.asyncio
    async def test_rollback_feature_flag_happy_path(self, db_session, make_feature_flag):
        flag = make_feature_flag(rollout_percentage=80, status=FeatureFlagStatus.ACTIVE)
        service = SafetyService(db_session)

        result = await service.rollback_feature_flag(flag.id, percentage=10, reason="load test")

        assert result.success is True
        assert result.previous_percentage == 80
        assert result.new_percentage == 10
        assert "rolled back from 80% to 10%" in result.message
        assert result.details == {"reason": "load test"}

        db_session.refresh(flag)
        assert flag.rollout_percentage == 10

    @pytest.mark.asyncio
    async def test_rollback_feature_flag_missing_flag_raises_404(self, db_session):
        service = SafetyService(db_session)
        with pytest.raises(HTTPException) as exc_info:
            await service.rollback_feature_flag(uuid.uuid4())
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_rollback_feature_flag_uses_default_args(self, db_session, make_feature_flag):
        flag = make_feature_flag(rollout_percentage=50)
        service = SafetyService(db_session)

        result = await service.rollback_feature_flag(flag.id)

        assert result.new_percentage == 0
        assert result.details == {"reason": "Manual rollback"}

    @pytest.mark.asyncio
    async def test_async_rollback_feature_flag_happy_path(self, db_session, make_feature_flag):
        """async_rollback_feature_flag duplicates rollback_feature_flag's
        body under a different name; exercised directly for its own
        coverage credit."""
        flag = make_feature_flag(rollout_percentage=60)
        service = SafetyService(db_session)

        result = await service.async_rollback_feature_flag(
            flag.id, percentage=5, reason="dup coverage"
        )

        assert result.success is True
        assert result.previous_percentage == 60
        assert result.new_percentage == 5
        db_session.refresh(flag)
        assert flag.rollout_percentage == 5

    @pytest.mark.asyncio
    async def test_async_rollback_feature_flag_missing_flag_raises_404(self, db_session):
        service = SafetyService(db_session)
        with pytest.raises(HTTPException) as exc_info:
            await service.async_rollback_feature_flag(uuid.uuid4())
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Bug #7: should_rollback
# ---------------------------------------------------------------------------


class TestShouldRollback:
    def test_missing_flag_returns_false_none_none(self, db_session):
        service = SafetyService(db_session)
        assert service.should_rollback(db_session, uuid.uuid4()) == (False, None, None)

    def test_inactive_flag_returns_false_none_none(self, db_session, make_feature_flag):
        flag = make_feature_flag(status=FeatureFlagStatus.INACTIVE, rollout_percentage=50)
        service = SafetyService(db_session)
        assert service.should_rollback(db_session, flag.id) == (False, None, None)

    def test_zero_rollout_returns_false_none_none(self, db_session, make_feature_flag):
        flag = make_feature_flag(status=FeatureFlagStatus.ACTIVE, rollout_percentage=0)
        service = SafetyService(db_session)
        assert service.should_rollback(db_session, flag.id) == (False, None, None)

    def test_active_nonzero_rollout_raises_attribute_error_bug(
        self, db_session, make_feature_flag
    ):
        """Documents bug #7: FeatureFlagSafetyConfig has no
        `monitoring_enabled` column. This line is outside the method's
        try/except, so the AttributeError propagates to the caller instead
        of being swallowed."""
        flag = make_feature_flag(status=FeatureFlagStatus.ACTIVE, rollout_percentage=50)
        service = SafetyService(db_session)

        with pytest.raises(AttributeError, match="monitoring_enabled"):
            service.should_rollback(db_session, flag.id)


# ---------------------------------------------------------------------------
# Bug #8: execute_rollback
# ---------------------------------------------------------------------------


class TestExecuteRollback:
    def test_missing_flag_returns_failure_response_with_no_side_effects(self, db_session):
        service = SafetyService(db_session)

        result = service.execute_rollback(db_session, uuid.uuid4(), reason="probe")

        assert result.success is False
        assert result.previous_percentage == -1
        # Bug #8a: schema field is `new_percentage`, code sets
        # `current_percentage` (silently dropped), so it stays None.
        assert result.new_percentage is None
        assert "does not exist" in result.message

    def test_existing_flag_without_prior_config_silently_zeroes_rollout(
        self, db_session, make_feature_flag
    ):
        """Documents bug #8 + 8b: the SafetyRollbackRecord construction
        always raises TypeError (real columns don't match the kwargs used),
        which is swallowed and reported as success=False - but because no
        safety config exists yet for this flag, get_or_create_safety_config's
        internal commit() prematurely persists rollout_percentage=0 before
        the failure even happens."""
        flag = make_feature_flag(status=FeatureFlagStatus.ACTIVE, rollout_percentage=75)
        assert (
            db_session.query(FeatureFlagSafetyConfig)
            .filter(FeatureFlagSafetyConfig.feature_flag_id == flag.id)
            .first()
            is None
        )
        service = SafetyService(db_session)

        result = service.execute_rollback(
            db_session,
            flag.id,
            reason="metric threshold breached",
            trigger_type=RollbackTriggerType.CUSTOM_METRIC,
            trigger_value=9.9,
            threshold_value=5.0,
        )

        assert result.success is False
        assert result.previous_percentage == -1
        assert result.new_percentage is None
        assert "invalid keyword argument" in result.message

        # The flag's rollout percentage was silently committed to 0 despite
        # the reported failure.
        db_session.refresh(flag)
        assert flag.rollout_percentage == 0

        # No rollback record was ever persisted.
        assert (
            db_session.query(SafetyRollbackRecord)
            .filter(SafetyRollbackRecord.feature_flag_id == flag.id)
            .count()
            == 0
        )

        # The session must still be usable after the internal rollback().
        assert (
            db_session.query(FeatureFlag).filter(FeatureFlag.id == flag.id).first() is not None
        )

    def test_existing_flag_with_prior_config_leaves_rollout_unchanged(
        self, db_session, make_feature_flag
    ):
        """Contrast case for bug #8b: when a safety config already exists,
        get_or_create_safety_config does NOT commit internally, so the
        eventual db.rollback() correctly reverts the pending
        rollout_percentage=0 change and the flag is left untouched."""
        flag = make_feature_flag(status=FeatureFlagStatus.ACTIVE, rollout_percentage=75)
        db_session.add(
            FeatureFlagSafetyConfig(
                feature_flag_id=flag.id, enabled=True, metrics={}, rollback_percentage=0
            )
        )
        db_session.commit()

        service = SafetyService(db_session)
        result = service.execute_rollback(db_session, flag.id, reason="probe with config")

        assert result.success is False
        db_session.refresh(flag)
        assert flag.rollout_percentage == 75
