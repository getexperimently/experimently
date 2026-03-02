"""
CRUD operations load test for the experimentation platform.

Tests the performance of create, read, update, and delete operations across
experiments and feature flags under concurrent load.

Two user classes simulate realistic dashboard traffic patterns:
- CrudWriteUser (weight 6): Write-heavy traffic — create, update, delete operations
- CrudReadUser (weight 4): Read-heavy traffic — list, get, and results queries

The 60/40 write/read split reflects admin dashboard usage where operators
actively manage experiments and feature flags while monitoring results.

Usage (headless CI):
    locust -f crud_load_test.py --headless --users 100 --spawn-rate 10 \
           --run-time 60s --host http://localhost:8000 \
           --csv /tmp/locust_crud

Usage (interactive web UI):
    locust -f crud_load_test.py --host http://localhost:8000
    # Then open http://localhost:8089 in your browser
"""
import os
import random
import uuid

from locust import HttpUser, task, between, events
from locust.env import Environment

# ---------------------------------------------------------------------------
# Test data — deterministic fake IDs used across all virtual users
# ---------------------------------------------------------------------------

# Fixed UUID namespace for deterministic ID generation via uuid5
_UUID_NAMESPACE: uuid.UUID = uuid.UUID("12345678-1234-5678-1234-567812345678")

# 20 experiment keys for CRUD operations
EXPERIMENT_KEYS: list[str] = [f"experiment-key-{i:04d}" for i in range(1, 21)]

# 20 deterministic experiment UUIDs (uuid5 for reproducibility across runs)
EXPERIMENT_IDS: list[str] = [
    str(uuid.uuid5(_UUID_NAMESPACE, f"experiment-{i}")) for i in range(1, 21)
]

# 15 feature flag keys
FEATURE_FLAG_KEYS: list[str] = [f"flag-{i:03d}" for i in range(1, 16)]

# 15 deterministic feature flag UUIDs
FEATURE_FLAG_IDS: list[str] = [
    str(uuid.uuid5(_UUID_NAMESPACE, f"flag-{i}")) for i in range(1, 16)
]

# User pool — 10,000 synthetic user IDs
USER_POOL_SIZE: int = 10_000

# Experiment types for realistic payloads
EXPERIMENT_TYPES: list[str] = ["ab_test", "multivariate"]

# Feature flag types
FLAG_TYPES: list[str] = ["boolean", "percentage", "variant"]


def _random_user_id() -> str:
    """Generate a random user ID from the synthetic user pool."""
    return f"user_{random.randint(1, USER_POOL_SIZE)}"


# ---------------------------------------------------------------------------
# CrudWriteUser — 60% of virtual users, write-heavy CRUD operations
# ---------------------------------------------------------------------------


class CrudWriteUser(HttpUser):
    """
    Simulates write-heavy dashboard traffic (60% of total load).

    This user class represents platform operators creating, updating, and
    deleting experiments and feature flags. Tasks are weighted to reflect
    realistic admin activity patterns:
    - create_experiment (weight 3): Most common write — new experiments
    - update_experiment (weight 2): Moderate — updating active experiments
    - delete_experiment (weight 1): Rare — removing draft experiments
    - create_feature_flag (weight 3): Frequent — new feature flags
    - update_feature_flag (weight 2): Moderate — adjusting flag configuration
    - bulk_flag_toggle (weight 1): Rare — toggling multiple flags at once
    """

    weight = 6
    wait_time = between(0.5, 2.0)

    def on_start(self) -> None:
        """Set up authentication headers for write operations."""
        self.api_key: str = os.environ.get("LOAD_TEST_API_KEY", "test-api-key")
        self.auth_headers: dict[str, str] = {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
            "Authorization": f"Bearer {os.environ.get('LOAD_TEST_AUTH_TOKEN', 'test-bearer-token')}",
        }

    @task(3)
    def create_experiment(self) -> None:
        """
        POST /api/v1/experiments

        Creates a new experiment with realistic payload including variants
        and traffic allocation. Weight 3 — most common write operation.
        """
        exp_key = f"load-test-exp-{uuid.uuid4().hex[:8]}"
        payload = {
            "name": f"Load Test Experiment {exp_key}",
            "description": "Experiment created during CRUD load test",
            "experiment_type": random.choice(EXPERIMENT_TYPES),
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
            headers=self.auth_headers,
            name="/api/v1/experiments",
            catch_response=True,
        )

    @task(2)
    def update_experiment(self) -> None:
        """
        PUT /api/v1/experiments/{experiment_id}

        Updates an existing experiment with a partial payload.
        Weight 2 — moderately frequent as operators adjust parameters.
        """
        experiment_id = random.choice(EXPERIMENT_IDS)
        payload = {
            "name": f"Updated Experiment {random.randint(1, 1000)}",
            "description": "Updated during CRUD load test",
            "traffic_allocation": round(random.uniform(0.1, 1.0), 2),
        }
        self.client.put(
            f"/api/v1/experiments/{experiment_id}",
            json=payload,
            headers=self.auth_headers,
            name="/api/v1/experiments/{experiment_id}",
            catch_response=True,
        )

    @task(1)
    def delete_experiment(self) -> None:
        """
        DELETE /api/v1/experiments/{experiment_id}

        Deletes a draft experiment. Weight 1 — rare operation, only
        applicable to experiments in DRAFT status.
        """
        experiment_id = random.choice(EXPERIMENT_IDS)
        self.client.delete(
            f"/api/v1/experiments/{experiment_id}",
            headers=self.auth_headers,
            name="/api/v1/experiments/{experiment_id}",
            catch_response=True,
        )

    @task(3)
    def create_feature_flag(self) -> None:
        """
        POST /api/v1/feature-flags

        Creates a new feature flag with realistic configuration.
        Weight 3 — frequent operation, flags are created alongside experiments.
        """
        flag_key = f"load-test-flag-{uuid.uuid4().hex[:8]}"
        payload = {
            "key": flag_key,
            "name": f"Load Test Flag {flag_key}",
            "description": "Feature flag created during CRUD load test",
            "flag_type": random.choice(FLAG_TYPES),
            "enabled": random.choice([True, False]),
            "rollout_percentage": random.randint(0, 100),
        }
        self.client.post(
            "/api/v1/feature-flags",
            json=payload,
            headers=self.auth_headers,
            name="/api/v1/feature-flags",
            catch_response=True,
        )

    @task(2)
    def update_feature_flag(self) -> None:
        """
        PUT /api/v1/feature-flags/{flag_id}

        Updates an existing feature flag with adjusted configuration.
        Weight 2 — moderate frequency as operators tune rollout parameters.
        """
        flag_id = random.choice(FEATURE_FLAG_IDS)
        payload = {
            "name": f"Updated Flag {random.randint(1, 1000)}",
            "description": "Updated during CRUD load test",
            "enabled": random.choice([True, False]),
            "rollout_percentage": random.randint(0, 100),
        }
        self.client.put(
            f"/api/v1/feature-flags/{flag_id}",
            json=payload,
            headers=self.auth_headers,
            name="/api/v1/feature-flags/{flag_id}",
            catch_response=True,
        )

    @task(1)
    def bulk_flag_toggle(self) -> None:
        """
        POST /api/v1/feature-flags/bulk-toggle

        Toggles multiple feature flags in a single request.
        Weight 1 — rare batch operation for emergency or deployment scenarios.
        """
        # Select a random subset of flag IDs to toggle
        num_flags = random.randint(2, 5)
        selected_flags = random.sample(FEATURE_FLAG_IDS, min(num_flags, len(FEATURE_FLAG_IDS)))
        payload = {
            "flag_ids": selected_flags,
            "enabled": random.choice([True, False]),
        }
        self.client.post(
            "/api/v1/feature-flags/bulk-toggle",
            json=payload,
            headers=self.auth_headers,
            name="/api/v1/feature-flags/bulk-toggle",
            catch_response=True,
        )


