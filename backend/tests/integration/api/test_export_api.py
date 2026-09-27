"""
DB-backed tests for the data export (#220).

* ``/export/variants`` and ``/export/experiments`` take their numbers from the
  computation behind ``GET /api/v1/results/{id}``, so each variant's
  assignments, conversions, rate, p-value and significance, and each
  experiment's winner and recommendation, equal what ``/results`` reports.
* ``/export/reports/experiments/{id}`` honours ``format=csv``, answers 404
  for an unknown id and 422 for one that is not a UUID.
* ``scope`` other than ``summary`` is refused with 422.
* An experiment whose results cannot be computed keeps its rows, with the
  result columns empty, and does not fail the export.
* The totals are counted in SQL: as events, assignments and raw metrics
  grow, the number of statements the export runs stays the same and it loads
  none of those rows.
* CSV cells are written spreadsheet-safe.

Rows created here are deleted in fixture teardown because the shared test
database is not truncated between tests.
"""

import csv
import io
import json
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event as sa_event
from sqlalchemy.orm import Session

from backend.app.models.assignment import Assignment
from backend.app.models.event import Event
from backend.app.models.experiment import (
    Experiment,
    ExperimentStatus,
    ExperimentType,
    Metric,
    MetricType,
    Variant,
)
from backend.app.models.metrics.metric import RawMetric
from backend.app.schemas.export import (
    ExportFormat,
    ExportRequest,
    VariantExportRow,
)
from backend.app.services.export_service import ExportService

VARIANT_HEADER = ",".join(VariantExportRow.model_fields.keys())


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _delete_rows(db_session, experiment_ids=(), flag_ids=()):
    db_session.rollback()
    for model in (Event, Assignment):
        db_session.query(model).filter(model.experiment_id.in_(experiment_ids)).delete(
            synchronize_session=False
        )
    if flag_ids:
        db_session.query(RawMetric).filter(
            RawMetric.feature_flag_id.in_(flag_ids)
        ).delete(synchronize_session=False)
    db_session.commit()


@pytest.fixture
def make_ab_experiment(db_session, make_experiment):
    """Factory: an ACTIVE A/B experiment with a primary and a secondary metric."""
    created = []

    def _make(name=None, control_name="control", treatment_name="treatment"):
        suffix = uuid.uuid4().hex[:8]
        experiment = make_experiment(
            name=name or f"Export API {suffix}",
            key=f"export-api-{suffix}",
            status=ExperimentStatus.ACTIVE,
            experiment_type=ExperimentType.A_B,
            start_date=datetime(2026, 9, 1, tzinfo=timezone.utc),
        )
        for variant_name, is_control in ((control_name, True), (treatment_name, False)):
            db_session.add(
                Variant(
                    experiment_id=experiment.id,
                    name=variant_name,
                    is_control=is_control,
                    traffic_allocation=50,
                )
            )
        # The secondary metric is created first, so that a builder picking the
        # first metric rather than the primary one would read the wrong numbers.
        db_session.add(
            Metric(
                experiment_id=experiment.id,
                name="Signup",
                event_name="signup",
                metric_type=MetricType.CONVERSION,
                is_primary=False,
            )
        )
        db_session.add(
            Metric(
                experiment_id=experiment.id,
                name="Purchase",
                event_name="purchase",
                metric_type=MetricType.CONVERSION,
                is_primary=True,
            )
        )
        db_session.commit()
        db_session.refresh(experiment)
        created.append(experiment.id)
        return experiment

    yield _make
    _delete_rows(db_session, experiment_ids=created)


def _variants(experiment):
    control = next(v for v in experiment.variants if v.is_control)
    treatment = next(v for v in experiment.variants if not v.is_control)
    return control, treatment


