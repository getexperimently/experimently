"""
CRUD operations load test for the experimentation platform.

Tests the performance of create, read, update, and delete operations across
experiments and feature flags under concurrent load.

Two user classes simulate realistic dashboard traffic patterns:
- CrudWriteUser (weight 6): Write-heavy traffic — create, update, delete operations
- CrudReadUser (weight 4): Read-heavy traffic — list, get, and results queries

The 60/40 write/read split reflects admin dashboard usage where operators
actively manage experiments and feature flags while monitoring results.

Both sign in as the seeded developer (see ``common.py``). A writer changes and
deletes only experiments and flags it created itself; results are read from
the seeded ACTIVE experiment, because a DRAFT experiment has none.

Usage (headless CI):
    locust -f crud_load_test.py --headless --users 100 --spawn-rate 10 \
           --run-time 60s --host http://localhost:8000 \
           --csv /tmp/locust_crud

Usage (interactive web UI):
    locust -f crud_load_test.py --host http://localhost:8000
    # Then open http://localhost:8089 in your browser
"""

import random
import uuid

from locust import HttpUser, between, events, task
from locust.env import Environment

from backend.tests.performance.locustfiles.common import (
    expect,
    login,
    seeded_experiment_id,
)

# The PERFORMANCE_TARGETS this file exercises. run_load_tests.py fails the run
# unless Locust recorded requests for every one of them.
TARGETS = (
    "create_experiment",
    "update_experiment",
    "delete_experiment",
    "create_feature_flag",
    "update_feature_flag",
    "bulk_flag_toggle",
    "list_experiments",
    "get_experiment_results",
)

# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

# Experiment types for realistic payloads
EXPERIMENT_TYPES: list[str] = ["a_b", "mv"]


