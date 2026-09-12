"""
Community-side behaviour of the optional-capability seam.

``backend/app/core/enterprise_features.py`` is the accessor layer over the
capability registry in ``backend/app/core/hooks.py``.  These tests pin the
Community half of that contract:

* an unregistered capability resolves to ``None`` and never raises,
* a registered one is handed back (or, for the provider-style keys, asked),
* every Community route that depends on one refuses with HTTP 501 rather
  than silently doing nothing.

Nothing here imports an Enterprise module: "installed" is simulated by
registering a stand-in under the capability's key.
"""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend.app.core import enterprise_features, hooks
from backend.app.schemas.experiment import ExperimentType


@contextmanager
def _capability_absent(*names: str):
    """Unregister *names* for the duration, restoring whatever was there."""
    saved = {name: hooks.get_capability(name) for name in names}
    with hooks._lock:
        for name in names:
            hooks._capabilities.pop(name, None)
    try:
        yield
    finally:
        for name, impl in saved.items():
            if impl is not None:
                hooks.register_capability(name, impl)


@contextmanager
def _capability(name: str, implementation):
    saved = hooks.get_capability(name)
    hooks.register_capability(name, implementation)
    try:
        yield
    finally:
        if saved is None:
            with hooks._lock:
                hooks._capabilities.pop(name, None)
        else:
            hooks.register_capability(name, saved)


# ---------------------------------------------------------------------------
# The seam itself
# ---------------------------------------------------------------------------


class TestCapabilityLookup:
    def test_unregistered_capability_resolves_to_none(self):
        assert hooks.get_capability("no.such.capability") is None

    def test_registration_replaces_not_first_wins(self):
        """A test that installs a fake after the loader ran must win."""
        with _capability("probe", "first"):
            hooks.register_capability("probe", "second")
            assert hooks.get_capability("probe") == "second"

    def test_counter_service_none_when_absent(self):
        with _capability_absent("counters.service"):
            assert enterprise_features.realtime_counter_service() is None

    def test_counter_service_is_a_provider_asked_each_time(self):
        """The scheduler runs for days and the licence can lapse under it."""
        answers = iter([object, None, object])
        with _capability("counters.service", lambda: next(answers)):
            assert enterprise_features.realtime_counter_service() is object
            assert enterprise_features.realtime_counter_service() is None
            assert enterprise_features.realtime_counter_service() is object

    def test_split_url_routing_unavailable_when_absent(self):
        with _capability_absent("split_url.routing"):
            assert enterprise_features.split_url_routing_available() is False

    def test_split_url_routing_follows_the_provider(self):
        with _capability("split_url.routing", lambda: None):
            assert enterprise_features.split_url_routing_available() is False
        with _capability("split_url.routing", lambda: lambda *a: "variant"):
            assert enterprise_features.split_url_routing_available() is True

    def test_split_url_preview_handler_none_when_absent(self):
        with _capability_absent("split_url.preview"):
            assert enterprise_features.split_url_preview_handler() is None

    def test_compliance_handlers_none_when_absent(self):
        with _capability_absent("compliance.report", "compliance.export"):
            assert enterprise_features.compliance_report_handler() is None
            assert enterprise_features.compliance_export_handler() is None

    @pytest.mark.enterprise
    def test_handlers_resolve_when_the_edition_is_registered(self):
        # This tree still ships the Enterprise modules and the transitional
        # registration installs them, so the seam must find them — a seam
        # that always returns None would hide a broken wiring.
        assert enterprise_features.split_url_routing_available() is True
        assert callable(enterprise_features.split_url_preview_handler())
        assert callable(enterprise_features.compliance_report_handler())
        assert callable(enterprise_features.compliance_export_handler())
        assert enterprise_features.realtime_counter_service() is not None

    @pytest.mark.regression
    def test_nothing_in_the_accessor_layer_names_an_enterprise_module(self):
        """The whole point of the registry: Community asks by key, not by path."""
        import inspect

        source = inspect.getsource(enterprise_features)
        for needle in (
            "split_url_service",
            "experiments_split_url",
            "compliance_reports",
            "dynamodb_counter_service",
            "importlib",
        ):
            assert needle not in source, needle


