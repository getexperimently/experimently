"""
Database stress test for the experimentation platform.

Pushes the database connection pool, write path, and query planner to their
limits with aggressive request timing and a large synthetic user pool.

Stress vectors:
  - Rapid concurrent writes to the experiments table (INSERT contention)
  - Filtered reads with pagination (query planner, index utilisation)
  - Complex result queries with joins (connection hold time)
  - High-volume feature flag evaluations (evaluation cache pressure)
  - Tracking bursts (write throughput, WAL pressure)
  - Batch flag evaluations (every flag for one user in a single request)

It calls only what ``backend/scripts/seed_sdk_contract.py`` creates (see
``common.py``); results are read from the seeded ACTIVE experiment.

Signals to watch for:
  - Connection pool exhaustion (HTTP 503, increasing queue wait times)
  - Lock contention on hot tables (increasing p99 latency)
  - Query plan regressions under load (sudden latency jumps)
  - Transaction deadlocks (intermittent 500 errors)

Usage (headless CI):
    locust -f db_stress_test.py --headless --users 200 --spawn-rate 50 \
           --run-time 120s --host http://localhost:8000 \
           --csv /tmp/locust_db_stress

Usage (interactive web UI):
    locust -f db_stress_test.py --host http://localhost:8000
    # Then open http://localhost:8089 in your browser
"""

import json
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
    seeded_experiment_id,
)

# The PERFORMANCE_TARGETS this file exercises. run_load_tests.py fails the run
# unless Locust recorded requests for every one of them.
TARGETS = (
    "create_experiment",
    "list_experiments",
    "get_experiment_results",
    "evaluate_flag",
    "track",
    "batch_evaluate_flags",
)

# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

# Event types that can be tracked
EVENT_TYPES: list[str] = ["page_view", "click", "conversion", "add_to_cart", "checkout"]

# Large user pool to stress connection pooling and avoid cache hot-spots
USER_POOL_SIZE: int = 100_000

# Experiment statuses for filtered queries
EXPERIMENT_STATUSES: list[str] = ["draft", "active", "paused", "completed"]

# Device types for context enrichment
DEVICE_TYPES: list[str] = ["mobile", "desktop", "tablet"]

# Country codes for targeting context
COUNTRY_CODES: list[str] = ["US", "GB", "DE", "FR", "CA", "AU"]


def _random_user_id() -> str:
    """Return a random user ID from the large synthetic pool."""
    return f"user_{random.randint(1, USER_POOL_SIZE)}"


def _random_context() -> dict[str, str]:
    """Return a random targeting context dictionary."""
    return {
        "country": random.choice(COUNTRY_CODES),
        "device": random.choice(DEVICE_TYPES),
        "app_version": f"3.{random.randint(0, 5)}.{random.randint(0, 99)}",
    }


# ---------------------------------------------------------------------------
# DbStressUser — aggressive timing to maximise database pressure
# ---------------------------------------------------------------------------


