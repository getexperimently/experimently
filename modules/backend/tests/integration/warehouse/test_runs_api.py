"""Warehouse analysis runs end to end: the API, the runner and a DuckDB warehouse."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.app.models.assignment import Assignment
from backend.app.models.event import Event
from backend.app.models.experiment import Metric, MetricType
from backend.app.services.analysis_service import AnalysisService
from modules.backend.app.models.warehouse_analysis_run import WarehouseAnalysisRun
from modules.backend.app.warehouse.errors import WarehouseError, WarehouseErrorCode
from modules.backend.tests.integration.warehouse import recording_estimator
from modules.backend.tests.integration.warehouse.conftest import WA, ts

pytestmark = [pytest.mark.integration, pytest.mark.modules]


def _exposure(user, key, variant, when):
    return (user, key, variant, when)


def _standard_data(wh, key: str) -> None:
    """Six units: three per variant; two control and one treatment convert."""
    wh.exposures(
        [
            _exposure("u1", key, "control", ts(2)),
            _exposure("u2", key, "control", ts(2)),
            _exposure("u3", key, "control", ts(3)),
            _exposure("u4", key, "treatment", ts(2)),
            _exposure("u5", key, "treatment", ts(3)),
            _exposure("u6", key, "treatment", ts(3)),
            _exposure("x1", "another-experiment", "control", ts(2)),
        ]
    )
    wh.events(
        [
            ("u1", ts(2, 5), None),
            ("u1", ts(2, 6), None),
            ("u2", ts(4), None),
            ("u4", ts(3), None),
        ]
    )


def test_proportion_run_end_to_end(wh):
    experiment = wh.experiment(end=ts(10))
    _standard_data(wh, experiment.key)
    ids = wh.ready(wh.as_("ADMIN"))
    client = wh.as_("DEVELOPER")
    response = wh.start_run(client, experiment, ids)
    assert response.status_code == 202, response.text
    run = wh.wait_for_run(client, response.json()["run_id"])
    assert run["status"] == "succeeded", run

    # The estimator is given the counts, control first, and the run's alpha.
    assert len(recording_estimator.CALLS) == 1
    call = recording_estimator.CALLS[0]
    assert call["alpha"] == pytest.approx(0.05)
    assert call["correction_method"] == "none"
    assert call["metric"] == {
        "id": ids["metric_source_id"],
        "name": "Purchases",
        "metric_type": "conversion",
        "is_primary": True,
    }
    assert [
        (v["variant_name"], v["n"], v["n_converted"]) for v in call["variants"]
    ] == [
        ("control", 3, 2),
        ("treatment", 3, 1),
    ]
    results = run["results"]
    metric = results["metrics"][0]
    assert metric["computed"] is True and metric["is_primary"] is True
    assert metric["result"]["metric_id"] == ids["metric_source_id"]
    assert [v["sample_size"] for v in metric["result"]["variants"]] == [3, 3]
    assert metric["result"]["variants"][1]["statistical_test_used"] == "fisher_exact"
    assert results["srm"]["observed"] == {str(v.id): 3 for v in experiment.variants}
    assert results["diagnostics"]["units"] == 6
    # View SQL: every statement sent, with its hash.
    assert [s["kind"] for s in run["statements"]] == ["diagnostics", "metric"]
    assert all(len(s["sha256"]) == 64 for s in run["statements"])
    assert run["window_start"].startswith("2026-09-01T00:00:00")
    assert run["window_end"].startswith("2026-09-10T00:00:00")


def _seed_results(wh, experiment, rows, *, is_primary=False):
    """The same units in the platform's own tables, as /results reads them."""
    variants = {v.name: v for v in experiment.variants}
    metric = Metric(
        experiment_id=experiment.id,
        name="Purchases",
        event_name="purchase",
        metric_type=MetricType.CONVERSION,
        is_primary=is_primary,
    )
    wh.db.add(metric)
    for user, variant, conversions in rows:
        wh.db.add(
            Assignment(
                experiment_id=experiment.id,
                variant_id=variants[variant].id,
                user_id=user,
            )
        )
        for when in conversions:
            wh.db.add(
                Event(
                    event_type="track",
                    event_name="purchase",
                    user_id=user,
                    experiment_id=experiment.id,
                    variant_id=variants[variant].id,
                    created_at=when.isoformat(),
                    value=1.0,
                )
            )
    wh.db.commit()
    wh.db.refresh(metric)
    return metric


