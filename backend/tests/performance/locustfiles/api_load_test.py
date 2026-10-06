"""
Baseline API load test for the experimentation platform.

This script simulates realistic production traffic with two user classes:
- TrackingUser (weight 8): High-frequency tracking traffic (assign + track events)
- APIUser (weight 2): Dashboard/API traffic (list experiments, evaluate flags)

The 80/20 split reflects typical production load patterns where tracking
calls far outnumber management API calls.

It calls only what ``backend/scripts/seed_sdk_contract.py`` creates (see
``common.py``): run that seed first, and pass its key in ``LOAD_TEST_API_KEY``
or ``LOAD_TEST_API_KEY_FILE``.

Usage (headless CI):
    locust -f api_load_test.py --headless --users 100 --spawn-rate 10 \
           --run-time 60s --host http://localhost:8000 \
           --csv /tmp/locust_baseline

Usage (interactive web UI):
    locust -f api_load_test.py --host http://localhost:8000
    # Then open http://localhost:8089 in your browser
"""

import random
import uuid

from locust import HttpUser, between, events, task
from locust.env import Environment

from backend.tests.performance.locustfiles.common import (
    EXPERIMENT_KEY,
    FLAG_KEY,
    expect,
    login,
    sdk_headers,
)

# The PERFORMANCE_TARGETS this file exercises. run_load_tests.py fails the run
# unless Locust recorded requests for every one of them.
TARGETS = ("track", "assign", "list_experiments", "evaluate_flag", "health")

# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

# User pool — 10,000 synthetic user IDs
USER_POOL_SIZE: int = 10_000

# Event types that can be tracked
EVENT_TYPES: list[str] = ["page_view", "click", "conversion", "add_to_cart", "checkout"]

# Device types for context enrichment
DEVICE_TYPES: list[str] = ["mobile", "desktop", "tablet"]

# Country codes for targeting context
COUNTRY_CODES: list[str] = ["US", "GB", "DE", "FR", "CA", "AU", "JP", "BR"]


def _random_user_id() -> str:
    """Generate a random user ID from the synthetic user pool."""
    return f"user_{random.randint(1, USER_POOL_SIZE)}"


def _random_context() -> dict:
    """Generate a random targeting context dict for assignment/evaluation requests."""
    return {
        "country": random.choice(COUNTRY_CODES),
        "device": random.choice(DEVICE_TYPES),
        "app_version": f"2.{random.randint(0, 9)}.{random.randint(0, 99)}",
    }


# ---------------------------------------------------------------------------
# TrackingUser — 80% of virtual users, simulates high-frequency SDK calls
# ---------------------------------------------------------------------------


class TrackingUser(HttpUser):
    """
    Simulates high-frequency tracking traffic (80% of total load).

    This user class represents client SDKs calling the tracking endpoints.
    Tasks are weighted to reflect real traffic patterns:
    - track_event (weight 3): Most common — users generate many events
    - assign_user (weight 1): Less common — assignment happens once per experiment
    """

    weight = 8
    # Short wait between tasks to simulate high-frequency SDK calls (20–100 req/s per user)
    wait_time = between(0.01, 0.05)

    def on_start(self) -> None:
        """Set up the API key headers for tracking calls."""
        self.headers: dict[str, str] = sdk_headers()

    @task(3)
    def track_event(self) -> None:
        """
        POST /api/v1/tracking/track

        Simulates SDK tracking an event associated with an experiment.
        Weight 3 — the most frequent operation in the tracking pipeline.
        """
        payload = {
            "experiment_key": EXPERIMENT_KEY,
            "user_id": _random_user_id(),
            "event_type": random.choice(EVENT_TYPES),
            "value": round(random.uniform(0.0, 100.0), 2),
            "metadata": {
                "source": "load_test",
                "session_id": str(uuid.uuid4()),
            },
        }
        with self.client.post(
            "/api/v1/tracking/track",
            json=payload,
            headers=self.headers,
            name="/api/v1/tracking/track",
            catch_response=True,
        ) as response:
            expect(response, 200)

    @task(1)
    def assign_user(self) -> None:
        """
        POST /api/v1/tracking/assign

        Simulates SDK requesting a user's experiment variant assignment.
        Weight 1 — less frequent than tracking but still high volume.
        """
        payload = {
            "experiment_key": EXPERIMENT_KEY,
            "user_id": _random_user_id(),
            "context": _random_context(),
        }
        with self.client.post(
            "/api/v1/tracking/assign",
            json=payload,
            headers=self.headers,
            name="/api/v1/tracking/assign",
            catch_response=True,
        ) as response:
            expect(response, 200)


