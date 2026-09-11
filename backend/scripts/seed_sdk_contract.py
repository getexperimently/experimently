#!/usr/bin/env python3
"""
Seed the fixtures used by the live SDK contract tests.

Creates (idempotently):
- the demo users (admin@demo.com owns everything),
- an ACTIVE A/B experiment with public key ``sdk_contract_ab`` (variants
  ``control`` / ``treatment`` at 50/50, primary metric ``purchase``),
- an ACTIVE feature flag ``sdk_contract_flag`` at 100% rollout,
- an API key named ``sdk-contract-smoke`` whose plaintext is written to
  ``tests/sdk-contract/live/.api_key`` (0600, gitignored).

Then run ``python tests/sdk-contract/live/run_live_contract.py`` against a
backend pointed at the same database.

Usage:
    source venv/bin/activate
    python backend/scripts/seed_sdk_contract.py [--reset]

Environment: the same POSTGRES_* variables as the other seed scripts.
``SDK_CONTRACT_API_KEY`` fixes the plaintext key (otherwise one is generated).
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import timedelta
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("POSTGRES_SERVER", "localhost")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "experimentation")
os.environ.setdefault("POSTGRES_SCHEMA", "experimentation")

from backend.scripts.seed_demo_data import (  # noqa: E402
    ensure_schema,
    ensure_tables,
    now_utc,
    seed_users,
)

from backend.app.core.security import hash_api_key  # noqa: E402
from backend.app.db.session import SessionLocal  # noqa: E402
from backend.app.models.api_key import APIKey, generate_api_key  # noqa: E402
from backend.app.models.assignment import Assignment  # noqa: E402
from backend.app.models.event import Event  # noqa: E402
from backend.app.models.experiment import (  # noqa: E402
    Experiment,
    ExperimentStatus,
    ExperimentType,
    Metric,
    MetricType,
    Variant,
)
from backend.app.models.feature_flag import FeatureFlag, FeatureFlagStatus  # noqa: E402

EXPERIMENT_KEY = "sdk_contract_ab"
FLAG_KEY = "sdk_contract_flag"
API_KEY_NAME = "sdk-contract-smoke"
KEY_FILE = PROJECT_ROOT / "tests" / "sdk-contract" / "live" / ".api_key"


def seed_experiment(db, admin_user) -> Experiment:
    existing = db.query(Experiment).filter(Experiment.key == EXPERIMENT_KEY).first()
    if existing:
        print(f"  Experiment '{EXPERIMENT_KEY}' already exists (id={existing.id}).")
        return existing

    exp = Experiment(
        key=EXPERIMENT_KEY,
        name="SDK contract A/B",
        description="Fixture for the live SDK contract tests.",
        hypothesis="Every SDK reaches the same sticky assignment through /tracking/assign.",
        status=ExperimentStatus.ACTIVE,
        experiment_type=ExperimentType.A_B,
        owner_id=admin_user.id,
        start_date=now_utc() - timedelta(days=1),
        end_date=now_utc() + timedelta(days=365),
        targeting_rules={},
        metrics={"primary_metric": "purchase", "metric_type": "conversion"},
        tags=["sdk-contract"],
    )
    db.add(exp)
    db.flush()
    db.add_all(
        [
            Variant(
                experiment_id=exp.id,
                name="control",
                description="Control",
                is_control=True,
                traffic_allocation=50,
                configuration={"color": "blue"},
            ),
            Variant(
                experiment_id=exp.id,
                name="treatment",
                description="Treatment",
                is_control=False,
                traffic_allocation=50,
                configuration={"color": "green"},
            ),
            Metric(
                experiment_id=exp.id,
                name="Purchase",
                event_name="purchase",
                metric_type=MetricType.CONVERSION,
                is_primary=True,
                minimum_sample_size=100,
            ),
        ]
    )
    db.commit()
    db.refresh(exp)
    print(f"  Created experiment '{EXPERIMENT_KEY}' (id={exp.id}).")
    return exp


def seed_flag(db, admin_user) -> FeatureFlag:
    existing = db.query(FeatureFlag).filter(FeatureFlag.key == FLAG_KEY).first()
    if existing:
        print(f"  Flag '{FLAG_KEY}' already exists (id={existing.id}).")
        return existing

    flag = FeatureFlag(
        key=FLAG_KEY,
        name="SDK contract flag",
        description="Always-on fixture for the live SDK contract tests.",
        status=FeatureFlagStatus.ACTIVE,
        owner_id=admin_user.id,
        rollout_percentage=100,
        targeting_rules={},
        tags=["sdk-contract"],
    )
    db.add(flag)
    db.commit()
    db.refresh(flag)
    print(f"  Created flag '{FLAG_KEY}' at 100% (id={flag.id}).")
    return flag


def seed_api_key(db, admin_user) -> str:
    existing = (
        db.query(APIKey)
        .filter(APIKey.name == API_KEY_NAME, APIKey.user_id == admin_user.id)
        .first()
    )
    if existing is not None and KEY_FILE.exists():
        plaintext = KEY_FILE.read_text().strip()
        if plaintext and hash_api_key(plaintext) == existing.key:
            print(f"  API key kept ({KEY_FILE.relative_to(PROJECT_ROOT)}).")
            return plaintext
        print("  Key file does not match the stored hash; rotating.")
    if existing is not None:
        db.delete(existing)
        db.commit()

    plaintext = os.environ.get("SDK_CONTRACT_API_KEY") or generate_api_key()
    db.add(
        APIKey(
            user_id=admin_user.id,
            key=hash_api_key(plaintext),
            name=API_KEY_NAME,
            description="Live SDK contract tests",
            scopes="read,write",
            is_active=True,
        )
    )
    db.commit()
    KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    KEY_FILE.write_text(plaintext + "\n")
    os.chmod(KEY_FILE, 0o600)
    print(f"  Created API key, written to {KEY_FILE.relative_to(PROJECT_ROOT)}.")
    return plaintext


def reset(db) -> None:
    exp = db.query(Experiment).filter(Experiment.key == EXPERIMENT_KEY).first()
    if exp:
        db.query(Event).filter(Event.experiment_id == exp.id).delete()
        db.query(Assignment).filter(Assignment.experiment_id == exp.id).delete()
        db.query(Metric).filter(Metric.experiment_id == exp.id).delete()
        db.query(Variant).filter(Variant.experiment_id == exp.id).delete()
        db.delete(exp)
    flag = db.query(FeatureFlag).filter(FeatureFlag.key == FLAG_KEY).first()
    if flag:
        db.query(Event).filter(Event.feature_flag_id == flag.id).delete()
        db.delete(flag)
    db.query(APIKey).filter(APIKey.name == API_KEY_NAME).delete()
    db.commit()
    if KEY_FILE.exists():
        KEY_FILE.unlink()
    print("  Removed the SDK contract experiment, flag, API key and key file.")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Seed the live SDK contract fixtures.")
    parser.add_argument("--reset", action="store_true", help="remove everything this script created")
    args = parser.parse_args(argv)

    print("SDK contract seed")
    with SessionLocal() as db:
        ensure_schema(db)  # the schema must exist before create_all
    ensure_tables()
    with SessionLocal() as db:
        if args.reset:
            reset(db)
            return 0
        users = seed_users(db)
        admin = users["admin@demo.com"]
        seed_experiment(db, admin)
        seed_flag(db, admin)
        seed_api_key(db, admin)
    print("Done. Run: python tests/sdk-contract/live/run_live_contract.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