def _results_counts(wh, experiment, metric):
    raw = AnalysisService(wh.db).calculate_metric_results(experiment, metric)
    return {
        v["variant_name"]: (v["sample_size"], v["conversions"])
        for v in raw["variant_results"]
    }


def _warehouse_counts():
    return {
        v["variant_name"]: (v["n"], v["n_converted"])
        for v in recording_estimator.CALLS[-1]["variants"]
    }


def _run(wh, experiment, rows):
    wh.exposures([(u, experiment.key, variant, ts(2)) for u, variant, _ in rows])
    wh.events([(u, when, None) for u, _, whens in rows for when in whens])
    ids = wh.ready(wh.as_("ADMIN"))
    client = wh.as_("DEVELOPER")
    response = wh.start_run(client, experiment, ids)
    assert response.status_code == 202, response.text
    run = wh.wait_for_run(client, response.json()["run_id"])
    assert run["status"] == "succeeded", run


def test_proportion_counts_match_results_on_restricted_fixture(wh):
    """With no pre-exposure event, no unit in two variants and no event outside
    the window, the warehouse counts equal /results' counts."""
    experiment = wh.experiment(end=ts(10))
    rows = [
        ("r1", "control", [ts(3), ts(4)]),
        ("r2", "control", []),
        ("r3", "control", [ts(5)]),
        ("r4", "treatment", [ts(3)]),
        ("r5", "treatment", []),
    ]
    metric = _seed_results(wh, experiment, rows)
    _run(wh, experiment, rows)
    assert (
        _warehouse_counts()
        == _results_counts(wh, experiment, metric)
        == {
            "control": (3, 2),
            "treatment": (2, 1),
        }
    )


def test_proportion_results_equal_results_on_restricted_fixture(wh):
    """On the counts /results also computes, the warehouse result is /results'
    result: every variant's numbers, significance and winner (only the metric's
    id differs -- a warehouse source is not a platform metric)."""
    import json

    experiment = wh.experiment(end=ts(10))
    rows = [
        ("q1", "control", [ts(3), ts(4)]),
        ("q2", "control", []),
        ("q3", "control", [ts(5)]),
        ("q4", "control", []),
        ("q5", "treatment", [ts(3)]),
        ("q6", "treatment", [ts(4)]),
        ("q7", "treatment", [ts(6)]),
    ]
    _seed_results(wh, experiment, rows, is_primary=True)
    wh.exposures([(u, experiment.key, v, ts(2)) for u, v, _ in rows])
    wh.events([(u, w, None) for u, _, ws in rows for w in ws])
    ids = wh.ready(wh.as_("ADMIN"))
    client = wh.as_("ADMIN")
    response = wh.start_run(
        client, experiment, ids, confidence_level=0.9, correction_method="bonferroni"
    )
    run = wh.wait_for_run(client, response.json()["run_id"])
    assert run["status"] == "succeeded", run
    warehouse = dict(run["results"]["metrics"][0]["result"])
    results = AnalysisService(wh.db).get_experiment_results(
        experiment.id, confidence_level=0.9, correction_method="bonferroni"
    )["metrics"][0]
    results = json.loads(json.dumps(results, default=str))
    assert warehouse.pop("metric_id") == ids["metric_source_id"]
    results.pop("metric_id")
    assert warehouse == results


def test_documented_difference_from_results(wh):
    """An event before the unit's first exposure converts it in /results but not
    in the warehouse: the stated definitional difference."""
    experiment = wh.experiment(end=ts(10))
    rows = [
        ("d1", "control", [ts(1, 12)]),  # before its exposure on the 2nd
        ("d2", "treatment", [ts(3)]),
    ]
    metric = _seed_results(wh, experiment, rows)
    _run(wh, experiment, rows)
    assert _results_counts(wh, experiment, metric)["control"] == (1, 1)
    assert _warehouse_counts()["control"] == (1, 0)
    assert (
        _warehouse_counts()["treatment"]
        == _results_counts(wh, experiment, metric)["treatment"]
    )


