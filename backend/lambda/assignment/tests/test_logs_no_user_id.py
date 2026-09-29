"""
The assignment Lambda never logs the user id, at any level (#269).

Each per-request path -- a new assignment, a sticky one, each exclusion, the
MAB path, storage, a lookup failure, and the handler's own lines -- is driven
with a distinctive user id, and every record is rendered through the real
``JsonFormatter`` (which copies an ``extra`` ``user_id`` into the line). No
rendered line may contain the user id; the routine lines are DEBUG; an error
line carries the exception's type, not its text.
"""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "shared"))

from models import (
    Assignment,
    BanditWeightsConfig,
    ExperimentConfig,
    ExperimentStatus,
    VariantConfig,
)
from utils import JsonFormatter

pytestmark = pytest.mark.regression

USER = "alice.user269@example.com"


class Capture(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.setFormatter(JsonFormatter())
        self.lines = []

    def emit(self, record):
        self.lines.append((record.levelname, self.format(record)))

    def with_user(self):
        return [line for line in self.lines if USER in line[1]]

    def above_debug(self):
        return [line for line in self.lines if line[0] != "DEBUG"]


@pytest.fixture
def capture():
    import assignment_service
    import handler

    cap = Capture()
    loggers = [assignment_service.logger, handler.logger]
    saved = [(lg, lg.level) for lg in loggers]
    for lg in loggers:
        lg.addHandler(cap)
        lg.setLevel(logging.DEBUG)
    yield cap
    for lg, level in saved:
        lg.removeHandler(cap)
        lg.setLevel(level)


def _config(targeting_rules=None):
    return ExperimentConfig(
        experiment_id="exp_269",
        key="exp-269",
        status=ExperimentStatus.ACTIVE,
        variants=[
            VariantConfig(key="control", allocation=0.5),
            VariantConfig(key="treatment", allocation=0.5),
        ],
        targeting_rules=targeting_rules,
    )


def _assignment():
    return Assignment(
        assignment_id="assign_269",
        user_id=USER,
        experiment_id="exp_269",
        experiment_key="exp-269",
        variant="treatment",
        timestamp=datetime.now(timezone.utc),
    )


def _assert_clean(cap, *, routine):
    assert cap.lines, "nothing was captured: the handler is not attached"
    assert cap.with_user() == [], cap.with_user()
    if routine:
        assert cap.above_debug() == [], cap.lines


def test_service_assignment_paths(capture):
    from assignment_service import AssignmentService

    service = AssignmentService()
    service.assign_variant(USER, _config())
    with patch.object(service, "check_global_holdout", return_value=True):
        assert service.assign_variant(USER, _config()) is None
    with patch.object(service, "check_mutual_exclusion", return_value=True):
        assert service.assign_variant(USER, _config()) is None
    with patch.object(service, "evaluate_targeting_rules", return_value=False):
        assert service.assign_variant(USER, _config([{"x": 1}])) is None
    service.get_weighted_variant(
        USER,
        _config(),
        BanditWeightsConfig(
            experiment_id="exp_269",
            algorithm="thompson_sampling",
            weights={"control": 0.5, "treatment": 0.5},
        ),
    )
    _assert_clean(capture, routine=True)


@patch("utils.put_dynamodb_item", return_value=True)
@patch("assignment_service.get_env_variable", return_value="table")
def test_service_storage(_env, _put, capture):
    from assignment_service import AssignmentService

    service = AssignmentService()
    service.store_assignment(_assignment())
    item = {
        "assignment_id": "assign_269",
        "user_id": USER,
        "experiment_id": "exp_269",
        "experiment_key": "exp-269",
        "variant": "treatment",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    with patch("utils.get_dynamodb_item", return_value=item):
        assert service.get_assignment(USER, "exp_269") is not None
    _assert_clean(capture, routine=True)


@patch("assignment_service.get_env_variable", return_value="table")
def test_service_lookup_error_logs_the_type_not_the_text(_env, capture):
    from assignment_service import AssignmentService

    with patch(
        "utils.get_dynamodb_item",
        side_effect=RuntimeError(f"key {{'user_id': '{USER}'}} rejected"),
    ):
        assert AssignmentService().get_assignment(USER, "exp_269") is None
    _assert_clean(capture, routine=False)
    errors = [line for line in capture.lines if line[0] == "ERROR"]
    assert len(errors) == 1 and "RuntimeError" in errors[0][1], capture.lines


def _event():
    return {
        "queryStringParameters": {"user_id": USER, "experiment_key": "exp-269"},
        "requestContext": {"requestId": "req-269"},
    }


@patch("handler.AssignmentService")
def test_handler_paths(service_class, capture):
    from handler import lambda_handler

    service = Mock()
    service_class.return_value = service
    service.get_experiment_config_cached.return_value = _config()

    service.get_or_create_assignment.return_value = _assignment()
    assert lambda_handler(_event(), {})["statusCode"] == 200
    service.get_or_create_assignment.return_value = None
    assert lambda_handler(_event(), {})["statusCode"] == 200
    service.get_experiment_config_cached.return_value = None
    assert lambda_handler(_event(), {})["statusCode"] == 404

    assert capture.with_user() == [], capture.with_user()
    info = [line for line in capture.lines if line[0] == "INFO"]
    # Only "Assignment request received", once per request, carries no user id.
    assert all("Assignment request received" in line[1] for line in info), info


@patch("handler.AssignmentService")
def test_handler_error_logs_the_type_not_the_text(service_class, capture):
    from handler import lambda_handler

    service_class.return_value.get_experiment_config_cached.side_effect = RuntimeError(
        f"lookup failed for {USER}"
    )
    response = lambda_handler(_event(), {})
    assert response["statusCode"] == 500
    assert capture.with_user() == [], capture.with_user()
    errors = [json.loads(line[1]) for line in capture.lines if line[0] == "ERROR"]
    assert len(errors) == 1 and "RuntimeError" in errors[0]["message"], capture.lines
