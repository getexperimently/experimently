"""The one place a PostgreSQL URL is assembled from its parts (#146).

Every URL builder in the backend -- both settings validators in
``core/config.py``, the fallback in ``db/session.py``, ``db/bootstrap.py`` and
``db/migrations/env.py`` -- used to interpolate ``POSTGRES_PASSWORD`` into the
URL as-is.  A password is arbitrary text and a URL is not: ``#`` starts a
fragment, ``?`` a query, ``/`` a path, ``:`` and ``@`` split the authority, and
``%`` starts an escape.  Aurora's generated master password excludes only
``" @ / \\`` (``enhanced_database_stack.py``), so it routinely contains the
rest, and a password with ``#`` in it made the settings refuse to build at all
("invalid port number").

Each component is percent-encoded with ``urllib.parse.quote(..., safe="")``.
Not ``quote_plus``: SQLAlchemy's ``make_url`` decodes ``+`` literally, so a
space would come back as ``+`` and authentication would fail.  Not
``str(sqlalchemy.engine.URL)``: that renders the password as ``***``.

``DATABASE_URI`` supplied whole is used as given, so it must already be
encoded; ``docs/deployment/secrets-management.md`` says so.

The result still has to be escaped once more for alembic, whose config is a
``configparser`` that treats ``%`` as interpolation -- ``migrations/env.py``
doubles it there and nowhere else.
"""

from __future__ import annotations

from urllib.parse import quote


def postgres_url(
    *,
    user: str,
    password: str,
    host: str,
    port: int | str,
    database: str,
    scheme: str = "postgresql",
) -> str:
    """``scheme://user:password@host:port/database`` with user and password encoded."""
    return (
        f"{scheme}://{quote(str(user), safe='')}:{quote(str(password), safe='')}"
        f"@{host}:{port}/{database}"
    )
