"""
DB-backed tests for ``services/analysis_snapshot_service.record_snapshot``.

Two properties the results endpoints depend on:

* **One row per experiment, kind and UTC day.**  ``GET /results/{id}`` writes a
  snapshot on every uncached request, so a dashboard polling every five seconds
  used to add ~17k full-JSON rows a day.  Repeated calls now refresh that day's
  row in place; the next day starts a new one.  The database enforces it with
  ``uq_analysis_snapshot_experiment_kind_as_of``.
* **The audit write owns no part of the caller's transaction.**  It runs in its
  own short-lived session, so a read endpoint cannot commit the pending
  ``experiment.bayesian_decision`` that ``AnalysisService`` merely flushed, and
  a failed snapshot cannot roll the caller's work back.

Rows created here are deleted in fixture teardown.
"""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from backend.app.core.stats_engine import ENGINE_VERSION
from backend.app.models.analysis_snapshot import AnalysisKind, AnalysisSnapshot
from backend.app.models.experiment import Experiment, ExperimentStatus
from backend.app.services.analysis_snapshot_service import (
    build_snapshot,
    record_snapshot,
    snapshot_day,
)


@pytest.fixture
def experiment(db_session, make_experiment):
    suffix = uuid.uuid4().hex[:8]
    exp = make_experiment(
        name=f"Snapshot service {suffix}",
        key=f"snapshot-service-{suffix}",
        status=ExperimentStatus.ACTIVE,
    )
    yield exp
    db_session.rollback()
    db_session.query(AnalysisSnapshot).filter(
        AnalysisSnapshot.experiment_id == exp.id
    ).delete(synchronize_session=False)
    db_session.commit()


def _rows(db_session, experiment_id, kind=None):
    db_session.expire_all()
    query = db_session.query(AnalysisSnapshot).filter(
        AnalysisSnapshot.experiment_id == experiment_id
    )
    if kind:
        query = query.filter(AnalysisSnapshot.kind == kind)
    return query.order_by(AnalysisSnapshot.as_of).all()


def _fresh_session(db_session):
    """A session on the same engine that sees only committed state."""
    return sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)()


@pytest.mark.integration
@pytest.mark.requires_db
class TestOneRowPerDay:
    def test_repeated_calls_in_one_day_update_one_row(self, db_session, experiment):
        as_of = datetime(2026, 9, 11, 8, 0, tzinfo=timezone.utc)

        for poll in range(5):
            record_snapshot(
                db_session,
                experiment.id,
                AnalysisKind.FREQUENTIST,
                {"poll": poll},
                as_of=as_of + timedelta(minutes=poll),
            )

        rows = _rows(db_session, experiment.id, "frequentist")
        assert len(rows) == 1
        # The row carries the latest payload...
        assert rows[0].payload == {"poll": 4}
        # ...stored against the UTC day, not the instant of any one request.
        assert rows[0].as_of == datetime(2026, 9, 11, tzinfo=timezone.utc)

    def test_next_day_starts_a_new_row(self, db_session, experiment):
        day_one = datetime(2026, 9, 11, 23, 30, tzinfo=timezone.utc)
        day_two = day_one + timedelta(hours=1)  # 00:30 the next UTC day

        record_snapshot(
            db_session, experiment.id, AnalysisKind.FREQUENTIST, {"d": 1}, as_of=day_one
        )
        record_snapshot(
            db_session, experiment.id, AnalysisKind.FREQUENTIST, {"d": 2}, as_of=day_two
        )

        rows = _rows(db_session, experiment.id, "frequentist")
        assert [r.payload["d"] for r in rows] == [1, 2]
        assert [r.as_of for r in rows] == [
            datetime(2026, 9, 11, tzinfo=timezone.utc),
            datetime(2026, 9, 12, tzinfo=timezone.utc),
        ]

    def test_kinds_do_not_share_a_row(self, db_session, experiment):
        as_of = datetime(2026, 9, 11, 12, tzinfo=timezone.utc)
        for kind in (
            AnalysisKind.FREQUENTIST,
            AnalysisKind.BAYESIAN,
            AnalysisKind.CUPED,
            AnalysisKind.SEQUENTIAL,
        ):
            record_snapshot(
                db_session, experiment.id, kind, {"k": kind.value}, as_of=as_of
            )
            record_snapshot(
                db_session, experiment.id, kind, {"k": kind.value}, as_of=as_of
            )

        assert len(_rows(db_session, experiment.id)) == 4

    def test_provenance_is_refreshed_with_the_payload(self, db_session, experiment):
        as_of = datetime(2026, 9, 11, 6, tzinfo=timezone.utc)
        record_snapshot(
            db_session,
            experiment.id,
            AnalysisKind.BAYESIAN,
            {"decision": "CONTINUE"},
            seed=111,
            n_samples=10_000,
            as_of=as_of,
        )
        record_snapshot(
            db_session,
            experiment.id,
            AnalysisKind.BAYESIAN,
            {"decision": "STOP_WINNER"},
            seed=222,
            n_samples=20_000,
            as_of=as_of,
        )

        rows = _rows(db_session, experiment.id, "bayesian")
        assert len(rows) == 1
        assert rows[0].payload == {"decision": "STOP_WINNER"}
        assert rows[0].seed == 222
        assert rows[0].n_samples == 20_000
        assert rows[0].engine_version == ENGINE_VERSION

    def test_database_rejects_a_duplicate_row(self, db_session, experiment):
        """The unique constraint, not just the service, enforces the rule."""
        as_of = snapshot_day(datetime(2026, 9, 11, 3, tzinfo=timezone.utc))
        session = _fresh_session(db_session)
        try:
            session.add(
                build_snapshot(
                    experiment.id, AnalysisKind.CUPED, {"n": 1}, as_of=as_of
                )
            )
            session.commit()
            session.add(
                build_snapshot(
                    experiment.id, AnalysisKind.CUPED, {"n": 2}, as_of=as_of
                )
            )
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()
        finally:
            session.close()

        assert len(_rows(db_session, experiment.id, "cuped")) == 1