# ---------------------------------------------------------------------------
# Community refuses what it cannot route
# ---------------------------------------------------------------------------


def _user(is_superuser: bool = True):
    user = MagicMock()
    user.id = 1
    user.is_superuser = is_superuser
    user.role = "admin"
    user.username = "admin"
    return user


class TestSplitUrlRefusedWithoutRouting:
    """ExperimentType.SPLIT_URL stays a live enum value; creation must not."""

    def _create_kwargs(self, experiment_type):
        return {
            "experiment_in": SimpleNamespace(experiment_type=experiment_type),
            "db": MagicMock(),
            "current_user": _user(),
            "cache_control": {},
        }

    @pytest.mark.asyncio
    async def test_create_split_url_experiment_returns_501(self):
        from backend.app.api.v1.endpoints import experiments

        with (
            patch.object(experiments, "check_permission", return_value=True),
            patch.object(
                experiments, "split_url_routing_available", return_value=False
            ),
        ):
            with pytest.raises(HTTPException) as exc:
                await experiments.create_experiment(
                    **self._create_kwargs(ExperimentType.SPLIT_URL)
                )

        assert exc.value.status_code == 501
        assert "split_url" in exc.value.detail

    @pytest.mark.asyncio
    async def test_update_to_split_url_returns_501(self):
        from backend.app.api.v1.endpoints import experiments

        db = MagicMock()
        existing = MagicMock()
        existing.status = "draft"
        db.query.return_value.filter.return_value.first.return_value = existing
        with (
            patch.object(
                experiments, "split_url_routing_available", return_value=False
            ),
            patch.object(
                experiments.deps, "get_experiment_access", return_value=existing
            ),
        ):
            with pytest.raises(HTTPException) as exc:
                await experiments.update_experiment(
                    experiment_id=uuid4(),
                    experiment_in=SimpleNamespace(
                        experiment_type=ExperimentType.SPLIT_URL
                    ),
                    db=db,
                    current_user=_user(),
                    cache_control={},
                )

        assert exc.value.status_code == 501

    @pytest.mark.asyncio
    @pytest.mark.regression
    async def test_update_checks_existence_and_authorisation_before_the_edition(
        self,
    ):
        """The edition check used to run first, so a request for a missing
        experiment -- or from a user who may not touch it -- answered 501 and
        revealed which features the build lacks before checking who asked."""
        from backend.app.api.v1.endpoints import experiments

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        with patch.object(
            experiments, "split_url_routing_available", return_value=False
        ):
            with pytest.raises(HTTPException) as exc:
                await experiments.update_experiment(
                    experiment_id=uuid4(),
                    experiment_in=SimpleNamespace(
                        experiment_type=ExperimentType.SPLIT_URL
                    ),
                    db=db,
                    current_user=_user(),
                    cache_control={},
                )
        assert exc.value.status_code == 404

        existing = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = existing
        with (
            patch.object(
                experiments, "split_url_routing_available", return_value=False
            ),
            patch.object(
                experiments.deps,
                "get_experiment_access",
                side_effect=HTTPException(status_code=403, detail="not yours"),
            ),
        ):
            with pytest.raises(HTTPException) as exc:
                await experiments.update_experiment(
                    experiment_id=uuid4(),
                    experiment_in=SimpleNamespace(
                        experiment_type=ExperimentType.SPLIT_URL
                    ),
                    db=db,
                    current_user=_user(is_superuser=False),
                    cache_control={},
                )
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    @pytest.mark.regression
    async def test_restating_a_stored_split_url_type_is_not_a_change(self):
        """A full-object PUT of a legacy split-URL row that only renames it
        carries experiment_type='split_url' too; it used to be refused."""
        from backend.app.api.v1.endpoints import experiments

        db = MagicMock()
        existing = MagicMock()
        existing.status = "draft"
        existing.experiment_type = ExperimentType.SPLIT_URL
        db.query.return_value.filter.return_value.first.return_value = existing
        with (
            patch.object(
                experiments, "split_url_routing_available", return_value=False
            ),
            patch.object(
                experiments.deps, "get_experiment_access", return_value=existing
            ),
            patch.object(experiments, "_reject_unroutable_split_url") as reject,
        ):
            try:
                await experiments.update_experiment(
                    experiment_id=uuid4(),
                    experiment_in=SimpleNamespace(
                        experiment_type=ExperimentType.SPLIT_URL, name="renamed"
                    ),
                    db=db,
                    current_user=_user(),
                    cache_control={},
                )
            except Exception:
                pass  # the mocked service path beyond the guard is not under test
        reject.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.regression
    async def test_clone_is_held_to_the_same_rule_as_create(self):
        """POST /{id}/clone copies experiment_type verbatim, so a build without
        routing could mint a second split-URL experiment from a legacy one."""
        from backend.app.api.v1.endpoints import experiments

        db = MagicMock()
        source = MagicMock()
        source.experiment_type = ExperimentType.SPLIT_URL
        db.query.return_value.filter.return_value.first.return_value = source
        with (
            patch.object(
                experiments, "split_url_routing_available", return_value=False
            ),
            patch.object(
                experiments, "split_url_routing_installed", return_value=False
            ),
            patch.object(
                experiments.deps, "get_experiment_access", return_value=source
            ),
        ):
            with pytest.raises(HTTPException) as exc:
                await experiments.clone_experiment(
                    experiment_id=uuid4(),
                    db=db,
                    current_user=_user(),
                    cache_control=SimpleNamespace(enabled=False, redis=None),
                )
        assert exc.value.status_code == 501

    @pytest.mark.asyncio
    async def test_non_split_url_types_are_untouched(self):
        """The guard must not fire for ordinary experiment types."""
        from backend.app.api.v1.endpoints import experiments

        with patch.object(
            experiments, "split_url_routing_available", return_value=False
        ):
            for experiment_type in (ExperimentType.A_B, ExperimentType.MULTIVARIATE):
                experiments._reject_unroutable_split_url(experiment_type)
            experiments._reject_unroutable_split_url(None)

    @pytest.mark.asyncio
    async def test_preview_route_returns_501_without_handler(self):
        from backend.app.api.v1.endpoints import experiments

        with patch.object(experiments, "split_url_preview_handler", return_value=None):
            with pytest.raises(HTTPException) as exc:
                await experiments.preview_split_url_assignment(
                    experiment_id=uuid4(),
                    user_id="u1",
                    db=MagicMock(),
                    current_user=_user(),
                )

        assert exc.value.status_code == 501


