"""
Retention for the analysis history tables.

`record_snapshot` keeps at most one row per experiment, kind and day, which
bounds the request path. The bandit scheduler still writes one
`bandit_state_history` row per arm per tick (~288 a day per experiment at the
default cadence), so both tables need a purge; `purge_expired_history` is it,
and the metrics scheduler tick calls it.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backend.app.models.analysis_snapshot import AnalysisKind, AnalysisSnapshot
from backend.app.services.analysis_snapshot_service import (
    purge_expired_history,
    record_snapshot,
)


@pytest.fixture
def experiment(db_session, normal_user):
    from backend.app.models.experiment import Experiment, ExperimentStatus

    exp = Experiment(
        name=f"retention {uuid.uuid4().hex[:8]}",
        key=f"retention_{uuid.uuid4().hex[:8]}",
        description="retention test",
        hypothesis="old analysis rows are purged",
        status=ExperimentStatus.ACTIVE,
        owner_id=normal_user.id,
    )
    db_session.add(exp)
    db_session.commit()
    db_session.refresh(exp)
    yield exp
    db_session.query(AnalysisSnapshot).filter(
        AnalysisSnapshot.experiment_id == exp.id
    ).delete(synchronize_session=False)
    db_session.delete(exp)
    db_session.commit()


def _snapshot_days(db_session, experiment_id) -> list[datetime]:
    return [
        row.as_of
        for row in db_session.query(AnalysisSnapshot)
        .filter(AnalysisSnapshot.experiment_id == experiment_id)
        .order_by(AnalysisSnapshot.as_of)
        .all()
    ]


class TestPurgeExpiredHistory:
    def test_deletes_rows_older_than_the_window_and_keeps_newer(
        self, db_session, experiment
    ):
        now = datetime.now(timezone.utc)
        for age_days in (200, 120, 91, 89, 10, 0):
            record_snapshot(
                db_session,
                experiment.id,
                AnalysisKind.FREQUENTIST,
                {"age_days": age_days},
                as_of=now - timedelta(days=age_days),
            )
        db_session.commit()
        assert len(_snapshot_days(db_session, experiment.id)) == 6

        deleted = purge_expired_history(db_session, retention_days=90)

        # The purge is global, so other tests' rows can be in the count too;
        # what this asserts is that at least this experiment's three old rows
        # went, and that its three recent ones stayed.
        assert deleted["analysis_snapshots"] >= 3
        remaining = _snapshot_days(db_session, experiment.id)
        assert len(remaining) == 3
        cutoff = now - timedelta(days=90)
        assert all(row >= cutoff for row in remaining)

    def test_retention_zero_disables_the_purge(self, db_session, experiment):
        record_snapshot(
            db_session,
            experiment.id,
            AnalysisKind.FREQUENTIST,
            {"old": True},
            as_of=datetime.now(timezone.utc) - timedelta(days=999),
        )
        db_session.commit()

        assert purge_expired_history(db_session, retention_days=0) == {
            "analysis_snapshots": 0,
            "bandit_state_history": 0,
        }
        assert len(_snapshot_days(db_session, experiment.id)) == 1

    def test_purge_never_raises_on_a_broken_session(self):
        """Retention is best-effort: a bad session is logged, not raised."""
        from unittest.mock import MagicMock

        broken = MagicMock()
        broken.get_bind.side_effect = RuntimeError("no bind")
        assert purge_expired_history(broken, retention_days=30) == {
            "analysis_snapshots": 0,
            "bandit_state_history": 0,
        }

    def test_metrics_tick_runs_the_purge(self, monkeypatch):
        """The purge has to run somewhere; the metrics tick is where."""
        import asyncio

        from backend.app.core import metrics_scheduler as module

        called: list[bool] = []
        monkeypatch.setattr(
            "backend.app.services.analysis_snapshot_service.purge_expired_history",
            lambda *a, **k: called.append(True) or {},
        )
        monkeypatch.setattr(
            module.MetricsService,
            "aggregate_metrics",
            classmethod(lambda cls, **kwargs: []),
        )
        asyncio.run(module.metrics_scheduler.aggregate_metrics())
        assert called == [True]