def test_run_stores_resolved_utc_window(wh):
    """A naive start_date is UTC: the stored window starts at that instant."""
    experiment = wh.experiment(start=datetime(2026, 9, 1, 6, 30), end=None)
    _standard_data(wh, experiment.key)
    ids = wh.ready(wh.as_("ADMIN"))
    client = wh.as_("ADMIN")
    response = wh.start_run(client, experiment, ids)
    assert response.status_code == 202, response.text
    run = wh.wait_for_run(client, response.json()["run_id"])
    assert run["window_start"] in ("2026-09-01T06:30:00Z", "2026-09-01T06:30:00+00:00")
    assert run["window_end"].startswith("2026-09-20T12:00:00")  # the harness clock
    assert "'2026-09-01 06:30:00+00:00'" in run["statements"][0]["sql"]


def test_explicit_window_with_no_offset_is_read_as_utc(wh):
    experiment = wh.experiment()
    _standard_data(wh, experiment.key)
    ids = wh.ready(wh.as_("ADMIN"))
    client = wh.as_("ADMIN")
    response = wh.start_run(
        client,
        experiment,
        ids,
        window_start="2026-09-02T00:00:00",
        window_end="2026-09-03T00:00:00+02:00",
    )
    run = wh.wait_for_run(client, response.json()["run_id"])
    assert run["window_start"].startswith("2026-09-02T00:00:00")
    assert run["window_end"].startswith("2026-09-02T22:00:00")


def test_experiment_without_window_422(wh):
    experiment = wh.experiment()
    experiment.start_date = None
    wh.db.commit()
    _standard_data(wh, experiment.key)
    ids = wh.ready(wh.as_("ADMIN"))
    response = wh.start_run(wh.as_("ADMIN"), experiment, ids)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "experiment_has_no_window"
    assert (
        wh.db.query(WarehouseAnalysisRun)
        .filter(WarehouseAnalysisRun.experiment_id == experiment.id)
        .count()
        == 0
    )


def test_srm_uses_traffic_allocation(wh):
    experiment = wh.experiment(end=ts(10), allocations=(90, 10))
    _standard_data(wh, experiment.key)
    ids = wh.ready(wh.as_("ADMIN"))
    client = wh.as_("ADMIN")
    run = wh.wait_for_run(
        client, wh.start_run(client, experiment, ids).json()["run_id"]
    )
    srm = run["results"]["srm"]
    control = next(v for v in experiment.variants if v.is_control)
    assert srm["expected"][str(control.id)] == pytest.approx(6 * 0.9)
    assert run["results"]["srm_skipped"] is None


def test_srm_none_for_bandit(wh):
    experiment = wh.experiment(end=ts(10), optimization_type="thompson_sampling")
    _standard_data(wh, experiment.key)
    ids = wh.ready(wh.as_("ADMIN"))
    client = wh.as_("ADMIN")
    run = wh.wait_for_run(
        client, wh.start_run(client, experiment, ids).json()["run_id"]
    )
    assert run["results"]["srm"] is None
    assert run["results"]["srm_skipped"] == "adaptive_allocation"


def test_variant_labels_truncated_in_python(wh):
    """A variant named with more than 64 characters matches the label the SQL
    cut to 64, and is reported as the experiment's variant."""
    experiment = wh.experiment(end=ts(10))
    long_name = "treatment-" + "x" * 80
    treatment = next(v for v in experiment.variants if not v.is_control)
    treatment.name = long_name[:100]
    wh.db.commit()
    wh.exposures(
        [
            ("a", experiment.key, "control", ts(2)),
            ("b", experiment.key, long_name, ts(2)),
        ]
    )
    wh.events([("b", ts(3), None)])
    ids = wh.ready(wh.as_("ADMIN"))
    client = wh.as_("ADMIN")
    run = wh.wait_for_run(
        client, wh.start_run(client, experiment, ids).json()["run_id"]
    )
    by_name = {v["variant_name"]: v for v in run["results"]["variants"]}
    assert by_name[long_name[:100]]["labels"] == [long_name[:64]]
    assert by_name[long_name[:100]]["units"] == 1
    assert run["results"]["unmapped_labels"] == []