@pytest.mark.integration
@pytest.mark.requires_db
class TestCallerTransactionIsUntouched:
    def test_successful_snapshot_does_not_commit_caller_changes(
        self, db_session, experiment
    ):
        """A GET must not persist what the analysis only flushed."""
        experiment.bayesian_decision = "STOP_WINNER"
        db_session.flush()  # flushed, not committed — as AnalysisService does

        row = record_snapshot(
            db_session,
            experiment.id,
            AnalysisKind.BAYESIAN,
            {"decision": "STOP_WINNER"},
            as_of=datetime(2026, 9, 11, 9, tzinfo=timezone.utc),
        )
        assert row is not None

        # The snapshot is committed...
        probe = _fresh_session(db_session)
        try:
            assert (
                probe.query(AnalysisSnapshot)
                .filter(AnalysisSnapshot.experiment_id == experiment.id)
                .count()
                == 1
            )
            # ...while the caller's pending change is still only pending.
            assert (
                probe.query(Experiment.bayesian_decision)
                .filter(Experiment.id == experiment.id)
                .scalar()
                is None
            )
        finally:
            probe.close()

        # The caller still owns it: rolling back discards it, as before.
        db_session.rollback()
        db_session.refresh(experiment)
        assert experiment.bayesian_decision is None

    def test_failed_snapshot_leaves_caller_changes_pending(
        self, db_session, experiment
    ):
        """A snapshot failure must not roll back the caller's work."""
        experiment.bayesian_decision = "CONTINUE"
        db_session.flush()

        with patch(
            "backend.app.services.analysis_snapshot_service._upsert",
            side_effect=RuntimeError("snapshot table missing"),
        ):
            assert (
                record_snapshot(
                    db_session,
                    experiment.id,
                    AnalysisKind.BAYESIAN,
                    {"decision": "CONTINUE"},
                )
                is None
            )

        # Still pending in the caller's transaction, and still committable.
        assert experiment in db_session.dirty or experiment.bayesian_decision == "CONTINUE"
        db_session.commit()
        db_session.refresh(experiment)
        assert experiment.bayesian_decision == "CONTINUE"
        assert _rows(db_session, experiment.id) == []

        experiment.bayesian_decision = None
        db_session.commit()

    def test_mocked_session_writes_nothing(self):
        """A unit-test session with no engine is skipped, not redirected."""
        from unittest.mock import MagicMock

        assert (
            record_snapshot(
                MagicMock(), uuid.uuid4(), AnalysisKind.FREQUENTIST, {"a": 1}
            )
            is None
        )
