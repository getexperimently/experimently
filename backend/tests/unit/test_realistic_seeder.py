"""The realistic-data seeder fails loudly and reports what the platform stored.

``PlatformSeeder`` (``backend/tests/realistic/data_generator.py``) used to
print a warning on a 401/422/5xx from the tracking API and carry on, counting
every attempt as seeded; it never created assignments, so the results engine
saw zero users. These tests run it against an in-process fake platform
(``httpx.MockTransport``) that records what it stored, and compare.

Refs #234.

The generator also used to convert each user by the variant it had picked
itself, while the server's hash put about half of them in the other variant,
so the lift it generated was diluted on the platform (a scenario its dry run
called significant came out at p = 0.44); its ``--seed`` was parsed and never
used, and its dates counted back from the moment of the run. The tests below
the line run it against a fake that assigns by the documented hash.
"""

from __future__ import annotations

import hashlib
import json
import struct
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

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


def _by_character_sum(user_id: str, experiment_key: str) -> str:
    # Deterministic, and independent of the generator's own split.
    return "control" if sum(map(ord, user_id)) % 2 == 0 else "treatment"


def documented_hash(user_id: str, experiment_key: str) -> str:
    """The API's assignment in a 50/50 control/treatment experiment.

    Written here from the algorithm tests/sdk-contract/golden-vectors.json
    states, not imported from the server: MD5 of "{user_id}:{key}", the first
    four bytes as a little-endian unsigned integer, divided by 2^32, times 100;
    buckets 0-49 are the first variant, control.
    """
    digest = hashlib.md5(
        f"{user_id}:{experiment_key}".encode(), usedforsecurity=False
    ).digest()
    bucket = int(struct.unpack("<I", digest[:4])[0] / 4294967296 * 100)
    return "control" if bucket < 50 else "treatment"


def opposite_of_documented_hash(user_id: str, experiment_key: str) -> str:
    """A platform that disagrees with the generator's plan for every user."""
    return (
        "treatment"
        if documented_hash(user_id, experiment_key) == "control"
        else "control"
    )


class FakePlatform:
    """Just enough of the API for the seeder, recording every stored row."""

    def __init__(
        self,
        fail_event_at: Optional[int] = None,
        fail_status: int = 500,
        assigner: Callable[[str, str], str] = _by_character_sum,
    ):
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.assignments: dict[str, dict[str, str]] = {}
        self.events: list[dict[str, Any]] = []
        self.keys: list[str] = []
        self.started = False
        self._fail_event_at = fail_event_at
        self._fail_status = fail_status
        self._event_attempts = 0
        self._assigner = assigner

    def _variant_for(self, user_id: str, experiment_key: str) -> dict[str, str]:
        name = self._assigner(user_id, experiment_key)
        return {"variant_id": f"v-{name}", "variant_name": name}

    def split(self) -> dict[str, dict[str, int]]:
        """Users and converting users per variant, as the results engine counts."""
        converting = {
            e["user_id"] for e in self.events if e["event_name"] == "purchase"
        }
        counts: dict[str, dict[str, int]] = {}
        for user_id, assignment in self.assignments.items():
            arm = counts.setdefault(
                assignment["variant_name"], {"users": 0, "converting_users": 0}
            )
            arm["users"] += 1
            arm["converting_users"] += user_id in converting
        return counts

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body = json.loads(request.content) if request.content else {}
        self.calls.append((path, body))

        if path == "/api/v1/experiments":
            if body["key"] in self.keys:
                return httpx.Response(
                    409,
                    json={
                        "detail": f"An experiment with the key '{body['key']}' already exists."
                    },
                )
            self.keys.append(body["key"])
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
                user_id, self._variant_for(user_id, body["experiment_key"])
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
    fake = platform(assigner=documented_hash)
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
    assert result["variant_mismatches"] == 0
    assert result["events_seeded"] == len(fake.events) == len(scenario.events)


# ---------------------------------------------------------------------------
# Each user converts in the platform's variant; seed and dates reproduce.
# ---------------------------------------------------------------------------


def _seed(result: ScenarioResult, **kwargs: Any) -> dict[str, Any]:
    return PlatformSeeder("http://platform.test", "jwt", api_key=API_KEY).seed_scenario(
        result, **kwargs
    )