def _seed(db_session, experiment, variant, n_users, n_purchases, n_signups=0):
    """n_users assignments, each with an exposure event; some purchase or sign up."""
    now_iso = datetime.now(timezone.utc).isoformat()
    prefix = f"{variant.name}-{uuid.uuid4().hex[:6]}"
    rows = []
    for i in range(n_users):
        user_id = f"{prefix}-{i:05d}"
        rows.append(
            Assignment(
                experiment_id=experiment.id, variant_id=variant.id, user_id=user_id
            )
        )
        names = ["exposure"]
        if i < n_purchases:
            names.append("purchase")
        if i < n_signups:
            names.append("signup")
        for name in names:
            rows.append(
                Event(
                    event_type=name,
                    event_name=name,
                    user_id=user_id,
                    experiment_id=experiment.id,
                    variant_id=variant.id,
                    value=1.0,
                    created_at=now_iso,
                )
            )
    db_session.add_all(rows)
    db_session.commit()


def _since(experiment):
    """A start_date that keeps the export to experiments made from this one on."""
    return (experiment.created_at - timedelta(seconds=1)).isoformat()


def _results(admin_client, experiment):
    response = admin_client.get(
        f"/api/v1/results/{experiment.id}", params={"use_cache": "false"}
    )
    assert response.status_code == 200, response.text
    return response.json()


def _primary(results):
    return next(m for m in results["metrics"] if m["is_primary"])


def _export(admin_client, route, experiment, fmt="json"):
    response = admin_client.get(
        f"/api/v1/export/{route}",
        params={"format": fmt, "start_date": _since(experiment)},
    )
    assert response.status_code == 200, response.text
    return response


@pytest.fixture
def significant_experiment(db_session, make_ab_experiment):
    """Treatment converts 70/400 against control's 40/400 on the primary metric."""
    experiment = make_ab_experiment()
    control, treatment = _variants(experiment)
    _seed(db_session, experiment, control, 400, 40, n_signups=200)
    _seed(db_session, experiment, treatment, 400, 70, n_signups=10)
    return experiment


