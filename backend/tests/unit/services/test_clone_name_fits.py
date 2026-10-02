"""A clone's name is cut to the limit the column sets, read from the column (#627).

The clone is named ``"Copy of <name>"``. A source name of 93 characters or more
made that longer than ``experiments.name`` (``String(100)``) and the insert
failed with a 500. The name is now cut to ``NAME_MAX``, which is read from the
column, so a change to the column's length moves the limit with it.

The same clone against a database, through the API, is in
``backend/tests/integration/api/test_clone_name_fits.py``.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from backend.app.models.experiment import (
    Experiment,
    ExperimentStatus,
    ExperimentType,
)
from backend.app.services import experiment_service
from backend.app.services.experiment_service import NAME_MAX, ExperimentService

pytestmark = pytest.mark.unit


def _clone_name(source_name: str) -> str:
    source = Experiment(
        id=uuid.uuid4(),
        name=source_name,
        description="d",
        hypothesis="h",
        experiment_type=ExperimentType.A_B,
        status=ExperimentStatus.COMPLETED,
        owner_id=uuid.uuid4(),
        tags=[],
    )
    source.variants = []
    source.metric_definitions = []
    db = MagicMock()
    service = ExperimentService(db)
    with patch.object(service, "_experiment_to_dict", return_value={}):
        service.clone_experiment(source, uuid.uuid4())
    clones = [
        c.args[0] for c in db.add.call_args_list if isinstance(c.args[0], Experiment)
    ]
    assert len(clones) == 1
    return clones[0].name


def test_the_name_limit_is_read_from_the_column():
    assert NAME_MAX == Experiment.__table__.c.name.type.length == 100


@pytest.mark.regression
def test_a_clone_of_a_full_length_name_is_cut_to_the_limit():
    source = "n" * NAME_MAX
    assert _clone_name(source) == ("Copy of " + source)[:NAME_MAX]


def test_the_clone_follows_the_limit_not_a_typed_number(monkeypatch):
    """Moving the limit moves the cut: the slice uses ``NAME_MAX``."""
    monkeypatch.setattr(experiment_service, "NAME_MAX", 20)
    assert _clone_name("n" * 50) == ("Copy of " + "n" * 50)[:20]


def test_a_short_name_is_left_whole():
    assert _clone_name("Checkout button") == "Copy of Checkout button"
