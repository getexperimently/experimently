"""
Integration tests for EventService (backend/app/services/event_service.py).

These tests exercise EventService against a real Postgres database (via the
`db_session` / `make_experiment` / `make_variant` / `make_event` /
`make_assignment` / `make_feature_flag` fixtures defined in
backend/tests/integration/conftest.py).

Coverage focus
--------------
- `EventService.build_event()`: mapping of schema-shaped (`timestamp`,
  `properties`/`metadata`) or column-shaped (`created_at`,
  `event_metadata`) input onto the `Event` ORM model, id coercion
  (str -> UUID), and its `ValueError`s for missing `user_id`, missing both
  `experiment_id`/`feature_flag_id`, and invalid UUID strings.
- `track_event` / `track_events_batch`: persistence (including the
  all-or-nothing batch contract) and rollback-on-failure behaviour, using
  both `EventCreate` instances and plain dicts.
- `track_conversion` / `track_exposure`: correct `Event` construction,
  assignment-based variant lookup, and the `feature_flag_id`-only path.
- `get_events_by_experiment` / `get_events_by_user`: filtering (event
  type/name, date range, pagination), newest-first ordering by
  `created_at`, and the serialized dict shape.
- `count_events_by_experiment`: filtering, including date filters, and the
  zero-match case.
- `delete_events_by_experiment` / `purge_old_events`: scoped/global
  deletion counts.

Since the shared per-process test database is not truncated between tests,
every test scopes its assertions to data it creates (unique `user_id`s /
`experiment_id`s), per repository testing conventions. `purge_old_events`
has no scoping parameter by design (it purges globally), so its tests
measure the "old" row count dynamically immediately before purging rather
than asserting a hardcoded global count, and additionally scope-check their
own tagged rows.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from freezegun import freeze_time
from pydantic import ValidationError
from sqlalchemy import func

from backend.app.models.event import Event, EventType
from backend.app.schemas.tracking import EventCreate
from backend.app.services.event_service import EventService


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


pytestmark = [pytest.mark.integration, pytest.mark.requires_db]


# ---------------------------------------------------------------------------
# build_event
# ---------------------------------------------------------------------------


class TestBuildEvent:
    def test_build_event_from_event_create_schema(self, make_experiment):
        experiment = make_experiment(name="Build Event Schema")
        event_data = EventCreate(
            user_id="schema-user",
            event_name="signup",
            experiment_id=str(experiment.id),
            properties={"plan": "pro"},
        )

        event = EventService.build_event(event_data)

        assert isinstance(event, Event)
        assert event.event_type == "custom"  # EventBase default
        assert event.event_name == "signup"
        assert event.user_id == "schema-user"
        assert event.experiment_id == experiment.id
        assert event.feature_flag_id is None
        assert event.variant_id is None
        assert event.event_metadata == {"plan": "pro"}
        # created_at defaults to "now" when timestamp is not set.
        parsed = datetime.fromisoformat(event.created_at)
        assert (datetime.now(timezone.utc) - parsed).total_seconds() < 30

    def test_build_event_accepts_feature_flag_id_without_experiment_id(
        self, make_feature_flag
    ):
        flag = make_feature_flag(name="Build Event Flag")
        event = EventService.build_event(
            {
                "user_id": "flag-user",
                "event_name": "flag_eval",
                "feature_flag_id": str(flag.id),
            }
        )

        assert event.feature_flag_id == flag.id
        assert event.experiment_id is None

    def test_build_event_metadata_key_priority(self, make_experiment):
        """event_metadata > properties > metadata (see _METADATA_KEYS)."""
        experiment = make_experiment(name="Build Event Metadata Priority")

        # event_metadata wins over properties/metadata when all three set.
        event = EventService.build_event(
            {
                "user_id": "u1",
                "experiment_id": str(experiment.id),
                "event_metadata": {"source": "event_metadata"},
                "properties": {"source": "properties"},
                "metadata": {"source": "metadata"},
            }
        )
        assert event.event_metadata == {"source": "event_metadata"}

        # properties wins over metadata when event_metadata absent.
        event = EventService.build_event(
            {
                "user_id": "u1",
                "experiment_id": str(experiment.id),
                "properties": {"source": "properties"},
                "metadata": {"source": "metadata"},
            }
        )
        assert event.event_metadata == {"source": "properties"}

        # metadata used when it's the only one present.
        event = EventService.build_event(
            {
                "user_id": "u1",
                "experiment_id": str(experiment.id),
                "metadata": {"source": "metadata"},
            }
        )
        assert event.event_metadata == {"source": "metadata"}

        # None of the three present -> event_metadata is None.
        event = EventService.build_event(
            {"user_id": "u1", "experiment_id": str(experiment.id)}
        )
        assert event.event_metadata is None

    def test_build_event_timestamp_key_priority_and_default(self, make_experiment):
        """timestamp > created_at (see _TIMESTAMP_KEYS); defaults to now."""
        experiment = make_experiment(name="Build Event Timestamp Priority")

        event = EventService.build_event(
            {
                "user_id": "u1",
                "experiment_id": str(experiment.id),
                "timestamp": "2020-01-01T00:00:00+00:00",
                "created_at": "2019-01-01T00:00:00+00:00",
            }
        )
        assert event.created_at == "2020-01-01T00:00:00+00:00"

        event = EventService.build_event(
            {
                "user_id": "u1",
                "experiment_id": str(experiment.id),
                "created_at": "2019-01-01T00:00:00+00:00",
            }
        )
        assert event.created_at == "2019-01-01T00:00:00+00:00"

        # A naive datetime gets UTC tzinfo attached.
        naive = datetime(2021, 6, 1, 12, 0, 0)
        event = EventService.build_event(
            {
                "user_id": "u1",
                "experiment_id": str(experiment.id),
                "timestamp": naive,
            }
        )
        assert event.created_at == "2021-06-01T12:00:00+00:00"

    def test_build_event_coerces_string_ids_to_uuid(self, make_experiment, make_variant):
        experiment = make_experiment(name="Build Event UUID Coercion")
        variant = make_variant(experiment=experiment)

        event = EventService.build_event(
            {
                "user_id": "u1",
                "experiment_id": str(experiment.id),
                "variant_id": str(variant.id),
            }
        )

        assert isinstance(event.experiment_id, uuid.UUID)
        assert event.experiment_id == experiment.id
        assert isinstance(event.variant_id, uuid.UUID)
        assert event.variant_id == variant.id

    def test_build_event_empty_string_id_treated_as_none(self, make_feature_flag):
        flag = make_feature_flag(name="Build Event Empty String Id")
        event = EventService.build_event(
            {
                "user_id": "u1",
                "experiment_id": "",
                "feature_flag_id": str(flag.id),
            }
        )
        assert event.experiment_id is None
        assert event.feature_flag_id == flag.id

    def test_build_event_raises_without_user_id(self, make_experiment):
        experiment = make_experiment(name="Build Event Missing User")
        with pytest.raises(ValueError, match="user_id"):
            EventService.build_event({"experiment_id": str(experiment.id)})

    def test_build_event_raises_without_experiment_or_feature_flag_id(self):
        with pytest.raises(
            ValueError, match="experiment_id or feature_flag_id"
        ):
            EventService.build_event({"user_id": "u1"})

    def test_build_event_raises_for_invalid_uuid(self):
        with pytest.raises(ValueError):
            EventService.build_event(
                {"user_id": "u1", "experiment_id": "not-a-real-uuid"}
            )


# ---------------------------------------------------------------------------
# track_event
# ---------------------------------------------------------------------------


class TestTrackEvent:
    def test_track_event_persists_and_returns_event_from_event_create(
        self, db_session, make_experiment
    ):
        experiment = make_experiment(name="Track Event Coverage")
        user_id = _uid("track-user")
        event_data = EventCreate(
            user_id=user_id,
            event_name="button_click",
            event_type="click",
            experiment_id=str(experiment.id),
            value=2.5,
            properties={"button": "buy-now"},
        )

        service = EventService(db_session)
        event = service.track_event(event_data)

        assert isinstance(event, Event)
        assert event.id is not None
        assert event.event_type == "click"
        assert event.event_name == "button_click"
        assert event.user_id == user_id
        assert event.experiment_id == experiment.id
        assert event.value == 2.5
        assert event.event_metadata == {"button": "buy-now"}

        fetched = db_session.query(Event).filter(Event.id == event.id).one()
        assert fetched.user_id == user_id

    def test_track_event_accepts_plain_dict(self, db_session, make_experiment):
        experiment = make_experiment(name="Track Event Dict Input")
        user_id = _uid("track-dict-user")

        service = EventService(db_session)
        event = service.track_event(
            {
                "user_id": user_id,
                "event_name": "page_view",
                "event_type": "page_view",
                "experiment_id": str(experiment.id),
                "created_at": _iso_now(),
            }
        )

        assert event.id is not None
        assert event.user_id == user_id
        assert (
            db_session.query(Event).filter(Event.user_id == user_id).count() == 1
        )

    def test_track_event_rolls_back_and_raises_on_invalid_data(
        self, db_session, make_experiment
    ):
        experiment = make_experiment(name="Track Event Rollback Coverage")
        tag_user = _uid("rollback-user")

        service = EventService(db_session)
        with pytest.raises(ValueError):
            # Missing user_id -> build_event raises before any DB write.
            service.track_event({"experiment_id": str(experiment.id)})

        # Session must remain usable after the rollback, and nothing from
        # this failed call should have been persisted.
        assert (
            db_session.query(Event).filter(Event.user_id == tag_user).count() == 0
        )
        # A subsequent, valid call on the same session/service must still work.
        event = service.track_event(
            {
                "user_id": tag_user,
                "event_name": "recovered",
                "experiment_id": str(experiment.id),
            }
        )
        assert event.id is not None


# ---------------------------------------------------------------------------
# track_conversion
# ---------------------------------------------------------------------------


class TestTrackConversion:
    def test_track_conversion_without_experiment_or_feature_flag_id_raises(
        self, db_session
    ):
        service = EventService(db_session)
        with pytest.raises(ValueError, match="experiment_id or feature_flag_id"):
            service.track_conversion(user_id="u1", event_name="signup")

    def test_track_conversion_with_feature_flag_id_only(
        self, db_session, make_feature_flag
    ):
        flag = make_feature_flag(name="Conversion Flag Only")
        user_id = _uid("conv-flag-user")

        service = EventService(db_session)
        event = service.track_conversion(
            user_id=user_id, event_name="signup", feature_flag_id=str(flag.id)
        )

        assert event.event_type == EventType.CONVERSION.value
        assert event.event_name == "signup"
        assert event.feature_flag_id == flag.id
        assert event.experiment_id is None
        assert event.variant_id is None
        assert event.event_metadata == {}

    def test_track_conversion_without_assignment_leaves_variant_id_none(
        self, db_session, make_experiment
    ):
        experiment = make_experiment(name="Conversion No Assignment")
        user_id = _uid("no-assignment-user")

        service = EventService(db_session)
        event = service.track_conversion(
            user_id=user_id, event_name="signup", experiment_id=str(experiment.id)
        )

        assert event.experiment_id == experiment.id
        assert event.variant_id is None

    def test_track_conversion_with_assignment_captures_variant(
        self, db_session, make_experiment, make_variant, make_assignment
    ):
        experiment = make_experiment(name="Conversion Assignment Lookup")
        variant = make_variant(
            experiment=experiment,
            name="Treatment",
            is_control=False,
            traffic_allocation=100,
        )
        user_id = _uid("conv-user")
        make_assignment(experiment=experiment, variant=variant, user_id=user_id)

        service = EventService(db_session)
        event = service.track_conversion(
            user_id=user_id,
            event_name="purchase",
            experiment_id=str(experiment.id),
            properties={"amount": 9.99},
            value=9.99,
        )

        assert event.variant_id == variant.id
        assert event.event_metadata == {"amount": 9.99}
        assert event.value == 9.99

        fetched = db_session.query(Event).filter(Event.id == event.id).one()
        assert fetched.variant_id == variant.id


# ---------------------------------------------------------------------------
# track_exposure
# ---------------------------------------------------------------------------


class TestTrackExposure:
    def test_track_exposure_persists_event_with_expected_fields(
        self, db_session, make_experiment, make_variant
    ):
        experiment = make_experiment(name="Exposure Coverage")
        variant = make_variant(experiment=experiment)
        user_id = _uid("exposure-user")

        service = EventService(db_session)
        event = service.track_exposure(
            user_id=user_id,
            experiment_id=str(experiment.id),
            variant_id=str(variant.id),
            properties={"source": "web"},
        )

        assert event.event_type == EventType.EXPOSURE.value
        assert event.event_name == "variant_exposure"
        assert event.user_id == user_id
        assert event.experiment_id == experiment.id
        assert event.variant_id == variant.id
        assert event.event_metadata == {"source": "web"}

    def test_track_exposure_without_properties_defaults_to_empty_dict(
        self, db_session, make_experiment, make_variant
    ):
        experiment = make_experiment(name="Exposure Default Properties")
        variant = make_variant(experiment=experiment)
        user_id = _uid("exposure-default-user")

        service = EventService(db_session)
        event = service.track_exposure(
            user_id=user_id,
            experiment_id=str(experiment.id),
            variant_id=str(variant.id),
        )

        assert event.event_metadata == {}


# ---------------------------------------------------------------------------
# track_events_batch
# ---------------------------------------------------------------------------


class TestTrackEventsBatch:
    def test_track_events_batch_persists_all_events(self, db_session, make_experiment):
        experiment = make_experiment(name="Batch Coverage")
        user_id = _uid("batch-user")
        payloads = [
            EventCreate(
                user_id=user_id,
                event_name=f"page_view_{i}",
                event_type="page_view",
                experiment_id=str(experiment.id),
            )
            for i in range(3)
        ]

        service = EventService(db_session)
        events = service.track_events_batch(payloads)

        assert len(events) == 3
        for event, i in zip(events, range(3)):
            assert event.id is not None
            assert event.event_name == f"page_view_{i}"

        persisted_count = (
            db_session.query(Event).filter(Event.user_id == user_id).count()
        )
        assert persisted_count == 3

    def test_track_events_batch_is_all_or_nothing(self, db_session, make_experiment):
        """One invalid item aborts the whole batch (build_event runs for all
        items before add_all()/commit()), so nothing should be persisted even
        though valid payloads preceded the bad one."""
        experiment = make_experiment(name="Batch Failure Coverage")
        user_id = _uid("batch-fail")
        good_payload = EventCreate(
            user_id=user_id, event_name="click", experiment_id=str(experiment.id)
        )
        bad_payload = {"user_id": user_id, "event_name": "bad"}  # no ids at all

        service = EventService(db_session)
        with pytest.raises(ValueError):
            service.track_events_batch([good_payload, bad_payload])

        assert (
            db_session.query(Event).filter(Event.user_id == user_id).count() == 0
        )

    def test_track_events_batch_empty_list_returns_empty_list(self, db_session):
        service = EventService(db_session)
        assert service.track_events_batch([]) == []


# ---------------------------------------------------------------------------
# get_events_by_experiment
# ---------------------------------------------------------------------------


class TestGetEventsByExperiment:
    def test_returns_events_newest_first_with_expected_shape(
        self, db_session, make_experiment, make_event
    ):
        experiment = make_experiment(name="Get Events Shape And Order")
        user_id = _uid("shape-user")
        t1 = "2024-01-01T00:00:00+00:00"
        t2 = "2024-01-02T00:00:00+00:00"
        t3 = "2024-01-03T00:00:00+00:00"

        make_event(
            experiment_id=experiment.id,
            user_id=user_id,
            event_type="conversion",
            event_name="purchase",
            value=5.0,
            created_at=t1,
        )
        make_event(
            experiment_id=experiment.id,
            user_id=user_id,
            event_type="conversion",
            event_name="purchase",
            value=6.0,
            created_at=t3,
        )
        make_event(
            experiment_id=experiment.id,
            user_id=user_id,
            event_type="conversion",
            event_name="purchase",
            value=7.0,
            created_at=t2,
        )

        service = EventService(db_session)
        results = service.get_events_by_experiment(experiment.id)

        assert [r["timestamp"] for r in results] == [t3, t2, t1]

        first = results[0]
        assert set(
            [
                "id",
                "user_id",
                "event_type",
                "event_name",
                "experiment_id",
                "feature_flag_id",
                "variant_id",
                "value",
                "timestamp",
                "properties",
            ]
        ).issubset(first.keys())
        assert first["experiment_id"] == str(experiment.id)
        assert first["user_id"] == user_id
        assert first["value"] == 6.0

    def test_filters_by_event_type_and_event_name(
        self, db_session, make_experiment, make_event
    ):
        experiment = make_experiment(name="Get Events Filter Type Name")
        make_event(
            experiment_id=experiment.id,
            user_id="u1",
            event_type="conversion",
            event_name="purchase",
        )
        make_event(
            experiment_id=experiment.id,
            user_id="u2",
            event_type="exposure",
            event_name="variant_exposure",
        )

        service = EventService(db_session)

        by_type = service.get_events_by_experiment(experiment.id, event_type="exposure")
        assert len(by_type) == 1
        assert by_type[0]["event_type"] == "exposure"

        by_name = service.get_events_by_experiment(experiment.id, event_name="purchase")
        assert len(by_name) == 1
        assert by_name[0]["event_name"] == "purchase"

    def test_filters_by_start_and_end_date(self, db_session, make_experiment, make_event):
        experiment = make_experiment(name="Get Events Filter Dates")
        make_event(
            experiment_id=experiment.id,
            user_id="u1",
            created_at="2024-01-01T00:00:00+00:00",
        )
        make_event(
            experiment_id=experiment.id,
            user_id="u2",
            created_at="2024-02-01T00:00:00+00:00",
        )
        make_event(
            experiment_id=experiment.id,
            user_id="u3",
            created_at="2024-03-01T00:00:00+00:00",
        )

        service = EventService(db_session)

        after_feb = service.get_events_by_experiment(
            experiment.id, start_date="2024-02-01T00:00:00+00:00"
        )
        assert {r["user_id"] for r in after_feb} == {"u2", "u3"}

        before_feb = service.get_events_by_experiment(
            experiment.id, end_date="2024-02-01T00:00:00+00:00"
        )
        assert {r["user_id"] for r in before_feb} == {"u1", "u2"}

        # start_date/end_date also accept datetime objects, not just strings.
        narrow = service.get_events_by_experiment(
            experiment.id,
            start_date=datetime(2024, 1, 15, tzinfo=timezone.utc),
            end_date=datetime(2024, 2, 15, tzinfo=timezone.utc),
        )
        assert {r["user_id"] for r in narrow} == {"u2"}

    def test_pagination_skip_and_limit(self, db_session, make_experiment, make_event):
        experiment = make_experiment(name="Get Events Pagination")
        for i in range(5):
            make_event(
                experiment_id=experiment.id,
                user_id=f"page-user-{i}",
                created_at=f"2024-01-0{i + 1}T00:00:00+00:00",
            )

        service = EventService(db_session)
        page = service.get_events_by_experiment(experiment.id, skip=2, limit=2)

        # Newest first: day5, day4, day3, day2, day1 -> skip 2, take 2 -> day3, day2
        assert [r["user_id"] for r in page] == ["page-user-2", "page-user-1"]

    def test_accepts_str_or_uuid_experiment_id(self, db_session, make_experiment, make_event):
        experiment = make_experiment(name="Get Events Str Or UUID")
        make_event(experiment_id=experiment.id, user_id="u1")

        service = EventService(db_session)
        assert len(service.get_events_by_experiment(str(experiment.id))) == 1
        assert len(service.get_events_by_experiment(experiment.id)) == 1

    def test_returns_empty_list_for_experiment_with_no_events(
        self, db_session, make_experiment
    ):
        experiment = make_experiment(name="Get Events No Events")
        service = EventService(db_session)
        assert service.get_events_by_experiment(experiment.id) == []


# ---------------------------------------------------------------------------
# count_events_by_experiment
# ---------------------------------------------------------------------------


class TestCountEventsByExperiment:
    def test_counts_with_type_and_name_filters(self, db_session, make_experiment, make_event):
        experiment = make_experiment(name="Count Events Coverage")
        other_experiment = make_experiment(name="Count Events Other")

        make_event(
            experiment_id=experiment.id,
            event_type="conversion",
            event_name="purchase",
            user_id="c1",
        )
        make_event(
            experiment_id=experiment.id,
            event_type="conversion",
            event_name="purchase",
            user_id="c2",
        )
        make_event(
            experiment_id=experiment.id,
            event_type="exposure",
            event_name="variant_exposure",
            user_id="c3",
        )
        make_event(
            experiment_id=other_experiment.id,
            event_type="conversion",
            event_name="purchase",
            user_id="c4",
        )

        service = EventService(db_session)

        assert service.count_events_by_experiment(experiment.id) == 3
        assert service.count_events_by_experiment(str(experiment.id)) == 3
        assert (
            service.count_events_by_experiment(experiment.id, event_type="conversion")
            == 2
        )
        assert (
            service.count_events_by_experiment(
                experiment.id, event_name="variant_exposure"
            )
            == 1
        )
        assert (
            service.count_events_by_experiment(
                experiment.id, event_type="conversion", event_name="variant_exposure"
            )
            == 0
        )
        assert service.count_events_by_experiment(other_experiment.id) == 1

    def test_counts_with_date_filters(self, db_session, make_experiment, make_event):
        experiment = make_experiment(name="Count Events Date Filters")
        make_event(
            experiment_id=experiment.id,
            user_id="d1",
            created_at="2024-01-01T00:00:00+00:00",
        )
        make_event(
            experiment_id=experiment.id,
            user_id="d2",
            created_at="2024-03-01T00:00:00+00:00",
        )

        service = EventService(db_session)

        assert (
            service.count_events_by_experiment(
                experiment.id, start_date="2024-02-01T00:00:00+00:00"
            )
            == 1
        )
        assert (
            service.count_events_by_experiment(
                experiment.id, end_date="2024-02-01T00:00:00+00:00"
            )
            == 1
        )
        assert (
            service.count_events_by_experiment(
                experiment.id,
                start_date="2024-01-01T00:00:00+00:00",
                end_date="2024-12-31T00:00:00+00:00",
            )
            == 2
        )

    def test_returns_zero_for_no_matches(self, db_session, make_experiment):
        experiment = make_experiment(name="Count Events Zero Coverage")
        service = EventService(db_session)
        result = service.count_events_by_experiment(experiment.id)
        assert result == 0
        assert result is not None


# ---------------------------------------------------------------------------
# get_events_by_user
# ---------------------------------------------------------------------------


class TestGetEventsByUser:
    def test_returns_events_for_user_newest_first(self, db_session, make_event):
        user_id = _uid("user-events")
        make_event(user_id=user_id, created_at="2024-01-01T00:00:00+00:00")
        make_event(user_id=user_id, created_at="2024-03-01T00:00:00+00:00")
        make_event(user_id=user_id, created_at="2024-02-01T00:00:00+00:00")

        service = EventService(db_session)
        results = service.get_events_by_user(user_id)

        assert [r["timestamp"] for r in results] == [
            "2024-03-01T00:00:00+00:00",
            "2024-02-01T00:00:00+00:00",
            "2024-01-01T00:00:00+00:00",
        ]
        assert all(r["user_id"] == user_id for r in results)

    def test_filters_by_experiment_id(self, db_session, make_experiment, make_event):
        experiment = make_experiment(name="Get Events By User Experiment Filter")
        other_experiment = make_experiment(name="Get Events By User Other Experiment")
        user_id = _uid("user-exp-filter")

        make_event(user_id=user_id, experiment_id=experiment.id)
        make_event(user_id=user_id, experiment_id=other_experiment.id)
        make_event(user_id=user_id)  # no experiment at all

        service = EventService(db_session)

        results = service.get_events_by_user(user_id, experiment_id=experiment.id)
        assert len(results) == 1
        assert results[0]["experiment_id"] == str(experiment.id)

        results_str = service.get_events_by_user(
            user_id, experiment_id=str(experiment.id)
        )
        assert len(results_str) == 1

        assert len(service.get_events_by_user(user_id)) == 3

    def test_filters_by_event_type_and_event_name(self, db_session, make_event):
        user_id = _uid("user-type-name-filter")
        make_event(user_id=user_id, event_type="conversion", event_name="purchase")
        make_event(user_id=user_id, event_type="exposure", event_name="variant_exposure")

        service = EventService(db_session)

        by_type = service.get_events_by_user(user_id, event_type="exposure")
        assert len(by_type) == 1
        assert by_type[0]["event_type"] == "exposure"

        by_name = service.get_events_by_user(user_id, event_name="purchase")
        assert len(by_name) == 1
        assert by_name[0]["event_name"] == "purchase"

    def test_pagination_skip_and_limit(self, db_session, make_event):
        user_id = _uid("user-pagination")
        for i in range(4):
            make_event(user_id=user_id, created_at=f"2024-01-0{i + 1}T00:00:00+00:00")

        service = EventService(db_session)
        page = service.get_events_by_user(user_id, skip=1, limit=2)
        # Newest first: day4, day3, day2, day1 -> skip 1, take 2 -> day3, day2
        assert [r["timestamp"] for r in page] == [
            "2024-01-03T00:00:00+00:00",
            "2024-01-02T00:00:00+00:00",
        ]

    def test_returns_empty_list_for_user_with_no_events(self, db_session):
        service = EventService(db_session)
        assert service.get_events_by_user(_uid("never-seen-user")) == []


# ---------------------------------------------------------------------------
# delete_events_by_experiment
# ---------------------------------------------------------------------------


class TestDeleteEventsByExperiment:
    def test_delete_events_by_experiment_removes_only_matching_events(
        self, db_session, make_experiment, make_event
    ):
        experiment = make_experiment(name="Delete Events Coverage A")
        other_experiment = make_experiment(name="Delete Events Coverage B")

        for i in range(3):
            make_event(experiment_id=experiment.id, user_id=f"del-user-{i}")
        make_event(experiment_id=other_experiment.id, user_id="keep-me")
        make_event(user_id="keep-me-too")  # no experiment_id at all

        service = EventService(db_session)
        deleted_count = service.delete_events_by_experiment(experiment.id)

        assert deleted_count == 3
        assert (
            db_session.query(Event)
            .filter(Event.experiment_id == experiment.id)
            .count()
            == 0
        )
        assert (
            db_session.query(Event)
            .filter(Event.experiment_id == other_experiment.id)
            .count()
            == 1
        )
        assert (
            db_session.query(Event)
            .filter(Event.user_id == "keep-me-too", Event.experiment_id.is_(None))
            .count()
            == 1
        )

    def test_delete_events_by_experiment_with_no_matches_returns_zero(
        self, db_session, make_experiment
    ):
        experiment = make_experiment(name="Delete Events No Matches")
        service = EventService(db_session)
        assert service.delete_events_by_experiment(experiment.id) == 0

    def test_delete_events_by_experiment_accepts_str_uuid(
        self, db_session, make_experiment, make_event
    ):
        experiment = make_experiment(name="Delete Events Str UUID")
        make_event(experiment_id=experiment.id, user_id="str-uuid-user")

        service = EventService(db_session)
        deleted_count = service.delete_events_by_experiment(str(experiment.id))
        assert deleted_count == 1


# ---------------------------------------------------------------------------
# purge_old_events
# ---------------------------------------------------------------------------


class TestPurgeOldEvents:
    def test_purge_old_events_deletes_only_events_older_than_cutoff(
        self, db_session, make_event
    ):
        fixed_now = datetime(2026, 6, 1, tzinfo=timezone.utc)
        with freeze_time(fixed_now):
            old_user = _uid("purge-old")
            recent_user = _uid("purge-recent")

            old_created_at = (fixed_now - timedelta(days=120)).isoformat()
            recent_created_at = (fixed_now - timedelta(days=10)).isoformat()

            make_event(user_id=old_user, created_at=old_created_at)
            make_event(user_id=old_user, created_at=old_created_at)
            make_event(user_id=recent_user, created_at=recent_created_at)

            # purge_old_events has no per-experiment/user scope: it purges
            # globally. Measure the "old" row count dynamically right before
            # purging (rather than asserting a hardcoded global number) so
            # this test doesn't depend on what other tests/rows exist.
            cutoff = (fixed_now - timedelta(days=90)).isoformat()
            expected_deleted = (
                db_session.query(func.count(Event.id))
                .filter(Event.created_at < cutoff)
                .scalar()
                or 0
            )
            assert expected_deleted >= 2  # at least our own 2 old rows

            service = EventService(db_session)
            deleted_count = service.purge_old_events(days_to_keep=90)

            assert deleted_count == expected_deleted

            # Our own tagged rows: old ones gone, recent one remains.
            assert (
                db_session.query(Event).filter(Event.user_id == old_user).count() == 0
            )
            assert (
                db_session.query(Event).filter(Event.user_id == recent_user).count()
                == 1
            )

    def test_purge_old_events_respects_custom_days_to_keep(self, db_session, make_event):
        fixed_now = datetime(2026, 6, 1, tzinfo=timezone.utc)
        with freeze_time(fixed_now):
            user_id = _uid("purge-custom")
            # 30 days old: survives a 90-day retention but not a 10-day one.
            make_event(
                user_id=user_id,
                created_at=(fixed_now - timedelta(days=30)).isoformat(),
            )

            service = EventService(db_session)

            # Still within a 90-day retention window -> survives.
            service.purge_old_events(days_to_keep=90)
            assert (
                db_session.query(Event).filter(Event.user_id == user_id).count() == 1
            )

            # A stricter 10-day retention window purges it.
            deleted = service.purge_old_events(days_to_keep=10)

            assert deleted >= 1
            assert (
                db_session.query(Event).filter(Event.user_id == user_id).count() == 0
            )

    def test_purge_old_events_uses_default_90_days_when_not_specified(
        self, db_session, make_event
    ):
        fixed_now = datetime(2026, 6, 1, tzinfo=timezone.utc)
        with freeze_time(fixed_now):
            user_id = _uid("purge-default")
            make_event(
                user_id=user_id,
                created_at=(fixed_now - timedelta(days=200)).isoformat(),
            )

            service = EventService(db_session)
            deleted_count = service.purge_old_events()  # default days_to_keep=90

            assert deleted_count >= 1
            assert (
                db_session.query(Event).filter(Event.user_id == user_id).count() == 0
            )
