"""
Assignment and flag evaluation never log the user id, at any level (#269).

Every per-request path in ``AssignmentService`` -- a new assignment, a sticky
one, an ineligible user, targeting assignment, a targeting error, a bulk
assignment that fails, a reassignment -- and the flag service's two error
lines are driven with a distinctive user id. For each:

* no record, at any level, contains the user id;
* the routine per-request lines are at DEBUG, not INFO;
* an error line carries the exception's type, not its text (the text can
  repeat the user id or an attribute value);
* at least one record was captured (a positive control: a capture that records
  nothing would otherwise pass everything above).

Capture replaces each module's ``logger`` with a recorder that keeps every call
at every level, as ``backend/tests/unit/core/test_evaluation_logs_no_attribute_values.py``
does, and for the same reason: caplog would miss DEBUG records once
``setup_logging()`` has set the root level to INFO.
"""

from __future__ import annotations

import traceback
from types import SimpleNamespace
from typing import List, Tuple
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from backend.app.models.experiment import Experiment, ExperimentStatus
from backend.app.models.feature_flag import FeatureFlagStatus
from backend.app.services import assignment_service as asvc
from backend.app.services import feature_flag_service as ffs

pytestmark = [pytest.mark.unit, pytest.mark.regression]

USER = "alice.user269@example.com"
LEVELS = ("debug", "info", "warning", "error", "critical")

NATIVE_US_ONLY = {
    "version": "1.0",
    "rules": [
        {
            "id": "us_only",
            "rule": {
                "operator": "and",
                "conditions": [
                    {"attribute": "country", "operator": "eq", "value": "US"}
                ],
            },
            "rollout_percentage": 100,
            "priority": 1,
        }
    ],
}


class Recorder:
    """Stands in for a module logger and keeps every call, formatted, at every level."""

    def __init__(self) -> None:
        self.records: List[Tuple[str, str]] = []

    def bind(self) -> SimpleNamespace:
        def at(level: str):
            def log(message, *args, **kwargs):
                text = message % args if args else str(message)
                if kwargs.get("exc_info"):
                    text += "\n" + traceback.format_exc()
                if kwargs.get("extra"):
                    text += " " + repr(kwargs["extra"])
                self.records.append((level, text))

            return log

        methods = {level: at(level) for level in LEVELS}
        methods["warn"] = methods["warning"]
        methods["exception"] = lambda message, *a, **k: at("error")(
            message, *a, exc_info=True
        )
        methods["isEnabledFor"] = lambda _level: True
        return SimpleNamespace(**methods)

    def with_user(self) -> List[Tuple[str, str]]:
        return [r for r in self.records if USER in r[1]]

    def at(self, *levels: str) -> List[Tuple[str, str]]:
        return [r for r in self.records if r[0] in levels]


@pytest.fixture
def logs(monkeypatch) -> Recorder:
    recorder = Recorder()
    for module in (asvc, ffs):
        monkeypatch.setattr(module, "logger", recorder.bind())
    return recorder


def _variant(name: str, is_control: bool):
    variant = MagicMock()
    variant.id = uuid4()
    variant.name = name
    variant.is_control = is_control
    variant.traffic_allocation = 50
    return variant


@pytest.fixture
def experiment():
    exp = MagicMock(spec=Experiment)
    exp.id = uuid4()
    exp.status = ExperimentStatus.ACTIVE
    exp.mutual_exclusion_group_id = None
    exp.targeting_rules = None
    exp.variants = [_variant("control", True), _variant("treatment", False)]
    return exp


def _service(experiment, existing=None):
    db = MagicMock()
    db.query.return_value.options.return_value.filter.return_value.first.return_value = experiment
    db.query.return_value.filter.return_value.order_by.return_value.first.return_value = existing
    db.query.return_value.filter.return_value.first.return_value = existing
    svc = asvc.AssignmentService(db)
    svc.event_service = MagicMock()
    svc.global_holdout_service = MagicMock()
    svc.global_holdout_service.is_user_in_holdout.return_value = (False, 0, 57)
    svc.mutual_exclusion_service = MagicMock()
    svc.mutual_exclusion_service.is_user_eligible_for_experiment.return_value = True
    return svc


def _assert_clean(logs: Recorder, *, routine: bool) -> None:
    assert logs.records, "nothing was captured: the recorder is not wired in"
    assert logs.with_user() == [], logs.with_user()
    if routine:
        assert logs.at("info", "warning", "error", "critical") == [], logs.records


def test_new_assignment(logs, experiment):
    svc = _service(experiment)
    treatment = experiment.variants[1]
    with (
        patch.object(svc, "_assigned_result", return_value={}),
        patch.object(svc, "_hash_user_to_variant", return_value=treatment.id),
    ):
        svc.assign_user(USER, experiment.id)
    _assert_clean(logs, routine=True)


