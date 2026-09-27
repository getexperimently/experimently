"""The realistic-data seeder fails loudly and reports what the platform stored.

``PlatformSeeder`` (``backend/tests/realistic/data_generator.py``) used to
print a warning on a 401/422/5xx from the tracking API and carry on, counting
every attempt as seeded; it never created assignments, so the results engine
saw zero users. These tests run it against an in-process fake platform
(``httpx.MockTransport``) that records what it stored, and compare.

Refs #234.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
import pytest

from backend.tests.realistic import data_generator
from backend.tests.realistic.data_generator import (
    DataScenario,
    PlatformSeeder,
    ScenarioResult,
    SimulatedUser,
    UserEvent,
)

API_KEY = "test-api-key"
T0 = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)


class FakePlatform:
    """Just enough of the API for the seeder, recording every stored row."""

    def __init__(self, fail_event_at: Optional[int] = None, fail_status: int = 500):
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.assignments: dict[str, dict[str, str]] = {}
        self.events: list[dict[str, Any]] = []
        self.started = False
        self._fail_event_at = fail_event_at
        self._fail_status = fail_status
        self._event_attempts = 0

    def _variant_for(self, user_id: str) -> dict[str, str]:
        # Deterministic, and independent of the generator's own split.
        name = "control" if sum(map(ord, user_id)) % 2 == 0 else "treatment"
        return {"variant_id": f"v-{name}", "variant_name": name}

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body = json.loads(request.content) if request.content else {}
        self.calls.append((path, body))

        if path == "/api/v1/experiments":
            return httpx.Response(
                201,
                json={
                    "id": "exp-1",
                    "key": body["key"],
                    "status": "draft",
                    "variants": [
                        {"id": "v-control", "name": "control"},
                        {"id": "v-treatment", "name": "treatment"},
                    ],
                },
            )
        if path == "/api/v1/experiments/exp-1/start":
            self.started = True
            return httpx.Response(200, json={"id": "exp-1", "status": "active"})

        if path.startswith("/api/v1/tracking/"):
            if request.headers.get("X-API-Key") != API_KEY:
                return httpx.Response(401, json={"detail": "Invalid API Key"})

        if path == "/api/v1/tracking/assign":
            if not self.started:
                return httpx.Response(404, json={"detail": "not active"})
            user_id = body["user_id"]
            assignment = self.assignments.setdefault(
                user_id, self._variant_for(user_id)
            )
            return httpx.Response(
                200,
                json={
                    "experiment_key": body["experiment_key"],
                    "user_id": user_id,
                    **assignment,
                    "is_control": assignment["variant_name"] == "control",
                    "assigned": True,
                    "reason": "assigned",
                },
            )

        if path == "/api/v1/tracking/events":
            self._event_attempts += 1
            if self._event_attempts == self._fail_event_at:
                return httpx.Response(self._fail_status, text="boom")
            if not isinstance(body.get("properties"), (dict, type(None))):
                return httpx.Response(422, json={"detail": "properties"})
            user_id = body["user_id"]
            # The results engine counts a conversion only for an assigned
            # user, in the variant they were assigned; the fake refuses the rest.
            assigned = self.assignments.get(user_id)
            if assigned is None or assigned["variant_id"] != body["variant_id"]:
                return httpx.Response(422, json={"detail": "no matching assignment"})
            stored = {**body, "id": f"evt-{len(self.events) + 1}"}
            self.events.append(stored)
            return httpx.Response(200, json=stored)

        return httpx.Response(404, json={"detail": f"unexpected {path}"})


@pytest.fixture
def platform(monkeypatch: pytest.MonkeyPatch):
    """Route the seeder's HTTP session to a fresh ``FakePlatform``."""

    def install(**kwargs: Any) -> FakePlatform:
        fake = FakePlatform(**kwargs)
        transport = httpx.MockTransport(fake.handler)
        monkeypatch.setattr(
            data_generator.requests,
            "Session",
            lambda: httpx.Client(transport=transport),
        )
        return fake

    return install


def _scenario() -> ScenarioResult:
    users = [
        SimulatedUser(f"user-{i}", "control" if i % 2 else "treatment", T0)
        for i in range(6)
    ]
    events = [
        UserEvent("user-0", "treatment", "purchase", 1.0, T0 + timedelta(hours=1)),
        UserEvent("user-1", "control", "purchase", 2.0, T0 + timedelta(hours=2)),
        # A pre-period event: before the user's assignment.
        UserEvent("user-2", "treatment", "page_view", 0.0, T0 - timedelta(days=3)),
        UserEvent("user-2", "treatment", "purchase", 5.0, T0 + timedelta(hours=3)),
        # No timestamp: the server stamps it.
        UserEvent("user-3", "control", "purchase", 1.0, None),
    ]
    return ScenarioResult(
        scenario_name="unit",
        users=users,
        events=events,
        control_cvr=0.5,
        treatment_cvr=0.5,
        expected_significant=False,
        edge_cases_injected=[],
    )


