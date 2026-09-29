"""
The event processor Lambda never logs the user id, at any level (#269).

Every event carries a ``user_id``. Each per-event log line -- the assignment
lookup in enrichment, a validation failure (pydantic's message repeats the
rejected value), an enrichment failure, an aggregation failure (a DynamoDB
error's message can repeat a key) -- is driven with a distinctive user id,
and no record, at any level, may contain it.
"""

import logging
from unittest.mock import patch

import pytest
from botocore.exceptions import ClientError

pytestmark = pytest.mark.regression

USER = "alice.user269@example.com"


class Capture(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append((record.levelname, record.getMessage()))

    def with_user(self):
        return [r for r in self.records if USER in r[1]]


@pytest.fixture
def capture():
    import batch_processor
    import event_aggregator
    import event_enricher
    import event_validator

    cap = Capture()
    loggers = [
        m.logger
        for m in (event_enricher, event_validator, event_aggregator, batch_processor)
    ]
    saved = [(lg, lg.level) for lg in loggers]
    for lg in loggers:
        lg.addHandler(cap)
        lg.setLevel(logging.DEBUG)
    yield cap
    for lg, level in saved:
        lg.removeHandler(cap)
        lg.setLevel(level)


def _event(**overrides):
    event = {
        "event_id": "evt_269",
        "event_type": "purchase",
        "user_id": USER,
        "experiment_id": "exp_269",
        "timestamp": "2026-09-28T10:30:00Z",
    }
    event.update(overrides)
    return event


def test_enrichment_does_not_log_the_user_id(capture):
    from event_enricher import enrich_event, enrich_events_batch
    from event_validator import validate_event

    validated = validate_event(_event())
    enrich_event(validated)
    assert any("exp_269" in r[1] for r in capture.records), capture.records

    with patch(
        "event_enricher.fetch_experiment_metadata",
        side_effect=RuntimeError(f"lookup failed for {USER}"),
    ):
        assert enrich_event(validated)["enrichment_error"] is True
    with patch(
        "event_enricher.enrich_event",
        side_effect=RuntimeError(f"enrichment failed for {USER}"),
    ):
        enrich_events_batch([validated])

    assert capture.with_user() == [], capture.with_user()
    assert sum(r[0] == "ERROR" for r in capture.records) == 2, capture.records


def test_validation_failure_does_not_log_the_rejected_value(capture):
    from event_validator import validate_event, validate_events_batch
    from pydantic import ValidationError

    bad = _event(timestamp=f"not a time {USER}")
    with pytest.raises(ValidationError) as raised:
        validate_event(bad)
    assert USER in str(raised.value)  # the probe: the text does carry it
    validate_events_batch([bad], skip_invalid=True)

    assert capture.records, "nothing was captured"
    assert capture.with_user() == [], capture.with_user()


def test_aggregation_failure_does_not_log_the_error_message(capture):
    from event_aggregator import aggregate_event, aggregate_events_batch

    error = ClientError(
        {
            "Error": {
                "Code": "ValidationException",
                "Message": f"invalid key user_id={USER}",
            }
        },
        "UpdateItem",
    )
    enriched = dict(_event(), variant="control")
    with patch("event_aggregator.dynamodb_table") as table:
        table.update_item.side_effect = error
        with pytest.raises(ClientError):
            aggregate_event(enriched, max_retries=1)
        table.update_item.side_effect = RuntimeError(f"boom {USER}")
        aggregate_events_batch([enriched])

    assert capture.with_user() == [], capture.with_user()
    errors = [r[1] for r in capture.records if r[0] == "ERROR"]
    assert any("ValidationException" in e for e in errors), errors