def test_variant_map_names_the_variant_of_a_label(wh):
    experiment = wh.experiment(end=ts(10))
    wh.exposures([("a", experiment.key, "A", ts(2)), ("b", experiment.key, "B", ts(2))])
    wh.events([("b", ts(3), None)])
    ids = wh.ready(wh.as_("ADMIN"))
    client = wh.as_("ADMIN")
    variants = {v.name: str(v.id) for v in experiment.variants}
    response = wh.start_run(
        client,
        experiment,
        ids,
        variant_map={"A": variants["control"], "B": variants["treatment"]},
    )
    run = wh.wait_for_run(client, response.json()["run_id"])
    assert _warehouse_counts() == {"control": (1, 0), "treatment": (1, 1)}
    assert run["request"]["variant_map"] == {
        "A": variants["control"],
        "B": variants["treatment"],
    }


def test_unmapped_labels_are_reported_not_counted(wh):
    experiment = wh.experiment(end=ts(10))
    wh.exposures(
        [
            ("a", experiment.key, "control", ts(2)),
            ("b", experiment.key, "treatment", ts(2)),
            ("c", experiment.key, "holdout", ts(2)),
        ]
    )
    wh.events([])
    ids = wh.ready(wh.as_("ADMIN"))
    client = wh.as_("ADMIN")
    run = wh.wait_for_run(
        client, wh.start_run(client, experiment, ids).json()["run_id"]
    )
    assert run["results"]["unmapped_labels"] == [{"label": "holdout", "units": 1}]
    assert _warehouse_counts() == {"control": (1, 0), "treatment": (1, 0)}


def test_a_metric_that_cannot_be_computed_says_why_never_zero(wh):
    """Metric rows in the window that match no exposed unit: that metric is
    "Not computed" with its reason; the run itself succeeds."""
    experiment = wh.experiment(end=ts(10))
    wh.exposures([("u1", experiment.key, "control", ts(2))])
    wh.events([("someone-else", ts(3), None)])
    ids = wh.ready(wh.as_("ADMIN"))
    client = wh.as_("ADMIN")
    run = wh.wait_for_run(
        client, wh.start_run(client, experiment, ids).json()["run_id"]
    )
    assert run["status"] == "succeeded"
    metric = run["results"]["metrics"][0]
    assert metric["computed"] is False
    assert metric["not_computed_reason"] == "join_key_mismatch"
    assert metric["message"].startswith("Not computed: ")
    assert metric["result"] is None
    assert recording_estimator.CALLS == []


def test_a_failed_run_reports_its_code_and_no_numbers(wh):
    experiment = wh.experiment(end=ts(10))
    _standard_data(wh, experiment.key)
    ids = wh.ready(wh.as_("ADMIN"))
    wh.fail_with = WarehouseError(
        WarehouseErrorCode.PERMISSION_DENIED, warehouse="athena"
    )
    client = wh.as_("VIEWER")
    response = wh.start_run(wh.as_("ADMIN"), experiment, ids)
    run = wh.wait_for_run(client, response.json()["run_id"])
    assert run["status"] == "failed"
    assert run["error_code"] == "permission_denied"
    assert run["error_message"] == (
        "The warehouse role does not have permission for this query."
    )
    assert run["results"] is None
    row = wh.db.get(WarehouseAnalysisRun, run["id"])
    wh.db.refresh(row)
    assert row.results is None and row.sufficient_statistics is None


