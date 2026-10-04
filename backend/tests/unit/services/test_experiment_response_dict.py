"""`ExperimentService._experiment_to_dict` copies every column that
`ExperimentResponse` would otherwise fill with a default (issue #197)."""

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from backend.app.models.experiment import Experiment, ExperimentStatus
from backend.app.schemas.experiment import ExperimentResponse
from backend.app.services.experiment_service import ExperimentService


def _experiment(**overrides) -> Experiment:
    now = datetime.now(timezone.utc)
    fields = {
        "id": uuid.uuid4(),
        "name": "Bandit",
        "experiment_type": "a_b",
        "status": ExperimentStatus.DRAFT,
        "owner_id": uuid.uuid4(),
        "created_at": now,
        "updated_at": now,
        "optimization_type": "fixed",
        "sequential_testing_enabled": False,
        # NOT NULL with a server default: every stored row has both (#580).
        "correction_method": "benjamini_hochberg",
        "confidence_level": 0.95,
    }
    fields.update(overrides)
    return Experiment(**fields)


@pytest.mark.unit
@pytest.mark.regression
@pytest.mark.parametrize("algorithm", ["thompson_sampling", "ucb1", "epsilon_greedy"])
def test_bandit_optimization_type_reaches_the_response(algorithm):
    data = ExperimentService(MagicMock())._experiment_to_dict(
        _experiment(optimization_type=algorithm)
    )
    assert ExperimentResponse(**data).optimization_type.value == algorithm


@pytest.mark.unit
@pytest.mark.regression
def test_other_defaulted_columns_reach_the_response():
    group_id = uuid.uuid4()
    data = ExperimentService(MagicMock())._experiment_to_dict(
        _experiment(
            sequential_testing_enabled=True,
            sequential_testing_method="msprt",
            sequential_testing_config={"alpha": 0.05},
            variance_reduction_config={"enabled": True},
            mutual_exclusion_group_id=group_id,
        )
    )
    response = ExperimentResponse(**data)
    assert response.sequential_testing_enabled is True
    assert response.sequential_testing_method == "msprt"
    assert response.sequential_testing_config == {"alpha": 0.05}
    assert response.variance_reduction_config == {"enabled": True}
    assert response.mutual_exclusion_group_id == group_id


@pytest.mark.unit
def test_an_unset_type_reads_as_fixed():
    data = ExperimentService(MagicMock())._experiment_to_dict(
        _experiment(optimization_type=None, sequential_testing_enabled=None)
    )
    response = ExperimentResponse(**data)
    assert response.optimization_type.value == "fixed"
    assert response.sequential_testing_enabled is False


@pytest.mark.unit
@pytest.mark.regression
def test_the_stored_correction_settings_reach_the_response():
    """#580: neither value is the response default, so a dict that left them
    out would report Benjamini-Hochberg at 0.95 over a stored choice, and the
    dashboard would send that back to the results."""
    data = ExperimentService(MagicMock())._experiment_to_dict(
        _experiment(correction_method="none", confidence_level=0.90)
    )
    response = ExperimentResponse(**data)
    assert response.correction_method.value == "none"
    assert response.confidence_level == 0.90
