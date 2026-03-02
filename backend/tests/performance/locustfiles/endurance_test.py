"""
Endurance test for the experimentation platform.

Tests for memory leaks, connection pool exhaustion, and performance degradation
over an extended period of sustained load.

Test profile:
  - 100 concurrent users for 30 minutes
  - Steady-state traffic mix representing typical production load
  - Metrics sampled at 5-minute intervals by the custom listener

Degradation signals to watch for:
  - Increasing p95/p99 latency over time (memory pressure, GC pauses)
  - Rising error rate (connection pool leaks, file descriptor exhaustion)
  - Decreasing RPS over time (throughput degradation under sustained load)
  - Memory growth in the server process (heap leaks in application code)

Usage (headless CI — 30 minute run):
    locust -f endurance_test.py --headless --users 100 --spawn-rate 10 \
           --run-time 30m --host http://localhost:8000 \
           --csv /tmp/locust_endurance

Usage (shorter run for smoke testing — 5 minutes):
    locust -f endurance_test.py --headless --users 50 --spawn-rate 5 \
           --run-time 5m --host http://localhost:8000 \
           --csv /tmp/locust_endurance_smoke

Usage (interactive web UI):
    locust -f endurance_test.py --host http://localhost:8000
    # Then open http://localhost:8089 in your browser
"""
import os
import random
import time
import uuid
from typing import Any

from locust import HttpUser, task, between, events
from locust.env import Environment

# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

EXPERIMENT_KEYS: list[str] = [f"experiment-key-{i:04d}" for i in range(1, 21)]
FEATURE_FLAG_KEYS: list[str] = [f"flag-{i:03d}" for i in range(1, 16)]
EVENT_TYPES: list[str] = [
    "page_view",
    "click",
    "conversion",
    "add_to_cart",
    "checkout",
    "search",
]
DEVICE_TYPES: list[str] = ["mobile", "desktop", "tablet"]
COUNTRY_CODES: list[str] = ["US", "GB", "DE", "FR", "CA", "AU"]

# Use a large user pool to avoid artificial caching effects
USER_POOL_SIZE: int = 100_000

# Interval in seconds between metric snapshot logs
METRICS_SNAPSHOT_INTERVAL_SECONDS: int = 300  # 5 minutes


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
# Endurance user class
# ---------------------------------------------------------------------------