def test_mean_metric_sources_are_not_run_yet(wh):
    admin = wh.as_("ADMIN")
    experiment = wh.experiment(end=ts(10))
    _standard_data(wh, experiment.key)
    ids = wh.ready(admin)
    mean = wh.metric_source(
        admin,
        ids["connection_id"],
        name="Revenue",
        metric_type="mean",
        columns={"unit_id": "user_id", "event_at": "event_at", "value": "amount"},
    )
    wh.validate(admin, mean["id"])
    response = admin.post(
        f"{WA}/experiments/{experiment.id}/runs",
        json={
            "connection_id": ids["connection_id"],
            "assignment_source_id": ids["assignment_source_id"],
            "metric_source_ids": [mean["id"]],
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "metric_type_unavailable"


def test_unvalidated_sources_are_refused(wh):
    admin = wh.as_("ADMIN")
    experiment = wh.experiment(end=ts(10))
    _standard_data(wh, experiment.key)
    connection = wh.athena_connection(admin)
    assignment = wh.assignment_source(admin, connection["id"])
    metric = wh.metric_source(admin, connection["id"])
    response = wh.start_run(
        admin,
        experiment,
        {
            "connection_id": connection["id"],
            "assignment_source_id": assignment["id"],
            "metric_source_id": metric["id"],
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "source_not_validated"


def test_runs_list_newest_first_for_every_role(wh):
    experiment = wh.experiment(end=ts(10))
    _standard_data(wh, experiment.key)
    ids = wh.ready(wh.as_("ADMIN"))
    client = wh.as_("ADMIN")
    first = wh.start_run(client, experiment, ids).json()["run_id"]
    wh.wait_for_run(client, first)
    wh.now = wh.now.replace(minute=5)
    second = wh.start_run(client, experiment, ids).json()["run_id"]
    wh.wait_for_run(client, second)
    for role in ("ADMIN", "DEVELOPER", "ANALYST", "VIEWER"):
        listed = wh.as_(role).get(f"{WA}/experiments/{experiment.id}/runs")
        assert listed.status_code == 200
        assert [r["id"] for r in listed.json()["runs"]] == [second, first]


def test_the_run_response_never_carries_rows(wh):
    """Results are aggregates: no unit id from the warehouse appears."""
    experiment = wh.experiment(end=ts(10))
    _standard_data(wh, experiment.key)
    ids = wh.ready(wh.as_("ADMIN"))
    client = wh.as_("ADMIN")
    response = client.get(
        f"{WA}/runs/{wh.start_run(client, experiment, ids).json()['run_id']}"
    )
    run = wh.wait_for_run(client, response.json()["id"])
    text = str(run)
    for unit in ("u1", "u2", "u3", "u4", "u5", "u6", "x1"):
        assert f"'{unit}'" not in text


def test_completed_runs_record_when(wh):
    experiment = wh.experiment(end=ts(10))
    _standard_data(wh, experiment.key)
    ids = wh.ready(wh.as_("ADMIN"))
    client = wh.as_("ADMIN")
    run = wh.wait_for_run(
        client, wh.start_run(client, experiment, ids).json()["run_id"]
    )
    assert run["finished_at"] is not None and run["started_at"] is not None
    assert (
        datetime.fromisoformat(run["finished_at"].replace("Z", "+00:00")).tzinfo
        == timezone.utc
    )


def test_starting_a_run_is_audited(wh):
    from sqlalchemy import text

    experiment = wh.experiment(end=ts(10))
    _standard_data(wh, experiment.key)
    ids = wh.ready(wh.as_("ADMIN"))
    client = wh.as_("DEVELOPER")
    run_id = wh.start_run(client, experiment, ids).json()["run_id"]
    wh.wait_for_run(client, run_id)
    rows = wh.db.execute(
        text(
            "SELECT action, actor_id, new_value FROM test_experimentation.audit_events_v2 "
            "WHERE resource_type = 'warehouse_analysis_run' AND resource_id = :id"
        ),
        {"id": run_id},
    ).all()
    assert len(rows) == 1
    assert str(rows[0].actor_id) == str(wh.user("DEVELOPER").id)
    assert rows[0].new_value["metric_source_ids"] == [ids["metric_source_id"]]
    assert "total_seconds" not in rows[0].new_value
