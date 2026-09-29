"""
The flag evaluation Lambda never logs the user id, at any level (#269).

Every record is rendered through the real ``JsonFormatter`` (which copies an
``extra`` ``user_id`` into the line). No rendered line may contain the user id;
the per-request result line is DEBUG; error lines carry the exception's type,
not its text.
"""

import json
import logging
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "shared"))

from models import FeatureFlagConfig
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


@pytest.fixture
def capture():
    import handler

    handler.reset_evaluator()
    cap = Capture()
    level = handler.logger.level
    handler.logger.addHandler(cap)
    handler.logger.setLevel(logging.DEBUG)
    yield cap
    handler.logger.removeHandler(cap)
    handler.logger.setLevel(level)
    handler.reset_evaluator()


FLAG = FeatureFlagConfig(
    flag_id="flag_269", key="flag-269", enabled=True, rollout_percentage=100.0
)


def _event():
    return {
        "queryStringParameters": {"user_id": USER, "flag_key": "flag-269"},
        "requestContext": {"requestId": "req-269"},
    }


@patch("handler.FeatureFlagEvaluator")
def test_evaluation_paths(evaluator_class, capture, monkeypatch):
    from handler import lambda_handler

    evaluator = Mock()
    evaluator_class.return_value = evaluator
    evaluator.get_flag_config_cached.return_value = FLAG
    evaluator.evaluate.return_value = {"enabled": True, "reason": "rollout"}

    # Kinesis succeeds, then fails with the user id in the error's text.
    monkeypatch.setenv("KINESIS_STREAM_NAME", "stream")
    with patch("handler.boto3") as boto:
        assert lambda_handler(_event(), {})["statusCode"] == 200
        boto.client.return_value.put_record.side_effect = RuntimeError(
            f"PartitionKey {USER} rejected"
        )
        assert lambda_handler(_event(), {})["statusCode"] == 200
    with patch(
        "handler.record_evaluation_event_async",
        side_effect=RuntimeError(f"tracking failed for {USER}"),
    ):
        assert lambda_handler(_event(), {})["statusCode"] == 200
    evaluator.get_flag_config_cached.return_value = None
    assert lambda_handler(_event(), {})["statusCode"] == 404

    assert capture.lines, "nothing was captured"
    assert capture.with_user() == [], capture.with_user()
    info = [line for line in capture.lines if line[0] == "INFO"]
    assert not any("Feature flag evaluated" in line[1] for line in info), info
    warnings = [json.loads(line[1]) for line in capture.lines if line[0] == "WARNING"]
    assert sum("RuntimeError" in w["message"] for w in warnings) == 2, warnings


@patch("handler.FeatureFlagEvaluator")
def test_handler_error_logs_the_type_not_the_text(evaluator_class, capture):
    from handler import lambda_handler

    evaluator_class.return_value.get_flag_config_cached.side_effect = RuntimeError(
        f"lookup failed for {USER}"
    )
    assert lambda_handler(_event(), {})["statusCode"] == 500
    assert capture.with_user() == [], capture.with_user()
    errors = [json.loads(line[1]) for line in capture.lines if line[0] == "ERROR"]
    assert len(errors) == 1 and "RuntimeError" in errors[0]["message"], capture.lines
