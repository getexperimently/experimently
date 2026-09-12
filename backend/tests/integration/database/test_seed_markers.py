"""
DB-backed tests for ``backend/scripts/seed_markers.py`` and the ``SeedMarker``
model behind it.

The marker table must be part of ``Base.metadata`` (so ``create_all`` and
Alembic autogenerate know about it) and the script must read and write the
very same table in an explicit schema.
"""

import pytest
from sqlalchemy import inspect

from backend.app.models.base import Base
from backend.app.models.seed_marker import SeedMarker
from backend.scripts import seed_markers

SCHEMA = "test_experimentation"


@pytest.fixture
def engine(test_db):
    seed_markers.clear(test_db, "demo", SCHEMA)
    seed_markers.clear(test_db, "shoplab", SCHEMA)
    yield test_db
    seed_markers.clear(test_db, "demo", SCHEMA)
    seed_markers.clear(test_db, "shoplab", SCHEMA)


class TestSeedMarkerModel:
    def test_table_is_on_base_metadata(self):
        names = {t.name for t in Base.metadata.tables.values()}
        assert SeedMarker.__tablename__ in names

    def test_script_table_matches_model(self):
        table = seed_markers.seed_markers_table("any_schema")
        assert table.schema == "any_schema"
        assert [c.name for c in table.columns] == [
            c.name for c in SeedMarker.__table__.columns
        ]
        assert [c.name for c in table.primary_key.columns] == ["name"]

    def test_create_all_created_it_in_the_test_schema(self, test_db):
        assert inspect(test_db).has_table(SeedMarker.__tablename__, schema=SCHEMA)


class TestSeedMarkerScript:
    def test_mark_and_query(self, engine):
        assert seed_markers.is_applied(engine, "demo", SCHEMA) is False
        seed_markers.mark_applied(engine, "demo", source="test", schema=SCHEMA)
        assert seed_markers.is_applied(engine, "demo", SCHEMA) is True
        applied = dict(seed_markers.applied(engine, SCHEMA))
        assert "demo" in applied

    def test_mark_is_idempotent(self, engine):
        seed_markers.mark_applied(engine, "shoplab", schema=SCHEMA)
        seed_markers.mark_applied(engine, "shoplab", schema=SCHEMA)
        assert [n for n, _ in seed_markers.applied(engine, SCHEMA)].count(
            "shoplab"
        ) == 1

    def test_clear(self, engine):
        seed_markers.mark_applied(engine, "demo", schema=SCHEMA)
        seed_markers.clear(engine, "demo", SCHEMA)
        assert seed_markers.is_applied(engine, "demo", SCHEMA) is False

    def test_ensure_table_is_safe_when_table_exists(self, engine):
        # create_all already made it; ensure_table must not fail or duplicate.
        seed_markers.ensure_table(engine, SCHEMA)
        seed_markers.ensure_table(engine, SCHEMA)
        assert inspect(engine).has_table(SeedMarker.__tablename__, schema=SCHEMA)
