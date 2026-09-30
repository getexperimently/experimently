"""DynamoDBCounterService makes only the calls the API task role allows (#392).

The Fargate stack grants the API task ``dynamodb:Query`` and
``dynamodb:UpdateItem`` on the counters table and nothing else
(``infrastructure/cdk/stacks/fargate_service_stack.py``). A service method that
starts making any other call -- ``get_item``, a ``batch_get_item`` on the
resource, a call through ``.meta.client`` or a fresh ``boto3.client`` -- would
pass every moto test and be refused in a deployment. So every public method is
driven here against a fake that records every attribute reached on the
resource, the table and any client, and anything but ``query`` and
``update_item`` on the counters table fails.
"""

from __future__ import annotations

import inspect

import pytest

from modules.backend.app.schemas.realtime_counters import CounterType, IncrementRequest
from modules.backend.app.services import dynamodb_counter_service
from modules.backend.app.services.dynamodb_counter_service import DynamoDBCounterService

pytestmark = pytest.mark.unit

TABLE = "experiment-counters-test"

#: What the task role allows, as ``(object, name, operation)``.
ALLOWED = {
    ("table", TABLE, "query"),
    ("table", TABLE, "update_item"),
}


class _Recorder:
    """Records every attribute reached on it; each one is callable."""

    def __init__(self, calls: list, kind: str, name: str = ""):
        self._calls = calls
        self._kind = kind
        self._name = name

    def __getattr__(self, attribute: str):
        if attribute.startswith("__"):
            raise AttributeError(attribute)
        self._calls.append((self._kind, self._name, attribute))
        return _Recorder(self._calls, f"{self._kind}.{attribute}", self._name)

    def __call__(self, *args, **kwargs):
        return {}


class _Table(_Recorder):
    """A table whose query returns one variant row, so every branch runs."""

    def __getattr__(self, attribute: str):
        if attribute == "query":
            self._calls.append(("table", self._name, "query"))
            return lambda **kwargs: {
                "Items": [
                    {
                        "pk": "EXPERIMENT#exp-1",
                        "sk": "VARIANT#v1",
                        "assignments": 2,
                        "events": 1,
                        "conversions": 1,
                        "last_updated": "2026-09-30T00:00:00+00:00",
                    }
                ]
            }
        if attribute == "update_item":
            self._calls.append(("table", self._name, "update_item"))
            return lambda **kwargs: {"Attributes": {"assignments": 1}}
        return super().__getattr__(attribute)


class _Resource(_Recorder):
    def Table(self, name: str):  # boto3 spells it this way
        self._calls.append(("resource", "", f"Table({name})"))
        return _Table(self._calls, "table", name)


@pytest.fixture
def calls(monkeypatch) -> list:
    """The calls made, with boto3's resource and client both replaced."""
    recorded: list = []

    def resource(service_name, *args, **kwargs):
        recorded.append(("boto3", "", f"resource({service_name})"))
        return _Resource(recorded, "resource")

    def client(service_name, *args, **kwargs):
        recorded.append(("boto3", "", f"client({service_name})"))
        return _Recorder(recorded, "client")

    monkeypatch.setattr(dynamodb_counter_service.boto3, "resource", resource)
    monkeypatch.setattr(dynamodb_counter_service.boto3, "client", client)
    return recorded


def _drive(service: DynamoDBCounterService) -> dict:
    """Call every public method, down every branch that reaches DynamoDB."""
    request = IncrementRequest(
        experiment_id="exp-1", variant_id="v1", counter_type=CounterType.EVENT
    )
    return {
        "increment_counter": lambda: service.increment_counter(
            "exp-1", "v1", CounterType.ASSIGNMENT
        ),
        "get_experiment_counters": lambda: service.get_experiment_counters("exp-1"),
        "bulk_increment": lambda: service.bulk_increment([request, request]),
        "reset_counters": lambda: (
            service.reset_counters("exp-1"),
            service.reset_counters("exp-1", variant_id="v1"),
            service.reset_counters("exp-1", counter_type=CounterType.CONVERSION),
        ),
    }


@pytest.mark.regression
def test_every_public_method_calls_only_query_and_update_item(calls):
    service = DynamoDBCounterService(table_name=TABLE)
    construction = list(calls)
    assert construction == [
        ("boto3", "", "resource(dynamodb)"),
        ("resource", "", f"Table({TABLE})"),
    ], construction

    drivers = _drive(service)
    public = {
        name
        for name, member in inspect.getmembers(DynamoDBCounterService)
        if not name.startswith("_") and callable(member)
    }
    assert public == set(drivers), (
        f"public methods {sorted(public - set(drivers))} are not driven here: "
        "add them, and make sure the task role grants what they call"
    )
    for name, drive in drivers.items():
        before = len(calls)
        drive()
        made = set(calls[before:])
        assert made, f"{name} reached DynamoDB not at all"
        assert made <= ALLOWED, (
            f"{name} made {sorted(made - ALLOWED)}; the API task role allows "
            "only dynamodb:Query and dynamodb:UpdateItem on the counters table "
            "(infrastructure/cdk/stacks/fargate_service_stack.py)"
        )
    assert {operation for _, _, operation in calls[len(construction) :]} == {
        "query",
        "update_item",
    }


def test_the_recorder_sees_a_call_outside_the_grant(calls):
    """Not vacuous: the fake records what the pin forbids."""
    service = DynamoDBCounterService(table_name=TABLE)
    service._table.get_item(Key={})
    service._dynamodb.batch_get_item(RequestItems={})
    service._table.meta.client.scan(TableName=TABLE)
    assert ("table", TABLE, "get_item") in calls
    assert ("resource", "", "batch_get_item") in calls
    assert ("table.meta.client", TABLE, "scan") in calls