@pytest.mark.unit
@pytest.mark.regression
def test_each_user_converts_in_the_variant_the_platform_assigned(platform):
    """Control never converts and treatment always does: the platform's
    treatment users are exactly its converters.

    On the old generator each user converted in the variant it had picked
    itself (the first half control), so about half of the platform's control
    users converted and half of its treatment users did not.
    """
    fake = platform(assigner=documented_hash)
    _seed(
        DataScenario(
            name="all-or-nothing",
            users=400,
            control_cvr=0.0,
            treatment_cvr=1.0,
            outlier_rate=0.0,
            seed=3,
        ).generate()
    )

    in_treatment = {
        user_id
        for user_id, a in fake.assignments.items()
        if a["variant_name"] == "treatment"
    }
    assert 150 < len(in_treatment) < 250
    assert {e["user_id"] for e in fake.events} == in_treatment


@pytest.mark.unit
@pytest.mark.regression
def test_conversions_follow_the_servers_answer_not_the_plan(platform):
    """A platform that puts every user in the other variant from the plan.

    The seeder converts by the answer, not by the dry run's plan, so the
    configured rates still hold and every user is a reported mismatch.
    """
    fake = platform(assigner=opposite_of_documented_hash)
    report = _seed(
        DataScenario(
            name="against-the-plan",
            users=400,
            control_cvr=0.0,
            treatment_cvr=1.0,
            outlier_rate=0.0,
            seed=3,
        ).generate()
    )

    split = fake.split()
    assert split["control"]["converting_users"] == 0
    assert split["treatment"]["converting_users"] == split["treatment"]["users"]
    assert report["variant_mismatches"] == 400
    assert report["by_variant"] == split


@pytest.mark.unit
@pytest.mark.regression
def test_the_configured_rates_hold_on_the_platform(platform):
    """10% against 30%: the platform's rates are those, not a blend of them.

    The old generator's rates on a hash-assigning platform came out near 20%
    in both variants (A1 measured 0.101 against 0.102 for targets of 0.080 and
    0.095).
    """
    fake = platform(assigner=documented_hash)
    _seed(
        DataScenario(
            name="rates",
            users=2_000,
            control_cvr=0.10,
            treatment_cvr=0.30,
            outlier_rate=0.0,
            seed=11,
        ).generate()
    )

    split = fake.split()
    control = split["control"]["converting_users"] / split["control"]["users"]
    treatment = split["treatment"]["converting_users"] / split["treatment"]["users"]
    assert 0.07 < control < 0.13, control
    assert 0.26 < treatment < 0.34, treatment


@pytest.mark.unit
@pytest.mark.regression
def test_the_dry_run_predicts_the_platforms_counts_and_p_value(platform):
    """What the dry run prints is what the platform counts.

    The old dry run printed "Expected significant: True" from the target rates
    for a split the platform never made.
    """
    fake = platform(assigner=documented_hash)
    result = DataScenario(
        name="prediction",
        users=3_000,
        control_cvr=0.08,
        treatment_cvr=0.12,
        day_of_week_effect=True,
        seed=21,
    ).generate()

    report = _seed(result)

    assert result.split() == fake.split() == report["by_variant"]
    assert report["variant_mismatches"] == 0
    assert report["events_seeded"] == report["events_generated"]
    predicted = result.metadata["predicted_p_value"]
    assert report["expected_p_value"] == pytest.approx(predicted, rel=1e-12)
    assert result.expected_significant == (predicted < 0.05)
    assert result.expected_significant  # 8% against 12% on 3,000 users


def _stored(fake: FakePlatform) -> tuple[Any, ...]:
    return (
        fake.keys,
        sorted(fake.assignments.items()),
        sorted(
            (e["user_id"], e["timestamp"], e["value"], e["variant_id"])
            for e in fake.events
        ),
    )


@pytest.mark.unit
@pytest.mark.regression
def test_the_same_seed_gives_the_same_data_and_counts(platform):
    """Two runs with one seed store the same rows; another seed does not.

    The old generator drew user ids and the experiment key from uuid4, so no
    two runs had a user in common.
    """

    def run(seed: int) -> tuple[tuple[Any, ...], dict[str, Any]]:
        fake = platform(assigner=documented_hash)
        report = _seed(
            DataScenario(
                name="repro",
                users=600,
                control_cvr=0.1,
                treatment_cvr=0.2,
                day_of_week_effect=True,
                session_decay=True,
                seed=seed,
            ).generate()
        )
        return _stored(fake), report

    first, first_report = run(7)
    again, again_report = run(7)
    other, other_report = run(8)

    assert first == again
    assert first_report == again_report
    assert first_report["experiment_key"] == "realistic-repro-seed7"
    assert set(dict(first[1])).isdisjoint(dict(other[1]))
    assert first_report["by_variant"] != other_report["by_variant"]