# ---------------------------------------------------------------------------
# APIUser — 20% of virtual users, simulates dashboard/management API calls
# ---------------------------------------------------------------------------


class APIUser(HttpUser):
    """
    Simulates API/dashboard traffic (20% of total load).

    This user class represents dashboard users and server-side SDK calls
    for feature flag evaluation. Tasks are weighted by frequency:
    - list_experiments (weight 5): Frequent dashboard polling (bearer token)
    - evaluate_feature_flag (weight 3): Server-side flag evaluation (API key)
    - health_check (weight 2): Monitoring and load balancer probes
    """

    weight = 2
    # Longer wait time between tasks — dashboard interactions are less frequent
    wait_time = between(0.5, 2.0)

    def on_start(self) -> None:
        """Sign in for the dashboard calls; the API key is for evaluation."""
        self.auth_headers: dict[str, str] = login(self.client)
        self.sdk_headers: dict[str, str] = sdk_headers()

    @task(5)
    def list_experiments(self) -> None:
        """
        GET /api/v1/experiments

        Simulates dashboard polling the experiments list.
        Weight 5 — frequent dashboard operation.
        """
        with self.client.get(
            "/api/v1/experiments/",
            headers=self.auth_headers,
            name="/api/v1/experiments",
            catch_response=True,
        ) as response:
            expect(response, 200)

    @task(3)
    def evaluate_feature_flag(self) -> None:
        """
        GET /api/v1/feature-flags/evaluate/{key}

        Simulates server-side SDK evaluating a feature flag for a user.
        Weight 3 — moderate frequency.
        """
        with self.client.get(
            f"/api/v1/feature-flags/evaluate/{FLAG_KEY}",
            params={"user_id": _random_user_id()},
            headers=self.sdk_headers,
            name="/api/v1/feature-flags/evaluate/{key}",
            catch_response=True,
        ) as response:
            expect(response, 200)

    @task(2)
    def health_check(self) -> None:
        """
        GET /health

        Simulates load balancer health probes and monitoring checks.
        Weight 2 — continuous background traffic.
        """
        with self.client.get(
            "/health",
            name="/health",
            catch_response=True,
        ) as response:
            expect(response, 200)


# ---------------------------------------------------------------------------
# Event hooks — save results on test completion
# ---------------------------------------------------------------------------


@events.quitting.add_listener
def on_quitting(environment: Environment, **kwargs: object) -> None:
    """
    Save final test statistics when Locust exits.

    Prints a summary to stdout so it is captured by CI logs.
    The CSV files are written by Locust itself when --csv is specified.
    """
    stats = environment.runner.stats if environment.runner else None
    if stats is None:
        return

    total_requests = stats.total.num_requests
    total_failures = stats.total.num_failures
    failure_rate = (
        (total_failures / total_requests * 100) if total_requests > 0 else 0.0
    )

    print("\n" + "=" * 60)
    print("LOAD TEST COMPLETED")
    print("=" * 60)
    print(f"Total requests : {total_requests}")
    print(f"Total failures : {total_failures} ({failure_rate:.2f}%)")
    print(f"RPS (avg)      : {stats.total.current_rps:.1f}")
    print("=" * 60)
