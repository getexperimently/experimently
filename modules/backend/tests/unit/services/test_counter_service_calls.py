"""DynamoDBCounterService makes only the calls the API task role allows (#392).

The Fargate stack grants the API task ``dynamodb:Query`` and
``dynamodb:UpdateItem`` on the counters table and nothing else
(``infrastructure/cdk/stacks/fargate_service_stack.py``). A service method that
starts making any other call -- ``get_item``, a ``batch_get_item`` on the
resource, a call through ``.meta.client`` or a fresh ``boto3.client`` -- would
pass every moto test and be refused in a deployment. So every public method is
driven here against a fake that records every attribute reached on the
resource, the table and any client, and anything but ``query`` and
``update_item`` on the counters table fails. Every method that handles an
error is driven again with ``update_item`` failing, so its ``except`` branch
runs under the recorder as well.
"""

from __future__ import annotations

import ast
import inspect
import textwrap

import pytest
from botocore.exceptions import ClientError

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
    """A table whose query returns one variant row, so every branch runs.

    ``failures`` is how many of the next ``update_item`` calls raise a
    ``ClientError`` instead of succeeding, so the callers' error branches run
    under the recorder too. A failed call is still recorded: it is a call the
    task role has to allow.
    """

    def __init__(self, calls: list, kind: str, name: str = ""):
        super().__init__(calls, kind, name)
        self.failures = 0

    def _update_item(self, **kwargs):
        if self.failures:
            self.failures -= 1
            raise ClientError(
                {"Error": {"Code": "ProvisionedThroughputExceededException"}},
                "UpdateItem",
            )
        return {"Attributes": {"assignments": 1}}

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
            return self._update_item
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


def _drive_failures(service: DynamoDBCounterService) -> dict:
    """Call every public method that handles an error, with ``update_item`` failing.

    Each driver makes the first ``update_item`` raise, runs the method, and
    checks the error branch really ran -- so a call planted in an ``except``
    block is reached and recorded, not skipped.
    """
    request = IncrementRequest(
        experiment_id="exp-1", variant_id="v1", counter_type=CounterType.EVENT
    )

    def bulk_increment():
        service._table.failures = 1
        result = service.bulk_increment([request, request])
        assert (result.processed, result.failed) == (1, 1), result

    def reset_counters():
        for kwargs in ({}, {"variant_id": "v1"}):
            service._table.failures = 1
            with pytest.raises(ClientError):
                service.reset_counters("exp-1", **kwargs)

    return {"bulk_increment": bulk_increment, "reset_counters": reset_counters}


def _methods_with_error_handling() -> set[str]:
    """The public methods whose source has a ``try`` statement."""
    found = set()
    for name, member in inspect.getmembers(DynamoDBCounterService, inspect.isfunction):
        if name.startswith("_"):
            continue
        tree = ast.parse(textwrap.dedent(inspect.getsource(member)))
        if any(isinstance(node, ast.Try) for node in ast.walk(tree)):
            found.add(name)
    return found


def _assert_allowed(calls: list, name: str, drive) -> set:
    before = len(calls)
    drive()
    made = set(calls[before:])
    assert made, f"{name} reached DynamoDB not at all"
    assert made <= ALLOWED, (
        f"{name} made {sorted(made - ALLOWED)}; the API task role allows "
        "only dynamodb:Query and dynamodb:UpdateItem on the counters table "
        "(infrastructure/cdk/stacks/fargate_service_stack.py)"
    )
    return made


@pytest.mark.regression
def test_every_error_branch_calls_only_query_and_update_item(calls):
    """The except branches too: a happy-path drive never reaches them."""
    service = DynamoDBCounterService(table_name=TABLE)
    drivers = _drive_failures(service)
    handling = _methods_with_error_handling()
    assert handling == set(drivers), (
        f"methods with error handling {sorted(handling - set(drivers))} are "
        "not driven down their error branch here"
    )
    for name, drive in drivers.items():
        _assert_allowed(calls, name, drive)
        assert service._table.failures == 0, f"{name} never reached update_item"


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
        _assert_allowed(calls, name, drive)
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
