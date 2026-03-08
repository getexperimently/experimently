"""
Domain-specific synthetic data engine for the Experimently platform.

Generates statistically realistic experimentation scenarios — not just valid
shapes but data that behaves like the real world: baseline conversion rates,
novelty effects, outliers, day-of-week patterns, and intentional edge cases.

Usage (standalone dry-run):
    python backend/tests/realistic/data_generator.py --scenario ab_test_lifecycle --dry-run

Usage (seed into running API):
    python backend/tests/realistic/data_generator.py --scenario ab_test_lifecycle --api-url http://localhost:8000 --token <JWT>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import requests


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class UserEvent:
    user_id: str
    variant_name: str
    event_name: str
    value: float
    timestamp: datetime
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class SimulatedUser:
    user_id: str
    variant_name: str
    assigned_at: datetime
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class ScenarioResult:
    scenario_name: str
    users: list[SimulatedUser]
    events: list[UserEvent]
    control_cvr: float
    treatment_cvr: float
    expected_significant: bool
    edge_cases_injected: list[str]
    metadata: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> str:
        control_events = [e for e in self.events if e.variant_name == "control"]
        treatment_events = [e for e in self.events if e.variant_name == "treatment"]
        control_users = [u for u in self.users if u.variant_name == "control"]
        treatment_users = [u for u in self.users if u.variant_name == "treatment"]

        actual_control_cvr = (
            len(control_events) / len(control_users) if control_users else 0
        )
        actual_treatment_cvr = (
            len(treatment_events) / len(treatment_users) if treatment_users else 0
        )

        return (
            f"Scenario: {self.scenario_name}\n"
            f"  Users: {len(self.users)} total "
            f"({len(control_users)} control, {len(treatment_users)} treatment)\n"
            f"  Events: {len(self.events)} total\n"
            f"  Control CVR: {actual_control_cvr:.3f} (target: {self.control_cvr:.3f})\n"
            f"  Treatment CVR: {actual_treatment_cvr:.3f} (target: {self.treatment_cvr:.3f})\n"
            f"  Expected significant: {self.expected_significant}\n"
            f"  Edge cases: {self.edge_cases_injected or 'none'}\n"
        )


# ---------------------------------------------------------------------------
# Core data generator
# ---------------------------------------------------------------------------

class DataScenario:
    """
    Generates statistically realistic experiment data.

    Parameters
    ----------
    name : str
        Scenario identifier used for seeding and reporting.
    users : int
        Total simulated user population (split 50/50 control/treatment).
    control_cvr : float
        Baseline conversion rate for the control group (0.0–1.0).
    treatment_cvr : float
        Conversion rate for the treatment group.  If > control_cvr, the
        experiment should show a positive lift.
    novelty_decay_days : int
        Number of days over which the treatment CVR exhibits a novelty spike
        (day-1 boost that decays to steady-state).  0 = no novelty effect.
    outlier_rate : float
        Fraction of users who produce extreme values (bots, whales).
    inject_edge_cases : list[str]
        Named edge cases to inject into the dataset.  Supported:
          - "zero_events_user": a user who never fires any event
          - "multi_assignment": same user assigned to both variants
          - "metric_drift": gradual baseline shift over time
          - "simpsons_paradox": subgroup reversal of aggregate trend
    day_of_week_effect : bool
        If True, apply weekday (1.2×) vs weekend (0.7×) multiplier.
    session_decay : bool
        If True, engagement drops 15% per week into the experiment.
    seed : int | None
        Random seed for reproducibility.
    """

    def __init__(
        self,
        name: str = "default",
        users: int = 1_000,
        control_cvr: float = 0.08,
        treatment_cvr: float = 0.095,
        novelty_decay_days: int = 0,
        outlier_rate: float = 0.02,
        inject_edge_cases: Optional[list[str]] = None,
        day_of_week_effect: bool = False,
        session_decay: bool = False,
        experiment_duration_days: int = 14,
        seed: Optional[int] = None,
    ):
        self.name = name
        self.users = users
        self.control_cvr = control_cvr
        self.treatment_cvr = treatment_cvr
        self.novelty_decay_days = novelty_decay_days
        self.outlier_rate = outlier_rate
        self.inject_edge_cases = inject_edge_cases or []
        self.day_of_week_effect = day_of_week_effect
        self.session_decay = session_decay
        self.experiment_duration_days = experiment_duration_days
        self._rng = random.Random(seed)
        self._start_date = datetime.now(timezone.utc) - timedelta(days=experiment_duration_days)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(self) -> ScenarioResult:
        """Run the full simulation and return a ScenarioResult."""
        users = self._assign_users()
        events = self._generate_events(users)

        # Inject edge cases
        injected: list[str] = []
        for ec in self.inject_edge_cases:
            fn = getattr(self, f"_inject_{ec}", None)
            if fn:
                fn(users, events)
                injected.append(ec)

        # Statistical significance check (rough power calculation)
        n_per_arm = self.users // 2
        delta = abs(self.treatment_cvr - self.control_cvr)
        pooled = (self.control_cvr + self.treatment_cvr) / 2
        se = math.sqrt(2 * pooled * (1 - pooled) / n_per_arm) if n_per_arm > 0 else 1
        z = delta / se if se > 0 else 0
        expected_significant = z >= 1.96  # two-tailed α=0.05

        return ScenarioResult(
            scenario_name=self.name,
            users=users,
            events=events,
            control_cvr=self.control_cvr,
            treatment_cvr=self.treatment_cvr,
            expected_significant=expected_significant,
            edge_cases_injected=injected,
            metadata={
                "experiment_duration_days": self.experiment_duration_days,
                "novelty_decay_days": self.novelty_decay_days,
                "day_of_week_effect": self.day_of_week_effect,
                "session_decay": self.session_decay,
                "z_score": round(z, 3),
            },
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _assign_users(self) -> list[SimulatedUser]:
        users: list[SimulatedUser] = []
        half = self.users // 2
        for i in range(self.users):
            user_id = f"user-{uuid.uuid4().hex[:12]}"
            variant = "control" if i < half else "treatment"
            day_offset = self._rng.uniform(0, self.experiment_duration_days)
            assigned_at = self._start_date + timedelta(days=day_offset)
            props: dict[str, Any] = {
                "country": self._rng.choice(["US", "UK", "CA", "AU", "DE"]),
                "device": self._rng.choice(["desktop", "mobile", "tablet"]),
                "segment": self._rng.choice(["new", "returning"]),
            }
            users.append(SimulatedUser(user_id, variant, assigned_at, props))
        return users

    def _effective_cvr(self, user: SimulatedUser, base_cvr: float) -> float:
        """Compute per-user effective CVR applying all modifiers."""
        cvr = base_cvr
        days_since_start = (user.assigned_at - self._start_date).total_seconds() / 86400

        # Novelty spike: treatment gets a burst on day 1 that decays
        if self.novelty_decay_days > 0 and user.variant_name == "treatment":
            decay_factor = max(
                0,
                1 - days_since_start / self.novelty_decay_days,
            )
            novelty_boost = 0.3 * decay_factor  # up to +30% on day 1
            cvr = min(cvr + novelty_boost, 1.0)

        # Day-of-week effect
        if self.day_of_week_effect:
            weekday = user.assigned_at.weekday()
            multiplier = 1.2 if weekday < 5 else 0.7
            cvr *= multiplier

        # Session decay: engagement drops 15% per week
        if self.session_decay:
            weeks = days_since_start / 7.0
            cvr *= max(0.1, 1.0 - 0.15 * weeks)

        return min(max(cvr, 0.0), 1.0)

    def _generate_events(self, users: list[SimulatedUser]) -> list[UserEvent]:
        events: list[UserEvent] = []
        for user in users:
            base_cvr = (
                self.control_cvr
                if user.variant_name == "control"
                else self.treatment_cvr
            )
            effective = self._effective_cvr(user, base_cvr)

            # Outlier: rare users produce very high-value events
            is_outlier = self._rng.random() < self.outlier_rate
            if is_outlier:
                effective = min(effective * 5, 1.0)

            if self._rng.random() < effective:
                value = self._rng.lognormvariate(0, 0.5) if is_outlier else 1.0
                event_time = user.assigned_at + timedelta(
                    hours=self._rng.uniform(0.1, 48)
                )
                events.append(
                    UserEvent(
                        user_id=user.user_id,
                        variant_name=user.variant_name,
                        event_name="purchase",
                        value=round(value, 2),
                        timestamp=event_time,
                        properties={"outlier": is_outlier},
                    )
                )
        return events

    # ------------------------------------------------------------------
    # Edge case injectors
    # ------------------------------------------------------------------

    def _inject_zero_events_user(
        self, users: list[SimulatedUser], events: list[UserEvent]
    ) -> None:
        """Add a user who is assigned but never fires any event."""
        ghost_id = f"ghost-{uuid.uuid4().hex[:8]}"
        users.append(
            SimulatedUser(
                user_id=ghost_id,
                variant_name="control",
                assigned_at=self._start_date + timedelta(hours=1),
                properties={"segment": "ghost"},
            )
        )

    def _inject_multi_assignment(
        self, users: list[SimulatedUser], events: list[UserEvent]
    ) -> None:
        """Inject a user who appears in both variants (assignment bug)."""
        if not users:
            return
        victim = self._rng.choice(users)
        duplicate = SimulatedUser(
            user_id=victim.user_id,
            variant_name="treatment" if victim.variant_name == "control" else "control",
            assigned_at=victim.assigned_at + timedelta(minutes=5),
            properties={**victim.properties, "duplicate_assignment": True},
        )
        users.append(duplicate)

    def _inject_metric_drift(
        self, users: list[SimulatedUser], events: list[UserEvent]
    ) -> None:
        """Add extra conversion events in the second half of the experiment to simulate drift."""
        midpoint = self._start_date + timedelta(days=self.experiment_duration_days / 2)
        late_users = [u for u in users if u.assigned_at > midpoint and u.variant_name == "control"]
        # Inject conversions for 10% of late control users (baseline drift)
        for user in self._rng.sample(late_users, min(len(late_users) // 10, len(late_users))):
            events.append(
                UserEvent(
                    user_id=user.user_id,
                    variant_name="control",
                    event_name="purchase",
                    value=1.0,
                    timestamp=user.assigned_at + timedelta(hours=2),
                    properties={"injected": "metric_drift"},
                )
            )

    def _inject_simpsons_paradox(
        self, users: list[SimulatedUser], events: list[UserEvent]
    ) -> None:
        """
        Create a subgroup where treatment does worse than control, even though
        the aggregate shows treatment winning.  Uses device = 'mobile' as the
        subgroup.
        """
        mobile_treatment = [
            u for u in users
            if u.variant_name == "treatment" and u.properties.get("device") == "mobile"
        ]
        # Remove any existing conversions for this subgroup
        mobile_ids = {u.user_id for u in mobile_treatment}
        events[:] = [e for e in events if e.user_id not in mobile_ids or e.properties.get("injected")]
        # Give mobile treatment users a lower CVR than control
        for user in mobile_treatment:
            if self._rng.random() < self.control_cvr * 0.5:  # half the control rate
                events.append(
                    UserEvent(
                        user_id=user.user_id,
                        variant_name="treatment",
                        event_name="purchase",
                        value=1.0,
                        timestamp=user.assigned_at + timedelta(hours=1),
                        properties={"injected": "simpsons_paradox", "device": "mobile"},
                    )
                )


# ---------------------------------------------------------------------------
# API seeder
# ---------------------------------------------------------------------------

class PlatformSeeder:
    """Seeds a running platform instance with scenario data via REST API."""

    def __init__(self, api_url: str, token: str):
        self.api_url = api_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update(
            {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        )

    def seed_scenario(self, result: ScenarioResult) -> dict[str, Any]:
        """Create an experiment and seed all events for the scenario."""
        exp_key = f"realistic-{result.scenario_name}-{uuid.uuid4().hex[:6]}"
        experiment = self._create_experiment(result, exp_key)
        exp_id = experiment["id"]

        variant_map = {v["name"]: v["id"] for v in experiment.get("variants", [])}
        seeded_events = 0
        for event in result.events:
            variant_id = variant_map.get(event.variant_name)
            if not variant_id:
                continue
            self._track_event(event, exp_id, variant_id)
            seeded_events += 1

        return {
            "experiment_id": exp_id,
            "experiment_key": exp_key,
            "users_seeded": len(result.users),
            "events_seeded": seeded_events,
        }

    def _create_experiment(self, result: ScenarioResult, key: str) -> dict[str, Any]:
        payload = {
            "name": f"[Realistic] {result.scenario_name}",
            "key": key,
            "description": f"Auto-generated scenario: {result.scenario_name}",
            "hypothesis": "Treatment will outperform control",
            "experiment_type": "a_b",
            "variants": [
                {"name": "control", "is_control": True, "traffic_allocation": 50},
                {"name": "treatment", "is_control": False, "traffic_allocation": 50},
            ],
            "metrics": [
                {
                    "name": "Conversion Rate",
                    "event_name": "purchase",
                    "metric_type": "conversion",
                    "is_primary": True,
                }
            ],
        }
        resp = self.session.post(f"{self.api_url}/api/v1/experiments", json=payload)
        resp.raise_for_status()
        return resp.json()

    def _track_event(self, event: UserEvent, exp_id: str, variant_id: str) -> None:
        payload = {
            "event_type": "track",
            "event_name": event.event_name,
            "user_id": event.user_id,
            "value": event.value,
            "experiment_id": exp_id,
            "variant_id": variant_id,
            "properties": json.dumps(event.properties),
        }
        resp = self.session.post(f"{self.api_url}/api/v1/events", json=payload)
        # Non-fatal: log and continue
        if not resp.ok:
            print(f"  Warning: failed to seed event for {event.user_id}: {resp.status_code}")


# ---------------------------------------------------------------------------
# Pre-built scenario factories
# ---------------------------------------------------------------------------

def make_ab_test_scenario(seed: int = 42) -> DataScenario:
    """
    Standard A/B test: detectable 18.75% relative lift over 14 days.

    Sample size rationale: detecting 8% → 9.5% CVR (delta=1.5pp) at α=0.05,
    80% power requires ~2,700 users per arm (5,400 total).  We use 6,000 to
    ensure robust detection even with natural variance.
    """
    return DataScenario(
        name="ab_test_lifecycle",
        users=6_000,
        control_cvr=0.08,
        treatment_cvr=0.095,
        day_of_week_effect=True,
        session_decay=False,
        seed=seed,
    )


def make_rollout_scenario(seed: int = 99) -> DataScenario:
    """
    Feature flag gradual rollout: negligible lift (rollout mechanics validation).

    Not designed to produce statistical significance — the goal is to test
    rollout percentage transitions, not detect an effect.
    """
    return DataScenario(
        name="feature_flag_rollout",
        users=4_000,
        control_cvr=0.05,
        treatment_cvr=0.051,
        day_of_week_effect=False,
        session_decay=True,
        experiment_duration_days=21,
        seed=seed,
    )


def make_novelty_scenario(seed: int = 7) -> DataScenario:
    """
    Novelty effect: day-1 spike that fades to a detectable steady-state lift.

    Uses 6,000 users to detect the 10% → 12% steady-state lift (delta=2pp)
    while also demonstrating the early inflated-CVR pattern.
    """
    return DataScenario(
        name="novelty_effect",
        users=6_000,
        control_cvr=0.10,
        treatment_cvr=0.12,
        novelty_decay_days=3,
        outlier_rate=0.01,
        day_of_week_effect=True,
        seed=seed,
    )


def make_edge_case_scenario(seed: int = 13) -> DataScenario:
    """
    Stress scenario: outliers, drift, multi-assignment bugs, Simpson's paradox.

    Uses 8,000 users so the underlying 6% → 7.2% lift (20% relative) remains
    detectable despite the noise injected by the edge cases.
    """
    return DataScenario(
        name="statistical_edge_cases",
        users=8_000,
        control_cvr=0.06,
        treatment_cvr=0.072,
        outlier_rate=0.03,
        inject_edge_cases=[
            "zero_events_user",
            "multi_assignment",
            "metric_drift",
            "simpsons_paradox",
        ],
        day_of_week_effect=True,
        session_decay=True,
        experiment_duration_days=21,
        seed=seed,
    )


def make_concurrent_scenario(seed: int = 21) -> DataScenario:
    """
    Concurrent experiments: overlapping audiences for interaction testing.

    8,000 users; detecting 7% → 8.2% lift (delta=1.2pp) at α=0.05 requires
    ~3,750 per arm (7,500 total).  We use 8,000 for comfortable margin.
    """
    return DataScenario(
        name="concurrent_experiments",
        users=8_000,
        control_cvr=0.07,
        treatment_cvr=0.082,
        day_of_week_effect=True,
        seed=seed,
    )


SCENARIOS: dict[str, DataScenario] = {
    "ab_test_lifecycle": make_ab_test_scenario(),
    "feature_flag_rollout": make_rollout_scenario(),
    "novelty_effect": make_novelty_scenario(),
    "statistical_edge_cases": make_edge_case_scenario(),
    "concurrent_experiments": make_concurrent_scenario(),
    "all": None,  # special keyword
}


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate realistic experiment data for the Experimently platform."
    )
    parser.add_argument(
        "--scenario",
        choices=list(SCENARIOS.keys()),
        default="ab_test_lifecycle",
        help="Which scenario to generate (default: ab_test_lifecycle)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print summary without seeding the API",
    )
    parser.add_argument(
        "--api-url",
        default="http://localhost:8000",
        help="Base URL of the running platform API",
    )
    parser.add_argument(
        "--token",
        default="",
        help="JWT bearer token for the API",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility",
    )
    args = parser.parse_args()

    to_run: list[DataScenario]
    if args.scenario == "all":
        to_run = [s for k, s in SCENARIOS.items() if k != "all" and s is not None]
    else:
        scenario = SCENARIOS[args.scenario]
        if scenario is None:
            print("Error: unexpected None scenario", file=sys.stderr)
            sys.exit(1)
        to_run = [scenario]

    for scenario in to_run:
        print(f"\nGenerating scenario: {scenario.name} ...")
        result = scenario.generate()
        print(result.summary())

        if not args.dry_run:
            if not args.token:
                print("  --token required to seed API.  Skipping.", file=sys.stderr)
                continue
            seeder = PlatformSeeder(args.api_url, args.token)
            seed_result = seeder.seed_scenario(result)
            print(f"  Seeded: {seed_result}")


if __name__ == "__main__":
    main()
