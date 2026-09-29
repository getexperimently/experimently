"""Which database refusals the experiment create answers as "key taken" (409).

Only a unique violation on the experiments key index counts, and the index
name follows the schema, so the match must hold for every schema the code
runs under: a deployment, CI's integration schema and the core build's.
"""

from types import SimpleNamespace

import pytest

from backend.app.api.v1.endpoints.experiments import is_experiment_key_conflict

pytestmark = [pytest.mark.unit, pytest.mark.regression]

SCHEMAS = ["experimentation", "test_experimentation", "core_build_4242"]


def _refusal(pgcode, schema, table, constraint, with_diag=True):
    diag = SimpleNamespace(
        schema_name=schema, table_name=table, constraint_name=constraint
    )
    orig = SimpleNamespace(pgcode=pgcode)
    if with_diag:
        orig.diag = diag
    return SimpleNamespace(orig=orig)


@pytest.mark.parametrize("schema", SCHEMAS)
def test_the_key_index_is_recognised_under_every_schema(schema):
    exc = _refusal("23505", schema, "experiments", f"ix_{schema}_experiments_key")
    assert is_experiment_key_conflict(exc) is True


@pytest.mark.parametrize("schema", SCHEMAS)
@pytest.mark.parametrize(
    "pgcode,table,constraint",
    [
        ("23505", "metrics", "{s}_metric_experiment_name"),
        ("23505", "experiments", "experiments_pkey"),
        ("23505", "experiments", "ix_other_schema_experiments_key"),
        ("23503", "experiments", "ix_{s}_experiments_key"),
    ],
)
def test_other_refusals_are_not_a_key_conflict(schema, pgcode, table, constraint):
    exc = _refusal(pgcode, schema, table, constraint.format(s=schema))
    assert is_experiment_key_conflict(exc) is False


def test_a_refusal_without_diagnostics_is_not_a_key_conflict():
    exc = _refusal(
        "23505",
        "experimentation",
        "experiments",
        "ix_experimentation_experiments_key",
        with_diag=False,
    )
    assert is_experiment_key_conflict(exc) is False


def test_an_error_without_a_driver_cause_is_not_a_key_conflict():
    assert is_experiment_key_conflict(SimpleNamespace(orig=None)) is False
    assert is_experiment_key_conflict(RuntimeError("x")) is False