# ---------------------------------------------------------------------------
# CrudReadUser — 40% of virtual users, read-heavy dashboard operations
# ---------------------------------------------------------------------------


class CrudReadUser(HttpUser):
    """
    Simulates read-heavy dashboard traffic (40% of total load).

    This user class represents dashboard users browsing experiments,
    viewing details, and checking results. Tasks are weighted to reflect
    typical dashboard browsing patterns:
    - list_experiments (weight 4): Most common — dashboard landing page
    - get_experiment (weight 3): Frequent — viewing experiment details
    - list_feature_flags (weight 3): Frequent — flag management page
    - get_experiment_results (weight 2): Moderate — checking experiment outcomes
    """

    weight = 4
    wait_time = between(0.5, 2.0)

    def on_start(self) -> None:
        """Set up authentication headers for read operations."""
        self.api_key: str = os.environ.get("LOAD_TEST_API_KEY", "test-api-key")
        self.auth_headers: dict[str, str] = {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
            "Authorization": f"Bearer {os.environ.get('LOAD_TEST_AUTH_TOKEN', 'test-bearer-token')}",
        }

    @task(4)
    def list_experiments(self) -> None:
        """
        GET /api/v1/experiments

        Lists experiments with random pagination parameters.
        Weight 4 — most frequent read, dashboard landing page polling.
        """
        page = random.randint(1, 5)
        per_page = random.choice([10, 20, 50])
        self.client.get(
            "/api/v1/experiments",
            params={"page": page, "per_page": per_page},
            headers=self.auth_headers,
            name="/api/v1/experiments",
            catch_response=True,
        )

    @task(3)
    def get_experiment(self) -> None:
        """
        GET /api/v1/experiments/{experiment_id}

        Retrieves a specific experiment by ID.
        Weight 3 — frequent when operators drill into experiment details.
        """
        experiment_id = random.choice(EXPERIMENT_IDS)
        self.client.get(
            f"/api/v1/experiments/{experiment_id}",
            headers=self.auth_headers,
            name="/api/v1/experiments/{experiment_id}",
            catch_response=True,
        )

    @task(3)
    def list_feature_flags(self) -> None:
        """
        GET /api/v1/feature-flags

        Lists all feature flags.
        Weight 3 — frequent dashboard operation for flag management.
        """
        self.client.get(
            "/api/v1/feature-flags",
            headers=self.auth_headers,
            name="/api/v1/feature-flags",
            catch_response=True,
        )

    @task(2)
    def get_experiment_results(self) -> None:
        """
        GET /api/v1/experiments/{experiment_id}/results

        Retrieves experiment results — involves complex database queries
        with joins across experiment, variant, and metrics tables.
        Weight 2 — moderate frequency as analysts check outcomes.
        """
        experiment_id = random.choice(EXPERIMENT_IDS)
        self.client.get(
            f"/api/v1/experiments/{experiment_id}/results",
            headers=self.auth_headers,
            name="/api/v1/experiments/{experiment_id}/results",
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
    print("CRUD LOAD TEST COMPLETED")
    print("=" * 60)
    print(f"Total requests : {total_requests}")
    print(f"Total failures : {total_failures} ({failure_rate:.2f}%)")
    print(f"RPS (avg)      : {stats.total.current_rps:.1f}")
    print("=" * 60)
