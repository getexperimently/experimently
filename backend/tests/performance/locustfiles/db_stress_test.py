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
  - Batch flag evaluations (multi-row reads in a single transaction)

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
import os
import random
import uuid

from locust import HttpUser, task, between, events
from locust.env import Environment

# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

# 20 experiment keys used in queries and writes
EXPERIMENT_KEYS: list[str] = [f"experiment-key-{i:04d}" for i in range(1, 21)]

# 15 feature flag keys for evaluation endpoints
FEATURE_FLAG_KEYS: list[str] = [f"flag-{i:03d}" for i in range(1, 16)]

# Event types that can be tracked
EVENT_TYPES: list[str] = ["page_view", "click", "conversion", "add_to_cart", "checkout"]

# Large user pool to stress connection pooling and avoid cache hot-spots
USER_POOL_SIZE: int = 100_000

# Experiment statuses for filtered queries
EXPERIMENT_STATUSES: list[str] = ["DRAFT", "ACTIVE", "PAUSED", "COMPLETED"]

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
    - batch_flag_eval (2): Multi-row reads in single transaction
    """

    wait_time = between(0.05, 0.2)

    def on_start(self) -> None:
        """Set up authentication headers for database stress operations."""
        self.api_key: str = os.environ.get("LOAD_TEST_API_KEY", "test-api-key")
        self.headers: dict[str, str] = {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
            "Authorization": f"Bearer {os.environ.get('LOAD_TEST_AUTH_TOKEN', 'test-bearer-token')}",
        }

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
            "description": "Created during database stress test",
            "experiment_type": "ab_test",
            "status": "DRAFT",
            "key": exp_key,
            "variants": [
                {"name": "control", "traffic_allocation": 0.5},
                {"name": "treatment", "traffic_allocation": 0.5},
            ],
            "traffic_allocation": round(random.uniform(0.1, 1.0), 2),
        }
        self.client.post(
            "/api/v1/experiments",
            json=payload,
            headers=self.headers,
            name="/api/v1/experiments [write]",
            catch_response=True,
        )

    @task(4)
    def read_with_filters(self) -> None:
        """
        GET /api/v1/experiments

        Reads experiments with status filters and pagination to stress
        query planning and index utilisation under concurrent load.
        Weight 4 — high-frequency filtered reads.
        """
        status = random.choice(EXPERIMENT_STATUSES)
        page = random.randint(1, 10)
        per_page = random.choice([10, 20, 50, 100])
        self.client.get(
            "/api/v1/experiments",
            params={"status": status, "page": page, "per_page": per_page},
            headers=self.headers,
            name="/api/v1/experiments [filtered]",
            catch_response=True,
        )

    @task(2)
    def complex_query(self) -> None:
        """
        GET /api/v1/experiments/{experiment_id}/results

        Triggers complex JOIN queries across experiments, variants, and
        metrics tables. Tests connection hold time under high concurrency.
        Weight 2 — moderate frequency, each query is expensive.
        """
        experiment_key = random.choice(EXPERIMENT_KEYS)
        # Use the key as a pseudo-ID to generate a deterministic UUID
        experiment_id = str(uuid.uuid5(
            uuid.UUID("12345678-1234-5678-1234-567812345678"),
            experiment_key,
        ))
        self.client.get(
            f"/api/v1/experiments/{experiment_id}/results",
            headers=self.headers,
            name="/api/v1/experiments/{experiment_id}/results",
            catch_response=True,
        )

    @task(3)
    def flag_evaluation_storm(self) -> None:
        """
        GET /api/v1/feature-flags/evaluate/{key}

        Rapid feature flag evaluations to stress the evaluation cache
        and underlying database reads when cache misses occur.
        Weight 3 — high frequency to overwhelm cache capacity.
        """
        flag_key = random.choice(FEATURE_FLAG_KEYS)
        self.client.get(
            f"/api/v1/feature-flags/evaluate/{flag_key}",
            params={"user_id": _random_user_id(), "context": str(_random_context())},
            headers=self.headers,
            name="/api/v1/feature-flags/evaluate/{key}",
            catch_response=True,
        )

    @task(5)
    def tracking_burst(self) -> None:
        """
        POST /api/v1/tracking/track

        High-volume event tracking writes to stress the write-ahead log
        and INSERT throughput on the events/tracking table.
        Weight 5 — highest frequency to maximise write pressure.
        """
        payload = {
            "experiment_key": random.choice(EXPERIMENT_KEYS),
            "user_id": _random_user_id(),
            "event_type": random.choice(EVENT_TYPES),
            "value": round(random.uniform(0.0, 500.0), 2),
            "metadata": {
                "source": "db_stress_test",
                "session_id": str(uuid.uuid4()),
                "device": random.choice(DEVICE_TYPES),
            },
        }
        self.client.post(
            "/api/v1/tracking/track",
            json=payload,
            headers=self.headers,
            name="/api/v1/tracking/track",
            catch_response=True,
        )

    @task(2)
    def batch_flag_eval(self) -> None:
        """
        POST /api/v1/feature-flags/evaluate-batch

        Batch evaluation of multiple feature flags in a single request.
        Tests multi-row reads within a single database transaction.
        Weight 2 — moderate frequency, each request is heavier than single eval.
        """
        # Select a random subset of flags to evaluate in one batch
        num_flags = random.randint(3, 8)
        selected_flags = random.sample(FEATURE_FLAG_KEYS, min(num_flags, len(FEATURE_FLAG_KEYS)))
        payload = {
            "flag_keys": selected_flags,
            "user_id": _random_user_id(),
            "context": _random_context(),
        }
        self.client.post(
            "/api/v1/feature-flags/evaluate-batch",
            json=payload,
            headers=self.headers,
            name="/api/v1/feature-flags/evaluate-batch",
            catch_response=True,
        )


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
    failure_rate = (total_failures / total_requests * 100) if total_requests > 0 else 0.0

    print("\n" + "=" * 60)
    print("DATABASE STRESS TEST COMPLETED")
    print("=" * 60)
    print(f"Total requests : {total_requests}")
    print(f"Total failures : {total_failures} ({failure_rate:.2f}%)")
    print(f"RPS (avg)      : {stats.total.current_rps:.1f}")
    print("=" * 60)