# ---------------------------------------------------------------------------
# The export carries the results API's numbers
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.requires_db
class TestExportEqualsResults:
    @pytest.mark.regression
    def test_variant_rows_equal_results(self, admin_client, significant_experiment):
        experiment = significant_experiment
        expected = {
            v["variant_id"]: v
            for v in _primary(_results(admin_client, experiment))["variants"]
        }

        rows = [
            r
            for r in _export(admin_client, "variants", experiment).json()
            if r["experiment_id"] == str(experiment.id)
        ]

        assert {r["variant_id"] for r in rows} == set(expected)
        for row in rows:
            want = expected[row["variant_id"]]
            assert row["variant_name"] == want["variant_name"]
            assert row["is_control"] == want["is_control"]
            assert row["assignments"] == want["sample_size"] == 400
            assert row["conversions"] == want["conversions"]
            assert row["conversion_rate"] == pytest.approx(want["mean"], abs=1e-12)
            if want["p_value"] is None:
                assert row["p_value"] is None
            else:
                assert row["p_value"] == pytest.approx(want["p_value"], abs=1e-12)
            assert row["is_significant"] == want["is_significant"]
            if want["relative_improvement_pct"] is None:
                assert row["relative_improvement_pct"] is None
            else:
                assert row["relative_improvement_pct"] == pytest.approx(
                    want["relative_improvement_pct"], abs=1e-12
                )
        # The primary metric's counts, not the secondary one's.
        by_name = {r["variant_name"]: r for r in rows}
        assert by_name["control"]["conversions"] == 40
        assert by_name["treatment"]["conversions"] == 70
        assert by_name["treatment"]["is_significant"] is True

    @pytest.mark.regression
    def test_experiment_row_winner_and_recommendation_equal_results(
        self, admin_client, significant_experiment
    ):
        experiment = significant_experiment
        summary = _results(admin_client, experiment)["summary"]
        assert summary["recommendation"] == "SHIP_VARIANT"
        _, treatment = _variants(experiment)
        assert summary["winning_variant_id"] == str(treatment.id)

        rows = [
            r
            for r in _export(admin_client, "experiments", experiment).json()
            if r["experiment_id"] == str(experiment.id)
        ]

        assert len(rows) == 1
        assert rows[0]["winner_variant"] == "treatment"
        assert rows[0]["recommendation"] == summary["recommendation"]
        assert rows[0]["total_assignments"] == 800
        # 800 exposures, 110 purchases and 210 sign-ups.
        assert rows[0]["total_events"] == 800 + 110 + 210

    def test_no_winner_is_empty_and_recommendation_still_equals_results(
        self, admin_client, db_session, make_ab_experiment
    ):
        experiment = make_ab_experiment()
        control, treatment = _variants(experiment)
        _seed(db_session, experiment, control, 200, 20)
        _seed(db_session, experiment, treatment, 200, 21)
        summary = _results(admin_client, experiment)["summary"]

        rows = [
            r
            for r in _export(admin_client, "experiments", experiment).json()
            if r["experiment_id"] == str(experiment.id)
        ]

        assert summary["winning_variant_id"] is None
        assert rows[0]["winner_variant"] is None
        assert rows[0]["recommendation"] == summary["recommendation"]

    def test_report_json_equals_the_exports(self, admin_client, significant_experiment):
        experiment = significant_experiment
        variants = [
            r
            for r in _export(admin_client, "variants", experiment).json()
            if r["experiment_id"] == str(experiment.id)
        ]
        experiments = [
            r
            for r in _export(admin_client, "experiments", experiment).json()
            if r["experiment_id"] == str(experiment.id)
        ]

        response = admin_client.get(
            f"/api/v1/export/reports/experiments/{experiment.id}"
        )

        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("application/json")
        report = response.json()
        assert report["experiment_id"] == str(experiment.id)
        assert report["experiments"] == experiments
        assert report["variants"] == variants

    @pytest.mark.regression
    def test_experiment_without_control_keeps_rows_with_empty_results(
        self, admin_client, db_session, make_experiment, significant_experiment
    ):
        """One experiment whose results cannot be computed does not fail the export."""
        broken = make_experiment(
            name=f"Export no control {uuid.uuid4().hex[:8]}",
            status=ExperimentStatus.ACTIVE,
            experiment_type=ExperimentType.A_B,
        )
        db_session.add(Variant(experiment_id=broken.id, name="only", is_control=False))
        # With a metric and no control variant, get_experiment_results raises
        # ValueError, which is what /results answers 404 for.
        db_session.add(
            Metric(
                experiment_id=broken.id,
                name="Purchase",
                event_name="purchase",
                metric_type=MetricType.CONVERSION,
                is_primary=True,
            )
        )
        db_session.commit()
        db_session.refresh(broken)
        assert (
            admin_client.get(
                f"/api/v1/results/{broken.id}", params={"use_cache": "false"}
            ).status_code
            == 404
        )

        variants = _export(admin_client, "variants", significant_experiment).json()
        experiments = _export(
            admin_client, "experiments", significant_experiment
        ).json()

        broken_variant = next(
            r for r in variants if r["experiment_id"] == str(broken.id)
        )
        for column in (
            "assignments",
            "conversions",
            "conversion_rate",
            "p_value",
            "is_significant",
            "relative_improvement_pct",
        ):
            assert broken_variant[column] is None, column
        broken_row = next(
            r for r in experiments if r["experiment_id"] == str(broken.id)
        )
        assert broken_row["winner_variant"] is None
        assert broken_row["recommendation"] is None
        # The healthy experiment in the same export still carries its numbers.
        healthy = next(
            r
            for r in experiments
            if r["experiment_id"] == str(significant_experiment.id)
        )
        assert healthy["recommendation"] == "SHIP_VARIANT"


