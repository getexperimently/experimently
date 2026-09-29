"""
The shared AWS helpers log an error's type and AWS code, never its message (#269).

Assignments are keyed on ``user_id`` and Kinesis records are partitioned on it,
so a DynamoDB or Kinesis error message can repeat a user id.
"""

import logging
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from botocore.exceptions import ClientError

sys.path.insert(0, str(Path(__file__).parent.parent))

import utils

pytestmark = pytest.mark.regression

USER = "alice.user269@example.com"


def _client_error():
    return ClientError(
        {"Error": {"Code": "ValidationException", "Message": f"bad key {USER}"}},
        "PutItem",
    )


class Capture(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.lines = []

    def emit(self, record):
        self.lines.append(self.format(record))


@pytest.fixture
def capture():
    logger = utils.get_logger(utils.__name__)
    cap = Capture()
    cap.setFormatter(utils.JsonFormatter())
    level = logger.level
    logger.addHandler(cap)
    logger.setLevel(logging.DEBUG)
    yield cap
    logger.removeHandler(cap)
    logger.setLevel(level)


def test_error_name():
    assert utils.error_name(_client_error()) == "ClientError(ValidationException)"
    assert utils.error_name(ValueError(USER)) == "ValueError"


def test_the_helpers_do_not_log_the_error_message(capture):
    with patch.object(utils, "get_dynamodb_resource") as resource:
        table = resource.return_value.Table.return_value
        table.put_item.side_effect = _client_error()
        table.get_item.side_effect = _client_error()
        assert utils.put_dynamodb_item("t", {"user_id": USER}) is False
        assert utils.get_dynamodb_item("t", {"user_id": USER}) is None
    with patch.object(utils, "get_kinesis_client") as client:
        client.return_value.put_record.side_effect = _client_error()
        client.return_value.put_records.side_effect = _client_error()
        utils.put_kinesis_record("s", {"user_id": USER}, USER)
        utils.batch_put_kinesis_records("s", [{"user_id": USER}])

    assert len(capture.lines) >= 4, capture.lines
    assert [line for line in capture.lines if USER in line] == []
    assert all("ValidationException" in line for line in capture.lines[:4])
