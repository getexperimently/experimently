"""
Spike test for the experimentation platform.

Tests system resilience under sudden, extreme traffic bursts.
The test follows a four-stage profile:
  1. Baseline  (0–30s):  10 users — normal steady-state traffic
  2. Spike     (30–60s): Ramp to 1000 users at 100/s — sudden traffic surge
  3. Sustain   (60–90s): Hold at 1000 users — extended peak load
  4. Recovery  (90–120s): Ramp back to 10 users at 100/s — traffic subsides

The goal is to detect:
- Latency degradation during the spike ramp
- Error rate spikes (circuit breakers, connection pool exhaustion)
- Recovery time after traffic normalises
- Memory/resource leaks that manifest only under burst conditions

Usage (headless CI):
    locust -f spike_test.py --headless --host http://localhost:8000 \
           --csv /tmp/locust_spike

Usage (interactive web UI):
    locust -f spike_test.py --host http://localhost:8000
    # Then open http://localhost:8089 in your browser
"""

import os
import random
import uuid

from locust import HttpUser, LoadTestShape, between, task

# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

EXPERIMENT_KEYS: list[str] = [f"experiment-key-{i:04d}" for i in range(1, 21)]
FEATURE_FLAG_KEYS: list[str] = [f"flag-{i:03d}" for i in range(1, 16)]
EVENT_TYPES: list[str] = ["page_view", "click", "conversion"]
USER_POOL_SIZE: int = 50_000  # Larger pool to avoid hot-user cache effects during spike


def _random_user_id() -> str:
    """Return a random user ID from the synthetic pool."""
    return f"user_{random.randint(1, USER_POOL_SIZE)}"


# ---------------------------------------------------------------------------
# Spike test shape
# ---------------------------------------------------------------------------


class SpikeTestShape(LoadTestShape):
    """
    Four-stage spike load profile.

    Each stage entry defines:
    - duration: Cumulative elapsed seconds at which the stage ends
    - users: Target concurrent user count for this stage
    - spawn_rate: Users per second to add/remove when transitioning to this stage
    """

    stages: list[dict[str, int]] = [
        {"duration": 30, "users": 10, "spawn_rate": 10},  # Baseline
        {"duration": 60, "users": 1000, "spawn_rate": 100},  # Spike ramp
        {"duration": 90, "users": 1000, "spawn_rate": 1},  # Sustain peak
        {"duration": 120, "users": 10, "spawn_rate": 100},  # Recovery
    ]

    def tick(self) -> tuple[int, int] | None:
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
# Spike user — mixed tracking and API traffic
# ---------------------------------------------------------------------------


class SpikeUser(HttpUser):
    """
    Mixed traffic user for spike testing.

    Uses a balanced task mix to stress all major endpoints simultaneously
    during the traffic burst. Short wait time to maximise RPS per user.
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

        Highest weight — event tracking is the most critical path under spike.
        """
        payload = {
            "experiment_key": random.choice(EXPERIMENT_KEYS),
            "user_id": _random_user_id(),
            "event_type": random.choice(EVENT_TYPES),
            "value": round(random.uniform(0.0, 100.0), 2),
            "metadata": {"source": "spike_test", "session_id": str(uuid.uuid4())},
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

        Assignment calls spike alongside tracking during traffic bursts.
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

        Server-side flag evaluation — frequently called on request path.
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

        Dashboard traffic — lower priority but must not degrade under spike.
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

        Monitors system availability during the spike — must stay fast.
        """
        self.client.get(
            "/health",
            name="/health",
            catch_response=True,
        )