# ---------------------------------------------------------------------------
# The single-experiment report
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.requires_db
class TestExperimentReport:
    @pytest.mark.regression
    def test_format_csv_is_the_variant_rows_as_csv(
        self, admin_client, significant_experiment
    ):
        experiment = significant_experiment
        response = admin_client.get(
            f"/api/v1/export/reports/experiments/{experiment.id}",
            params={"format": "csv"},
        )

        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("text/csv")
        assert "attachment" in response.headers["content-disposition"]
        lines = response.text.splitlines()
        assert lines[0] == VARIANT_HEADER
        rows = list(csv.DictReader(io.StringIO(response.text)))
        assert len(rows) == 2
        for row in rows:
            for cell in row.values():
                assert not cell.startswith(("{", "[")), cell
        expected = {
            v["variant_id"]: v
            for v in _primary(_results(admin_client, experiment))["variants"]
        }
        for row in rows:
            want = expected[row["variant_id"]]
            assert int(row["assignments"]) == want["sample_size"]
            assert int(row["conversions"]) == want["conversions"]
            assert float(row["conversion_rate"]) == pytest.approx(
                want["mean"], abs=1e-12
            )

    @pytest.mark.regression
    def test_unknown_experiment_is_404(self, admin_client):
        response = admin_client.get(
            f"/api/v1/export/reports/experiments/{uuid.uuid4()}"
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "Experiment not found"

    @pytest.mark.regression
    def test_non_uuid_id_is_422(self, admin_client):
        response = admin_client.get("/api/v1/export/reports/experiments/not-a-uuid")
        assert response.status_code == 422


@pytest.mark.integration
@pytest.mark.requires_db
@pytest.mark.regression
@pytest.mark.parametrize("route", ["experiments", "variants"])
def test_scope_other_than_summary_is_422(admin_client, route):
    response = admin_client.get(f"/api/v1/export/{route}", params={"scope": "events"})
    assert response.status_code == 422
    assert response.json()["detail"] == (
        "scope=events is not supported; the export is available with scope=summary only"
    )


# ---------------------------------------------------------------------------
# Spreadsheet-safe CSV cells
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.requires_db
class TestSpreadsheetSafeCells:
    @pytest.mark.regression
    def test_leading_characters_are_written_as_text(
        self, admin_client, db_session, make_ab_experiment, make_feature_flag
    ):
        experiment = make_ab_experiment(
            name=f"=1+2 {uuid.uuid4().hex[:6]}",
            control_name="-10% off",
            treatment_name="@home",
        )
        flag = make_feature_flag(key=f"flag-{uuid.uuid4().hex[:8]}", name="+plus\tname")

        experiments = list(
            csv.DictReader(
                io.StringIO(
                    _export(admin_client, "experiments", experiment, "csv").text
                )
            )
        )
        variants = list(
            csv.DictReader(
                io.StringIO(_export(admin_client, "variants", experiment, "csv").text)
            )
        )
        flags_csv = admin_client.get(
            "/api/v1/export/feature-flags",
            params={"format": "csv", "start_date": _since(flag)},
        ).text
        flags = list(csv.DictReader(io.StringIO(flags_csv)))

        exp_row = next(
            r for r in experiments if r["experiment_id"] == str(experiment.id)
        )
        assert exp_row["experiment_name"] == "'" + experiment.name
        names = {
            r["variant_name"]
            for r in variants
            if r["experiment_id"] == str(experiment.id)
        }
        assert names == {"'-10% off", "'@home"}
        flag_row = next(r for r in flags if r["flag_id"] == str(flag.id))
        assert flag_row["flag_name"] == "'+plus\tname"
        # Ordinary text and numbers are unchanged.
        assert flag_row["flag_key"] == flag.key
        assert exp_row["experiment_type"] == "a_b"

        # JSON carries the values as they are.
        json_rows = _export(admin_client, "variants", experiment).json()
        assert {
            r["variant_name"]
            for r in json_rows
            if r["experiment_id"] == str(experiment.id)
        } == {"-10% off", "@home"}

    def test_every_leading_character(self):
        from backend.app.services.export_service import spreadsheet_safe

        for text in ("=A1", "+1", "-1", "@A1", "\tA1", "\rA1"):
            assert spreadsheet_safe(text) == "'" + text
        for value in ("A1", "", "1-2", " =A1", -1, -0.5, None, True):
            assert spreadsheet_safe(value) == value


# ---------------------------------------------------------------------------
# Growth invariance: totals are counted in SQL
# ---------------------------------------------------------------------------


class _Probe:
    """Counts the statements a session runs and the rows of each model it loads."""

    MODELS = (Event, Assignment, RawMetric)

    def __init__(self, engine):
        self.engine = engine
        self.statements = 0
        self.loaded = Counter()

    def _on_execute(self, *args, **kwargs):
        self.statements += 1

    def _loader(self, model):
        def _on_load(target, context):
            self.loaded[model.__name__] += 1

        return _on_load

    def __enter__(self):
        sa_event.listen(self.engine, "before_cursor_execute", self._on_execute)
        self._listeners = [(m, self._loader(m)) for m in self.MODELS]
        for model, fn in self._listeners:
            sa_event.listen(model, "load", fn)
        return self

    def __exit__(self, *exc):
        sa_event.remove(self.engine, "before_cursor_execute", self._on_execute)
        for model, fn in self._listeners:
            sa_event.remove(model, "load", fn)


@pytest.mark.integration
@pytest.mark.requires_db
@pytest.mark.regression
def test_export_work_does_not_grow_with_events_and_raw_metrics(
    db_session, make_ab_experiment, make_feature_flag
):
    """
    The experiment and flag exports count assignments, events and evaluations
    in SQL: adding rows changes the totals, not the number of statements run,
    and no Event, Assignment or RawMetric row is loaded.
    """
    experiment = make_ab_experiment()
    control, treatment = _variants(experiment)
    flag = make_feature_flag(key=f"flag-{uuid.uuid4().hex[:8]}")
    flag_since = flag.created_at - timedelta(seconds=1)

    def add_rows(n):
        _seed(db_session, experiment, control, n, n // 5)
        _seed(db_session, experiment, treatment, n, n // 4)
        db_session.add_all(
            RawMetric(
                metric_type="flag_evaluation", feature_flag_id=flag.id, user_id=f"u{i}"
            )
            for i in range(n)
        )
        db_session.commit()

    def measure():
        session = Session(bind=db_session.get_bind())
        try:
            with _Probe(session.get_bind()) as probe:
                service = ExportService(session)
                experiments = json.loads(
                    service.export_experiments(
                        ExportRequest(format=ExportFormat.JSON),
                        experiment_ids=[str(experiment.id)],
                    )[0]
                )
                flags = json.loads(
                    service.export_feature_flags(
                        ExportRequest(format=ExportFormat.JSON, start_date=flag_since)
                    )[0]
                )
            flag_row = next(r for r in flags if r["flag_id"] == str(flag.id))
            return probe, experiments[0], flag_row
        finally:
            session.close()

    try:
        add_rows(20)
        small, small_exp, small_flag = measure()
        add_rows(200)
        large, large_exp, large_flag = measure()
    finally:
        _delete_rows(db_session, flag_ids=[flag.id])

    # The totals are live ...
    assert small_exp["total_assignments"] == 40
    assert large_exp["total_assignments"] == 440
    assert large_exp["total_events"] > small_exp["total_events"]
    assert small_flag["total_evaluations"] == 20
    assert large_flag["total_evaluations"] == 220
    # ... and the work to produce them does not grow with the rows.
    assert large.statements == small.statements, (small.statements, large.statements)
    assert dict(small.loaded) == {}, small.loaded
    assert dict(large.loaded) == {}, large.loaded