@pytest.mark.unit
@pytest.mark.regression
def test_a_401_from_the_tracking_api_stops_the_seeder(platform):
    """Without --api-key every tracking call is 401: raise, naming the status.

    On the old seeder this printed a warning per event and returned
    ``events_seeded`` equal to the number generated, with nothing stored.
    """
    fake = platform()
    seeder = PlatformSeeder("http://platform.test", "jwt")  # no api_key

    with pytest.raises(Exception, match="401") as excinfo:
        seeder.seed_scenario(_scenario())

    assert "--api-key" in str(excinfo.value)
    assert fake.events == []


@pytest.mark.unit
@pytest.mark.regression
def test_reported_counts_are_what_the_platform_stored(platform):
    """With a key, users are assigned before their events and counts match storage.

    On the old seeder no assignment was ever created, so every event was
    refused and the report still claimed all of them.
    """
    fake = platform()
    result = PlatformSeeder(
        "http://platform.test", "jwt", api_key=API_KEY
    ).seed_scenario(_scenario())

    assert len(fake.assignments) == 6
    assert len(fake.events) == 5
    assert result["users_seeded"] == len(fake.assignments)
    assert result["events_seeded"] == len(fake.events)
    assert result["events_generated"] == 5
    assert result["events_skipped_unassigned"] == 0


@pytest.mark.unit
def test_each_users_assignment_precedes_their_events(platform):
    fake = platform()
    PlatformSeeder("http://platform.test", "jwt", api_key=API_KEY).seed_scenario(
        _scenario()
    )

    assigned_so_far: set[str] = set()
    for path, body in fake.calls:
        if path == "/api/v1/tracking/assign":
            assigned_so_far.add(body["user_id"])
        elif path == "/api/v1/tracking/events":
            assert body["user_id"] in assigned_so_far, body


@pytest.mark.unit
def test_events_use_the_server_assigned_variant_and_report_mismatches(platform):
    fake = platform()
    scenario = _scenario()
    result = PlatformSeeder(
        "http://platform.test", "jwt", api_key=API_KEY
    ).seed_scenario(scenario)

    for event in fake.events:
        assert event["variant_id"] == fake.assignments[event["user_id"]]["variant_id"]
    expected_mismatches = sum(
        1
        for u in scenario.users
        if fake.assignments[u.user_id]["variant_name"] != u.variant_name
    )
    assert result["variant_mismatches"] == expected_mismatches


@pytest.mark.unit
def test_timestamps_are_sent_so_pre_period_events_can_be_seeded(platform):
    fake = platform()
    PlatformSeeder("http://platform.test", "jwt", api_key=API_KEY).seed_scenario(
        _scenario()
    )

    by_name = {(e["user_id"], e["event_name"]): e for e in fake.events}
    pre = by_name[("user-2", "page_view")]
    assert datetime.fromisoformat(pre["timestamp"]) == T0 - timedelta(days=3)
    assert "timestamp" not in by_name[("user-3", "purchase")]
    # Properties go as an object, which is what EventCreate accepts.
    assert all(isinstance(e["properties"], dict) for e in fake.events)


@pytest.mark.unit
@pytest.mark.parametrize("status", [422, 500, 503])
def test_a_failed_event_mid_run_raises_rather_than_counting_it(platform, status):
    fake = platform(fail_event_at=3, fail_status=status)
    seeder = PlatformSeeder("http://platform.test", "jwt", api_key=API_KEY)

    with pytest.raises(Exception, match=f"HTTP {status}"):
        seeder.seed_scenario(_scenario())

    assert len(fake.events) == 2


@pytest.mark.unit
def test_a_generated_scenario_seeds_every_user_and_event(platform):
    """A real generated scenario, end to end against the fake platform."""
    fake = platform()
    scenario = DataScenario(
        name="small", users=200, control_cvr=0.2, treatment_cvr=0.3, seed=5
    ).generate()

    result = PlatformSeeder(
        "http://platform.test", "jwt", api_key=API_KEY
    ).seed_scenario(scenario)

    assert (
        result["users_seeded"]
        == len(fake.assignments)
        == len({u.user_id for u in scenario.users})
    )
    assert result["events_seeded"] == len(fake.events) == len(scenario.events)