@pytest.mark.unit
@pytest.mark.regression
def test_one_scenario_generates_the_same_result_each_time():
    """The old generator kept one random stream per scenario object, so a
    second ``generate()`` (``--scenario all`` reuses the objects) drew new data.
    """
    scenario = DataScenario(name="twice", users=300, seed=4)
    first, second = scenario.generate(), scenario.generate()

    assert [u.user_id for u in first.users] == [u.user_id for u in second.users]
    assert [(e.user_id, e.timestamp) for e in first.events] == [
        (e.user_id, e.timestamp) for e in second.events
    ]


def _dry_run(monkeypatch: pytest.MonkeyPatch, capsys, *args: str) -> str:
    monkeypatch.setattr(
        sys,
        "argv",
        ["data_generator", "--scenario", "feature_flag_rollout", "--dry-run", *args],
    )
    data_generator.main()
    return capsys.readouterr().out


@pytest.mark.unit
@pytest.mark.regression
def test_the_seed_option_decides_the_data(monkeypatch, capsys):
    """``--seed`` was parsed and never used."""
    first = _dry_run(monkeypatch, capsys, "--seed", "5")
    again = _dry_run(monkeypatch, capsys, "--seed", "5")
    other = _dry_run(monkeypatch, capsys, "--seed", "6")

    assert "Users: 4000 total" in first
    assert first == again
    assert other != first


@pytest.mark.unit
@pytest.mark.regression
def test_dates_do_not_depend_on_the_day_of_the_run(monkeypatch):
    """The same seed on two different days gives the same dates and events.

    The old start was now() minus the duration, so the day-of-week effect saw
    a different weekday mix, and generated different rates, on each day.
    """

    def generate() -> ScenarioResult:
        return DataScenario(
            name="dates",
            users=500,
            control_cvr=0.2,
            treatment_cvr=0.3,
            day_of_week_effect=True,
            session_decay=True,
            seed=9,
        ).generate()

    today = generate()

    class Later(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:
            return datetime(2031, 3, 15, 9, 30, tzinfo=tz or timezone.utc)

    monkeypatch.setattr(data_generator, "datetime", Later)
    later = generate()

    assert [u.assigned_at for u in today.users] == [u.assigned_at for u in later.users]
    assert [(e.timestamp, e.value) for e in today.events] == [
        (e.timestamp, e.value) for e in later.events
    ]
    assert today.split() == later.split()
    start = data_generator.DEFAULT_START_DATE
    # A Monday, so a 14- or 21-day scenario is whole weeks.
    assert start.weekday() == 0
    assert min(u.assigned_at for u in today.users) >= start


@pytest.mark.unit
def test_a_key_already_on_the_platform_is_refused_with_the_way_out(platform):
    """The default key comes from the seed, so a second run of one scenario
    and seed on one platform is a 409: the error says what to pass."""
    fake = platform(assigner=documented_hash)
    result = DataScenario(name="again", users=50, seed=1).generate()
    _seed(result)

    with pytest.raises(data_generator.SeedingError, match="409") as excinfo:
        _seed(result)
    assert "--experiment-key" in str(excinfo.value)

    report = _seed(result, experiment_key="again-second-run")
    assert report["experiment_key"] == "again-second-run"
    assert fake.keys == ["realistic-again-seed1", "again-second-run"]


@pytest.mark.unit
@pytest.mark.parametrize(
    "name, users, significant",
    [
        ("ab_test_lifecycle", 12_000, True),
        ("feature_flag_rollout", 4_000, False),
        ("novelty_effect", 6_000, True),
        ("statistical_edge_cases", 8_001, True),
        ("concurrent_experiments", 8_000, False),
    ],
)
def test_each_scenario_at_its_default_seed_is_what_the_agent_says(
    name: str, users: int, significant: bool
):
    """.claude/agents/data-generator.md lists each scenario's users and whether
    it is significant at its default seed; the QA agents rely on that table."""
    factory = data_generator.SCENARIOS[name]
    assert factory is not None
    result = factory().generate()

    assert len({u.user_id for u in result.users}) == users
    assert result.expected_significant is significant