def _experiment_payload() -> dict:
    """A valid ExperimentCreate body: two variants and a primary metric."""
    exp_key = f"load-test-exp-{uuid.uuid4().hex[:8]}"
    return {
        "name": f"Load Test Experiment {exp_key}",
        "key": exp_key,
        "description": "Experiment created during CRUD load test",
        "experiment_type": random.choice(EXPERIMENT_TYPES),
        "variants": [
            {"name": "control", "is_control": True, "traffic_allocation": 50},
            {"name": "treatment", "traffic_allocation": 50},
        ],
        "metrics": [{"name": "Purchase", "event_name": "purchase", "is_primary": True}],
    }


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
    - update_experiment (weight 2): Moderate — updating draft experiments
    - delete_experiment (weight 1): Rare — removing draft experiments
    - create_feature_flag (weight 3): Frequent — new feature flags
    - update_feature_flag (weight 2): Moderate — adjusting flag configuration
    - bulk_flag_toggle (weight 1): Rare — toggling multiple flags at once
    """

    weight = 6
    wait_time = between(0.5, 2.0)

    def on_start(self) -> None:
        """Sign in, and create one experiment and one flag to change."""
        self.auth_headers: dict[str, str] = login(self.client)
        self.experiment_ids: list[str] = []
        self.flag_ids: list[str] = []
        self.create_experiment()
        self.create_feature_flag()

    @task(3)
    def create_experiment(self) -> None:
        """
        POST /api/v1/experiments

        Creates a new DRAFT experiment with two variants and a primary metric.
        Weight 3 — most common write operation.
        """
        with self.client.post(
            "/api/v1/experiments/",
            json=_experiment_payload(),
            headers=self.auth_headers,
            name="/api/v1/experiments",
            catch_response=True,
        ) as response:
            if expect(response, 201):
                self.experiment_ids.append(response.json()["id"])

    @task(2)
    def update_experiment(self) -> None:
        """
        PUT /api/v1/experiments/{experiment_id}

        Updates one of this user's draft experiments with a partial payload.
        Weight 2 — moderately frequent as operators adjust parameters.
        """
        if not self.experiment_ids:
            self.create_experiment()
            if not self.experiment_ids:
                return
        experiment_id = random.choice(self.experiment_ids)
        payload = {
            "name": f"Updated Experiment {random.randint(1, 1000)}",
            "description": "Updated during CRUD load test",
        }
        with self.client.put(
            f"/api/v1/experiments/{experiment_id}",
            json=payload,
            headers=self.auth_headers,
            name="/api/v1/experiments/{experiment_id}",
            catch_response=True,
        ) as response:
            expect(response, 200)

    @task(1)
    def delete_experiment(self) -> None:
        """
        DELETE /api/v1/experiments/{experiment_id}

        Deletes one of this user's draft experiments; the API asks for the ID
        again as ``experiment_key`` to confirm. Weight 1 — rare operation.
        """
        if not self.experiment_ids:
            self.create_experiment()
            if not self.experiment_ids:
                return
        experiment_id = self.experiment_ids.pop()
        with self.client.delete(
            f"/api/v1/experiments/{experiment_id}",
            params={"experiment_key": experiment_id},
            headers=self.auth_headers,
            name="/api/v1/experiments/{experiment_id}",
            catch_response=True,
        ) as response:
            expect(response, 204)

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
            "rollout_percentage": random.randint(0, 100),
        }
        with self.client.post(
            "/api/v1/feature-flags/",
            json=payload,
            headers=self.auth_headers,
            name="/api/v1/feature-flags",
            catch_response=True,
        ) as response:
            if expect(response, 201):
                self.flag_ids.append(response.json()["id"])

    @task(2)
    def update_feature_flag(self) -> None:
        """
        PUT /api/v1/feature-flags/{flag_id}

        Updates one of this user's feature flags.
        Weight 2 — moderate frequency as operators tune rollout parameters.
        """
        if not self.flag_ids:
            self.create_feature_flag()
            if not self.flag_ids:
                return
        payload = {
            "description": "Updated during CRUD load test",
            "rollout_percentage": random.randint(0, 100),
        }
        with self.client.put(
            f"/api/v1/feature-flags/{random.choice(self.flag_ids)}",
            json=payload,
            headers=self.auth_headers,
            name="/api/v1/feature-flags/{flag_id}",
            catch_response=True,
        ) as response:
            expect(response, 200)

    @task(1)
    def bulk_flag_toggle(self) -> None:
        """
        POST /api/v1/feature-flags/bulk-toggle

        Enables or disables several of this user's flags in one request.
        Weight 1 — rare batch operation for emergency or deployment scenarios.
        The endpoint answers 200 even when some flags fail, so the body's
        ``failed`` count is part of the verdict.
        """
        if not self.flag_ids:
            self.create_feature_flag()
            if not self.flag_ids:
                return
        selected = random.sample(
            self.flag_ids, min(random.randint(2, 5), len(self.flag_ids))
        )
        payload = {
            "flag_ids": selected,
            "action": random.choice(["enable", "disable"]),
        }
        with self.client.post(
            "/api/v1/feature-flags/bulk-toggle",
            json=payload,
            headers=self.auth_headers,
            name="/api/v1/feature-flags/bulk-toggle",
            catch_response=True,
        ) as response:
            if expect(response, 200):
                failed = (response.json() or {}).get("failed", 0)
                if failed:
                    response.failure(f"{failed} of {len(selected)} flags not toggled")


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
        """Sign in, and find the seeded experiment to read."""
        self.auth_headers: dict[str, str] = login(self.client)
        self.experiment_id: str = seeded_experiment_id(self.client, self.auth_headers)

    @task(4)
    def list_experiments(self) -> None:
        """
        GET /api/v1/experiments

        Lists experiments with random pagination parameters.
        Weight 4 — most frequent read, dashboard landing page polling.
        """
        with self.client.get(
            "/api/v1/experiments/",
            params={
                "skip": random.randint(0, 4) * 20,
                "limit": random.choice([10, 20, 50]),
            },
            headers=self.auth_headers,
            name="/api/v1/experiments",
            catch_response=True,
        ) as response:
            expect(response, 200)

    @task(3)
    def get_experiment(self) -> None:
        """
        GET /api/v1/experiments/{experiment_id}

        Retrieves the seeded experiment by ID.
        Weight 3 — frequent when operators drill into experiment details.
        """
        with self.client.get(
            f"/api/v1/experiments/{self.experiment_id}",
            headers=self.auth_headers,
            name="/api/v1/experiments/{experiment_id}",
            catch_response=True,
        ) as response:
            expect(response, 200)

    @task(3)
    def list_feature_flags(self) -> None:
        """
        GET /api/v1/feature-flags

        Lists all feature flags.
        Weight 3 — frequent dashboard operation for flag management.
        """
        with self.client.get(
            "/api/v1/feature-flags/",
            headers=self.auth_headers,
            name="/api/v1/feature-flags",
            catch_response=True,
        ) as response:
            expect(response, 200)

    @task(2)
    def get_experiment_results(self) -> None:
        """
        GET /api/v1/experiments/{experiment_id}/results

        Retrieves the seeded experiment's results — involves complex database
        queries with joins across experiment, variant, and metrics tables.
        Weight 2 — moderate frequency as analysts check outcomes.
        """
        with self.client.get(
            f"/api/v1/experiments/{self.experiment_id}/results",
            headers=self.auth_headers,
            name="/api/v1/experiments/{experiment_id}/results",
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
    print("CRUD LOAD TEST COMPLETED")
    print("=" * 60)
    print(f"Total requests : {total_requests}")
    print(f"Total failures : {total_failures} ({failure_rate:.2f}%)")
    print(f"RPS (avg)      : {stats.total.current_rps:.1f}")
    print("=" * 60)