class DbStressUser(HttpUser):
    """
    Database stress test user with aggressive request timing.

    Uses very short wait times (50ms–200ms) to maximise concurrent database
    operations and stress the connection pool. Task weights are designed to
    create a balanced mix of reads and writes that push different database
    subsystems:
    - concurrent_write (4): INSERT pressure on experiments table
    - read_with_filters (4): Filtered SELECT with pagination (index stress)
    - complex_query (2): JOIN-heavy result queries (connection hold time)
    - flag_evaluation_storm (3): Rapid flag evaluations (cache + read pressure)
    - tracking_burst (5): High-volume event writes (WAL, write throughput)
    - batch_flag_eval (2): Every flag evaluated for one user in one request
    """

    wait_time = between(0.05, 0.2)

    def on_start(self) -> None:
        """API key for the SDK routes; a bearer token for the management routes."""
        self.headers: dict[str, str] = sdk_headers()
        self.auth_headers: dict[str, str] = login(self.client)
        self.experiment_id: str = seeded_experiment_id(self.client, self.auth_headers)

    @task(4)
    def concurrent_write(self) -> None:
        """
        POST /api/v1/experiments

        Creates experiments rapidly to stress the write path.
        Weight 4 — high-frequency writes to test INSERT contention,
        WAL throughput, and connection pool under write pressure.
        """
        exp_key = f"stress-exp-{uuid.uuid4().hex[:12]}"
        payload = {
            "name": f"Stress Test Experiment {exp_key}",
            "key": exp_key,
            "description": "Created during database stress test",
            "experiment_type": "a_b",
            "variants": [
                {"name": "control", "is_control": True, "traffic_allocation": 50},
                {"name": "treatment", "traffic_allocation": 50},
            ],
            "metrics": [
                {"name": "Purchase", "event_name": "purchase", "is_primary": True}
            ],
        }
        with self.client.post(
            "/api/v1/experiments/",
            json=payload,
            headers=self.auth_headers,
            name="/api/v1/experiments",
            catch_response=True,
        ) as response:
            expect(response, 201)

    @task(4)
    def read_with_filters(self) -> None:
        """
        GET /api/v1/experiments

        Reads experiments with status filters and pagination to stress
        query planning and index utilisation under concurrent load.
        Weight 4 — high-frequency filtered reads.
        """
        params = {
            "status_filter": random.choice(EXPERIMENT_STATUSES),
            "skip": random.randint(0, 9) * 20,
            "limit": random.choice([10, 20, 50, 100]),
        }
        with self.client.get(
            "/api/v1/experiments/",
            params=params,
            headers=self.auth_headers,
            name="/api/v1/experiments",
            catch_response=True,
        ) as response:
            expect(response, 200)

    @task(2)
    def complex_query(self) -> None:
        """
        GET /api/v1/experiments/{experiment_id}/results

        Triggers complex JOIN queries across experiments, variants, and
        metrics tables. Tests connection hold time under high concurrency.
        Weight 2 — moderate frequency, each query is expensive.
        """
        with self.client.get(
            f"/api/v1/experiments/{self.experiment_id}/results",
            headers=self.auth_headers,
            name="/api/v1/experiments/{experiment_id}/results",
            catch_response=True,
        ) as response:
            expect(response, 200)

    @task(3)
    def flag_evaluation_storm(self) -> None:
        """
        GET /api/v1/feature-flags/evaluate/{key}

        Rapid feature flag evaluations to stress the evaluation cache
        and underlying database reads when cache misses occur.
        Weight 3 — high frequency to overwhelm cache capacity.
        """
        with self.client.get(
            f"/api/v1/feature-flags/evaluate/{FLAG_KEY}",
            params={
                "user_id": _random_user_id(),
                "context": json.dumps(_random_context()),
            },
            headers=self.headers,
            name="/api/v1/feature-flags/evaluate/{key}",
            catch_response=True,
        ) as response:
            expect(response, 200)

    @task(5)
    def tracking_burst(self) -> None:
        """
        POST /api/v1/tracking/track

        High-volume event tracking writes to stress the write-ahead log
        and INSERT throughput on the events/tracking table.
        Weight 5 — highest frequency to maximise write pressure.
        """
        payload = {
            "experiment_key": EXPERIMENT_KEY,
            "user_id": _random_user_id(),
            "event_type": random.choice(EVENT_TYPES),
            "value": round(random.uniform(0.0, 500.0), 2),
            "metadata": {
                "source": "db_stress_test",
                "session_id": str(uuid.uuid4()),
                "device": random.choice(DEVICE_TYPES),
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

    @task(2)
    def batch_flag_eval(self) -> None:
        """
        GET /api/v1/feature-flags/user/{user_id}

        Every feature flag evaluated for one user in a single request, the
        call an SDK makes at start-up. Weight 2 — moderate frequency, each
        request is heavier than a single evaluation.
        """
        user_id = _random_user_id()
        with self.client.get(
            f"/api/v1/feature-flags/user/{user_id}",
            params={"context": json.dumps(_random_context())},
            headers=self.headers,
            name="/api/v1/feature-flags/user/{user_id}",
            catch_response=True,
        ) as response:
            expect(response, 200)


# ---------------------------------------------------------------------------
# Event hooks — print summary on test completion
# ---------------------------------------------------------------------------


@events.quitting.add_listener
def on_quitting(environment: Environment, **kwargs: object) -> None:
    """
    Print final test statistics when Locust exits.

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
    print("DATABASE STRESS TEST COMPLETED")
    print("=" * 60)
    print(f"Total requests : {total_requests}")
    print(f"Total failures : {total_failures} ({failure_rate:.2f}%)")
    print(f"RPS (avg)      : {stats.total.current_rps:.1f}")
    print("=" * 60)
