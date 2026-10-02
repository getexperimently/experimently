"""A create without a ``key`` retries only a taken generated key (#388).

The integration suite proves the retry against Postgres (a real savepoint and
the real key index). This pins which refusals are retried: a unique conflict
on the key index is, a bounded number of times; anything else is raised on
the first attempt, because another key cannot cure it.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import IntegrityError

from backend.app.models.experiment import Experiment
from backend.app.services import experiment_service as svc_module
from backend.app.services.experiment_service import ExperimentService

pytestmark = [pytest.mark.unit, pytest.mark.regression]


def _refusal(constraint: str) -> IntegrityError:
    diag = SimpleNamespace(
        schema_name="experimentation",
        table_name="experiments",
        constraint_name=constraint,
    )
    return IntegrityError("INSERT", {}, SimpleNamespace(pgcode="23505", diag=diag))


KEY_TAKEN = "ix_experimentation_experiments_key"


def _service(monkeypatch, flush_effects):
    db = MagicMock()
    db.flush.side_effect = flush_effects
    keys = iter(f"generated-{i}" for i in range(100))
    calls: list[str] = []

    def gen(name: str) -> str:
        key = next(keys)
        calls.append(key)
        return key

    monkeypatch.setattr(ExperimentService, "generate_key", staticmethod(gen))
    return ExperimentService(db), db, calls


def test_a_taken_generated_key_is_replaced(monkeypatch):
    service, db, calls = _service(monkeypatch, [_refusal(KEY_TAKEN), None])
    experiment = Experiment(name="Retry me")

    service._insert_with_generated_key(experiment)

    assert calls == ["generated-0", "generated-1"]
    assert experiment.key == "generated-1"
    assert db.begin_nested.call_count == 2


def test_the_retry_is_bounded(monkeypatch):
    service, _, calls = _service(monkeypatch, [_refusal(KEY_TAKEN)] * 10)

    with pytest.raises(IntegrityError):
        service._insert_with_generated_key(Experiment(name="Always taken"))

    assert len(calls) == svc_module.KEY_GENERATION_ATTEMPTS


def test_another_refusal_is_not_retried(monkeypatch):
    service, _, calls = _service(monkeypatch, [_refusal("experiments_pkey"), None])

    with pytest.raises(IntegrityError):
        service._insert_with_generated_key(Experiment(name="Other refusal"))

    assert calls == ["generated-0"]


def test_a_caller_supplied_key_is_never_regenerated(monkeypatch):
    service, db, calls = _service(monkeypatch, [_refusal(KEY_TAKEN)])
    monkeypatch.setattr(svc_module, "_normalise_analysis_configs", lambda *a: None)

    with pytest.raises(IntegrityError):
        service.create_experiment(
            {"name": "Mine", "key": "chosen-key", "variants": [], "metrics": []},
            user_id="00000000-0000-0000-0000-000000000001",
        )

    assert calls == []
    db.begin_nested.assert_not_called()