def test_sticky_assignment(logs, experiment):
    svc = _service(experiment, existing=MagicMock(variant_id=uuid4()))
    with patch.object(svc, "_assigned_result", return_value={}):
        svc.assign_user(USER, experiment.id)
    _assert_clean(logs, routine=True)


def test_ineligible_user(logs, experiment):
    svc = _service(experiment)
    svc.global_holdout_service.is_user_in_holdout.return_value = (True, 10, 3)
    result = svc.assign_user(USER, experiment.id)
    assert result["assigned"] is False
    _assert_clean(logs, routine=True)


def test_targeting_assignment_and_ineligible(logs, experiment):
    svc = _service(experiment)
    treatment = experiment.variants[1]
    with (
        patch.object(svc, "get_assignment", return_value={}),
        patch.object(svc, "_hash_user_to_variant", return_value=treatment.id),
    ):
        svc.assign_user_with_targeting(USER, experiment.id, {})
    with patch.object(
        svc,
        "_evaluate_experiment_targeting",
        return_value={"eligible": False, "reason": f"no match for {USER}"},
    ):
        svc.assign_user_with_targeting(USER, experiment.id, {})
    _assert_clean(logs, routine=True)


def test_sticky_targeting_assignment(logs, experiment):
    svc = _service(experiment, existing=MagicMock(variant_id=uuid4()))
    with patch.object(svc, "get_assignment", return_value={}):
        svc.assign_user_with_targeting(USER, experiment.id, {})
    _assert_clean(logs, routine=True)


def test_targeting_error_logs_the_type_not_the_text(logs, experiment):
    experiment.targeting_rules = NATIVE_US_ONLY
    svc = _service(experiment)
    svc.rules_evaluation_service = MagicMock()
    svc.rules_evaluation_service.evaluate_rules_with_validation.side_effect = (
        ValueError(f"attribute value {USER} is not valid")
    )
    result = svc._evaluate_experiment_targeting(experiment, {"user_id": USER}, True)
    assert result["eligible"] is False
    _assert_clean(logs, routine=False)
    assert [r[0] for r in logs.records] == ["error"], logs.records
    assert "ValueError" in logs.records[0][1]


def test_bulk_assignment_error_logs_the_type_not_the_text(logs, experiment):
    svc = _service(experiment)
    svc.db.add.side_effect = RuntimeError(
        f"(psycopg2) [parameters: {{'user_id': '{USER}'}}]"
    )
    with patch.object(svc, "_hash_user_to_variant", return_value=uuid4()):
        result = svc.bulk_assign_users([USER], experiment.id)
    assert result["errors"] == 1
    _assert_clean(logs, routine=False)
    errors = logs.at("error")
    assert len(errors) == 1 and "RuntimeError" in errors[0][1], logs.records


def test_reassignment(logs, experiment):
    svc = _service(experiment, existing=MagicMock())
    with (
        patch.object(svc, "get_assignment", return_value={}),
        patch.object(svc, "_hash_user_to_variant", return_value=uuid4()),
    ):
        svc.reassign_user(USER, experiment.id, track_exposure=False)
    _assert_clean(logs, routine=False)


def _flag():
    return SimpleNamespace(
        id="00000000-0000-0000-0000-000000000269",
        key="no-user-id",
        status=FeatureFlagStatus.ACTIVE,
        rollout_percentage=100,
        targeting_rules=None,
    )


def test_flag_evaluation_error_logs_the_type_not_the_text(logs, monkeypatch):
    metrics = MagicMock()
    monkeypatch.setattr(ffs, "MetricsService", metrics)
    service = ffs.FeatureFlagService(db=MagicMock())
    with patch.object(
        service,
        "_match_targeting_rule",
        side_effect=ValueError(f"cannot evaluate for {USER}"),
    ):
        result = service.evaluate_flag_detailed(_flag(), USER, {})
    assert result["reason"] == "error"
    _assert_clean(logs, routine=False)
    errors = logs.at("error")
    assert len(errors) == 1 and "ValueError" in errors[0][1], logs.records
    # The operator's record of the failure keeps the full text, in error_logs.
    assert USER in metrics.log_error.call_args.kwargs["data"].message


def test_flag_metrics_failure_logs_the_type_not_the_text(logs, monkeypatch):
    metrics = MagicMock()
    metrics.record_flag_evaluation.side_effect = RuntimeError(
        f"[parameters: {{'user_id': '{USER}'}}]"
    )
    monkeypatch.setattr(ffs, "MetricsService", metrics)
    service = ffs.FeatureFlagService(db=MagicMock())
    service.evaluate_flag_detailed(_flag(), USER, {})
    _assert_clean(logs, routine=False)
    errors = logs.at("error")
    assert len(errors) == 1 and "RuntimeError" in errors[0][1], logs.records
