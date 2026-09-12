"""
Breakpoint (capacity finding) test for the experimentation platform.

Progressively increases load through seven stages to find the system's
breaking point — the concurrency level at which error rates spike or
latency becomes unacceptable.

Load profile (7 stages, monotonically increasing):
  Stage 1 (0–60s):    10 users   @ 5/s   — warm-up baseline
  Stage 2 (60–120s):  50 users   @ 10/s  — light production load
  Stage 3 (120–180s): 100 users  @ 15/s  — moderate load
  Stage 4 (180–240s): 200 users  @ 20/s  — heavy load
  Stage 5 (240–300s): 500 users  @ 30/s  — peak traffic
  Stage 6 (300–360s): 1000 users @ 50/s  — stress zone
  Stage 7 (360–420s): 2000 users @ 100/s — overload / breaking point

Signals to watch for:
  - The stage where p99 latency exceeds SLA thresholds
  - The user count at which error rate first exceeds 1%
  - Connection pool exhaustion indicators (503 responses)
  - The maximum sustainable RPS before degradation

Usage (headless CI):
    locust -f breakpoint_test.py --headless --host http://localhost:8000 \
           --csv /tmp/locust_breakpoint

Usage (interactive web UI):
    locust -f breakpoint_test.py --host http://localhost:8000
    # Then open http://localhost:8089 in your browser
"""

import os
import random
import uuid
from typing import Any, Optional, Tuple

from locust import HttpUser, LoadTestShape, between, events, task
from locust.env import Environment

# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

EXPERIMENT_KEYS: list[str] = [f"experiment-key-{i:04d}" for i in range(1, 21)]
FEATURE_FLAG_KEYS: list[str] = [f"flag-{i:03d}" for i in range(1, 16)]
EVENT_TYPES: list[str] = ["page_view", "click", "conversion"]
USER_POOL_SIZE: int = 50_000  # Large pool to avoid hot-user cache effects


def _random_user_id() -> str:
    """Return a random user ID from the synthetic pool."""
    return f"user_{random.randint(1, USER_POOL_SIZE)}"


# ---------------------------------------------------------------------------
# Breakpoint test shape — progressively increasing load
# ---------------------------------------------------------------------------


class BreakpointShape(LoadTestShape):
    """
    Seven-stage breakpoint load profile with monotonically increasing users.

    Each stage entry defines:
    - duration: Cumulative elapsed seconds at which the stage ends
    - users: Target concurrent user count for this stage
    - spawn_rate: Users per second to add when transitioning to this stage
    """

    stages: list[dict[str, int]] = [
        {"duration": 60, "users": 10, "spawn_rate": 5},
        {"duration": 120, "users": 50, "spawn_rate": 10},
        {"duration": 180, "users": 100, "spawn_rate": 15},
        {"duration": 240, "users": 200, "spawn_rate": 20},
        {"duration": 300, "users": 500, "spawn_rate": 30},
        {"duration": 360, "users": 1000, "spawn_rate": 50},
        {"duration": 420, "users": 2000, "spawn_rate": 100},
    ]

    def tick(self) -> Optional[Tuple[int, int]]:
        """
        Return (user_count, spawn_rate) for the current run time.

        Returns None to stop the test when all stages are complete.
        """
        run_time = self.get_run_time()
        for stage in self.stages:
            if run_time < stage["duration"]:
                return stage["users"], stage["spawn_rate"]
        # All stages complete — signal Locust to stop
        return None


# ---------------------------------------------------------------------------
# Breakpoint user — mixed traffic to stress all major endpoints
# ---------------------------------------------------------------------------


class BreakpointUser(HttpUser):
    """
    Mixed traffic user for breakpoint testing.

    Uses aggressive wait times to maximise concurrency at each stage.
    Task weights represent a balanced production traffic mix:
    - track_event (weight 4): Highest volume — event tracking pipeline
    - assign_user (weight 2): Moderate — experiment assignment
    - evaluate_feature_flag (weight 2): Moderate — server-side flag evaluation
    - list_experiments (weight 1): Low — dashboard polling
    - health_check (weight 1): Low — monitoring probes
    """

    wait_time = between(0.05, 0.2)

    def on_start(self) -> None:
        """Set up authentication headers."""
        self.api_key: str = os.environ.get("LOAD_TEST_API_KEY", "test-api-key")
        self.headers: dict[str, str] = {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
        }

    @task(4)
    def track_event(self) -> None:
        """
        POST /api/v1/tracking/track

        Highest weight — event tracking is the most critical path.
        At high user counts this stresses write throughput and WAL.
        """
        payload = {
            "experiment_key": random.choice(EXPERIMENT_KEYS),
            "user_id": _random_user_id(),
            "event_type": random.choice(EVENT_TYPES),
            "value": round(random.uniform(0.0, 100.0), 2),
            "metadata": {"source": "breakpoint_test", "session_id": str(uuid.uuid4())},
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

        Experiment assignment — tests the assignment logic and database
        writes under increasing concurrency.
        """
        payload = {
            "experiment_key": random.choice(EXPERIMENT_KEYS),
            "user_id": _random_user_id(),
            "context": {"country": "US", "device": "mobile"},
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

        Server-side flag evaluation — tests cache effectiveness and
        database read path as concurrency scales.
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

        Dashboard traffic — tests that list queries remain stable
        even as overall system load increases dramatically.
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

        Health probe — must remain responsive at every load stage.
        A failing health check indicates the system has truly broken.
        """
        self.client.get(
            "/health",
            name="/health",
            catch_response=True,
        )


# ---------------------------------------------------------------------------
# Event hooks — log stage progression and final summary
# ---------------------------------------------------------------------------


@events.test_start.add_listener
def on_test_start(environment: Environment, **kwargs: Any) -> None:
    """Log test configuration and stage descriptions at start."""
    print("\n" + "=" * 60)
    print("BREAKPOINT TEST STARTED")
    print("=" * 60)
    print("Progressive load stages:")
    print("  Stage 1 (0-60s):    10 users   @ 5/s   — warm-up baseline")
    print("  Stage 2 (60-120s):  50 users   @ 10/s  — light production")
    print("  Stage 3 (120-180s): 100 users  @ 15/s  — moderate load")
    print("  Stage 4 (180-240s): 200 users  @ 20/s  — heavy load")
    print("  Stage 5 (240-300s): 500 users  @ 30/s  — peak traffic")
    print("  Stage 6 (300-360s): 1000 users @ 50/s  — stress zone")
    print("  Stage 7 (360-420s): 2000 users @ 100/s — overload")
    print("=" * 60)


@events.test_stop.add_listener
def on_test_stop(environment: Environment, **kwargs: Any) -> None:
    """Log final summary with aggregate statistics."""
    stats = environment.runner.stats if environment.runner else None
    if stats is None:
        return

    total_requests = stats.total.num_requests
    total_failures = stats.total.num_failures
    failure_rate = (total_requests and total_failures / total_requests * 100) or 0.0
    avg_rps = stats.total.current_rps

    print("\n" + "=" * 60)
    print("BREAKPOINT TEST COMPLETED")
    print("=" * 60)
    print(f"Total requests : {total_requests:,}")
    print(f"Total failures : {total_failures:,} ({failure_rate:.2f}%)")
    print(f"Avg RPS        : {avg_rps:.1f}")
    print("=" * 60)
    if failure_rate > 5.0:
        print("RESULT: System broke under load — failure rate exceeded 5%")
    elif failure_rate > 1.0:
        print("RESULT: System degraded — failure rate exceeded 1%")
    else:
        print("RESULT: System survived all stages — no breakpoint found")
    print("=" * 60)
