"""
Seed markers: which idempotent seeds (``SEED=demo,shoplab,...``) have been
applied to this database.

The container entrypoint (``backend/docker-entrypoint.sh``) consults this
table through ``backend/scripts/seed_markers.py`` so a restart never re-seeds.
The model lives on ``Base.metadata`` so the bootstrap's ``create_all`` creates
it on a fresh database and ``alembic revision --autogenerate`` never proposes
dropping it.
"""

from sqlalchemy import Column, DateTime, String

from backend.app.models.base import Base


class SeedMarker(Base):
    __tablename__ = "seed_markers"

    name = Column(String(64), primary_key=True)
    applied_at = Column(DateTime(timezone=True), nullable=False)
    source = Column(String(255), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<SeedMarker {self.name} applied_at={self.applied_at}>"
