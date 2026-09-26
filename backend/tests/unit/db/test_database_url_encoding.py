"""A database password survives every URL builder intact (#146).

Aurora's generated master password excludes only ``" @ / \\``, so it routinely
contains ``#``, ``?``, ``%``, ``:`` and ``,``; a human-chosen one can also hold
``+`` and spaces.  Every URL builder in the backend interpolated the password
raw, so a ``#`` made the settings refuse to build ("invalid port number") and
the others silently changed the credentials the driver sent.

Each check below takes **the string actually handed to** ``create_engine`` (or,
for alembic, the value alembic reads back from its configparser) and asserts
``make_url(...).password`` is the original password, at every site:

1. ``Settings.DATABASE_URI`` (``assemble_database_connection``);
2. ``Settings.SQLALCHEMY_DATABASE_URI``'s own builder
   (``assemble_db_connection``, when there is no ``DATABASE_URI``);
3. ``db/session.py``, both through the settings and through its fallback;
4. ``db/bootstrap.database_url()``;
5. ``db/migrations/env.py``, through a real ``alembic current`` whose engine
   factory is replaced by a recorder.

(``ProdSettings.get_db_url``, the sixth, had no callers and was deleted.)

The session and alembic checks run in a subprocess because both build their URL
at import time.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import PostgresDsn, TypeAdapter
from sqlalchemy.engine import make_url

from backend.app.core import config
from backend.app.db import bootstrap

pytestmark = [pytest.mark.unit, pytest.mark.regression]

REPO_ROOT = Path(__file__).resolve().parents[4]
ALEMBIC_INI = REPO_ROOT / "backend" / "app" / "db" / "alembic.ini"

#: One character per password, then the lot together, then passwords that
#: already look like escapes -- a builder that decodes twice fails those.
PASSWORDS = [
    "a#b",
    "a,b",
    "a?b",
    "a%b",
    "a:b",
    "a+b",
    "a b",
    "p#,?%:+ w/@x",
    "%23literal",
    "100%%",
]


def _password(url: str) -> str | None:
    return make_url(url).password


def _clean_env(**extra: str) -> dict[str, str]:
    """The subprocess environment: no inherited POSTGRES_* or DATABASE_URI."""
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("POSTGRES_", "DATABASE_URI", "SQLALCHEMY_"))
    }
    env.update(
        PYTHONPATH=str(REPO_ROOT),
        APP_ENV="test",
        TESTING="true",
        POSTGRES_SERVER="db.example.internal",
        POSTGRES_USER="postgres",
        POSTGRES_PORT="5432",
        POSTGRES_DB="experimentation",
        **extra,
    )
    return env


def _run(script: str) -> dict[str, str | None]:
    """Run *script*, which prints one JSON object of password -> decoded."""
    result = subprocess.run(
        [sys.executable, "-c", script, json.dumps(PASSWORDS)],
        cwd=REPO_ROOT,
        env=_clean_env(),
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stderr[-3000:]
    return json.loads(result.stdout.strip().splitlines()[-1])


def _assert_all_round_trip(decoded: dict[str, str | None], site: str) -> None:
    wrong = {pw: got for pw, got in decoded.items() if got != pw}
    assert not wrong, f"{site} changed these passwords (sent -> received): {wrong}"
    assert set(decoded) == set(PASSWORDS), decoded


@pytest.mark.parametrize("password", PASSWORDS)
def test_settings_database_uri(password: str):
    """Sites 1 and 3a: the URL session.py hands create_engine by default."""
    settings = config.TestSettings(
        POSTGRES_PASSWORD=password,
        POSTGRES_SERVER="db.example.internal",
        DATABASE_URI=None,
        SQLALCHEMY_DATABASE_URI=None,
    )
    assert _password(str(settings.DATABASE_URI)) == password
    assert _password(str(settings.SQLALCHEMY_DATABASE_URI)) == password


@pytest.mark.parametrize("password", PASSWORDS)
def test_settings_sqlalchemy_uri_built_from_components(password: str):
    """Site 2: SQLALCHEMY_DATABASE_URI's own builder, with no DATABASE_URI.

    Validated into the field's type afterwards, as pydantic would, because the
    field holds a PostgresDsn and ``str()`` of that is what reaches the engine.
    """
    info = SimpleNamespace(
        data={
            "POSTGRES_USER": "postgres",
            "POSTGRES_PASSWORD": password,
            "POSTGRES_SERVER": "db.example.internal",
            "POSTGRES_PORT": "5432",
            "POSTGRES_DB": "experimentation",
        }
    )
    built = config.Settings.assemble_db_connection(None, info)
    as_field = TypeAdapter(PostgresDsn).validate_python(built)
    assert _password(str(as_field)) == password


@pytest.mark.parametrize("password", PASSWORDS)
def test_bootstrap_database_url(password: str, monkeypatch):
    """Site 4: what bootstrap passes to create_engine."""
    monkeypatch.setenv("POSTGRES_PASSWORD", password)
    monkeypatch.setenv("POSTGRES_SERVER", "db.example.internal")
    assert _password(bootstrap.database_url()) == password


_SESSION_SCRIPT = """
import importlib, json, sys
import sqlalchemy
from sqlalchemy.engine import make_url

FALLBACK = {fallback}
seen = {{}}
current = None

def recording_create_engine(url, *args, **kwargs):
    seen[current] = make_url(url).password
    raise RuntimeError("recorded")

sqlalchemy.create_engine = recording_create_engine

import backend.app.core.config as config

for current in json.loads(sys.argv[1]):
    config.settings = config.TestSettings(POSTGRES_PASSWORD=current)
    if FALLBACK:
        config.settings.DATABASE_URI = None
        config.settings.SQLALCHEMY_DATABASE_URI = None
    sys.modules.pop("backend.app.db.session", None)
    try:
        importlib.import_module("backend.app.db.session")
    except RuntimeError as exc:
        assert str(exc) == "recorded", exc
print(json.dumps(seen))
"""


@pytest.mark.parametrize("fallback", [False, True], ids=["settings", "fallback"])
def test_session_create_engine(fallback: bool):
    """Site 3: db/session.py, through the settings and through its fallback."""
    decoded = _run(_SESSION_SCRIPT.format(fallback=fallback))
    _assert_all_round_trip(
        decoded, f"db/session.py ({'fallback' if fallback else 'settings'})"
    )


_ALEMBIC_SCRIPT = """
import json, os, sys
import sqlalchemy
from sqlalchemy.engine import make_url
from alembic.config import main

seen = {{}}
current = None

class Recorded(Exception):
    pass

def recording_engine_from_config(section, prefix="sqlalchemy.", **kwargs):
    seen[current] = make_url(section[prefix + "url"]).password
    raise Recorded()

sqlalchemy.engine_from_config = recording_engine_from_config

for current in json.loads(sys.argv[1]):
    os.environ["POSTGRES_PASSWORD"] = current
    try:
        main(argv=["-c", {ini!r}, "current"])
    except Recorded:
        pass
print(json.dumps(seen))
"""


def test_alembic_env_reads_back_the_password():
    """Site 5: migrations/env.py, through alembic's configparser.

    The URL is percent-encoded and then has every ``%`` doubled, because
    configparser treats ``%`` as interpolation; what alembic reads back with
    ``get_section`` -- the dict ``engine_from_config`` receives -- must decode
    to the original password.
    """
    decoded = _run(_ALEMBIC_SCRIPT.format(ini=str(ALEMBIC_INI)))
    _assert_all_round_trip(decoded, "migrations/env.py")