class TestComplianceRoutesRefusedWithoutEnterprise:
    def test_report_route_returns_501_without_handler(self):
        from backend.app.api.v1.endpoints import compliance

        with patch.object(compliance, "compliance_report_handler", return_value=None):
            with pytest.raises(HTTPException) as exc:
                compliance.generate_compliance_report(
                    standard="soc2",
                    start_time=None,
                    end_time=None,
                    current_user=_user(),
                    db=MagicMock(),
                )

        assert exc.value.status_code == 501

    def test_export_route_returns_501_without_handler(self):
        from backend.app.api.v1.endpoints import compliance

        with patch.object(compliance, "compliance_export_handler", return_value=None):
            with pytest.raises(HTTPException) as exc:
                compliance.export_audit_events(
                    format="json",
                    start_time=None,
                    end_time=None,
                    current_user=_user(),
                    db=MagicMock(),
                )

        assert exc.value.status_code == 501

    def test_audit_event_listing_stays_community(self):
        """GET /compliance/audit-events must not consult the seam at all."""
        from backend.app.api.v1.endpoints import compliance

        service = MagicMock()
        service.get_events.return_value = {
            "items": [],
            "total": 0,
            "page": 1,
            "limit": 50,
        }
        with (
            _capability_absent("compliance.report", "compliance.export"),
            patch.object(hooks, "get_capability", side_effect=AssertionError("asked")),
            patch.object(compliance, "AuditLogService", return_value=service),
        ):
            result = compliance.list_audit_events(
                resource_type=None,
                actor_id=None,
                action=None,
                start_time=None,
                end_time=None,
                page=1,
                limit=50,
                current_user=_user(),
                db=MagicMock(),
            )

        assert result.total == 0
        service.get_events.assert_called_once()