class EnduranceUser(HttpUser):
    """
    Sustained load user for endurance testing.

    Represents steady-state production traffic over 30 minutes.
    Task weights reflect realistic production ratios:
    - track_event (4): Highest volume — every user interaction generates events
    - assign_user (2): Moderate — assignment on experiment entry
    - evaluate_feature_flag (2): Moderate — server-side evaluation per request
    - list_experiments (1): Low — dashboard polling
    - health_check (1): Low — monitoring probes
    """

    wait_time = between(0.1, 0.5)

    def on_start(self) -> None:
        """Initialise authentication headers for this virtual user."""
        self.api_key: str = os.environ.get("LOAD_TEST_API_KEY", "test-api-key")
        self.headers: dict[str, str] = {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
        }

    @task(4)
    def track_event(self) -> None:
        """
        POST /api/v1/tracking/track

        Highest-frequency operation — simulates continuous event stream
        from all active users throughout the endurance window.
        """
        payload = {
            "experiment_key": random.choice(EXPERIMENT_KEYS),
            "user_id": _random_user_id(),
            "event_type": random.choice(EVENT_TYPES),
            "value": round(random.uniform(0.0, 500.0), 2),
            "metadata": {
                "source": "endurance_test",
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
    def assign_user(self) -> None:
        """
        POST /api/v1/tracking/assign

        Simulates users entering experiments — occurs continuously as new
        users arrive throughout the endurance window.
        """
        payload = {
            "experiment_key": random.choice(EXPERIMENT_KEYS),
            "user_id": _random_user_id(),
            "context": _random_context(),
        }
        self.client.post(
            "/api/v1/tracking/assign",
            json=payload,
            headers=self.headers,
            name="/api/v1/tracking/assign",
            catch_response=True,
        )

    @task(2)
    def evaluate_feature_flag(self) -> None:
        """
        GET /api/v1/feature-flags/evaluate/{key}

        Server-side flag evaluation on the critical request path.
        Tests that the evaluation cache remains effective over time.
        """
        flag_key = random.choice(FEATURE_FLAG_KEYS)
        self.client.get(
            f"/api/v1/feature-flags/evaluate/{flag_key}",
            params={"user_id": _random_user_id()},
            headers=self.headers,
            name="/api/v1/feature-flags/evaluate/{key}",
            catch_response=True,
        )

    @task(1)
    def list_experiments(self) -> None:
        """
        GET /api/v1/experiments

        Dashboard polling — tests that the DB query plan stays stable
        and doesn't degrade as the connection pool ages.
        """
        self.client.get(
            "/api/v1/experiments",
            headers=self.headers,
            name="/api/v1/experiments",
            catch_response=True,
        )

    @task(1)
    def health_check(self) -> None:
        """
        GET /health

        Continuous availability monitoring — should always return quickly
        even under sustained load.
        """
        self.client.get(
            "/health",
            name="/health",
            catch_response=True,
        )


# ---------------------------------------------------------------------------
# Periodic metrics snapshots
# ---------------------------------------------------------------------------

# Track when the last snapshot was taken so we can log at 5-minute intervals
_last_snapshot_time: float = 0.0
_snapshot_number: int = 0


@events.request.add_listener
def on_request(
    request_type: str,
    name: str,
    response_time: float,
    response_length: int,
    exception: Any,
    context: Any,
    **kwargs: Any,
) -> None:
    """
    Periodic snapshot listener — logs aggregate stats every 5 minutes.

    This enables detecting gradual performance degradation by comparing
    snapshots from early in the test against those from later minutes.
    """
    global _last_snapshot_time, _snapshot_number

    current_time = time.time()
    if current_time - _last_snapshot_time >= METRICS_SNAPSHOT_INTERVAL_SECONDS:
        _last_snapshot_time = current_time
        _snapshot_number += 1
        # The actual stats object is on the runner — accessed via the global env.
        # We just log a marker here; full stats are available in the Locust CSV output.
        elapsed_minutes = _snapshot_number * (METRICS_SNAPSHOT_INTERVAL_SECONDS // 60)
        print(
            f"\n[ENDURANCE SNAPSHOT {_snapshot_number}] "
            f"Elapsed: {elapsed_minutes}m — "
            f"check /tmp/locust_endurance_stats.csv for current percentiles"
        )


@events.test_start.add_listener
def on_test_start(environment: Environment, **kwargs: Any) -> None:
    """Log test configuration at start."""
    global _last_snapshot_time
    _last_snapshot_time = time.time()
    print("\n" + "=" * 60)
    print("ENDURANCE TEST STARTED")
    print("Target: 100 users for 30 minutes")
    print(f"Snapshot interval: {METRICS_SNAPSHOT_INTERVAL_SECONDS}s")
    print("=" * 60)


@events.test_stop.add_listener
def on_test_stop(environment: Environment, **kwargs: Any) -> None:
    """Log final summary when test completes."""
    stats = environment.runner.stats if environment.runner else None
    if stats is None:
        return

    total = stats.total.num_requests
    failures = stats.total.num_failures
    failure_pct = (failures / total * 100) if total > 0 else 0.0

    print("\n" + "=" * 60)
    print("ENDURANCE TEST COMPLETED")
    print("=" * 60)
    print(f"Total requests : {total:,}")
    print(f"Total failures : {failures:,} ({failure_pct:.2f}%)")
    print(f"Avg RPS        : {stats.total.current_rps:.1f}")
    print(f"Snapshots taken: {_snapshot_number}")
    print("=" * 60)
    if failure_pct > 1.0:
        print("WARNING: Failure rate exceeded 1% threshold during endurance run")
    else:
        print("Failure rate within acceptable threshold (<1%)")
    print("=" * 60)
